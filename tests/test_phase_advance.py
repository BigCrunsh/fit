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
