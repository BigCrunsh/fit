"""Race forecast is anchored to the calibrated VDOT, not Garmin VO2max (D1).

The dashboard headline forecast comes from ``get_calibration_anchor('vdot')`` via
the Daniels formula inverse (``anchor_race_time``) — NOT the retired
``_vdot_to_marathon_seconds`` table fed by the latest Garmin VO2max. Garmin's
HR-based VO2max runs well above this athlete's race-implied VDOT (≈49 vs ≈39),
so forecasting off it inflated the number. When no anchor exists, the cold-start
fallback is a conservative (slowest) Riegel extrapolation from real races —
never the table.
"""

from datetime import date, timedelta

from fit.fitness import anchor_race_time, vdot_to_race_time
from fit.analysis import predict_race_time, riegel_fallback_secs
from fit.report.sections import predictions as P


def _set_vdot_anchor(db, value, *, method="manual", confidence="high", stale_days=0):
    d = (date.today() - timedelta(days=stale_days)).isoformat()
    db.execute(
        "INSERT INTO calibration (metric, value, method, confidence, date, active) "
        "VALUES ('vdot', ?, ?, ?, ?, 1)",
        (value, method, confidence, d),
    )
    db.commit()


def _add_race(db, d, distance_km, *, result_time=None, garmin_time=None):
    db.execute(
        "INSERT INTO race_calendar (date, name, distance, distance_km, status, "
        "result_time, garmin_time) VALUES (?, ?, ?, ?, 'completed', ?, ?)",
        (d, f"R{distance_km}", f"{distance_km:g}km", distance_km, result_time, garmin_time),
    )
    db.commit()


class TestAnchorRaceTime:
    # Happy
    def test_matches_formula_inverse(self, db):
        _set_vdot_anchor(db, 40.0)
        assert anchor_race_time(db, 42.195) == vdot_to_race_time(40.0, 42.195)

    def test_faster_at_shorter_distance(self, db):
        _set_vdot_anchor(db, 45.0)
        assert anchor_race_time(db, 10.0) < anchor_race_time(db, 42.195)

    # Unhappy (2:1)
    def test_none_when_no_anchor(self, db):
        assert anchor_race_time(db, 42.195) is None

    def test_none_for_zero_distance(self, db):
        _set_vdot_anchor(db, 40.0)
        assert anchor_race_time(db, 0) is None

    def test_none_for_none_conn(self):
        assert anchor_race_time(None, 42.195) is None

    def test_ignores_garmin_vo2max_rows(self, db):
        # A Garmin reference row must NOT become the forecast anchor.
        _set_vdot_anchor(db, 55.0, method="device_vo2max", confidence="low")
        assert anchor_race_time(db, 42.195) is None


class TestPredictRaceTimeVdotLeg:
    # Happy
    def test_vdot_leg_from_anchor(self, db):
        _set_vdot_anchor(db, 42.0)
        preds = predict_race_time(conn=db, races=[])
        assert preds["vdot"] is not None
        assert preds["vdot"]["vdot"] == 42.0
        assert preds["vdot"]["predicted_seconds"] == vdot_to_race_time(42.0, 42.195)

    # Unhappy: the vo2max param no longer drives the leg
    def test_vo2max_param_ignored_without_conn(self):
        assert predict_race_time(races=[], vo2max=49)["vdot"] is None
        assert predict_race_time(races=[], vo2max=100)["vdot"] is None

    def test_no_anchor_no_vdot_leg(self, db):
        assert predict_race_time(conn=db, races=[])["vdot"] is None


class TestRiegelFallback:
    # Happy
    def test_slowest_extrapolation(self, db):
        _add_race(db, "2026-01-01", 10.0, result_time="0:50:00")   # 3000s
        _add_race(db, "2026-02-01", 21.1, result_time="1:50:00")   # 6600s
        from_10k = round(3000 * (42.195 / 10.0) ** 1.06)
        from_hm = round(6600 * (42.195 / 21.1) ** 1.06)
        assert riegel_fallback_secs(db, 42.195) == max(from_10k, from_hm)

    def test_uses_garmin_time_when_no_result(self, db):
        _add_race(db, "2026-02-01", 21.1, garmin_time="1:50:00")
        assert riegel_fallback_secs(db, 42.195) is not None

    # Unhappy (2:1)
    def test_none_without_races(self, db):
        assert riegel_fallback_secs(db, 42.195) is None

    def test_skips_target_distance_race(self, db):
        _add_race(db, "2026-02-01", 42.195, result_time="3:50:00")
        assert riegel_fallback_secs(db, 42.195) is None  # d1 == target_km skipped

    def test_skips_zero_distance(self, db):
        _add_race(db, "2026-02-01", 0, result_time="0:50:00")
        assert riegel_fallback_secs(db, 42.195) is None


class TestHeadlineSourcePriority:
    def test_anchor_preferred_over_races(self, db):
        _set_vdot_anchor(db, 40.0)
        _add_race(db, "2026-02-01", 21.1, result_time="1:50:00")
        expected = vdot_to_race_time(40.0, 42.195)
        out = P._prediction_summary(db)
        assert out.startswith(f"Prediction: {expected // 3600}:{(expected % 3600) // 60:02d}")

    def test_falls_back_to_race_observation(self, db):
        _add_race(db, "2026-02-01", 21.1, result_time="1:50:00")
        out = P._prediction_summary(db)
        assert out is not None and "race estimate" in out

    def test_none_without_anchor_or_races(self, db):
        assert P._prediction_summary(db) is None
