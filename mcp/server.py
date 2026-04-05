"""MCP server exposing fitness.db to Claude Chat and Claude Code."""

import json
import logging
import sqlite3
from pathlib import Path

from mcp.server.fastmcp import FastMCP

logger = logging.getLogger(__name__)

# Load config to find DB path
from fit.config import get_config

config = get_config(Path(__file__).parent.parent)
db_path = Path(config["sync"]["db_path"]).expanduser()

mcp = FastMCP("fit-mcp", instructions="Personal fitness data platform. Query fitness.db for health, activities, sleep, HRV, training metrics.")


def _get_conn() -> sqlite3.Connection:
    """Get a read-only connection to fitness.db."""
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


@mcp.tool()
def get_coaching_context() -> str:
    """Get structured data summary for coaching analysis. Returns key metrics, trends, and status."""
    conn = _get_conn()
    try:
        sections = []

        # ACWR
        acwr_row = conn.execute("SELECT week, acwr FROM weekly_agg WHERE acwr IS NOT NULL ORDER BY week DESC LIMIT 1").fetchone()
        if acwr_row:
            acwr = acwr_row["acwr"]
            safety = "SAFE" if 0.8 <= acwr <= 1.3 else "CAUTION" if acwr <= 1.5 else "DANGER"
            sections.append(f"ACWR: {acwr} ({safety})")

        # Zone distribution (last 4 weeks)
        zones = conn.execute("""
            SELECT ROUND(AVG(z12_pct), 1) as avg_z12, ROUND(AVG(z45_pct), 1) as avg_z45
            FROM weekly_agg WHERE week >= (SELECT MAX(week) FROM weekly_agg WHERE week <= date('now'))
            ORDER BY week DESC LIMIT 4
        """).fetchone()
        if zones and zones["avg_z12"] is not None:
            sections.append(f"Zone distribution (4wk avg): Z1+Z2={zones['avg_z12']}%, Z4+Z5={zones['avg_z45']}%")

        # Active phase
        phase = conn.execute("SELECT * FROM training_phases WHERE status = 'active' LIMIT 1").fetchone()
        if phase:
            sections.append(f"Active phase: {phase['phase']} — {phase['name']} ({phase['start_date']} to {phase['end_date']})")
            if phase["z12_pct_target"]:
                sections.append(f"  Phase Z1+Z2 target: {phase['z12_pct_target']}%")

        # Run type breakdown (last 4 weeks)
        types = conn.execute("""
            SELECT run_type, COUNT(*) as n FROM activities
            WHERE type = 'running' AND date >= date('now', '-28 days')
            GROUP BY run_type ORDER BY n DESC
        """).fetchall()
        if types:
            type_str = ", ".join(f"{r['run_type']}:{r['n']}" for r in types)
            sections.append(f"Run types (4wk): {type_str}")

        # Speed per BPM trend
        spb = conn.execute("""
            SELECT ROUND(AVG(speed_per_bpm), 3) as recent
            FROM activities WHERE type = 'running' AND speed_per_bpm IS NOT NULL
            AND date >= date('now', '-28 days')
        """).fetchone()
        spb_prev = conn.execute("""
            SELECT ROUND(AVG(speed_per_bpm), 3) as prev
            FROM activities WHERE type = 'running' AND speed_per_bpm IS NOT NULL
            AND date BETWEEN date('now', '-56 days') AND date('now', '-29 days')
        """).fetchone()
        if spb and spb["recent"]:
            trend = ""
            if spb_prev and spb_prev["prev"]:
                diff = spb["recent"] - spb_prev["prev"]
                trend = f" (vs prev 4wk: {'↑' if diff > 0 else '↓'}{abs(diff):.3f})"
            sections.append(f"Speed/BPM (4wk avg): {spb['recent']}{trend}")

        # Consistency
        streak = conn.execute("SELECT consecutive_weeks_3plus FROM weekly_agg ORDER BY week DESC LIMIT 1").fetchone()
        if streak:
            sections.append(f"Consistency streak: {streak['consecutive_weeks_3plus']} weeks with 3+ runs")

        # Calibration status
        from fit.calibration import get_calibration_status
        cal_status = get_calibration_status(conn)
        stale_cals = [c for c in cal_status if c["stale"]]
        if stale_cals:
            sections.append("Stale calibrations: " + ", ".join(f"{c['metric']} ({c['retest_prompt']})" for c in stale_cals))

        # Recent health
        health = conn.execute("""
            SELECT ROUND(AVG(resting_heart_rate), 1) as rhr, ROUND(AVG(sleep_duration_hours), 1) as sleep,
                   ROUND(AVG(hrv_last_night), 1) as hrv, ROUND(AVG(training_readiness), 0) as readiness
            FROM daily_health WHERE date >= date('now', '-7 days')
        """).fetchone()
        if health:
            sections.append(f"Last 7d: RHR={health['rhr']}, Sleep={health['sleep']}h, HRV={health['hrv']}, Readiness={health['readiness']}")

        # Goals
        goals = conn.execute("SELECT name, type, target_date FROM goals WHERE active = 1").fetchall()
        if goals:
            sections.append("Goals: " + "; ".join(f"{g['name']} ({g['target_date'] or 'no date'})" for g in goals))

        return "Coaching Context:\n" + "\n".join(f"  {s}" for s in sections)
    finally:
        conn.close()


@mcp.tool()
def save_coaching_notes(insights_json: str) -> str:
    """Save coaching insights to reports/coaching.json. Pass a JSON string with insights array."""
    from datetime import datetime

    try:
        data = json.loads(insights_json)
    except json.JSONDecodeError as e:
        return f"Error: Invalid JSON: {e}"

    if "insights" not in data:
        # Wrap bare array
        if isinstance(data, list):
            data = {"insights": data}
        else:
            return "Error: JSON must contain an 'insights' array."

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
