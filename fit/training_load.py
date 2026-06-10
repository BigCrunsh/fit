"""Training-Load context — the shared load primitives.

Bounded context (DDD review): everything derived from `training_load` lives here so
load concepts cannot silently fork. The CHRONIC-LOAD primitive below is the single
fitness-state concept platform-wide (marathon-durability-model Decision 6): ACWR's
chronic denominator and the forecast's fitness covariate must both resolve to it (F2).

Incremental context split: functions move here from `fit/analysis.py` with re-export
shims left behind; new load code lands here directly. Still in `fit/analysis.py`
(queued): `compute_weekly_agg`, `compute_rolling_week`, `_compute_acwr` (per-week,
coupled to weekly_agg writes), monotony/strain, sRPE.

load-unification (DONE 2026-06-10): the live `compute_rolling_acwr` chronic denominator
now reads the daily-load primitive (`chronic_load_before`), not the prior-4-ISO-week
`weekly_agg` totals — one chronic-load concept platform-wide (ACWR + marathon model).
Only `weekly_agg.acwr` keeps an ISO-week form, deliberately, as the chart-acwr trend.
"""

from __future__ import annotations

import sqlite3
from datetime import date

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
    """Rolling ACWR from the one shared daily-load primitive (no weekly_agg / ISO week).

    acute   = total load over the last 7 days (``end_date-6 .. end_date``).
    chronic = mean WEEKLY load over the 28 days BEFORE that window (uncoupled) — the
              shared ``chronic_load_before`` primitive evaluated at the acute-window
              start, scaled ×7 so it is comparable to the 7-day acute sum.

    Both terms read ``DAILY_LOAD_SQL`` (raw daily load), so there is no weighted /
    unweighted split and no ISO-week boundary: the live ACWR and the marathon model now
    resolve chronic load the *same* way (load-unification — was: acute from
    ``compute_rolling_week`` vs chronic from the cycling-weighted ``weekly_agg`` ISO
    totals). The stored ``weekly_agg.acwr`` stays the ISO-week **trend** series
    (chart-acwr); this is the live "now" read. ``config`` is accepted for signature
    stability but unused (raw load only). Returns None without ≥3 weeks of history or a
    positive chronic base; spikes >3.0 are capped to None.
    """
    import pandas as pd

    if end_date is None:
        end_date = date.today()

    dl = pd.read_sql_query(DAILY_LOAD_SQL, conn, parse_dates=["date"])
    if dl.empty:
        return None
    day_ord = dl["date"].map(pd.Timestamp.toordinal).to_numpy()
    day_load = dl["load"].fillna(0.0).to_numpy()

    ref = end_date.toordinal()
    acute_start = ref - 6
    # Need ≥3 weeks of history before "now" (mirrors the old ≥3-of-4-prior-weeks guard).
    if int(day_ord.min()) > ref - 21:
        return None

    acute = float(day_load[(day_ord >= acute_start) & (day_ord <= ref)].sum())
    # Uncoupled chronic: daily-mean load over the 28 days before the acute window,
    # scaled to a weekly total. Same primitive the marathon model reads.
    chronic_weekly = chronic_load_before(acute_start, day_ord, day_load, CHRONIC_WINDOW_DAYS) * 7.0
    if chronic_weekly <= 0:
        return None

    acwr = round(acute / chronic_weekly, 2)
    return acwr if acwr <= 3.0 else None
