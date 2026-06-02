"""Point-in-time anchors: changing a calibration must not rewrite history.

An activity is classified with the anchor active AS OF its own date, so a later
LTHR/MaxHR change can't retroactively reclassify past activities (or shift the
weekly/phase aggregates built from them). The dated calibration rows + the
stamped lthr_used/max_hr_used reconstruct why a past phase was classified.
"""

from datetime import date

from fit.calibration import add_calibration, get_active_calibration
from fit.sync import enrich_existing_activities


class TestAsofLookup:
    def test_returns_value_active_at_that_date(self, db):
        add_calibration(db, "lthr", 172, "manual", "high", date(2025, 1, 1))
        add_calibration(db, "lthr", 175, "manual", "high", date(2025, 6, 1))
        assert get_active_calibration(db, "lthr", asof=date(2025, 3, 1))["value"] == 172
        assert get_active_calibration(db, "lthr", asof=date(2025, 9, 1))["value"] == 175

    def test_none_before_first_calibration(self, db):
        add_calibration(db, "lthr", 172, "manual", "high", date(2025, 1, 1))
        assert get_active_calibration(db, "lthr", asof=date(2024, 12, 1)) is None

    def test_default_is_current(self, db):
        add_calibration(db, "lthr", 172, "manual", "high", date(2025, 1, 1))
        # No asof → current behaviour (returns the row regardless of asof window).
        assert get_active_calibration(db, "lthr")["value"] == 172


class TestEnrichHistoricalStability:
    def test_later_lthr_change_does_not_reclassify_old_activity(self, db, config):
        add_calibration(db, "lthr", 170, "manual", "high", date(2025, 1, 1))
        db.execute(
            "INSERT INTO activities (id, date, type, distance_km, duration_min, avg_hr) "
            "VALUES ('old', '2025-02-01', 'running', 10.0, 50.0, 160)")
        db.commit()

        enrich_existing_activities(db, config, force=True)
        lthr_used_1 = db.execute("SELECT lthr_used FROM activities WHERE id='old'").fetchone()[0]
        assert lthr_used_1 == 170

        # Confirm a NEW, higher LTHR months later, then re-enrich everything.
        add_calibration(db, "lthr", 180, "manual", "high", date(2025, 6, 1))
        enrich_existing_activities(db, config, force=True)

        # The Feb activity is STILL classified with the as-of (170), not 180 —
        # history is stable across the anchor change.
        lthr_used_2 = db.execute("SELECT lthr_used FROM activities WHERE id='old'").fetchone()[0]
        assert lthr_used_2 == 170
