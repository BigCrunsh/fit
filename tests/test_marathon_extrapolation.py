"""How the forecast reports reaching past the longest run it has ever seen.

The bug this replaces: the coaching context flagged the forecast `UNVALIDATED`
whenever `d_max < goal` and then hard-coded the remedy as "a 30 km+ run is what
validates it". Two things were wrong with that.

  1. The trigger and the remedy measured different things. With a 35 km longest
     run and a 42.195 km goal the flag fired and the advice was to go do 30 km —
     which the athlete had done nine days earlier. It read as self-contradiction
     because it *was* one.
  2. `d_max < goal` is permanently true for a marathon goal unless you have
     already raced a marathon. Nobody runs 42 km in training, so the flag could
     never be cleared. It carried no information; it was a constant.

What actually governs the reach is three separate quantities, and the athlete
can act on only one of them:
  - the LEVER ARM, log(goal / d_max) — how far past the observed range it must go;
  - the WALL SCALE, set by demonstrated pace-holding in long runs, floored so the
    model never claims full confidence at a distance never run;
  - the DIRECTION — the penalty is one-sided, so it can only add time, which is
    why the fast end of the interval is a floor rather than a best case.

So we report those as facts with a price in minutes, and we prescribe a longer
run only when the long-run range is genuinely short AND there is still time to
run one.
"""

import pytest

from fit.marathon.predict import (
    MIN_DAYS_TO_EXTEND_LONG_RUN,
    extrapolation_assessment,
)
from fit.analysis import LONG_RUN_COVERAGE_FRAC

MARATHON = 42.195


def _fc(d_max, *, goal=MARATHON, median=15000.0, wall_med=240.0, wall_hi=800.0,
        defaulted=False, reason="median long-run pace-fade +0.3% over 6 run(s)"):
    """A forecast result shaped like `forecast()`'s, without needing a fitted posterior."""
    import math
    gap = max(0.0, math.log(goal / d_max))
    return {
        "median": median, "lo": median - 600, "hi": median + 1800,
        "goal": goal, "d_max": d_max, "d_max_date": "2026-09-05", "gap": gap,
        "wall_cost_median_sec": wall_med if gap > 0 else 0.0,
        "wall_cost_hi_sec": wall_hi if gap > 0 else 0.0,
        "extrapolation": {"scale": 0.02, "shrink": 0.5, "defaulted": defaulted,
                          "nu": 4, "reason": reason, "n_runs": 0 if defaulted else 6},
    }


class TestNoActionWhenTheLongRunRangeIsCovered:
    def test_a_35km_long_run_does_not_ask_for_a_30km_run(self):
        """The exact reported contradiction: 35 km logged, told to go run 30 km."""
        a = extrapolation_assessment(_fc(35.12), days_to_race=13)
        assert a["covered"] is True
        assert a["action"] is None

    def test_coverage_boundary_counts_as_covered(self):
        """Exactly at the threshold is covered — no off-by-one that re-fires the nag."""
        a = extrapolation_assessment(_fc(LONG_RUN_COVERAGE_FRAC * MARATHON), days_to_race=60)
        assert a["covered"] is True
        assert a["action"] is None

    def test_still_reports_the_reach_and_its_price(self):
        """Covered does not mean silent: the model is still extrapolating, and the
        one-sided penalty still means the fast end is a floor."""
        a = extrapolation_assessment(_fc(35.12), days_to_race=13)
        assert a["extrapolating"] is True
        assert a["reach_pct"] == pytest.approx(20.1, abs=0.2)
        assert a["wall_cost_median_sec"] == 240.0
        assert a["wall_cost_hi_sec"] == 800.0


class TestActionOnlyWhenShortAndThereIsTime:
    def test_short_long_run_with_a_build_left_asks_for_a_longer_one(self):
        a = extrapolation_assessment(_fc(24.0), days_to_race=70)
        assert a["covered"] is False
        assert a["action"]["kind"] == "extend_long_run"
        assert a["action"]["target_km"] == pytest.approx(33.8, abs=0.1)
        assert a["action_blocked"] is None

    def test_short_long_run_inside_the_taper_prescribes_nothing(self):
        """Adding a long run 10 days out is worse than the gap it would close."""
        a = extrapolation_assessment(_fc(24.0), days_to_race=10)
        assert a["covered"] is False
        assert a["action"] is None
        assert a["action_blocked"] == "too-close-to-race"

    def test_boundary_day_still_blocks(self):
        a = extrapolation_assessment(_fc(24.0), days_to_race=MIN_DAYS_TO_EXTEND_LONG_RUN - 1)
        assert a["action"] is None
        a2 = extrapolation_assessment(_fc(24.0), days_to_race=MIN_DAYS_TO_EXTEND_LONG_RUN)
        assert a2["action"] is not None

    def test_unknown_race_date_does_not_invent_urgency(self):
        a = extrapolation_assessment(_fc(24.0), days_to_race=None)
        assert a["action"] is not None          # no date → no reason to suppress
        assert a["action_blocked"] is None


class TestEvidenceState:
    def test_absent_long_run_evidence_is_named_as_absent(self):
        """`defaulted` means no qualifying long run fed the wall scale — the model
        is on the generic population prior, which the athlete should be told."""
        a = extrapolation_assessment(
            _fc(24.0, defaulted=True, reason="no qualifying long runs (≥15 km, ≥ Moderate, with splits)"),
            days_to_race=70)
        assert a["evidence_defaulted"] is True
        assert "no qualifying long runs" in a["evidence"]

    def test_demonstrated_pace_holding_is_carried_through(self):
        a = extrapolation_assessment(_fc(35.12), days_to_race=13)
        assert a["evidence_defaulted"] is False
        assert "pace-fade" in a["evidence"]


class TestNoExtrapolationAtAll:
    def test_a_goal_distance_effort_removes_the_caveat_entirely(self):
        """Race the distance and there is nothing to extrapolate — no reach, no
        penalty, no caveat. This is the state the old flag could never reach."""
        a = extrapolation_assessment(_fc(MARATHON), days_to_race=30)
        assert a["extrapolating"] is False
        assert a["reach_pct"] == pytest.approx(0.0, abs=0.01)
        assert a["wall_cost_median_sec"] == 0.0
        assert a["action"] is None

    def test_beyond_goal_distance_is_not_negative_reach(self):
        a = extrapolation_assessment(_fc(50.0), days_to_race=30)
        assert a["extrapolating"] is False
        assert a["reach_pct"] == 0.0
