"""Feature extraction for the marathon-durability model — pure pandas/numpy, no PyMC.

Pulls qualifying efforts and daily training load from fitness.db, computes the
*incoming* CTL/ATL (loads strictly BEFORE each effort day, so the effort's own load
never inflates its fitness), and the model covariates:

    x = log(distance / 42.195)   durability (0 at the marathon)
    c = (CTL - 50) / 10          fitness state, per 10 CTL, centred at 50
    h = (avg_hr - LTHR) / 5      effort / maximality, per 5 bpm vs LTHR

LTHR comes from the calibration anchor (`standardize-calibration-anchors`), never a
hardcoded constant. See design.md (Decision 8 / Data & features).
"""

from __future__ import annotations

import sqlite3

import numpy as np
import pandas as pd

D_REF = 42.195      # marathon km; x = 0 at the marathon
CTL_REF = 50.0      # fitness centre (CTL units)
H_DIV = 5.0         # bpm per effort unit
TAU_CTL = 42.0      # chronic load time-constant (days) — fitness
TAU_ATL = 7.0       # acute load time-constant (days) — fatigue

# Continuous, intensity-bearing efforts only. Intervals are excluded (their
# distance_km includes recoveries, so they are not one continuous effort). The
# run_type label is NOT used to assume maximality — the h (HR) covariate carries it,
# so a submaximal race and a hard tempo sit on the same frontier.
EFFORT_SQL = """
SELECT id, date, run_type, distance_km, duration_min, avg_hr
FROM activities
WHERE type IN ('running', 'track_running')
  AND ( run_type = 'race'
        OR (run_type IN ('tempo', 'progression') AND effort_class IN ('Hard', 'Very Hard')) )
  AND distance_km > 0 AND duration_min > 0 AND avg_hr > 0
ORDER BY date
"""

# Daily training load = sum over all activities that day (cross-training included;
# matches the prototype and TrainingPeaks CTL/ATL). No SQLite math functions needed.
DAILY_LOAD_SQL = """
SELECT date, SUM(training_load) AS load
FROM activities
WHERE training_load IS NOT NULL
GROUP BY date
ORDER BY date
"""


def _ewma_strictly_before(jd: int, day_ord: np.ndarray, day_load: np.ndarray, tau: float) -> float:
    """Closed-form EWMA of daily load at ordinal day ``jd`` using days strictly < jd.

    Matches the TrainingPeaks CTL/ATL recursion to ~1%: sum(load·exp(-Δt/τ))/τ.
    """
    if day_ord.size == 0:
        return 0.0
    mask = day_ord < jd
    if not mask.any():
        return 0.0
    return float(np.sum(day_load[mask] * np.exp(-(jd - day_ord[mask]) / tau)) / tau)


def _lthr(conn: sqlite3.Connection) -> float:
    """LTHR from the calibration anchor. Raises when absent (forecast must degrade)."""
    from fit.calibration import get_calibration_anchor  # local: keep features import-light

    anchor = get_calibration_anchor(conn, "lthr")
    if not anchor or not anchor.get("value"):
        raise ValueError("no LTHR calibration anchor — marathon forecast cannot run")
    return float(anchor["value"])


def extract_efforts(conn: sqlite3.Connection) -> pd.DataFrame:
    """Qualifying efforts with incoming CTL/ATL and model covariates x/c/h/logt.

    Efforts with no prior load history (undefined CTL) are dropped. The returned
    frame carries ``.attrs['d_max']`` (longest observed distance — the extrapolation
    boundary) and ``.attrs['lthr']`` (the LTHR used).

    Raises ValueError when there is no LTHR anchor, no qualifying efforts, or no
    effort with prior history — all of which the caller treats as "degrade to the
    anchor headline" (Decision 7), never a crash.
    """
    eff = pd.read_sql_query(EFFORT_SQL, conn, parse_dates=["date"])
    if eff.empty:
        raise ValueError("no qualifying efforts for the marathon model")

    lthr = _lthr(conn)
    dl = pd.read_sql_query(DAILY_LOAD_SQL, conn, parse_dates=["date"])
    day_ord = dl["date"].map(pd.Timestamp.toordinal).to_numpy() if not dl.empty else np.array([])
    day_load = dl["load"].fillna(0.0).to_numpy() if not dl.empty else np.array([])

    jd = eff["date"].map(pd.Timestamp.toordinal).to_numpy()
    eff["ctl"] = [_ewma_strictly_before(j, day_ord, day_load, TAU_CTL) for j in jd]
    eff["atl"] = [_ewma_strictly_before(j, day_ord, day_load, TAU_ATL) for j in jd]

    eff = eff[eff["ctl"] > 0].copy()  # drop efforts with no prior history (CTL undefined)
    if eff.empty:
        raise ValueError("no efforts with prior training history")

    eff["x"] = np.log(eff["distance_km"]) - np.log(D_REF)
    eff["c"] = (eff["ctl"] - CTL_REF) / 10.0
    eff["h"] = (eff["avg_hr"] - lthr) / H_DIV
    eff["logt"] = np.log(eff["duration_min"])

    eff = eff.reset_index(drop=True)
    eff.attrs["d_max"] = float(eff["distance_km"].max())
    eff.attrs["lthr"] = lthr
    return eff
