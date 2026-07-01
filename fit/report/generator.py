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
    _training_phases_json,
    _definitions,
    _physiology,
    _pace_zones,
    _concepts,
    _attention_items,
    _prediction_confidence,
    _calibration_history,
    _vdot_comparison,
    _coaching,
    _recent_alerts,
    _phase_compliance,
    _calibration_panel,
    _data_health_panel,
    _race_countdown,
    _split_data,
    _subtitle,
    _body_summary,
    _fitness_profile_data,
    _checkpoint_data,
    _prediction_trend_data,
    _overview_hub,
    _readiness_summary,
    _race_readiness_hero,
    _todays_capability,
    _fitness_gap_analysis,
    _body_comp_data,
    _profile_takeaways,
    _last_7_days_hero,
    _training_objectives,
    _last_7_days_runs,
    _weekly_plan_adherence,
)
from fit.report.sections.charts import _all_charts  # noqa: E402
from fit.report.sections.predictions import _prediction_summary, _marathon_forecast  # noqa: E402


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
        # Triage order (recovery → consistency → physiology → synthesis); `job` is the
        # one-line decision each tab supports, shown as a subtitle (dashboard-information-architecture).
        "tabs": [
            {"id": "overview", "label": "Overview", "job": "On track? And the one thing to do."},
            {"id": "readiness", "label": "Readiness", "job": "Can I absorb training — am I fresh?"},
            {"id": "training", "label": "Training", "job": "Am I doing the work?"},
            {"id": "profile", "label": "Profile", "job": "Who am I — and what will race day give?"},
            {"id": "coach", "label": "Coach", "job": "The plan, and why."},
        ],
        "headline": _headline(conn),
        "headline_signal": _headline_signal(conn),
        "prediction_summary": _prediction_summary(conn),
        "marathon_forecast": _marathon_forecast(conn),
        "charts": _all_charts(conn),
        "definitions": _definitions(conn),
        "physiology": _physiology(conn),
        "pace_zones": _pace_zones(conn),
        "concepts": _concepts(),
        "attention_items": _attention_items(conn),
        "prediction_confidence": _prediction_confidence(conn),
        "calibration_history": _calibration_history(conn),
        "vdot_comparison": _vdot_comparison(conn),
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
        "phase_compliance": _phase_compliance(conn),
        "calibration_panel": _calibration_panel(conn),
        "data_health": _data_health_panel(conn),
        "race_countdown": _race_countdown(conn),
        "split_data": _split_data(conn),
        "fitness_profile": _fitness_profile_data(conn),
        "checkpoints": _checkpoint_data(conn),
        "body_summary": _body_summary(conn),
        "prediction_trend": _prediction_trend_data(conn),
        "overview_hub": _overview_hub(conn),
        "readiness_summary": _readiness_summary(conn),
        "race_readiness": _race_readiness_hero(conn),
        "todays_capability": _todays_capability(conn),
        "fitness_gaps": _fitness_gap_analysis(conn),
        "body_comp": _body_comp_data(conn),
        "profile_takeaways": _profile_takeaways(conn),
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
