"""CLI entry point for the fit command."""

import logging
from pathlib import Path

import click
from rich.console import Console

from fit.logging_config import setup_logging

console = Console()
logger = logging.getLogger(__name__)

# Repo root: parent of fit/ package
REPO_ROOT = Path(__file__).parent.parent
MIGRATIONS_DIR = REPO_ROOT / "migrations"


def _conn():
    """Get a database connection with migrations applied."""
    from fit.config import get_config
    from fit.db import get_db
    return get_db(get_config(), migrations_dir=MIGRATIONS_DIR)


@click.group()
@click.version_option(version="0.1.0", prog_name="fit")
@click.option("--verbose", "-v", is_flag=True, help="Enable debug logging to console.")
def main(verbose: bool):
    """Personal fitness data platform."""
    setup_logging(verbose=verbose)


@main.command()
@click.option("--days", default=7, help="Number of days to sync.")
@click.option("--full", is_flag=True, help="Sync all available history.")
@click.option("--splits", is_flag=True, help="Download .fit files and compute per-km splits.")
def sync(days: int, full: bool, splits: bool):
    """Pull data from Garmin, enrich with weather, store in SQLite."""
    from fit.config import get_config
    from fit.db import get_db
    from fit.sync import run_sync

    config = get_config()
    conn = get_db(config, migrations_dir=MIGRATIONS_DIR)

    try:
        counts = run_sync(conn, config, days=days, full=full, download_splits=splits)
        console.print(f"\n[green]✓[/green] Synced: {counts['health']} health, {counts['activities']} activities, "
                       f"{counts['enriched']} enriched, {counts['weather']} weather, {counts['weekly_agg']} weeks")
        if counts.get("splits"):
            console.print(f"  [green]✓[/green] Processed {counts['splits']} activities for splits")
        if counts.get("srpe"):
            console.print(f"  [green]✓[/green] Computed sRPE for {counts['srpe']} activities")
        if counts.get("planned_workouts"):
            console.print(f"  [green]✓[/green] Synced {counts['planned_workouts']} planned workouts")
        for w in counts.get("warnings", []):
            console.print(f"  [yellow]⚠ {w}[/yellow]")
        console.print("[bold green]Done.[/bold green]")
    except Exception as e:
        console.print(f"[bold red]Sync failed:[/bold red] {e}")
        logger.exception("Sync failed")
        raise SystemExit(1)
    finally:
        conn.close()


@main.command("splits")
@click.option("--backfill", is_flag=True, help="Process all running activities missing splits.")
@click.option("--activity-id", default=None, help="Process a single activity by ID.")
def splits(backfill: bool, activity_id: str):
    """Download .fit files and compute per-km splits."""
    import time as _time

    from fit.config import get_config
    from fit.db import get_db

    config = get_config()
    conn = get_db(config, migrations_dir=MIGRATIONS_DIR)

    try:
        from fit import garmin
        from fit.analysis import RUNNING_TYPES_SQL
        from fit.fit_file import process_splits_for_activity

        token_dir = config["sync"]["garmin_token_dir"]
        api = garmin.connect(token_dir)
        max_downloads = config.get("sync", {}).get("max_fit_downloads", 20)

        if activity_id:
            n = process_splits_for_activity(conn, api, activity_id, config)
            console.print(f"  [green]✓[/green] {n} splits for activity {activity_id}")
        elif backfill:
            rows = conn.execute(f"""
                SELECT id FROM activities
                WHERE type IN {RUNNING_TYPES_SQL} AND (splits_status IS NULL OR splits_status = 'download_failed')
                ORDER BY date DESC LIMIT ?
            """, (max_downloads,)).fetchall()
            console.print(f"[bold]Processing {len(rows)} activities (max {max_downloads} per batch)...[/bold]")
            total = 0
            for i, row in enumerate(rows):
                n = process_splits_for_activity(conn, api, row["id"], config)
                total += n
                if n > 0:
                    console.print(f"  [green]✓[/green] {n} splits for {row['id']}")
                if i < len(rows) - 1:
                    _time.sleep(2)  # Rate control: 2s delay between downloads
            console.print(f"\n[bold green]Done.[/bold green] Processed {total} total splits across {len(rows)} activities.")
        else:
            console.print("Use --backfill to process all missing, or --activity-id for one activity.")
    except Exception as e:
        console.print(f"[bold red]Splits failed:[/bold red] {e}")
        logger.exception("Splits failed")
        raise SystemExit(1)
    finally:
        conn.close()


@main.group()
def backfill():
    """One-shot data backfills."""


@backfill.command("rpe")
@click.option("--refresh", is_flag=True,
              help="Re-fetch RPE for all running activities, even if already populated. "
                   "Default sync only refreshes the last 14 days; use this to force a full refresh.")
def backfill_rpe(refresh: bool):
    """Backfill per-activity RPE/feel/compliance from Garmin.

    Walks all running activities lacking these fields and calls
    api.get_activity(id) for each. Idempotent — re-running skips
    activities already populated unless --refresh is passed.
    """
    from rich.progress import (Progress, SpinnerColumn, TextColumn,
                               BarColumn, MofNCompleteColumn, TimeElapsedColumn)

    from fit.config import get_config
    from fit.db import get_db
    from fit import garmin
    from fit.analysis import RUNNING_TYPES_SQL

    config = get_config()
    conn = get_db(config, migrations_dir=MIGRATIONS_DIR)

    try:
        api = garmin.connect(config["sync"]["garmin_token_dir"])
        if refresh:
            rows = conn.execute(
                f"SELECT id, name FROM activities "
                f"WHERE type IN {RUNNING_TYPES_SQL} ORDER BY date DESC"
            ).fetchall()
        else:
            rows = conn.execute(
                f"SELECT id, name FROM activities "
                f"WHERE type IN {RUNNING_TYPES_SQL} "
                f"AND (rpe IS NULL OR feel IS NULL OR compliance_score IS NULL) "
                f"ORDER BY date DESC"
            ).fetchall()

        if not rows:
            console.print("[dim]Nothing to backfill — all running activities have RPE/feel/compliance populated.[/dim]")
            return

        console.print(f"[bold]Backfilling RPE for {len(rows)} activities...[/bold]")
        updated = 0
        with Progress(
            SpinnerColumn(),
            TextColumn("[bold]{task.description}"),
            BarColumn(),
            MofNCompleteColumn(),
            TimeElapsedColumn(),
        ) as progress:
            task = progress.add_task("RPE", total=len(rows))
            for r in rows:
                try:
                    g = garmin.fetch_activity_rpe(api, r["id"])
                except Exception as e:
                    logger.debug("RPE fetch failed for %s: %s", r["id"], e)
                    progress.advance(task)
                    continue
                if any(v is not None for v in g.values()):
                    if refresh:
                        conn.execute(
                            "UPDATE activities SET "
                            "rpe = COALESCE(?, rpe), "
                            "feel = COALESCE(?, feel), "
                            "compliance_score = COALESCE(?, compliance_score) "
                            "WHERE id = ?",
                            (g["rpe"], g["feel"], g["compliance_score"], r["id"]),
                        )
                    else:
                        conn.execute(
                            "UPDATE activities SET "
                            "rpe = COALESCE(rpe, ?), "
                            "feel = COALESCE(feel, ?), "
                            "compliance_score = COALESCE(compliance_score, ?) "
                            "WHERE id = ?",
                            (g["rpe"], g["feel"], g["compliance_score"], r["id"]),
                        )
                    updated += 1
                progress.advance(task)
            conn.commit()

        console.print(f"\n[bold green]Done.[/bold green] Updated {updated} of {len(rows)} activities.")

        # Recompute sRPE for activities that now have RPE
        from fit.analysis import compute_srpe
        n = compute_srpe(conn)
        if n:
            console.print(f"  [dim]sRPE computed for {n} activities[/dim]")
    finally:
        conn.close()


@main.group(invoke_without_command=True)
@click.pass_context
def checkin(ctx):
    """Daily check-in — auto-selects morning/run/evening based on time."""
    if ctx.invoked_subcommand is None:
        from fit.checkin import run_checkin

        conn = _conn()
        try:
            run_checkin(conn)
        finally:
            conn.close()


@checkin.command("morning")
@click.argument("target_date", default=None, required=False)
def checkin_morning(target_date: str | None):
    """Pre-run readiness: sleep quality, legs, energy."""
    from fit.checkin import run_morning

    conn = _conn()
    try:
        run_morning(conn, target_date=target_date)
    finally:
        conn.close()


@checkin.command("run")
@click.argument("target_date", default=None, required=False)
def checkin_run(target_date: str | None):
    """Post-run: session notes (shows today's activity). RPE comes from Garmin."""
    from fit.checkin import run_post_run

    conn = _conn()
    try:
        run_post_run(conn, target_date=target_date)
    finally:
        conn.close()


@checkin.command("evening")
@click.argument("target_date", default=None, required=False)
def checkin_evening(target_date: str | None):
    """Recovery: hydration, eating, alcohol, water, weight."""
    from fit.checkin import run_evening

    conn = _conn()
    try:
        run_evening(conn, target_date=target_date)
    finally:
        conn.close()


@checkin.command("update")
@click.argument("target_date", default=None, required=False)
def checkin_update(target_date: str | None):
    """Update an existing check-in for any date."""
    from fit.checkin import run_checkin

    conn = _conn()
    try:
        run_checkin(conn, target_date=target_date, update=True)
    finally:
        conn.close()


@checkin.command("list")
@click.option("--days", default=30, help="Number of days to show (default 30).")
def checkin_list(days: int):
    """List previous check-ins."""
    from datetime import date as date_cls

    from rich import box as rich_box
    from rich.panel import Panel
    from rich.table import Table

    conn = _conn()
    try:
        rows = conn.execute(
            "SELECT c.date, c.sleep_quality, c.energy, c.legs, "
            "c.hydration, c.eating, c.alcohol, c.alcohol_detail, "
            "c.water_liters, c.notes, "
            "a.distance_km AS run_km, a.rpe AS rpe, "
            "p.target_distance_km AS plan_km, "
            "p.workout_type AS plan_type "
            "FROM checkins c "
            "LEFT JOIN ("
            "  SELECT date, distance_km, rpe "
            "  FROM activities "
            "  WHERE type IN ('running','track_running','trail_running') "
            "  GROUP BY date ORDER BY training_load DESC"
            ") a ON a.date = c.date "
            "LEFT JOIN ("
            "  SELECT date, target_distance_km, workout_type "
            "  FROM planned_workouts "
            "  WHERE status = 'active' OR status = 'completed'"
            "  GROUP BY date ORDER BY sequence_ordinal"
            ") p ON p.date = c.date "
            "WHERE c.date >= date('now', ?) ORDER BY c.date DESC",
            (f"-{days} days",),
        ).fetchall()
        if not rows:
            console.print(f"[dim]No check-ins in the last {days} days.[/dim]")
            return

        # Color helpers
        _good = "#34d399"   # green
        _ok = "#60a5fa"     # blue
        _poor = "#f87171"   # red
        _dim = "dim"

        def _qual_color(val, good, poor):
            """Color a quality value (Good/OK/Poor style)."""
            if not val or val == "–":
                return f"[{_dim}]–[/]"
            if val in good:
                return f"[{_good}]{val}[/]"
            if val in poor:
                return f"[{_poor}]{val}[/]"
            return val

        _alc_labels = {0: None, 1: "Light", 3: "Mod", 5: "Heavy"}
        _alc_colors = {0: _dim, 1: _ok, 3: "#eab308", 5: _poor}

        today = date_cls.today().isoformat()

        t = Table(
            box=rich_box.SIMPLE_HEAD, show_edge=False,
            pad_edge=False, padding=(0, 1),
        )
        t.add_column("Date", no_wrap=True)
        t.add_column("Day", justify="right", no_wrap=True)
        t.add_column("RPE", justify="right", no_wrap=True)
        t.add_column("Sleep", no_wrap=True)
        t.add_column("Energy", no_wrap=True)
        t.add_column("Legs", no_wrap=True)
        t.add_column("Hydra", no_wrap=True)
        t.add_column("Eat", no_wrap=True)
        t.add_column("Alc", no_wrap=True)
        t.add_column("Water", justify="right", no_wrap=True)
        t.add_column("Notes", style="dim", ratio=1,
                     overflow="ellipsis", no_wrap=True)

        for r in rows:
            # Date — bold if today
            date_str = r["date"][5:]  # MM-DD
            if r["date"] == today:
                date_str = f"[bold]{date_str}[/]"

            # Day — actual run distance, or planned, or Rest
            if r["run_km"]:
                day = f"[bold]{r['run_km']:.0f}km[/]"
            elif r["plan_km"]:
                day = f"[{_dim}]({r['plan_km']:.0f}km)[/]"
            elif r["plan_type"] and r["plan_type"] == "rest":
                day = f"[{_dim}]Rest[/]"
            else:
                day = f"[{_dim}]Rest[/]"

            # RPE — colored by intensity
            if r["rpe"] is not None:
                rpe_v = r["rpe"]
                rpe_c = (
                    _poor if rpe_v >= 8
                    else "#eab308" if rpe_v >= 6
                    else _good if rpe_v <= 4
                    else _ok
                )
                rpe = f"[{rpe_c}]{rpe_v}[/]"
            else:
                rpe = f"[{_dim}]–[/]"

            # Quality fields
            sleep = _qual_color(
                r["sleep_quality"], {"Good"}, {"Poor"})
            energy = _qual_color(
                r["energy"], {"Good"}, {"Low"})
            legs = _qual_color(
                r["legs"], {"Fresh"}, {"Heavy"})
            hydra = _qual_color(
                r["hydration"], {"Good"}, {"Low"})
            eat = _qual_color(
                r["eating"], {"Good"}, {"Poor"})

            # Alcohol — categorical label with color
            alc_val = r["alcohol"] if r["alcohol"] is not None else 0
            alc_int = int(alc_val)
            alc_label = _alc_labels.get(alc_int)
            if alc_label:
                alc_c = _alc_colors.get(alc_int, _dim)
                alc = f"[{alc_c}]{alc_label}[/]"
            else:
                alc = f"[{_dim}]–[/]"

            # Water
            if r["water_liters"]:
                water = f"{r['water_liters']:.1f}L"
            else:
                water = f"[{_dim}]–[/]"

            notes = (r["notes"] or "")[:40]

            t.add_row(
                date_str, day, rpe, sleep, energy, legs,
                hydra, eat, alc, water, notes,
            )

        title = f"[bold]Check-ins[/] [dim]last {days}d[/]"
        footer = (
            f"[dim]{len(rows)} "
            f"check-in{'s' if len(rows) != 1 else ''}[/]"
        )
        console.print(Panel(
            t, title=title, subtitle=footer,
            border_style="blue", padding=(0, 1),
        ))
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
    conn = get_db(config, migrations_dir=MIGRATIONS_DIR)

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


DISTANCE_ALIASES = {
    "5k": ("5km", 5.0), "5km": ("5km", 5.0),
    "10k": ("10km", 10.0), "10km": ("10km", 10.0),
    "hm": ("Halbmarathon", 21.1), "half": ("Halbmarathon", 21.1), "halbmarathon": ("Halbmarathon", 21.1),
    "marathon": ("Marathon", 42.195), "m": ("Marathon", 42.195),
}


@main.group(invoke_without_command=True)
@click.pass_context
def races(ctx):
    """Manage race calendar."""
    if ctx.invoked_subcommand is None:
        ctx.invoke(races_list)


@races.command("list")
def races_list():
    """Show race calendar with match status."""
    conn = _conn()
    try:
        rows = conn.execute("""
            SELECT rc.id, rc.date, rc.name, rc.distance, rc.status, rc.target_time, rc.result_time,
                   rc.garmin_time, rc.activity_id, rc.organizer
            FROM race_calendar rc ORDER BY rc.date
        """).fetchall()
        from rich import box as rich_box
        from rich.panel import Panel
        from rich.table import Table

        t = Table(box=rich_box.SIMPLE_HEAD, show_edge=False, pad_edge=False, padding=(0, 1), expand=True)
        t.add_column("", width=2)  # match icon
        t.add_column("#", style="dim", justify="right", no_wrap=True)
        t.add_column("Date", no_wrap=True)
        t.add_column("Dist", no_wrap=True)
        t.add_column("Result", justify="right", no_wrap=True)
        t.add_column("Target", justify="right", no_wrap=True)
        t.add_column("Name", ratio=1, overflow="ellipsis", no_wrap=True)

        for r in rows:
            sc = {"completed": "green", "registered": "cyan", "planned": "dim", "dns": "red", "dnf": "red"}.get(r["status"], "dim")
            matched = "[green]✓[/]" if r["activity_id"] else " "
            result = r["result_time"] or r["garmin_time"] or "—"
            target = r["target_time"] or "—"
            t.add_row(matched, str(r["id"]), r["date"], r["distance"],
                      result, target, f"[{sc}]{r['name']}[/]")

        console.print(Panel(t, title=f"[bold]Races[/] [dim]{len(rows)} total[/]", border_style="blue", padding=(0, 1)))
        unmatched = [r for r in rows if r["status"] == "completed" and not r["activity_id"]]
        if unmatched:
            console.print(f"\n  [yellow]⚠ {len(unmatched)} completed race(s) without matching activity (pre-sync period)[/yellow]")
        console.print()
    finally:
        conn.close()


@races.command("add")
def races_add():
    """Add a race to the calendar interactively."""
    from rich.prompt import Prompt

    conn = _conn()
    try:
        name = Prompt.ask("  Race name")
        race_date = Prompt.ask("  Date (YYYY-MM-DD)")
        distance_input = Prompt.ask("  Distance (5k/10k/half/marathon or e.g. 5.7km)").strip().lower()

        # Resolve distance
        if distance_input in DISTANCE_ALIASES:
            distance_label, distance_km = DISTANCE_ALIASES[distance_input]
        else:
            # Try parsing as number + km
            import re
            m = re.match(r"([\d.]+)\s*km?", distance_input)
            if m:
                distance_km = float(m.group(1))
                distance_label = f"{distance_km}km"
            else:
                distance_km = None
                distance_label = distance_input

        status = Prompt.ask("  Status", choices=["registered", "planned", "completed"], default="registered")
        target_time = Prompt.ask("  Target time (H:MM:SS or M:SS, enter=skip)", default="").strip() or None
        result_time = None
        if status == "completed":
            result_time = Prompt.ask("  Official result time (H:MM:SS, enter=skip)", default="").strip() or None
        organizer = Prompt.ask("  Organizer (enter=skip)", default="").strip() or None

        conn.execute("""
            INSERT INTO race_calendar (date, name, organizer, distance, distance_km, status, target_time, result_time)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (race_date, name, organizer, distance_label, distance_km, status, target_time, result_time))
        race_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.commit()

        console.print(f"\n  [green]✓ Race added: {name} on {race_date} (id={race_id})[/green]")
        console.print("  [dim]Use 'fit races' to view calendar, 'fit sync' to match with Garmin activities[/dim]")
    finally:
        conn.close()


@races.command("update")
@click.argument("race_id", type=int)
def races_update(race_id):
    """Update a race in the calendar."""
    from rich.prompt import Prompt

    conn = _conn()
    try:
        row = conn.execute("SELECT * FROM race_calendar WHERE id = ?", (race_id,)).fetchone()
        if not row:
            console.print(f"  [red]Race {race_id} not found[/red]")
            return

        console.print(f"\n  [bold]Updating: {row['name']} ({row['date']})[/bold]")
        console.print("  [dim]Press enter to keep current value[/dim]\n")

        name = Prompt.ask(f"  Name [{row['name']}]", default=row["name"])
        race_date = Prompt.ask(f"  Date [{row['date']}]", default=row["date"])

        distance_input = Prompt.ask(f"  Distance [{row['distance']}]", default=row["distance"]).strip().lower()
        if distance_input in DISTANCE_ALIASES:
            distance_label, distance_km = DISTANCE_ALIASES[distance_input]
        elif distance_input == row["distance"].lower():
            distance_label, distance_km = row["distance"], row["distance_km"]
        else:
            import re
            m = re.match(r"([\d.]+)\s*km?", distance_input)
            if m:
                distance_km = float(m.group(1))
                distance_label = f"{distance_km}km"
            else:
                distance_km = row["distance_km"]
                distance_label = distance_input

        status = Prompt.ask(f"  Status [{row['status']}]",
                            choices=["registered", "planned", "completed", "dns", "dnf"],
                            default=row["status"])
        target_time = Prompt.ask(f"  Target time [{row['target_time'] or '—'}]",
                                 default=row["target_time"] or "").strip() or None
        result_time = Prompt.ask(f"  Result time [{row['result_time'] or '—'}]",
                                 default=row["result_time"] or "").strip() or None

        conn.execute("""
            UPDATE race_calendar SET name=?, date=?, distance=?, distance_km=?,
                status=?, target_time=?, result_time=?
            WHERE id=?
        """, (name, race_date, distance_label, distance_km, status, target_time, result_time, race_id))
        conn.commit()
        console.print(f"\n  [green]✓ Updated race {race_id}: {name}[/green]")
    finally:
        conn.close()


@races.command("delete")
@click.argument("race_id", type=int)
def races_delete(race_id):
    """Delete a race from the calendar."""
    from rich.prompt import Prompt

    conn = _conn()
    try:
        row = conn.execute("SELECT name, date, distance FROM race_calendar WHERE id = ?", (race_id,)).fetchone()
        if not row:
            console.print(f"  [red]Race {race_id} not found[/red]")
            return

        confirm = Prompt.ask(
            f"  Delete {row['name']} ({row['date']}, {row['distance']})? [y/n]",
            choices=["y", "n"], default="n"
        )
        if confirm != "y":
            console.print("  Cancelled.")
            return

        # Unlink any goals referencing this race
        conn.execute("UPDATE goals SET race_id = NULL WHERE race_id = ?", (race_id,))
        # Untag activity
        conn.execute("""
            UPDATE activities SET run_type = NULL
            WHERE id = (SELECT activity_id FROM race_calendar WHERE id = ?)
        """, (race_id,))
        conn.execute("DELETE FROM race_calendar WHERE id = ?", (race_id,))
        conn.commit()
        console.print(f"  [green]✓ Deleted race {race_id}: {row['name']}[/green]")
    finally:
        conn.close()


@main.group(invoke_without_command=True)
@click.pass_context
def target(ctx):
    """Manage target race."""
    if ctx.invoked_subcommand is None:
        ctx.invoke(target_show)


@target.command("set")
@click.argument("race_id", type=int)
def target_set(race_id):
    """Set the target race. Objectives re-derive automatically."""
    from fit.goals import set_target_race

    conn = _conn()
    try:
        race = set_target_race(conn, race_id)
        console.print(f"\n  [green]✓ Target set: {race['name']} ({race['distance']}) on {race['date']}[/green]")
        if race.get("target_time"):
            console.print(f"  Target time: {race['target_time']}")

        # Show fitness profile summary
        try:
            from fit.fitness import get_fitness_profile, inverse_vdot

            profile = get_fitness_profile(conn)
            if profile["effective_vdot"]:
                console.print("\n  [bold]Fitness Profile[/bold]")
                console.print(f"  Effective VDOT: {profile['effective_vdot']}")

                # Show required VDOT for target
                if race.get("target_time") and race.get("distance_km"):
                    def _parse_time(t):
                        p = t.split(":")
                        return int(p[0]) * 3600 + int(p[1]) * 60 + (int(p[2]) if len(p) > 2 else 0)

                    target_secs = _parse_time(race["target_time"])
                    required_vdot = inverse_vdot(target_secs, race["distance_km"])
                    if required_vdot:
                        gap = profile["effective_vdot"] - required_vdot
                        status = "[green]✓ on track[/green]" if gap >= 0 else f"[yellow]⚠ need +{abs(gap):.1f} VDOT[/yellow]"
                        console.print(f"  Required VDOT: {required_vdot} ({status})")

            for dim_name in ("aerobic", "threshold", "economy", "resilience"):
                dim = profile[dim_name]
                if dim.get("current_value"):
                    trend_icon = {"improving": "↑", "declining": "↓", "flat": "→"}.get(dim["trend"], "?")
                    console.print(f"  {dim_name.capitalize():12s}: {dim['current_value']} {dim.get('unit', '')} {trend_icon}")
                elif dim.get("message"):
                    console.print(f"  {dim_name.capitalize():12s}: [dim]{dim['message']}[/dim]")
        except Exception:
            pass

        console.print("\n  [dim]Run 'fit report' to update dashboard[/dim]")
    except ValueError as e:
        console.print(f"  [red]{e}[/red]")
    finally:
        conn.close()


@target.command("show")
def target_show():
    """Show current target race, fitness profile, and objectives."""
    from rich.panel import Panel
    from rich.table import Table

    from fit.goals import get_target_race

    conn = _conn()
    try:
        race = get_target_race(conn)
        if not race:
            console.print("  No target race set. Use 'fit target set <race_id>' to set one.")
            console.print("  [dim]Run 'fit races' to see available races.[/dim]")
            return

        from datetime import date as d
        days_left = (d.fromisoformat(race["date"]) - d.today()).days

        # Header panel
        target_time = race.get('target_time') or '—'
        header = f"[bold]{race['name']}[/bold]\n{race['distance']}  ·  {race['date']}  ·  [bold]{days_left}[/bold] days  ·  target [bold]{target_time}[/bold]"
        console.print(Panel(header, border_style="bright_blue", padding=(0, 2)))

        # Fitness profile with derived targets and achievability
        try:
            from fit.fitness import (
                compute_achievability,
                derive_objectives,
                get_fitness_profile,
            )

            profile = get_fitness_profile(conn)
            derived = derive_objectives(conn, race["id"])
            derived = compute_achievability(conn, derived, days_left)

            from rich import box as rich_box

            def _s(a):
                return {"on_track": "[green]✓[/]", "tight": "[yellow]⚠[/]", "at_risk": "[red]✗[/]"}.get(a, " ")

            def _fobj(kw):
                return next((o for o in derived if kw in o["name"].lower()), None)

            # ── Fitness Profile (VDOT + 4 dimensions, all in one panel) ──
            t = Table(box=rich_box.SIMPLE_HEAD, show_edge=False, pad_edge=False, padding=(0, 1))
            t.add_column("", style="bold", no_wrap=True)
            t.add_column("Now", justify="right")
            t.add_column("Trend", style="dim")
            t.add_column("Need", justify="right")
            t.add_column("Gap", justify="right")
            t.add_column("", width=2)

            # VDOT row (summary score)
            vdot = profile["effective_vdot"]
            vdot_obj = _fobj("vdot")
            if vdot:
                src = profile["race_vdot_date"][:7] if profile.get("race_vdot_date") else "est."
                garmin_note = f"G:{profile['garmin_vo2max']:.0f}" if profile["garmin_vo2max"] else ""
                trend_str = f"[dim]{src} {garmin_note}[/]"
                req = f"≥{vdot_obj['target_value']}" if vdot_obj else "—"
                gap = f"{vdot - vdot_obj['target_value']:+.1f}" if vdot_obj else "—"
                ach = _s(vdot_obj.get("achievability")) if vdot_obj else ""
                t.add_row("[bold]VDOT[/]", f"[bold]{vdot:.1f}[/]", trend_str, req, gap, ach)
            elif profile["garmin_vo2max"]:
                t.add_row("[bold]VDOT[/]", f"[bold]{profile['garmin_vo2max']:.1f}[/]", "[dim]Garmin est.[/]", "—", "—", "")

            t.add_row("", "", "", "", "", "")  # separator

            # 4 dimensions — each with target from _dim_ objectives
            dim_targets = {
                "aerobic": _fobj("_dim_aerobic"),
                "threshold": _fobj("_dim_threshold"),
                "economy": _fobj("_dim_economy"),
                "resilience": _fobj("_dim_resilience"),
            }

            for label, key, desc in [
                ("Aerobic", "aerobic", "VO2max"),
                ("Threshold", "threshold", "Z2 pace"),
                ("Economy", "economy", "spd/bpm"),
                ("Resilience", "resilience", "drift km"),
            ]:
                dim = profile[key]
                dim_obj = dim_targets.get(key)
                need = str(dim_obj["target_value"]) if dim_obj else "—"

                row_label = f"{label} [dim]({desc})[/]"
                if dim.get("current_value") is not None:
                    arrow = {"improving": "[green]↑[/]", "declining": "[red]↓[/]", "flat": "→"}.get(dim["trend"], "")
                    rate = f"{dim['rate_per_month']:+.2f}/mo" if dim.get("rate_per_month") else ""
                    trend_str = f"{arrow} {rate}".strip() if arrow or rate else "—"

                    current_val = dim["current_value"]
                    if dim_obj and dim_obj.get("target_value") is not None:
                        target_val = dim_obj["target_value"]
                        gap = current_val - target_val
                        ach = "[green]✓[/]" if gap >= 0 else ("[yellow]⚠[/]" if gap > -target_val * 0.1 else "[red]✗[/]")
                        t.add_row(row_label, str(current_val), trend_str, need, f"{gap:+.1f}", ach)
                    else:
                        t.add_row(row_label, str(current_val), trend_str, need, "—", "")
                else:
                    msg = dim.get("message", "no data")
                    if len(msg) > 25:
                        msg = msg[:25] + "…"
                    t.add_row(row_label, "—", f"[dim]{msg}[/]", need, "—", "")

            console.print(Panel(t, title="[bold]Fitness Profile[/]", border_style="blue", padding=(0, 1)))

            # ── Objectives ──
            ot = Table(box=rich_box.SIMPLE_HEAD, show_edge=False, pad_edge=False, padding=(0, 2))
            ot.add_column("", min_width=2)
            ot.add_column("Objective", min_width=26)
            ot.add_column("Now", justify="right", style="bold", min_width=7)
            ot.add_column("Need", justify="right", min_width=7)
            ot.add_column("Why", style="dim", min_width=8)

            for obj in derived:
                if "vdot" in obj["name"].lower() or obj["name"].startswith("_dim_"):
                    continue  # shown in fitness profile, not objectives
                cur = obj.get("current_value")
                cur_s = f"{cur}" if cur is not None else "—"
                why = {"auto_daniels": "Daniels", "auto_distance": "distance", "auto_timeline": "timeline"}.get(obj.get("derivation_source", ""), "")
                ot.add_row(_s(obj.get("achievability")), obj["name"], cur_s, str(obj["target_value"]), why)

            console.print(Panel(ot, title=f"[bold]Objectives[/] [dim]derived from {target_time}[/]",
                                border_style="blue", padding=(0, 1)))

            # ── Checkpoints ──
            from fit.fitness import derive_checkpoint_targets
            checkpoints = derive_checkpoint_targets(conn)
            if checkpoints:
                ct = Table(box=rich_box.SIMPLE_HEAD, show_edge=False, pad_edge=False, padding=(0, 2))
                ct.add_column("Days", justify="right", style="bold", min_width=5)
                ct.add_column("Race", min_width=18)
                ct.add_column("Dist", min_width=5)
                ct.add_column("Your", justify="right", min_width=8)
                ct.add_column("On-track", justify="right", min_width=8)
                ct.add_column("", min_width=18)

                for cp in checkpoints:
                    sig = cp.get("signal", "")
                    # Shorten signals
                    if "faster than needed" in sig:
                        short_sig = "[green]faster ✓[/]"
                    elif "close to" in sig:
                        short_sig = "[yellow]on pace[/]"
                    elif "slower" in sig:
                        short_sig = "[red]slower ⚠[/]"
                    else:
                        short_sig = ""
                    ct.add_row(str(cp["days"]), cp["name"], cp["distance"],
                               cp["user_target"] or "—", cp["derived_target"], short_sig)

                console.print(Panel(ct, title="[bold]Checkpoints[/] [dim]milestone races[/]",
                                    border_style="blue", padding=(0, 1)))

        except Exception as e:
            console.print(f"  [dim]Fitness profile unavailable: {e}[/dim]")

        console.print()
    finally:
        conn.close()


@target.command("clear")
def target_clear():
    """Remove the target race."""
    from fit.goals import clear_target_race

    conn = _conn()
    try:
        clear_target_race(conn)
        console.print("  [green]✓ Target race cleared[/green]")
    finally:
        conn.close()


@main.group(invoke_without_command=True)
@click.pass_context
def plan(ctx):
    """Manage training plan."""
    if ctx.invoked_subcommand is None:
        ctx.invoke(plan_show)


@plan.command("show")
@click.option("--days", default=14, help="Days of history to show (default 14).")
@click.option("--upcoming", default=7, help="Days ahead to show (default 7).")
@click.pass_context
def plan_show(ctx, days: int, upcoming: int):
    """Show planned workouts with adherence for past + upcoming."""
    from datetime import date, timedelta

    conn = _conn()
    try:
        # Update statuses for past workouts first
        from fit.plan import update_plan_statuses
        update_plan_statuses(conn)

        today = date.today()
        start = today - timedelta(days=days)
        end = today + timedelta(days=upcoming)
        rows = conn.execute("""
            SELECT pw.date, pw.workout_name, pw.workout_type,
                   pw.target_distance_km, pw.status
            FROM planned_workouts pw
            WHERE pw.date BETWEEN ? AND ?
            ORDER BY pw.date, pw.sequence_ordinal
        """, (start.isoformat(), end.isoformat())).fetchall()

        if not rows:
            console.print("  No planned workouts. Import: [bold]fit plan import <file>[/]")
            return

        # Pre-fetch actual activities for the date range
        from fit.analysis import RUNNING_TYPES_SQL as rts
        actuals = conn.execute(f"""
            SELECT date, distance_km, duration_min, avg_hr, hr_zone,
                   pace_sec_per_km, aerobic_te
            FROM activities
            WHERE date BETWEEN ? AND ? AND type IN {rts}
            ORDER BY date, training_load DESC
        """, (start.isoformat(), end.isoformat())).fetchall()
        actual_by_date = {}
        for a in actuals:
            if a["date"] not in actual_by_date:
                actual_by_date[a["date"]] = a

        # Pre-fetch RPE from checkins
        checkins = conn.execute(
            "SELECT date, rpe FROM checkins WHERE date BETWEEN ? AND ? AND rpe IS NOT NULL",
            (start.isoformat(), end.isoformat()),
        ).fetchall()
        rpe_by_date = {c["date"]: c["rpe"] for c in checkins}

        from rich import box as rich_box
        from rich.panel import Panel
        from rich.table import Table

        import re
        t = Table(box=rich_box.SIMPLE_HEAD, show_edge=False, pad_edge=False, padding=(0, 2))
        t.add_column("Date", style="dim")
        t.add_column("", width=2)  # status icon
        t.add_column("Type", style="bold")
        t.add_column("Plan", justify="right")
        t.add_column("Actual", justify="right")
        t.add_column("Zone", justify="right")
        t.add_column("TE", justify="right")
        t.add_column("Time", justify="right")
        t.add_column("RPE", justify="right")
        t.add_column("Detail", style="dim")

        # Unified zone color palette (matches dashboard design system)
        _Z1 = "#93c5fd"  # light blue
        _Z2 = "#60a5fa"  # blue
        _Z3 = "#eab308"  # yellow
        _Z4 = "#f97316"  # orange
        _Z5 = "#ef4444"  # red

        def _zone_color(zone_str):
            """Return Rich hex color for a zone string like 'Z2'."""
            return {"Z1": _Z1, "Z2": _Z2, "Z3": _Z3, "Z4": _Z4, "Z5": _Z5}.get(zone_str, "dim")

        # Workout type — distinct color per type
        type_colors = {
            "easy": _Z2, "recovery": _Z1, "long": "#34d399",
            "tempo": _Z3, "intervals": _Z4, "progression": "#c084fc",
            "rest": "dim",
        }
        # TE → zone color (Garmin scale 0-5)
        def _te_color(te):
            if te < 2.0:
                return _Z1
            if te < 3.0:
                return _Z2
            if te < 4.0:
                return _Z3
            return _Z4

        status_icons = {"completed": "[green]✓[/]", "missed": "[red]✗[/]", "active": "[dim]·[/]"}

        for r in rows:
            plan_dist = f"{r['target_distance_km']:.1f}" if r["target_distance_km"] else "—"
            wtype = r["workout_type"] or "other"
            color = type_colors.get(wtype, "dim")
            status = r["status"] or "active"
            icon = status_icons.get(status, "·")

            # Clean Runna name
            name = r["workout_name"] or ""
            m = re.search(r"-\s*(.+?)\s*\(", name)
            detail = m.group(1).strip() if m else name[:25]

            # Match actual activity
            actual = actual_by_date.get(r["date"])
            if actual and status != "active":
                act_dist = f"{actual['distance_km']:.1f}" if actual["distance_km"] else "—"
                dur = actual["duration_min"]
                time_str = f"{int(dur)}m" if dur else "—"
                rpe = rpe_by_date.get(r["date"])
                rpe_str = str(rpe) if rpe else "—"
                # Zone — colored by actual zone
                zone = actual["hr_zone"] or ""
                zone_str = f"[{_zone_color(zone)}]{zone}[/]" if zone else ""
                # Garmin Training Effect (0-5) — same zone palette
                te = actual["aerobic_te"]
                if te is not None:
                    te_str = f"[{_te_color(te)}]{te:.1f}[/]"
                else:
                    te_str = "—"
            else:
                act_dist = ""
                zone_str = ""
                te_str = ""
                time_str = ""
                rpe_str = ""

            # Highlight today
            date_str = r["date"][5:]
            if r["date"] == today.isoformat():
                date_str = f"[bold]{date_str}[/]"

            t.add_row(date_str, icon, f"[{color}]{wtype}[/]",
                      plan_dist, act_dist, zone_str, te_str, time_str,
                      rpe_str, detail)

        # Summary
        completed = sum(1 for r in rows if r["status"] == "completed")
        missed = sum(1 for r in rows if r["status"] == "missed")
        active = sum(1 for r in rows if r["status"] == "active")
        total_past = completed + missed
        pct = f" ({round(completed / total_past * 100)}%)" if total_past else ""

        title = f"[bold]Plan[/] [dim]{days}d back + {upcoming}d ahead[/]"
        footer = f"[green]✓ {completed}[/] [red]✗ {missed}[/] [dim]· {active} upcoming[/]{pct}"
        console.print(Panel(t, title=title, subtitle=footer, border_style="blue", padding=(0, 1)))
    finally:
        conn.close()


@plan.command("sync")
def plan_sync_cmd():
    """Sync planned workouts from Garmin Calendar (Runna)."""
    from fit.garmin import connect
    from fit.plan import sync_planned_workouts, update_plan_statuses

    from fit.config import get_config
    config = get_config()
    conn = _conn()
    try:
        api = connect(config["sync"]["garmin_token_dir"])
        count = sync_planned_workouts(api, conn)
        update_plan_statuses(conn)
        if count:
            console.print(f"  [green]✓ Synced {count} workouts from Garmin Calendar[/green]")
        else:
            console.print("  [dim]No new workouts found in Garmin Calendar[/dim]")
    finally:
        conn.close()


@plan.command("import")
@click.argument("file", type=click.Path(exists=True))
def plan_import(file):
    """Import planned workouts from CSV."""
    from fit.plan import import_plan_csv

    conn = _conn()
    try:
        count = import_plan_csv(conn, file)
        console.print(f"  [green]✓ Imported {count} workouts from {file}[/green]")
    finally:
        conn.close()


@plan.command("validate")
@click.argument("file", type=click.Path(exists=True))
def plan_validate(file):
    """Dry-run validate a plan CSV file."""
    from fit.plan import validate_plan_csv

    issues = validate_plan_csv(file)
    if not issues:
        console.print(f"  [green]✓ {file} is valid[/green]")
    else:
        console.print(f"  [yellow]⚠ {len(issues)} issue(s):[/yellow]")
        for issue in issues:
            console.print(f"    {issue}")


@main.command("import-health")
@click.argument("file", type=click.Path(exists=True))
def import_health(file):
    """Import body comp from Apple Health export (Export.zip or Export.xml)."""
    from fit.apple_health import import_apple_health

    conn = _conn()
    try:
        result = import_apple_health(conn, file)
        if result.get("error"):
            console.print(f"  [red]{result['error']}[/red]")
            return
        console.print(f"\n  [green]✓[/green] Imported {result['imported']} body comp records")
        if result.get("date_range"):
            lo, hi = result["date_range"]
            console.print(f"  Date range: {lo} → {hi}")
        for field, count in result.get("records", {}).items():
            if count > 0:
                console.print(f"  {field}: {count} records")
        console.print("\n  [dim]Run 'fit report' to see updated weight + body fat charts[/dim]")
    finally:
        conn.close()


@main.command()
def doctor():
    """Validate data pipeline health."""
    from fit.calibration import get_calibration_status
    from fit.data_health import check_data_sources

    conn = _conn()
    try:
        from rich import box as rich_box
        from rich.panel import Panel
        from rich.table import Table

        issues = 0
        t = Table(box=rich_box.SIMPLE_HEAD, show_edge=False, pad_edge=False, padding=(0, 1))
        t.add_column("", width=2)
        t.add_column("Check")
        t.add_column("Detail", style="dim")

        # Schema version
        versions = [r[0] for r in conn.execute("SELECT version FROM schema_version ORDER BY version").fetchall()]
        t.add_row("[green]✓[/]", "Schema", f"{len(versions)} migrations applied")

        # Tables
        tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchall()]
        expected = {"activities", "daily_health", "checkins", "body_comp", "weather", "goals",
                    "training_phases", "goal_log", "calibration", "weekly_agg", "schema_version",
                    "correlations", "alerts", "import_log", "race_calendar",
                    "activity_splits", "planned_workouts"}
        missing_tables = expected - set(tables)
        if missing_tables:
            t.add_row("[red]✗[/]", "Tables", f"missing: {missing_tables}")
            issues += 1
        else:
            t.add_row("[green]✓[/]", "Tables", f"{len(expected)} present")

        # Weekly_agg freshness
        latest_activity = conn.execute("SELECT MAX(created_at) FROM activities").fetchone()[0]
        latest_agg = conn.execute("SELECT MAX(created_at) FROM weekly_agg").fetchone()[0]
        if latest_activity and latest_agg and latest_activity > latest_agg:
            t.add_row("[yellow]⚠[/]", "Weekly agg", "may be stale — run fit recompute")
            issues += 1
        else:
            t.add_row("[green]✓[/]", "Weekly agg", "up to date")

        # Calibration
        cal = get_calibration_status(conn)
        stale = [c for c in cal if c["stale"]]
        if stale:
            t.add_row("[yellow]⚠[/]", "Calibration", f"stale: {', '.join(c['metric'] for c in stale)}")
            issues += 1
        else:
            t.add_row("[green]✓[/]", "Calibration", "all current")

        # Data sources
        sources = check_data_sources(conn)
        bad = [s for s in sources if s["status"] != "active"]
        if bad:
            t.add_row("[yellow]⚠[/]", "Data sources", f"{len(bad)} warning(s)")
            issues += 1
        else:
            t.add_row("[green]✓[/]", "Data sources", "all active")

        # Correlations
        try:
            corr_count = conn.execute("SELECT COUNT(*) FROM correlations WHERE status = 'computed'").fetchone()[0]
            t.add_row("[green]✓[/]", "Correlations", f"{corr_count} computed")
        except Exception:
            t.add_row("[dim]—[/]", "Correlations", "not yet computed")

        # Splits coverage
        try:
            total_runs = conn.execute(
                "SELECT COUNT(*) FROM activities WHERE type IN ('running','trail_running','treadmill_running')"
            ).fetchone()[0]
            with_splits = conn.execute(
                "SELECT COUNT(*) FROM activities WHERE type IN ('running','trail_running','treadmill_running') AND splits_status = 'done'"
            ).fetchone()[0]
            if total_runs == 0:
                t.add_row("[dim]—[/]", "Splits", "no running activities")
            elif with_splits == total_runs:
                t.add_row("[green]✓[/]", "Splits", f"{with_splits}/{total_runs} runs")
            elif with_splits == 0:
                t.add_row("[yellow]⚠[/]", "Splits", f"0/{total_runs} runs — run fit sync to fetch")
                issues += 1
            else:
                t.add_row("[yellow]⚠[/]", "Splits", f"{with_splits}/{total_runs} runs — run fit sync --full for backfill")
                issues += 1
        except Exception:
            t.add_row("[dim]—[/]", "Splits", "table missing")

        status_str = "[green]healthy[/]" if issues == 0 else f"[yellow]{issues} issue(s)[/]"
        console.print(Panel(t, title=f"[bold]Doctor[/] {status_str}", border_style="blue" if issues == 0 else "yellow", padding=(0, 1)))
    finally:
        conn.close()


@main.command()
def correlate():
    """Compute cross-domain correlations and display results."""
    from fit.correlations import compute_all_correlations

    conn = _conn()
    try:
        from rich import box as rich_box
        from rich.panel import Panel
        from rich.table import Table

        results = compute_all_correlations(conn)
        if not results:
            console.print("  No new correlations to compute (data unchanged).")
            return

        t = Table(box=rich_box.SIMPLE_HEAD, show_edge=False, pad_edge=False, padding=(0, 1))
        t.add_column("r", justify="right", style="bold")
        t.add_column("Pair")
        t.add_column("n", justify="right", style="dim")
        t.add_column("Confidence", style="dim")

        for r in sorted(results, key=lambda x: abs(x.get("spearman_r") or 0), reverse=True):
            sr = r.get("spearman_r") or 0
            if r["status"] == "insufficient_data":
                t.add_row("[dim]—[/]", f"[dim]{r['name']}[/]", str(r["sample_size"]), "insufficient data")
            else:
                color = "green" if abs(sr) >= 0.3 else "yellow" if abs(sr) >= 0.15 else "dim"
                t.add_row(f"[{color}]{sr:+.3f}[/]", r["name"], str(r["sample_size"]), r["confidence"])

        console.print(Panel(t, title=f"[bold]Correlations[/] [dim]{len(results)} pairs[/]", border_style="blue", padding=(0, 1)))
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
    conn = get_db(config, migrations_dir=MIGRATIONS_DIR)

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

    conn = _conn()

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
    """Quick overview — what you need to know right now."""
    from datetime import date as d

    from rich import box as rich_box
    from rich.panel import Panel
    from rich.table import Table

    conn = _conn()

    try:
        last_health = conn.execute(
            "SELECT MAX(date) FROM daily_health"
        ).fetchone()[0] or "never"
        last_activity = conn.execute(
            "SELECT MAX(date) FROM activities"
        ).fetchone()[0]
        last_sync = last_activity or last_health

        # Target race header
        from fit.goals import get_active_phase, get_target_race
        target = get_target_race(conn)
        if target:
            days_left = (d.fromisoformat(target["date"]) - d.today()).days
            tt = target.get("target_time") or ""
            header = (
                f"[bold]{target['name']}[/]\n"
                f"{target['distance']}  ·  {days_left} days"
                f"  ·  target {tt}  ·  synced {last_sync}"
            )
        else:
            header = (
                f"[bold]fit[/]  ·  synced {last_sync}\n"
                "[dim]No target race. Run: fit target set <race_id>[/]"
            )
        console.print(Panel(
            header, border_style="bright_blue", padding=(0, 2),
        ))

        # Alerts (safety first)
        try:
            from fit.alerts import get_recent_alerts
            alerts = get_recent_alerts(conn, days=3)
            seen = set()
            for a in alerts:
                if a["type"] not in seen:
                    seen.add(a["type"])
                    console.print(
                        f"  [red]⚠ {a['type'].replace('_', ' ').title()}"
                        f":[/] {a['message'][:70]}"
                    )
        except Exception:
            pass

        # ── Fitness Profile (4 dimensions) ──
        try:
            from fit.fitness import get_fitness_profile
            fp = get_fitness_profile(conn)
            ft = Table(
                box=rich_box.SIMPLE_HEAD, show_edge=False,
                pad_edge=False, padding=(0, 2),
            )
            ft.add_column("Dimension", style="bold")
            ft.add_column("Value", justify="right")
            ft.add_column("Trend", justify="right")

            dims = [
                ("Aerobic", "aerobic", "VO2max"),
                ("Threshold", "threshold", "Z2 pace"),
                ("Economy", "economy", "spd/bpm"),
                ("Resilience", "resilience", "drift km"),
            ]
            for label, key, desc in dims:
                dim = fp.get(key, {})
                val = dim.get("current_value")
                trend = dim.get("trend", "")
                rate = dim.get("rate_per_month")
                if val is not None:
                    val_s = (
                        f"{val:.4f}" if key == "economy"
                        else f"{val:.1f}"
                    )
                    trend_s = ""
                    n_pts = dim.get("data_points", 0)
                    if rate is not None:
                        sign = "+" if rate >= 0 else ""
                        color = "green" if rate >= 0 else "red"
                        rate_s = (
                            f"{sign}{rate:.4f}/mo"
                            if key == "economy"
                            else f"{sign}{rate:.1f}/mo"
                        )
                        trend_s = f"[{color}]{rate_s}[/]"
                        if n_pts < 5:
                            trend_s += f" [dim](n={n_pts})[/]"
                    elif trend and str(trend) != "None":
                        trend_s = f"[dim]{trend}[/]"
                    ft.add_row(
                        f"{label} [dim]({desc})[/]",
                        val_s, trend_s,
                    )
                else:
                    src = dim.get("source", "")
                    ft.add_row(
                        f"{label} [dim]({desc})[/]",
                        "[dim]—[/]",
                        f"[dim]{src}[/]" if src else "",
                    )

            if fp.get("effective_vdot"):
                ft.add_row(
                    "VDOT", f"{fp['effective_vdot']:.1f}", "",
                )

            # Weight (from body_comp, lower = better for running)
            wt = conn.execute(
                "SELECT weight_kg, date FROM body_comp "
                "WHERE weight_kg IS NOT NULL "
                "ORDER BY date DESC LIMIT 1"
            ).fetchone()
            wt_prev = conn.execute(
                "SELECT weight_kg, date FROM body_comp "
                "WHERE weight_kg IS NOT NULL "
                "AND date <= date('now', '-7 days') "
                "ORDER BY date DESC LIMIT 1"
            ).fetchone()
            if wt:
                wt_trend = ""
                if wt_prev:
                    delta = wt["weight_kg"] - wt_prev["weight_kg"]
                    days_gap = (
                        d.fromisoformat(wt["date"])
                        - d.fromisoformat(wt_prev["date"])
                    ).days
                    if abs(delta) < 0.1:
                        wt_trend = "[dim]→[/]"
                    else:
                        # Normalize to per-week rate
                        rate = delta / days_gap * 7 if days_gap else delta
                        sign = "+" if rate > 0 else ""
                        color = "green" if rate < 0 else "red"
                        wt_trend = (
                            f"[{color}]{sign}{rate:.1f}/wk[/]"
                        )
                ft.add_row(
                    "Weight [dim](kg)[/]",
                    f"{wt['weight_kg']:.1f}", wt_trend,
                )

            console.print(Panel(
                ft, title="[bold]Fitness Profile[/]",
                border_style="cyan", padding=(0, 1),
            ))
        except Exception:
            pass

        # ── Objectives (4 canonical slots) ──
        from datetime import timedelta
        from fit.analysis import compute_rolling_acwr, compute_rolling_week
        rolling = compute_rolling_week(conn)
        rolling_prev = compute_rolling_week(
            conn, end_date=d.today() - timedelta(days=7),
        )
        rolling_acwr = compute_rolling_acwr(conn)

        # Consistency uses last *completed* ISO week, not partial current
        today_iso = d.today().isocalendar()
        completed_week = conn.execute(
            "SELECT * FROM weekly_agg WHERE week < ? "
            "ORDER BY week DESC LIMIT 1",
            (f"{today_iso[0]}-W{today_iso[1]:02d}",),
        ).fetchone()
        prev_completed = conn.execute(
            "SELECT * FROM weekly_agg WHERE week < ? "
            "ORDER BY week DESC LIMIT 1 OFFSET 1",
            (f"{today_iso[0]}-W{today_iso[1]:02d}",),
        ).fetchone()

        ot = Table(
            box=rich_box.SIMPLE_HEAD, show_edge=False,
            pad_edge=False, padding=(0, 2),
        )
        ot.add_column("Objective", style="bold")
        ot.add_column("Current", justify="right")
        ot.add_column("WoW", justify="right")
        ot.add_column("Target", justify="right", style="dim")
        ot.add_column("Status")

        goals = conn.execute(
            "SELECT * FROM goals WHERE active = 1"
        ).fetchall()
        goal_map = {}
        for g in goals:
            name = (g["name"] or "").lower()
            if "volume" in name:
                goal_map["volume"] = dict(g)
            elif "long run" in name:
                goal_map["long_run"] = dict(g)
            elif "z2" in name:
                goal_map["z2"] = dict(g)
            elif "consistency" in name:
                goal_map["consistency"] = dict(g)

        obj_defs = [
            ("Volume", "volume", "km/wk"),
            ("Long Run", "long_run", "km"),
            ("Z2 Compliance", "z2", "%"),
            ("Consistency", "consistency", "wks"),
        ]
        for label, key, unit in obj_defs:
            goal = goal_map.get(key)
            tgt = goal["target_value"] if goal else None

            cur, prev = None, None
            if key == "volume":
                cur = round(rolling["run_km"], 1) if rolling else 0
                prev = (
                    round(rolling_prev["run_km"], 1)
                    if rolling_prev and rolling_prev.get("run_km")
                    else None
                )
            elif key == "long_run":
                cur = (
                    round(rolling["longest_run_km"], 1)
                    if rolling and rolling.get("longest_run_km")
                    else 0
                )
                prev = (
                    round(rolling_prev["longest_run_km"], 1)
                    if rolling_prev
                    and rolling_prev.get("longest_run_km")
                    else None
                )
            elif key == "z2":
                cur = (
                    round(rolling["z12_pct"], 1)
                    if rolling
                    and rolling.get("z12_pct") is not None
                    else None
                )
                prev = (
                    round(rolling_prev["z12_pct"], 1)
                    if rolling_prev
                    and rolling_prev.get("z12_pct") is not None
                    else None
                )
            elif key == "consistency":
                cur = (
                    completed_week["consecutive_weeks_3plus"]
                    if completed_week else 0
                )
                prev = (
                    prev_completed["consecutive_weeks_3plus"]
                    if prev_completed else None
                )

            cur_s = f"{cur}" if cur is not None else "—"
            tgt_s = f"{tgt} {unit}" if tgt else "no target"

            # WoW delta with arrow
            if cur is not None and prev is not None:
                delta = cur - prev
                if abs(delta) < 0.05:
                    wow_s = "[dim]→ same[/]"
                elif delta > 0:
                    wow_s = f"[green]▲ +{delta:.1f}[/]"
                else:
                    wow_s = f"[red]▼ {delta:.1f}[/]"
            else:
                wow_s = "[dim]—[/]"

            if tgt and cur is not None:
                pct = cur / tgt if tgt else 0
                if pct >= 0.9:
                    st = "[green]on track[/]"
                elif pct >= 0.7:
                    st = "[yellow]at risk[/]"
                else:
                    st = "[red]off track[/]"
            else:
                st = "[dim]—[/]"

            ot.add_row(label, f"{cur_s} {unit}", wow_s, tgt_s, st)

        console.print(Panel(
            ot, title="[bold]Objectives[/]",
            border_style="blue", padding=(0, 1),
        ))

        # ── Readiness & Load ──
        rt = Table(
            box=rich_box.SIMPLE_HEAD, show_edge=False,
            pad_edge=False, padding=(0, 2),
        )
        rt.add_column("Metric", style="bold")
        rt.add_column("Value", justify="right")
        rt.add_column("WoW", justify="right")
        rt.add_column("")

        # Current + 7d-ago health for WoW
        h = conn.execute(
            "SELECT training_readiness, resting_heart_rate, "
            "hrv_last_night, sleep_duration_hours "
            "FROM daily_health ORDER BY date DESC LIMIT 1"
        ).fetchone()
        h7 = conn.execute(
            "SELECT training_readiness, resting_heart_rate, "
            "hrv_last_night, sleep_duration_hours "
            "FROM daily_health "
            "WHERE date <= date('now', '-7 days') "
            "ORDER BY date DESC LIMIT 1"
        ).fetchone()

        def _wow(cur, prev, fmt=".0f", invert=False):
            """Format WoW delta with colored arrow.
            invert=True means lower is better (e.g. RHR).
            """
            if cur is None or prev is None:
                return "[dim]—[/]"
            delta = cur - prev
            if abs(delta) < 0.5:
                return "[dim]→[/]"
            good = delta < 0 if invert else delta > 0
            arrow = "▲" if delta > 0 else "▼"
            color = "green" if good else "red"
            sign = "+" if delta > 0 else ""
            return f"[{color}]{arrow} {sign}{delta:{fmt}}[/]"

        if h:
            r = h["training_readiness"]
            action = (
                "[green]quality session[/]" if r and r >= 75
                else "[yellow]easy day[/]" if r and r >= 50
                else "[red]rest[/]" if r else ""
            )
            rt.add_row(
                "Readiness", str(r or "—"),
                _wow(r, h7["training_readiness"] if h7 else None),
                action,
            )
            rt.add_row(
                "RHR",
                f"{h['resting_heart_rate'] or '—'} bpm",
                _wow(
                    h["resting_heart_rate"],
                    h7["resting_heart_rate"] if h7 else None,
                    invert=True,
                ),
                "",
            )
            rt.add_row(
                "HRV",
                f"{h['hrv_last_night'] or '—'} ms",
                _wow(
                    h["hrv_last_night"],
                    h7["hrv_last_night"] if h7 else None,
                    fmt=".1f",
                ),
                "",
            )
            rt.add_row(
                "Sleep",
                f"{h['sleep_duration_hours']:.1f}h"
                if h["sleep_duration_hours"] else "—",
                _wow(
                    h["sleep_duration_hours"],
                    h7["sleep_duration_hours"] if h7 else None,
                    fmt=".1f",
                ),
                "",
            )

        if rolling_acwr is not None:
            safety = (
                "[green]safe[/]" if 0.8 <= rolling_acwr <= 1.3
                else "[yellow]caution[/]" if rolling_acwr <= 1.5
                else "[red]DANGER[/]"
            )
            rt.add_row("ACWR", f"{rolling_acwr:.2f}", "", safety)
        if rolling and rolling.get("monotony"):
            m = rolling["monotony"]
            m_st = (
                "[red]high[/]" if m > 2.0
                else "[yellow]moderate[/]" if m > 1.5 else ""
            )
            rt.add_row("Monotony", f"{m:.1f}", "", m_st)

        rt.add_row(
            "Last 7 days",
            f"{rolling['run_km']}km / {rolling['run_count']} runs",
            "",
            "",
        )

        phase = get_active_phase(conn)
        if phase:
            rt.add_row("Phase", phase["name"], "", phase["phase"])

        console.print(Panel(
            rt, title="[bold]Readiness & Load[/]",
            border_style="green", padding=(0, 1),
        ))

        # Calibration (compact)
        from fit.calibration import get_calibration_status
        cal_status = get_calibration_status(conn)
        stale = [c for c in cal_status if c["stale"] or c["missing"]]
        if stale:
            for c in stale:
                icon = "[yellow]⚠[/]" if c["stale"] else "[red]✗[/]"
                console.print(
                    f"  {icon} {c['metric']}: "
                    f"{c.get('retest_prompt', 'needs update')}"
                )
        else:
            console.print("  [green]✓[/] All calibrations current")

        console.print(
            "\n  [dim]Details: fit target show · Dashboard: fit report[/]"
        )
    finally:
        conn.close()
