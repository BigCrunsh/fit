"""Feature extraction for the marathon-durability model — pure pandas/numpy, no PyMC.

Pulls qualifying efforts and daily training load from fitness.db, computes the
*incoming* chronic load (the same primitive ACWR uses as its chronic denominator —
a trailing mean of daily load, strictly BEFORE each effort so the effort's own load
never inflates its fitness), and the model covariates:

    x = log(distance / D_REF)    durability — D_REF = the GOAL distance (goal-adaptive)
    c = (chronic − ref) / scale  fitness state, from the shared chronic-load primitive
    h = (avg_hr − LTHR) / 5      effort / maximality, per 5 bpm vs LTHR

`D_REF` is the goal race distance (`get_target_race`), so the model re-centres when the
target changes (marathon → half). LTHR comes from the calibration anchor. There is NO
new CTL/ATL EWMA — fitness state reuses one shared chronic-load concept (Decision 6).
See design.md.
"""

from __future__ import annotations

import sqlite3

import numpy as np
import pandas as pd

MARATHON_KM = 42.195         # fallback D_REF when no goal race is set
CHRONIC_REF = 50.0           # fitness centre (chronic-load units) — cosmetic, like D_REF
CHRONIC_SCALE = 10.0         # c is per-10 chronic-load units
CHRONIC_WINDOW_DAYS = 28     # trailing window for chronic load (≈ ACWR's 4 ISO weeks)
H_DIV = 5.0                  # bpm per effort unit

# Continuous, intensity-bearing efforts only. Intervals excluded (their distance_km
# includes recoveries). run_type is NOT used for maximality — the h (HR) covariate is.
EFFORT_SQL = """
SELECT id, date, run_type, distance_km, duration_min, avg_hr
FROM activities
WHERE type IN ('running', 'track_running')
  AND ( run_type = 'race'
        OR (run_type IN ('tempo', 'progression') AND effort_class IN ('Hard', 'Very Hard')) )
  AND distance_km > 0 AND duration_min > 0 AND avg_hr > 0
ORDER BY date
"""

# Daily training load = sum over all activities that day (cross-training included).
DAILY_LOAD_SQL = """
SELECT date, SUM(training_load) AS load
FROM activities
WHERE training_load IS NOT NULL
GROUP BY date
ORDER BY date
"""


def _chronic_before(jd: int, day_ord: np.ndarray, day_load: np.ndarray, window: int) -> float:
    """Mean daily load over the trailing `window` days strictly BEFORE ordinal day jd.

    This is the chronic-load primitive ACWR uses as its denominator, evaluated
    point-in-time (incoming fitness, not inflated by the effort's own load). Averaged
    over the window length so a sparse-but-recent block doesn't read as low fitness.
    """
    if day_ord.size == 0:
        return 0.0
    mask = (day_ord < jd) & (day_ord >= jd - window)
    if not mask.any():
        return 0.0
    return float(np.sum(day_load[mask]) / window)


def _lthr(conn: sqlite3.Connection) -> float:
    """LTHR from the calibration anchor. Raises when absent (forecast must degrade)."""
    from fit.calibration import get_calibration_anchor  # local: keep features import-light

    anchor = get_calibration_anchor(conn, "lthr")
    if not anchor or not anchor.get("value"):
        raise ValueError("no LTHR calibration anchor — marathon forecast cannot run")
    return float(anchor["value"])


def _goal_distance(conn: sqlite3.Connection) -> float:
    """The goal race distance (D_REF), so x re-centres with the target. Falls back to
    the marathon when no target race is registered."""
    from fit.goals import get_target_race  # local

    target = get_target_race(conn)
    d = target.get("distance_km") if target else None
    return float(d) if d and d > 0 else MARATHON_KM


def extract_efforts(conn: sqlite3.Connection) -> pd.DataFrame:
    """Qualifying efforts with incoming chronic load and model covariates x/c/h/logt.

    Efforts with no prior load history (chronic load 0) are dropped. The returned frame
    carries ``.attrs``: ``d_max`` (longest observed distance — the extrapolation
    boundary), ``lthr``, and ``goal`` (the D_REF used).

    Raises ValueError when there is no LTHR anchor, no qualifying efforts, or no effort
    with prior history — all of which the caller treats as "degrade to the anchor
    headline" (Decision 7), never a crash.
    """
    eff = pd.read_sql_query(EFFORT_SQL, conn, parse_dates=["date"])
    if eff.empty:
        raise ValueError("no qualifying efforts for the marathon model")

    lthr = _lthr(conn)
    goal = _goal_distance(conn)
    dl = pd.read_sql_query(DAILY_LOAD_SQL, conn, parse_dates=["date"])
    day_ord = dl["date"].map(pd.Timestamp.toordinal).to_numpy() if not dl.empty else np.array([])
    day_load = dl["load"].fillna(0.0).to_numpy() if not dl.empty else np.array([])

    jd = eff["date"].map(pd.Timestamp.toordinal).to_numpy()
    eff["chronic"] = [_chronic_before(j, day_ord, day_load, CHRONIC_WINDOW_DAYS) for j in jd]

    eff = eff[eff["chronic"] > 0].copy()  # drop efforts with no prior history
    if eff.empty:
        raise ValueError("no efforts with prior training history")

    eff["x"] = np.log(eff["distance_km"]) - np.log(goal)
    eff["c"] = (eff["chronic"] - CHRONIC_REF) / CHRONIC_SCALE
    eff["h"] = (eff["avg_hr"] - lthr) / H_DIV
    eff["logt"] = np.log(eff["duration_min"])

    eff = eff.reset_index(drop=True)
    eff.attrs["d_max"] = float(eff["distance_km"].max())
    eff.attrs["lthr"] = lthr
    eff.attrs["goal"] = goal
    return eff
