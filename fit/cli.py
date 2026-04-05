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

    console.print(f"[bold]Syncing Garmin Connect...[/bold]")
    try:
        counts = run_sync(conn, config, days=days, full=full)
        console.print(f"  [green]✓[/green] {counts['health']} health days")
        console.print(f"  [green]✓[/green] {counts['activities']} activities")
        console.print(f"  [green]✓[/green] {counts['spo2']} SpO2 days")
        console.print(f"  [green]✓[/green] {counts['weather']} weather days")
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
    from datetime import date, datetime

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

        # Get all weeks with activities
        weeks = conn.execute("""
            SELECT DISTINCT strftime('%Y-W', date, 'weekday 0', '-6 days')
                || substr('0' || (strftime('%W', date, 'weekday 0', '-6 days') + 0), -2)
            FROM activities ORDER BY 1
        """).fetchall()

        # Simpler: get all distinct ISO weeks
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

        last_health = conn.execute(
            "SELECT MAX(date) FROM daily_health"
        ).fetchone()[0]

        console.print(f"\n  [bold]fit[/bold] — {counts['daily_health']} health days, "
                       f"{counts['activities']} activities, {counts['checkins']} check-ins")
        console.print(f"  Last sync: {last_health or 'never'}")

        # Active goals
        goals = conn.execute("SELECT name, type, target_date FROM goals WHERE active = 1").fetchall()
        if goals:
            console.print("  Goals:")
            for g in goals:
                console.print(f"    {g[0]} ({g[1]}) — {g[2] or 'no date'}")
        else:
            console.print("  No active goals.")

        console.print()
    finally:
        conn.close()
