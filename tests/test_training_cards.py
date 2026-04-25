"""Tests for Training tab hero card and objectives (cards.py)."""

from datetime import date, timedelta

from fit.report.sections.cards import (
    _coaching, _last_7_days_hero, _last_7_days_runs, _training_objectives,
    _weekly_plan_adherence,
)


class TestLast7DaysHero:
    def test_returns_rolling_volume(self, db, config):
        """Hero card should show rolling 7d volume from activities."""
        today = date.today()
        for i in range(3):
            d = (today - timedelta(days=i + 1)).isoformat()
            db.execute(
                "INSERT INTO activities (id, date, type, distance_km, duration_min, avg_hr) "
                "VALUES (?, ?, 'running', 10, 60, 140)",
                (f"hero-{i}", d),
            )
        db.commit()

        hero = _last_7_days_hero(db, config=config)
        assert hero["volume_km"] == 30
        assert hero["run_count"] == 3

    def test_no_activities(self, db, config):
        """Hero card handles empty activity list."""
        hero = _last_7_days_hero(db, config=config)
        assert hero["volume_km"] == 0
        assert hero["run_count"] == 0
        assert hero["compliance_pct"] is None

    def test_compliance_with_plan(self, db, config):
        """Compliance ring shows planned vs completed."""
        today = date.today()
        for i in range(3):
            d = (today - timedelta(days=i + 1)).isoformat()
            db.execute(
                "INSERT INTO planned_workouts (date, workout_name, workout_type, status) "
                "VALUES (?, 'Easy Run', 'easy', 'active')",
                (d,),
            )
            if i < 2:  # 2 of 3 completed
                db.execute(
                    "INSERT INTO activities (id, date, type, distance_km, duration_min, avg_hr) "
                    "VALUES (?, ?, 'running', 8, 50, 135)",
                    (f"plan-{i}", d),
                )
        db.commit()

        hero = _last_7_days_hero(db, config=config)
        assert hero["compliance_total"] == 3
        assert hero["compliance_completed"] == 2
        assert hero["compliance_pct"] == 67

    def test_volume_target_from_phase(self, db, config):
        """Volume progress bar uses active phase targets."""
        today = date.today()
        db.execute("INSERT INTO goals (id, name, type, active) VALUES (1, 'Test', 'marathon', 1)")
        db.execute(
            "INSERT INTO training_phases (goal_id, phase, name, start_date, "
            "weekly_km_min, weekly_km_max, status) "
            "VALUES (1, 'P1', 'Base', ?, 25, 35, 'active')",
            (today.isoformat(),),
        )
        db.execute(
            "INSERT INTO activities (id, date, type, distance_km, duration_min, avg_hr) "
            "VALUES ('vol1', ?, 'running', 15, 90, 140)",
            ((today - timedelta(days=1)).isoformat(),),
        )
        db.commit()

        hero = _last_7_days_hero(db, config=config)
        assert hero["volume_target_km"] == 30  # midpoint of 25-35
        assert hero["volume_pct"] == 50  # 15/30 * 100


class TestTrainingObjectives:
    def test_deactivated_without_race(self, db):
        """Without target race, all slots are deactivated."""
        result = _training_objectives(db)
        assert result["active"] is False
        assert len(result["slots"]) == 4
        assert all(s["status"] == "deactivated" for s in result["slots"])
        assert "fit target set" in result["prompt"]

    def test_active_with_race_and_goals(self, db):
        """With target race and derived goals, slots show current vs target."""
        today = date.today()
        future = (today + timedelta(days=120)).isoformat()
        db.execute(
            "INSERT INTO race_calendar (id, date, name, distance, distance_km, status) "
            "VALUES (1, ?, 'Marathon', 'Marathon', 42.195, 'registered')",
            (future,),
        )
        # Auto-derived goals (simulating what set_target_race would create)
        db.execute(
            "INSERT INTO goals (id, name, type, target_value, target_unit, "
            "race_id, active, derivation_source) "
            "VALUES (1, 'Peak volume 50-65km/wk', 'metric', 65, 'km/week', 1, 1, 'auto_distance')"
        )
        db.execute(
            "INSERT INTO goals (id, name, type, target_value, target_unit, "
            "race_id, active, derivation_source) "
            "VALUES (2, 'Long run 32km', 'metric', 32, 'km', 1, 1, 'auto_distance')"
        )
        db.execute(
            "INSERT INTO goals (id, name, type, target_value, target_unit, "
            "race_id, active, derivation_source) "
            "VALUES (3, 'Z2 compliance ≥80%', 'metric', 80, '%%', 1, 1, 'auto_distance')"
        )
        db.execute(
            "INSERT INTO goals (id, name, type, target_value, target_unit, "
            "race_id, active, derivation_source) "
            "VALUES (4, 'Consistency 12wk', 'habit', 12, 'consecutive_weeks', 1, 1, 'auto_timeline')"
        )
        # Some current data
        db.execute(
            "INSERT INTO activities (id, date, type, distance_km, duration_min, avg_hr) "
            "VALUES ('obj1', ?, 'running', 20, 120, 140)",
            ((today - timedelta(days=1)).isoformat(),),
        )
        db.execute(
            "INSERT INTO weekly_agg (week, run_km, run_count, consecutive_weeks_3plus) "
            "VALUES ('2026-W14', 40, 4, 8)"
        )
        db.commit()

        result = _training_objectives(db)
        assert result["active"] is True
        assert len(result["slots"]) == 4
        names = [s["name"] for s in result["slots"]]
        assert names == ["Volume", "Long Run", "Z2 Compliance", "Consistency"]

    def test_slot_names_always_4(self, db):
        """Always returns exactly 4 slots regardless of goal data."""
        result = _training_objectives(db)
        assert len(result["slots"]) == 4


class TestLast7DaysRuns:
    def test_multiple_runs(self, db):
        """Returns runs from last 7 days with correct fields."""
        today = date.today()
        for i in range(3):
            d = (today - timedelta(days=i + 1)).isoformat()
            db.execute(
                "INSERT INTO activities (id, date, type, name, distance_km, "
                "duration_min, pace_sec_per_km, avg_hr, hr_zone, run_type, "
                "effort_class, training_load) "
                "VALUES (?, ?, 'running', 'Easy Run', 8, 50, 375, 130, 'Z2', "
                "'easy', 'Easy', 120)",
                (f"run7d-{i}", d),
            )
        db.commit()

        runs = _last_7_days_runs(db)
        assert len(runs) == 3
        assert runs[0]["distance_km"] == 8
        assert runs[0]["pace"] == "6:15"
        assert runs[0]["hr_zone"] == "Z2"

    def test_no_runs(self, db):
        """Returns empty list when no runs in window."""
        runs = _last_7_days_runs(db)
        assert runs == []

    def test_plan_comparison_too_fast(self, db):
        """Flags 'too fast' when easy plan but Z3+ HR."""
        today = date.today()
        d = (today - timedelta(days=1)).isoformat()
        db.execute(
            "INSERT INTO planned_workouts (date, workout_name, workout_type, status) "
            "VALUES (?, 'Easy Recovery', 'easy', 'active')",
            (d,),
        )
        db.execute(
            "INSERT INTO activities (id, date, type, name, distance_km, "
            "duration_min, pace_sec_per_km, avg_hr, hr_zone, run_type) "
            "VALUES ('fast1', ?, 'running', 'Morning Run', 10, 55, 330, 155, 'Z3', 'tempo')",
            (d,),
        )
        db.commit()

        runs = _last_7_days_runs(db)
        assert len(runs) == 1
        assert runs[0]["plan_comparison"] is not None
        assert runs[0]["plan_comparison"]["verdict"] == "too fast"

    def test_plan_comparison_on_target(self, db):
        """On target when easy plan and Z2 HR."""
        today = date.today()
        d = (today - timedelta(days=1)).isoformat()
        db.execute(
            "INSERT INTO planned_workouts (date, workout_name, workout_type, status) "
            "VALUES (?, 'Easy Run', 'easy', 'active')",
            (d,),
        )
        db.execute(
            "INSERT INTO activities (id, date, type, name, distance_km, "
            "duration_min, pace_sec_per_km, avg_hr, hr_zone, run_type) "
            "VALUES ('easy1', ?, 'running', 'Easy Run', 8, 50, 375, 128, 'Z2', 'easy')",
            (d,),
        )
        db.commit()

        runs = _last_7_days_runs(db)
        assert runs[0]["plan_comparison"]["verdict"] == "on target"

    def test_excludes_old_runs(self, db):
        """Runs older than 7 days are excluded."""
        d = (date.today() - timedelta(days=10)).isoformat()
        db.execute(
            "INSERT INTO activities (id, date, type, name, distance_km, "
            "duration_min, avg_hr) "
            "VALUES ('old1', ?, 'running', 'Old Run', 10, 60, 140)",
            (d,),
        )
        db.commit()

        runs = _last_7_days_runs(db)
        assert len(runs) == 0


    def test_plan_match_via_garmin_id(self, db):
        """Garmin workout ID link takes priority over type match."""
        today = date.today()
        d = (today - timedelta(days=1)).isoformat()
        # Two plans for the same day
        db.execute(
            "INSERT INTO planned_workouts (date, workout_name, workout_type, "
            "garmin_workout_id, status) "
            "VALUES (?, 'Intervals', 'intervals', 'act-int', 'completed')",
            (d,),
        )
        db.execute(
            "INSERT INTO planned_workouts (date, workout_name, workout_type, "
            "garmin_workout_id, status, sequence_ordinal) "
            "VALUES (?, 'Easy Run', 'easy', NULL, 'active', 2)",
            (d,),
        )
        # Activity matches by Garmin ID
        db.execute(
            "INSERT INTO activities (id, date, type, name, distance_km, "
            "duration_min, pace_sec_per_km, avg_hr, hr_zone, run_type) "
            "VALUES ('act-int', ?, 'running', 'Intervals', 8, 45, 337, 160, 'Z4', 'intervals')",
            (d,),
        )
        db.commit()

        runs = _last_7_days_runs(db)
        assert len(runs) == 1
        assert runs[0]["plan_comparison"]["planned_name"] == "Intervals"
        assert runs[0]["plan_comparison"]["match_method"] == "Garmin workout link"

    def test_race_shows_race_calendar(self, db):
        """Race activity shows race_calendar info, not training plan."""
        today = date.today()
        d = (today - timedelta(days=1)).isoformat()
        # A training plan exists for the day
        db.execute(
            "INSERT INTO planned_workouts (date, workout_name, workout_type, status) "
            "VALUES (?, 'Easy Run', 'easy', 'active')",
            (d,),
        )
        # Race activity
        db.execute(
            "INSERT INTO activities (id, date, type, name, distance_km, "
            "duration_min, pace_sec_per_km, avg_hr, hr_zone, run_type) "
            "VALUES ('race-1', ?, 'running', 'Park Run', 5.0, 22, 264, 175, 'Z5', 'race')",
            (d,),
        )
        # Race calendar entry linked to activity
        db.execute(
            "INSERT INTO race_calendar (name, date, distance, distance_km, "
            "status, activity_id, garmin_time, target_time) "
            "VALUES ('Park Run 5K', ?, '5K', 5.0, 'completed', 'race-1', '0:22:00', '0:21:30')",
            (d,),
        )
        db.commit()

        runs = _last_7_days_runs(db)
        assert len(runs) == 1
        assert runs[0]["plan_comparison"]["verdict"] == "race"
        assert runs[0]["plan_comparison"]["planned_name"] == "Park Run 5K"
        assert runs[0]["plan_comparison"]["race_result"] == "0:22:00"
        assert runs[0]["plan_comparison"]["race_target"] == "0:21:30"

    def test_two_activities_one_plan_garmin_id(self, db):
        """Two activities, one plan with Garmin ID → plan matches linked activity, other is unplanned."""
        today = date.today()
        d = (today - timedelta(days=1)).isoformat()
        db.execute(
            "INSERT INTO planned_workouts (date, workout_name, workout_type, "
            "garmin_workout_id, status) "
            "VALUES (?, 'Intervals', 'intervals', 'act-train', 'completed')",
            (d,),
        )
        db.execute(
            "INSERT INTO activities (id, date, type, name, distance_km, "
            "duration_min, pace_sec_per_km, avg_hr, hr_zone, run_type) "
            "VALUES ('act-train', ?, 'running', 'Intervals', 8, 45, 337, 160, 'Z4', 'intervals')",
            (d,),
        )
        db.execute(
            "INSERT INTO activities (id, date, type, name, distance_km, "
            "duration_min, pace_sec_per_km, avg_hr, hr_zone, run_type) "
            "VALUES ('act-race', ?, 'running', 'Evening Race', 3, 14, 280, 180, 'Z5', 'race')",
            (d,),
        )
        db.execute(
            "INSERT INTO race_calendar (name, date, distance, distance_km, "
            "status, activity_id, garmin_time) "
            "VALUES ('Evening 3K', ?, '3K', 3.0, 'completed', 'act-race', '0:14:00')",
            (d,),
        )
        db.commit()

        runs = _last_7_days_runs(db)
        assert len(runs) == 2
        # Ordered by id DESC: act-train first (higher id string), act-race second
        by_id = {r["name"]: r for r in runs}
        assert by_id["Intervals"]["plan_comparison"]["planned_name"] == "Intervals"
        assert by_id["Intervals"]["plan_comparison"]["match_method"] == "Garmin workout link"
        assert by_id["Evening Race"]["plan_comparison"]["verdict"] == "race"
        assert by_id["Evening Race"]["plan_comparison"]["planned_name"] == "Evening 3K"


    def test_run_card_displays_rpe_feel_compliance(self, db):
        """Per-run card surfaces Garmin-imported RPE/feel/compliance."""
        today = date.today()
        d = (today - timedelta(days=1)).isoformat()
        db.execute(
            "INSERT INTO activities (id, date, type, name, distance_km, "
            "duration_min, pace_sec_per_km, avg_hr, hr_zone, run_type, "
            "rpe, feel, compliance_score) "
            "VALUES ('run-rpe', ?, 'running', 'Easy Run', 8, 50, 375, 130, 'Z2', 'easy', "
            "7, 4, 95)",
            (d,),
        )
        db.commit()

        runs = _last_7_days_runs(db)
        assert len(runs) == 1
        assert runs[0]["rpe"] == 7
        assert runs[0]["feel"] == 4
        assert runs[0]["feel_label"] == "Good"
        assert runs[0]["compliance_score"] == 95

    def test_run_card_handles_null_rpe(self, db):
        """Runs without RPE/feel/compliance get None for all three."""
        today = date.today()
        d = (today - timedelta(days=1)).isoformat()
        db.execute(
            "INSERT INTO activities (id, date, type, name, distance_km, "
            "duration_min, pace_sec_per_km, avg_hr, hr_zone, run_type) "
            "VALUES ('run-no-rpe', ?, 'running', 'Easy Run', 8, 50, 375, 130, 'Z2', 'easy')",
            (d,),
        )
        db.commit()

        runs = _last_7_days_runs(db)
        assert len(runs) == 1
        assert runs[0]["rpe"] is None
        assert runs[0]["feel"] is None
        assert runs[0]["feel_label"] is None
        assert runs[0]["compliance_score"] is None

    def test_run_card_partial_fields(self, db):
        """Partial population — only RPE set, feel/compliance NULL."""
        today = date.today()
        d = (today - timedelta(days=1)).isoformat()
        db.execute(
            "INSERT INTO activities (id, date, type, name, distance_km, "
            "duration_min, pace_sec_per_km, avg_hr, hr_zone, run_type, rpe) "
            "VALUES ('run-part', ?, 'running', 'Run', 5, 30, 360, 140, 'Z2', 'easy', 5)",
            (d,),
        )
        db.commit()

        runs = _last_7_days_runs(db)
        assert runs[0]["rpe"] == 5
        assert runs[0]["feel"] is None
        assert runs[0]["feel_label"] is None
        assert runs[0]["compliance_score"] is None

    def test_run_card_feel_label_mapping(self, db):
        """Feel 1-5 maps to Bad/Poor/Neutral/Good/Great."""
        today = date.today()
        d = (today - timedelta(days=1)).isoformat()
        # Insert one run per feel value
        for feel_val, expected in [(1, "Bad"), (2, "Poor"), (3, "Neutral"),
                                    (4, "Good"), (5, "Great")]:
            db.execute(
                "INSERT INTO activities (id, date, type, name, distance_km, "
                "duration_min, pace_sec_per_km, avg_hr, hr_zone, run_type, feel) "
                "VALUES (?, ?, 'running', 'R', 5, 30, 360, 140, 'Z2', 'easy', ?)",
                (f"feel-{feel_val}", d, feel_val),
            )
        db.commit()

        runs = _last_7_days_runs(db)
        labels = {r["feel"]: r["feel_label"] for r in runs}
        assert labels == {1: "Bad", 2: "Poor", 3: "Neutral", 4: "Good", 5: "Great"}


class TestWeeklyPlanAdherence:
    def test_no_plan_data(self, db):
        """Returns empty list with no planned workouts."""
        result = _weekly_plan_adherence(db)
        assert result == []

    def test_adherence_with_data(self, db):
        """Returns compliance data when plan exists."""
        today = date.today()
        # Insert planned workouts for this week
        monday = today - timedelta(days=today.weekday())
        for d_offset in range(3):
            d = (monday + timedelta(days=d_offset)).isoformat()
            db.execute(
                "INSERT INTO planned_workouts (date, workout_name, workout_type, status) "
                "VALUES (?, 'Run', 'easy', 'active')",
                (d,),
            )
            if d_offset < 2:
                db.execute(
                    "INSERT INTO activities (id, date, type, distance_km, duration_min, avg_hr) "
                    "VALUES (?, ?, 'running', 8, 50, 135)",
                    (f"adh-{d_offset}", d),
                )
        db.commit()

        result = _weekly_plan_adherence(db)
        assert len(result) >= 1
        week = result[0]
        assert "compliance_pct" in week
        assert "color" in week


class TestCoachingStaleness:
    def test_3_day_old_is_fresh(self, db):
        """Coaching notes from 3 days ago should not be stale."""
        import json as _json
        from pathlib import Path

        db_path = db.execute("PRAGMA database_list").fetchone()[2]
        reports_dir = Path(db_path).parent / "reports"
        reports_dir.mkdir(parents=True, exist_ok=True)
        coaching_date = (date.today() - timedelta(days=3)).isoformat()
        (reports_dir / "coaching.json").write_text(_json.dumps({
            "report_date": coaching_date,
            "generated_at": coaching_date + "T12:00:00",
            "insights": [{"type": "info", "title": "Test", "body": "Test body"}],
        }))

        result = _coaching(db)
        assert result is not None
        assert result["stale"] is False

    def test_9_day_old_is_stale(self, db):
        """Coaching notes from 9 days ago should be stale."""
        import json as _json
        from pathlib import Path

        db_path = db.execute("PRAGMA database_list").fetchone()[2]
        reports_dir = Path(db_path).parent / "reports"
        reports_dir.mkdir(parents=True, exist_ok=True)
        coaching_date = (date.today() - timedelta(days=9)).isoformat()
        (reports_dir / "coaching.json").write_text(_json.dumps({
            "report_date": coaching_date,
            "generated_at": coaching_date + "T12:00:00",
            "insights": [{"type": "info", "title": "Test", "body": "Test body"}],
        }))

        result = _coaching(db)
        assert result is not None
        assert result["stale"] is True
