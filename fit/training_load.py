"""Training-Load context — the shared load primitives.

Bounded context (DDD review): everything derived from `training_load` lives here so
load concepts cannot silently fork. The CHRONIC-LOAD windowing primitive below
(`chronic_load_before`) is the single fitness-state model platform-wide
(marathon-durability-model Decision 6): ACWR's chronic denominator and the forecast's
fitness covariate both resolve to it (F2) — they differ only by activity filter (ACWR =
running only; the forecast = all activities), never by a second ISO-vs-rolling formula.

Incremental context split: functions move here from `fit/analysis.py` with re-export
shims left behind; new load code lands here directly. Still in `fit/analysis.py`
(queued): `compute_weekly_agg`, `compute_rolling_week`, `_compute_acwr` (per-week,
coupled to weekly_agg writes), monotony/strain, sRPE.

load-unification (DONE 2026-06-10): the live `compute_rolling_acwr` chronic denominator
now reads the daily-load windowing primitive (`chronic_load_before`), not the
prior-4-ISO-week `weekly_agg` totals. ACWR and the marathon model share that primitive
but filter activities to suit their question: ACWR counts RUNNING only (injury = running
mechanical load), the model counts all activities (fitness = total aerobic load, Decision
6). `weekly_agg.acwr` keeps an ISO-week form, deliberately, as the chart-acwr trend.
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
    """Rolling ACWR over RUNNING load only — the injury-risk ratio for running.

    acute   = total running load over the last 7 days (``end_date-6 .. end_date``).
    chronic = mean WEEKLY running load over the 28 days BEFORE that window (uncoupled) —
              the shared ``chronic_load_before`` windowing primitive evaluated at the
              acute-window start, scaled ×7 so it is comparable to the 7-day acute sum.

    Cross-training (cycling, etc.) is **excluded**: ACWR is a *running* mechanical-load
    ratio, so a hard bike week must not mask a running spike (nor a bike block prop the
    chronic baseline). This differs from the marathon model's *fitness* covariate
    (``chronic_load``), which counts all activities (cross-training is aerobic fitness —
    marathon-durability-model Decision 6); the two share the windowing primitive but
    filter activities to suit their question.

    There is no ISO-week boundary and no weighted/unweighted split (the old chronic read
    cycling-weighted ``weekly_agg`` ISO totals). The stored ``weekly_agg.acwr`` stays the
    ISO-week **trend** series (chart-acwr); this is the live "now" read. ``config`` is
    accepted for signature stability but unused. Returns None without ≥3 weeks of history
    or a positive chronic base; spikes >3.0 are capped to None.
    """
    import pandas as pd
    from fit.analysis import RUNNING_TYPES_SQL  # local: avoid import cycle

    if end_date is None:
        end_date = date.today()

    running_daily_load_sql = (
        "SELECT date, SUM(training_load) AS load FROM activities "
        f"WHERE training_load IS NOT NULL AND type IN {RUNNING_TYPES_SQL} "
        "GROUP BY date ORDER BY date"
    )
    dl = pd.read_sql_query(running_daily_load_sql, conn, parse_dates=["date"])
    if dl.empty:
        return None
    day_ord = dl["date"].map(pd.Timestamp.toordinal).to_numpy()
    day_load = dl["load"].fillna(0.0).to_numpy()

    ref = end_date.toordinal()
    acute_start = ref - 6
    # Need ≥3 weeks of running history before "now" (mirrors the old ≥3-of-4-weeks guard).
    if int(day_ord.min()) > ref - 21:
        return None

    acute = float(day_load[(day_ord >= acute_start) & (day_ord <= ref)].sum())
    # Uncoupled chronic: daily-mean running load over the 28 days before the acute
    # window, scaled to a weekly total (same windowing primitive as the model).
    chronic_weekly = chronic_load_before(acute_start, day_ord, day_load, CHRONIC_WINDOW_DAYS) * 7.0
    if chronic_weekly <= 0:
        return None

    acwr = round(acute / chronic_weekly, 2)
    return acwr if acwr <= 3.0 else None
