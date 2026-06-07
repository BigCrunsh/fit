"""Fitness dimensions use a robust median over a 4-week window, not the latest reading.

VO2max and speed_per_bpm are two-sided (terrain/tailwind/strap inflate, heat/
fatigue deflate), so the current value is the median over the dimension window —
a single noisy latest reading (or a downhill-inflated max) must not define it.
"""

from datetime import date, timedelta

from fit.fitness import _compute_economy, _compute_aerobic, DIMENSION_WINDOW_DAYS


def _run(db, aid, days_ago, spb=None, vo2=None):
    d = (date.today() - timedelta(days=days_ago)).isoformat()
    db.execute(
        "INSERT INTO activities (id, date, type, distance_km, duration_min, avg_hr, "
        "speed_per_bpm, vo2max) VALUES (?, ?, 'running', 8.0, 45, 150, ?, ?)",
        (aid, d, spb, vo2))
    db.commit()


class TestDimensionMedian:
    def test_economy_uses_median_not_latest(self, db):
        # Latest run is a downhill outlier (1.50); median of the set is 1.12.
        for i, spb in enumerate([1.10, 1.11, 1.12, 1.13, 1.50]):
            _run(db, f"e{i}", days_ago=20 - i*3, spb=spb)  # last inserted (i=4) is most recent
        r = _compute_economy(db)
        assert r["current_value"] == 1.12        # median, not the latest 1.50

    def test_aerobic_anchors_on_vdot_not_garmin(self, db):
        # Garmin VO2max readings (incl. an optimistic 60) must NOT set the value — the
        # calibrated VDOT anchor does (Garmin only shapes the trend, and reads high).
        for i, v in enumerate([48, 49, 50, 49, 60]):
            _run(db, f"a{i}", days_ago=20 - i*3, vo2=v)
        db.execute("INSERT INTO calibration (metric, value, method, confidence, date, active) "
                   "VALUES ('vdot', 38, 'manual', 'high', date('now','-1 day'), 1)")
        db.commit()
        r = _compute_aerobic(db)
        assert r["current_value"] == 38.0        # the calibrated VDOT anchor, NOT the Garmin median 49
        assert r["unit"] == "VDOT"

    def test_aerobic_empty_without_any_signal(self, db):
        # No anchor, no race, no Garmin → degrade gracefully (not a fabricated value).
        assert _compute_aerobic(db)["current_value"] is None

    def test_window_excludes_old_readings(self, db):
        _run(db, "old", days_ago=DIMENSION_WINDOW_DAYS + 10, spb=2.0)  # outside window
        for i, spb in enumerate([1.10, 1.11, 1.12]):
            _run(db, f"n{i}", days_ago=5 + i, spb=spb)
        r = _compute_economy(db)
        assert r["current_value"] == 1.11        # 2.0 excluded; median of in-window
