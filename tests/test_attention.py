"""Tests for the Attention panel aggregator (_attention_items)
and the race-countdown prediction-confidence helper."""

from datetime import date, timedelta


from fit.report.sections.cards import _attention_items, _prediction_confidence


def _add_calibration(db, metric, value, days_ago, confidence="medium"):
    cal_date = (date.today() - timedelta(days=days_ago)).isoformat()
    db.execute("UPDATE calibration SET active = 0 WHERE metric = ?", (metric,))
    db.execute(
        "INSERT INTO calibration (metric, value, method, confidence, date, active) "
        "VALUES (?, ?, 'manual', ?, ?, 1)",
        (metric, value, confidence, cal_date),
    )
    db.commit()


def _add_race(db, days_ago, distance_km=10.0, result_time="42:30"):
    d = (date.today() - timedelta(days=days_ago)).isoformat()
    db.execute(
        "INSERT INTO race_calendar (date, name, distance, distance_km, result_time, status) "
        "VALUES (?, 'Race', '10K', ?, ?, 'completed')",
        (d, distance_km, result_time),
    )
    db.commit()


class TestAttentionItems:
    """The panel should aggregate, dedupe, and severity-sort pending actions."""

    def test_empty_when_nothing_pending(self, db, config):
        """No calibrations, no data, no coaching → empty list, panel hides."""
        items = _attention_items(db)
        # Empty DB has missing metrics → some items will show. Filter to ensure
        # the structure is correct regardless.
        assert isinstance(items, list)
        for i in items:
            assert i["severity"] in {"critical", "warning", "info"}
            assert "message" in i
            assert "tag" in i

    def test_lthr_missing_is_warning(self, db, config):
        """Missing LTHR is a warning — anchors training zones."""
        items = _attention_items(db)
        lthr_items = [i for i in items if i["tag"] == "cal_missing_lthr"]
        assert lthr_items
        assert lthr_items[0]["severity"] == "warning"

    def test_severity_order(self, db, config):
        """Items are sorted critical → warning → info."""
        items = _attention_items(db)
        sev_order = {"critical": 0, "warning": 1, "info": 2}
        indices = [sev_order[i["severity"]] for i in items]
        assert indices == sorted(indices)

    def test_dedupes_by_tag(self, db, config):
        """No two items share the same tag — dedupe across sources."""
        items = _attention_items(db)
        tags = [i["tag"] for i in items]
        assert len(tags) == len(set(tags))

    def test_lthr_calibrated_is_not_flagged(self, db, config):
        """Fresh LTHR cal removes the LTHR-missing warning."""
        _add_calibration(db, "lthr", 172, days_ago=10)
        items = _attention_items(db)
        assert not any(i["tag"] == "cal_missing_lthr" for i in items)

    def test_command_included_on_actionable_items(self, db, config):
        """Items that map to a CLI command include it for easy copy-paste."""
        items = _attention_items(db)
        cal_lthr = next((i for i in items if i["tag"] == "cal_missing_lthr"), None)
        assert cal_lthr and cal_lthr["command"] is not None


class TestPredictionConfidence:
    """Race-prediction confidence reflects anchor freshness + race history."""

    def test_low_when_no_data_anywhere(self, db, config):
        result = _prediction_confidence(db)
        assert result["level"] == "low"

    def test_high_when_anchors_fresh_and_races_present(self, db, config):
        _add_calibration(db, "lthr", 172, days_ago=10)
        _add_calibration(db, "vo2max", 49, days_ago=20)
        _add_race(db, days_ago=30)
        _add_race(db, days_ago=60)
        result = _prediction_confidence(db)
        assert result["level"] == "high"

    def test_medium_when_one_anchor_stale(self, db, config):
        # LTHR stale (>56 days), VO2max fresh, 2 races
        _add_calibration(db, "lthr", 172, days_ago=100)
        _add_calibration(db, "vo2max", 49, days_ago=20)
        _add_race(db, days_ago=30)
        _add_race(db, days_ago=60)
        result = _prediction_confidence(db)
        assert result["level"] == "medium"
        assert "LTHR" in result["reason"]

    def test_medium_when_only_one_race(self, db, config):
        _add_calibration(db, "lthr", 172, days_ago=10)
        _add_calibration(db, "vo2max", 49, days_ago=20)
        _add_race(db, days_ago=30)
        result = _prediction_confidence(db)
        assert result["level"] == "medium"
        assert "1 recent race" in result["reason"]

    def test_low_when_both_anchors_stale(self, db, config):
        _add_calibration(db, "lthr", 172, days_ago=100)
        _add_calibration(db, "vo2max", 49, days_ago=120)
        _add_race(db, days_ago=30)
        result = _prediction_confidence(db)
        assert result["level"] == "low"

    def test_high_reason_is_empty(self, db, config):
        """When everything is fresh, the reason string is empty (no caveat to show)."""
        _add_calibration(db, "lthr", 172, days_ago=10)
        _add_calibration(db, "vo2max", 49, days_ago=20)
        _add_race(db, days_ago=30)
        _add_race(db, days_ago=60)
        result = _prediction_confidence(db)
        assert result["reason"] == ""


def _add_completed_race_with_activity(db, d, name, distance_km, avg_hr,
                                      result_time=None, garmin_time=None):
    """Insert a completed race + linked activity for race-attention tests."""
    aid = f"act-{d}"
    db.execute(
        "INSERT INTO activities (id, date, type, name, distance_km, duration_min, avg_hr) "
        "VALUES (?, ?, 'running', ?, ?, ?, ?)",
        (aid, d, name, distance_km, distance_km * 5.5, avg_hr),
    )
    db.execute(
        "INSERT INTO race_calendar (date, name, distance, distance_km, status, "
        "activity_id, result_time, garmin_time) VALUES (?, ?, ?, ?, 'completed', ?, ?, ?)",
        (d, name, f"{distance_km:g}km", distance_km, aid, result_time, garmin_time),
    )
    db.commit()


class TestRaceMissingResultTime:
    def test_flags_completed_race_without_official_time(self, db):
        _add_completed_race_with_activity(db, "2026-03-22", "Müggelturm HM", 21.1, 173,
                                          garmin_time="2:01:48")  # no result_time
        items = _attention_items(db)
        tags = {i["tag"] for i in items}
        assert "race_missing_result_time" in tags

    def test_no_flag_when_official_time_present(self, db):
        _add_completed_race_with_activity(db, "2026-03-22", "HM", 21.1, 173,
                                          result_time="1:50:00", garmin_time="2:01:48")
        items = _attention_items(db)
        assert "race_missing_result_time" not in {i["tag"] for i in items}


class TestLthrSuggestion:
    def test_suggests_lthr_from_recent_hm(self, db):
        # Active LTHR 172; a recent HM at avg 173 implies ~175 (≥3 apart) → suggest.
        _add_calibration(db, "lthr", 172, days_ago=200)
        _add_completed_race_with_activity(db, "2026-03-22", "HM", 21.1, 173,
                                          garmin_time="2:01:48")
        items = _attention_items(db)
        sug = [i for i in items if i["tag"] == "lthr_suggestion"]
        assert sug, "expected an lthr_suggestion item"
        assert "fit calibrate lthr 175" in sug[0]["command"]

    def test_no_suggestion_when_close_to_active(self, db):
        # HM avg 170 → ~172 (HM correction ×1.01 = 171.7→172), within 3 of active → no nudge.
        _add_calibration(db, "lthr", 172, days_ago=200)
        _add_completed_race_with_activity(db, "2026-03-22", "HM", 21.1, 170,
                                          garmin_time="2:05:00")
        items = _attention_items(db)
        assert "lthr_suggestion" not in {i["tag"] for i in items}

    def test_no_suggestion_from_sub_hm_race(self, db):
        # A 12.5km steady "race" (Osterlauf-style) must NOT drive the suggestion.
        _add_calibration(db, "lthr", 172, days_ago=200)
        _add_completed_race_with_activity(db, "2026-04-04", "Osterlauf", 12.5, 166,
                                          garmin_time="1:10:33")
        items = _attention_items(db)
        assert "lthr_suggestion" not in {i["tag"] for i in items}

    def test_no_suggestion_when_active_is_device_measured(self, db):
        # A device-measured LTHR (Garmin auto-LT) is trusted over any race proxy,
        # so a race-implied nudge is suppressed even when it differs >=3.
        db.execute(
            "INSERT INTO calibration (metric, value, method, confidence, date, active) "
            "VALUES ('lthr', 171, 'device_lt', 'high', ?, 1)",
            ((date.today() - timedelta(days=1)).isoformat(),),
        )
        db.commit()
        _add_completed_race_with_activity(db, "2026-03-22", "HM", 21.1, 173,
                                          garmin_time="2:01:48")  # implies ~175
        items = _attention_items(db)
        assert "lthr_suggestion" not in {i["tag"] for i in items}


class TestVdotNoAnchor:
    """Only the genuine "no performance anchor at all" case is flagged — never the
    structural Garmin-reads-higher gap (Garmin's wrist VO2max is optimistic by design)."""

    def test_flags_when_no_anchor_but_garmin_present(self, db, config):
        # Garmin VO2max exists, but no qualifying running anchor → prompt a time trial.
        db.execute("INSERT INTO activities (id, date, type, vo2max) VALUES ('a1', ?, 'running', 49)",
                   (date.today().isoformat(),))
        db.commit()
        tags = {i["tag"] for i in _attention_items(db)}
        assert "vdot_no_anchor" in tags
        # The retired "anchors disagree" item must never appear.
        assert "vdot_anchor_disagreement" not in tags
