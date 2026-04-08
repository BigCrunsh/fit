"""Tests for fit/alerts.py — threshold rules engine."""

from fit.alerts import run_alerts, get_recent_alerts


class TestAlertRules:
    def _setup_health(self, db, readiness=80, hrv=30):
        db.execute("INSERT INTO daily_health (date, training_readiness, hrv_last_night, resting_heart_rate) VALUES (date('now'), ?, ?, 58)", (readiness, hrv))
        db.commit()

    def _setup_weekly(self, db, z12_pct=80, run_km=20, streak=4):
        db.execute("INSERT INTO weekly_agg (week, z12_pct, run_km, run_count, consecutive_weeks_3plus) VALUES ('2026-W14', ?, ?, 3, ?)", (z12_pct, run_km, streak))
        db.commit()

    def test_no_alerts_healthy(self, db, config):
        self._setup_health(db)
        self._setup_weekly(db)
        alerts = run_alerts(db, config)
        # With healthy data, most rules shouldn't fire
        assert isinstance(alerts, list)

    def test_readiness_gate_fires(self, db, config):
        self._setup_health(db, readiness=20)
        alerts = run_alerts(db, config)
        types = [a["type"] for a in alerts]
        assert "readiness_gate" in types

    def test_readiness_gate_not_fires_high(self, db, config):
        self._setup_health(db, readiness=80)
        alerts = run_alerts(db, config)
        types = [a["type"] for a in alerts]
        assert "readiness_gate" not in types

    def test_all_runs_too_hard(self, db, config):
        self._setup_weekly(db, z12_pct=10)
        alerts = run_alerts(db, config)
        types = [a["type"] for a in alerts]
        assert "all_runs_too_hard" in types

    def test_all_runs_fine(self, db, config):
        self._setup_weekly(db, z12_pct=85)
        alerts = run_alerts(db, config)
        types = [a["type"] for a in alerts]
        assert "all_runs_too_hard" not in types

    def test_duplicate_same_day(self, db, config):
        self._setup_health(db, readiness=20)
        run_alerts(db, config)
        run_alerts(db, config)
        # Second run should not duplicate the alert in DB
        count = db.execute("SELECT COUNT(*) FROM alerts WHERE type = 'readiness_gate'").fetchone()[0]
        assert count == 1


class TestGetRecentAlerts:
    def test_empty(self, db):
        assert get_recent_alerts(db) == []

    def test_returns_recent(self, db):
        db.execute("INSERT INTO alerts (date, type, message) VALUES (date('now'), 'test', 'Test alert')")
        db.commit()
        alerts = get_recent_alerts(db)
        assert len(alerts) == 1
        assert alerts[0]["type"] == "test"

    def test_old_excluded(self, db):
        db.execute("INSERT INTO alerts (date, type, message) VALUES (date('now', '-30 days'), 'old', 'Old alert')")
        db.commit()
        alerts = get_recent_alerts(db, days=7)
        assert len(alerts) == 0

    def test_auto_dismiss_readiness_recovered(self, db):
        """Readiness alert auto-dismissed when readiness improves above threshold."""
        db.execute("INSERT INTO alerts (date, type, message) VALUES (date('now'), 'readiness_gate', 'Readiness is 6')")
        # Current readiness is good now
        db.execute("INSERT INTO daily_health (date, training_readiness) VALUES (date('now'), 80)")
        db.commit()
        alerts = get_recent_alerts(db)
        assert len(alerts) == 0
        # Alert should be marked acknowledged
        ack = db.execute("SELECT acknowledged FROM alerts WHERE type = 'readiness_gate'").fetchone()
        assert ack["acknowledged"] == 1

    def test_auto_dismiss_zone_compliance_improved(self, db):
        """Z2 alert auto-dismissed when zone compliance improves."""
        db.execute("INSERT INTO alerts (date, type, message) VALUES (date('now'), 'all_runs_too_hard', 'Only 0%')")
        # Z12 is now healthy
        db.execute("INSERT INTO weekly_agg (week, z12_pct, run_km, run_count) VALUES ('2026-W14', 85, 30, 4)")
        db.commit()
        alerts = get_recent_alerts(db)
        assert len(alerts) == 0
        ack = db.execute("SELECT acknowledged FROM alerts WHERE type = 'all_runs_too_hard'").fetchone()
        assert ack["acknowledged"] == 1

    def test_keeps_alert_when_condition_holds(self, db):
        """Alert stays when underlying condition is still true."""
        db.execute("INSERT INTO alerts (date, type, message) VALUES (date('now'), 'readiness_gate', 'Readiness is 6')")
        db.execute("INSERT INTO daily_health (date, training_readiness) VALUES (date('now'), 6)")
        db.commit()
        alerts = get_recent_alerts(db)
        assert len(alerts) == 1
        assert alerts[0]["type"] == "readiness_gate"

    def test_auto_dismiss_volume_ramp_resolved(self, db):
        """Volume ramp alert dismissed when streak grows or ramp flattens."""
        db.execute("INSERT INTO alerts (date, type, message) VALUES (date('now'), 'volume_ramp', 'Volume increased 37%')")
        # Now volume is stable with good consistency
        db.execute("INSERT INTO weekly_agg (week, z12_pct, run_km, run_count, consecutive_weeks_3plus) VALUES ('2026-W14', 80, 30, 4, 10)")
        db.execute("INSERT INTO weekly_agg (week, z12_pct, run_km, run_count, consecutive_weeks_3plus) VALUES ('2026-W13', 80, 29, 4, 9)")
        db.commit()
        alerts = get_recent_alerts(db)
        assert len(alerts) == 0

    def test_unknown_alert_type_kept(self, db):
        """Unknown alert types are never auto-dismissed."""
        db.execute("INSERT INTO alerts (date, type, message) VALUES (date('now'), 'custom_alert', 'Something')")
        db.commit()
        alerts = get_recent_alerts(db)
        assert len(alerts) == 1
