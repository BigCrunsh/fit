"""Garmin lactate-threshold ingestion → device-anchored LTHR.

The watch's auto-detected LT HR is ingested as a `device_lt` calibration row and
becomes the LTHR anchor: authoritative over the race-avg-HR proxy, but below a
deliberate human confirm. Replaces reverse-engineering LTHR from race HR.
"""

from datetime import date, timedelta

from fit.calibration import get_calibration_anchor
from fit.garmin import fetch_lactate_threshold
import fit.sync as sync


def _d(days_ago):
    return (date.today() - timedelta(days=days_ago)).isoformat()


def _row(db, value, method, confidence, days_ago):
    db.execute(
        "INSERT INTO calibration (metric, value, method, confidence, date, active) "
        "VALUES ('lthr', ?, ?, ?, ?, 1)",
        (value, method, confidence, _d(days_ago)),
    )
    db.commit()


class _FakeApi:
    def __init__(self, payload):
        self._payload = payload

    def connectapi(self, endpoint):
        return self._payload


class TestDeviceAnchorPrecedence:
    def test_device_beats_race_proxy(self, db):
        _row(db, 164, "race_observation", "low", 30)
        _row(db, 175, "race_observation", "low", 20)
        _row(db, 173, "device_lt", "high", 1)
        a = get_calibration_anchor(db, "lthr")
        assert a["value"] == 173
        assert a["method"] == "device_lt"

    def test_human_confirm_overrides_device(self, db):
        _row(db, 173, "device_lt", "high", 2)
        _row(db, 168, "manual", "high", 1)  # deliberate, newer
        a = get_calibration_anchor(db, "lthr")
        assert a["value"] == 168
        assert a["method"] == "manual"

    def test_device_excluded_from_race_suggestion(self, db):
        # the policy suggestion ("what races imply") ignores the device value
        _row(db, 160, "race_observation", "low", 30)
        _row(db, 162, "race_observation", "low", 20)
        _row(db, 164, "race_observation", "low", 10)
        _row(db, 173, "device_lt", "high", 1)
        a = get_calibration_anchor(db, "lthr")
        assert a["value"] == 173                # device is the anchor
        assert a["suggestion"]["value"] == 162  # median of the 3 race rows only
        assert a["suggestion"]["differs"] is True

    def test_device_anchor_suppresses_policy_nag(self, db):
        # evaluate_suggestions must NOT nag toward a policy estimate when the
        # active anchor is device-measured: precedence already ranks device >
        # policy, so the suggestion could never win — surfacing it is self-
        # contradictory. (The suggestion itself still computes + differs.)
        from fit.calibration import evaluate_suggestions
        _row(db, 160, "race_observation", "low", 30)
        _row(db, 162, "race_observation", "low", 20)
        _row(db, 164, "race_observation", "low", 10)
        _row(db, 173, "device_lt", "high", 1)
        assert get_calibration_anchor(db, "lthr")["suggestion"]["differs"] is True
        assert not any(s["metric"] == "lthr"
                       for s in evaluate_suggestions(db, review={}))

    def test_policy_nag_present_without_device(self, db):
        # Contrast: with a human-confirmed (non-device) anchor that differs from
        # the race-implied median, the suggestion IS surfaced for accept/reject.
        from fit.calibration import evaluate_suggestions
        _row(db, 160, "race_observation", "low", 30)
        _row(db, 162, "race_observation", "low", 20)
        _row(db, 164, "race_observation", "low", 10)   # median 162
        _row(db, 172, "manual", "high", 1)             # confirmed, differs from 162
        a = get_calibration_anchor(db, "lthr")
        assert a["method"] == "manual" and a["value"] == 172
        assert any(s["metric"] == "lthr"
                   for s in evaluate_suggestions(db, review={}))


class TestFetchParser:
    def test_parses_lthr_and_speed(self):
        api = _FakeApi({"biometricProfile": {
            "lactateThresholdHeartRate": 173.0, "lactateThresholdSpeed": 0.342}})
        lt = fetch_lactate_threshold(api)
        assert lt["lthr"] == 173.0
        assert lt["lt_speed_mps"] == 0.342

    def test_none_when_field_missing(self):
        assert fetch_lactate_threshold(_FakeApi({"biometricProfile": {}})) is None

    def test_none_when_not_dict(self):
        assert fetch_lactate_threshold(_FakeApi("cloudflare interstitial")) is None


class TestSyncStore:
    def test_stores_then_dedups_then_restores_on_change(self, db, monkeypatch):
        monkeypatch.setattr(sync.garmin, "fetch_lactate_threshold",
                            lambda api: {"lthr": 173.0, "lt_speed_mps": 0.34})
        assert sync._sync_lactate_threshold(db, object()) is True       # first store
        assert get_calibration_anchor(db, "lthr")["value"] == 173.0
        assert sync._sync_lactate_threshold(db, object()) is False      # unchanged → dedup

        monkeypatch.setattr(sync.garmin, "fetch_lactate_threshold",
                            lambda api: {"lthr": 170.0})
        assert sync._sync_lactate_threshold(db, object()) is True       # changed → store

    def test_no_store_when_fetch_returns_none(self, db, monkeypatch):
        monkeypatch.setattr(sync.garmin, "fetch_lactate_threshold", lambda api: None)
        assert sync._sync_lactate_threshold(db, object()) is False
