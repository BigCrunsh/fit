"""Rolling training frequency and volume change — replacing the ISO-week measures.

The bug this suite encodes: a plan that runs every other day was reported as a
"61% volume jump (16->25km) with 0 weeks of consistency". Both numbers came from
ISO-week buckets. Nothing had been skipped — the plan itself scheduled 7 runs
across Aug 12-26 and all 7 were completed — but the week boundary happened to
split them 3/2/2, and the current week was only 4 days old when compared against
a complete one. Rolling windows over consecutive days say the opposite: volume
was DOWN 36% and frequency was steady at ~2.75 runs/7d.

The property that matters is day-shift invariance: moving a run by a day or two
must not change either verdict, because nothing about the training changed.
"""

from datetime import date, timedelta

import pytest

from fit.analysis import compute_run_frequency, compute_volume_change

TODAY = date(2026, 8, 27)

# The real plan: every other day, with a planned 4-day gap after the Aug 16 long
# run. Dates and distances as actually completed.
REAL_RUNS = [
    (date(2026, 8, 12), 11.4), (date(2026, 8, 14), 12.9), (date(2026, 8, 16), 29.2),
    (date(2026, 8, 20), 8.4), (date(2026, 8, 22), 7.3), (date(2026, 8, 24), 14.0),
    (date(2026, 8, 26), 11.2),
]


def _runs(db, entries):
    for i, (d, km) in enumerate(entries):
        db.execute(
            "INSERT INTO activities (id, date, type, distance_km, duration_min) "
            "VALUES (?, ?, 'running', ?, ?)",
            (f"r{i}", d.isoformat(), km, km * 6),
        )
    db.commit()


def _every_n_days(start, count, n, km=10.0):
    return [(start + timedelta(days=i * n), km) for i in range(count)]


# ── the rate ──

class TestRunFrequencyRate:
    def test_counts_runs_in_the_trailing_window_scaled_to_seven_days(self, db):
        # 12 runs in 28 days = 3 runs per 7 days.
        _runs(db, _every_n_days(TODAY - timedelta(days=27), 12, 2))
        f = compute_run_frequency(db, end_date=TODAY, rate_days=28)
        assert f["runs"] == 12
        assert f["runs_per_week"] == 3.0

    def test_real_plan_reads_its_actual_cadence_not_zero(self, db):
        _runs(db, REAL_RUNS)
        f = compute_run_frequency(db, end_date=TODAY, rate_days=28)
        assert f["runs"] == 7
        assert f["runs_per_week"] == pytest.approx(1.75, abs=0.01)

    def test_no_runs_is_zero_not_an_error(self, db):
        f = compute_run_frequency(db, end_date=TODAY)
        assert f["runs"] == 0 and f["runs_per_week"] == 0.0
        assert f["base_pct"] == 0.0 and f["thin"] is True

    def test_a_run_exactly_at_the_window_edge_is_included(self, db):
        # trailing 28 days means today-27..today, inclusive at both ends.
        _runs(db, [(TODAY - timedelta(days=27), 10.0)])
        assert compute_run_frequency(db, end_date=TODAY, rate_days=28)["runs"] == 1

    def test_a_run_one_day_past_the_window_edge_is_excluded(self, db):
        _runs(db, [(TODAY - timedelta(days=28), 10.0)])
        assert compute_run_frequency(db, end_date=TODAY, rate_days=28)["runs"] == 0

    def test_non_running_activities_do_not_count(self, db):
        db.execute("INSERT INTO activities (id, date, type, distance_km) "
                   "VALUES ('s1', ?, 'open_water_swimming', 0.1)", (TODAY.isoformat(),))
        db.commit()
        assert compute_run_frequency(db, end_date=TODAY)["runs"] == 0


# ── the base share ──

class TestRunFrequencyBase:
    def test_sustained_three_per_week_reads_full_base(self, db):
        # Every other day for 10 weeks: every trailing 7-day window holds 3-4 runs.
        _runs(db, _every_n_days(TODAY - timedelta(days=69), 35, 2))
        f = compute_run_frequency(db, end_date=TODAY, base_days=56)
        assert f["base_pct"] == 100.0
        assert f["sustained_weeks"] == pytest.approx(8.0, abs=0.01)
        assert f["thin"] is False

    def test_a_single_planned_gap_does_not_zero_the_base(self, db):
        # THE REGRESSION: the ISO-week streak read 0 here. A gap costs a few
        # windows, not the whole history.
        _runs(db, _every_n_days(TODAY - timedelta(days=69), 20, 2)
              + _every_n_days(TODAY - timedelta(days=25), 12, 2))
        f = compute_run_frequency(db, end_date=TODAY, base_days=56)
        assert f["base_pct"] > 60
        assert f["thin"] is False

    def test_genuinely_thin_training_is_still_flagged(self, db):
        # One run a week for 8 weeks — no trailing window ever holds 3.
        _runs(db, _every_n_days(TODAY - timedelta(days=56), 9, 7))
        f = compute_run_frequency(db, end_date=TODAY, base_days=56)
        assert f["base_pct"] == 0.0
        assert f["thin"] is True

    def test_base_pct_counts_windows_not_calendar_weeks(self, db):
        _runs(db, _every_n_days(TODAY - timedelta(days=13), 7, 2))
        f = compute_run_frequency(db, end_date=TODAY, base_days=14)
        # 14 daily windows evaluated; the early ones can't hold 3 runs yet.
        assert 0 < f["base_pct"] < 100

    def test_target_runs_is_configurable(self, db):
        _runs(db, _every_n_days(TODAY - timedelta(days=27), 14, 2))
        strict = compute_run_frequency(db, end_date=TODAY, base_days=28, target_runs=5)
        assert strict["base_pct"] == 0.0          # 4 runs/wk never reaches 5
        assert strict["target_runs"] == 5


# ── day-shift invariance: the actual requirement ──

class TestDayShiftInvariance:
    @pytest.mark.parametrize("shift", [-2, -1, 1, 2])
    def test_shifting_one_run_does_not_flip_the_thin_verdict(self, db, shift):
        runs = _every_n_days(TODAY - timedelta(days=69), 35, 2)
        moved = [(d + timedelta(days=shift), km) if i == 17 else (d, km)
                 for i, (d, km) in enumerate(runs)]
        _runs(db, moved)
        assert compute_run_frequency(db, end_date=TODAY, base_days=56)["thin"] is False

    @pytest.mark.parametrize("shift", [-2, -1, 1, 2])
    def test_shifting_one_run_barely_moves_the_rate(self, db, shift):
        runs = _every_n_days(TODAY - timedelta(days=27), 12, 2)
        moved = [(d + timedelta(days=shift), km) if i == 5 else (d, km)
                 for i, (d, km) in enumerate(runs)]
        _runs(db, moved)
        f = compute_run_frequency(db, end_date=TODAY, rate_days=28)
        assert f["runs_per_week"] == pytest.approx(3.0, abs=0.26)   # at most one run in/out


# ── volume change ──

class TestVolumeChange:
    def test_real_plan_shows_a_decrease_not_a_61_percent_jump(self, db):
        _runs(db, REAL_RUNS)
        v = compute_volume_change(db, end_date=TODAY)
        assert v["current_km"] == pytest.approx(32.5, abs=0.1)
        assert v["previous_km"] == pytest.approx(50.5, abs=0.1)
        assert v["pct_change"] < 0

    def test_a_real_ramp_is_detected(self, db):
        _runs(db, [(TODAY - timedelta(days=10), 10.0), (TODAY - timedelta(days=8), 10.0),
                   (TODAY - timedelta(days=3), 20.0), (TODAY - timedelta(days=1), 20.0)])
        v = compute_volume_change(db, end_date=TODAY)
        assert v["pct_change"] == pytest.approx(100.0, abs=0.1)

    def test_no_previous_volume_yields_no_percentage(self, db):
        # Coming back from zero: a percentage would be infinite and meaningless.
        _runs(db, [(TODAY - timedelta(days=1), 10.0)])
        v = compute_volume_change(db, end_date=TODAY)
        assert v["previous_km"] == 0
        assert v["pct_change"] is None

    def test_no_runs_at_all(self, db):
        v = compute_volume_change(db, end_date=TODAY)
        assert v["current_km"] == 0 and v["pct_change"] is None

    def test_windows_do_not_overlap(self, db):
        # today-6..today vs today-13..today-7; a run on today-7 belongs to the
        # PREVIOUS window only.
        _runs(db, [(TODAY - timedelta(days=7), 10.0)])
        v = compute_volume_change(db, end_date=TODAY)
        assert v["current_km"] == 0 and v["previous_km"] == pytest.approx(10.0)

    @pytest.mark.parametrize("shift", [-2, -1, 1, 2])
    def test_shifting_a_run_inside_a_steady_block_keeps_change_small(self, db, shift):
        runs = _every_n_days(TODAY - timedelta(days=13), 7, 2)
        moved = [(d + timedelta(days=shift), km) if i == 3 else (d, km)
                 for i, (d, km) in enumerate(runs)]
        _runs(db, moved)
        v = compute_volume_change(db, end_date=TODAY)
        # One 10km run crossing the boundary is at most ~1 run's worth of swing,
        # nowhere near the +61% the ISO comparison produced from the same shape.
        assert abs(v["pct_change"]) <= 50
