"""Dashboard section generators — decomposed re-exports from generator.py.

Import from here for clean access to individual sections:
    from fit.report.sections import generate_dashboard
    from fit.report.sections import status_cards, all_charts, race_prediction
"""

# ruff: noqa: F401
# Re-export the main entry point
from fit.report.generator import generate_dashboard

# Re-export section groups for targeted imports
from fit.report.generator import (
    _status_cards as status_cards,
    _checkin as checkin,
    _journey as journey,
    _goal_progress as goal_progress,
    _milestones as milestones,
    _recent_alerts as recent_alerts,
    _phase_compliance as phase_compliance,
    _calibration_panel as calibration_panel,
    _data_health_panel as data_health_panel,
    _sleep_mismatches as sleep_mismatches,
    _upcoming_races as upcoming_races,
    _headline as headline,
    _headline_signal as headline_signal,
    _week_over_week as week_over_week,
    _run_timeline as run_timeline,
    _all_charts as all_charts,
    _get_event_annotations as event_annotations,
    _race_prediction as race_prediction,
    _prediction_summary as prediction_summary,
    _coaching as coaching,
    _correlation_bars as correlation_bars,
    _trend_badges as trend_badges,
    _why_connectors as why_connectors,
    _race_countdown as race_countdown,
    _walk_break as walk_break,
    _z2_remediation as z2_remediation,
    _rolling_correlations as rolling_correlations,
    _split_data as split_data,
    _plan_adherence as plan_adherence,
    _definitions as definitions,
)

__all__ = ["generate_dashboard"]
