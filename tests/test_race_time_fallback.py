"""Race-time fallback: predictions use garmin_time when result_time is absent."""

from fit.report.sections.predictions import _prediction_summary


def _add_completed_race(db, d, name, distance_km, *, result_time=None, garmin_time=None):
    db.execute(
        "INSERT INTO race_calendar (date, name, distance, distance_km, status, "
        "result_time, garmin_time) VALUES (?, ?, ?, ?, 'completed', ?, ?)",
        (d, name, f"{distance_km:g}km", distance_km, result_time, garmin_time),
    )
    db.commit()


class TestRaceTimeFallback:
    def test_prediction_summary_runs_with_garmin_only(self, db):
        _add_completed_race(db, "2026-03-22", "HM", 21.1, garmin_time="2:01:48")
        assert _prediction_summary(db) is not None
