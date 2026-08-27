"""Personal wellness baselines and deviation states.

Single source of truth for the wellness early-warning signals: the alert rules
(fire AND auto-dismiss), the coaching context health line, and the dashboard
respiration chart all read `wellness_snapshot` — same numbers everywhere, no
fire-then-instant-dismiss drift.

Baseline semantics: rolling median of the trailing `wellness_baseline_days`
observations that PRECEDE the evaluated days (an ongoing illness must not
absorb into its own baseline), requiring `MIN_BASELINE_OBS` observations.
Missing days break consecutive-deviation streaks (a gap means "unknown", not
"still elevated"). The sleep- and waking-respiration series are never mixed:
each deviates only against its own baseline.
"""

import sqlite3
from datetime import date, timedelta
from statistics import median

MIN_BASELINE_OBS = 14
HRV_LOW_RATIO = 0.85          # ratio fallback when Garmin's hrv_status is missing
RESP_CONSECUTIVE_NIGHTS = 2   # nights at/above baseline+delta → respiration_elevated
RHR_CONSECUTIVE_DAYS = 3      # days at/above baseline+delta → rhr_elevated
READINESS_CLIFF = 50          # readiness below this joins the recovery-cliff compound
_MAX_STREAK_EVAL = 14         # longest streak we evaluate (longer = baseline has shifted)


def _series(conn: sqlite3.Connection, column: str) -> list[tuple[date, float]]:
    """(date, value) observations for a daily_health column, newest first."""
    rows = conn.execute(
        f"SELECT date, {column} AS v FROM daily_health "
        f"WHERE {column} IS NOT NULL ORDER BY date DESC LIMIT 400"
    ).fetchall()
    return [(date.fromisoformat(r["date"]), float(r["v"])) for r in rows]


def _baseline_before(series: list[tuple[date, float]], day: date, window_days: int) -> float | None:
    """Median of observations in the window strictly before `day`; None if too few."""
    lo = day - timedelta(days=window_days)
    vals = [v for d, v in series if lo <= d < day]
    return median(vals) if len(vals) >= MIN_BASELINE_OBS else None


def _consecutive_elevated(series: list[tuple[date, float]], delta: float,
                          window_days: int) -> tuple[int, float | None]:
    """Largest n where the latest n calendar-consecutive observations all read
    ≥ baseline + delta, with the baseline computed strictly before the OLDEST
    evaluated day (so the episode never pollutes its own baseline).

    Returns (streak, baseline) — baseline is the streak's baseline, or the
    latest-day baseline when there is no streak (for reporting).
    """
    if not series:
        return 0, None
    by_date = dict(series)
    latest = series[0][0]
    best_n, best_baseline = 0, None
    for n in range(1, _MAX_STREAK_EVAL + 1):
        days = [latest - timedelta(days=i) for i in range(n)]
        if days[-1] not in by_date:
            break  # calendar gap — longer streaks are impossible too
        b = _baseline_before(series, days[-1], window_days)
        if b is None:
            continue  # window too thin at this depth; a deeper one may not be
        if all(by_date[d] >= b + delta for d in days):
            best_n, best_baseline = n, b
    if best_n == 0:
        best_baseline = _baseline_before(series, latest, window_days)
    return best_n, best_baseline


def _choose_respiration_series(conn: sqlite3.Connection,
                               window_days: int) -> tuple[str | None, list[tuple[date, float]]]:
    """Sleep series when it can carry a baseline, else waking; else whichever has data."""
    sleep = _series(conn, "avg_sleep_respiration")
    if sleep and _baseline_before(sleep, sleep[0][0], window_days) is not None:
        return "sleep", sleep
    waking = _series(conn, "avg_respiration")
    if waking and _baseline_before(waking, waking[0][0], window_days) is not None:
        return "waking", waking
    if sleep:
        return "sleep", sleep
    if waking:
        return "waking", waking
    return None, []


def _avg_last_7(series: list[tuple[date, float]]) -> float | None:
    """Average over the 7 calendar days ending at the series' latest observation."""
    if not series:
        return None
    lo = series[0][0] - timedelta(days=6)
    vals = [v for d, v in series if d >= lo]
    return round(sum(vals) / len(vals), 1)


def wellness_snapshot(conn: sqlite3.Connection, config: dict | None = None) -> dict:
    """Baselines, latest values, and deviation states for the wellness signals."""
    coaching = (config or {}).get("coaching", {})
    resp_delta = float(coaching.get("respiration_delta_brpm", 2.0))
    rhr_delta = float(coaching.get("rhr_delta_bpm", 5))
    window = int(coaching.get("wellness_baseline_days", 28))

    # Respiration — sleep preferred, waking fallback (D3)
    resp_label, resp_series = _choose_respiration_series(conn, window)
    resp_n, resp_baseline = _consecutive_elevated(resp_series, resp_delta, window)
    respiration = {
        "series": resp_label,
        "baseline": resp_baseline,
        "latest": resp_series[0][1] if resp_series else None,
        "avg_7d": _avg_last_7(resp_series),
        "delta": resp_delta,
        "consecutive_elevated": resp_n if resp_baseline is not None else 0,
        "elevated": resp_baseline is not None and resp_n >= RESP_CONSECUTIVE_NIGHTS,
    }

    # RHR
    rhr_series = _series(conn, "resting_heart_rate")
    rhr_n, rhr_baseline = _consecutive_elevated(rhr_series, rhr_delta, window)
    rhr = {
        "baseline": rhr_baseline,
        "latest": rhr_series[0][1] if rhr_series else None,
        "delta": rhr_delta,
        "consecutive_elevated": rhr_n if rhr_baseline is not None else 0,
        "elevated": rhr_baseline is not None and rhr_n >= RHR_CONSECUTIVE_DAYS,
    }

    # HRV — baseline for the ratio fallback
    hrv_series = _series(conn, "hrv_last_night")
    hrv_baseline = _baseline_before(hrv_series, hrv_series[0][0], window) if hrv_series else None
    hrv = {
        "baseline": hrv_baseline,
        "latest": hrv_series[0][1] if hrv_series else None,
    }

    # Recovery cliff — same-day compound on the latest day with an RHR reading.
    # All three read the SAME row: elevated RHR + low HRV + low readiness together.
    cliff = False
    components: dict = {}
    anchor = conn.execute(
        "SELECT date, resting_heart_rate, hrv_last_night, hrv_status, training_readiness "
        "FROM daily_health WHERE resting_heart_rate IS NOT NULL ORDER BY date DESC LIMIT 1"
    ).fetchone()
    if anchor is not None:
        anchor_day = date.fromisoformat(anchor["date"])
        anchor_baseline = _baseline_before(rhr_series, anchor_day, window)
        rhr_up = (anchor_baseline is not None
                  and anchor["resting_heart_rate"] >= anchor_baseline + rhr_delta)
        status = (anchor["hrv_status"] or "").upper() or None
        if status is not None:
            hrv_low = status == "LOW"
        else:
            anchor_hrv_baseline = _baseline_before(hrv_series, anchor_day, window)
            hrv_low = (anchor["hrv_last_night"] is not None
                       and anchor_hrv_baseline is not None
                       and anchor["hrv_last_night"] < HRV_LOW_RATIO * anchor_hrv_baseline)
        readiness = anchor["training_readiness"]
        cliff = bool(rhr_up and hrv_low and readiness is not None and readiness < READINESS_CLIFF)
        components = {
            "date": anchor["date"],
            "rhr": anchor["resting_heart_rate"],
            "rhr_baseline": anchor_baseline,
            "hrv_status": status,
            "hrv": anchor["hrv_last_night"],
            "readiness": readiness,
        }

    return {
        "respiration": respiration,
        "rhr": rhr,
        "hrv": hrv,
        "recovery_cliff": cliff,
        "recovery_cliff_components": components,
    }


# ── Readiness breakdown ──
#
# Garmin's Training Readiness is its number, not ours (`fit/garmin.py` copies the
# score verbatim). A low score says nothing about WHY on its own: the same 1/100
# can mean "still inside a hard session's recovery window" or "HRV has collapsed",
# and those call for opposite responses. Garmin returns a 0-100 rating per input,
# so name the driver from the data instead of letting readers assume fatigue.
#
# Single source of the answer: the `readiness_gate` alert message and the coaching
# context both read this. Never re-derive a driver inline.

# (column, human name) — the inputs Garmin rates, in the order Garmin presents them.
_READINESS_FACTORS = (
    ("readiness_recovery_factor_pct", "recovery time"),
    ("readiness_sleep_factor_pct", "sleep"),
    ("readiness_hrv_factor_pct", "HRV"),
    ("readiness_acwr_factor_pct", "load ratio"),
    ("readiness_sleep_history_pct", "sleep history"),
    ("readiness_stress_history_pct", "stress history"),
)
FACTOR_HEALTHY_PCT = 65   # at or above this, a factor is not what's holding the score down


def readiness_breakdown(conn: sqlite3.Connection) -> dict:
    """Why the latest readiness score reads what it reads.

    Returns the score, the lowest-rated input (`driver`), the inputs that are
    fine, any recovery-time debt still counting down, and a one-line `summary`.
    `driver` and `summary` are None when the factors were never stored (every row
    synced before migration 020) — an unexplained score is reported as such
    rather than attributed to a guessed cause.
    """
    row = conn.execute(
        "SELECT date, training_readiness, readiness_level, readiness_feedback, "
        "       readiness_recovery_time_min, "
        + ", ".join(c for c, _ in _READINESS_FACTORS)
        + " FROM daily_health WHERE training_readiness IS NOT NULL "
          "ORDER BY date DESC LIMIT 1"
    ).fetchone()
    if row is None:
        return {"date": None, "score": None, "level": None, "driver": None,
                "driver_pct": None, "healthy": [], "recovery_time_h": None,
                "feedback": None, "summary": None}

    rated = [(name, row[col]) for col, name in _READINESS_FACTORS if row[col] is not None]
    debt_min = row["readiness_recovery_time_min"]
    debt_h = round(debt_min / 60) if debt_min else None

    driver, driver_pct = (min(rated, key=lambda f: f[1]) if rated else (None, None))
    healthy = [name for name, pct in rated if pct >= FACTOR_HEALTHY_PCT]

    summary = None
    if driver is not None:
        summary = f"lowest-rated input is {driver} ({driver_pct}/100)"
        # Recovery-time debt is the actionable context even when it is not the
        # lowest factor: it says the score sits inside a hard session's shadow
        # and will climb back on its own clock.
        if debt_h:
            summary += (f" — {debt_h}h still counting down" if driver == "recovery time"
                        else f"; {debt_h}h of recovery time still counting down")
        if healthy:
            summary += f". Rated fine: {', '.join(healthy)}"

    return {
        "date": row["date"],
        "score": row["training_readiness"],
        "level": row["readiness_level"],
        "driver": driver,
        "driver_pct": driver_pct,
        "healthy": healthy,
        "recovery_time_h": debt_h,
        "feedback": row["readiness_feedback"],
        "summary": summary,
    }
