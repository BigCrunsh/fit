"""Tests for fit/alerts.py — threshold rules engine."""

from datetime import date, timedelta

from fit.alerts import run_alerts, get_recent_alerts, severity_of


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

    def test_readiness_gate_names_the_driver_when_factors_are_stored(self, db, config):
        # "Rest or very easy activity only" with no reason attached is what made a
        # recovery-time countdown read as accumulated fatigue. Garmin rates the
        # inputs; the message must say which one is low.
        db.execute("INSERT INTO daily_health (date, training_readiness, readiness_level, "
                   "readiness_recovery_time_min, readiness_recovery_factor_pct, "
                   "readiness_hrv_factor_pct, readiness_acwr_factor_pct, "
                   "readiness_sleep_history_pct, readiness_stress_history_pct) "
                   "VALUES (date('now'), 1, 'POOR', 3849, 16, 76, 85, 83, 77)")
        db.commit()
        msg = next(a for a in run_alerts(db, config) if a["type"] == "readiness_gate")["message"]
        assert "recovery time" in msg and "64h" in msg
        assert "Readiness is 1" in msg          # the original claim is unchanged

    def test_readiness_gate_message_unchanged_without_factors(self, db, config):
        # Rows synced before the factor columns existed have nothing to explain
        # with; the message must not gain an invented cause.
        self._setup_health(db, readiness=20)
        msg = next(a for a in run_alerts(db, config) if a["type"] == "readiness_gate")["message"]
        assert "Readiness is 20" in msg
        assert "lowest-rated input" not in msg

    def test_readiness_gate_data_context_carries_the_driver(self, db, config):
        db.execute("INSERT INTO daily_health (date, training_readiness, "
                   "readiness_recovery_time_min, readiness_recovery_factor_pct, "
                   "readiness_hrv_factor_pct) VALUES (date('now'), 1, 3849, 16, 76)")
        db.commit()
        a = next(a for a in run_alerts(db, config) if a["type"] == "readiness_gate")
        assert a["data"]["driver"] == "recovery time"
        assert a["data"]["recovery_time_h"] == 64

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

    def test_every_fired_alert_carries_severity(self, db, config):
        """Every alert returned by run_alerts MUST include a severity field —
        critical / warning / info, never absent."""
        self._setup_health(db, readiness=20)
        self._setup_weekly(db, z12_pct=10)
        alerts = run_alerts(db, config)
        for a in alerts:
            assert "severity" in a, f"alert {a['type']!r} missing severity"
            assert a["severity"] in {"critical", "warning", "info"}

    def test_readiness_gate_is_critical(self, db, config):
        self._setup_health(db, readiness=20)
        alerts = [a for a in run_alerts(db, config) if a["type"] == "readiness_gate"]
        assert alerts and alerts[0]["severity"] == "critical"

    def test_all_runs_too_hard_is_warning(self, db, config):
        self._setup_weekly(db, z12_pct=10)
        alerts = [a for a in run_alerts(db, config) if a["type"] == "all_runs_too_hard"]
        assert alerts and alerts[0]["severity"] == "warning"

    def test_severity_of_unknown_defaults_to_info(self):
        """severity_of() never returns absent — unknown rules default to info."""
        assert severity_of("some_future_rule") == "info"


class TestWellnessAlerts:
    """Baseline-deviation rules: respiration_elevated / rhr_elevated / recovery_cliff."""

    @staticmethod
    def _day(offset):
        return (date.today() - timedelta(days=offset)).isoformat()

    def _insert(self, db, offset, **cols):
        keys = ["date"] + list(cols.keys())
        vals = [self._day(offset)] + list(cols.values())
        db.execute(
            f"INSERT INTO daily_health ({','.join(keys)}) VALUES ({','.join('?' * len(vals))})",
            vals,
        )

    def _baseline(self, db, start_offset, days, **cols):
        for i in range(days):
            self._insert(db, start_offset + i, **cols)
        db.commit()

    # respiration_elevated

    def test_respiration_elevated_fires_warning(self, db, config):
        self._baseline(db, 2, 28, avg_sleep_respiration=15.0)
        self._insert(db, 1, avg_sleep_respiration=17.2)
        self._insert(db, 0, avg_sleep_respiration=17.5)
        db.commit()
        fired = [a for a in run_alerts(db, config) if a["type"] == "respiration_elevated"]
        assert fired and fired[0]["severity"] == "warning"
        assert "15.0" in fired[0]["message"]  # baseline named in the message

    def test_respiration_single_night_does_not_fire(self, db, config):
        self._baseline(db, 2, 28, avg_sleep_respiration=15.0)
        self._insert(db, 1, avg_sleep_respiration=15.1)
        self._insert(db, 0, avg_sleep_respiration=18.0)
        db.commit()
        assert not [a for a in run_alerts(db, config) if a["type"] == "respiration_elevated"]

    def test_respiration_no_baseline_does_not_fire(self, db, config):
        self._baseline(db, 2, 5, avg_sleep_respiration=15.0)  # 5 obs < 14
        self._insert(db, 1, avg_sleep_respiration=19.0)
        self._insert(db, 0, avg_sleep_respiration=19.0)
        db.commit()
        assert not [a for a in run_alerts(db, config) if a["type"] == "respiration_elevated"]

    def test_respiration_auto_dismisses_when_normalized(self, db, config):
        self._baseline(db, 2, 28, avg_sleep_respiration=15.0)
        self._insert(db, 1, avg_sleep_respiration=17.5)
        self._insert(db, 0, avg_sleep_respiration=17.5)
        db.commit()
        run_alerts(db, config)
        # condition holds right after firing (fire/dismiss parity)
        assert any(a["type"] == "respiration_elevated" for a in get_recent_alerts(db))
        # respiration normalizes → auto-dismissed
        db.execute("UPDATE daily_health SET avg_sleep_respiration = 15.0 WHERE date >= ?", (self._day(1),))
        db.commit()
        assert not any(a["type"] == "respiration_elevated" for a in get_recent_alerts(db))

    # rhr_elevated

    def test_rhr_elevated_fires_after_three_days(self, db, config):
        self._baseline(db, 3, 28, resting_heart_rate=55)
        self._insert(db, 2, resting_heart_rate=61)
        self._insert(db, 1, resting_heart_rate=60)
        self._insert(db, 0, resting_heart_rate=62)
        db.commit()
        fired = [a for a in run_alerts(db, config) if a["type"] == "rhr_elevated"]
        assert fired and fired[0]["severity"] == "warning"

    def test_rhr_two_days_does_not_fire(self, db, config):
        self._baseline(db, 2, 28, resting_heart_rate=55)
        self._insert(db, 1, resting_heart_rate=61)
        self._insert(db, 0, resting_heart_rate=62)
        db.commit()
        assert not [a for a in run_alerts(db, config) if a["type"] == "rhr_elevated"]

    # recovery_cliff

    def _cliff(self, db, rhr=62, hrv_status="LOW", readiness=38):
        self._baseline(db, 1, 28, resting_heart_rate=55, hrv_last_night=40.0)
        self._insert(db, 0, resting_heart_rate=rhr, hrv_status=hrv_status,
                     training_readiness=readiness)
        db.commit()

    def test_recovery_cliff_fires_critical(self, db, config):
        self._cliff(db)
        fired = [a for a in run_alerts(db, config) if a["type"] == "recovery_cliff"]
        assert fired and fired[0]["severity"] == "critical"

    def test_recovery_cliff_two_of_three_does_not_fire(self, db, config):
        self._cliff(db, hrv_status="BALANCED")
        assert not [a for a in run_alerts(db, config) if a["type"] == "recovery_cliff"]

    def test_recovery_cliff_auto_dismisses_on_recovery(self, db, config):
        self._cliff(db)
        run_alerts(db, config)
        assert any(a["type"] == "recovery_cliff" for a in get_recent_alerts(db))
        db.execute("UPDATE daily_health SET training_readiness = 80, hrv_status = 'BALANCED' WHERE date = ?",
                   (self._day(0),))
        db.commit()
        assert not any(a["type"] == "recovery_cliff" for a in get_recent_alerts(db))

    def test_empty_db_no_wellness_alerts_no_crash(self, db, config):
        alerts = run_alerts(db, config)
        assert not [a for a in alerts
                    if a["type"] in ("respiration_elevated", "rhr_elevated", "recovery_cliff")]


class TestSeveritySort:
    def _fire_alert(self, db, alert_date, alert_type, message="msg"):
        db.execute(
            "INSERT INTO alerts (date, type, message, data_context, acknowledged) VALUES (?, ?, ?, '{}', 0)",
            (alert_date, alert_type, message),
        )
        db.commit()

    def test_severity_sort_critical_above_warning(self, db, config):
        # Fire one of each, store with same date so severity decides order.
        today = date.today().isoformat()
        self._fire_alert(db, today, "all_runs_too_hard")     # warning
        # Mock condition: insert weekly_agg matching the rule's predicate
        db.execute("INSERT INTO weekly_agg (week, z12_pct) VALUES ('2026-W14', 10)")
        # Now fire a critical
        self._fire_alert(db, today, "readiness_gate")
        db.execute("INSERT INTO daily_health (date, training_readiness) VALUES (date('now'), 20)")
        db.commit()
        result = get_recent_alerts(db)
        # Both should appear, critical first
        types = [a["type"] for a in result]
        idx_critical = types.index("readiness_gate")
        idx_warning = types.index("all_runs_too_hard")
        assert idx_critical < idx_warning

    def test_dedupe_to_most_recent_per_type(self, db, config):
        """If a rule fired twice (yesterday + today), only one row shows."""
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        today = date.today().isoformat()
        self._fire_alert(db, yesterday, "all_runs_too_hard", "old")
        self._fire_alert(db, today, "all_runs_too_hard", "new")
        db.execute("INSERT INTO weekly_agg (week, z12_pct) VALUES ('2026-W14', 10)")
        db.commit()
        result = get_recent_alerts(db)
        same_type = [a for a in result if a["type"] == "all_runs_too_hard"]
        assert len(same_type) == 1
        assert same_type[0]["message"] == "new"


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


class TestACWRRollingAlert:
    """ACWR alert uses rolling 7-day window — no day-of-week suppression."""

    def test_undertraining_fires_any_day(self, db, config):
        """ACWR undertraining alert fires when rolling ACWR < 0.6, regardless of day of week."""
        today = date.today()
        # Build 4 weeks of chronic history with decent total_load
        # Start from w+2 so nearest chronic week doesn't overlap rolling 7-day window
        for w in range(4):
            monday = today - timedelta(days=today.weekday()) - timedelta(weeks=w + 2)
            week_label = f"{monday.isocalendar()[0]}-W{monday.isocalendar()[1]:02d}"
            db.execute(
                "INSERT INTO weekly_agg (week, run_km, run_count, z12_pct, total_load) "
                "VALUES (?, 40, 4, 80, 200)",
                (week_label,),
            )
            # Insert activities for those weeks
            for d in range(4):
                run_date = (monday + timedelta(days=d)).isoformat()
                db.execute(
                    "INSERT INTO activities (id, date, type, distance_km, duration_min, avg_hr, training_load) "
                    "VALUES (?, ?, 'running', 10, 60, 140, 50)",
                    (f"act-{w}-{d}", run_date),
                )

        # Current rolling 7 days: only 1 short run → low acute load → ACWR < 0.6
        recent_date = (today - timedelta(days=2)).isoformat()
        db.execute(
            "INSERT INTO activities (id, date, type, distance_km, duration_min, avg_hr, training_load) "
            "VALUES ('act-recent', ?, 'running', 3, 20, 130, 15)",
            (recent_date,),
        )
        db.commit()

        alerts = run_alerts(db, config)
        types = [a["type"] for a in alerts]
        assert "undertraining" in types

    def test_no_undertraining_when_acwr_ok(self, db, config):
        """No undertraining alert when rolling ACWR is in safe range."""
        today = date.today()
        # Build 4 weeks of moderate chronic history
        for w in range(4):
            monday = today - timedelta(days=today.weekday()) - timedelta(weeks=w + 1)
            week_label = f"{monday.isocalendar()[0]}-W{monday.isocalendar()[1]:02d}"
            db.execute(
                "INSERT INTO weekly_agg (week, run_km, run_count, z12_pct, total_load) "
                "VALUES (?, 30, 3, 80, 150)",
                (week_label,),
            )
            for d in range(3):
                run_date = (monday + timedelta(days=d)).isoformat()
                db.execute(
                    "INSERT INTO activities (id, date, type, distance_km, duration_min, avg_hr, training_load) "
                    "VALUES (?, ?, 'running', 10, 60, 140, 50)",
                    (f"act-ok-{w}-{d}", run_date),
                )

        # Current 7 days: similar volume → ACWR ~1.0
        for d in range(3):
            run_date = (today - timedelta(days=d + 1)).isoformat()
            db.execute(
                "INSERT INTO activities (id, date, type, distance_km, duration_min, avg_hr, training_load) "
                "VALUES (?, ?, 'running', 10, 60, 140, 50)",
                (f"act-curr-{d}", run_date),
            )
        db.commit()

        alerts = run_alerts(db, config)
        types = [a["type"] for a in alerts]
        assert "undertraining" not in types


class TestMonotonyRollingAlert:
    """high_monotony reads rolling-7d monotony (window policy §4.1), not weekly_agg."""

    def _insert_daily_runs(self, db, loads):
        """One run per day across the rolling 7-day window (today-6..today)."""
        today = date.today()
        for i, load in enumerate(loads):
            d = (today - timedelta(days=i)).isoformat()
            db.execute(
                "INSERT INTO activities (id, date, type, distance_km, duration_min, avg_hr, training_load) "
                "VALUES (?, ?, 'running', 8, 50, 140, ?)",
                (f"mono-{i}", d, load),
            )
        db.commit()

    def test_fires_from_rolling_when_uniform_load(self, db, config):
        # Near-uniform load across all 7 days → high monotony (>2.0). No weekly_agg row
        # is inserted, so a fire proves the rule reads compute_rolling_week, not the store.
        self._insert_daily_runs(db, [50, 50, 50, 50, 50, 50, 55])
        types = [a["type"] for a in run_alerts(db, config)]
        assert "high_monotony" in types

    def test_not_fire_when_varied(self, db, config):
        # Hard/rest mix → high day-to-day variance → low monotony (<2.0).
        self._insert_daily_runs(db, [100, 0, 0, 80, 0, 0, 30])
        types = [a["type"] for a in run_alerts(db, config)]
        assert "high_monotony" not in types

    def test_no_fire_on_empty_window(self, db, config):
        # No activities → monotony undefined (stdev 0) → no alert, no crash.
        types = [a["type"] for a in run_alerts(db, config)]
        assert "high_monotony" not in types

    def test_auto_dismiss_when_monotony_drops(self, db, config):
        # A stale high_monotony alert is dismissed once the rolling window varies —
        # fire and dismiss share the same rolling source, so they stay aligned.
        db.execute("INSERT INTO alerts (date, type, message) VALUES (date('now'), 'high_monotony', 'Monotony is 2.6')")
        self._insert_daily_runs(db, [100, 0, 0, 80, 0, 0, 30])
        alerts = get_recent_alerts(db)
        assert "high_monotony" not in [a["type"] for a in alerts]
        ack = db.execute("SELECT acknowledged FROM alerts WHERE type = 'high_monotony'").fetchone()
        assert ack["acknowledged"] == 1
