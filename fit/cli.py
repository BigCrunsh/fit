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
        from fit.fit_file import process_splits_for_activity

        token_dir = config["sync"]["garmin_token_dir"]
        api = garmin.connect(token_dir)
        max_downloads = config.get("sync", {}).get("max_fit_downloads", 20)

        if activity_id:
            n = process_splits_for_activity(conn, api, activity_id, config)
            console.print(f"  [green]✓[/green] {n} splits for activity {activity_id}")
        elif backfill:
            rows = conn.execute("""
                SELECT id FROM activities
                WHERE type = 'running' AND (splits_status IS NULL OR splits_status = 'download_failed')
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


@main.command()
def checkin():
    """Interactive daily check-in logger."""
    from fit.checkin import run_checkin
    from fit.config import get_config
    from fit.db import get_db

    config = get_config()
    conn = get_db(config, migrations_dir=MIGRATIONS_DIR)
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
    from fit.config import get_config
    from fit.db import get_db

    config = get_config()
    conn = get_db(config, migrations_dir=MIGRATIONS_DIR)
    try:
        rows = conn.execute("""
            SELECT rc.id, rc.date, rc.name, rc.distance, rc.status, rc.target_time, rc.result_time,
                   rc.garmin_time, rc.activity_id, rc.organizer
            FROM race_calendar rc ORDER BY rc.date
        """).fetchall()
        console.print(f"\n[bold]Race Calendar ({len(rows)} races)[/bold]\n")
        console.print(f"  {'':1s} {'ID':>3s}  {'Date':10s}  {'Status':10s}  {'Distance':12s}  {'Official':>8s}  {'Garmin':>8s}  {'Target':>8s}  Name")
        console.print(f"  {'':1s} {'─'*3}  {'─'*10}  {'─'*10}  {'─'*12}  {'─'*8}  {'─'*8}  {'─'*8}  {'─'*20}")
        for r in rows:
            matched = "[green]✓[/green]" if r["activity_id"] else "[red]✗[/red]"
            status_color = {"completed": "green", "registered": "cyan", "planned": "dim", "dns": "red", "dnf": "red"}
            sc = status_color.get(r["status"], "dim")
            result = r["result_time"] or "—"
            garmin = r["garmin_time"] or "—"
            target = r["target_time"] or "—"
            console.print(f"  {matched} {r['id']:3d}  {r['date']}  [{sc}]{r['status']:10s}[/]  {r['distance']:12s}  {result:>8s}  {garmin:>8s}  {target:>8s}  {r['name']}")
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

    from fit.config import get_config
    from fit.db import get_db

    config = get_config()
    conn = get_db(config, migrations_dir=MIGRATIONS_DIR)
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
        organizer = Prompt.ask("  Organizer (enter=skip)", default="").strip() or None

        conn.execute("""
            INSERT INTO race_calendar (date, name, organizer, distance, distance_km, status, target_time)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (race_date, name, organizer, distance_label, distance_km, status, target_time))
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

    from fit.config import get_config
    from fit.db import get_db

    config = get_config()
    conn = get_db(config, migrations_dir=MIGRATIONS_DIR)
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

    from fit.config import get_config
    from fit.db import get_db

    config = get_config()
    conn = get_db(config, migrations_dir=MIGRATIONS_DIR)
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
    conn = get_db(config, migrations_dir=MIGRATIONS_DIR)
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
    conn = get_db(config, migrations_dir=MIGRATIONS_DIR)
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
    conn = get_db(config, migrations_dir=MIGRATIONS_DIR)
    try:
        conn.execute("UPDATE goals SET active = 0 WHERE id = ?", (goal_id,))
        log_goal_event(conn, goal_id, None, "goal_completed", "Goal marked as achieved")
        conn.commit()
        console.print(f"  [green]✓ Goal {goal_id} completed[/green]")
    finally:
        conn.close()


@main.group(invoke_without_command=True)
@click.pass_context
def plan(ctx):
    """Manage training plan."""
    if ctx.invoked_subcommand is None:
        ctx.invoke(plan_show)


@plan.command("show")
@click.pass_context
def plan_show(ctx):
    """Show next 7 days of planned workouts."""
    from datetime import date, timedelta

    from fit.config import get_config
    from fit.db import get_db

    config = get_config()
    conn = get_db(config, migrations_dir=MIGRATIONS_DIR)
    try:
        today = date.today()
        end = today + timedelta(days=7)
        rows = conn.execute("""
            SELECT date, workout_name, workout_type, target_distance_km
            FROM planned_workouts
            WHERE date BETWEEN ? AND ? AND status = 'active'
            ORDER BY date, sequence_ordinal
        """, (today.isoformat(), end.isoformat())).fetchall()

        if not rows:
            console.print("  No planned workouts for the next 7 days.")
            return
        console.print("\n[bold]Plan — next 7 days[/bold]\n")
        for r in rows:
            dist = f"{r['target_distance_km']:.1f}km" if r["target_distance_km"] else "—"
            wtype = r["workout_type"] or "other"
            color = {"easy": "blue", "long": "green", "tempo": "yellow", "intervals": "red"}.get(wtype, "dim")
            console.print(f"  {r['date']}  [{color}]{wtype:12s}[/]  {dist:>8s}  {r['workout_name'] or ''}")
        console.print()
    finally:
        conn.close()


@plan.command("import")
@click.argument("file", type=click.Path(exists=True))
def plan_import(file):
    """Import planned workouts from CSV."""
    from fit.config import get_config
    from fit.db import get_db
    from fit.plan import import_plan_csv

    config = get_config()
    conn = get_db(config, migrations_dir=MIGRATIONS_DIR)
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
    from fit.config import get_config
    from fit.db import get_db

    config = get_config()
    conn = get_db(config, migrations_dir=MIGRATIONS_DIR)
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
    from fit.config import get_config
    from fit.data_health import check_data_sources
    from fit.db import get_db

    config = get_config()
    conn = get_db(config, migrations_dir=MIGRATIONS_DIR)
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
    conn = get_db(config, migrations_dir=MIGRATIONS_DIR)
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
    from fit.config import get_config
    from fit.db import get_db

    config = get_config()
    conn = get_db(config, migrations_dir=MIGRATIONS_DIR)

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
    conn = get_db(config, migrations_dir=MIGRATIONS_DIR)

    try:
        counts = {}
        for table in ("daily_health", "activities", "checkins", "body_comp", "weather", "goals"):
            row = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
            counts[table] = row[0]

        last_health = conn.execute("SELECT MAX(date) FROM daily_health").fetchone()[0]

        console.print(f"\n  [bold]fit[/bold] — {counts['daily_health']} health days, "
                       f"{counts['activities']} activities, {counts['checkins']} check-ins")
        console.print(f"  Last sync: {last_health or 'never'}")

        # Target race countdown
        from datetime import date as d

        from fit.goals import get_active_phase, get_target_race
        target_race = get_target_race(conn)
        if target_race:
            days_left = (d.fromisoformat(target_race["date"]) - d.today()).days
            target_time = target_race.get("target_time") or ""
            console.print(f"  [bold]Target Race:[/bold] {target_race['name']} — [cyan]{days_left} days[/cyan]"
                          + (f" — target: {target_time}" if target_time else ""))

        # Active phase with position
        phase = get_active_phase(conn)
        if phase:
            total_phases = conn.execute(
                "SELECT COUNT(*) FROM training_phases WHERE goal_id = ?",
                (phase["goal_id"],)
            ).fetchone()[0]
            phase_pos = f" (of {total_phases})" if total_phases else ""
            console.print(f"  [bold]Phase:[/bold] {phase['phase']} — {phase['name']}{phase_pos}")
            if phase.get("z12_pct_target"):
                console.print(f"    Z1+Z2 target: {phase['z12_pct_target']}%, km: {phase.get('weekly_km_min')}-{phase.get('weekly_km_max')}")

        # Objective progress (active goals)
        goals = conn.execute("SELECT * FROM goals WHERE active = 1 ORDER BY id").fetchall()
        if goals:
            console.print("  [bold]Objectives:[/bold]")
            for g in goals:
                progress = ""
                if g["type"] == "metric" and g["target_value"]:
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
                console.print(f"    {g['name']} ({g['type']}) — {g['target_date'] or 'no date'}{progress}")

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

        # ACWR + streak
        acwr_row = conn.execute("SELECT acwr FROM weekly_agg WHERE acwr IS NOT NULL ORDER BY week DESC LIMIT 1").fetchone()
        streak_row = conn.execute("SELECT consecutive_weeks_3plus FROM weekly_agg ORDER BY week DESC LIMIT 1").fetchone()
        if acwr_row and acwr_row["acwr"]:
            v = acwr_row["acwr"]
            safety = "[green]safe[/green]" if 0.8 <= v <= 1.3 else "[yellow]caution[/yellow]" if v <= 1.5 else "[red]DANGER[/red]"
            console.print(f"  [bold]ACWR:[/bold] {v:.2f} ({safety})")
        if streak_row and streak_row[0]:
            console.print(f"  [bold]Streak:[/bold] {streak_row[0]} consecutive weeks with 3+ runs")

        console.print()
    finally:
        conn.close()
