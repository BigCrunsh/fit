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


def run_checkin(conn: sqlite3.Connection, target_date: str | None = None, update: bool = False) -> None:
    """Run interactive check-in and save to DB.

    Args:
        target_date: ISO date string (default: today).
        update: If True, pre-fill from existing check-in for selective editing.
    """
    target = target_date or date.today().isoformat()

    # Check for existing check-in — auto-enter update mode if one exists
    existing = conn.execute("SELECT * FROM checkins WHERE date = ?", (target,)).fetchone()
    if existing:
        update = True

    if existing:
        console.print(f"\n[bold]Update check-in — {target}[/bold]")
        console.print("[dim]Press enter to keep current value.[/dim]\n")
    else:
        console.print(f"\n[bold]Daily check-in — {target}[/bold]\n")

    data = {"date": target}

    # Reverse-lookup: value → key for category fields
    def _rev(options, val):
        for k, v in options.items():
            if v == val:
                return k
        return ""

    # Categorical fields
    for field, meta in CATEGORY_FIELDS.items():
        cur = existing[field] if existing else None
        hint = f" [dim]({cur})[/dim]" if update and cur else ""
        key = Prompt.ask(f"  {meta['prompt']}{hint} {meta['keys']}", default=_rev(meta["options"], cur) if update and cur else "").strip().lower()
        data[field] = meta["options"].get(key, cur if update and cur else "OK")

    # Water
    cur_water = str(existing["water_liters"]) if existing and existing["water_liters"] else ""
    hint = f" [dim]({cur_water})[/dim]" if update and cur_water else ""
    water = Prompt.ask(f"  Water (liters){hint}", default=cur_water if update else "").strip()
    data["water_liters"] = float(water) if water else None

    # Alcohol
    cur_alc = str(existing["alcohol"]) if existing and existing["alcohol"] else "0"
    cur_alc_detail = existing["alcohol_detail"] if existing else None
    default_alc = cur_alc_detail or cur_alc if update else "0"
    hint = f" [dim]({default_alc})[/dim]" if update and existing and existing["alcohol"] else ""
    alcohol_str = Prompt.ask(f"  Alcohol (e.g., '0', '2 beers'){hint}", default=default_alc if update else "0").strip()
    data["alcohol"], data["alcohol_detail"] = _parse_alcohol(alcohol_str)

    # Sleep quality
    sleep_opts = {"p": "Poor", "o": "OK", "g": "Good"}
    cur_sleep = existing["sleep_quality"] if existing else None
    hint = f" [dim]({cur_sleep})[/dim]" if update and cur_sleep else ""
    sleep_key = Prompt.ask(f"  Sleep quality{hint} [P]oor / [O]K / [G]ood", default=_rev(sleep_opts, cur_sleep) if update and cur_sleep else "").strip().lower()
    data["sleep_quality"] = sleep_opts.get(sleep_key, cur_sleep if update and cur_sleep else "OK")

    # RPE (show activity for context)
    activity = conn.execute(
        f"SELECT name, avg_hr, hr_zone FROM activities WHERE date = ? AND type IN {RUNNING_TYPES_SQL} ORDER BY training_load DESC LIMIT 1",
        (target,),
    ).fetchone()
    if activity:
        console.print(f"  [dim]Run: {activity['name']} (HR {activity['avg_hr']}, {activity['hr_zone']})[/dim]")
    console.print("  [dim]RPE: 1-2=rest day, 3-4=easy, 5-6=moderate, 7-8=hard, 9-10=race effort[/dim]")
    cur_rpe = str(existing["rpe"]) if existing and existing["rpe"] is not None else ""
    hint = f" [dim]({cur_rpe})[/dim]" if update and cur_rpe else ""
    rpe_str = Prompt.ask(f"  RPE 1-10{hint}", default=cur_rpe if update else "").strip()
    data["rpe"] = int(rpe_str) if rpe_str and rpe_str.isdigit() and 1 <= int(rpe_str) <= 10 else None

    # Weight (optional)
    weight_str = Prompt.ask("  Weight kg (enter=skip)", default="").strip()
    data["weight_kg"] = float(weight_str) if weight_str else None

    # Notes
    cur_notes = existing["notes"] if existing else None
    hint = f" [dim]({cur_notes[:40]}...)[/dim]" if update and cur_notes and len(cur_notes) > 40 else (f" [dim]({cur_notes})[/dim]" if update and cur_notes else "")
    data["notes"] = Prompt.ask(f"  Notes{hint}", default=cur_notes if update and cur_notes else "").strip() or None

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
        """, (target, data["weight_kg"]))

    # RPE cross-write to activities
    if data.get("rpe") and activity:
        conn.execute(f"UPDATE activities SET rpe = ? WHERE date = ? AND type IN {RUNNING_TYPES_SQL}", (data["rpe"], target))

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

    action = "Updated" if update and existing else "Saved"
    console.print(f"\n[bold green]✓ {action}: {target}[/bold green]")
    logger.info("Check-in %s for %s", action.lower(), target)


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
