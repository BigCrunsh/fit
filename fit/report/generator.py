"""Dashboard HTML generator — thin orchestrator importing from sections/."""

import logging
import sqlite3
from datetime import datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from fit.analysis import RUNNING_TYPES_SQL

logger = logging.getLogger(__name__)

TEMPLATE_DIR = Path(__file__).parent / "templates"
CHARTJS_PATH = Path(__file__).parent / "chartjs.min.js"
ANNOTATION_PATH = Path(__file__).parent / "chartjs-annotation.min.js"
DATE_ADAPTER_PATH = Path(__file__).parent / "chartjs-date-adapter.min.js"

# Import all section generators
from fit.report.sections.cards import (  # noqa: E402
    _headline,
    _headline_signal,
    _status_cards,
    _training_phases_json,
    _checkin,
    _journey,
    _week_over_week,
    _run_timeline,
    _definitions,
    _coaching,
    _milestones,
    _goal_progress,
    _recent_alerts,
    _correlation_bars,
    _phase_compliance,
    _calibration_panel,
    _data_health_panel,
    _sleep_mismatches,
    _trend_badges,
    _why_connectors,
    _race_countdown,
    _walk_break,
    _z2_remediation,
    _rolling_correlations,
    _split_data,
    _upcoming_races,
    _plan_adherence,
    _subtitle,
    _body_summary,
    _volume_story,
    _checkin_progress,
    _status_cards_with_actions,
    _fitness_profile_data,
    _derived_objectives_data,
    _checkpoint_data,
    _prediction_trend_data,
    _next_workouts,
    _overview_objectives,
    _readiness_summary,
    _race_readiness_hero,
    _todays_capability,
    _fitness_gap_analysis,
    _body_comp_data,
    _last_7_days_hero,
    _training_objectives,
    _last_7_days_runs,
    _weekly_plan_adherence,
)
from fit.report.sections.charts import _all_charts  # noqa: E402
from fit.report.sections.predictions import _prediction_summary, _race_prediction  # noqa: E402


def generate_dashboard(conn: sqlite3.Connection, output_path: Path) -> None:
    """Generate the full HTML dashboard from DB data."""
    env = Environment(loader=FileSystemLoader(str(TEMPLATE_DIR)))
    template = env.get_template("dashboard.html")

    chartjs_code = CHARTJS_PATH.read_text() if CHARTJS_PATH.exists() else ""
    annotation_code = ANNOTATION_PATH.read_text() if ANNOTATION_PATH.exists() else ""
    date_adapter_code = DATE_ADAPTER_PATH.read_text() if DATE_ADAPTER_PATH.exists() else ""

    context = {
        "title": "fit — Dashboard",
        "subtitle": _subtitle(conn),
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "chartjs_code": chartjs_code,
        "annotation_code": annotation_code,
        "date_adapter_code": date_adapter_code,
        "tabs": [
            {"id": "overview", "label": "Overview"},
            {"id": "profile", "label": "Profile"},
            {"id": "training", "label": "Training"},
            {"id": "readiness", "label": "Readiness"},
            {"id": "coach", "label": "Coach"},
        ],
        "headline": _headline(conn),
        "headline_signal": _headline_signal(conn),
        "prediction_summary": _prediction_summary(conn),
        "status_cards": _status_cards(conn),
        "checkin": _checkin(conn),
        "journey": _journey(conn),
        "wow": _week_over_week(conn),
        "run_timeline": _run_timeline(conn),
        "charts": _all_charts(conn),
        "definitions": _definitions(conn),
        "race_prediction": _race_prediction(conn),
        "coaching": _coaching(conn),
        "recent_alerts": _recent_alerts(conn),
        "rpe_checkin_count": conn.execute(
            f"SELECT COUNT(*) FROM activities WHERE type IN {RUNNING_TYPES_SQL} AND rpe IS NOT NULL"
        ).fetchone()[0],
        "rpe_garmin_count": conn.execute(
            f"SELECT COUNT(*) FROM activities WHERE type IN {RUNNING_TYPES_SQL} AND aerobic_te IS NOT NULL AND date >= date('now', '-90 days')"
        ).fetchone()[0],
        "run_count": conn.execute(
            f"SELECT COUNT(*) FROM activities WHERE type IN {RUNNING_TYPES_SQL}"
        ).fetchone()[0],
        "milestones": _milestones(conn),
        "goal_progress": _goal_progress(conn),
        "correlation_bars": _correlation_bars(conn),
        "phase_compliance": _phase_compliance(conn),
        "calibration_panel": _calibration_panel(conn),
        "data_health": _data_health_panel(conn),
        "sleep_mismatches": _sleep_mismatches(conn),
        "trend_badges": _trend_badges(conn),
        "why_connectors": _why_connectors(conn),
        "race_countdown": _race_countdown(conn),
        "walk_break": _walk_break(conn),
        "z2_remediation": _z2_remediation(conn),
        "rolling_correlations": _rolling_correlations(conn),
        "split_data": _split_data(conn),
        "plan_adherence": _plan_adherence(conn),
        "upcoming_races": _upcoming_races(conn),
        "fitness_profile": _fitness_profile_data(conn),
        "derived_objectives": _derived_objectives_data(conn),
        "checkpoints": _checkpoint_data(conn),
        "body_summary": _body_summary(conn),
        "volume_story": _volume_story(conn),
        "checkin_progress": _checkin_progress(conn),
        "status_cards_actions": _status_cards_with_actions(conn),
        "prediction_trend": _prediction_trend_data(conn),
        "next_workouts": _next_workouts(conn),
        "overview_objectives": _overview_objectives(conn),
        "readiness_summary": _readiness_summary(conn),
        "race_readiness": _race_readiness_hero(conn),
        "todays_capability": _todays_capability(conn),
        "fitness_gaps": _fitness_gap_analysis(conn),
        "body_comp": _body_comp_data(conn),
        "training_phases_json": _training_phases_json(conn),
        "hero_card": _last_7_days_hero(conn),
        "training_objectives": _training_objectives(conn),
        "last_7_days_runs": _last_7_days_runs(conn),
        "weekly_plan_adherence": _weekly_plan_adherence(conn),
    }

    html = template.render(**context)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html)
    logger.info("Dashboard written to %s (%d bytes)", output_path, len(html))
