#!/usr/bin/env python3
"""
marathon_model.py  -- fitness-aware durability model for marathon prediction.

Reads efforts and training load straight from fitness.db, fits a Bayesian
log-time regression (durability exponent + fitness state + effort proxy),
prints predictions with credible intervals, and writes a 2-panel chart.

Usage:
    FIT_DB=/path/to/fitness.db python marathon_model.py
    # defaults to ./fitness.db

Deps: pymc>=5, arviz, numpy, pandas, matplotlib, scipy(optional). sqlite3 stdlib.
"""
import os, sqlite3, numpy as np, pandas as pd

# ----------------------------------------------------------------------------
# Config / constants  (all centring choices live here)
# ----------------------------------------------------------------------------
DB_PATH   = os.environ.get("FIT_DB", "fitness.db")
TODAY     = pd.Timestamp(os.environ.get("FIT_TODAY", "2026-06-02"))
D_REF     = 42.195      # marathon km -> x = 0 at marathon
CTL_REF   = 50.0        # fitness centre (CTL units); alpha is marathon @ this CTL
LTHR      = 172.0       # lactate-threshold HR (athlete config); effort proxy centre
H_DIV     = 5.0         # bpm per effort unit
H_MARA    = -1.0        # maximal *marathon* effort ~ avg HR 167 -> (167-172)/5
TAU_CTL   = 42.0        # chronic load time-constant (days)
TAU_ATL   = 7.0         # acute load time-constant (days)

# Continuous, intensity-bearing efforts only. Intervals excluded (not continuous).
# NB: the run_type label is NOT used to assume maximality; the HR proxy does that.
EFFORT_SQL = """
SELECT id, date, run_type, distance_km, duration_min, avg_hr
FROM activities
WHERE type IN ('running','track_running')
  AND ( run_type = 'race'
        OR (run_type IN ('tempo','progression') AND effort_class IN ('Hard','Very Hard')) )
ORDER BY date
"""
DAILY_LOAD_SQL = """
SELECT date, SUM(training_load) AS load
FROM activities WHERE training_load IS NOT NULL
GROUP BY date ORDER BY date
"""

# ----------------------------------------------------------------------------
# Load + feature engineering
# ----------------------------------------------------------------------------
def load_data(db=DB_PATH):
    con = sqlite3.connect(db)
    eff = pd.read_sql(EFFORT_SQL, con, parse_dates=["date"])
    dl  = pd.read_sql(DAILY_LOAD_SQL, con, parse_dates=["date"])
    con.close()
    return eff, dl

def ctl_at(jd, day_ord, day_load, tau, strict):
    """Closed-form EWMA: sum load*exp(-dt/tau)/tau over days (< jd) or (<= jd)."""
    mask = (day_ord < jd) if strict else (day_ord <= jd)
    return float(np.sum(day_load[mask] * np.exp(-(jd - day_ord[mask]) / tau)) / tau)

def add_features(eff, dl):
    day_ord  = dl["date"].map(pd.Timestamp.toordinal).to_numpy()
    day_load = dl["load"].to_numpy()
    jd = eff["date"].map(pd.Timestamp.toordinal).to_numpy()
    # incoming fitness/fatigue: strictly BEFORE the effort day (excludes self-load)
    eff["ctl"] = [ctl_at(j, day_ord, day_load, TAU_CTL, strict=True)  for j in jd]
    eff["atl"] = [ctl_at(j, day_ord, day_load, TAU_ATL, strict=True)  for j in jd]
    eff = eff[eff["ctl"] > 0].copy()                 # drop efforts with no prior history
    eff["x"]    = np.log(eff.distance_km) - np.log(D_REF)
    eff["c"]    = (eff.ctl - CTL_REF) / 10.0
    eff["h"]    = (eff.avg_hr - LTHR) / H_DIV
    eff["logt"] = np.log(eff.duration_min)
    return eff, (day_ord, day_load)

# ----------------------------------------------------------------------------
# Model
# ----------------------------------------------------------------------------
def fit_model(eff, draws=3000, tune=2000, seed=7):
    import pymc as pm
    x, c, h, logt = eff.x.values, eff.c.values, eff.h.values, eff.logt.values
    with pm.Model():
        alpha  = pm.Normal("alpha",  np.log(240), 0.4)   # log marathon @ x=0, CTL=50, HR=LTHR
        beta_d = pm.Normal("beta_d", 1.06, 0.05)         # durability exponent (Riegel prior)
        phi    = pm.Normal("phi",    0.0,  0.05)         # fitness: log-time per +10 CTL
        kappa  = pm.Normal("kappa",  0.0,  0.05)         # effort: log-time per +5 bpm over LTHR
        delta  = pm.Normal("delta",  0.0,  0.03)         # durability x fitness interaction
        mu = alpha + beta_d*x + phi*c + kappa*h + delta*(x*c)
        sigma  = pm.HalfNormal("sigma", 0.06)
        nu     = pm.Gamma("nu", 2, 0.1)                  # Student-T -> robust to bad-day races
        pm.StudentT("y", nu=nu, mu=mu, sigma=sigma, observed=logt)
        idata = pm.sample(draws, tune=tune, target_accept=0.95,
                          chains=4, cores=1, random_seed=seed, progressbar=False)
    return idata

# ----------------------------------------------------------------------------
# Prediction helpers
# ----------------------------------------------------------------------------
def flat(idata):
    P = idata.posterior
    return {k: P[k].values.flatten() for k in ["alpha","beta_d","phi","kappa","delta","sigma","nu"]}

def predict_minutes(s, ctl, avg_hr, dist_km=D_REF):
    """Posterior draws of predicted time (min) at a distance/fitness/effort."""
    x = np.log(dist_km) - np.log(D_REF)
    c = (ctl - CTL_REF) / 10.0
    h = (avg_hr - LTHR) / H_DIV
    return np.exp(s["alpha"] + s["beta_d"]*x + s["phi"]*c + s["kappa"]*h + s["delta"]*(x*c))

def fmt(m):
    H=int(m//60); M=int(m%60); S=int(round((m-int(m))*60))
    if S==60: M+=1; S=0
    return f"{H}:{M:02d}:{S:02d}"

def report(idata, eff):
    import arviz as az
    print(f"N efforts = {len(eff)} | dist {eff.distance_km.min()}-{eff.distance_km.max()} km "
          f"| HR {eff.avg_hr.min()}-{eff.avg_hr.max()} | CTL {eff.ctl.min():.1f}-{eff.ctl.max():.1f}")
    print(az.summary(idata, var_names=["alpha","beta_d","phi","kappa","delta","sigma","nu"]).to_string())
    s = flat(idata)
    MARA_HR = LTHR + H_MARA*H_DIV   # 167
    print(f"\nMarathon @ maximal effort (avg HR {MARA_HR:.0f}):")
    for lbl, ctl in [("current ~50",50),("built 60",60),("peak ~70",70),("detrained 25",25)]:
        t = predict_minutes(s, ctl, MARA_HR)
        print(f"  CTL {lbl:11s}: {fmt(np.median(t))}  90% {fmt(np.percentile(t,5))}..{fmt(np.percentile(t,95))}"
              f"  P(sub4)={np.mean(t<240):.2f}")
    b=s["beta_d"]; ph=s["phi"]; ka=s["kappa"]; de=s["delta"]
    print(f"\nbeta_d (durability exp): {np.median(b):.3f} [{np.percentile(b,5):.3f},{np.percentile(b,95):.3f}]")
    print(f"phi (per +10 CTL): {np.median(ph):+.4f} [{np.percentile(ph,5):+.4f},{np.percentile(ph,95):+.4f}]"
          f"  ~{100*(np.exp(np.median(ph))-1):+.1f}%/10CTL")
    print(f"kappa (per +5 bpm): {np.median(ka):+.4f} [{np.percentile(ka,5):+.4f},{np.percentile(ka,95):+.4f}]")
    print(f"delta (durab x fit): {np.median(de):+.4f} [{np.percentile(de,5):+.4f},{np.percentile(de,95):+.4f}]"
          f"  P(<0)={np.mean(de<0):.2f}")
    return s

# ----------------------------------------------------------------------------
# Chart (2 panels: durability power law + fitness-tracking marathon trend)
# ----------------------------------------------------------------------------
def chart(idata, eff, daily, out="marathon_model.png"):
    import matplotlib; matplotlib.use("Agg")
    import matplotlib.pyplot as plt, matplotlib.dates as mdates
    from matplotlib.cm import ScalarMappable
    from matplotlib.colors import Normalize
    s = flat(idata); day_ord, day_load = daily
    ma,mb,mph,mka,mde = (np.median(s[k]) for k in ["alpha","beta_d","phi","kappa","delta"])
    MARA_HR = LTHR + H_MARA*H_DIV
    cmap="RdYlBu_r"; norm=Normalize(vmin=3, vmax=21)   # blue=short, yellow=mid, red=long
    x,c,h,dd = eff.x.values, eff.c.values, eff.h.values, eff.distance_km.values

    fig,(axA,axB)=plt.subplots(1,2,figsize=(14,6),gridspec_kw={"width_ratios":[1,1.25]})

    # Panel A: normalise out fitness+effort, leaving distance dependence
    t_norm=np.exp(eff.logt.values - mph*c - mka*(h-H_MARA) - mde*(x*c))
    axA.scatter(dd,t_norm,c=dd,cmap=cmap,norm=norm,s=70,edgecolor="k",lw=.6,zorder=5)
    dgrid=np.linspace(2.5,43,200); xg=np.log(dgrid)-np.log(D_REF)
    draws=np.exp(np.add.outer(xg,np.zeros_like(s["beta_d"]))*s["beta_d"]+s["alpha"]+s["kappa"]*H_MARA)
    axA.plot(dgrid,np.exp(ma+mb*xg+mka*H_MARA),color="#333",lw=2,label=f"power law, exp={mb:.3f}")
    axA.fill_between(dgrid,np.percentile(draws,5,1),np.percentile(draws,95,1),color="#888",alpha=.2)
    axA.axvline(D_REF,color="#C44E52",ls=":",lw=1.2)
    axA.set_xscale("log"); axA.set_yscale("log")
    axA.set_xticks([3,5,10,21,42]); axA.set_xticklabels(["3","5","10","21","42"])
    axA.set_yticks([15,25,50,100,240]); axA.set_yticklabels(["15","25","50","100","240"])
    axA.set_xlabel("distance (km, log)"); axA.set_ylabel("time @ CTL50 + max effort (min, log)")
    axA.set_title("A. Durability: one power law once fitness & effort removed")
    axA.legend(fontsize=8); axA.grid(alpha=.25,which="both")

    # Panel B: marathon-equiv tracking CTL over time
    gd=pd.date_range("2024-08-01",TODAY,freq="SMS")           # ~twice monthly
    gctl=np.array([ctl_at(d.toordinal(),day_ord,day_load,TAU_CTL,strict=False) for d in gd])
    cc=(gctl-CTL_REF)/10.0
    line=np.exp(np.add.outer(cc,np.zeros_like(s["alpha"]))*s["phi"]+s["alpha"]+s["kappa"]*H_MARA)
    axB.plot(gd,np.median(line,1)/60,color="#4C72B0",lw=2,label="marathon @ max effort, tracking CTL")
    axB.fill_between(gd,np.percentile(line,5,1)/60,np.percentile(line,95,1)/60,color="#4C72B0",alpha=.15)
    mar_pt=np.exp(eff.logt.values - mb*x - mka*(h-H_MARA) - mde*(x*c))
    axB.scatter(eff.date,mar_pt/60,c=dd,cmap=cmap,norm=norm,s=70,edgecolor="k",lw=.6,zorder=5)
    ct=(ctl_at(TODAY.toordinal(),day_ord,day_load,TAU_CTL,strict=False)-CTL_REF)/10.0
    tt=np.exp(s["alpha"]+s["phi"]*ct+s["kappa"]*H_MARA)
    axB.errorbar(TODAY,np.median(tt)/60,
        yerr=[[(np.median(tt)-np.percentile(tt,5))/60],[(np.percentile(tt,95)-np.median(tt))/60]],
        fmt="D",color="#222",ms=9,capsize=4,zorder=6,label=f"today: {fmt(np.median(tt))[:4]}")
    axB.axhline(4.0,color="grey",ls="--",lw=1); axB.text(gd[1],4.01,"sub-4:00",color="grey",fontsize=9)
    axB.yaxis.set_major_formatter(plt.FuncFormatter(lambda v,_:f"{int(v)}:{int(round((v-int(v))*60)):02d}"))
    axB.set_ylabel("maximal marathon-equivalent (h:mm)"); axB.set_xlabel("date")
    axB.xaxis.set_major_formatter(mdates.DateFormatter("%b %y"))
    axB.set_title("B. Marathon-equivalent tracks training")
    axB.legend(fontsize=8); axB.grid(alpha=.25)

    cb=fig.colorbar(ScalarMappable(norm=norm,cmap=cmap),ax=[axA,axB],pad=.01,fraction=.025)
    cb.set_label("distance (km)  [blue short / yellow mid / red long]")
    fig.savefig(out,dpi=140,bbox_inches="tight")
    print(f"wrote {out}")

# ----------------------------------------------------------------------------
if __name__ == "__main__":
    eff, dl = load_data()
    eff, daily = add_features(eff, dl)
    idata = fit_model(eff)
    report(idata, eff)
    chart(idata, eff, daily)
    try:
        idata.to_netcdf("marathon_posterior.nc")
    except Exception as e:
        print("posterior save skipped:", e)
