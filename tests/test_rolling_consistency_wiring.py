"""Every consumer of "consistency" reads the rolling measure, not the ISO-week streak.

`consecutive_weeks_3plus` is still written to weekly_agg for historical continuity,
but nothing reads it to decide or display anything: an every-other-day plan whose
runs a week boundary split 3/2 was reported as "0 weeks of consistency" while the
athlete had completed every scheduled session. These tests pin each consumer to
`compute_run_frequency`, so the panel, the CLI, the objective and the coach can no
longer disagree with each other.
"""

from datetime import date, timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# Every other day for 10 weeks: nothing skipped, but ISO weeks split it 3/4/3/3...
STEADY = [(i * 2, 10.0) for i in range(35)]
# One run a week: genuinely thin.
THIN = [(i * 7, 10.0) for i in range(9)]


def _runs(db, offsets_km):
    for i, (offset, km) in enumerate(offsets_km):
        d = (date.today() - timedelta(days=offset)).isoformat()
        db.execute("INSERT INTO activities (id, date, type, distance_km, duration_min) "
                   "VALUES (?, ?, 'running', ?, ?)", (f"c{i}", d, km, km * 6))
    db.commit()


def _iso_week_row(db, run_count, streak):
    """A weekly_agg row whose ISO streak disagrees with the rolling reality."""
    iso = date.today().isocalendar()
    db.execute(
        "INSERT INTO weekly_agg (week, run_km, run_count, consecutive_weeks_3plus, "
        "longest_run_km, z12_pct) VALUES (?, 20, ?, ?, 14, 80)",
        (f"{iso[0]}-W{iso[1]:02d}", run_count, streak),
    )
    db.commit()


# ── the source guard ──

class TestNothingReadsTheIsoStreak:
    def test_only_analysis_writes_the_column(self):
        # A grep-style guard: the identifier may appear where the column is
        # WRITTEN (fit/analysis.py) and nowhere else in decision or display code.
        offenders = []
        for path in (REPO_ROOT / "fit").rglob("*.py"):
            if path.name == "analysis.py":
                continue
            text = path.read_text()
            if "consecutive_weeks_3plus" in text:
                offenders.append(str(path.relative_to(REPO_ROOT)))
        assert offenders == [], (
            "these still read the ISO-week streak instead of compute_run_frequency: "
            + ", ".join(offenders)
        )

    def test_the_column_is_still_written_for_history(self, db):
        # Historical continuity: dropping it would rewrite the past.
        from fit.analysis import compute_weekly_agg
        cols = [r[1] for r in db.execute("PRAGMA table_info(weekly_agg)")]
        assert "consecutive_weeks_3plus" in cols
        assert callable(compute_weekly_agg)


# ── the coaching context ──

class TestCoachContext:
    def test_reports_frequency_as_a_rate(self, db):
        import fit.coaching.context as ctx
        _runs(db, STEADY)
        text = "\n".join(ctx._ctx_health(db))
        assert "Frequency:" in text and "runs/7d" in text
        assert "Consistency streak" not in text

    def test_reports_volume_change_as_rolling_not_calendar(self, db):
        import fit.coaching.context as ctx
        _runs(db, STEADY)
        text = "\n".join(ctx._ctx_health(db))
        assert "Volume change:" in text
        assert "rolling windows, NOT calendar weeks" in text

    def test_steady_plan_is_not_described_as_zero_consistency(self, db):
        import fit.coaching.context as ctx
        _runs(db, STEADY)
        _iso_week_row(db, run_count=2, streak=0)      # the ISO view says 0
        text = "\n".join(ctx._ctx_health(db))
        freq_line = next(ln for ln in ctx._ctx_health(db) if ln.startswith("Frequency:"))
        # The ISO row says 0; the rolling measure must report the real cadence.
        assert " 0% of the last" not in freq_line
        assert "= 0.0 weeks sustained" not in freq_line
        assert "3.50 runs/7d" in text          # every other day = 3.5 runs per week


# ── the objective ──

class TestConsistencyObjective:
    def _objective(self, db, runs, target_weeks=8):
        from fit.fitness import compute_achievability
        _runs(db, runs)
        objs = [{"name": f"Consistency {target_weeks}wk", "type": "habit",
                 "target_value": target_weeks, "target_unit": "consecutive_weeks"}]
        return compute_achievability(db, objs, days_remaining=60)[0]

    def test_steady_plan_scores_near_its_target(self, db):
        obj = self._objective(db, STEADY, target_weeks=8)
        assert obj["current_value"] > 6          # ISO streak reported 0 here

    def test_thin_training_scores_low(self, db):
        obj = self._objective(db, THIN, target_weeks=8)
        assert obj["current_value"] == 0

    def test_no_runs_is_zero_not_none(self, db):
        obj = self._objective(db, [], target_weeks=8)
        assert obj["current_value"] == 0

    def test_window_matches_the_objective_length(self, db):
        # A 4-week objective is judged over 4 weeks and a 12-week one over 12, so
        # each score is capped by its own target rather than a fixed 8-week window.
        from fit.fitness import compute_achievability
        _runs(db, STEADY)
        scores = {}
        for weeks in (4, 12):
            objs = [{"name": f"Consistency {weeks}wk", "type": "habit",
                     "target_value": weeks, "target_unit": "consecutive_weeks"}]
            scores[weeks] = compute_achievability(db, objs, days_remaining=60)[0]["current_value"]
        assert scores[4] <= 4
        assert scores[12] > scores[4]


# ── the dashboard ──

class TestDashboardObjectives:
    def test_overview_streak_uses_rolling_frequency(self, db):
        from fit.report.sections.cards import _overview_objectives
        _runs(db, STEADY)
        _iso_week_row(db, run_count=2, streak=0)
        out = _overview_objectives(db)
        assert out is not None
        tile = next(o for o in out if o["label"] == "Consistency")
        assert float(tile["value"]) > 6

    def test_overview_history_series_is_rolling(self, db):
        from fit.report.sections.cards import _objective_history
        _runs(db, STEADY)
        _iso_week_row(db, run_count=2, streak=0)
        hist = _objective_history(db)
        assert len(hist["consistency"]) == 8
        assert max(hist["consistency"]) > 0      # ISO column would give all zeros

    def test_training_strip_has_no_updates_monday_label(self, db):
        # "streak secured, updates Monday" is ISO-week framing; a rolling measure
        # updates every day.
        from fit.report.sections.cards import _training_objectives
        _runs(db, STEADY)
        _iso_week_row(db, run_count=2, streak=0)
        slots = _training_objectives(db)["slots"]
        labels = " ".join(str(s.get("streak_label") or "") for s in slots)
        assert "updates Monday" not in labels

    def test_training_strip_consistency_is_rolling(self, db):
        from fit.report.sections.cards import _training_objectives
        _runs(db, STEADY)
        _iso_week_row(db, run_count=2, streak=0)
        slots = _training_objectives(db)["slots"]
        slot = next(s for s in slots if s["name"] == "Consistency")
        assert slot["current"] > 6

    def test_dashboard_survives_no_data(self, db):
        from fit.report.sections.cards import _objective_history, _training_objectives
        assert _objective_history(db) == {} or "consistency" in _objective_history(db)
        assert isinstance(_training_objectives(db)["slots"], list)
