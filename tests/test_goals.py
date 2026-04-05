"""Tests for fit/goals.py — phase lifecycle, compliance, goal logging."""

import json
from datetime import date

import pytest

from fit.goals import (
    complete_phase,
    get_active_phase,
    get_phase_compliance,
    log_goal_event,
    revise_phase,
)


# ════════════════════════════════════════════════════════════════
# Get Active Phase
# ════════════════════════════════════════════════════════════════


class TestActivePhase:
    # Happy
    def test_get_active(self, db):
        db.execute("INSERT INTO goals (id, name, type, active) VALUES (1, 'Test', 'marathon', 1)")
        db.execute("INSERT INTO training_phases (id, goal_id, phase, name, status) VALUES (1, 1, 'Phase 1', 'Base', 'active')")
        db.commit()
        phase = get_active_phase(db)
        assert phase is not None
        assert phase["name"] == "Base"

    def test_filter_by_goal(self, db):
        db.execute("INSERT INTO goals (id, name, type, active) VALUES (1, 'A', 'marathon', 1)")
        db.execute("INSERT INTO goals (id, name, type, active) VALUES (2, 'B', 'metric', 1)")
        db.execute("INSERT INTO training_phases (id, goal_id, phase, name, status) VALUES (1, 1, 'P1', 'Base', 'active')")
        db.execute("INSERT INTO training_phases (id, goal_id, phase, name, status) VALUES (2, 2, 'P1', 'Other', 'active')")
        db.commit()
        phase = get_active_phase(db, goal_id=1)
        assert phase["name"] == "Base"

    def test_returns_dict_not_row(self, db):
        db.execute("INSERT INTO goals (id, name, type, active) VALUES (1, 'Test', 'marathon', 1)")
        db.execute("INSERT INTO training_phases (id, goal_id, phase, name, status) VALUES (1, 1, 'P1', 'Base', 'active')")
        db.commit()
        phase = get_active_phase(db)
        assert isinstance(phase, dict)

    # Unhappy
    def test_no_active_phase(self, db):
        assert get_active_phase(db) is None

    def test_only_planned_not_returned(self, db):
        db.execute("INSERT INTO goals (id, name, type, active) VALUES (1, 'Test', 'marathon', 1)")
        db.execute("INSERT INTO training_phases (id, goal_id, phase, name, status) VALUES (1, 1, 'Phase 1', 'Base', 'planned')")
        db.commit()
        assert get_active_phase(db) is None

    def test_only_completed_not_returned(self, db):
        db.execute("INSERT INTO goals (id, name, type, active) VALUES (1, 'Test', 'marathon', 1)")
        db.execute("INSERT INTO training_phases (id, goal_id, phase, name, status) VALUES (1, 1, 'P1', 'Done', 'completed')")
        db.commit()
        assert get_active_phase(db) is None

    def test_only_revised_not_returned(self, db):
        db.execute("INSERT INTO goals (id, name, type, active) VALUES (1, 'Test', 'marathon', 1)")
        db.execute("INSERT INTO training_phases (id, goal_id, phase, name, status) VALUES (1, 1, 'P1', 'Old', 'revised')")
        db.commit()
        assert get_active_phase(db) is None

    def test_wrong_goal_id(self, db):
        db.execute("INSERT INTO goals (id, name, type, active) VALUES (1, 'Test', 'marathon', 1)")
        db.execute("INSERT INTO training_phases (id, goal_id, phase, name, status) VALUES (1, 1, 'P1', 'Base', 'active')")
        db.commit()
        assert get_active_phase(db, goal_id=999) is None

    def test_multiple_active_returns_first(self, db):
        """Multiple active phases — returns LIMIT 1 (first found)."""
        db.execute("INSERT INTO goals (id, name, type, active) VALUES (1, 'Test', 'marathon', 1)")
        db.execute("INSERT INTO training_phases (id, goal_id, phase, name, status) VALUES (1, 1, 'P1', 'First', 'active')")
        db.execute("INSERT INTO training_phases (id, goal_id, phase, name, status) VALUES (2, 1, 'P2', 'Second', 'active')")
        db.commit()
        phase = get_active_phase(db)
        assert phase is not None


# ════════════════════════════════════════════════════════════════
# Complete Phase
# ════════════════════════════════════════════════════════════════


class TestCompletePhase:
    def _setup(self, db, status="active"):
        db.execute("INSERT INTO goals (id, name, type, active) VALUES (1, 'Test', 'marathon', 1)")
        db.execute(f"INSERT INTO training_phases (id, goal_id, phase, name, status) VALUES (1, 1, 'P1', 'Base', '{status}')")
        db.commit()

    # Happy
    def test_complete_with_actuals(self, db):
        self._setup(db)
        complete_phase(db, 1, actuals={"weekly_km_avg": 22, "z12_pct": 72})
        row = db.execute("SELECT status, actuals FROM training_phases WHERE id = 1").fetchone()
        assert row["status"] == "completed"
        assert "22" in row["actuals"]

    def test_complete_without_actuals(self, db):
        self._setup(db)
        complete_phase(db, 1)
        row = db.execute("SELECT status, actuals FROM training_phases WHERE id = 1").fetchone()
        assert row["status"] == "completed"
        assert row["actuals"] is None

    def test_complete_updates_timestamp(self, db):
        self._setup(db)
        complete_phase(db, 1)
        row = db.execute("SELECT updated_at FROM training_phases WHERE id = 1").fetchone()
        assert row["updated_at"] is not None

    # Unhappy
    def test_complete_already_completed(self, db):
        """Double-completing should be idempotent."""
        self._setup(db)
        complete_phase(db, 1)
        complete_phase(db, 1)
        row = db.execute("SELECT status FROM training_phases WHERE id = 1").fetchone()
        assert row["status"] == "completed"

    def test_complete_nonexistent_phase(self, db):
        """No-op for non-existent ID (UPDATE affects 0 rows)."""
        complete_phase(db, 999)  # should not raise

    def test_complete_planned_phase(self, db):
        """Can complete a planned phase (skipping active)."""
        self._setup(db, status="planned")
        complete_phase(db, 1)
        row = db.execute("SELECT status FROM training_phases WHERE id = 1").fetchone()
        assert row["status"] == "completed"

    def test_complete_revised_phase(self, db):
        """Can re-complete a revised phase."""
        self._setup(db, status="revised")
        complete_phase(db, 1)
        row = db.execute("SELECT status FROM training_phases WHERE id = 1").fetchone()
        assert row["status"] == "completed"


# ════════════════════════════════════════════════════════════════
# Revise Phase
# ════════════════════════════════════════════════════════════════


class TestRevisePhase:
    def _setup(self, db):
        db.execute("INSERT INTO goals (id, name, type, active) VALUES (1, 'Test', 'marathon', 1)")
        db.execute("""INSERT INTO training_phases (id, goal_id, phase, name, start_date, end_date,
                      z12_pct_target, weekly_km_min, weekly_km_max, targets, status)
                      VALUES (1, 1, 'P2', 'Volume', '2026-06-01', '2026-07-31', 80, 40, 50, '{"run_frequency": [4, 5]}', 'active')""")
        db.commit()

    # Happy
    def test_revise_creates_new(self, db):
        self._setup(db)
        new_id = revise_phase(db, 1, {"weekly_km_min": 35, "weekly_km_max": 45}, "Knee issue")
        assert new_id > 1
        old = db.execute("SELECT status FROM training_phases WHERE id = 1").fetchone()
        assert old["status"] == "revised"
        new = db.execute("SELECT status, weekly_km_min FROM training_phases WHERE id = ?", (new_id,)).fetchone()
        assert new["status"] == "active"
        assert new["weekly_km_min"] == 35

    def test_revise_logs_event(self, db):
        self._setup(db)
        revise_phase(db, 1, {"weekly_km_min": 20}, "Adjusted")
        log = db.execute("SELECT * FROM goal_log WHERE type = 'phase_revised'").fetchone()
        assert log is not None
        assert "Adjusted" in log["description"]

    def test_revise_preserves_unchanged_targets(self, db):
        """Fields not in new_targets should carry over from old phase."""
        self._setup(db)
        new_id = revise_phase(db, 1, {"weekly_km_min": 35}, "partial update")
        new = db.execute("SELECT * FROM training_phases WHERE id = ?", (new_id,)).fetchone()
        assert new["weekly_km_max"] == 50  # unchanged
        assert new["z12_pct_target"] == 80  # unchanged

    def test_revise_stores_previous_and_new_values(self, db):
        self._setup(db)
        revise_phase(db, 1, {"weekly_km_min": 35}, "bump")
        log = db.execute("SELECT * FROM goal_log ORDER BY id DESC LIMIT 1").fetchone()
        prev = json.loads(log["previous_value"])
        new = json.loads(log["new_value"])
        assert "run_frequency" in prev
        assert "weekly_km_min" in new

    # Unhappy
    def test_revise_nonexistent_raises(self, db):
        with pytest.raises(ValueError, match="Phase 999 not found"):
            revise_phase(db, 999, {}, "No reason")

    def test_revise_with_empty_targets(self, db):
        """Empty targets dict — phase gets revised with old values preserved."""
        self._setup(db)
        new_id = revise_phase(db, 1, {}, "no changes")
        new = db.execute("SELECT * FROM training_phases WHERE id = ?", (new_id,)).fetchone()
        assert new["weekly_km_min"] == 40  # original value
        assert new["weekly_km_max"] == 50

    def test_revise_planned_phase(self, db):
        """Can revise a planned phase too."""
        db.execute("INSERT INTO goals (id, name, type, active) VALUES (1, 'Test', 'marathon', 1)")
        db.execute("""INSERT INTO training_phases (id, goal_id, phase, name,
                      weekly_km_min, weekly_km_max, targets, status)
                      VALUES (1, 1, 'P1', 'Base', 20, 30, '{}', 'planned')""")
        db.commit()
        revise_phase(db, 1, {"weekly_km_min": 25}, "adjust")
        old = db.execute("SELECT status FROM training_phases WHERE id = 1").fetchone()
        assert old["status"] == "revised"

    def test_revise_preserves_goal_id(self, db):
        self._setup(db)
        new_id = revise_phase(db, 1, {"weekly_km_min": 35}, "test")
        new = db.execute("SELECT goal_id FROM training_phases WHERE id = ?", (new_id,)).fetchone()
        assert new["goal_id"] == 1

    def test_revise_preserves_phase_name(self, db):
        self._setup(db)
        new_id = revise_phase(db, 1, {}, "test")
        new = db.execute("SELECT phase, name FROM training_phases WHERE id = ?", (new_id,)).fetchone()
        assert new["phase"] == "P2"
        assert new["name"] == "Volume"


# ════════════════════════════════════════════════════════════════
# Goal Logging
# ════════════════════════════════════════════════════════════════


class TestGoalLog:
    # Happy
    def test_log_event(self, db):
        db.execute("INSERT INTO goals (id, name, type, active) VALUES (1, 'Test', 'marathon', 1)")
        db.commit()
        log_goal_event(db, 1, None, "goal_created", "Test goal created")
        db.commit()
        row = db.execute("SELECT * FROM goal_log").fetchone()
        assert row["type"] == "goal_created"
        assert row["description"] == "Test goal created"

    def test_log_with_values(self, db):
        db.execute("INSERT INTO goals (id, name, type, active) VALUES (1, 'Test', 'marathon', 1)")
        db.commit()
        log_goal_event(db, 1, None, "goal_updated", "Pace changed",
                       previous_value={"pace": 341}, new_value={"pace": 350})
        db.commit()
        row = db.execute("SELECT previous_value, new_value FROM goal_log").fetchone()
        assert "341" in row["previous_value"]
        assert "350" in row["new_value"]

    def test_log_records_date(self, db):
        db.execute("INSERT INTO goals (id, name, type, active) VALUES (1, 'Test', 'marathon', 1)")
        db.commit()
        log_goal_event(db, 1, None, "info", "test")
        db.commit()
        row = db.execute("SELECT date FROM goal_log").fetchone()
        assert row["date"] == date.today().isoformat()

    # Unhappy
    def test_log_null_phase_id(self, db):
        db.execute("INSERT INTO goals (id, name, type, active) VALUES (1, 'Test', 'marathon', 1)")
        db.commit()
        log_goal_event(db, 1, None, "goal_created", "New goal")
        db.commit()
        row = db.execute("SELECT * FROM goal_log").fetchone()
        assert row["phase_id"] is None

    def test_log_null_values(self, db):
        db.execute("INSERT INTO goals (id, name, type, active) VALUES (1, 'Test', 'marathon', 1)")
        db.execute("INSERT INTO training_phases (id, goal_id, phase, name, status) VALUES (1, 1, 'P1', 'Base', 'active')")
        db.commit()
        log_goal_event(db, 1, 1, "info", "note", previous_value=None, new_value=None)
        db.commit()
        row = db.execute("SELECT * FROM goal_log").fetchone()
        assert row["previous_value"] is None
        assert row["new_value"] is None

    def test_log_complex_json_values(self, db):
        db.execute("INSERT INTO goals (id, name, type, active) VALUES (1, 'Test', 'marathon', 1)")
        db.commit()
        complex_val = {"nested": {"key": [1, 2, 3]}, "x": None}
        log_goal_event(db, 1, None, "test", "test", previous_value=complex_val)
        db.commit()
        row = db.execute("SELECT previous_value FROM goal_log").fetchone()
        parsed = json.loads(row["previous_value"])
        assert parsed["nested"]["key"] == [1, 2, 3]


# ════════════════════════════════════════════════════════════════
# Phase Compliance
# ════════════════════════════════════════════════════════════════


class TestPhaseCompliance:
    def _setup_phase(self, db, targets='{"run_frequency": [3, 4], "acwr_range": [0.8, 1.2]}'):
        db.execute("INSERT INTO goals (id, name, type, active) VALUES (1, 'Test', 'marathon', 1)")
        db.execute(f"""INSERT INTO training_phases (id, goal_id, phase, name, start_date,
                      z12_pct_target, weekly_km_min, weekly_km_max, targets, status)
                      VALUES (1, 1, 'P1', 'Base', '2026-04-01', 90, 25, 30,
                      '{targets}', 'active')""")
        db.commit()

    def _insert_weekly(self, db, week, **kwargs):
        defaults = {"week": week, "run_count": 3, "run_km": 27, "z12_pct": 91, "acwr": 1.0}
        defaults.update(kwargs)
        cols = ", ".join(defaults.keys())
        placeholders = ", ".join(["?"] * len(defaults))
        db.execute(f"INSERT INTO weekly_agg ({cols}) VALUES ({placeholders})", list(defaults.values()))
        db.commit()

    # Happy
    def test_compliance_on_track(self, db):
        self._setup_phase(db)
        self._insert_weekly(db, "2026-W14", run_km=27, z12_pct=91, run_count=3, acwr=1.0)
        self._insert_weekly(db, "2026-W15", run_km=28, z12_pct=92, run_count=4, acwr=1.05)
        result = get_phase_compliance(db, 1)
        assert result["status"] == "active"
        z12 = [d for d in result["dimensions"] if "Z1+Z2" in d["name"]]
        assert z12[0]["on_track"] is True

    def test_compliance_volume_in_range(self, db):
        self._setup_phase(db)
        self._insert_weekly(db, "2026-W14", run_km=27)
        self._insert_weekly(db, "2026-W15", run_km=28)
        result = get_phase_compliance(db, 1)
        km = [d for d in result["dimensions"] if "km" in d["name"].lower()]
        assert km[0]["on_track"] is True

    def test_compliance_run_frequency_on_track(self, db):
        self._setup_phase(db)
        self._insert_weekly(db, "2026-W14", run_count=3)
        self._insert_weekly(db, "2026-W15", run_count=4)
        result = get_phase_compliance(db, 1)
        freq = [d for d in result["dimensions"] if "Runs" in d["name"]]
        assert freq[0]["on_track"] is True

    # Unhappy
    def test_compliance_no_data(self, db):
        self._setup_phase(db)
        result = get_phase_compliance(db, 1)
        assert result["status"] == "no_data"

    def test_compliance_nonexistent_phase(self, db):
        result = get_phase_compliance(db, 999)
        assert result == {}

    def test_compliance_volume_below_range(self, db):
        self._setup_phase(db)
        self._insert_weekly(db, "2026-W14", run_km=10)
        self._insert_weekly(db, "2026-W15", run_km=12)
        result = get_phase_compliance(db, 1)
        km = [d for d in result["dimensions"] if "km" in d["name"].lower()]
        assert km[0]["on_track"] is False

    def test_compliance_volume_above_range(self, db):
        self._setup_phase(db)
        self._insert_weekly(db, "2026-W14", run_km=40)
        self._insert_weekly(db, "2026-W15", run_km=42)
        result = get_phase_compliance(db, 1)
        km = [d for d in result["dimensions"] if "km" in d["name"].lower()]
        assert km[0]["on_track"] is False

    def test_compliance_z12_below_target(self, db):
        self._setup_phase(db)
        self._insert_weekly(db, "2026-W14", z12_pct=70)
        self._insert_weekly(db, "2026-W15", z12_pct=72)
        result = get_phase_compliance(db, 1)
        z12 = [d for d in result["dimensions"] if "Z1+Z2" in d["name"]]
        # avg=71, target=90, 90*0.9=81 → off track
        assert z12[0]["on_track"] is False

    def test_compliance_with_null_weekly_fields(self, db):
        self._setup_phase(db)
        self._insert_weekly(db, "2026-W14", run_km=None, z12_pct=None, run_count=None, acwr=None)
        result = get_phase_compliance(db, 1)
        assert result["status"] == "active"
        for d in result["dimensions"]:
            if d.get("actual") is None:
                assert d["on_track"] is False or d["on_track"] is None

    def test_compliance_single_week(self, db):
        """One week of data should still produce compliance."""
        self._setup_phase(db)
        self._insert_weekly(db, "2026-W14", run_km=27, z12_pct=91)
        result = get_phase_compliance(db, 1)
        assert result["status"] == "active"

    def test_compliance_no_targets_in_json(self, db):
        """Phase with empty JSON targets should still work (fewer dimensions)."""
        self._setup_phase(db, targets='{}')
        self._insert_weekly(db, "2026-W14")
        result = get_phase_compliance(db, 1)
        assert result["status"] == "active"
        # Should still have z12 and volume dimensions from denormalized columns
        assert len(result["dimensions"]) >= 2

    def test_compliance_acwr_out_of_range(self, db):
        self._setup_phase(db)
        self._insert_weekly(db, "2026-W14", acwr=1.5)
        self._insert_weekly(db, "2026-W15", acwr=1.6)
        result = get_phase_compliance(db, 1)
        acwr = [d for d in result["dimensions"] if "ACWR" in d["name"]]
        assert acwr[0]["on_track"] is False
