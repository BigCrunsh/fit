"""Extrapolation-prior layer for the marathon forecast — pure pandas/numpy, no PyMC.

Sets the scale of the one-sided wall penalty ``γ ~ HalfStudentT(ν, extrapolation_scale)``
from PREPAREDNESS — how well you HOLD PACE in long runs — NOT cardiac drift. The
dual-lens review rejected drift as the marathon-fade signal (decoupling doesn't predict
marathon durability; late-race fade is *speed*-driven). The evidenced signal is
fast-finish long runs, so the quality input here is **pace-fade**: the speed give-back
over a long run's second half, gated to ≥ Moderate effort (holding an *easy* long run
isn't durability evidence).

    extrapolation_scale = GENERIC_WALL_SCALE · shrink,   shrink ∈ [SHRINK_FLOOR, 1]

- starts at the generic population wall scale (maximally uncertain),
- shrinks ONLY as pace-holding is demonstrated (asymmetric — never inflates on noise),
- floored (never full confidence until a goal-distance effort validates it),
- the extrapolation DISTANCE is handled by the penalty multiplier ``log(d/d_max)`` at
  predict time, NOT re-encoded here (avoids double-counting the gap).

See design.md Decision 2 / Decision 9 (the watch layer monitors this).
"""

from __future__ import annotations

import sqlite3

import numpy as np

NU = 4                      # HalfStudentT dof — labelled heavy-tail convention (design Decision 2)
GENERIC_WALL_SCALE = 0.04   # population wall scale: marathon penalty median ≈ +2% at γ·log(2)
SHRINK_FLOOR = 0.5          # never below half the generic scale until a goal-distance effort exists

# Pace-fade quality band (fraction of first-half pace). Hold within FADE_LO → full credit
# (shrink to floor); fade ≥ FADE_HI → no credit (stay generic). Linear between.
FADE_LO = 0.0
FADE_HI = 0.08
QUALITY_MIN_KM = 15.0        # a "long run" for durability-quality purposes
QUALITY_WINDOW_DAYS = 112    # ~16 weeks — the marathon-build horizon
QUALITY_EFFORT = ("Moderate", "Hard", "Very Hard")
_MIN_SPLITS = 4              # need enough splits to halve meaningfully


def _qualifying_long_runs(conn: sqlite3.Connection):
    placeholders = ",".join("?" * len(QUALITY_EFFORT))
    return conn.execute(
        f"""
        SELECT id, date, distance_km FROM activities
        WHERE type IN ('running', 'track_running')
          AND splits_status = 'done'
          AND distance_km >= ?
          AND effort_class IN ({placeholders})
          AND date >= date('now', ?)
        ORDER BY date DESC
        """,
        (QUALITY_MIN_KM, *QUALITY_EFFORT, f"-{QUALITY_WINDOW_DAYS} days"),
    ).fetchall()


def _run_pace_fade(conn: sqlite3.Connection, activity_id) -> float | None:
    """Second-half vs first-half pace give-back for one run. >0 = slowed (faded)."""
    paces = [r[0] for r in conn.execute(
        "SELECT pace_sec_per_km FROM activity_splits WHERE activity_id = ? "
        "AND pace_sec_per_km IS NOT NULL ORDER BY split_num", (activity_id,)
    ).fetchall()]
    if len(paces) < _MIN_SPLITS:
        return None
    half = len(paces) // 2
    p1 = float(np.mean(paces[:half]))
    p2 = float(np.mean(paces[half:]))
    if p1 <= 0:
        return None
    return (p2 - p1) / p1


def long_run_pace_fade(conn: sqlite3.Connection) -> dict:
    """Median pace-fade over recent qualifying long runs (≥ Moderate effort, ≥15 km).

    Returns {fade, n_runs}; fade is None when there are no qualifying long runs (the
    caller then keeps the generic wall scale and flags it as defaulted).
    """
    fades = []
    for run in _qualifying_long_runs(conn):
        f = _run_pace_fade(conn, run["id"])
        if f is not None:
            fades.append(f)
    if not fades:
        return {"fade": None, "n_runs": 0}
    return {"fade": float(np.median(fades)), "n_runs": len(fades)}


def extrapolation_prior(conn: sqlite3.Connection, goal: float | None = None) -> dict:
    """The wall-penalty prior for ``γ ~ HalfStudentT(ν, scale)`` (design Decision 2).

    ``scale = GENERIC_WALL_SCALE · shrink``; ``shrink`` is driven by pace-holding only
    (the gap is the penalty multiplier's job). Asymmetric (data only reduces), floored,
    and ``defaulted=True`` when there is no qualifying long-run evidence.

    ``goal`` is accepted for symmetry with the caller but unused here — the goal/d_max
    gap enters the penalty at predict time, not the scale.
    """
    q = long_run_pace_fade(conn)
    if q["fade"] is None:
        return {
            "scale": GENERIC_WALL_SCALE, "default_scale": GENERIC_WALL_SCALE,
            "shrink": 1.0, "defaulted": True, "nu": NU,
            "quality_pace_fade": None, "n_runs": 0,
            "reason": "no qualifying long runs (≥15 km, ≥ Moderate, with splits) — generic wall scale",
        }
    # frac: 0 = holds pace (full shrink), 1 = fades hard (no shrink). Asymmetric + clamped.
    frac = min(1.0, max(0.0, (q["fade"] - FADE_LO) / (FADE_HI - FADE_LO)))
    shrink = SHRINK_FLOOR + (1.0 - SHRINK_FLOOR) * frac
    return {
        "scale": GENERIC_WALL_SCALE * shrink, "default_scale": GENERIC_WALL_SCALE,
        "shrink": shrink, "defaulted": False, "nu": NU,
        "quality_pace_fade": q["fade"], "n_runs": q["n_runs"],
        "reason": f"median long-run pace-fade {q['fade'] * 100:+.1f}% over {q['n_runs']} run(s)",
    }
