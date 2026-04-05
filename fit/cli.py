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
