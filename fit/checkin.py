"""Interactive daily check-in CLI — morning / run / evening structure.

A runner's day has natural check-in moments:
  morning  — pre-run readiness: sleep quality, legs, energy
  run      — post-run: RPE + session notes (with activity context)
  evening  — recovery inputs: hydration, eating, alcohol, water

All write to the same checkins row (ON CONFLICT UPDATE), so you can do
one, two, or all three per day. `fit checkin` auto-selects based on
time of day and whether you ran today.

Alcohol Scale
─────────────
Categorical scale calibrated to ethanol dose and recovery impact for
a ~78kg runner (based on athletic recovery research):

  None     0g ethanol       —                           stored=0
  Light    ≤20g (~1 std)    1 beer (0.5L), 1 wine       stored=1
  Moderate 20–50g (2-3 std) 2-3 beers, 1L beer, 2-3     stored=3
                            wines
  Heavy    >50g (4+ std)    4+ beers, bottle wine        stored=5

Pharmacology notes:
- 0.5g/kg body weight (~39g for 78kg) is the threshold where sleep
  architecture and HRV are measurably impaired.
- Light (≤20g): ~3% HRV drop, negligible sleep impact. Train normally.
- Moderate (20–50g): 5-15% HRV drop, reduced REM. Possible to train
  but recovery is compromised — adjust intensity next day.
- Heavy (>50g): 25%+ HRV drop, deep sleep disrupted. Rest day
  recommended, skip quality sessions.

Stored values (0/1/3/5) are backward-compatible: alerts fire at ≥2
(catches moderate+heavy), correlations use numeric scale.
"""

import logging
from datetime import date, datetime, timedelta

from rich.console import Console
from rich.prompt import Prompt

from fit.analysis import RUNNING_TYPES_SQL

logger = logging.getLogger(__name__)
console = Console()


# ── Field definitions ──

CATEGORY_FIELDS = {
    "sleep_quality": {
        "prompt": "Sleep quality",
        "options": {"p": "Poor", "o": "OK", "g": "Good"},
        "keys": "[P]oor / [O]K / [G]ood",
    },
    "legs": {
        "prompt": "Legs",
        "options": {"h": "Heavy", "o": "OK", "f": "Fresh"},
        "keys": "[H]eavy / [O]K / [F]resh",
    },
    "energy": {
        "prompt": "Energy",
        "options": {"l": "Low", "n": "Normal", "g": "Good"},
        "keys": "[L]ow / [N]ormal / [G]ood",
    },
    "hydration": {
        "prompt": "Hydration",
        "options": {"l": "Low", "o": "OK", "g": "Good"},
        "keys": "[L]ow / [O]K / [G]ood",
    },
    "eating": {
        "prompt": "Eating",
        "options": {"p": "Poor", "o": "OK", "g": "Good"},
        "keys": "[P]oor / [O]K / [G]ood",
    },
}

# Alcohol: categorical scale → numeric (see module docstring for calibration)
ALCOHOL_SCALE = {
    "n": (0, "None"),
    "l": (1, "Light"),
    "m": (3, "Moderate"),
    "h": (5, "Heavy"),
}
ALCOHOL_KEYS = "[N]one / [L]ight / [M]oderate / [H]eavy"
ALCOHOL_HINT = (
    "  [dim]L=1 beer/1 wine  M=2-3 beers/1L beer  "
    "H=4+ beers/bottle wine[/dim]"
)

# Reverse: numeric → key for pre-filling
_ALCOHOL_REV = {0: "n", 1: "l", 3: "m", 5: "h"}

# Which fields belong to which check-in moment
MORNING_FIELDS = ["sleep_quality", "legs", "energy"]
EVENING_FIELDS = ["hydration", "eating"]


def _rev(options, val):
    """Reverse-lookup: value → key for category fields."""
    for k, v in options.items():
        if v == val:
            return k
    return ""


def _ask_category(field, existing):
    """Prompt for a categorical field, pre-filling from existing data."""
    meta = CATEGORY_FIELDS[field]
    cur = existing[field] if existing else None
    hint = f" [dim]({cur})[/dim]" if cur else ""
    default = _rev(meta["options"], cur) if cur else ""
    key = Prompt.ask(
        f"  {meta['prompt']}{hint} {meta['keys']}",
        default=default,
    ).strip().lower()
    return meta["options"].get(key, cur or "OK")


def _get_existing(conn, target):
    """Get existing check-in for date, or None."""
    return conn.execute(
        "SELECT * FROM checkins WHERE date = ?", (target,)
    ).fetchone()


def _get_today_activity(conn, target):
    """Get today's main running activity, or None."""
    return conn.execute(
        f"SELECT name, distance_km, avg_hr, hr_zone, aerobic_te "
        f"FROM activities WHERE date = ? AND type IN {RUNNING_TYPES_SQL} "
        f"ORDER BY training_load DESC LIMIT 1",
        (target,),
    ).fetchone()


def _save_checkin(conn, data, existing):
    """Merge data into checkins row (only update non-None fields)."""
    target = data["date"]

    if existing:
        # Merge: only overwrite fields that are explicitly set
        merged = {col: existing[col] for col in existing.keys() if col != "created_at"}
        for k, v in data.items():
            if v is not None:
                merged[k] = v
        data = merged

    conn.execute("""
        INSERT INTO checkins (date, hydration, alcohol, alcohol_detail, legs,
                              eating, water_liters, energy, rpe, sleep_quality, notes)
        VALUES (:date, :hydration, :alcohol, :alcohol_detail, :legs,
                :eating, :water_liters, :energy, :rpe, :sleep_quality, :notes)
        ON CONFLICT(date) DO UPDATE SET
            hydration = excluded.hydration, alcohol = excluded.alcohol,
            alcohol_detail = excluded.alcohol_detail, legs = excluded.legs,
            eating = excluded.eating, water_liters = excluded.water_liters,
            energy = excluded.energy, rpe = excluded.rpe,
            sleep_quality = excluded.sleep_quality, notes = excluded.notes
    """, {
        "date": target,
        "hydration": data.get("hydration"),
        "alcohol": data.get("alcohol", 0),
        "alcohol_detail": data.get("alcohol_detail"),
        "legs": data.get("legs"),
        "eating": data.get("eating"),
        "water_liters": data.get("water_liters"),
        "energy": data.get("energy"),
        "rpe": data.get("rpe"),
        "sleep_quality": data.get("sleep_quality"),
        "notes": data.get("notes"),
    })

    conn.commit()


# ── Check-in moments ──


def run_morning(conn, target_date=None):
    """Morning check-in: sleep quality, legs, energy, notes."""
    target = target_date or date.today().isoformat()
    existing = _get_existing(conn, target)

    console.print(f"\n[bold]☀ Morning — {target}[/bold]")
    if existing:
        console.print("[dim]Press enter to keep current value.[/dim]")
    console.print()

    data = {"date": target}
    for field in MORNING_FIELDS:
        data[field] = _ask_category(field, existing)

    cur_notes = existing["notes"] if existing else None
    hint = f" [dim]({cur_notes[:40]})[/dim]" if cur_notes else ""
    notes = Prompt.ask(f"  Notes{hint}", default=cur_notes or "").strip()
    data["notes"] = notes or None

    _save_checkin(conn, data, existing)
    console.print("\n[bold green]✓ Morning check-in saved[/bold green]")


def run_post_run(conn, target_date=None):
    """Post-run check-in: RPE + session notes (with activity context)."""
    target = target_date or date.today().isoformat()
    existing = _get_existing(conn, target)
    activity = _get_today_activity(conn, target)

    console.print(f"\n[bold]🏃 Post-run — {target}[/bold]")
    if existing:
        console.print("[dim]Press enter to keep current value.[/dim]")

    if activity:
        parts = [activity["name"] or "Run"]
        if activity["distance_km"]:
            parts.append(f"{activity['distance_km']:.1f}km")
        if activity["hr_zone"]:
            parts.append(activity["hr_zone"])
        if activity["aerobic_te"]:
            parts.append(f"TE {activity['aerobic_te']:.1f}")
        console.print(f"  [dim]{' · '.join(parts)}[/dim]")
    else:
        console.print(f"  [dim]No run found for {target}[/dim]")

    console.print(
        "  [dim]RPE is sourced from Garmin (post-run prompt on the watch / "
        "Connect app).[/dim]"
    )

    data = {"date": target}

    cur_notes = existing["notes"] if existing else None
    hint = f" [dim]({cur_notes[:40]})[/dim]" if cur_notes else ""
    notes = Prompt.ask(
        f"  Session notes{hint}", default=cur_notes or ""
    ).strip()
    data["notes"] = notes or cur_notes

    _save_checkin(conn, data, existing)
    console.print("\n[bold green]✓ Post-run check-in saved[/bold green]")


def run_evening(conn, target_date=None):
    """Evening check-in: hydration, eating, alcohol, water."""
    target = target_date or date.today().isoformat()
    existing = _get_existing(conn, target)

    console.print(f"\n[bold]🌙 Evening — {target}[/bold]")
    if existing:
        console.print("[dim]Press enter to keep current value.[/dim]")
    console.print()

    data = {"date": target}

    for field in EVENING_FIELDS:
        data[field] = _ask_category(field, existing)

    # Alcohol (categorical scale — see module docstring for calibration)
    cur_alc = existing["alcohol"] if existing else None
    default_key = _ALCOHOL_REV.get(cur_alc, "n") if cur_alc is not None else "n"
    cur_label = ALCOHOL_SCALE.get(default_key, (0, "None"))[1]
    hint = f" [dim]({cur_label})[/dim]" if cur_alc else ""
    console.print(ALCOHOL_HINT)
    key = Prompt.ask(
        f"  Alcohol{hint} {ALCOHOL_KEYS}",
        default=default_key,
    ).strip().lower()
    if key in ALCOHOL_SCALE:
        data["alcohol"] = ALCOHOL_SCALE[key][0]
        # Ask for optional detail (e.g., "2 beers", "1 glass wine") for later analysis
        if ALCOHOL_SCALE[key][0] > 0:
            cur_detail = existing["alcohol_detail"] if existing else None
            detail_hint = (
                f" [dim]({cur_detail})[/dim]" if cur_detail else ""
            )
            detail = Prompt.ask(
                f"  What{detail_hint}", default=cur_detail or ""
            ).strip()
            data["alcohol_detail"] = detail or ALCOHOL_SCALE[key][1]
        else:
            data["alcohol_detail"] = None
    else:
        data["alcohol"] = cur_alc or 0
        data["alcohol_detail"] = existing["alcohol_detail"] if existing else None

    # Water
    cur_water = (
        str(existing["water_liters"])
        if existing and existing["water_liters"]
        else ""
    )
    hint = f" [dim]({cur_water}L)[/dim]" if cur_water else ""
    water = Prompt.ask(
        f"  Water (liters){hint}", default=cur_water or ""
    ).strip()
    data["water_liters"] = float(water) if water else None

    _save_checkin(conn, data, existing)
    console.print("\n[bold green]✓ Evening check-in saved[/bold green]")


# ── Smart default ──


def run_checkin(conn, target_date=None, update=False):
    """Smart auto-select based on time of day, today's activity, and yesterday's gaps.

    Priority order:
    1. Yesterday's evening if missing (morning is a natural time to fill it in)
    2. Today's morning if not done
    3. Post-run if ran today and no RPE yet
    4. Evening if after 6pm and not done
    5. Next unfilled section for today
    """
    target = target_date or date.today().isoformat()
    today = date.today().isoformat()
    existing = _get_existing(conn, target)
    hour = datetime.now().hour

    # Determine what's already filled for target date
    has_morning = (
        existing
        and existing["sleep_quality"]
        and existing["legs"]
        and existing["energy"]
    )
    has_evening = (
        existing
        and existing["hydration"]
        and existing["eating"]
    )

    if update:
        # Explicit update: show the most relevant section
        if has_evening:
            run_evening(conn, target)
        else:
            run_morning(conn, target)
        return

    # Check yesterday's gaps (only when checking in for today, no explicit date).
    # RPE/run details come from Garmin per-activity, so we only gate on
    # morning + evening here — there's nothing the checkin run section can fill
    # automatically that the user hasn't already entered in Garmin.
    if target == today and not target_date:
        yesterday = (
            date.fromisoformat(today) - timedelta(days=1)
        ).isoformat()
        yd = _get_existing(conn, yesterday)

        yd_has_morning = (
            yd and yd["sleep_quality"] and yd["legs"] and yd["energy"]
        )
        yd_has_evening = yd and yd["hydration"] and yd["eating"]

        gaps = []
        if not yd_has_morning:
            gaps.append("morning")
        if not yd_has_evening:
            gaps.append("evening")

        if gaps:
            console.print(
                f"[yellow]Yesterday's check-in is incomplete "
                f"({', '.join(gaps)}).[/yellow]"
            )
            for section in gaps:
                if section == "morning":
                    run_morning(conn, yesterday)
                elif section == "evening":
                    run_evening(conn, yesterday)
            console.print()  # spacing before today's check-in
            # Continue to today's check-in

    # Smart default based on time + state.
    # The post-run section is now opt-in (notes only — RPE is sourced from
    # Garmin), so it is not auto-prompted; users invoke `fit checkin run`
    # explicitly when they want to add session notes.
    if not has_morning:
        run_morning(conn, target)
    elif hour >= 18 and not has_evening:
        run_evening(conn, target)
    elif not has_evening:
        console.print(
            f"\n[dim]Morning done for {target}. "
            f"Evening check-in opens after 6pm. "
            f"Use `fit checkin run` to add session notes.[/dim]"
        )
    else:
        console.print(
            f"\n[dim]All check-ins done for {target}. "
            f"Use morning/run/evening to update specific fields.[/dim]"
        )


def _parse_alcohol(s):
    """Parse alcohol input: '0' → (0, None), '2 beers' → (2.0, '2 beers')."""
    if not s or s == "0":
        return 0, None
    parts = s.split(None, 1)
    try:
        count = float(parts[0])
        return count, s
    except ValueError:
        return 1.0, s
