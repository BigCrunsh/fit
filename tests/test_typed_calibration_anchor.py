"""Tests for the typed calibration anchor (DDD E1+E2).

E1 — `CalibrationAnchor` value object: `value` is always real; absence is `None`
     (no "anchor with no value").
E2 — typed trust taxonomy: `TrustTier`/`Confidence`/`CalibrationMethod` drive
     selection; an unknown stored method degrades to `LEGACY`, never raises.

Behaviour preservation for the policy/precedence numbers lives in
`test_anchor_policy.py` and `test_lthr_ingestion.py`; this file covers the types
and the absence/legacy edges.
"""

from datetime import date, timedelta

import pytest

from fit.calibration import (
    CalibrationAnchor, CalibrationMethod, Confidence, TrustTier,
    get_calibration_anchor, get_calibration_history,
)


def _ins(db, metric, value, method, days_ago, confidence="medium", active=0):
    db.execute(
        "INSERT INTO calibration (metric, value, method, confidence, date, active, flags) "
        "VALUES (?, ?, ?, ?, ?, ?, '[]')",
        (metric, value, method, confidence,
         (date.today() - timedelta(days=days_ago)).isoformat(), active),
    )
    db.commit()


# ── E2 types in isolation (task 1.5) ─────────────────────────────────────────

class TestTrustTier:
    def test_is_a_total_order_matching_precedence(self):
        assert (TrustTier.CONFIRMED > TrustTier.DEVICE > TrustTier.POLICY
                > TrustTier.LEGACY > TrustTier.REFERENCE > TrustTier.INFORMATIONAL)

    def test_legacy_and_above_are_anchor_eligible(self):
        for t in (TrustTier.LEGACY, TrustTier.POLICY, TrustTier.DEVICE, TrustTier.CONFIRMED):
            assert t.is_anchor_eligible

    def test_reference_and_informational_are_not_anchor_eligible(self):
        assert not TrustTier.REFERENCE.is_anchor_eligible
        assert not TrustTier.INFORMATIONAL.is_anchor_eligible


class TestConfidence:
    def test_ordering(self):
        assert Confidence.HIGH > Confidence.MEDIUM > Confidence.LOW

    def test_from_str_roundtrip(self):
        for s in ("low", "medium", "high"):
            assert Confidence.from_str(s).to_str() == s

    def test_from_str_unknown_and_none_default_low(self):
        assert Confidence.from_str(None) == Confidence.LOW
        assert Confidence.from_str("garbage") == Confidence.LOW
        assert Confidence.from_str("") == Confidence.LOW


class TestCalibrationMethod:
    def test_known_strings_map_to_expected_tier(self):
        cases = {
            "manual": TrustTier.CONFIRMED, "confirmed": TrustTier.CONFIRMED,
            "device_lt": TrustTier.DEVICE, "device_vo2max": TrustTier.REFERENCE,
            "race_observation": TrustTier.INFORMATIONAL,
            "effort_observation": TrustTier.INFORMATIONAL,
        }
        for s, tier in cases.items():
            assert CalibrationMethod.resolve(s).trust_tier == tier

    def test_auto_derived_candidates_are_legacy_tier(self):
        # D3: candidate methods are observation rows; as an active row they are
        # only ever last-resort (LEGACY), below the synthesized POLICY suggestion.
        for s in ("race_candidate", "activity_max", "drift_test", "scale"):
            assert CalibrationMethod.resolve(s).trust_tier == TrustTier.LEGACY

    def test_unknown_string_degrades_to_legacy(self):
        assert CalibrationMethod.resolve("garmin_lt_pre_migration") is CalibrationMethod.LEGACY
        assert CalibrationMethod.resolve("garmin_lt_pre_migration").trust_tier == TrustTier.LEGACY

    def test_none_and_empty_degrade_to_legacy(self):
        assert CalibrationMethod.resolve(None) is CalibrationMethod.LEGACY
        assert CalibrationMethod.resolve("") is CalibrationMethod.LEGACY

    def test_legacy_is_anchor_eligible(self):
        assert CalibrationMethod.resolve("anything_unknown").is_anchor_eligible

    def test_reference_method_not_anchor_eligible(self):
        assert not CalibrationMethod.DEVICE_VO2MAX.is_anchor_eligible
        assert not CalibrationMethod.RACE_OBSERVATION.is_anchor_eligible


class TestCalibrationAnchorValueObject:
    def test_value_is_accessible_and_object_is_frozen(self):
        a = CalibrationAnchor(metric="lthr", value=172.0, confidence="high",
                              method="confirmed", source_date="2026-06-01",
                              stale=False, inputs=[], suggestion=None)
        assert a.value == 172.0
        with pytest.raises(Exception):
            a.value = 5  # frozen → cannot mutate


# ── E1: absence is None, never a valueless anchor ────────────────────────────

class TestAnchorAbsence:
    def test_no_rows_returns_none(self, db):
        assert get_calibration_anchor(db, "vdot") is None

    def test_reference_only_metric_returns_none(self, db):
        # device_vo2max is REFERENCE: excluded from the estimator AND not
        # anchor-eligible → no anchor at all (not an object with value=None).
        _ins(db, "vdot", 49.0, "device_vo2max", days_ago=5, active=1)
        assert get_calibration_anchor(db, "vdot") is None

    def test_informational_rows_feed_policy_and_yield_an_anchor(self, db):
        # race_observation is informational: never the active row, but DOES feed
        # the estimator → the anchor is the resulting policy suggestion, not None.
        _ins(db, "vdot", 40.9, "race_observation", days_ago=20)
        a = get_calibration_anchor(db, "vdot")
        assert a is not None
        assert a.method == "policy"
        assert isinstance(a.value, float) and a.value == 40.9

    def test_anchor_value_is_always_a_real_number_when_present(self, db):
        _ins(db, "lthr", 172, "manual", days_ago=2, confidence="high", active=1)
        a = get_calibration_anchor(db, "lthr")
        assert a is not None and isinstance(a.value, (int, float))


# ── E2: typed precedence + legacy robustness ─────────────────────────────────

class TestTypedPrecedence:
    def test_confirmed_beats_device(self, db):
        _ins(db, "lthr", 173, "device_lt", days_ago=2, confidence="high", active=1)
        _ins(db, "lthr", 168, "manual", days_ago=1, confidence="high", active=1)
        a = get_calibration_anchor(db, "lthr")
        assert a.value == 168 and a.method == "manual"

    def test_device_beats_policy_estimate(self, db):
        _ins(db, "lthr", 160, "race_observation", days_ago=30)
        _ins(db, "lthr", 162, "race_observation", days_ago=20)
        _ins(db, "lthr", 164, "race_observation", days_ago=10)
        _ins(db, "lthr", 173, "device_lt", days_ago=1, confidence="high", active=1)
        a = get_calibration_anchor(db, "lthr")
        assert a.value == 173 and a.method == "device_lt"   # DEVICE > POLICY
        assert a.suggestion is not None                     # policy still carried

    def test_unknown_legacy_method_is_used_as_last_resort_no_crash(self, db):
        # A pre-migration / unknown method on the active row of a policy-less
        # metric: resolves to LEGACY, still selectable, never raises.
        _ins(db, "weight", 74.2, "garmin_scale_v1_legacy", days_ago=1,
             confidence="high", active=1)
        a = get_calibration_anchor(db, "weight")
        assert a is not None and a.value == 74.2
        assert a.method == "garmin_scale_v1_legacy"   # original string preserved on the anchor

    def test_active_calibration_tie_broken_by_recency(self, db):
        from fit.calibration import get_active_calibration
        _ins(db, "max_hr", 192, "manual", days_ago=40, confidence="high", active=1)
        _ins(db, "max_hr", 195, "manual", days_ago=5, confidence="high", active=1)
        # same tier + confidence → most recent date wins
        assert get_active_calibration(db, "max_hr")["value"] == 195


class TestLegacyMethodRobustness:
    def test_junk_method_row_loads_via_history_without_error(self, db):
        _ins(db, "lthr", 170, "weird_old_method", days_ago=10, confidence="low")
        hist = get_calibration_history(db, "lthr")
        assert len(hist) == 1
        assert hist[0]["method"] == "weird_old_method"
        assert hist[0]["flags"] == []


# ── E1 consumer: None handled cleanly (no .get on a missing anchor) ──────────

class TestConsumerNoneHandling:
    def test_marathon_lthr_feature_raises_when_no_anchor(self, db):
        from fit.marathon.features import _lthr
        with pytest.raises(ValueError, match="no LTHR calibration anchor"):
            _lthr(db)

    def test_marathon_maxhr_feature_none_when_no_anchor(self, db):
        from fit.marathon.features import _max_hr
        assert _max_hr(db) is None
