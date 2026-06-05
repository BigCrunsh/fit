"""Extrapolation-prior (wall penalty scale) from long-run pace-holding — no PyMC.

The scale starts at the generic wall and shrinks ONLY as pace-holding is demonstrated:
asymmetric (never inflates), floored (never full confidence pre-goal-distance), gated to
≥ Moderate effort (an easy long run isn't durability evidence). The extrapolation gap is
the penalty multiplier's job, not the scale's — so it is NOT re-encoded here.
"""

from datetime import date, timedelta

import pytest

from fit.marathon.preparedness import (
    extrapolation_prior, long_run_pace_fade,
    GENERIC_WALL_SCALE, SHRINK_FLOOR, FADE_HI,
)


def _d(days_ago):
    return (date.today() - timedelta(days=days_ago)).isoformat()


def _long_run(db, aid, *, distance_km, effort_class, first_half_pace, second_half_pace,
              n_splits=16, days_ago=20):
    db.execute(
        "INSERT INTO activities (id, date, type, distance_km, effort_class, splits_status) "
        "VALUES (?, ?, 'running', ?, ?, 'done')",
        (aid, _d(days_ago), distance_km, effort_class),
    )
    half = n_splits // 2
    for k in range(1, n_splits + 1):
        pace = first_half_pace if k <= half else second_half_pace
        db.execute(
            "INSERT INTO activity_splits (activity_id, split_num, distance_km, pace_sec_per_km) "
            "VALUES (?, ?, 1.0, ?)", (aid, k, pace))
    db.commit()


class TestExtrapolationPrior:
    # Happy
    def test_holding_pace_shrinks_to_floor(self, db):
        # negative split (held / sped up) → full credit → shrink at the floor
        _long_run(db, "hold", distance_km=18, effort_class="Moderate",
                  first_half_pace=300, second_half_pace=294)
        p = extrapolation_prior(db)
        assert p["defaulted"] is False
        assert p["shrink"] == pytest.approx(SHRINK_FLOOR)
        assert p["scale"] == pytest.approx(GENERIC_WALL_SCALE * SHRINK_FLOOR)

    def test_fading_hard_stays_generic(self, db):
        # ≥8% pace-fade → no credit → generic scale
        _long_run(db, "fade", distance_km=18, effort_class="Moderate",
                  first_half_pace=300, second_half_pace=300 * (1 + FADE_HI + 0.01))
        p = extrapolation_prior(db)
        assert p["shrink"] == pytest.approx(1.0)
        assert p["scale"] == pytest.approx(GENERIC_WALL_SCALE)

    def test_partial_fade_interpolates_within_band(self, db):
        # 4% fade → halfway through [0, 8%] band → shrink halfway between floor and 1
        _long_run(db, "mid", distance_km=18, effort_class="Hard",
                  first_half_pace=300, second_half_pace=312)  # +4%
        p = extrapolation_prior(db)
        assert SHRINK_FLOOR < p["shrink"] < 1.0
        assert p["shrink"] == pytest.approx(SHRINK_FLOOR + (1 - SHRINK_FLOOR) * 0.5, abs=0.02)

    # Unhappy (2:1)
    def test_no_long_runs_defaults_to_generic(self, db):
        p = extrapolation_prior(db)
        assert p["defaulted"] is True
        assert p["scale"] == pytest.approx(GENERIC_WALL_SCALE)
        assert p["shrink"] == 1.0
        assert p["n_runs"] == 0

    def test_easy_long_run_does_not_count(self, db):
        # holds pace, but Easy effort → not durability evidence → still defaulted
        _long_run(db, "easy", distance_km=20, effort_class="Easy",
                  first_half_pace=330, second_half_pace=325)
        p = extrapolation_prior(db)
        assert p["defaulted"] is True
        assert p["n_runs"] == 0

    def test_short_run_does_not_count(self, db):
        _long_run(db, "short", distance_km=10, effort_class="Hard",
                  first_half_pace=290, second_half_pace=285)
        assert extrapolation_prior(db)["defaulted"] is True

    def test_shrink_never_below_floor_or_above_one(self, db):
        # extreme negative split (way under) must still clamp at the floor, not below
        _long_run(db, "super", distance_km=22, effort_class="Very Hard",
                  first_half_pace=320, second_half_pace=260)
        p = extrapolation_prior(db)
        assert SHRINK_FLOOR <= p["shrink"] <= 1.0
        assert p["shrink"] == pytest.approx(SHRINK_FLOOR)

    def test_run_without_enough_splits_ignored(self, db):
        _long_run(db, "fewsplits", distance_km=18, effort_class="Moderate",
                  first_half_pace=300, second_half_pace=300, n_splits=2)
        assert long_run_pace_fade(db)["fade"] is None
