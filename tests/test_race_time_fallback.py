"""Race-time fallback: predictions use garmin_time when result_time is absent."""

from fit.report.sections.predictions import _race_prediction, _prediction_summary


def _add_completed_race(db, d, name, distance_km, *, result_time=None, garmin_time=None):
    db.execute(
        "INSERT INTO race_calendar (date, name, distance, distance_km, status, "
        "result_time, garmin_time) VALUES (?, ?, ?, ?, 'completed', ?, ?)",
        (d, name, f"{distance_km:g}km", distance_km, result_time, garmin_time),
    )
    db.commit()


class TestRaceTimeFallback:
    def test_race_with_only_garmin_time_still_predicts(self, db):
        # HM with watch time but no official chip time → still renders a Riegel
        # prediction. The db fixture has no VO2max, so any race-extrapolated row
        # proves the garmin_time fallback fed it.
        _add_completed_race(db, "2026-03-22", "Müggelturm HM", 21.1, garmin_time="2:01:48")
        pred = _race_prediction(db)
        assert pred and isinstance(pred, str)
        assert "Riegel" in pred  # a race-extrapolated row was rendered

    def test_race_with_neither_time_excluded(self, db):
        # No official AND no watch time, no VO2max → nothing to predict from.
        _add_completed_race(db, "2026-03-22", "HM", 21.1)
        assert _race_prediction(db) is None

    def test_prediction_summary_runs_with_garmin_only(self, db):
        _add_completed_race(db, "2026-03-22", "HM", 21.1, garmin_time="2:01:48")
        assert _prediction_summary(db) is not None
