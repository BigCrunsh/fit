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


if __name__ == "__main__":
    mcp.run()
