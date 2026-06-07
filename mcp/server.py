"""MCP server exposing fitness.db to Claude Chat and Claude Code."""

import json
import logging
import sqlite3
from pathlib import Path

from mcp.server.fastmcp import FastMCP

logger = logging.getLogger(__name__)

# Load config to find DB path (must be after mcp import to avoid circular)
from fit.analysis import RUNNING_TYPES_SQL  # noqa: E402
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

        run_count = conn.execute(f"""
            SELECT COUNT(*) FROM activities
            WHERE type IN {RUNNING_TYPES_SQL} AND date >= date('now', ?)
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
    """Check if the dashboard and coaching notes are up to date. Coaching uses 7-day cadence."""
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

        # Check coaching file — 7-day staleness, not sync-based
        coaching_date = None
        coaching_stale = False
        if coaching_path.exists():
            import json as _json
            from datetime import date as _date
            data = _json.loads(coaching_path.read_text())
            coaching_date = data.get("report_date", data.get("generated_at", "unknown"))
            try:
                coaching_dt = _date.fromisoformat(coaching_date[:10])
                coaching_age_days = (_date.today() - coaching_dt).days
                coaching_stale = coaching_age_days > 7
            except (ValueError, TypeError):
                coaching_stale = True
                coaching_age_days = None

        stale_msg = ""
        if coaching_stale and coaching_date:
            stale_msg = f" (STALE — {coaching_age_days}d old, weekly review recommended)"
        elif coaching_date:
            stale_msg = f" (fresh — {coaching_age_days}d old)"

        return (
            f"Dashboard Freshness:\n"
            f"  Last health sync: {last_sync or 'never'}\n"
            f"  Last activity sync: {last_activity or 'never'}\n"
            f"  Dashboard report: {report_date or 'not generated'}\n"
            f"  Coaching notes: {coaching_date or 'not generated'}{stale_msg}"
        )
    finally:
        conn.close()


def _ctx_profile(conn) -> list[str]:
    """Zone boundaries, calibrations, thresholds — anchored to the ACTIVE model.

    The "easy ceiling" coaching keys off MUST be the active model's Z2 upper
    bound. When zone_model is 'lthr' that's the LTHR Z2 ceiling (~153 at
    LTHR 172), NOT the stricter max-HR diagnostic ceiling (134) — emitting
    the wrong one makes coaching flag legitimate Z2 easy runs as too hard.
    All boundaries are read from config (zones_lthr / zones_max_hr), never
    from hardcoded multipliers.
    """
    s = []
    profile = config.get("profile", {})
    max_hr = profile.get("max_hr")
    zone_model = profile.get("zone_model", "max_hr")
    zones_maxhr = profile.get("zones_max_hr", {})
    s.append(f"Profile: max_hr={max_hr}, zone_model={zone_model}")

    from fit.calibration import get_active_calibration as _get_cal, get_calibration_status
    lthr_cal = _get_cal(conn, "lthr")

    # Max-HR boundaries (diagnostic unless zone_model == 'max_hr')
    z2_max = zones_maxhr.get("z2", [115, 134])
    maxhr_ceiling = z2_max[1]
    s.append(f"Zone boundaries (max HR model): Z2 (Easy)={z2_max[0]}-{z2_max[1]} bpm, "
             f"Z3 (Moderate)={zones_maxhr.get('z3', [134, 154])[0]}-{zones_maxhr.get('z3', [134, 154])[1]}, "
             f"Z4 (Hard)={zones_maxhr.get('z4', [154, 173])[0]}-{zones_maxhr.get('z4', [154, 173])[1]}")

    # LTHR boundaries from config percentages (primary when zone_model == 'lthr')
    lthr_ceiling = None
    if lthr_cal:
        lthr = lthr_cal["value"]
        zl = profile.get("zones_lthr", {})
        z2_pct = zl.get("z2_pct", [85, 89])
        z4_pct = zl.get("z4_pct", [95, 99])
        lthr_ceiling = round(lthr * z2_pct[1] / 100)
        s.append(f"LTHR: {lthr} bpm ({lthr_cal['method']}, {lthr_cal['date']})")
        s.append(f"Zone boundaries (LTHR model): Z2={round(lthr * z2_pct[0] / 100)}-{lthr_ceiling}, "
                 f"Z4={round(lthr * z4_pct[0] / 100)}-{round(lthr * z4_pct[1] / 100)}")

    # The binding easy ceiling is the ACTIVE model's — this is what coaching must use.
    if zone_model == "lthr" and lthr_ceiling is not None:
        s.append(f"IMPORTANT: zone_model is LTHR — easy runs must stay below {lthr_ceiling} bpm "
                 f"(LTHR Z2 ceiling), NOT the max-HR ceiling ({maxhr_ceiling}) and NOT 150 bpm")
    else:
        s.append(f"IMPORTANT: easy runs must stay below {maxhr_ceiling} bpm (Z2 ceiling), NOT 150 bpm")

    # Fitness anchor — the SINGLE standardized VDOT (get_calibration_anchor): the
    # human-confirmed sticky value, or the windowed-max policy estimate. The GAP
    # to Garmin's wrist-HR VO2max is the signal: a large positive gap means Garmin
    # is optimistic and prediction should trust the anchor (see dashboard VDOT Trend).
    try:
        from fit.calibration import get_calibration_anchor
        anchor = get_calibration_anchor(conn, "vdot")
        garmin_row = conn.execute(
            "SELECT vo2max FROM activities WHERE vo2max IS NOT NULL ORDER BY date DESC LIMIT 1"
        ).fetchone()
        garmin_vo2 = float(garmin_row["vo2max"]) if garmin_row and garmin_row["vo2max"] else None
        if anchor and anchor.get("value") is not None:
            stale = " — STALE, suggest a fresh 5–10k/threshold test" if anchor.get("stale") else ""
            line = (f"Fitness anchor: VDOT {anchor['value']:g} "
                    f"({anchor.get('method')}, confidence {anchor.get('confidence')}){stale}")
            if garmin_vo2:
                gap = garmin_vo2 - anchor["value"]
                line += f"; Garmin VO2max {garmin_vo2:.0f} (gap {gap:+.0f} — trust the anchor)"
            if anchor.get("suggestion") and anchor["suggestion"].get("differs"):
                line += f"; pending suggestion {anchor['suggestion']['value']:g} (run `fit calibrate vdot`)"
            s.append(line)
        elif garmin_vo2:
            s.append(f"Fitness anchor: none yet; Garmin VO2max {garmin_vo2:.0f} only "
                     "(race a 5-10k at ≥LTHR to anchor VDOT)")
    except Exception:
        pass

    stale_cals = [c for c in get_calibration_status(conn) if c["stale"]]
    if stale_cals:
        s.append("Stale calibrations: " + ", ".join(f"{c['metric']} ({c['retest_prompt']})" for c in stale_cals))
    return s


def _ctx_health(conn) -> list[str]:
    """Recent health metrics, ACWR, today's activity."""
    s = []
    # Today's completed activity (so coaching knows what was already done)
    today_runs = conn.execute(f"""
        SELECT name, distance_km, duration_min, avg_hr, hr_zone, run_type, pace_sec_per_km
        FROM activities
        WHERE type IN {RUNNING_TYPES_SQL} AND date = date('now')
    """).fetchall()
    if today_runs:
        for r in today_runs:
            pace = f"{int(r['pace_sec_per_km']//60)}:{int(r['pace_sec_per_km']%60):02d}" if r["pace_sec_per_km"] else "?"
            s.append(f"TODAY's run (COMPLETED): {r['name']} — {r['distance_km']}km, {pace}/km, HR {r['avg_hr']}, {r['hr_zone']}, {r['run_type']}")
    else:
        s.append("No run today (yet)")

    # Rolling 7-day ACWR — no partial-week issues
    from fit.analysis import compute_rolling_acwr, compute_rolling_week
    acwr_safe = config.get("analysis", {}).get("acwr_safe_range", [0.8, 1.3])
    acwr_danger = config.get("analysis", {}).get("acwr_danger_threshold", 1.5)
    rolling_acwr = compute_rolling_acwr(conn)
    if rolling_acwr is not None:
        safety = "SAFE" if acwr_safe[0] <= rolling_acwr <= acwr_safe[1] else "CAUTION" if rolling_acwr <= acwr_danger else "DANGER"
        s.append(f"ACWR: {rolling_acwr:.2f} ({safety}) [rolling 7-day]")
    rolling = compute_rolling_week(conn)
    if rolling:
        s.append(f"Last 7 days: {rolling['run_km']:.0f}km / {rolling['run_count']} runs")
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
    # Monotony/strain — leading overtraining indicators
    ms_row = conn.execute("SELECT monotony, strain FROM weekly_agg WHERE monotony IS NOT NULL ORDER BY week DESC LIMIT 1").fetchone()
    if ms_row:
        m, st = ms_row["monotony"], ms_row["strain"]
        m_flag = " (HIGH — overtraining risk)" if m and m > 2.0 else ""
        s.append(f"Monotony: {m}{m_flag}, Strain: {st}")
    return s


def _ctx_training(conn) -> list[str]:
    """Zone distribution, run types, efficiency, active phase."""
    s = []
    # Average the last 4 weeks that have zone data. ISO-week strings
    # ('2026-W23') already sort chronologically, so ORDER BY week DESC LIMIT 4
    # in a subquery IS the 4-week window. Do NOT compare week strings to
    # date('now') — '2026-W..' > '2026-06-..' lexically, so that filter
    # silently anchored on 2025-W52 and averaged ~6 months, inflating the
    # Z4+Z5 share with old race/interval weeks (reported 24% vs ~0-12% actual).
    zones = conn.execute("""
        SELECT ROUND(AVG(z12_pct), 1) as avg_z12, ROUND(AVG(z45_pct), 1) as avg_z45
        FROM (
            SELECT z12_pct, z45_pct FROM weekly_agg
            WHERE z12_pct IS NOT NULL
            ORDER BY week DESC LIMIT 4
        )
    """).fetchone()
    if zones and zones["avg_z12"] is not None:
        s.append(f"Zone distribution (last 4 wks w/ data): Z1+Z2={zones['avg_z12']}%, "
                 f"Z4+Z5={zones['avg_z45']}%")
    phase = conn.execute("SELECT * FROM training_phases WHERE status = 'active' LIMIT 1").fetchone()
    if phase:
        s.append(f"Active phase: {phase['phase']} — {phase['name']} ({phase['start_date']} to {phase['end_date']})")
        if phase["z12_pct_target"]:
            s.append(f"  Phase Z1+Z2 target: {phase['z12_pct_target']}%")
    types = conn.execute(f"""
        SELECT run_type, COUNT(*) as n FROM activities
        WHERE type IN {RUNNING_TYPES_SQL} AND date >= date('now', '-28 days')
        GROUP BY run_type ORDER BY n DESC
    """).fetchall()
    if types:
        s.append("Run types (4wk): " + ", ".join(f"{r['run_type']}:{r['n']}" for r in types))
    # Aerobic efficiency: prefer the Z2-gated speed/bpm (pure-aerobic signal, matches
    # the dashboard's "Aerobic Efficiency (Z2 speed/bpm)"); fall back to all-runs
    # speed/bpm when the window has no Z2-classified runs.
    def _avg_spb(col: str, start_mod: str, end_mod: str):
        row = conn.execute(f"""
            SELECT ROUND(AVG({col}), 3) as v FROM activities
            WHERE type IN {RUNNING_TYPES_SQL} AND {col} IS NOT NULL
            AND date BETWEEN date('now', ?) AND date('now', ?)
        """, (start_mod, end_mod)).fetchone()
        return row["v"] if row else None

    col, label = "speed_per_bpm_z2", "Z2 speed/bpm"
    recent = _avg_spb(col, "-28 days", "+1 day")
    if recent is None:
        col, label = "speed_per_bpm", "speed/bpm (all runs)"
        recent = _avg_spb(col, "-28 days", "+1 day")
    if recent:
        prev = _avg_spb(col, "-56 days", "-29 days")
        trend = ""
        if prev:
            diff = recent - prev
            trend = f" (vs prev 4wk: {'↑' if diff > 0 else '↓'}{abs(diff):.3f})"
        s.append(f"{label} (4wk avg): {recent}{trend}")
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
        act = conn.execute(f"""
            SELECT a.id, a.date, a.name, a.distance_km, a.temp_at_start_c, a.humidity_at_start_pct
            FROM activities a
            WHERE a.type IN {RUNNING_TYPES_SQL} AND a.splits_status = 'done'
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
        if adherence and adherence.get("weekly_compliance_pct") is not None:
            s.append(f"Plan adherence: {adherence['weekly_compliance_pct']:.0f}% weekly compliance")
            missed = adherence.get("missed", [])
            if missed:
                s.append(f"  Missed workouts: {len(missed)}")
            if adherence.get("systematic_override"):
                s.append("  Systematic intensity override detected (easy→hard pattern)")

        # This week's plan (all upcoming workouts in next 10 days)
        upcoming = conn.execute("""
            SELECT date, workout_name, workout_type, target_distance_km
            FROM planned_workouts
            WHERE date >= date('now') AND date <= date('now', '+10 days') AND status = 'active'
            ORDER BY date, sequence_ordinal
        """).fetchall()
        if upcoming:
            s.append("Planned workouts (next 10 days):")
            for w in upcoming:
                dist = f"{w['target_distance_km']:.1f}km" if w["target_distance_km"] else ""
                s.append(f"  {w['date']} {w['workout_type']:10s} {dist:>7s}  {w['workout_name']}")
            s.append("  (Adjust recommendations based on this plan. Override intensity if needed for safety.)")

        # Readiness recommendation
        try:
            from fit.config import get_config as _get_config
            _cfg = _get_config(Path(__file__).parent.parent)
            rec = get_readiness_recommendation(conn, _cfg)
            if rec and rec.get("recommend_swap"):
                s.append(f"  READINESS WARNING: {rec['recommendation']}")
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
def _ctx_forecast(conn) -> list[str]:
    """Marathon durability-model forecast for coaching (None-safe — empty when the
    forecast extra/posterior/history is absent, so the coach simply doesn't see it).

    Keeps the coaching context in sync with the dashboard headline (CLAUDE.md contract):
    median + 90% interval + P(goal) as a fitness-SUFFICIENCY ceiling (not race-day odds),
    the unvalidated-extrapolation caveat, and the chronic-load lever.
    """
    try:
        from fit.marathon.predict import (
            forecast as run_forecast, required_chronic_for_goal, _current_c, forecast_context,
        )
    except ImportError:
        return []
    ctx = forecast_context(conn)        # shared load (posterior + efforts + prior)
    if ctx is None:
        return []
    post, ds = ctx.idata, ctx.ds

    row = conn.execute("SELECT target_time FROM goals WHERE active = 1 AND target_time IS NOT NULL "
                       "ORDER BY type DESC LIMIT 1").fetchone()
    goal_secs = None
    if row and row["target_time"]:
        p = str(row["target_time"]).split(":")
        try:
            goal_secs = int(p[0]) * 3600 + int(p[1]) * 60 + (int(p[2]) if len(p) > 2 else 0)
        except (ValueError, IndexError):
            goal_secs = None

    fc = run_forecast(conn, goal_seconds=goal_secs)  # cached shared load
    if not fc:
        return []

    def _hms(x):
        x = int(round(x)); return f"{x // 3600}:{(x % 3600) // 60:02d}:{x % 60:02d}"

    ex = fc["extrapolation"]
    s = [f"Marathon forecast (durability model, maximal effort): {_hms(fc['median'])} "
         f"[90% {_hms(fc['lo'])}–{_hms(fc['hi'])}]"]
    if goal_secs and fc.get("p_ceiling") is not None:
        s.append(f"  P(goal {_hms(goal_secs)}) = {fc['p_ceiling']:.0%} — fitness-SUFFICIENCY ceiling, "
                 f"NOT race-day odds (excludes weather/pacing/fuelling)")
    if ds.d_max < ds.goal:
        s.append(f"  UNVALIDATED: longest effort {ds.d_max:.0f} km vs {ds.goal:.0f} km goal — "
                 f"treat the interval as a floor; a 30 km+ run is what validates it")
    if goal_secs:
        req = required_chronic_for_goal(post, ds, goal_seconds=goal_secs,
                                        extrapolation_scale=ex["scale"], nu=ex["nu"])
        cur = _current_c(conn) * 10 + 50
        if req:
            s.append(f"  Lever: chronic load ≈{req['chronic_load']:.0f} for P(goal)≥80% "
                     f"(now ≈{cur:.0f}) — fitness/volume is the lever; durability is normal")
    return s


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
        sections.extend(_ctx_forecast(conn))
        sections.extend(_ctx_plan(conn))
        sections.extend(_ctx_previous_coaching())
        return "Coaching Context:\n" + "\n".join(f"  {s}" for s in sections)
    finally:
        conn.close()


def _ctx_previous_coaching() -> list[str]:
    """Summary of previous coaching notes for continuity."""
    s = []
    try:
        reports_dir = Path(config["sync"]["db_path"]).expanduser().parent / "reports"
        coaching_path = reports_dir / "coaching.json"
        if coaching_path.exists():
            data = json.loads(coaching_path.read_text())
            gen_date = data.get("report_date", data.get("generated_at", "?"))
            insights = data.get("insights", [])
            if insights:
                s.append(f"Previous coaching ({gen_date}): {len(insights)} insights")
                # Show titles + types as summary (not full body — too long)
                for i in insights[:5]:
                    s.append(f"  [{i.get('type', '?')}] {i.get('title', '?')}")
                if len(insights) > 5:
                    s.append(f"  ... and {len(insights) - 5} more")
                s.append("  (Full previous coaching available in coaching.json. Reference what you recommended last time.)")
    except Exception:
        pass
    return s


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

    # Archive previous coaching notes to history (append, never lose)
    history_path = reports_dir / "coaching_history.json"
    if coaching_path.exists():
        try:
            prev = json.loads(coaching_path.read_text())
            history = json.loads(history_path.read_text()) if history_path.exists() else []
            history.append(prev)
            history_path.write_text(json.dumps(history, indent=2))
        except Exception:
            pass  # Don't fail the save if archiving fails

    # Atomic write: temp file + rename
    tmp_path = coaching_path.with_suffix(".tmp")
    tmp_path.write_text(json.dumps(data, indent=2))
    tmp_path.rename(coaching_path)

    n = len(data.get("insights", []))
    return f"Saved {n} coaching insights to {coaching_path} (previous notes archived to coaching_history.json)"


if __name__ == "__main__":
    mcp.run()
