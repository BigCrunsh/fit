"""Calibration tracking for physiological metrics."""

import json
import logging
import sqlite3
from datetime import date, timedelta

logger = logging.getLogger(__name__)

STALENESS_THRESHOLDS = {
    "max_hr": timedelta(days=365),
    "lthr": timedelta(days=56),  # 8 weeks
    "aet": timedelta(days=56),   # 8 weeks — AeT shifts during build phases
    "weight": timedelta(days=7),
    "vo2max": timedelta(days=90),
}

RETEST_PROMPTS = {
    "max_hr": "Verify during your next hard race or interval session.",
    "lthr": "Schedule a 30-min time trial, or we can auto-extract from your next 10k+ race.",
    "aet": "Run a 15+ km steady-pace effort (flat terrain, fueled) — we auto-derive AeT from HR drift.",
    "weight": "Step on the scale or enter weight in `fit checkin`.",
    "vo2max": "Run outdoors with GPS for Garmin to update estimate.",
}

# Plausibility envelopes for the flag taxonomy. Outside the envelope, a
# reading is recorded with `implausible_value` flag and `confidence=low`
# rather than being silently dropped — keeps an audit trail of strap
# glitches and lets the history chart show the anomaly as a red ring.
_PLAUSIBLE = {
    "max_hr": (140, 215),
    "lthr":   (130, 200),
    "aet":    (100, 180),  # typically 70-85% × LTHR for trained runners
    "vo2max": (25, 80),
    "weight": (35, 200),  # kg
}

# Direction-anomaly thresholds (drop vs prior active) within 12 weeks.
# Slow drift downward is real (age, detraining); sudden drops usually
# mean under-recovery or measurement noise.
_DIRECTION_DROP = {
    "max_hr": 2,    # bpm
    "lthr": 5,      # bpm
    "vo2max": 3,    # ml/kg/min
}

# Tolerance for "agrees with prior" — within ±tolerance of the active row.
_AGREE_TOLERANCE = {
    "max_hr": 2,
    "lthr": 2,
    "aet": 3,
    "vo2max": 1,
    "weight": 0.5,
}


def derive_flags(metric: str, value: float, method: str,
                 prior: dict | None) -> list[str]:
    """Compute the flag list for a new calibration reading.

    Inputs:
        metric: 'max_hr' | 'lthr' | 'aet' | 'vo2max' | 'weight'
        value: the new reading
        method: 'manual' | 'race_extract' | 'activity_max' | 'drift_test' | ...
        prior: the currently-active calibration dict (or None)

    Returns:
        Sorted list of flag strings. Empty list = clean reading.
    """
    flags: list[str] = []

    # implausible — physiologically out of envelope
    env = _PLAUSIBLE.get(metric)
    if env and (value < env[0] or value > env[1]):
        flags.append("implausible_value")

    if prior is not None:
        prior_val = prior.get("value")
        if prior_val is not None:
            tol = _AGREE_TOLERANCE.get(metric, 2)
            if abs(value - prior_val) <= tol:
                flags.append("agrees_with_prior")
            else:
                # Unexpected directional drop within 12 weeks
                drop_threshold = _DIRECTION_DROP.get(metric)
                if drop_threshold is not None and prior_val - value > drop_threshold:
                    if prior.get("date"):
                        prior_date = date.fromisoformat(prior["date"])
                        if (date.today() - prior_date).days < 84:  # 12 weeks
                            flags.append("unexpected_direction")
                # Upward revision of max_hr (or vo2max) in a hard-effort
                # context is the strongest evidence the prior was a low
                # guess — the body literally demonstrated a higher value.
                # Mark it as `new_peak` so derive_confidence promotes to
                # high rather than letting an older manual reading win.
                if (
                    metric in ("max_hr", "vo2max")
                    and method != "activity_max"
                    and value > prior_val + tol
                ):
                    flags.append("new_peak")

    # Weak context — extracted from a non-race / non-hard-effort activity.
    # `activity_max` flag is used by max_hr extraction outside races.
    if method == "activity_max":
        flags.append("weak_context")

    return sorted(set(flags))


def derive_confidence(method: str, flags: list[str], has_prior_agreement: bool = False) -> str:
    """Map (method, flags, prior_agreement) → confidence tier.

    Uniform rubric across all metrics:
        high   — manual write OR two corroborating readings within tolerance
        medium — single recent reading from a hard-effort context, no flags
        low    — any blocking flag (implausible_value / spike /
                 unexpected_direction / weak_context)

    Note: stale → low is a query-time concern, not encoded in the stored
    `confidence` field. The row's stored confidence reflects write-time
    quality; `get_calibration_status()` reports `low` when the active row
    has crossed its STALENESS_THRESHOLDS boundary.
    """
    # Blocking flags always demote to low — manual override can't rescue
    # an implausible reading (the user should re-enter or rely on the
    # next valid reading).
    blockers = {"implausible_value", "spike", "unexpected_direction", "weak_context"}
    if any(f in blockers for f in flags):
        return "low"
    if method == "manual":
        return "high"
    if has_prior_agreement or "agrees_with_prior" in flags:
        return "high"
    # Upward revision in a hard-effort context — physiology said so, trust it.
    if "new_peak" in flags:
        return "high"
    return "medium"


_CONFIDENCE_RANK = {"high": 0, "medium": 1, "low": 2}

# Methods that are recorded for history/context only and must NEVER be
# auto-selected as the active calibration. `race_estimate` LTHR rows are
# written from past races to populate the calibration-history chart, but the
# active LTHR stays human-confirmed (run `fit calibrate lthr`) so a noisy or
# non-max effort sitting in race_calendar can't silently shift the zone model.
INFORMATIONAL_METHODS = {"race_estimate"}


def get_active_calibration(conn: sqlite3.Connection, metric: str) -> dict | None:
    """Get the active calibration row for a metric, preferring higher confidence.

    Selection rule (subsumes the old date-only behavior):
      1. Informational rows (INFORMATIONAL_METHODS) are excluded entirely —
         they're chart history, never the active value.
      2. Prefer non-stale rows over stale rows.
      3. Within that pool, prefer higher confidence (high → medium → low).
      4. Within tied confidence, prefer the most recent date.

    This keeps a single spurious low-confidence row (e.g., a strap-glitch
    220 bpm max_hr) from displacing a clean medium-confidence row written
    earlier. Falls back to pure date if no rows are within the staleness
    window.
    """
    rows = conn.execute(
        "SELECT * FROM calibration WHERE metric = ?", (metric,),
    ).fetchall()
    rows = [r for r in rows if (r["method"] or "") not in INFORMATIONAL_METHODS]
    if not rows:
        return None

    threshold = STALENESS_THRESHOLDS.get(metric, timedelta(days=365))
    today = date.today()

    def _key(r):
        # Compound key: (stale flag, confidence rank, -ordinal). min() picks
        # non-stale before stale, then high → medium → low, then most recent.
        try:
            day = date.fromisoformat(r["date"])
            stale_flag = 1 if (today - day) > threshold else 0
            day_neg = -day.toordinal()
        except (ValueError, TypeError):
            stale_flag, day_neg = 1, 0
        return (stale_flag, _CONFIDENCE_RANK.get(r["confidence"] or "low", 2), day_neg)

    return dict(min(rows, key=_key))


# ── Standardizing anchor layer (standardize-calibration-anchors) ──
#
# Every consumer obtains a fitness anchor through get_calibration_anchor(),
# which applies a per-metric AGGREGATION_POLICY over that metric's observation
# rows. The policy matches the metric's statistics:
#
#   - VDOT / MaxHR are one-sided (a race is bounded above by fitness; MaxHR is
#     a literal ceiling) → take the MAX. A slow/trail race can't drag VDOT down
#     because a max never selects it.
#   - LTHR / AeT are two-sided noisy thresholds (a hot day inflates avg HR
#     without raising the threshold) → take a ROBUST CENTER (median/trimmed).
#
# Phase 1 ships the VDOT policy (max, recency-decayed). LTHR/AeT/MaxHR keep the
# legacy single-row selection until their policies land (Phase 5); for those,
# get_calibration_anchor falls back to get_active_calibration with no suggestion.
# Methods that represent a human-owned, confirmed anchor. The active value is
# *sticky* — it is whatever the athlete last confirmed and changes only when
# they accept a new suggestion (never auto-overwritten by the windowed max).
CONFIRMED_METHODS = {"manual", "confirmed"}

AGGREGATION_POLICY = {
    "vdot": {
        # Suggestion = max over observations inside a trailing window. A max
        # ignores slow/distorted efforts by construction (a trail or not-all-
        # out race can't be selected); the window is what captures downward
        # trends — a once-fast effort ages out and, if nothing fresh replaces
        # it, the anchor goes stale and prompts a re-test rather than guessing.
        "estimator": "max_window",
        "window_days": 180,           # 6 months — drives suggestions AND staleness
        # Garmin's wrist-HR estimate is reference-only (optimistic); it never
        # enters the max and is used only as a last-resort bootstrap value.
        "reference_methods": {"garmin_estimate"},
        "min_samples": 1,
        "differs_materially": 1.0,    # VDOT points before a suggestion is raised
    },
}


def _max_in_window(rows, window_days, now):
    """Maximum observation value inside a trailing window.

    Returns (value, [contributing rows in-window, best-first]) or (None, []).
    A max can't be dragged down by a slow/distorted effort; downward trends are
    captured by the window — old strong efforts age out of it.
    """
    floor = now - timedelta(days=window_days)
    scored = []
    for r in rows:
        try:
            d = date.fromisoformat(r["date"])
            v = float(r["value"])
        except (ValueError, TypeError, KeyError):
            continue
        if d < floor or d > now:
            continue
        scored.append((v, (now - d).days, r))
    if not scored:
        return None, []
    scored.sort(key=lambda s: s[0], reverse=True)
    return round(scored[0][0], 1), [dict(s[2], _age_days=s[1]) for s in scored]


def get_calibration_anchor(conn: sqlite3.Connection, metric: str) -> dict | None:
    """Canonical fitness anchor for a metric — the single way consumers read one.

    Returns a payload::

        {value, confidence, method, stale, inputs, suggestion}

    - ``value`` is what consumers use: the human-confirmed *sticky* active value
      when one exists, else the policy estimate so the dashboard is never blank.
    - ``stale`` is True when the value's source effort is older than the policy
      window (or there is no in-window evidence) — the cue to prompt a re-test.
    - ``suggestion`` is the policy estimate from the trailing window plus whether
      it ``differs`` materially from the active value (what sync uses to prompt
      accept/reject). None when no in-window observation exists.

    Metrics without a policy fall back to the legacy single-row selection
    (no suggestion), so nothing regresses before their policies land.
    """
    policy = AGGREGATION_POLICY.get(metric)
    active = get_active_calibration(conn, metric)

    if not policy:
        if not active:
            return None
        return {"value": active["value"], "confidence": active.get("confidence"),
                "method": active.get("method"), "stale": None,
                "inputs": [active], "suggestion": None}

    rows = [dict(r) for r in conn.execute(
        "SELECT * FROM calibration WHERE metric = ?", (metric,)).fetchall()]
    ref = policy.get("reference_methods", set())
    observations = [r for r in rows if (r.get("method") or "") not in ref]
    now = date.today()
    window = policy["window_days"]

    suggestion = None
    if policy["estimator"] == "max_window" and len(observations) >= policy["min_samples"]:
        val, contributors = _max_in_window(observations, window, now)
        if val is not None:
            top = contributors[0]
            suggestion = {
                "value": val,
                "reason": (f"max of {len(contributors)} effort(s) in last "
                           f"{window}d: {top['value']:g} from {top['date']} "
                           f"(~{top['_age_days']}d ago)"),
                "inputs": contributors,
            }

    # Sticky active: a confirmed/manual row is the value, untouched by the
    # window. Without one (bootstrap), fall back to the windowed suggestion.
    confirmed = active if (active and active.get("method") in CONFIRMED_METHODS) else None
    if confirmed:
        value = confirmed["value"]
        confidence = confirmed.get("confidence")
        method = confirmed["method"]
        src_date = confirmed.get("date")
    elif suggestion is not None:
        value, confidence, method, src_date = suggestion["value"], "medium", "policy", suggestion["inputs"][0]["date"]
    elif active:
        value, confidence, method, src_date = active["value"], active.get("confidence"), active.get("method"), active.get("date")
    else:
        return {"value": None, "confidence": None, "method": None, "stale": True,
                "inputs": [], "suggestion": suggestion}

    # Stale when the value's source effort has aged past the window.
    stale = True
    try:
        stale = (now - date.fromisoformat(src_date)).days > window
    except (ValueError, TypeError):
        stale = True

    if suggestion is not None:
        suggestion["differs"] = abs(suggestion["value"] - value) >= policy["differs_materially"]

    return {"value": value, "confidence": confidence, "method": method, "stale": stale,
            "inputs": suggestion["inputs"] if suggestion else ([confirmed] if confirmed else []),
            "suggestion": suggestion}


def add_calibration(conn: sqlite3.Connection, metric: str, value: float,
                    method: str, confidence: str, cal_date: date,
                    source_activity_id: str | None = None,
                    notes: str | None = None,
                    flags: list[str] | None = None) -> None:
    """Add a new calibration row.

    The new row is marked active=1; all prior rows for the metric get
    active=0. Note: this is just a bookkeeping flag — `get_active_calibration`
    re-evaluates active using the confidence-aware rule on every read, so
    the column's value reflects "last inserted", not "currently used".

    `flags` is a list of taxonomy tags ({implausible_value, spike,
    unexpected_direction, agrees_with_prior, weak_context}) — stored as a
    JSON array string. Empty list / None becomes '[]'.
    """
    conn.execute("UPDATE calibration SET active = 0 WHERE metric = ? AND active = 1", (metric,))
    flags_json = json.dumps(sorted(set(flags))) if flags else "[]"
    conn.execute("""
        INSERT INTO calibration (metric, value, method, confidence, date,
                                 source_activity_id, notes, active, flags)
        VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?)
    """, (metric, value, method, confidence, cal_date.isoformat(),
          source_activity_id, notes, flags_json))
    conn.commit()
    logger.info("Calibration added: %s = %s (%s, %s confidence%s)",
                metric, value, method, confidence,
                f", flags={flags}" if flags else "")


def is_stale(conn: sqlite3.Connection, metric: str) -> bool:
    """Check if a calibration is older than its staleness threshold."""
    cal = get_active_calibration(conn, metric)
    if cal is None:
        return True
    threshold = STALENESS_THRESHOLDS.get(metric, timedelta(days=365))
    cal_date = date.fromisoformat(cal["date"])
    return (date.today() - cal_date) > threshold


def get_calibration_status(conn: sqlite3.Connection) -> list[dict]:
    """Get status of all tracked metrics with staleness and retest prompts."""
    results = []
    for metric in ("max_hr", "lthr", "aet", "weight", "vo2max"):
        cal = get_active_calibration(conn, metric)
        stale = is_stale(conn, metric)
        threshold = STALENESS_THRESHOLDS[metric]

        entry = {
            "metric": metric,
            "value": cal["value"] if cal else None,
            "method": cal["method"] if cal else None,
            "date": cal["date"] if cal else None,
            "confidence": cal["confidence"] if cal else None,
            "stale": stale,
            "missing": cal is None,
            "threshold_days": threshold.days,
            "retest_prompt": RETEST_PROMPTS[metric] if stale else None,
        }

        if cal and not stale:
            cal_date = date.fromisoformat(cal["date"])
            entry["days_ago"] = (date.today() - cal_date).days
            entry["days_until_stale"] = (cal_date + threshold - date.today()).days

        results.append(entry)

    return results


def get_calibration_history(conn: sqlite3.Connection, metric: str) -> list[dict]:
    """Return every calibration row for a metric, oldest first.

    Used by the dashboard's per-metric history chart and by the CLI
    `fit calibrate history <metric>` command. Each dict includes value,
    date, method, confidence, source_activity_id, notes, and the parsed
    flags list.
    """
    rows = conn.execute("""
        SELECT id, metric, value, method, confidence, date,
               source_activity_id, notes, flags
        FROM calibration
        WHERE metric = ?
        ORDER BY date ASC
    """, (metric,)).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        try:
            d["flags"] = json.loads(d["flags"] or "[]")
        except (ValueError, TypeError):
            d["flags"] = []
        out.append(d)
    return out


def extract_max_hr_from_activity(activity: dict, current_max_hr: float | None) -> float | None:
    """Return the activity's max_hr if it raises the calibrated max above current.

    The watch records peak HR per activity. When that peak exceeds the stored
    max_hr calibration by >1 bpm and falls within a physiologically plausible
    range, treat it as evidence that the calibration is out of date — the body
    just demonstrated a higher max than we had on file.

    Plausible range: 140–215 bpm for adults. Above 215 is almost always a strap
    glitch; below 140 is too low to be a max for a trained runner. Returns
    None when the activity gives us no new information.

    Accepts any running-class activity (running, track_running, trail_running),
    matching the broader RUNNING_TYPES convention used elsewhere.
    """
    from fit.analysis import RUNNING_TYPES
    if activity.get("type") not in RUNNING_TYPES:
        return None
    observed = activity.get("max_hr")
    if not observed or observed < 140 or observed > 215:
        return None
    if current_max_hr is not None and observed <= current_max_hr + 1:
        return None
    return float(observed)


# Thresholds for AeT candidate detection. Named so they're greppable.
_AET_MIN_DISTANCE_KM = 12.0
_AET_STEADY_PACE_STDDEV_SEC = 15.0


def _weighted_hr_avg(splits: list[dict]) -> float | None:
    """Distance-weighted average HR over a list of split rows.

    Splits with missing `avg_hr` are excluded from BOTH numerator and
    denominator — keeps the math symmetric instead of silently zeroing
    the numerator. Returns None when no usable rows remain.
    """
    valid = [s for s in splits
             if s.get("avg_hr") is not None and s.get("distance_km")]
    if not valid:
        return None
    total_hr_km = sum(s["avg_hr"] * s["distance_km"] for s in valid)
    total_km = sum(s["distance_km"] for s in valid)
    return total_hr_km / total_km if total_km else None


def extract_aet_from_steady_run(activity: dict, splits: list[dict]) -> dict | None:
    """Derive an AeT estimate from a candidate steady-pace long run.

    Method (HR-drift bisection):
      1. Require running activity with distance >= _AET_MIN_DISTANCE_KM (12 km).
      2. Pace stddev across the run's middle splits (warmup + cooldown
         excluded) must be < _AET_STEADY_PACE_STDDEV_SEC (15 sec/km).
      3. Compute first-half vs second-half avg HR (distance-weighted).
      4. drift_pct = (h2 - h1) / h1 * 100
      5. Classify:
          drift < 0      → invalid (negative drift, no row written)
          0 ≤ drift < 5  → lower bound: AeT > avg_hr_of_run
          5 ≤ drift ≤ 7  → direct estimate: AeT ≈ avg_hr_of_run
          drift > 7      → upper bound: AeT < avg_hr_of_run

    Returns dict with `value` (the AeT estimate, in bpm), `drift_pct`,
    and `classification`. Returns None when the activity doesn't qualify.
    The caller maps `classification` → flag taxonomy when storing.
    """
    from fit.analysis import RUNNING_TYPES

    if activity.get("type") not in RUNNING_TYPES:
        return None
    distance = activity.get("distance_km") or 0
    if distance < _AET_MIN_DISTANCE_KM:
        return None
    if not splits or len(splits) < 4:
        return None

    # Pace-steadiness check uses the middle (warmup + cooldown excluded).
    # HR-drift uses the FULL split set — warmup HR is part of how the body
    # responded to the effort and matters for the first-half average.
    middle_paces = [s["pace_sec_per_km"] for s in splits[1:-1]
                    if s.get("pace_sec_per_km") is not None]
    if len(middle_paces) < 2:
        return None
    mean_pace = sum(middle_paces) / len(middle_paces)
    variance = sum((p - mean_pace) ** 2 for p in middle_paces) / len(middle_paces)
    if variance ** 0.5 > _AET_STEADY_PACE_STDDEV_SEC:
        return None  # not steady — likely intervals or fartlek

    mid = len(splits) // 2
    h1 = _weighted_hr_avg(splits[:mid])
    h2 = _weighted_hr_avg(splits[mid:])
    if h1 is None or h2 is None or h1 <= 0:
        return None
    drift_pct = (h2 - h1) / h1 * 100

    if drift_pct < 0:
        return None  # negative drift — runner slowed down or fueling kicked in

    # Run-average HR (used as the AeT estimate/anchor across all classes)
    avg_hr = activity.get("avg_hr") or ((h1 + h2) / 2)

    if drift_pct < 5:
        classification = "lower_bound"
    elif drift_pct <= 7:
        classification = "direct_estimate"
    else:
        classification = "upper_bound"

    return {
        "value": round(float(avg_hr), 1),
        "drift_pct": round(drift_pct, 2),
        "classification": classification,
    }


def extract_lthr_from_race(activity: dict) -> float | None:
    """Estimate LTHR from a race activity >= 10km.

    Uses avg HR of the second half of the race as an approximation.
    Since we don't have split data, we use the overall avg HR as a proxy
    (for races, avg HR of the whole effort is close to LTHR).
    """
    distance = activity.get("distance_km") or 0
    avg_hr = activity.get("avg_hr")
    run_type = activity.get("run_type")

    activity_type = activity.get("type", "")
    if activity_type != "running" or run_type != "race" or distance < 10 or not avg_hr:
        return None

    # For races >= 10km, overall avg HR approximates LTHR
    # For HM/marathon, it's slightly below LTHR; for 10k, slightly above
    # Apply a small correction factor based on distance
    if distance >= 40:  # marathon
        correction = 1.02  # avg HR is ~2% below LTHR
    elif distance >= 20:  # half marathon
        correction = 1.01
    else:  # 10k-ish
        correction = 0.99  # avg HR is ~1% above LTHR

    estimated_lthr = round(avg_hr * correction)
    logger.info("LTHR estimate from %s (%.1fkm): avg_hr=%d → estimated LTHR=%d",
                activity.get("name"), distance, avg_hr, estimated_lthr)
    return estimated_lthr


def backfill_race_lthr(conn: sqlite3.Connection) -> int:
    """Populate LTHR *history* from past races for the calibration chart.

    For every completed race ≥10km with a linked activity, write an
    informational `race_estimate` LTHR row (a method get_active_calibration
    ignores) dated at the race. This builds the LTHR-over-time series the
    calibration chart shows WITHOUT touching the active calibration — under
    the human-confirmed model (Option A) a noisy or non-max race can't shift
    the zones. Idempotent: skips a race already represented by a race_estimate
    row (matched on source_activity_id). Returns the number of rows added.

    To promote one of these to the active LTHR, the athlete confirms it
    deliberately via `fit calibrate lthr <value>`.
    """
    from fit.analysis import RUNNING_TYPES_SQL

    races = conn.execute(f"""
        SELECT a.id, a.date, a.name, a.distance_km, a.avg_hr
        FROM race_calendar rc JOIN activities a ON a.id = rc.activity_id
        WHERE rc.status = 'completed' AND a.type IN {RUNNING_TYPES_SQL}
          AND a.distance_km >= 10 AND a.avg_hr IS NOT NULL
        ORDER BY a.date ASC
    """).fetchall()

    added = 0
    for r in races:
        exists = conn.execute(
            "SELECT 1 FROM calibration WHERE metric = 'lthr' AND method = 'race_estimate' "
            "AND source_activity_id = ? LIMIT 1", (r["id"],),
        ).fetchone()
        if exists:
            continue
        est = extract_lthr_from_race({
            "type": "running", "run_type": "race",
            "distance_km": r["distance_km"], "avg_hr": r["avg_hr"], "name": r["name"],
        })
        if not est:
            continue
        # Plain insert with active=0 — do NOT call add_calibration (which would
        # flip the active flag). These are history, not the active value.
        # confidence='low' is belt-and-suspenders: get_active_calibration
        # already excludes race_estimate by method, but low confidence also
        # keeps a real (medium/high) calibration winning under the plain
        # confidence-then-recency rule — so even an older code path can't
        # promote an estimate to active.
        conn.execute("""
            INSERT INTO calibration (metric, value, method, confidence, date,
                                     source_activity_id, notes, active, flags)
            VALUES ('lthr', ?, 'race_estimate', 'low', ?, ?, ?, 0, '[]')
        """, (est, r["date"], r["id"],
              f"Race estimate from {r['name']} ({r['distance_km']:.1f}km, avg HR {r['avg_hr']})"))
        added += 1
    conn.commit()
    return added
