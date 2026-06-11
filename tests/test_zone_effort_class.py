"""Tests for the Zone / EffortClass value objects (DDD E3).

Zone owns the zone ladder's identity, ordering, and the single zone→effort-class
mapping; an invalid zone is rejected rather than silently mislabeled. Behaviour for
valid inputs (Z1–Z5, None) is unchanged — the wider classification/run-type behaviour
is covered by test_analysis.py / test_plan.py (the oracle).
"""

import pytest

from fit.analysis import EffortClass, Zone, compute_effort_class


# ── Happy ────────────────────────────────────────────────────────────────────

class TestZoneHappy:
    def test_ordering_is_intrinsic(self):
        assert Zone.Z1 < Zone.Z2 < Zone.Z3 < Zone.Z4 < Zone.Z5
        assert Zone.parse("Z4") >= Zone.Z3      # the "Z3 and above" threshold idiom

    def test_parse_valid(self):
        assert Zone.parse("Z1") is Zone.Z1
        assert Zone.parse("Z5") is Zone.Z5

    def test_effort_class_mapping_is_complete_and_single(self):
        assert Zone.Z1.effort_class is EffortClass.RECOVERY
        assert Zone.Z2.effort_class is EffortClass.EASY
        assert Zone.Z3.effort_class is EffortClass.MODERATE
        assert Zone.Z4.effort_class is EffortClass.HARD
        assert Zone.Z5.effort_class is EffortClass.VERY_HARD
        # exactly the five zones map — no extra, no missing
        assert {z.effort_class.value for z in Zone} == {
            "Recovery", "Easy", "Moderate", "Hard", "Very Hard"}


# ── Unhappy / edge ─────────────────────────────────────────────────────────────

class TestZoneUnhappy:
    def test_parse_is_case_and_whitespace_insensitive(self):
        # matches the old _zone_to_number behaviour (was case-insensitive)
        assert Zone.parse("z3") is Zone.Z3
        assert Zone.parse("  Z2 ") is Zone.Z2

    @pytest.mark.parametrize("bad", ["Z0", "Z6", "Z9", "Z", "foo", ""])
    def test_parse_rejects_junk(self, bad):
        with pytest.raises(KeyError):
            Zone.parse(bad)

    def test_parse_rejects_none(self):
        with pytest.raises(AttributeError):
            Zone.parse(None)

    def test_parse_or_none_is_tolerant(self):
        assert Zone.parse_or_none(None) is None
        assert Zone.parse_or_none("Z9") is None
        assert Zone.parse_or_none("") is None
        assert Zone.parse_or_none("z2") is Zone.Z2     # still parses the valid ones

    def test_compute_effort_class_rejects_invalid(self):
        # the regression: an unknown/typo zone no longer maps silently to "Easy"
        with pytest.raises(KeyError):
            compute_effort_class("Z9")
        with pytest.raises(KeyError):
            compute_effort_class("easy")

    def test_compute_effort_class_none_passthrough(self):
        assert compute_effort_class(None) is None
