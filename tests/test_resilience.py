"""Resilience dimension = a recency/length-weighted, censored, shrink-to-prior estimate
(resilience-uncertainty change).

Drift onset is one-sided (bounded above by durability; a short/easy/bad run only pushes it
earlier), so the estimate favours the best *demonstrated* onset — a 10 km drifting at km 6
must not mask an 18 km that held to km 11. The exact value is no longer the raw max (it is
weighted and shrunk toward a prior), so these assert the directional invariants that hold
regardless of the judgment constants: the long/strong run drives the estimate, the short/weak
run does not, and the estimate never exceeds the best demonstrated onset.
"""

from datetime import date, timedelta

from fit.fitness import _compute_resilience


def _seed_run(db, aid, days_ago, n_splits, onset_split, base_hr=150, hi_hr=160, pace=300, run_type=None):
    """A run whose HR:pace ratio jumps at `onset_split` → drift onset there."""
    d = (date.today() - timedelta(days=days_ago)).isoformat()
    db.execute(
        "INSERT INTO activities (id, date, type, distance_km, duration_min, splits_status, run_type) "
        "VALUES (?, ?, 'running', ?, ?, 'done', ?)",
        (aid, d, float(n_splits), n_splits * pace / 60.0, run_type))
    for k in range(1, n_splits + 1):
        hr = hi_hr if k >= onset_split else base_hr
        db.execute(
            "INSERT INTO activity_splits (activity_id, split_num, distance_km, pace_sec_per_km, avg_hr) "
            "VALUES (?, ?, 1.0, ?, ?)", (aid, k, pace, hr))
    db.commit()


class TestResilienceBestOnset:
    def test_long_run_drives_estimate_short_run_does_not_mask(self, db):
        # Earlier 18 km run holds to km 11; later 10 km run drifts at km 6.
        _seed_run(db, "long18", days_ago=20, n_splits=18, onset_split=11)
        _seed_run(db, "short10", days_ago=5, n_splits=10, onset_split=6)
        r = _compute_resilience(db)
        # The 18 km's km-11 hold drives it (well above the 10 km's km-6 drift), and the
        # estimate never exceeds the best demonstrated onset.
        assert r["current_value"] > 8           # not masked by the km-6 short run
        assert r["current_value"] <= 11         # ≤ best demonstrated

    def test_short_recent_run_does_not_mask_durability(self, db):
        _seed_run(db, "long", days_ago=15, n_splits=16, onset_split=10)
        _seed_run(db, "shortest", days_ago=1, n_splits=8, onset_split=5)
        r = _compute_resilience(db)
        assert r["current_value"] > 7           # the km-10 long run drives it, not the km-5
        assert r["current_value"] <= 10         # ≤ best demonstrated

    def test_empty_when_no_long_runs_with_splits(self, db):
        r = _compute_resilience(db)
        assert r.get("current_value") is None

    def test_thin_data_shrinks_toward_prior_with_wide_band(self, db):
        # A single recent 20 km no-drift run is real but weak evidence: the estimate shrinks
        # below the raw 20, confidence is low, and the band is wide (resilience-uncertainty).
        _seed_run(db, "lone20", days_ago=2, n_splits=20, onset_split=99)  # onset_split>n → no drift
        r = _compute_resilience(db)
        assert r["current_value"] < 20                      # shrunk toward the prior, not raw 20
        assert r["confidence"]["level"] == "low"            # one run → low confidence
        assert (r["band"]["hi"] - r["current_value"]) >= (r["current_value"] - r["band"]["lo"])  # asymmetric (up)

    def test_ci_brackets_estimate_and_is_a_real_interval(self, db):
        # The band is now a Bayesian-bootstrap sampling CI (option 1): it brackets the estimate
        # and is non-degenerate. (It can lean either way — the bootstrap reflects which runs the
        # resample weights, not a fixed one-sided shape.)
        _seed_run(db, "a", days_ago=3, n_splits=18, onset_split=99)   # no drift, 18 km
        _seed_run(db, "b", days_ago=10, n_splits=16, onset_split=12)  # drift at 12
        _seed_run(db, "c", days_ago=17, n_splits=14, onset_split=10)  # drift at 10
        r = _compute_resilience(db)
        lo, hi, est = r["band"]["lo"], r["band"]["hi"], r["current_value"]
        assert lo <= est <= hi and hi > lo

    def test_thinner_sample_gives_a_wider_interval(self, db):
        # Bootstrap CI widens when fewer runs feed it (the resample spread grows).
        _seed_run(db, "p", days_ago=4, n_splits=16, onset_split=12)
        _seed_run(db, "q", days_ago=9, n_splits=14, onset_split=9)
        r = _compute_resilience(db)
        assert (r["band"]["hi"] - r["band"]["lo"]) / r["current_value"] > 0.15  # genuinely uncertain

    def test_censored_points_flagged(self, db):
        _seed_run(db, "nodrift", days_ago=4, n_splits=16, onset_split=99)  # held to the end
        _seed_run(db, "drift", days_ago=8, n_splits=15, onset_split=9)     # decoupled at 9
        pts = {p["dist"]: p for p in _compute_resilience(db)["points"]}
        assert pts[16.0]["censored"] is True and pts[16.0]["value"] == 16.0  # lower bound = distance
        assert pts[15.0]["censored"] is False and pts[15.0]["value"] == 9.0  # observed onset

    def test_recency_a_stale_strong_run_is_discounted(self, db):
        # A 20 km no-drift run 60 days ago is real but stale; recent runs are weaker. Durability
        # is trainable/detrainable, so the estimate must NOT sit at the stale 20.
        _seed_run(db, "stale20", days_ago=60, n_splits=20, onset_split=99)
        _seed_run(db, "recent12", days_ago=2, n_splits=12, onset_split=7)
        _seed_run(db, "recent12b", days_ago=6, n_splits=12, onset_split=8)
        assert _compute_resilience(db)["current_value"] < 20

    def test_length_a_long_run_outweighs_a_short_one(self, db):
        # Same recency, both no-drift (lower bounds). The 20 km probes later km than the 8 km,
        # so it carries more weight and pulls the estimate well above the 8–20 midpoint.
        _seed_run(db, "long20", days_ago=5, n_splits=20, onset_split=99)
        _seed_run(db, "short8", days_ago=5, n_splits=8, onset_split=99)
        assert _compute_resilience(db)["current_value"] > 14

    def test_hard_effort_runs_are_excluded(self, db):
        # Resilience = aerobic durability: a tempo/progression/race run decouples early BY
        # DESIGN, so it must NOT feed the estimate; a steady long run does (knob B).
        _seed_run(db, "long", days_ago=3, n_splits=18, onset_split=99, run_type="long")    # no drift
        _seed_run(db, "tempo", days_ago=2, n_splits=16, onset_split=5, run_type="tempo")   # early drift
        _seed_run(db, "prog", days_ago=1, n_splits=15, onset_split=4, run_type="progression")
        dists = {p["dist"] for p in _compute_resilience(db)["points"]}
        assert 18.0 in dists                      # steady long run kept
        assert 16.0 not in dists and 15.0 not in dists   # tempo + progression dropped
