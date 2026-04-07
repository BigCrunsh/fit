"""MCP server exposing fitness.db to Claude Chat and Claude Code."""

import json
import logging
import sqlite3
from pathlib import Path

from mcp.server.fastmcp import FastMCP

logger = logging.getLogger(__name__)

# Load config to find DB path (must be after mcp import to avoid circular)
from fit.config import get_config  # noqa: E402

config = get_config(Path(__file__).parent.parent)
db_path = Path(config["sync"]["db_path"]).expanduser()

mcp = FastMCP("fit-mcp", instructions="Personal fitness data platform. Query fitness.db for health, activities, sleep, HRV, training metrics.")


def _get_conn() -> sqlite3.Connection:
    """Get a read-only connection to fitness.db."""
    if not db_path.exists():
        raise FileNotFoundError(
            f"fitness.db not found at {db_path}. Run `fit sync` first to create and populate the database."
        )
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _format_rows(rows: list[sqlite3.Row], max_rows: int = 100) -> str:
    """Format query results as column-aligned text."""
    if not rows:
        return "No results."

    cols = rows[0].keys()
    display = rows[:max_rows]

    # Compute column widths
    widths = {c: len(c) for c in cols}
    for row in display:
        for c in cols:
            widths[c] = max(widths[c], len(str(row[c] if row[c] is not None else "")))

    # Header
    header = " | ".join(c.ljust(widths[c]) for c in cols)
    sep = "-+-".join("-" * widths[c] for c in cols)

    # Rows
    lines = [header, sep]
    for row in display:
        line = " | ".join(str(row[c] if row[c] is not None else "").ljust(widths[c]) for c in cols)
        lines.append(line)

    if len(rows) > max_rows:
        lines.append(f"\n... {len(rows) - max_rows} more rows (showing first {max_rows})")

    return "\n".join(lines)


@mcp.tool()
def execute_sql_query(query: str) -> str:
    """Execute a SELECT query against fitness.db. Only SELECT statements are allowed."""
    stripped = query.strip()
    # Remove leading comments
    while stripped.startswith("--"):
        stripped = stripped.split("\n", 1)[-1].strip()

    if not stripped.upper().startswith("SELECT"):
        return "Error: Only SELECT queries are allowed."

    conn = _get_conn()
    try:
        rows = conn.execute(stripped).fetchall()
        return _format_rows(list(rows))
    except Exception as e:
        return f"SQL Error: {e}"
    finally:
        conn.close()


@mcp.tool()
def get_health_summary(days: int = 7) -> str:
    """Get a summary of recent health metrics for the specified number of days."""
    conn = _get_conn()
    try:
        row = conn.execute("""
            SELECT
                COUNT(*) as days,
                ROUND(AVG(resting_heart_rate), 1) as avg_rhr,
                ROUND(AVG(sleep_duration_hours), 1) as avg_sleep,
                ROUND(AVG(hrv_last_night), 1) as avg_hrv,
                ROUND(AVG(training_readiness), 0) as avg_readiness,
                ROUND(AVG(avg_stress_level), 0) as avg_stress
            FROM daily_health
            WHERE date >= date('now', ?)
        """, (f"-{days} days",)).fetchone()

        if not row or row["days"] == 0:
            return f"No health data available for the last {days} days."

        run_count = conn.execute("""
            SELECT COUNT(*) FROM activities
            WHERE type = 'running' AND date >= date('now', ?)
        """, (f"-{days} days",)).fetchone()[0]

        weight = conn.execute("""
            SELECT weight_kg FROM body_comp ORDER BY date DESC LIMIT 1
        """).fetchone()

        return (
            f"Health Summary (last {days} days):\n"
            f"  Days with data: {row['days']}\n"
            f"  Avg RHR: {row['avg_rhr']} bpm\n"
            f"  Avg Sleep: {row['avg_sleep']} hours\n"
            f"  Avg HRV: {row['avg_hrv']} ms\n"
            f"  Avg Readiness: {row['avg_readiness']}\n"
            f"  Avg Stress: {row['avg_stress']}\n"
            f"  Runs: {run_count}\n"
            f"  Latest Weight: {weight['weight_kg'] if weight else 'N/A'} kg"
        )
    finally:
        conn.close()


@mcp.tool()
def get_run_context(date: str) -> str:
    """Get full context for a run on a specific date (activity + health + checkin + weather + weight)."""
    conn = _get_conn()
    try:
        rows = conn.execute("SELECT * FROM v_run_days WHERE date = ?", (date,)).fetchall()
        if not rows:
            return f"No running activity found for {date}."
        return _format_rows(list(rows))
    finally:
        conn.close()


@mcp.tool()
def explore_database_structure() -> str:
    """List all tables and views with their row counts."""
    conn = _get_conn()
    try:
        objects = conn.execute("""
            SELECT type, name FROM sqlite_master
            WHERE type IN ('table', 'view') AND name NOT LIKE 'sqlite_%'
            ORDER BY type, name
        """).fetchall()

        lines = []
        for obj in objects:
            count = conn.execute(f"SELECT COUNT(*) FROM [{obj['name']}]").fetchone()[0]
            lines.append(f"  {obj['type']:5s} {obj['name']:25s} {count:>6d} rows")

        return "Database Structure:\n" + "\n".join(lines)
    finally:
        conn.close()


@mcp.tool()
def get_table_details(table_name: str) -> str:
    """Get column definitions and sample data for a specific table."""
    conn = _get_conn()
    try:
        # Validate table exists
        exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE name = ? AND type IN ('table', 'view')",
            (table_name,)
        ).fetchone()
        if not exists:
            return f"Error: Table or view '{table_name}' does not exist."

        # Column info
        cols = conn.execute(f"PRAGMA table_info([{table_name}])").fetchall()
        col_lines = [f"  {c['name']:30s} {c['type'] or 'ANY':15s}" for c in cols]

        # Sample data
        samples = conn.execute(f"SELECT * FROM [{table_name}] LIMIT 3").fetchall()
        sample_text = _format_rows(list(samples)) if samples else "  (empty)"

        return f"Table: {table_name}\n\nColumns:\n" + "\n".join(col_lines) + f"\n\nSample data:\n{sample_text}"
    finally:
        conn.close()


@mcp.tool()
def check_dashboard_freshness() -> str:
    """Check if the dashboard and coaching notes are up to date with the latest sync."""
    conn = _get_conn()
    try:
        last_sync = conn.execute("SELECT MAX(date) FROM daily_health").fetchone()[0]
        last_activity = conn.execute("SELECT MAX(date) FROM activities").fetchone()[0]

        report_path = Path(config["sync"]["db_path"]).expanduser().parent / "reports" / "dashboard.html"
        coaching_path = Path(config["sync"]["db_path"]).expanduser().parent / "reports" / "coaching.json"

        # Check report file
        report_date = None
        if report_path.exists():
            import os
            mtime = os.path.getmtime(report_path)
            from datetime import datetime
            report_date = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M")

        # Check coaching file
        coaching_date = None
        if coaching_path.exists():
            import json as _json
            data = _json.loads(coaching_path.read_text())
            coaching_date = data.get("generated_at", "unknown")

        return (
            f"Dashboard Freshness:\n"
            f"  Last health sync: {last_sync or 'never'}\n"
            f"  Last activity sync: {last_activity or 'never'}\n"
            f"  Dashboard report: {report_date or 'not generated'}\n"
            f"  Coaching notes: {coaching_date or 'not generated'}"
        )
    finally:
        conn.close()


def _ctx_profile(conn) -> list[str]:
    """Zone boundaries, calibrations, thresholds."""
    s = []
    max_hr = config.get("profile", {}).get("max_hr")
    zones_maxhr = config.get("profile", {}).get("zones_max_hr", {})
    zone_model = config.get("profile", {}).get("zone_model", "max_hr")
    s.append(f"Profile: max_hr={max_hr}, zone_model={zone_model}")
    z2_bounds = zones_maxhr.get("z2", [115, 134])
    z4_bounds = zones_maxhr.get("z4", [154, 173])
    s.append(f"Zone boundaries (max HR model): Z2 (Easy)={z2_bounds[0]}-{z2_bounds[1]} bpm, "
             f"Z3 (Moderate)={zones_maxhr.get('z3', [134, 154])[0]}-{zones_maxhr.get('z3', [134, 154])[1]}, "
             f"Z4 (Hard)={z4_bounds[0]}-{z4_bounds[1]}")
    s.append(f"IMPORTANT: Easy runs must stay below {z2_bounds[1]} bpm (Z2 ceiling), NOT 150 bpm")
    from fit.calibration import get_active_calibration as _get_cal, get_calibration_status
    lthr_cal = _get_cal(conn, "lthr")
    if lthr_cal:
        s.append(f"LTHR: {lthr_cal['value']} bpm ({lthr_cal['method']}, {lthr_cal['date']})")
        s.append(f"Zone boundaries (LTHR model): Z2={round(lthr_cal['value']*0.85)}-{round(lthr_cal['value']*0.89)}, "
                 f"Z4={round(lthr_cal['value']*0.95)}-{round(lthr_cal['value']*0.99)}")
    stale_cals = [c for c in get_calibration_status(conn) if c["stale"]]
    if stale_cals:
        s.append("Stale calibrations: " + ", ".join(f"{c['metric']} ({c['retest_prompt']})" for c in stale_cals))
    return s


def _ctx_health(conn) -> list[str]:
    """Recent health metrics, ACWR."""
    s = []
    acwr_safe = config.get("analysis", {}).get("acwr_safe_range", [0.8, 1.3])
    acwr_danger = config.get("analysis", {}).get("acwr_danger_threshold", 1.5)
    acwr_row = conn.execute("SELECT week, acwr FROM weekly_agg WHERE acwr IS NOT NULL ORDER BY week DESC LIMIT 1").fetchone()
    if acwr_row:
        acwr = acwr_row["acwr"]
        safety = "SAFE" if acwr_safe[0] <= acwr <= acwr_safe[1] else "CAUTION" if acwr <= acwr_danger else "DANGER"
        s.append(f"ACWR: {acwr} ({safety})")
    health = conn.execute("""
        SELECT ROUND(AVG(resting_heart_rate), 1) as rhr, ROUND(AVG(sleep_duration_hours), 1) as sleep,
               ROUND(AVG(hrv_last_night), 1) as hrv, ROUND(AVG(training_readiness), 0) as readiness
        FROM daily_health WHERE date >= date('now', '-7 days')
    """).fetchone()
    if health:
        s.append(f"Last 7d: RHR={health['rhr']}, Sleep={health['sleep']}h, HRV={health['hrv']}, Readiness={health['readiness']}")
    streak = conn.execute("SELECT consecutive_weeks_3plus FROM weekly_agg ORDER BY week DESC LIMIT 1").fetchone()
    if streak:
        s.append(f"Consistency streak: {streak['consecutive_weeks_3plus']} weeks with 3+ runs")
    return s


def _ctx_training(conn) -> list[str]:
    """Zone distribution, run types, efficiency, active phase."""
    s = []
    zones = conn.execute("""
        SELECT ROUND(AVG(z12_pct), 1) as avg_z12, ROUND(AVG(z45_pct), 1) as avg_z45
        FROM weekly_agg WHERE week >= (SELECT MAX(week) FROM weekly_agg WHERE week <= date('now'))
        ORDER BY week DESC LIMIT 4
    """).fetchone()
    if zones and zones["avg_z12"] is not None:
        s.append(f"Zone distribution (4wk avg): Z1+Z2={zones['avg_z12']}%, Z4+Z5={zones['avg_z45']}%")
    phase = conn.execute("SELECT * FROM training_phases WHERE status = 'active' LIMIT 1").fetchone()
    if phase:
        s.append(f"Active phase: {phase['phase']} — {phase['name']} ({phase['start_date']} to {phase['end_date']})")
        if phase["z12_pct_target"]:
            s.append(f"  Phase Z1+Z2 target: {phase['z12_pct_target']}%")
    types = conn.execute("""
        SELECT run_type, COUNT(*) as n FROM activities
        WHERE type = 'running' AND date >= date('now', '-28 days')
        GROUP BY run_type ORDER BY n DESC
    """).fetchall()
    if types:
        s.append("Run types (4wk): " + ", ".join(f"{r['run_type']}:{r['n']}" for r in types))
    spb = conn.execute("""
        SELECT ROUND(AVG(speed_per_bpm), 3) as recent FROM activities
        WHERE type = 'running' AND speed_per_bpm IS NOT NULL AND date >= date('now', '-28 days')
    """).fetchone()
    spb_prev = conn.execute("""
        SELECT ROUND(AVG(speed_per_bpm), 3) as prev FROM activities
        WHERE type = 'running' AND speed_per_bpm IS NOT NULL
        AND date BETWEEN date('now', '-56 days') AND date('now', '-29 days')
    """).fetchone()
    if spb and spb["recent"]:
        trend = ""
        if spb_prev and spb_prev["prev"]:
            diff = spb["recent"] - spb_prev["prev"]
            trend = f" (vs prev 4wk: {'↑' if diff > 0 else '↓'}{abs(diff):.3f})"
        s.append(f"Speed/BPM (4wk avg): {spb['recent']}{trend}")
    return s


def _ctx_correlations(conn) -> list[str]:
    """Top correlations + recent alerts."""
    s = []
    try:
        corrs = conn.execute("""
            SELECT metric_pair, spearman_r, sample_size, confidence
            FROM correlations WHERE status = 'computed' AND spearman_r IS NOT NULL
            ORDER BY ABS(spearman_r) DESC LIMIT 5
        """).fetchall()
        if corrs:
            s.append("Top correlations: " + ", ".join(
                f"{c['metric_pair']} r={c['spearman_r']:+.2f} (n={c['sample_size']}, {c['confidence']})" for c in corrs))
    except Exception:
        pass
    try:
        from fit.alerts import get_recent_alerts
        alerts = get_recent_alerts(conn, days=7)
        if alerts:
            s.append(f"Active alerts ({len(alerts)}): " + "; ".join(a["message"][:80] for a in alerts[:3]))
    except Exception:
        pass
    return s


def _ctx_splits(conn) -> list[str]:
    """Split analysis from most recent long run."""
    s = []
    try:
        # Most recent running activity with splits
        act = conn.execute("""
            SELECT a.id, a.date, a.name, a.distance_km, a.temp_at_start_c, a.humidity_at_start_pct
            FROM activities a
            WHERE a.type = 'running' AND a.splits_status = 'done'
            ORDER BY a.date DESC LIMIT 1
        """).fetchone()
        if not act:
            return s

        splits = conn.execute("""
            SELECT split_num, pace_sec_per_km, avg_hr, avg_cadence, time_above_z2_ceiling_sec
            FROM activity_splits WHERE activity_id = ? ORDER BY split_num
        """, (act["id"],)).fetchall()
        if not splits:
            return s

        split_dicts = [dict(sp) for sp in splits]

        from fit.fit_file import compute_cardiac_drift, compute_pace_variability, compute_cadence_drift, flag_heat_affected

        drift = compute_cardiac_drift(split_dicts)
        pace_cv = compute_pace_variability(split_dicts)
        cadence = compute_cadence_drift(split_dicts)
        heat = flag_heat_affected(dict(act))

        s.append(f"Latest split analysis: {act['name']} ({act['date']}, {act['distance_km']}km)")
        if drift["status"] == "detected":
            s.append(f"  Cardiac drift: {drift['drift_pct']:.1f}% (onset at km {drift['drift_onset_km']})")
        elif drift["status"] == "inconclusive_variable_pace":
            s.append(f"  Cardiac drift: inconclusive (pace CV={drift['pace_cv_pct']:.1f}%)")
        elif drift["status"] == "none":
            s.append(f"  Cardiac drift: none detected ({drift['drift_pct']:.1f}%)")

        if pace_cv is not None:
            s.append(f"  Pace variability: CV={pace_cv:.1f}%")
        if cadence:
            s.append(f"  Cadence drift: {cadence['drift_pct']:+.1f}% ({cadence['status']})")
        if heat:
            s.append("  HEAT-AFFECTED: >25C or >70% humidity — HR zones less reliable")
    except Exception:
        pass
    return s


def _ctx_plan(conn) -> list[str]:
    """Plan adherence and next planned workout."""
    s = []
    try:
        from fit.plan import compute_plan_adherence, get_readiness_recommendation

        # Plan adherence
        adherence = compute_plan_adherence(conn)
        if adherence and adherence.get("compliance_pct") is not None:
            s.append(f"Plan adherence: {adherence['compliance_pct']:.0f}% weekly compliance")
            if adherence.get("missed_count"):
                s.append(f"  Missed workouts: {adherence['missed_count']}")
            if adherence.get("override_pattern"):
                s.append(f"  Override pattern: {adherence['override_pattern']}")

        # Next planned workout
        next_workout = conn.execute("""
            SELECT date, workout_name, workout_type, target_distance_km
            FROM planned_workouts
            WHERE date >= date('now') AND status = 'active'
            ORDER BY date, sequence_ordinal LIMIT 1
        """).fetchone()
        if next_workout:
            dist = f"{next_workout['target_distance_km']:.1f}km" if next_workout["target_distance_km"] else ""
            s.append(f"Next planned: {next_workout['workout_name']} ({next_workout['workout_type']}) "
                     f"{dist} on {next_workout['date']}")

        # Readiness recommendation
        try:
            config = {"coaching": {"readiness_gate_threshold": 40}}
            rec = get_readiness_recommendation(conn, config)
            if rec and rec.get("swap_recommended"):
                s.append(f"  READINESS WARNING: {rec['message']}")
        except Exception:
            pass
    except Exception:
        pass
    return s


def _ctx_goals(conn) -> list[str]:
    """Active goals."""
    s = []
    goals = conn.execute("SELECT name, type, target_date FROM goals WHERE active = 1").fetchall()
    if goals:
        s.append("Goals: " + "; ".join(f"{g['name']} ({g['target_date'] or 'no date'})" for g in goals))
    return s


@mcp.tool()
def get_coaching_context() -> str:
    """Get structured data summary for coaching analysis. Returns key metrics, trends, and status."""
    conn = _get_conn()
    try:
        sections = []
        sections.extend(_ctx_profile(conn))
        sections.extend(_ctx_health(conn))
        sections.extend(_ctx_training(conn))
        sections.extend(_ctx_correlations(conn))
        sections.extend(_ctx_goals(conn))
        sections.extend(_ctx_plan(conn))
        return "Coaching Context:\n" + "\n".join(f"  {s}" for s in sections)
    finally:
        conn.close()


@mcp.tool()
def save_coaching_notes(insights_json: str) -> str:
    """Save coaching insights to reports/coaching.json. Pass a JSON array where EACH insight MUST have: type (critical/warning/positive/info/target), title (short), and body (FULL analysis paragraph with specific numbers and recommendations — minimum 20 chars, typically 2-5 sentences). Insights without body text will be rejected."""
    from datetime import datetime

    try:
        data = json.loads(insights_json)
    except json.JSONDecodeError as e:
        return f"Error: Invalid JSON: {e}"

    if "insights" not in data:
        if isinstance(data, list):
            data = {"insights": data}
        else:
            return "Error: JSON must contain an 'insights' array."

    # Validate each insight has type, title, AND body with actual content
    errors = []
    for i, insight in enumerate(data.get("insights", [])):
        if not insight.get("type"):
            errors.append(f"Insight {i}: missing 'type' (critical/warning/positive/info/target)")
        if not insight.get("title"):
            errors.append(f"Insight {i}: missing 'title'")
        if not insight.get("body") or len(str(insight.get("body", ""))) < 20:
            errors.append(f"Insight {i} ('{insight.get('title', '?')}'): missing or too short 'body' — "
                          "each insight MUST include the full analysis paragraph, not just a title. "
                          "The body should contain specific numbers, context, and actionable recommendations.")
    if errors:
        return "Error: Insights validation failed. Fix these issues and re-save:\n" + "\n".join(errors)

    data["generated_at"] = datetime.now().isoformat()
    data["report_date"] = datetime.now().strftime("%Y-%m-%d")

    reports_dir = Path(config["sync"]["db_path"]).expanduser().parent / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    coaching_path = reports_dir / "coaching.json"

    # Atomic write: temp file + rename
    tmp_path = coaching_path.with_suffix(".tmp")
    tmp_path.write_text(json.dumps(data, indent=2))
    tmp_path.rename(coaching_path)

    n = len(data.get("insights", []))
    return f"Saved {n} coaching insights to {coaching_path}"


if __name__ == "__main__":
    mcp.run()
