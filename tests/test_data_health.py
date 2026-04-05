"""Tests for fit/data_health.py — data source freshness checking."""

from datetime import date, timedelta


from fit.data_health import check_data_sources, _check


# ════════════════════════════════════════════════════════════════
# _check helper
# ════════════════════════════════════════════════════════════════


class TestCheckHelper:
    # Happy
    def test_active_source(self):
        today = date(2026, 4, 5)
        result = _check("test", "2026-04-04", today, stale_days=3)
        assert result["status"] == "active"
        assert result["days_ago"] == 1

    def test_exactly_at_stale_threshold(self):
        today = date(2026, 4, 5)
        result = _check("test", "2026-04-02", today, stale_days=3)
        assert result["status"] == "active"  # 3 days ago, threshold is 3

    # Unhappy
    def test_stale_source(self):
        today = date(2026, 4, 5)
        result = _check("test", "2026-03-01", today, stale_days=3)
        assert result["status"] == "stale"
        assert result["days_ago"] == 35

    def test_just_past_stale(self):
        today = date(2026, 4, 5)
        result = _check("test", "2026-04-01", today, stale_days=3)
        assert result["status"] == "stale"  # 4 days ago > 3

    def test_missing_source(self):
        today = date(2026, 4, 5)
        result = _check("test", None, today, stale_days=3)
        assert result["status"] == "missing"
        assert result["last_date"] is None

    def test_empty_string_date(self):
        """Empty string is falsy → missing."""
        today = date(2026, 4, 5)
        result = _check("test", "", today, stale_days=3)
        assert result["status"] == "missing"

    def test_same_day(self):
        today = date(2026, 4, 5)
        result = _check("test", "2026-04-05", today, stale_days=3)
        assert result["status"] == "active"
        assert result["days_ago"] == 0


# ════════════════════════════════════════════════════════════════
# Full check_data_sources
# ════════════════════════════════════════════════════════════════


class TestCheckDataSources:
    def _insert_health(self, db, day, **kwargs):
        defaults = {"date": day, "resting_heart_rate": 55}
        defaults.update(kwargs)
        cols = ", ".join(defaults.keys())
        placeholders = ", ".join(["?"] * len(defaults))
        db.execute(f"INSERT OR REPLACE INTO daily_health ({cols}) VALUES ({placeholders})",
                   list(defaults.values()))
        db.commit()

    def _insert_activity(self, db, day, **kwargs):
        defaults = {"id": f"act-{day}", "date": day, "type": "running", "name": "Run"}
        defaults.update(kwargs)
        cols = ", ".join(defaults.keys())
        placeholders = ", ".join(["?"] * len(defaults))
        db.execute(f"INSERT INTO activities ({cols}) VALUES ({placeholders})",
                   list(defaults.values()))
        db.commit()

    def _insert_weight(self, db, day, weight=78.0):
        db.execute("INSERT INTO body_comp (date, weight_kg) VALUES (?, ?)", (day, weight))
        db.commit()

    def _insert_checkin(self, db, day):
        db.execute("INSERT INTO checkins (date, hydration) VALUES (?, 'OK')", (day,))
        db.commit()

    # Happy
    def test_all_sources_active(self, db):
        today = date.today().isoformat()
        self._insert_health(db, today, avg_spo2=97, hrv_status="balanced",
                            training_readiness=70)
        self._insert_activity(db, today, subtype="auto_detected", id="act-moveiq")
        self._insert_weight(db, today)
        self._insert_checkin(db, today)
        results = check_data_sources(db)
        source_map = {r["source"]: r["status"] for r in results}
        assert source_map["garmin_health"] == "active"
        assert source_map["garmin_activities"] == "active"
        assert source_map["spo2"] == "active"
        assert source_map["weight"] == "active"
        assert source_map["checkins"] == "active"

    def test_returns_list(self, db):
        results = check_data_sources(db)
        assert isinstance(results, list)
        assert len(results) > 0

    # Unhappy
    def test_all_missing_empty_db(self, db):
        """With empty tables (no user data), most sources should be missing or stale.
        Note: backfill migrations may populate some data from legacy sources."""
        results = check_data_sources(db)
        # At minimum, the function should return entries for all known sources
        sources = {r["source"] for r in results}
        assert "garmin_health" in sources
        assert "garmin_activities" in sources
        assert "spo2" in sources
        assert "weight" in sources
        assert "checkins" in sources

    def test_garmin_health_stale_at_4_days(self, db):
        stale_date = (date.today() - timedelta(days=4)).isoformat()
        self._insert_health(db, stale_date)
        results = check_data_sources(db)
        health = [r for r in results if r["source"] == "garmin_health"][0]
        assert health["status"] == "stale"

    def test_garmin_health_active_at_3_days(self, db):
        recent_date = (date.today() - timedelta(days=3)).isoformat()
        self._insert_health(db, recent_date)
        results = check_data_sources(db)
        health = [r for r in results if r["source"] == "garmin_health"][0]
        assert health["status"] == "active"

    def test_garmin_activities_stale_at_8_days(self, db):
        stale_date = (date.today() - timedelta(days=8)).isoformat()
        self._insert_activity(db, stale_date)
        results = check_data_sources(db)
        activities = [r for r in results if r["source"] == "garmin_activities"][0]
        assert activities["status"] == "stale"

    def test_garmin_activities_active_at_7_days(self, db):
        recent_date = (date.today() - timedelta(days=7)).isoformat()
        self._insert_activity(db, recent_date)
        results = check_data_sources(db)
        activities = [r for r in results if r["source"] == "garmin_activities"][0]
        assert activities["status"] == "active"

    def test_spo2_all_null(self, db):
        """SpO2 all NULL in recent 14 days → missing."""
        today = date.today().isoformat()
        self._insert_health(db, today, avg_spo2=None)
        results = check_data_sources(db)
        spo2 = [r for r in results if r["source"] == "spo2"][0]
        assert spo2["status"] == "missing"
        assert spo2["instruction"] is not None

    def test_spo2_present(self, db):
        today = date.today().isoformat()
        self._insert_health(db, today, avg_spo2=97)
        results = check_data_sources(db)
        spo2 = [r for r in results if r["source"] == "spo2"][0]
        assert spo2["status"] == "active"

    def test_hrv_status_missing(self, db):
        today = date.today().isoformat()
        self._insert_health(db, today, hrv_status=None)
        results = check_data_sources(db)
        hrv = [r for r in results if r["source"] == "hrv_status"][0]
        assert hrv["status"] == "missing"

    def test_hrv_status_present(self, db):
        today = date.today().isoformat()
        self._insert_health(db, today, hrv_status="balanced")
        results = check_data_sources(db)
        hrv = [r for r in results if r["source"] == "hrv_status"][0]
        assert hrv["status"] == "active"

    def test_training_readiness_missing(self, db):
        today = date.today().isoformat()
        self._insert_health(db, today, training_readiness=None)
        results = check_data_sources(db)
        tr = [r for r in results if r["source"] == "training_readiness"][0]
        assert tr["status"] == "missing"

    def test_training_readiness_present(self, db):
        today = date.today().isoformat()
        self._insert_health(db, today, training_readiness=70)
        results = check_data_sources(db)
        tr = [r for r in results if r["source"] == "training_readiness"][0]
        assert tr["status"] == "active"

    def test_move_iq_missing(self, db):
        """No auto_detected activities → move_iq missing."""
        today = date.today().isoformat()
        self._insert_activity(db, today, subtype="manual")
        results = check_data_sources(db)
        miq = [r for r in results if r["source"] == "move_iq"][0]
        assert miq["status"] == "missing"

    def test_move_iq_present(self, db):
        today = date.today().isoformat()
        self._insert_activity(db, today, subtype="auto_detected", id="act-miq")
        results = check_data_sources(db)
        miq = [r for r in results if r["source"] == "move_iq"][0]
        assert miq["status"] == "active"

    def test_weight_stale(self, db):
        stale_date = (date.today() - timedelta(days=8)).isoformat()
        self._insert_weight(db, stale_date)
        results = check_data_sources(db)
        weight = [r for r in results if r["source"] == "weight"][0]
        assert weight["status"] == "stale"

    def test_checkins_stale_at_3_days(self, db):
        """Checkin stale_days=2, so 3 days ago is stale."""
        stale_date = (date.today() - timedelta(days=3)).isoformat()
        # Clear any backfill data first
        db.execute("DELETE FROM checkins")
        db.commit()
        self._insert_checkin(db, stale_date)
        results = check_data_sources(db)
        checkins = [r for r in results if r["source"] == "checkins"][0]
        assert checkins["status"] == "stale"

    def test_checkins_active(self, db):
        today = date.today().isoformat()
        self._insert_checkin(db, today)
        results = check_data_sources(db)
        checkins = [r for r in results if r["source"] == "checkins"][0]
        assert checkins["status"] == "active"

    def test_missing_sources_have_instructions(self, db):
        """Missing sources with known instructions should have them."""
        today = date.today().isoformat()
        self._insert_health(db, today, avg_spo2=None, hrv_status=None,
                            training_readiness=None)
        results = check_data_sources(db)
        spo2 = [r for r in results if r["source"] == "spo2"][0]
        assert spo2["instruction"] is not None
        assert "Pulse Ox" in spo2["instruction"]

    def test_mixed_fresh_and_stale(self, db):
        """Some sources fresh, some stale."""
        today = date.today().isoformat()
        stale = (date.today() - timedelta(days=30)).isoformat()
        self._insert_health(db, today, avg_spo2=97, training_readiness=70)
        self._insert_activity(db, stale)
        results = check_data_sources(db)
        source_map = {r["source"]: r["status"] for r in results}
        assert source_map["garmin_health"] == "active"
        assert source_map["garmin_activities"] == "stale"
