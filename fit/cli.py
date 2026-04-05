"""CLI entry point for the fit command."""

import logging
from pathlib import Path

import click
from rich.console import Console

from fit.logging_config import setup_logging

console = Console()
logger = logging.getLogger(__name__)


@click.group()
@click.version_option(version="0.1.0", prog_name="fit")
@click.option("--verbose", "-v", is_flag=True, help="Enable debug logging to console.")
def main(verbose: bool):
    """Personal fitness data platform."""
    setup_logging(verbose=verbose)


@main.command()
@click.option("--days", default=7, help="Number of days to sync.")
@click.option("--full", is_flag=True, help="Sync all available history.")
def sync(days: int, full: bool):
    """Pull data from Garmin, enrich with weather, store in SQLite."""
    from fit.config import get_config
    from fit.db import get_db
    from fit.sync import run_sync

    config = get_config()
    conn = get_db(config, migrations_dir=Path.cwd() / "migrations")

    try:
        counts = run_sync(conn, config, days=days, full=full)
        console.print(f"\n[green]✓[/green] Synced: {counts['health']} health, {counts['activities']} activities, "
                       f"{counts['enriched']} enriched, {counts['weather']} weather, {counts['weekly_agg']} weeks")
        console.print("[bold green]Done.[/bold green]")
    except Exception as e:
        console.print(f"[bold red]Sync failed:[/bold red] {e}")
        logger.exception("Sync failed")
        raise SystemExit(1)
    finally:
        conn.close()


@main.command()
def checkin():
    """Interactive daily check-in logger."""
    from fit.checkin import run_checkin
    from fit.config import get_config
    from fit.db import get_db

    config = get_config()
    conn = get_db(config, migrations_dir=Path.cwd() / "migrations")
    try:
        run_checkin(conn)
    finally:
        conn.close()


@main.command()
@click.option("--daily", is_flag=True, help="Save a daily snapshot (YYYY-MM-DD.html).")
@click.option("--weekly", is_flag=True, help="Save a weekly snapshot (YYYY-WNN.html).")
def report(daily: bool, weekly: bool):
    """Generate HTML dashboard."""
    from datetime import date

    from fit.config import get_config
    from fit.db import get_db
    from fit.report.generator import generate_dashboard

    config = get_config()
    conn = get_db(config, migrations_dir=Path.cwd() / "migrations")

    reports_dir = Path(config["sync"]["db_path"]).expanduser().parent / "reports"

    try:
        # Always generate the current dashboard
        dashboard_path = reports_dir / "dashboard.html"
        generate_dashboard(conn, dashboard_path)
        console.print(f"  [green]✓[/green] {dashboard_path}")

        if daily:
            snapshot = reports_dir / f"{date.today().isoformat()}.html"
            generate_dashboard(conn, snapshot)
            console.print(f"  [green]✓[/green] {snapshot}")

        if weekly:
            iso = date.today().isocalendar()
            snapshot = reports_dir / f"{iso.year}-W{iso.week:02d}.html"
            generate_dashboard(conn, snapshot)
            console.print(f"  [green]✓[/green] {snapshot}")

        console.print("[bold green]Done.[/bold green]")
    finally:
        conn.close()


@main.command("races")
def races():
    """Show race calendar with match status."""
    from fit.config import get_config
    from fit.db import get_db

    config = get_config()
    conn = get_db(config, migrations_dir=Path.cwd() / "migrations")
    try:
        rows = conn.execute("""
            SELECT rc.date, rc.name, rc.distance, rc.status, rc.target_time, rc.result_time,
                   rc.garmin_time, rc.activity_id, rc.organizer
            FROM race_calendar rc ORDER BY rc.date
        """).fetchall()
        console.print(f"\n[bold]Race Calendar ({len(rows)} races)[/bold]\n")
        console.print(f"  {'':1s} {'Date':10s}  {'Status':10s}  {'Distance':12s}  {'Official':>8s}  {'Garmin':>8s}  {'Target':>8s}  Name")
        console.print(f"  {'':1s} {'─'*10}  {'─'*10}  {'─'*12}  {'─'*8}  {'─'*8}  {'─'*8}  {'─'*20}")
        for r in rows:
            matched = "[green]✓[/green]" if r["activity_id"] else "[red]✗[/red]"
            status_color = {"completed": "green", "registered": "cyan", "planned": "dim", "dns": "red", "dnf": "red"}
            sc = status_color.get(r["status"], "dim")
            result = r["result_time"] or "—"
            garmin = r["garmin_time"] or "—"
            target = r["target_time"] or "—"
            console.print(f"  {matched} {r['date']}  [{sc}]{r['status']:10s}[/]  {r['distance']:12s}  {result:>8s}  {garmin:>8s}  {target:>8s}  {r['name']}")
        # Show unmatched warning
        unmatched = [r for r in rows if r["status"] == "completed" and not r["activity_id"]]
        if unmatched:
            console.print(f"\n  [yellow]⚠ {len(unmatched)} completed race(s) without matching activity (pre-sync period)[/yellow]")
        console.print()
    finally:
        conn.close()


@main.group()
def goal():
    """Manage training goals."""
    pass


@goal.command("add")
def goal_add():
    """Add a new goal interactively."""
    from rich.prompt import Prompt

    from fit.config import get_config
    from fit.db import get_db
    from fit.goals import create_goal

    config = get_config()
    conn = get_db(config, migrations_dir=Path.cwd() / "migrations")
    try:
        name = Prompt.ask("  Goal name")
        goal_type = Prompt.ask("  Type", choices=["race", "metric", "habit"])
        target_value = None
        target_unit = None
        target_time = None
        target_date = None

        if goal_type == "race":
            target_time = Prompt.ask("  Target time (e.g., 3:59:59)", default="")
            target_date = Prompt.ask("  Race date (YYYY-MM-DD)", default="")
        elif goal_type == "metric":
            target_value = float(Prompt.ask("  Target value"))
            target_unit = Prompt.ask("  Unit (e.g., ml/kg/min, kg, weeks)")
            target_date = Prompt.ask("  Target date (YYYY-MM-DD, enter=none)", default="") or None
        elif goal_type == "habit":
            target_value = float(Prompt.ask("  Target (e.g., 8 for 8 consecutive weeks)"))
            target_unit = Prompt.ask("  Unit (e.g., consecutive_weeks)")

        gid = create_goal(conn, name, goal_type, target_value=target_value, target_unit=target_unit,
                          target_time=target_time or None, target_date=target_date or None)
        console.print(f"  [green]✓ Goal created: {name} (id={gid})[/green]")
    finally:
        conn.close()


@goal.command("list")
def goal_list():
    """Show all active goals with progress."""
    from fit.config import get_config
    from fit.db import get_db

    config = get_config()
    conn = get_db(config, migrations_dir=Path.cwd() / "migrations")
    try:
        goals = conn.execute("SELECT * FROM goals WHERE active = 1 ORDER BY id").fetchall()
        if not goals:
            console.print("  No active goals.")
            return
        for g in goals:
            progress = ""
            if g["type"] == "metric" and g["target_value"]:
                # Find current value
                if "vo2" in g["name"].lower():
                    cur = conn.execute("SELECT vo2max FROM activities WHERE vo2max IS NOT NULL ORDER BY date DESC LIMIT 1").fetchone()
                    if cur:
                        pct = cur["vo2max"] / g["target_value"] * 100
                        progress = f" [{cur['vo2max']}/{g['target_value']} = {pct:.0f}%]"
                elif "weight" in g["name"].lower():
                    cur = conn.execute("SELECT weight_kg FROM body_comp ORDER BY date DESC LIMIT 1").fetchone()
                    if cur:
                        progress = f" [{cur['weight_kg']:.1f}/{g['target_value']}kg]"
            elif g["type"] == "habit" and g["target_value"]:
                streak = conn.execute("SELECT consecutive_weeks_3plus FROM weekly_agg ORDER BY week DESC LIMIT 1").fetchone()
                if streak:
                    progress = f" [{streak[0] or 0}/{int(g['target_value'])} weeks]"
            console.print(f"  {g['id']}. {g['name']} ({g['type']}) — {g['target_date'] or 'no date'}{progress}")
    finally:
        conn.close()


@goal.command("complete")
@click.argument("goal_id", type=int)
def goal_complete(goal_id: int):
    """Mark a goal as achieved."""
    from fit.config import get_config
    from fit.db import get_db
    from fit.goals import log_goal_event

    config = get_config()
    conn = get_db(config, migrations_dir=Path.cwd() / "migrations")
    try:
        conn.execute("UPDATE goals SET active = 0 WHERE id = ?", (goal_id,))
        log_goal_event(conn, goal_id, None, "goal_completed", "Goal marked as achieved")
        conn.commit()
        console.print(f"  [green]✓ Goal {goal_id} completed[/green]")
    finally:
        conn.close()


@main.command()
def doctor():
    """Validate data pipeline health."""
    from fit.calibration import get_calibration_status
    from fit.config import get_config
    from fit.data_health import check_data_sources
    from fit.db import get_db

    config = get_config()
    conn = get_db(config, migrations_dir=Path.cwd() / "migrations")
    try:
        issues = 0
        console.print("\n[bold]fit doctor[/bold]\n")

        # Schema version
        versions = [r[0] for r in conn.execute("SELECT version FROM schema_version ORDER BY version").fetchall()]
        console.print(f"  [green]✓[/green] Schema versions: {versions}")

        # Tables
        tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchall()]
        expected = {"activities", "daily_health", "checkins", "body_comp", "weather", "goals",
                    "training_phases", "goal_log", "calibration", "weekly_agg", "schema_version",
                    "correlations", "alerts", "import_log"}
        missing_tables = expected - set(tables)
        if missing_tables:
            console.print(f"  [red]✗[/red] Missing tables: {missing_tables}")
            issues += 1
        else:
            console.print(f"  [green]✓[/green] All {len(expected)} tables present")

        # Weekly_agg freshness
        latest_activity = conn.execute("SELECT MAX(created_at) FROM activities").fetchone()[0]
        latest_agg = conn.execute("SELECT MAX(created_at) FROM weekly_agg").fetchone()[0]
        if latest_activity and latest_agg and latest_activity > latest_agg:
            console.print("  [yellow]⚠[/yellow] weekly_agg may be stale — run `fit recompute`")
            issues += 1
        else:
            console.print("  [green]✓[/green] weekly_agg up to date")

        # Calibration
        cal = get_calibration_status(conn)
        stale = [c for c in cal if c["stale"]]
        if stale:
            console.print(f"  [yellow]⚠[/yellow] {len(stale)} stale calibration(s): {', '.join(c['metric'] for c in stale)}")
            issues += 1
        else:
            console.print("  [green]✓[/green] All calibrations current")

        # Data sources
        sources = check_data_sources(conn)
        bad = [s for s in sources if s["status"] != "active"]
        if bad:
            console.print(f"  [yellow]⚠[/yellow] {len(bad)} data source warning(s)")
            for s in bad:
                console.print(f"    {s['source']}: {s['status']}")
            issues += 1
        else:
            console.print("  [green]✓[/green] All data sources active")

        # Correlations
        try:
            corr_count = conn.execute("SELECT COUNT(*) FROM correlations WHERE status = 'computed'").fetchone()[0]
            console.print(f"  [green]✓[/green] {corr_count} correlations computed")
        except Exception:
            console.print("  [dim]—[/dim] Correlations table not yet created (run `fit sync`)")

        console.print(f"\n  {'[green]All healthy ✓' if issues == 0 else f'[yellow]{issues} issue(s) found'}[/]\n")
    finally:
        conn.close()


@main.command()
def correlate():
    """Compute cross-domain correlations and display results."""
    from fit.config import get_config
    from fit.correlations import compute_all_correlations
    from fit.db import get_db

    config = get_config()
    conn = get_db(config, migrations_dir=Path.cwd() / "migrations")
    try:
        results = compute_all_correlations(conn)
        if not results:
            console.print("No new correlations to compute (data unchanged).")
            return
        console.print(f"\n[bold]Correlations ({len(results)} pairs):[/bold]\n")
        for r in sorted(results, key=lambda x: abs(x.get("spearman_r") or 0), reverse=True):
            if r["status"] == "insufficient_data":
                console.print(f"  [dim]{r['name']}: insufficient data (n={r['sample_size']})[/dim]")
            else:
                sr = r.get("spearman_r") or 0
                color = "[green]" if abs(sr) >= 0.3 else "[yellow]" if abs(sr) >= 0.15 else "[dim]"
                console.print(f"  {color}r={sr:+.3f}[/] {r['name']} (n={r['sample_size']}, p={r.get('p_value', '?')}, {r['confidence']})")
        console.print()
    finally:
        conn.close()


@main.command()
@click.option("--all", "recompute_all", is_flag=True, help="Recompute all weeks, not just recent.")
def recompute(recompute_all: bool):
    """Recompute derived metrics and weekly aggregations."""
    from fit.config import get_config
    from fit.db import get_db
    from fit.sync import enrich_existing_activities

    config = get_config()
    conn = get_db(config, migrations_dir=Path.cwd() / "migrations")

    try:
        console.print("[bold]Enriching activities with missing derived fields...[/bold]")
        enriched = enrich_existing_activities(conn, config)
        console.print(f"  [green]✓[/green] Enriched {enriched} activities")

        console.print("[bold]Recomputing weekly aggregations...[/bold]")
        from fit.analysis import compute_weekly_agg
        from fit.sync import _upsert_weekly_agg

        # Get all distinct ISO weeks
        from datetime import date as d
        all_dates = conn.execute("SELECT DISTINCT date FROM activities ORDER BY date").fetchall()
        week_set = set()
        for row in all_dates:
            dt = d.fromisoformat(row[0])
            iso = dt.isocalendar()
            week_set.add(f"{iso.year}-W{iso.week:02d}")

        for week_str in sorted(week_set):
            agg = compute_weekly_agg(conn, week_str)
            _upsert_weekly_agg(conn, agg)

        conn.commit()
        console.print(f"  [green]✓[/green] Recomputed {len(week_set)} weeks")
        console.print("[bold green]Done.[/bold green]")
    finally:
        conn.close()


@main.command()
@click.argument("metric", type=click.Choice(["max_hr", "lthr"]))
def calibrate(metric: str):
    """Calibrate a physiological metric (max_hr or lthr)."""
    from datetime import date as d

    from rich.prompt import Prompt

    from fit.calibration import add_calibration
    from fit.config import get_config
    from fit.db import get_db

    config = get_config()
    conn = get_db(config, migrations_dir=Path.cwd() / "migrations")

    try:
        if metric == "max_hr":
            console.print("\n[bold]Max HR Calibration[/bold]")
            console.print("  Enter the highest HR you've observed in a recent race or hard effort.")
            value = float(Prompt.ask("  Max HR (bpm)"))
            method = Prompt.ask("  Method", choices=["race", "lab_test", "manual"], default="race")
            add_calibration(conn, "max_hr", value, method, "high", d.today())
            console.print(f"  [green]✓ Max HR calibrated: {value} bpm[/green]")

        elif metric == "lthr":
            console.print("\n[bold]LTHR Calibration (30-min Time Trial)[/bold]")
            console.print("  Protocol: warm up 15min, run 30min all-out (even pace),")
            console.print("  LTHR = average HR of the LAST 20 minutes.")
            value = float(Prompt.ask("  LTHR (avg HR of last 20 min)"))
            add_calibration(conn, "lthr", value, "time_trial", "high", d.today())
            console.print(f"  [green]✓ LTHR calibrated: {value} bpm[/green]")
    finally:
        conn.close()


@main.command()
def status():
    """Quick overview of data and goals."""
    from fit.config import get_config
    from fit.db import get_db

    config = get_config()
    conn = get_db(config, migrations_dir=Path.cwd() / "migrations")

    try:
        counts = {}
        for table in ("daily_health", "activities", "checkins", "body_comp", "weather", "goals"):
            row = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
            counts[table] = row[0]

        last_health = conn.execute("SELECT MAX(date) FROM daily_health").fetchone()[0]

        console.print(f"\n  [bold]fit[/bold] — {counts['daily_health']} health days, "
                       f"{counts['activities']} activities, {counts['checkins']} check-ins")
        console.print(f"  Last sync: {last_health or 'never'}")

        # Calibration status
        from fit.calibration import get_calibration_status
        cal_status = get_calibration_status(conn)
        console.print("  [bold]Calibration:[/bold]")
        for c in cal_status:
            icon = "[green]✓[/green]" if not c["stale"] and not c["missing"] else "[yellow]⚠[/yellow]" if c["stale"] else "[red]✗[/red]"
            val = f"{c['value']} ({c['method']}, {c['date']})" if c["value"] else "not set"
            prompt = f" — {c['retest_prompt']}" if c["retest_prompt"] else ""
            console.print(f"    {icon} {c['metric']}: {val}{prompt}")

        # Data source health
        from fit.data_health import check_data_sources
        sources = check_data_sources(conn)
        stale_or_missing = [s for s in sources if s["status"] != "active"]
        if stale_or_missing:
            console.print(f"  [bold]Data Health:[/bold] {len(stale_or_missing)} warning(s)")
            for s in stale_or_missing:
                icon = "[yellow]⚠[/yellow]" if s["status"] == "stale" else "[red]✗[/red]"
                console.print(f"    {icon} {s['source']}: {s['status']}"
                               + (f" — {s['instruction']}" if s.get("instruction") else ""))

        # Active phase
        from fit.goals import get_active_phase
        phase = get_active_phase(conn)
        if phase:
            console.print(f"  [bold]Phase:[/bold] {phase['phase']} — {phase['name']}")
            if phase.get("z12_pct_target"):
                console.print(f"    Z1+Z2 target: {phase['z12_pct_target']}%, km: {phase.get('weekly_km_min')}-{phase.get('weekly_km_max')}")

        # ACWR + streak
        acwr_row = conn.execute("SELECT acwr FROM weekly_agg WHERE acwr IS NOT NULL ORDER BY week DESC LIMIT 1").fetchone()
        streak_row = conn.execute("SELECT consecutive_weeks_3plus FROM weekly_agg ORDER BY week DESC LIMIT 1").fetchone()
        if acwr_row and acwr_row["acwr"]:
            v = acwr_row["acwr"]
            safety = "[green]safe[/green]" if 0.8 <= v <= 1.3 else "[yellow]caution[/yellow]" if v <= 1.5 else "[red]DANGER[/red]"
            console.print(f"  [bold]ACWR:[/bold] {v:.2f} ({safety})")
        if streak_row and streak_row[0]:
            console.print(f"  [bold]Streak:[/bold] {streak_row[0]} consecutive weeks with 3+ runs")

        # Active goals
        goals = conn.execute("SELECT name, type, target_date FROM goals WHERE active = 1").fetchall()
        if goals:
            console.print("  [bold]Goals:[/bold]")
            for g in goals:
                console.print(f"    {g[0]} ({g[1]}) — {g[2] or 'no date'}")

        console.print()
    finally:
        conn.close()
