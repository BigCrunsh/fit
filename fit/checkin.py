"""Interactive daily check-in CLI."""

import logging
import sqlite3
from datetime import date

from rich.console import Console
from rich.prompt import Prompt

from fit.analysis import RUNNING_TYPES_SQL

logger = logging.getLogger(__name__)
console = Console()

CATEGORY_FIELDS = {
    "hydration": {"prompt": "Hydration", "options": {"l": "Low", "o": "OK", "g": "Good"}, "keys": "[L]ow / [O]K / [G]ood"},
    "legs": {"prompt": "Legs", "options": {"h": "Heavy", "o": "OK", "f": "Fresh"}, "keys": "[H]eavy / [O]K / [F]resh"},
    "eating": {"prompt": "Eating", "options": {"p": "Poor", "o": "OK", "g": "Good"}, "keys": "[P]oor / [O]K / [G]ood"},
    "energy": {"prompt": "Energy", "options": {"l": "Low", "n": "Normal", "g": "Good"}, "keys": "[L]ow / [N]ormal / [G]ood"},
}


def run_checkin(conn: sqlite3.Connection) -> None:
    """Run interactive check-in and save to DB."""
    today = date.today().isoformat()

    # Check for existing check-in
    existing = conn.execute("SELECT * FROM checkins WHERE date = ?", (today,)).fetchone()
    if existing:
        console.print(f"\n[yellow]Check-in already exists for {today}:[/yellow]")
        console.print(f"  Hydration: {existing['hydration']}, Legs: {existing['legs']}, "
                       f"Eating: {existing['eating']}, Alcohol: {existing['alcohol']}")
        overwrite = Prompt.ask("Overwrite?", choices=["y", "n"], default="n")
        if overwrite != "y":
            console.print("Keeping existing check-in.")
            return

    console.print(f"\n[bold]Daily check-in — {today}[/bold]\n")

    data = {"date": today}

    # Categorical fields
    for field, meta in CATEGORY_FIELDS.items():
        key = Prompt.ask(f"  {meta['prompt']} {meta['keys']}").strip().lower()
        data[field] = meta["options"].get(key, "OK")

    # Water
    water = Prompt.ask("  Water (liters, enter=skip)", default="").strip()
    data["water_liters"] = float(water) if water else None

    # Alcohol
    alcohol_str = Prompt.ask("  Alcohol (e.g., '0', '2 beers', enter=skip)", default="0").strip()
    data["alcohol"], data["alcohol_detail"] = _parse_alcohol(alcohol_str)

    # Sleep quality
    sleep_key = Prompt.ask("  Sleep quality [P]oor / [O]K / [G]ood", default="o").strip().lower()
    data["sleep_quality"] = {"p": "Poor", "o": "OK", "g": "Good"}.get(sleep_key, "OK")

    # RPE (show today's activity for context)
    activity_today = conn.execute(
        f"SELECT name, avg_hr, hr_zone FROM activities WHERE date = ? AND type IN {RUNNING_TYPES_SQL} ORDER BY training_load DESC LIMIT 1",
        (today,),
    ).fetchone()
    if activity_today:
        console.print(f"  [dim]Today's run: {activity_today['name']} (HR {activity_today['avg_hr']}, {activity_today['hr_zone']})[/dim]")
    console.print("  [dim]RPE: 1-2=rest day, 3-4=easy, 5-6=moderate, 7-8=hard, 9-10=race effort[/dim]")
    rpe_str = Prompt.ask("  RPE 1-10 (enter=skip)", default="").strip()
    data["rpe"] = int(rpe_str) if rpe_str and rpe_str.isdigit() and 1 <= int(rpe_str) <= 10 else None

    # Weight (optional)
    weight_str = Prompt.ask("  Weight kg (enter=skip)", default="").strip()
    data["weight_kg"] = float(weight_str) if weight_str else None

    # Notes
    data["notes"] = Prompt.ask("  Notes (enter=skip)", default="").strip() or None

    # Save check-in
    conn.execute("""
        INSERT INTO checkins (date, hydration, alcohol, alcohol_detail, legs, eating, water_liters, energy, rpe, sleep_quality, notes)
        VALUES (:date, :hydration, :alcohol, :alcohol_detail, :legs, :eating, :water_liters, :energy, :rpe, :sleep_quality, :notes)
        ON CONFLICT(date) DO UPDATE SET
            hydration = excluded.hydration, alcohol = excluded.alcohol,
            alcohol_detail = excluded.alcohol_detail, legs = excluded.legs,
            eating = excluded.eating, water_liters = excluded.water_liters,
            energy = excluded.energy, rpe = excluded.rpe,
            sleep_quality = excluded.sleep_quality, notes = excluded.notes
    """, data)

    # Weight cross-write to body_comp
    if data.get("weight_kg"):
        conn.execute("""
            INSERT INTO body_comp (date, weight_kg, source)
            VALUES (?, ?, 'checkin')
            ON CONFLICT(date) DO UPDATE SET weight_kg = excluded.weight_kg, source = 'checkin'
        """, (today, data["weight_kg"]))

    # RPE cross-write to activities
    if data.get("rpe") and activity_today:
        conn.execute(f"UPDATE activities SET rpe = ? WHERE date = ? AND type IN {RUNNING_TYPES_SQL}", (data["rpe"], today))

    conn.commit()

    # sRPE computation: if RPE was entered, compute sRPE for same-day activities
    if data.get("rpe"):
        try:
            from fit.analysis import compute_srpe
            srpe_count = compute_srpe(conn)
            if srpe_count:
                console.print(f"  [dim]sRPE computed for {srpe_count} activity(ies)[/dim]")
        except Exception as e:
            logger.debug("sRPE computation after checkin failed: %s", e)

    console.print(f"\n[bold green]✓ Saved: {today}[/bold green]")
    logger.info("Check-in saved for %s", today)


def _parse_alcohol(s: str) -> tuple[float, str | None]:
    """Parse alcohol input: '0' → (0, None), '2 beers' → (2.0, '2 beers'), 'small glass wine' → (1.0, 'small glass wine')."""
    if not s or s == "0":
        return 0, None
    # Try to extract leading number
    parts = s.split(None, 1)
    try:
        count = float(parts[0])
        return count, s
    except ValueError:
        # No leading number — text describes a drink, assume 1 serving
        return 1.0, s
