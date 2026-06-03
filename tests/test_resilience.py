"""Resilience dimension uses the BEST recent long-run drift onset, not the latest.

Drift onset is one-sided (bounded above by durability; a short/easy/bad run only
pushes it earlier), so the max over recent qualifying long runs is the truest
signal — a 10 km drifting at km 6 must not overwrite an 18 km that held to km 11.
"""

from datetime import date, timedelta

from fit.fitness import _compute_resilience


def _seed_run(db, aid, days_ago, n_splits, onset_split, base_hr=150, hi_hr=160, pace=300):
    """A run whose HR:pace ratio jumps at `onset_split` → drift onset there."""
    d = (date.today() - timedelta(days=days_ago)).isoformat()
    db.execute(
        "INSERT INTO activities (id, date, type, distance_km, duration_min, splits_status) "
        "VALUES (?, ?, 'running', ?, ?, 'done')",
        (aid, d, float(n_splits), n_splits * pace / 60.0))
    for k in range(1, n_splits + 1):
        hr = hi_hr if k >= onset_split else base_hr
        db.execute(
            "INSERT INTO activity_splits (activity_id, split_num, distance_km, pace_sec_per_km, avg_hr) "
            "VALUES (?, ?, 1.0, ?, ?)", (aid, k, pace, hr))
    db.commit()


class TestResilienceBestOnset:
    def test_uses_max_onset_not_latest(self, db):
        # Earlier 18 km run holds to km 11; latest 10 km run drifts at km 6.
        _seed_run(db, "long18", days_ago=20, n_splits=18, onset_split=11)
        _seed_run(db, "short10", days_ago=5, n_splits=10, onset_split=6)
        r = _compute_resilience(db)
        assert r["current_value"] == 11.0       # the best, not the latest (6)

    def test_short_recent_run_does_not_mask_durability(self, db):
        _seed_run(db, "long", days_ago=15, n_splits=16, onset_split=10)
        _seed_run(db, "shortest", days_ago=1, n_splits=8, onset_split=5)
        r = _compute_resilience(db)
        assert r["current_value"] == 10.0

    def test_empty_when_no_long_runs_with_splits(self, db):
        r = _compute_resilience(db)
        assert r.get("current_value") is None
