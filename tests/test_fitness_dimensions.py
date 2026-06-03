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

    def test_aerobic_uses_median(self, db):
        for i, v in enumerate([48, 49, 50, 49, 60]):   # 60 = optimistic Garmin spike
            _run(db, f"a{i}", days_ago=20 - i*3, vo2=v)
        r = _compute_aerobic(db)
        assert r["current_value"] == 49.0        # median, not 60

    def test_window_excludes_old_readings(self, db):
        _run(db, "old", days_ago=DIMENSION_WINDOW_DAYS + 10, spb=2.0)  # outside window
        for i, spb in enumerate([1.10, 1.11, 1.12]):
            _run(db, f"n{i}", days_ago=5 + i, spb=spb)
        r = _compute_economy(db)
        assert r["current_value"] == 1.11        # 2.0 excluded; median of in-window
