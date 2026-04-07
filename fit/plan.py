"""Training plan management: Garmin Calendar sync + CSV import + adherence tracking."""

import csv
import json
import logging
import re
from datetime import date, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

# Runna workout name pattern (German):
# "W 2 Mi. Intervalle - 1-km-Wiederholungen (7,5 km)"
# "W 5 Sa. Langer Lauf - Aerob (18 km)"
RUNNA_PATTERN = re.compile(
    r"W\s*(\d+)\s+(Mo|Di|Mi|Do|Fr|Sa|So)\.\s*"
    r"(Dauerlauf|Tempo|Intervalle|Langer Lauf|Erholung|Steigerungslauf)"
    r"(?:\s*-\s*(.+?))?\s*\((\d+[.,]?\d*)\s*km\)",
    re.IGNORECASE,
)

WORKOUT_TYPE_MAP = {
    "dauerlauf": "easy",
    "tempo": "tempo",
    "intervalle": "intervals",
    "langer lauf": "long",
    "erholung": "recovery",
    "steigerungslauf": "progression",
}


# ── Garmin Calendar Sync ──


def sync_planned_workouts(api, conn, months=2):
    """Sync planned workouts from Garmin Calendar (Runna integration).

    Best-effort: the Garmin Calendar API is undocumented and may change.
    Falls back gracefully with a warning if the API is unavailable.
    Use 'fit plan import' as a robust CSV fallback.

    Returns count of synced workouts.
    """
    try:
        today = date.today()
        count = 0

        # Determine current plan version
        row = conn.execute(
            "SELECT MAX(plan_version) FROM planned_workouts"
        ).fetchone()
        plan_version = (row[0] or 0) + 1

        for month_offset in range(months):
            target = _month_offset(today, month_offset)
            try:
                items = api.garth.connectapi(
                    f"/calendar-service/year/{target.year}"
                    f"/month/{target.month}"
                )
            except Exception as e:
                logger.debug(
                    "Calendar API call failed for %s/%s: %s",
                    target.year, target.month, e,
                )
                continue

            if not isinstance(items, list):
                items = (
                    items.get("calendarItems", [])
                    if isinstance(items, dict)
                    else []
                )

            ordinal_by_date = {}
            for item in items:
                if item.get("itemType") == "workout":
                    workout = _parse_calendar_item(item)
                    if workout:
                        d = workout.get("date", "")
                        ordinal_by_date[d] = ordinal_by_date.get(d, 0) + 1
                        workout["plan_version"] = plan_version
                        workout["sequence_ordinal"] = ordinal_by_date[d]
                        _upsert_planned_workout(conn, workout)
                        count += 1

        conn.commit()
        logger.info(
            "Synced %d planned workouts from Garmin Calendar", count
        )
        return count

    except Exception as e:
        logger.warning(
            "Garmin Calendar sync failed (best-effort): %s. "
            "Use 'fit plan import' as fallback.",
            e,
        )
        return 0


def _month_offset(d, offset):
    """Return a date in the target month (1st of month + offset months)."""
    month = d.month + offset
    year = d.year + (month - 1) // 12
    month = ((month - 1) % 12) + 1
    return date(year, month, 1)


def _parse_calendar_item(item):
    """Parse a Garmin Calendar item into a planned workout dict."""
    name = item.get("title") or item.get("itemName") or ""
    match = RUNNA_PATTERN.match(name)

    workout = {
        "date": (item.get("date") or "")[:10],
        "workout_name": name,
        "garmin_workout_id": str(
            item.get("workoutId") or item.get("id") or ""
        ),
    }

    if match:
        workout.update({
            "plan_week": int(match.group(1)),
            "plan_day": match.group(2),
            "workout_type": WORKOUT_TYPE_MAP.get(
                match.group(3).lower(), "other"
            ),
            "target_distance_km": float(
                match.group(5).replace(",", ".")
            ),
        })
    else:
        workout["workout_type"] = _guess_workout_type(name)

    return workout


def _guess_workout_type(name):
    """Guess workout type from name when Runna pattern doesn't match."""
    name_lower = name.lower()
    for keyword, wtype in [
        ("tempo", "tempo"),
        ("interval", "intervals"),
        ("long", "long"),
        ("langer lauf", "long"),
        ("easy", "easy"),
        ("recovery", "recovery"),
        ("erholung", "recovery"),
        ("dauerlauf", "easy"),
        ("steigerung", "progression"),
        ("rest", "rest"),
        ("ruhe", "rest"),
        ("kraft", "strength"),
        ("strength", "strength"),
    ]:
        if keyword in name_lower:
            return wtype
    return "other"


# ── CSV Import ──


def import_plan_csv(conn, csv_path, plan_version=None):
    """Import planned workouts from CSV. Equally robust as Garmin sync.

    Expected CSV columns (flexible headers):
        date, name/workout_name, type/workout_type, distance_km,
        zone/target_zone, week, day, structure (optional JSON)

    Returns count of imported workouts.
    """
    path = Path(csv_path)
    if not path.exists():
        raise FileNotFoundError(f"Plan CSV not found: {path}")

    if plan_version is None:
        row = conn.execute(
            "SELECT MAX(plan_version) FROM planned_workouts"
        ).fetchone()
        plan_version = (row[0] or 0) + 1

    count = 0
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for i, row in enumerate(reader):
            workout_date = row.get("date", "").strip()
            if not workout_date:
                continue

            distance_raw = row.get("distance_km", "").strip()
            target_distance = None
            if distance_raw:
                try:
                    target_distance = float(
                        distance_raw.replace(",", ".")
                    )
                except (ValueError, TypeError):
                    pass

            week_raw = row.get("week", "").strip()
            plan_week = None
            if week_raw:
                try:
                    plan_week = int(week_raw)
                except (ValueError, TypeError):
                    pass

            structure_raw = row.get("structure", "").strip()
            structure = None
            if structure_raw:
                try:
                    json.loads(structure_raw)  # validate
                    structure = structure_raw
                except (json.JSONDecodeError, ValueError):
                    pass

            workout = {
                "date": workout_date,
                "workout_name": (
                    row.get("name")
                    or row.get("workout_name", "")
                ).strip(),
                "workout_type": (
                    row.get("type")
                    or row.get("workout_type", "other")
                ).strip(),
                "target_distance_km": target_distance,
                "target_zone": (
                    row.get("zone")
                    or row.get("target_zone", "")
                ).strip() or None,
                "plan_week": plan_week,
                "plan_day": row.get("day", "").strip() or None,
                "plan_version": plan_version,
                "sequence_ordinal": i + 1,
                "structure": structure,
            }
            _upsert_planned_workout(conn, workout)
            count += 1

    conn.commit()
    logger.info(
        "Imported %d workouts from %s (version %d)",
        count, path, plan_version,
    )
    return count


def validate_plan_csv(csv_path):
    """Dry-run validation of plan CSV format. Returns list of issues.

    Checks: file exists, required headers, date formats, data types.
    """
    issues = []
    path = Path(csv_path)

    if not path.exists():
        return [f"File not found: {path}"]

    try:
        with open(path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            headers = reader.fieldnames or []

            # Check required headers
            required = {"date"}
            found = set(h.lower().strip() for h in headers)
            missing = required - found
            if missing:
                issues.append(f"Missing required column(s): {missing}")

            # Check for at least one name/type column
            if not (found & {"name", "workout_name"}):
                issues.append(
                    "Missing workout name column (expected 'name' "
                    "or 'workout_name')"
                )
            if not (found & {"type", "workout_type"}):
                issues.append(
                    "Missing workout type column (expected 'type' "
                    "or 'workout_type')"
                )

            row_count = 0
            for i, row in enumerate(reader, start=2):
                row_count += 1
                d = row.get("date", "").strip()
                if not d:
                    issues.append(f"Row {i}: empty date")
                    continue

                # Validate date format
                try:
                    date.fromisoformat(d)
                except ValueError:
                    issues.append(
                        f"Row {i}: invalid date format '{d}' "
                        "(expected YYYY-MM-DD)"
                    )

                # Validate distance if present
                dist = row.get("distance_km", "").strip()
                if dist:
                    try:
                        float(dist.replace(",", "."))
                    except (ValueError, TypeError):
                        issues.append(
                            f"Row {i}: invalid distance_km '{dist}'"
                        )

                # Validate week if present
                week = row.get("week", "").strip()
                if week:
                    try:
                        int(week)
                    except (ValueError, TypeError):
                        issues.append(
                            f"Row {i}: invalid week '{week}' "
                            "(expected integer)"
                        )

            if row_count == 0:
                issues.append("CSV file has no data rows")

    except Exception as e:
        issues.append(f"Failed to read CSV: {e}")

    return issues


# ── Upsert ──


def _upsert_planned_workout(conn, workout):
    """Insert or update a planned workout."""
    conn.execute("""
        INSERT INTO planned_workouts (
            date, workout_name, workout_type, target_distance_km,
            target_zone, structure, plan_week, plan_day,
            garmin_workout_id, plan_version, sequence_ordinal
        )
        VALUES (
            :date, :workout_name, :workout_type, :target_distance_km,
            :target_zone, :structure, :plan_week, :plan_day,
            :garmin_workout_id, :plan_version, :sequence_ordinal
        )
        ON CONFLICT(date, plan_version, sequence_ordinal) DO UPDATE SET
            workout_name = excluded.workout_name,
            workout_type = excluded.workout_type,
            target_distance_km = excluded.target_distance_km,
            target_zone = excluded.target_zone,
            structure = excluded.structure,
            garmin_workout_id = excluded.garmin_workout_id
    """, {
        "date": workout.get("date"),
        "workout_name": workout.get("workout_name"),
        "workout_type": workout.get("workout_type"),
        "target_distance_km": workout.get("target_distance_km"),
        "target_zone": workout.get("target_zone"),
        "structure": (
            json.dumps(workout["structure"])
            if isinstance(workout.get("structure"), (list, dict))
            else workout.get("structure")
        ),
        "plan_week": workout.get("plan_week"),
        "plan_day": workout.get("plan_day"),
        "garmin_workout_id": workout.get("garmin_workout_id"),
        "plan_version": workout.get("plan_version", 1),
        "sequence_ordinal": workout.get("sequence_ordinal", 1),
    })


# ── Plan Adherence ──


def compute_plan_adherence(conn, week_str=None):
    """Compute per-run deltas and weekly compliance.

    Args:
        conn: Database connection.
        week_str: ISO week string (e.g., "2026-W14"). Defaults to current week.

    Returns dict with:
        planned: list of planned workouts for the week
        actuals: list of actual activities matched by date
        matches: list of {planned, actual, distance_delta, type_match}
        missed: planned workouts with no matching activity
        unplanned: activities with no planned workout
        weekly_compliance_pct: matched / total_planned * 100
        rest_compliance: whether rest days were respected
        systematic_override: True if >60% easy runs at Z3+ over 3 weeks
    """
    if week_str is None:
        today = date.today()
        iso = today.isocalendar()
        week_str = f"{iso.year}-W{iso.week:02d}"

    # Parse ISO week to date range
    week_start = _iso_week_to_monday(week_str)
    week_end = week_start + timedelta(days=6)

    # Get latest active plan version
    version_row = conn.execute("""
        SELECT plan_version FROM planned_workouts
        WHERE status = 'active'
        ORDER BY plan_version DESC LIMIT 1
    """).fetchone()

    if not version_row:
        return {
            "week": week_str,
            "planned": [],
            "actuals": [],
            "matches": [],
            "missed": [],
            "unplanned": [],
            "weekly_compliance_pct": None,
            "rest_compliance": None,
            "systematic_override": False,
        }

    plan_version = version_row[0]

    # Get planned workouts for the week
    planned = conn.execute("""
        SELECT * FROM planned_workouts
        WHERE date BETWEEN ? AND ?
          AND plan_version = ?
          AND status = 'active'
        ORDER BY date, sequence_ordinal
    """, (week_start.isoformat(), week_end.isoformat(), plan_version)
    ).fetchall()
    planned = [dict(r) for r in planned]

    # Get actual running activities for the week
    actuals = conn.execute("""
        SELECT id, date, type, distance_km, duration_min, avg_hr,
               hr_zone, effort_class, run_type, pace_sec_per_km
        FROM activities
        WHERE date BETWEEN ? AND ?
          AND type IN ('running', 'track_running', 'trail_running')
        ORDER BY date
    """, (week_start.isoformat(), week_end.isoformat())).fetchall()
    actuals = [dict(r) for r in actuals]

    # Match planned to actual by date
    matches = []
    matched_planned_ids = set()
    matched_actual_ids = set()

    for p in planned:
        if p["workout_type"] == "rest":
            # Rest day: check if there's NO activity
            has_activity = any(a["date"] == p["date"] for a in actuals)
            matches.append({
                "planned": p,
                "actual": None,
                "type_match": not has_activity,
                "rest_day": True,
                "rest_respected": not has_activity,
            })
            matched_planned_ids.add(p["id"])
            continue

        # Find best matching activity on the same date
        candidates = [
            a for a in actuals
            if a["date"] == p["date"] and a["id"] not in matched_actual_ids
        ]

        if candidates:
            # Pick the one closest in distance
            best = min(
                candidates,
                key=lambda a: abs(
                    (a["distance_km"] or 0)
                    - (p["target_distance_km"] or 0)
                ),
            )
            distance_delta = None
            if p["target_distance_km"] and best["distance_km"]:
                distance_delta = round(
                    best["distance_km"] - p["target_distance_km"], 2
                )

            matches.append({
                "planned": p,
                "actual": best,
                "distance_delta": distance_delta,
                "type_match": _types_compatible(
                    p["workout_type"], best.get("effort_class")
                ),
                "rest_day": False,
            })
            matched_planned_ids.add(p["id"])
            matched_actual_ids.add(best["id"])
        else:
            matches.append({
                "planned": p,
                "actual": None,
                "distance_delta": None,
                "type_match": False,
                "rest_day": False,
            })
            matched_planned_ids.add(p["id"])

    missed = [
        m for m in matches
        if m["actual"] is None and not m.get("rest_day")
    ]
    unplanned = [
        a for a in actuals if a["id"] not in matched_actual_ids
    ]

    # Weekly compliance: matched runs / total non-rest planned
    non_rest_planned = [
        p for p in planned if p["workout_type"] != "rest"
    ]
    matched_count = sum(
        1 for m in matches
        if m["actual"] is not None and not m.get("rest_day")
    )
    compliance = (
        round(matched_count / len(non_rest_planned) * 100)
        if non_rest_planned
        else None
    )

    # Rest day compliance
    rest_matches = [m for m in matches if m.get("rest_day")]
    rest_compliance = (
        all(m.get("rest_respected") for m in rest_matches)
        if rest_matches
        else None
    )

    # Systematic override detection (3-week lookback)
    override = _detect_systematic_override(conn, week_start)

    return {
        "week": week_str,
        "planned": planned,
        "actuals": actuals,
        "matches": matches,
        "missed": missed,
        "unplanned": unplanned,
        "weekly_compliance_pct": compliance,
        "rest_compliance": rest_compliance,
        "systematic_override": override,
    }


def _types_compatible(planned_type, effort_class):
    """Check if actual effort class is compatible with planned type."""
    if not effort_class:
        return True  # no data to judge

    compat = {
        "easy": ("Recovery", "Easy"),
        "recovery": ("Recovery", "Easy"),
        "long": ("Easy", "Moderate"),
        "tempo": ("Moderate", "Hard"),
        "intervals": ("Hard", "Very Hard"),
        "progression": ("Moderate", "Hard"),
    }
    allowed = compat.get(planned_type, ())
    return effort_class in allowed


def _detect_systematic_override(conn, week_start):
    """Detect if >60% of easy/recovery runs are at Z3+ over 3 weeks.

    This indicates the athlete is systematically running too hard on easy
    days -- a common training error.
    """
    lookback_start = week_start - timedelta(weeks=3)

    # Get planned easy/recovery workouts in the lookback
    easy_planned = conn.execute("""
        SELECT pw.date FROM planned_workouts pw
        WHERE pw.date BETWEEN ? AND ?
          AND pw.workout_type IN ('easy', 'recovery')
          AND pw.status = 'active'
    """, (lookback_start.isoformat(), week_start.isoformat())).fetchall()

    if len(easy_planned) < 3:
        return False

    easy_dates = [r["date"] for r in easy_planned]

    # Check how many of those days had Z3+ runs
    z3_plus_count = 0
    for d in easy_dates:
        activity = conn.execute("""
            SELECT hr_zone FROM activities
            WHERE date = ? AND type IN ('running', 'track_running', 'trail_running') AND hr_zone IS NOT NULL
            ORDER BY duration_min DESC LIMIT 1
        """, (d,)).fetchone()
        if activity and activity["hr_zone"]:
            zone_num = _zone_to_number(activity["hr_zone"])
            if zone_num >= 3:
                z3_plus_count += 1

    ratio = z3_plus_count / len(easy_dates) if easy_dates else 0
    return ratio > 0.6


def _zone_to_number(zone_str):
    """Convert zone string like 'Z3' or 'z3' to integer 3."""
    if not zone_str:
        return 0
    try:
        return int(zone_str.upper().replace("Z", ""))
    except (ValueError, TypeError):
        return 0


def _iso_week_to_monday(week_str):
    """Convert ISO week string to the Monday date of that week."""
    parts = week_str.split("-W")
    year = int(parts[0])
    week = int(parts[1])
    # ISO week 1 contains Jan 4
    jan4 = date(year, 1, 4)
    # Monday of week 1
    week1_monday = jan4 - timedelta(days=jan4.weekday())
    return week1_monday + timedelta(weeks=week - 1)


# ── Readiness Gate ──


def get_readiness_recommendation(conn, config):
    """Check if today's planned workout should be swapped based on readiness.

    Returns dict with:
        planned: today's planned workout (or None)
        readiness: latest readiness score
        threshold: adaptive threshold
        recommend_swap: bool
        recommendation: human-readable suggestion
    """
    today = date.today()

    # Get today's planned workout
    planned = conn.execute("""
        SELECT * FROM planned_workouts
        WHERE date = ? AND status = 'active'
        ORDER BY sequence_ordinal LIMIT 1
    """, (today.isoformat(),)).fetchone()

    if not planned:
        return {
            "planned": None,
            "readiness": None,
            "threshold": None,
            "recommend_swap": False,
            "recommendation": "No planned workout today.",
        }

    planned = dict(planned)

    # Get latest readiness
    readiness_row = conn.execute("""
        SELECT training_readiness FROM daily_health
        WHERE date = ? AND training_readiness IS NOT NULL
    """, (today.isoformat(),)).fetchone()

    if not readiness_row:
        # Try yesterday
        readiness_row = conn.execute("""
            SELECT training_readiness FROM daily_health
            WHERE training_readiness IS NOT NULL
            ORDER BY date DESC LIMIT 1
        """).fetchone()

    readiness = readiness_row["training_readiness"] if readiness_row else None

    # Adaptive threshold: default 40, raised to 50 during return-to-run
    base_threshold = config.get("coaching", {}).get(
        "readiness_gate_threshold", 40
    )
    threshold = base_threshold

    # Check for return-to-run (gap >= 14 days in last 30 days)
    gap_check = conn.execute("""
        SELECT MAX(date) as last_run FROM activities
        WHERE type IN ('running', 'track_running', 'trail_running')
          AND date < date('now', '-14 days')
          AND date >= date('now', '-60 days')
    """).fetchone()
    recent_run = conn.execute("""
        SELECT MIN(date) as first_recent FROM activities
        WHERE type IN ('running', 'track_running', 'trail_running') AND date >= date('now', '-14 days')
    """).fetchone()

    if gap_check and gap_check["last_run"] and recent_run and recent_run["first_recent"]:
        gap_days = (
            date.fromisoformat(recent_run["first_recent"])
            - date.fromisoformat(gap_check["last_run"])
        ).days
        if gap_days >= 14:
            threshold = max(threshold, 50)

    if readiness is None:
        return {
            "planned": planned,
            "readiness": None,
            "threshold": threshold,
            "recommend_swap": False,
            "recommendation": (
                "No readiness data available. Proceed as planned, "
                "but listen to your body."
            ),
        }

    # Only recommend swap for quality sessions
    quality_types = {"tempo", "intervals", "long", "progression"}
    is_quality = planned["workout_type"] in quality_types

    recommend_swap = is_quality and readiness < threshold

    if recommend_swap:
        recommendation = (
            f"Readiness is {readiness} (threshold: {threshold}). "
            f"Planned: {planned['workout_type']}. "
            f"Consider swapping to an easy run or rest day."
        )
    elif readiness < threshold and not is_quality:
        recommendation = (
            f"Readiness is low ({readiness}) but today is "
            f"{planned['workout_type']} -- proceed at gentle pace."
        )
    else:
        recommendation = (
            f"Readiness {readiness} is adequate for "
            f"{planned['workout_type']}. Proceed as planned."
        )

    return {
        "planned": planned,
        "readiness": readiness,
        "threshold": threshold,
        "recommend_swap": recommend_swap,
        "recommendation": recommendation,
    }


# ── Display Helpers ──


def get_upcoming_plan(conn, days=7):
    """Get planned workouts for the next N days.

    Returns list of dicts with planned workout info + match status.
    """
    today = date.today()
    end = today + timedelta(days=days)

    # Get latest active plan version
    version_row = conn.execute("""
        SELECT plan_version FROM planned_workouts
        WHERE status = 'active'
        ORDER BY plan_version DESC LIMIT 1
    """).fetchone()

    if not version_row:
        return []

    plan_version = version_row[0]

    planned = conn.execute("""
        SELECT pw.*, a.id as activity_id, a.distance_km as actual_km,
               a.duration_min as actual_min, a.effort_class as actual_effort
        FROM planned_workouts pw
        LEFT JOIN activities a
            ON pw.date = a.date AND a.type IN ('running', 'track_running', 'trail_running')
        WHERE pw.date BETWEEN ? AND ?
          AND pw.plan_version = ?
          AND pw.status = 'active'
        ORDER BY pw.date, pw.sequence_ordinal
    """, (today.isoformat(), end.isoformat(), plan_version)).fetchall()

    return [dict(r) for r in planned]
