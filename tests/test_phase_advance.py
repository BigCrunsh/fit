"""Tests for date-based training-phase status advancement."""

from datetime import date, timedelta

from fit.periodization import advance_phase_status


def _add_phase(db, phase, start_days, end_days, status):
    db.execute(
        "INSERT INTO training_phases (phase, name, start_date, end_date, status) "
        "VALUES (?, ?, ?, ?, ?)",
        (phase, phase, (date.today() + timedelta(days=start_days)).isoformat(),
         (date.today() + timedelta(days=end_days)).isoformat(), status),
    )
    db.commit()


def _status(db, phase):
    return db.execute("SELECT status FROM training_phases WHERE phase = ?", (phase,)).fetchone()[0]


class TestAdvancePhaseStatus:
    def test_past_phase_becomes_completed(self, db):
        _add_phase(db, "P1", -60, -1, "active")  # ended yesterday
        assert advance_phase_status(db) == 1
        assert _status(db, "P1") == "completed"

    def test_current_phase_becomes_active(self, db):
        _add_phase(db, "P2", -1, 30, "planned")  # started yesterday, ongoing
        assert advance_phase_status(db) == 1
        assert _status(db, "P2") == "active"

    def test_future_phase_stays_planned(self, db):
        _add_phase(db, "P3", 10, 40, "planned")
        assert advance_phase_status(db) == 0  # no change
        assert _status(db, "P3") == "planned"

    def test_full_sequence(self, db):
        _add_phase(db, "Base", -60, -1, "active")    # → completed
        _add_phase(db, "Volume", 0, 59, "planned")   # → active (starts today)
        _add_phase(db, "Peak", 60, 100, "planned")   # stays planned
        advance_phase_status(db)
        assert _status(db, "Base") == "completed"
        assert _status(db, "Volume") == "active"
        assert _status(db, "Peak") == "planned"

    def test_revised_phase_left_untouched(self, db):
        _add_phase(db, "P1", -60, -1, "revised")  # manual override
        assert advance_phase_status(db) == 0
        assert _status(db, "P1") == "revised"

    def test_no_dates_skipped(self, db):
        db.execute("INSERT INTO training_phases (phase, name, status) VALUES ('X','X','active')")
        db.commit()
        assert advance_phase_status(db) == 0


class TestSyncAdvancesPhases:
    """The daily pipeline must advance phases, not just `fit recompute`.

    `advance_phase_status` was only ever called from `fit recompute` — a command
    that gets run after a calibration change, not daily. So a real plan sat on
    "Phase 2 — Volume" for 45 days after that phase ended on 2026-07-31, and every
    phase-driven comparison (zone-distribution targets, the weekly-km band, the
    coaching context's phase line, `fit status`) graded the athlete against the
    wrong block through all of August and September. Phases advance on calendar
    dates, so the step belongs wherever the calendar is re-read — i.e. sync.
    """

    def test_sync_module_calls_advance_phase_status(self):
        from pathlib import Path
        src = (Path(__file__).resolve().parent.parent / "fit" / "sync.py").read_text()
        assert "advance_phase_status" in src, (
            "fit/sync.py must advance training-phase status; without it the active "
            "phase silently goes stale the day a phase boundary passes"
        )

    def test_stale_phase_advances_without_touching_a_revised_one(self, db):
        """End to end on the shape that actually broke: a phase whose end date has
        passed is still 'active' while its successor sits 'planned'."""
        _add_phase(db, "Volume", -105, -45, "active")    # ended 45 days ago, still active
        _add_phase(db, "Peak", -44, 0, "planned")        # should be the active one (ends today)
        _add_phase(db, "Taper", 1, 13, "planned")
        _add_phase(db, "Hand-edited", -200, -150, "revised")
        assert advance_phase_status(db) == 2
        assert _status(db, "Volume") == "completed"
        assert _status(db, "Peak") == "active"
        assert _status(db, "Taper") == "planned"
        assert _status(db, "Hand-edited") == "revised"

    def test_phase_ending_today_is_still_active_not_completed(self, db):
        """Off-by-one guard: a phase is completed only once its end date has PASSED,
        so the last day of a block isn't spent grading against the next one."""
        _add_phase(db, "Peak", -40, 0, "planned")
        advance_phase_status(db)
        assert _status(db, "Peak") == "active"
