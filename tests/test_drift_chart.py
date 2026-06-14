"""Long-Run Resilience chart (chart-drift) regression guards.

Two bugs, one root cause: the chart binned pace/HR by `split_num` (the lap *index*) and
labelled each bin "Nkm", and it included every run type. So an interval session with many
short laps (e.g. 30 laps over 10 km) stretched the x-axis to "30km" — past any real distance —
and its fast/jog sawtooth made the pace line wavy. The fix bins by *cumulative distance* and
restricts the chart to steady runs (the same compute_cardiac_drift gate the Resilience
dimension uses), so the axis is real km and interval runs are excluded.
"""

import re
from datetime import date, timedelta

from fit.report.sections.charts import _all_charts


def _seed(db, aid, days_ago, run_type, lap_dists, paces, hrs):
    """Insert a run with explicit per-lap distance / pace / HR."""
    d = (date.today() - timedelta(days=days_ago)).isoformat()
    dist = sum(lap_dists)
    db.execute(
        "INSERT INTO activities (id, date, type, distance_km, duration_min, run_type, splits_status) "
        "VALUES (?, ?, 'running', ?, ?, ?, 'done')",
        (aid, d, dist, sum(p / 60 * km for p, km in zip(paces, lap_dists)), run_type))
    for k, (km, pace, hr) in enumerate(zip(lap_dists, paces, hrs), start=1):
        db.execute(
            "INSERT INTO activity_splits (activity_id, split_num, distance_km, pace_sec_per_km, avg_hr) "
            "VALUES (?, ?, ?, ?, ?)", (aid, k, km, pace, hr))
    db.commit()


def _drift_chart(db):
    for c in _all_charts(db):
        if c.get("id") == "chart-drift":
            return c
    return None


# The chart config string has a JS legend-filter function injected, so it isn't valid JSON —
# parse the axis labels ("Nkm") and per-run dataset labels ("Pace MM-DD") with regex.
def _max_label_km(chart):
    return max(int(m) for m in re.findall(r'"(\d+)km"', chart["config"]))


def _per_run_pace_lines(chart):
    return re.findall(r'"(Pace \d\d-\d\d)"', chart["config"])  # excludes "Avg Pace"


def _drift_marker_xmin(chart):
    m = re.search(r'"drift":\s*\{[^}]*?"xMin":\s*([0-9.]+)', chart["config"])
    return float(m.group(1)) if m else None


class TestDriftChartAxisIsRealDistance:
    def test_axis_does_not_exceed_longest_run(self, db):
        # Steady 20 km long run (20 × 1 km, flat HR → no drift, included).
        _seed(db, "long20", 1, "long", [1.0] * 20, [360] * 20, [150] * 20)
        # Interval: 30 sub-km laps over ~10 km, sawtooth pace → high CV (excluded). Under the
        # OLD bug its 30 laps pushed the x-axis to "30km".
        n = 30
        _seed(db, "intervals", 3, "intervals",
              [10.0 / n] * n,
              [270 if i % 2 else 600 for i in range(n)],
              [165 if i % 2 else 130 for i in range(n)])
        chart = _drift_chart(db)
        assert chart is not None
        # Axis tops out at the longest *steady* run (≈20 km), never the 30-lap interval count.
        assert _max_label_km(chart) <= 21

    def test_interval_run_is_excluded(self, db):
        _seed(db, "long20", 1, "long", [1.0] * 20, [360] * 20, [150] * 20)
        n = 30
        _seed(db, "intervals", 3, "intervals",
              [10.0 / n] * n,
              [270 if i % 2 else 600 for i in range(n)],
              [165 if i % 2 else 130 for i in range(n)])
        chart = _drift_chart(db)
        # Only the steady run contributes a per-run line.
        lines = _per_run_pace_lines(chart)
        interval_date = (date.today() - timedelta(days=3)).isoformat()[-5:]
        assert all(interval_date not in lbl for lbl in lines), f"interval run leaked into {lines}"
        assert len(lines) == 1


class TestDriftChartStillRendersSteadyRuns:
    def test_two_steady_runs_both_included(self, db):
        _seed(db, "long20", 2, "long", [1.0] * 20, [360] * 20, [150] * 20)
        _seed(db, "long15", 6, "long", [1.0] * 15, [370] * 15, [148] * 15)
        chart = _drift_chart(db)
        assert chart is not None
        assert len(_per_run_pace_lines(chart)) == 2
        assert _max_label_km(chart) <= 21  # the longer run, real km

    def test_short_runs_below_8km_excluded(self, db):
        # The dimension floor is 8 km; a 6 km steady run shouldn't drive the resilience chart.
        _seed(db, "long20", 2, "long", [1.0] * 20, [360] * 20, [150] * 20)
        _seed(db, "short6", 4, "easy", [1.0] * 6, [380] * 6, [140] * 6)
        chart = _drift_chart(db)
        assert len(_per_run_pace_lines(chart)) == 1


class TestDriftOnsetMarker:
    def test_no_drift_best_run_marker_stays_on_axis(self, db):
        # Flat HR over 20 km → no drift → onset = full distance (20). The marker must land ON
        # the last km tick, not just past it (the bug that clipped the line out of the plot).
        _seed(db, "long20", 1, "long", [1.0] * 20, [360] * 20, [150] * 20)
        chart = _drift_chart(db)
        xmin = _drift_marker_xmin(chart)
        assert xmin is not None                          # the line is emitted
        assert xmin <= _max_label_km(chart) - 1          # on-axis (≤ last index) → not clipped

    def test_marker_sits_near_detected_onset(self, db):
        # HR steps up at km 11 → drift onset ≈ 11 km → marker near that km (index ≈ 10).
        hrs = [150 if k < 11 else 168 for k in range(18)]
        _seed(db, "long18", 2, "long", [1.0] * 18, [360] * 18, hrs)
        chart = _drift_chart(db)
        xmin = _drift_marker_xmin(chart)
        assert xmin is not None and 8 <= xmin <= 12
