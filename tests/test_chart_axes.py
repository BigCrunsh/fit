"""Regression tests for the chart x-axis sizing bugs (task #38).

Two failures the UX QA caught:
  1. Profile trend charts reserved empty space out to a far race date,
     compressing the actual data into a sliver → _profile_x_range must cap
     the max at a short lookahead past today.
  2. The weekly Volume bar chart went blank because its bar chart had a
     'time' x-scale applied without offset → bars pinned at pixel 0. Its
     config must bake type:'time' + offset:true.
"""

import json
import re
from datetime import date, timedelta
from pathlib import Path

from fit.report.sections.charts import _profile_x_range, _all_charts

REPO = Path(__file__).resolve().parent.parent


def _seed_phase(db, start_days_ago=60, end_days_ahead=30):
    db.execute(
        "INSERT INTO training_phases (phase, name, start_date, end_date, status) "
        "VALUES ('Phase 1', 'Base', ?, ?, 'active')",
        ((date.today() - timedelta(days=start_days_ago)).isoformat(),
         (date.today() + timedelta(days=end_days_ahead)).isoformat()),
    )
    db.commit()


def _seed_race(db, days_ahead, status="planned", distance_km=42.195):
    db.execute(
        "INSERT INTO race_calendar (date, name, distance, distance_km, status) "
        "VALUES (?, 'Race', ?, ?, ?)",
        ((date.today() + timedelta(days=days_ahead)).isoformat(),
         f"{distance_km:g}km", distance_km, status),
    )
    db.commit()


class TestProfileXRange:
    def test_max_extends_to_far_race_plus_buffer(self, db):
        """The axis must reach the race (+10d buffer) so all phases + the race
        marker are visible — even when the race is months out."""
        _seed_phase(db)
        _seed_race(db, days_ahead=120)
        _, mx = _profile_x_range(db)
        assert date.fromisoformat(mx) == date.today() + timedelta(days=130)

    def test_max_uses_last_phase_end_when_later_than_race(self, db):
        """If the last phase ends after the race, extend to the phase end."""
        # phase ends today+200; race today+120 → max = today+210
        _seed_phase(db, start_days_ago=60, end_days_ahead=200)
        _seed_race(db, days_ahead=120)
        _, mx = _profile_x_range(db)
        assert date.fromisoformat(mx) == date.today() + timedelta(days=210)

    def test_min_is_first_phase_minus_two_weeks(self, db):
        _seed_phase(db, start_days_ago=60)
        _seed_race(db, days_ahead=120)
        mn, _ = _profile_x_range(db)
        assert date.fromisoformat(mn) == date.today() - timedelta(days=74)

    def test_no_race_falls_back_to_last_phase_end(self, db):
        _seed_phase(db, end_days_ahead=30)
        _, mx = _profile_x_range(db)
        assert date.fromisoformat(mx) == date.today() + timedelta(days=40)


class TestVolumeChartTimeAxis:
    def _seed_weekly_runs(self, db):
        # 8 weekly easy runs so chart-volume builds with multiple bars.
        for i in range(8):
            d = (date.today() - timedelta(weeks=i)).isoformat()
            db.execute(
                "INSERT INTO activities (id, date, type, distance_km, duration_min, "
                "avg_hr, run_type) VALUES (?, ?, 'running', 10.0, 55, 145, 'easy')",
                (f"v{i}", d),
            )
        db.commit()

    def _volume_cfg(self, db):
        charts = _all_charts(db)
        vol = next((c for c in charts if c["id"] == "chart-volume"), None)
        assert vol is not None, "chart-volume not generated"
        return json.loads(vol["config"])

    def test_volume_x_axis_is_time_with_offset(self, db):
        """Bars-on-time need type:time AND offset:true, or they pin at x=0."""
        self._seed_weekly_runs(db)
        x = self._volume_cfg(db)["options"]["scales"]["x"]
        assert x.get("type") == "time", "volume x-scale must be a baked time scale"
        assert x.get("offset") is True, "time bar chart needs offset:true to render bars"
        assert x.get("time", {}).get("unit") == "week"

    def test_volume_labels_are_iso_dates(self, db):
        """Labels must be ISO dates (not 'YYYY-Www') for the time scale to parse."""
        self._seed_weekly_runs(db)
        labels = self._volume_cfg(db)["data"]["labels"]
        assert labels, "expected weekly labels"
        for lbl in labels:
            # parses as a real date; '2026-W23' would raise
            date.fromisoformat(lbl)


class TestProfileXMaxTemplate:
    def test_template_profilexmax_extends_to_full_plan(self):
        """Guard: profileXMax must span the whole plan (race / last phase end +
        buffer) so every phase and the race marker show — NOT cap near today."""
        html = (REPO / "fit" / "report" / "templates" / "dashboard.html").read_text()
        # No today-based lookahead cap (that hid the future phases + race).
        assert "LOOKAHEAD_DAYS" not in html
        # Extends to the later of race / last phase end.
        assert "trainingPhases[trainingPhases.length - 1].end" in html


class TestChartInitVisibility:
    """Charts must be created while their tab is visible — a chart born in a
    display:none tab gets a 0×0 plot area and never recovers (renders collapsed
    with overlapping axis labels). The template reveals every tab for the
    synchronous init pass, then restores. Guard both halves and their order.
    """

    def _script(self):
        html = (REPO / "fit" / "report" / "templates" / "dashboard.html").read_text()
        return html

    def test_all_tabs_revealed_before_chart_init(self):
        html = self._script()
        reveal = "querySelectorAll('.tab-content').forEach(function (t) { t.style.display = 'block'; })"
        assert reveal in html, "init pass must reveal all tabs before creating charts"
        # The reveal must come BEFORE the chart-instance creation loop.
        assert html.index(reveal) < html.index("const chartInstances = {}"), \
            "tabs must be revealed before charts are constructed"

    def test_tab_visibility_restored_after_init(self):
        html = self._script()
        restore = "querySelectorAll('.tab-content').forEach(function (t) { t.style.display = ''; })"
        assert restore in html, "init pass must restore tab visibility afterwards"
        # Restore must come AFTER the chart loop.
        assert html.index(restore) > html.index("const chartInstances = {}"), \
            "tab visibility must be restored only after charts are constructed"

    def test_showtab_does_not_reintroduce_resize_hack(self):
        """showTab should stay simple — the resize-on-show experiment didn't
        work (hidden-init charts can't recover via resize) and is gone."""
        html = self._script()
        # The function should just toggle classes, not call resize/update.
        start = html.index("function showTab(")
        body = html[start:start + 400]
        assert "resize(" not in body and "resizeTabCharts" not in body


class TestChartSizingStandardization:
    """Chart size is owned by the container (.chart-box + tier class) with a
    fixed height, and charts fill it via maintainAspectRatio:false. This
    replaced the timing-dependent Chart.js aspect inference (which rendered
    charts squashed-or-stretched depending on create-vs-resize timing).
    """

    def _html(self):
        return (REPO / "fit" / "report" / "templates" / "dashboard.html").read_text()

    def _css(self):
        return (REPO / "fit" / "report" / "templates" / "design_system.css").read_text()

    def test_tier_class_on_chart_box_not_bare_canvas(self):
        """Size tiers belong on the .chart-box container; a bare canvas with a
        tier class would size off the canvas's intrinsic box, not the layout."""
        html = self._html()
        # No canvas should carry a tier class directly.
        assert not re.search(r'<canvas[^>]*class="chart-canvas-', html), \
            "tier class must be on the .chart-box, not the <canvas>"
        # And every full chart-box pairs with a tier class.
        boxes = re.findall(r'class="chart-box([^"]*)"', html)
        assert boxes, "expected chart-box containers"
        assert all("chart-canvas-" in b for b in boxes), \
            "every .chart-box must carry a size tier"

    def test_tiers_have_fixed_height_not_aspect_ratio(self):
        """aspect-ratio collapses a box that contains a <canvas>; use fixed px."""
        css = self._css()
        for tier in ("sm", "md", "lg", "xl"):
            m = re.search(r'\.chart-canvas-%s\s*\{([^}]*)\}' % tier, css)
            assert m, f"missing .chart-canvas-{tier} rule"
            assert "height:" in m.group(1), f".chart-canvas-{tier} needs a fixed height"
            assert "aspect-ratio" not in m.group(1), \
                f".chart-canvas-{tier} must not use aspect-ratio (collapses with canvas child)"

    def test_no_tier_class_name_collision(self):
        """The mini-chart utility must not reuse a size-tier class name."""
        css = self._css()
        # chart-canvas-md must be defined exactly once (the tier), not also as
        # a 200px mini utility.
        assert css.count(".chart-canvas-md {") + css.count(".chart-canvas-md{") <= 1, \
            "chart-canvas-md is defined more than once — name collision"
        assert ".chart-canvas-mini" in css, "mini wrapper should use its own class"

    def test_init_loop_sets_maintain_aspect_ratio_false(self):
        html = self._html()
        # Within the per-chart init block, charts must fill the container.
        assert "cfg.options.maintainAspectRatio = false" in html
