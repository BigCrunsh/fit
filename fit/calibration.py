"""Calibration tracking for physiological metrics."""

import json
import logging
import os
import sqlite3
from dataclasses import dataclass
from datetime import date, timedelta
from enum import Enum, IntEnum

logger = logging.getLogger(__name__)


# ── Typed trust taxonomy (DDD E1+E2) ─────────────────────────────────────────
# The calibration trust model as types. `TrustTier`'s ordering IS the precedence
# (confirmed > device > policy > legacy); INFORMATIONAL/REFERENCE are never
# anchors. `CalibrationMethod` pairs every known stored method string with a
# tier — an "untiered method" is unrepresentable — and `resolve` degrades an
# unknown/legacy string to TrustTier.LEGACY rather than raising, so historical
# rows keep loading. `CalibrationAnchor` makes "an anchor with no value"
# unrepresentable. See docs/GLOSSARY.md (trust taxonomy) and the archived
# typed-calibration-anchor OpenSpec change.


class TrustTier(IntEnum):
    """How far a calibration source is trusted; the ordering is the precedence."""

    INFORMATIONAL = 0   # race_observation/effort_observation — history/chart, never an anchor
    REFERENCE = 1       # device_vo2max — context only, never an estimator input
    LEGACY = 2          # un-tiered/unknown active row — last-resort fallback
    POLICY = 3          # the windowed policy estimate ("what races imply")
    DEVICE = 4          # device_lt — instrument measurement
    CONFIRMED = 5       # manual/confirmed — human-owned, sticky

    @property
    def is_anchor_eligible(self) -> bool:
        """REFERENCE/INFORMATIONAL are never anchors; anything >= LEGACY can be."""
        return self >= TrustTier.LEGACY


class Confidence(IntEnum):
    """Ordered confidence tier; replaces the _CONFIDENCE_RANK dict."""

    LOW = 0
    MEDIUM = 1
    HIGH = 2

    @classmethod
    def from_str(cls, s: str | None) -> "Confidence":
        return {"low": cls.LOW, "medium": cls.MEDIUM, "high": cls.HIGH}.get(
            (s or "").lower(), cls.LOW)

    def to_str(self) -> str:
        return self.name.lower()


class CalibrationMethod(Enum):
    """A stored calibration-method string paired with its trust tier.

    A member cannot be declared without a tier, so an "untiered method" is
    unrepresentable. `resolve` maps a stored string to a member, degrading
    unknown/None strings to the LEGACY sentinel (never raises). `POLICY` is the
    marker for the synthesized windowed suggestion (not a stored string).
    """

    MANUAL             = ("manual",             TrustTier.CONFIRMED)
    CONFIRMED          = ("confirmed",          TrustTier.CONFIRMED)
    DEVICE_LT          = ("device_lt",          TrustTier.DEVICE)
    DEVICE_VO2MAX      = ("device_vo2max",      TrustTier.REFERENCE)
    RACE_OBSERVATION   = ("race_observation",   TrustTier.INFORMATIONAL)
    EFFORT_OBSERVATION = ("effort_observation", TrustTier.INFORMATIONAL)
    RACE_CANDIDATE     = ("race_candidate",     TrustTier.LEGACY)
    ACTIVITY_MAX       = ("activity_max",       TrustTier.LEGACY)
    DRIFT_TEST         = ("drift_test",         TrustTier.LEGACY)
    SCALE              = ("scale",              TrustTier.LEGACY)
    POLICY             = ("policy",             TrustTier.POLICY)
    LEGACY             = ("__legacy__",         TrustTier.LEGACY)

    def __init__(self, method_str: str, trust_tier: TrustTier):
        self.method_str = method_str
        self.trust_tier = trust_tier

    @property
    def is_anchor_eligible(self) -> bool:
        return self.trust_tier.is_anchor_eligible

    @classmethod
    def resolve(cls, s: str | None) -> "CalibrationMethod":
        """Map a stored method string to a member; unknown/None → LEGACY."""
        if s:
            for m in cls:
                if m is not cls.LEGACY and m.method_str == s:
                    return m
        return cls.LEGACY


@dataclass(frozen=True)
class CalibrationAnchor:
    """The single canonical value for a metric (DDD E1).

    `value` is always a real number — "an anchor with no value" is
    unrepresentable; absence is signalled by `get_calibration_anchor` returning
    None. `method`/`confidence` stay the same display strings the legacy dict
    exposed; the typed taxonomy above is used internally for selection.
    """

    metric: str
    value: float
    confidence: str | None
    method: str
    source_date: str | None
    stale: bool | None
    inputs: list
    suggestion: dict | None

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
    "vdot":   (25, 80),    # same envelope as vo2max — VDOT is a pseudo-VO2max
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
    "vdot": 1,
    "weight": 0.5,
}


def derive_flags(metric: str, value: float, method: str,
                 prior: dict | None) -> list[str]:
    """Compute the flag list for a new calibration reading.

    Inputs:
        metric: 'max_hr' | 'lthr' | 'aet' | 'vo2max' | 'weight'
        value: the new reading
        method: 'manual' | 'race_candidate' | 'activity_max' | 'drift_test' | ...
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


# Confidence ordering and the method→tier taxonomy live in the typed enums
# (`Confidence`, `CalibrationMethod`/`TrustTier`) at the top of the module. The
# four former string-sets (CONFIRMED/DEVICE/REFERENCE/INFORMATIONAL_METHODS) and
# the `_CONFIDENCE_RANK` dict are gone — selection reads `method.trust_tier` and
# `Confidence` directly.
#
# Informational-tier rows (`race_observation`/`effort_observation`) are recorded
# for the calibration-history chart but must NEVER be auto-selected as the active
# value: the active LTHR stays human-confirmed (run `fit calibrate lthr`) so a
# noisy or non-max race can't silently shift the zone model.


def get_active_calibration(conn: sqlite3.Connection, metric: str,
                           asof: date | None = None) -> dict | None:
    """Get the active calibration row for a metric, preferring higher confidence.

    Selection rule (subsumes the old date-only behavior):
      1. Informational-tier rows (`race_observation`/`effort_observation`) are
         excluded entirely — they're chart history, never the active value.
      2. Prefer non-stale rows over stale rows.
      3. Within that pool, prefer higher confidence (high → medium → low).
      4. Within tied confidence, prefer the most recent date.

    This keeps a single spurious low-confidence row (e.g., a strap-glitch
    220 bpm max_hr) from displacing a clean medium-confidence row written
    earlier. Falls back to pure date if no rows are within the staleness
    window.

    `asof` enables POINT-IN-TIME reconstruction: it returns the row that was
    active *as of* that date — only rows dated on/before `asof` are considered,
    and staleness is judged relative to `asof`. This is how historical zone /
    phase classifications stay stable when a calibration later changes: an
    activity is classified with the anchor active on ITS date, not today's. With
    no `asof` (the default) it returns the currently-active row as before.
    """
    ref = asof or date.today()
    rows = conn.execute(
        "SELECT * FROM calibration WHERE metric = ?", (metric,),
    ).fetchall()
    rows = [r for r in rows
            if CalibrationMethod.resolve(r["method"]).trust_tier != TrustTier.INFORMATIONAL]

    # Point-in-time: only when reconstructing a past date do we exclude rows
    # dated after it. The default (asof=None) keeps the exact prior behaviour
    # (all rows eligible) so nothing about "current" selection changes.
    if asof is not None:
        def _on_or_before(r):
            try:
                return date.fromisoformat(r["date"]) <= ref
            except (ValueError, TypeError):
                return True  # undated rows always eligible
        rows = [r for r in rows if _on_or_before(r)]
    if not rows:
        return None

    threshold = STALENESS_THRESHOLDS.get(metric, timedelta(days=365))

    def _key(r):
        # Compound key: (stale flag, -confidence, -ordinal). min() picks
        # non-stale before stale, then high → medium → low, then most recent.
        try:
            day = date.fromisoformat(r["date"])
            stale_flag = 1 if (ref - day) > threshold else 0
            day_neg = -day.toordinal()
        except (ValueError, TypeError):
            stale_flag, day_neg = 1, 0
        return (stale_flag, -Confidence.from_str(r["confidence"]), day_neg)

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
# Trust tiers (CONFIRMED > DEVICE > POLICY > LEGACY; REFERENCE/INFORMATIONAL never
# anchors) are defined on `CalibrationMethod`/`TrustTier` at the top of the module:
#   - CONFIRMED (manual/confirmed): human-owned, *sticky* active value — changes
#     only when the athlete accepts a new suggestion, never auto-overwritten.
#   - DEVICE (device_lt): Garmin's auto-detected LT — authoritative ABOVE the
#     race-proxy policy estimate but BELOW a human confirm; kept out of the policy
#     estimator (the policy answers "what do your RACES imply", a `differs` cross-check).
#   - REFERENCE (device_vo2max): recorded for context, never fed to an estimator
#     and never an anchor — Garmin's wrist-HR VO2max is optimistic by design.

# Two estimator families, picked by the metric's statistics:
#   - 'max'    — one-sided / ceiling metrics (VDOT, MaxHR). A slow/distorted
#                effort can't be selected, so no gate is needed; downward trends
#                surface as strong efforts ageing out of the window → stale.
#   - 'median' — two-sided noisy thresholds (LTHR, AeT). A hot day inflates avg
#                HR without raising the threshold; a max would bias the zone
#                ceiling up, so we take a robust centre.
# Uniform shape for all four: a trailing window, staleness == window, sticky
# confirm, no hard gates (plausibility/effort-hardness ride along as confidence,
# surfaced at the confirm prompt). Only three things vary: family (→ min_samples
# 1 vs 3), MaxHR's longer 365d window (max HR is hit ~yearly), and the unit of
# `differs` (reusing _AGREE_TOLERANCE). See standardize-calibration-anchors.
AGGREGATION_POLICY = {
    "vdot":   {"family": "max",    "window_days": 180, "min_samples": 1, "differs": 1.0},
    "max_hr": {"family": "max",    "window_days": 365, "min_samples": 1, "differs": 2.0},
    "lthr":   {"family": "median", "window_days": 180, "min_samples": 3, "differs": 2.0},
    "aet":    {"family": "median", "window_days": 180, "min_samples": 3, "differs": 3.0},
}


def _window_obs(rows, window_days, now):
    """Observation rows inside the trailing window, each tagged with _age_days."""
    floor = now - timedelta(days=window_days)
    out = []
    for r in rows:
        try:
            d = date.fromisoformat(r["date"])
            float(r["value"])
        except (ValueError, TypeError, KeyError):
            continue
        if d < floor or d > now:
            continue
        out.append(dict(r, _age_days=(now - d).days))
    return out


def _max_in_window(rows, window_days, now):
    """Maximum observation value inside a trailing window (one-sided metrics).

    Returns (value, [contributing rows in-window, best-first]) or (None, []).
    A max can't be dragged down by a slow/distorted effort; downward trends are
    captured by the window — old strong efforts age out of it.
    """
    obs = _window_obs(rows, window_days, now)
    if not obs:
        return None, []
    obs.sort(key=lambda r: float(r["value"]), reverse=True)
    return round(float(obs[0]["value"]), 1), obs


def _median_in_window(rows, window_days, now):
    """Median observation value inside a trailing window (two-sided thresholds).

    The median is intrinsically outlier-robust — a hot-day high reading can't
    pull it up the way a max would. Returns (value, [rows recent-first]) or
    (None, []).
    """
    obs = _window_obs(rows, window_days, now)
    if not obs:
        return None, []
    vals = sorted(float(r["value"]) for r in obs)
    n = len(vals)
    med = vals[n // 2] if n % 2 else (vals[n // 2 - 1] + vals[n // 2]) / 2
    obs.sort(key=lambda r: r["_age_days"])
    return round(med, 1), obs


def get_calibration_anchor(conn: sqlite3.Connection, metric: str) -> CalibrationAnchor | None:
    """Canonical calibration anchor for a metric — the single way consumers read one.

    Returns a :class:`CalibrationAnchor` whose ``value`` is always a real number,
    or ``None`` when no anchor-eligible value exists. There is no "anchor with no
    value": absence is ``None`` and a consumer's only check is ``anchor is None``.

    - ``value`` is the human-confirmed *sticky* active value when one exists, else
      the policy estimate so the dashboard is never blank.
    - ``stale`` is True when the value's source effort is older than the policy
      window (or there is no in-window evidence) — the cue to prompt a re-test.
    - ``suggestion`` is the policy estimate from the trailing window plus whether
      it ``differs`` materially from the active value (what sync uses to prompt
      accept/reject), a plain-language ``reason``, and a ``confidence`` carried
      from the contributing rows (the confidence model is surfaced at the prompt,
      not used to auto-filter). None when there is no in-window observation.

    Metrics without a policy fall back to the legacy single-row selection
    (no suggestion), so nothing regresses.
    """
    policy = AGGREGATION_POLICY.get(metric)
    active = get_active_calibration(conn, metric)

    if not policy:
        if not active:
            return None
        return CalibrationAnchor(
            metric=metric, value=active["value"], confidence=active.get("confidence"),
            method=active.get("method"), source_date=active.get("date"), stale=None,
            inputs=[active], suggestion=None)

    rows = [dict(r) for r in conn.execute(
        "SELECT * FROM calibration WHERE metric = ?", (metric,)).fetchall()]
    observations = [r for r in rows
                    if CalibrationMethod.resolve(r.get("method")).trust_tier
                    not in (TrustTier.REFERENCE, TrustTier.DEVICE)]
    now = date.today()
    window = policy["window_days"]
    family = policy["family"]
    estimator = _max_in_window if family == "max" else _median_in_window

    suggestion = None
    val, contributors = estimator(observations, window, now)
    if val is not None:
        if len(contributors) >= policy["min_samples"]:
            # Confidence rides from the contributing rows; lowest wins (a single
            # implausible/low row keeps the suggestion cautious for the prompt).
            confs = [c.get("confidence") or "low" for c in contributors]
            sug_conf = min(confs, key=Confidence.from_str)   # lowest confidence wins
            verb = "max" if family == "max" else "median"
            top = contributors[0]
            suggestion = {
                "value": val,
                "confidence": sug_conf,
                "reason": (f"{verb} of {len(contributors)} effort(s) in last {window}d"
                           + (f" — best {top['value']:g} from {top['date']} (~{top['_age_days']}d ago)"
                              if family == "max" else "")),
                "inputs": contributors,
            }
        elif contributors:
            # Below min_samples (median needs ≥N): don't fabricate a centre —
            # fall back to the most recent single row at low confidence.
            recent = min(contributors, key=lambda c: c["_age_days"])
            suggestion = {
                "value": round(float(recent["value"]), 1),
                "confidence": "low",
                "reason": (f"only {len(contributors)} of {policy['min_samples']} "
                           f"needed in last {window}d — using most recent, low confidence"),
                "inputs": contributors,
            }

    # Precedence: human confirm (sticky) > device measurement (Garmin LT) > policy
    # estimate (what races imply) > legacy active. A confirmed/manual row is the
    # value, untouched by the estimator; else a recent device reading is
    # authoritative over the race-proxy; else fall back to the policy suggestion.
    active_tier = CalibrationMethod.resolve(active.get("method")).trust_tier if active else None
    confirmed = active if active_tier == TrustTier.CONFIRMED else None
    device = active if active_tier == TrustTier.DEVICE else None
    if confirmed:
        value, confidence, method, src_date = (
            confirmed["value"], confirmed.get("confidence"), confirmed["method"], confirmed.get("date"))
    elif device:
        value, confidence, method, src_date = (
            device["value"], device.get("confidence"), device["method"], device.get("date"))
    elif suggestion is not None:
        value, confidence, method, src_date = (
            suggestion["value"], suggestion["confidence"], "policy", suggestion["inputs"][0]["date"])
    elif active and active_tier.is_anchor_eligible:
        # Legacy fallback — any anchor-eligible active row that isn't confirmed/
        # device. REFERENCE rows (e.g. Garmin VO2max) are excluded by
        # is_anchor_eligible, so they never become the anchor.
        value, confidence, method, src_date = (
            active["value"], active.get("confidence"), active.get("method"), active.get("date"))
    else:
        return None

    # Stale when the value's source effort has aged past the window.
    try:
        stale = (now - date.fromisoformat(src_date)).days > window
    except (ValueError, TypeError):
        stale = True

    if suggestion is not None:
        suggestion["differs"] = abs(suggestion["value"] - value) >= policy["differs"]

    return CalibrationAnchor(
        metric=metric, value=value, confidence=confidence, method=method,
        source_date=src_date, stale=stale,
        inputs=(suggestion["inputs"] if suggestion else ([confirmed] if confirmed else [])),
        suggestion=suggestion)


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
    informational `race_observation` LTHR row (a method get_active_calibration
    ignores) dated at the race. This builds the LTHR-over-time series the
    calibration chart shows WITHOUT touching the active calibration — under
    the human-confirmed model (Option A) a noisy or non-max race can't shift
    the zones. Idempotent: skips a race already represented by a race_observation
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
            "SELECT 1 FROM calibration WHERE metric = 'lthr' AND method = 'race_observation' "
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
        # already excludes race_observation by method, but low confidence also
        # keeps a real (medium/high) calibration winning under the plain
        # confidence-then-recency rule — so even an older code path can't
        # promote an estimate to active.
        conn.execute("""
            INSERT INTO calibration (metric, value, method, confidence, date,
                                     source_activity_id, notes, active, flags)
            VALUES ('lthr', ?, 'race_observation', 'low', ?, ?, ?, 0, '[]')
        """, (est, r["date"], r["id"],
              f"Race estimate from {r['name']} ({r['distance_km']:.1f}km, avg HR {r['avg_hr']})"))
        added += 1
    conn.commit()
    return added


def _parse_hms(t: str | None) -> int | None:
    """Parse 'H:MM:SS' or 'MM:SS' to seconds. None on bad input."""
    if not t:
        return None
    try:
        parts = [int(p) for p in t.split(":")]
    except (ValueError, AttributeError):
        return None
    if len(parts) == 3:
        return parts[0] * 3600 + parts[1] * 60 + parts[2]
    if len(parts) == 2:
        return parts[0] * 60 + parts[1]
    return None


def backfill_race_vdot(conn: sqlite3.Connection) -> int:
    """Populate VDOT *observations* from past races for the anchor + history.

    For every completed race in 5–25 km with a usable time, write an
    informational `race_observation` VDOT row (which get_active_calibration
    ignores) dated at the race, computed via Daniels. These feed the VDOT
    aggregation policy's windowed max and the calibration-history chart WITHOUT
    becoming the active value — under the human-confirmed model the athlete
    confirms the anchor via `fit calibrate vdot <value>` (or the sync prompt).
    Official `result_time` is preferred over `garmin_time`. Idempotent on
    source_activity_id. Returns the number of rows added.
    """
    from fit.fitness import compute_vdot_from_race

    races = conn.execute("""
        SELECT a.id, a.date, a.name, a.distance_km,
               COALESCE(rc.result_time, rc.garmin_time) AS race_time
        FROM race_calendar rc JOIN activities a ON a.id = rc.activity_id
        WHERE rc.status = 'completed' AND a.distance_km >= 5 AND a.distance_km <= 25
        ORDER BY a.date ASC
    """).fetchall()

    added = 0
    for r in races:
        secs = _parse_hms(r["race_time"])
        if not secs:
            continue
        vdot = compute_vdot_from_race(r["distance_km"], secs)
        if vdot is None:
            continue
        exists = conn.execute(
            "SELECT 1 FROM calibration WHERE metric = 'vdot' AND method = 'race_observation' "
            "AND source_activity_id = ? LIMIT 1", (r["id"],),
        ).fetchone()
        if exists:
            continue
        conn.execute("""
            INSERT INTO calibration (metric, value, method, confidence, date,
                                     source_activity_id, notes, active, flags)
            VALUES ('vdot', ?, 'race_observation', 'low', ?, ?, ?, 0, '[]')
        """, (round(vdot, 1), r["date"], r["id"],
              f"Race estimate from {r['name']} ({r['distance_km']:.1f}km)"))
        added += 1
    conn.commit()
    return added


def backfill_effort_vdot(conn: sqlite3.Connection, days: int = 720) -> int:
    """Populate VDOT observations from qualifying hard TRAINING efforts.

    Races are covered by backfill_race_vdot (official times). This adds the
    other half of "races ∪ hard efforts": any non-race effort that passes the
    physiological qualifier (5–25 km, avg HR ≥ LTHR, consistent pace) per
    get_fitness_anchors, written as an informational `effort_observation` vdot row.
    A max estimator means a slow effort is harmless (never selected); a genuine
    hard solo time-trial can only sharpen the anchor. Idempotent on
    source_activity_id, and skips activities already represented by a race row.
    Returns rows added.
    """
    from fit.fitness import get_fitness_anchors

    anchors = [a for a in get_fitness_anchors(conn, days=days)
               if a.get("source") == "training"]
    added = 0
    for a in anchors:
        aid = a["activity_id"]
        exists = conn.execute(
            "SELECT 1 FROM calibration WHERE metric = 'vdot' "
            "AND method IN ('race_observation', 'effort_observation') "
            "AND source_activity_id = ? LIMIT 1", (aid,),
        ).fetchone()
        if exists:
            continue
        conn.execute("""
            INSERT INTO calibration (metric, value, method, confidence, date,
                                     source_activity_id, notes, active, flags)
            VALUES ('vdot', ?, 'effort_observation', 'low', ?, ?, ?, 0, '[]')
        """, (round(a["vdot"], 1), a["date"], aid,
              f"Hard-effort estimate from {a.get('name') or 'training effort'} "
              f"({a['distance_km']:.1f}km, avg HR {a['avg_hr']})"))
        added += 1
    conn.commit()
    return added


# ── Suggest → confirm governance (standardize-calibration-anchors) ──
#
# Anchors never change silently. After ingest, evaluate_suggestions() finds the
# metrics whose policy suggestion differs materially from the active value. The
# human accepts (writes a confirmed anchor) or rejects (recorded in a ledger so
# the same value isn't re-raised until it moves). State lives in a small JSON
# sidecar next to the DB — no schema change, easy to inspect.

def _review_path() -> str:
    from fit.config import get_config
    try:
        db = get_config().get("sync", {}).get("db_path")
    except Exception:
        db = None
    db = db or os.path.expanduser("~/.fit/fitness.db")
    return os.path.join(os.path.dirname(os.path.abspath(db)), "calibration_review.json")


def load_review(path: str | None = None) -> dict:
    path = path or _review_path()
    try:
        with open(path) as f:
            return json.load(f)
    except (FileNotFoundError, ValueError):
        return {}


def save_review(data: dict, path: str | None = None) -> None:
    path = path or _review_path()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            json.dump(data, f, indent=2)
    except OSError as e:
        logger.debug("could not persist calibration review: %s", e)


def evaluate_suggestions(conn: sqlite3.Connection, review: dict | None = None) -> list[dict]:
    """Metrics whose policy suggestion differs materially from the active value
    and hasn't been dismissed at (within differs of) the same value.

    Returns a list of {metric, value, active, reason, confidence}. Pure read —
    does not write anything.
    """
    review = review if review is not None else load_review()
    out = []
    for metric, policy in AGGREGATION_POLICY.items():
        anchor = get_calibration_anchor(conn, metric)
        sug = anchor.suggestion if anchor else None
        if not sug or not sug.get("differs"):
            continue
        # The active value is device-measured (e.g. Garmin's auto-detected LT).
        # Anchor precedence is confirmed > device > policy, so a policy estimate
        # can never displace a device reading — nagging to change it would be
        # self-contradictory. Suppress until the device stops providing the value.
        if CalibrationMethod.resolve(anchor.method).trust_tier == TrustTier.DEVICE:
            continue
        dismissed = review.get(metric)
        if (dismissed and dismissed.get("state") == "dismissed"
                and abs(dismissed.get("value", 1e9) - sug["value"]) < policy["differs"]):
            continue  # already rejected at ~this value; don't re-nag
        out.append({
            "metric": metric,
            "value": sug["value"],
            "active": anchor.value,
            "reason": sug.get("reason"),
            "confidence": sug.get("confidence"),
        })
    return out


def accept_suggestion(conn: sqlite3.Connection, metric: str, path: str | None = None) -> float | None:
    """Confirm the current policy suggestion as the active anchor (sticky)."""
    anchor = get_calibration_anchor(conn, metric)
    sug = anchor.suggestion if anchor else None
    if not sug:
        return None
    add_calibration(conn, metric, sug["value"], "confirmed", "high", date.today())
    review = load_review(path)
    review.pop(metric, None)
    save_review(review, path)
    return sug["value"]


def reject_suggestion(conn: sqlite3.Connection, metric: str, path: str | None = None) -> None:
    """Dismiss the current suggestion; ledger suppresses it until it moves."""
    anchor = get_calibration_anchor(conn, metric)
    sug = anchor.suggestion if anchor else None
    if not sug:
        return
    review = load_review(path)
    review[metric] = {"state": "dismissed", "value": sug["value"],
                      "date": date.today().isoformat()}
    save_review(review, path)
