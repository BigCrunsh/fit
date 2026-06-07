"""Training-Load context — the shared load primitives.

Bounded context (DDD review): everything derived from `training_load` lives here so
load concepts cannot silently fork. The CHRONIC-LOAD primitive below is the single
fitness-state concept platform-wide (marathon-durability-model Decision 6): ACWR's
chronic denominator and the forecast's fitness covariate must both resolve to it (F2).

Incremental context split: functions move here from `fit/analysis.py` with re-export
shims left behind; new load code lands here directly. Still in `fit/analysis.py`
(queued): `compute_weekly_agg`, `compute_rolling_week`, `_compute_acwr` (per-week,
coupled to weekly_agg writes), monotony/strain, sRPE.

TODO(load-unification): ACWR's chronic denominator (avg of prior 4 ISO weeks from
weekly_agg) and `chronic_load` here (trailing 28-day mean of daily load) are the same
concept computed two ways. Unifying ACWR onto `chronic_load` is a deliberate,
slightly behavior-changing step — do it consciously, with its own tests.
"""

from __future__ import annotations

import sqlite3
from datetime import date, timedelta

import numpy as np

CHRONIC_WINDOW_DAYS = 28  # ≈ ACWR's "prior 4 ISO weeks" chronic baseline

# Daily training load = sum over all activities that day (cross-training included).
DAILY_LOAD_SQL = """
SELECT date, SUM(training_load) AS load
FROM activities
WHERE training_load IS NOT NULL
GROUP BY date
ORDER BY date
"""


def chronic_load_before(jd: int, day_ord: np.ndarray, day_load: np.ndarray,
                        window: int = CHRONIC_WINDOW_DAYS) -> float:
    """Mean daily load over the trailing `window` days strictly BEFORE ordinal day jd.

    The chronic-load primitive, point-in-time: incoming fitness, never inflated by the
    day's own load. Averaged over the window length so a sparse-but-recent block does
    not read as low fitness. Pure function — callers pre-fetch the daily-load arrays
    (via DAILY_LOAD_SQL) when evaluating many dates.
    """
    if day_ord.size == 0:
        return 0.0
    mask = (day_ord < jd) & (day_ord >= jd - window)
    if not mask.any():
        return 0.0
    return float(np.sum(day_load[mask]) / window)


def chronic_load(conn: sqlite3.Connection, asof: date | None = None,
                 window: int = CHRONIC_WINDOW_DAYS) -> float:
    """Point-in-time chronic load for a single date (convenience over the pure form)."""
    import pandas as pd

    dl = pd.read_sql_query(DAILY_LOAD_SQL, conn, parse_dates=["date"])
    if dl.empty:
        return 0.0
    day_ord = dl["date"].map(pd.Timestamp.toordinal).to_numpy()
    day_load = dl["load"].fillna(0.0).to_numpy()
    ref = (asof or date.today()).toordinal()
    return chronic_load_before(ref, day_ord, day_load, window)


def compute_rolling_acwr(conn: sqlite3.Connection, end_date: date | None = None,
                         config: dict | None = None) -> float | None:
    """Compute ACWR using rolling 7-day acute load vs ISO-week chronic baseline.

    Acute load: from compute_rolling_week() (last 7 days).
    Chronic load: average of prior 4 ISO weeks from weekly_agg.
    (Moved from fit/analysis.py — Training Load context. See the module TODO on
    unifying the chronic denominator with `chronic_load`.)
    """
    from fit.analysis import compute_rolling_week  # local: avoid import cycle

    if end_date is None:
        end_date = date.today()

    rolling = compute_rolling_week(conn, end_date, config=config)
    acute_load = rolling["total_load"]

    # Chronic: prior 4 ISO weeks from weekly_agg
    prev_loads = []
    ref_date = end_date - timedelta(days=7)
    for _ in range(4):
        ref_iso = ref_date.isocalendar()
        pw_str = f"{ref_iso[0]}-W{ref_iso[1]:02d}"
        row = conn.execute(
            "SELECT total_load FROM weekly_agg WHERE week = ?", (pw_str,)
        ).fetchone()
        if row and row["total_load"] is not None:
            prev_loads.append(row["total_load"])
        ref_date -= timedelta(weeks=1)

    if len(prev_loads) < 3:
        return None

    chronic = sum(prev_loads) / len(prev_loads)
    if chronic <= 0:
        return None

    acwr = round(acute_load / chronic, 2)
    if acwr > 3.0:
        return None

    return acwr
