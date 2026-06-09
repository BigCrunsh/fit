# Domain-Driven Design Review — `fit`

A tactical-DDD pass over the `fit/` package: ubiquitous language, naming, and
encapsulation. Each finding gives the location (`file:line`), what's wrong, **why it
matters for the domain model** (not generic clean-code), and a before/after sketch.

This is a **proposal** — no code changed. It builds on the strategic DDD work already
in the repo (the `DATA_LINEAGE.md §6` glossary, the documented bounded contexts, and
the vocabulary-correcting migration `016_calibration_method_rename.sql`).

---

## Headline

The **strategic** model is in good shape — there's a written glossary, explicit
bounded contexts, one real value object (`EffortDataset`), and a migration that renamed
storage strings to match the ubiquitous language. The gap is one layer down, in the
**tactical** model: outside `fit/marathon/`, essentially every domain concept is a
`sqlite3.Row` → `dict`. Behaviour lives in module-level functions, invariants are
enforced at call sites, and several of the most important value-bearing fields can hold
**illegal values** — an "anchor" with `value=None`, a zone that's an arbitrary string, a
phase status that's a free-text column.

`EffortDataset` (`fit/marathon/features.py:56`) is the pattern to extend. The point is
not "wrap everything in a class" — it's to introduce types at the **few** places where
their absence is actively costing correctness. Five changes, ordered by impact:

| # | Change | Kind | Impact |
|---|--------|------|--------|
| 1 | `CalibrationAnchor` value object — make "anchor with no value" unrepresentable | Encapsulation | **High** |
| 2 | Method trust tiers as a `CalibrationMethod` enum, not four string-sets | Naming + Encapsulation | **High** |
| 3 | `Zone` / `EffortClass` value objects — one home for the zone ladder | Encapsulation | **High** |
| 4 | `TrainingPhase` aggregate — own the lifecycle, compliance, and "one active" invariant | Encapsulation | **Med-High** |
| 5 | `Activity` — stop mutating a dict in place (stage it; biggest lift) | Encapsulation | **Highest value, largest lift** |
| — | Naming + polish (below) | Naming | Low–Med |

Items 1–3 are high-leverage **and** low-blast-radius (calibration + the zone model). Item
4 is a clean aggregate refactor. Item 5 is real but should be staged, not done in one pass.

---

## 1. Ubiquitous language in use

Inferred from class/function/variable names, comments, the schema, and the glossary.
Load-bearing concepts:

- **Entities** (identity + lifecycle): `Activity` (the central one), `TrainingPhase`,
  `Goal`/`Objective`, `Race` (`race_calendar` row), `Calibration` row.
- **Value objects / candidates**: `CalibrationAnchor`, `Zone` (Z1–Z5), `EffortClass`
  (Recovery…Very Hard), `Confidence` (high/med/low), `RunType`, `EffortDataset` ✅
  (already done), `Forecast` (median + interval + P(goal)), weekly aggregate, and the
  recurring `{type, message, date, previous_value, new_value}` change-record.
- **Domain primitives**: `training_load`, `chronic_load`, `acute_load`, `ACWR`,
  `monotony`, `strain`, `sRPE`, `VDOT` vs `Garmin VO2max`, `LTHR`/`MaxHR`/`AeT`,
  `Resilience` (decoupling onset) vs `Pace-fade`, `speed_per_bpm`.

### Where one concept wears two names (or one name covers two concepts)

1. **`Goal` vs `Objective`** — table `goals`, module `goals.py`, but `derive_objectives()`
   (`fitness.py:624`), `compute_achievability(objectives)`, and the UI all say *objective*.
   The storage/UI split is intentional (CLAUDE.md), but the **Python domain layer**
   straddles both. → **N1**.
2. **`readiness` is three concepts** — Garmin's measured `training_readiness`,
   `evaluate_phase_readiness()` (phase advancement), and `get_readiness_recommendation()`
   (today's go/no-go). Same word, three referents. → **N2**.
3. **`inverse_vdot()` ≡ `compute_vdot_from_race()`** — the docstring admits "This is
   simply compute_vdot_from_race" (`fitness.py:356`; glossary D15). → **N3**.
4. **`vo2max` the column = Garmin VO2max**, but the name drops "Garmin." The glossary is
   emphatic that Garmin VO2max ≠ VDOT and is reference-only — yet `milestones.py:64`
   surfaces a "VO2max peak" headline straight from it. → **N4**.
5. **`checkins.rpe` vs `activities.rpe`** — the view aliases them `daily_rpe`/`activity_rpe`,
   but RPE's SSOT is now `activities.rpe` (Garmin) and is no longer collected via checkin
   (CLAUDE.md). `checkins.rpe` is a stale second home. → **P4**.

---

## 2. NAMING

### N1 — `Goal` vs `Objective` in the domain layer · *medium*
**Location:** `fit/goals.py` (whole module), `fit/fitness.py:624 derive_objectives`,
`:794 compute_achievability`.
**What's wrong:** The storage/UI split (DB `goals`, UI "objectives") is fine, but the
*domain code* uses both interchangeably for the same concept. `goals.py` simultaneously
manages Goals, Phases, **and** Races, while the derived thing is called an Objective
elsewhere.
**Why it matters for the model:** When the ubiquitous term is "objective" (the athlete's
and UI's word), the domain layer should speak it. Keep `goals` purely as a persistence
name and name the *concept* `Objective` everywhere in code — that removes a synonym pair
from the model's core. `goals.py` is also three aggregates in one module.

```
# before:  goals.py owns Goal + Phase + Race;  fitness.py derives "objectives"
# after:   Objective (domain) ←→ goals (table); split planning/{objective,phase,race}.py
```

### N2 — `readiness` overloaded across three concepts · *medium*
**Location:** `daily_health.training_readiness` (schema), `periodization.py:189
evaluate_phase_readiness`, `plan.py:846 get_readiness_recommendation`.
**Why it matters:** In a coaching domain these are genuinely different decisions a user
reasons about separately; one word makes the model ambiguous in code and conversation.
**Recommendation:** reserve **`readiness`** for the measured Garmin metric. Rename:
`evaluate_phase_readiness → assess_phase_advancement`;
`get_readiness_recommendation → recommend_today_session` (or `daily_training_gate`).

### N3 — `inverse_vdot` redundant alias · *low (free)*
**Location:** `fit/fitness.py:356`. Pure pass-through to `compute_vdot_from_race`;
"inverse of what?" reveals nothing. Delete it (inline the few call sites), or — if the
intent "VDOT required for a target" is worth a name — call it
`required_vdot_for_target(target_time, distance)`. Either way, kill the synonym.

### N4 — `vo2max` column hides its provenance · *low–medium*
**Location:** `activities.vo2max`, `_get_garmin_vo2max`, `milestones.py:64`.
The column *is* Garmin VO2max, but the name omits it — and the SSOT contract says this
value must never be a headline, yet `detect_milestones` emits a "VO2max peak" achievement
from it. Renaming the column is expensive, so: (a) document it
(`vo2max -- Garmin device estimate (reference-only; NOT VDOT)`), and (b) drop or relabel
the VO2max-peak milestone, which contradicts the contract.

---

## 3. ENCAPSULATION

Root cause is recurring: **anemic models**. `enrich_activity` (`analysis.py:270`) mutates
a caller's `dict` in place and returns it; every "entity" is a `dict(row)`; invariants
live in the functions that read the dicts, not on the things themselves.

### E1 — `CalibrationAnchor`: make "anchor with no value" unrepresentable · *highest impact*
**Location:** `fit/calibration.py:308 get_calibration_anchor`; consumers in
`features.py:70-85`, `fitness.py`, `report/`, MCP.
**What's wrong:** The calibration anchor is "the single canonical value per metric" — the
most important domain concept — but it's a bare dict, and one branch returns an *anchor
with no value*:

```python
# calibration.py:399 — a "CalibrationAnchor" that has no value
return {"value": None, "confidence": None, "method": None, "stale": True,
        "inputs": [], "suggestion": suggestion}
```

So every consumer re-derives the invariant the anchor should guarantee:

```python
# features.py:75 — repeated everywhere an anchor is read
anchor = get_calibration_anchor(conn, "lthr")
if not anchor or not anchor.get("value"):
    raise ValueError("no LTHR calibration anchor — marathon forecast cannot run")
lthr = float(anchor["value"])
```

**Why it matters for the model:** an "anchor" is *by definition* a known, trusted value.
`{value: None}` is a contradiction in the ubiquitous language — a non-anchor masquerading
as one. Because it's expressible, the "is there actually an anchor?" decision is
duplicated across `marathon/`, `fitness.py`, `report/`, and the MCP server — four places
that can drift (the CLAUDE.md SSOT-contract note exists because they have).

```python
@dataclass(frozen=True)
class CalibrationAnchor:
    metric: str
    value: float                  # invariant: always a real number
    method: CalibrationMethod     # see E2
    confidence: Confidence        # see E2
    source_date: date
    stale: bool
    suggestion: Suggestion | None

def get_calibration_anchor(conn, metric) -> CalibrationAnchor | None:
    if no_usable_row:
        return None               # ← was {"value": None, ...}
    return CalibrationAnchor(metric, value, method, confidence, src_date, stale, suggestion)

# consumer collapses to one honest line:
anchor = get_calibration_anchor(conn, "lthr")
if anchor is None:
    raise ValueError("no LTHR calibration anchor — forecast degrades to the anchor headline")
lthr = anchor.value               # guaranteed float
```

A *domain service* returning a *value object*. Migrate consumers incrementally behind the
same function name.

### E2 — Trust tier as a `CalibrationMethod` enum, not four parallel string-sets · *high*
**Location:** `calibration.py:144-253` — `_CONFIDENCE_RANK`, `INFORMATIONAL_METHODS`,
`CONFIRMED_METHODS`, `REFERENCE_METHODS`, `DEVICE_METHODS`, and the precedence ladder at
`:382-400`.
**What's wrong:** the glossary defines a four-tier trust taxonomy
(CONFIRMED > DEVICE > REFERENCE > INFORMATIONAL) — a real domain concept. In code it's a
raw `method` string plus four module-level sets, with the precedence hand-unrolled:

```python
confirmed = active if (active and active.get("method") in CONFIRMED_METHODS) else None
device    = active if (not confirmed and active and active.get("method") in DEVICE_METHODS) else None
if confirmed:   value, ... = confirmed[...]
elif device:    value, ... = device[...]
elif suggestion is not None: ...
elif active and (active.get("method") or "") not in REFERENCE_METHODS: ...
```

`Confidence` has the same smell — a string ordered by a separate `_CONFIDENCE_RANK` dict.
**Why it matters for the model:** "which source wins" *is* the calibration domain.
Tier-as-set-membership scattered across the module means a new method string can be added
without a tier (silently defaulting), and the precedence rule isn't expressed as the
ordering it is. Migration 016 renamed the strings; giving them a *type* completes it.

```python
class TrustTier(IntEnum):                      # ordering IS the precedence
    LEGACY = 0; INFORMATIONAL = 1; REFERENCE = 2; POLICY = 3; DEVICE = 4; CONFIRMED = 5

class Confidence(IntEnum):                      # replaces _CONFIDENCE_RANK
    LOW = 0; MEDIUM = 1; HIGH = 2

class CalibrationMethod(Enum):
    MANUAL         = ("manual",           TrustTier.CONFIRMED)
    DEVICE_LT      = ("device_lt",        TrustTier.DEVICE)
    DEVICE_VO2MAX  = ("device_vo2max",    TrustTier.REFERENCE)
    RACE_CANDIDATE = ("race_candidate",   TrustTier.POLICY)
    RACE_OBS       = ("race_observation", TrustTier.INFORMATIONAL)
    # ...
    @property
    def trust_tier(self) -> TrustTier: return self.value[1]
    @property
    def is_anchor_eligible(self) -> bool: return self.trust_tier >= TrustTier.POLICY

# precedence ladder collapses to its real meaning:
best = max((a for a in candidates if a.method.is_anchor_eligible),
           key=lambda a: (a.method.trust_tier, a.source_date), default=None)
```

A new method *must* declare a tier or it won't construct — the "untiered method" state
is gone.

### E3 — `Zone` / `EffortClass` value objects · *high*
**Location:** zone strings `"Z1".."Z5"` everywhere; `analysis.py:165 compute_effort_class`
(zone→class map); `plan.py:821 _zone_to_number` (re-parses `"Z3"→3`); hardcoded
`("Z3","Z4","Z5")` tuples at `plan.py:674, 766-777`.
**What's wrong:** Zone is a primitive string with rich, duplicated rules attached from
outside: the 5-zone↔5-effort-class map lives in one dict in `analysis.py`, the ordering
("Z3+ is hard") is re-derived in `plan.py`, and a typo'd zone string is silently valid.
**Why it matters for the model:** the zone ladder *is* the project's central intensity
model (first thing in CLAUDE.md). Splitting "what zones exist / how they order / which
effort class each maps to" across modules means a zone-model change must be chased through
all of them. `compute_effort_class` also hides a quiet bug: an unknown zone falls through
to `"Easy"` (`:175`), so a bad string is mislabeled easy rather than rejected.

```python
class Zone(IntEnum):                           # ordering is intrinsic
    Z1 = 1; Z2 = 2; Z3 = 3; Z4 = 4; Z5 = 5
    @classmethod
    def parse(cls, s: str) -> "Zone": return cls[s.strip()]   # "Z3" -> Zone.Z3, raises on junk
    @property
    def effort_class(self) -> "EffortClass":   # the one mapping, owned here
        return _ZONE_EFFORT[self]

class EffortClass(Enum):
    RECOVERY="Recovery"; EASY="Easy"; MODERATE="Moderate"; HARD="Hard"; VERY_HARD="Very Hard"

# plan.py before:   if _zone_to_number(zone) >= 3:  ...  zone in ("Z3","Z4","Z5")
# plan.py after:    if Zone.parse(zone) >= Zone.Z3:
# analysis.py before:  compute_effort_class("Z9") -> "Easy"   (silent)
# analysis.py after:   Zone.parse("Z9")           -> KeyError (illegal state caught)
```

Boundary *numbers* still come from config (CLAUDE.md) — this only centralizes zone
*identity, ordering, and effort-class mapping*, which are domain rules, not config.

### E4 — `TrainingPhase` aggregate: lifecycle + compliance + "one active" invariant · *med-high*
**Location:** `goals.py:25 complete_phase`, `:41 revise_phase`, `:211 get_phase_compliance`;
`periodization.py:155 advance_phase_status`.
**What's wrong, three ways:**
1. **Status is a free-text column** (`'planned'/'active'/'completed'/'revised'`) compared
   with string literals across `goals.py` and `periodization.py`. No enum, no guarded
   transitions.
2. **"Exactly one active phase" is an unprotected invariant.** `revise_phase` inserts a
   new `status='active'` row; nothing stops two phases being active, and
   `complete_phase`/`advance_phase_status` each poke status independently.
3. **Compliance behaviour lives outside the phase** — `get_phase_compliance` reaches into
   `weekly_agg`, averages, and applies the on-track rule, including a magic `* 0.9`
   tolerance, emitting stringly-typed dicts:

```python
# goals.py:240 — the on-track rule for a phase lives in a free function, not on the phase
"on_track": actual >= phase["z12_pct_target"] * 0.9 if actual else False,
```

**Why it matters for the model:** a training phase has a real lifecycle
(planned→active→completed, or →revised) with an aggregate invariant (one active at a time)
that the *phase aggregate* should guarantee — today it's enforced by whichever function
writes status last. And "am I complying with this phase?" is the phase's own question; the
`0.9` fudge and the dimensions are phase policy currently homeless in a query function, so
periodization, plan-adherence, and the dashboard each risk their own "on track" copy.

```python
class PhaseStatus(Enum):
    PLANNED="planned"; ACTIVE="active"; COMPLETED="completed"; REVISED="revised"

@dataclass
class TrainingPhase:                 # aggregate root
    id: int; goal_id: int; name: str; status: PhaseStatus
    targets: PhaseTargets            # value object (z12_pct, weekly_km range, run_freq, acwr_range)
    def revise(self, new_targets, reason) -> "TrainingPhase": ...        # factory: same goal/name
    def compliance(self, recent_weeks: list[WeeklyAggregate]) -> list[ComplianceDimension]:
        ...                          # the 0.9 tolerance + dimension rules live HERE

class PhaseRepository:
    def activate(self, phase_id):    # the invariant, in ONE transaction
        ...                          # deactivate any other ACTIVE phase, then set this one
```

`ComplianceDimension` (name, target, actual, on_track) becomes a shared value object
instead of an ad-hoc dict re-shaped in several builders.

### E5 — `Activity`: stop mutating a dict in place · *highest value, largest lift — stage it*
**Location:** `analysis.py:270 enrich_activity` and its derivers (`classify_run_type`,
`compute_speed_per_bpm*`, `compute_effort_class`).
**What's wrong:** the platform's central entity is a bare dict, and enrichment is
*side-effecting*:

```python
def enrich_activity(activity: dict, ...) -> dict:
    activity.update(zones)                 # mutates the caller's dict
    activity["speed_per_bpm"] = spb        # ...in place
    activity["run_type"] = ...             # returns the same object it mutated
    return activity
```

All knowledge about an Activity (zone, effort class, efficiency, type) lives in
`analysis.py`, not with the Activity. The race-tag-preservation guard at `:307-316` is
exactly the kind of invariant ("re-enrichment must not clobber a race tag") that belongs
*on the entity*, not in a free function callers must remember to route through.
**Why it matters:** textbook anemic model — and the in-place mutation silently alters a
caller's input, the class of thing that makes the documented `recompute --force`
race-wipe bug (`:307`) possible in the first place.
**Recommendation — staged, because it touches sync/report/MCP:**
- **(a)** make `enrich_activity` *non-mutating* — build and return a new dict (or an
  `EnrichedActivity` value object). Pure, testable, no caller surprises.
- **(b)** move the rules that already carry invariants (zone→effort-class via E3, the
  race-tag guard) onto an `Activity`/`EnrichedActivity` type, so "an enriched activity
  always has a valid zone and a non-clobbered race tag" is guaranteed by construction.

The only recommendation **not** to attempt in one pass — highest value, but incremental.

---

## 4. Polish — lower value, do when nearby

- **P1 — Shared `ChangeRecord` value object.** The exact
  `{type, message, date, previous_value, new_value}` shape recurs in `milestones.py:37`,
  `goal_log` events (`goals.py:83`), and `alerts.py` (`{type, message, data_context}`).
  One value object (with a typed `EventType` enum) unifies three near-identical shapes.
- **P2 — Categorical check-in fields are stringly-typed.** `hydration` (Low/OK/Good),
  `legs` (Heavy/OK/Fresh), `energy`, `eating`, `sleep_quality` — small ordered enums;
  today any string is a valid column value.
- **P3 — `Race.status` / `Goal.active` / alert severity** are the same magic-string story
  as PhaseStatus (E4) at lower stakes — fold into enums when touching `race_calendar`/`goals`.
- **P4 — Retire `checkins.rpe`.** A second home for a concept whose SSOT is now
  `activities.rpe`; the `daily_rpe` view alias keeps it alive. Confirm unused, then drop
  (schema change — confirm before removing data).
- **P5 — `data_health.py` vs `fit doctor`.** The module behind the `doctor` command is
  named `data_health` ("data" = the generic-noun smell). `pipeline_health` or
  `integrity_check` matches the command's intent and the ubiquitous language.

---

## Net

The strategic model is already strong; the wins are tactical and concentrate in the
**calibration** context (E1+E2 — the most important concept is the least typed) and the
**intensity/zone** model (E3). Those three are high-leverage and low-blast-radius. E4 is a
clean aggregate refactor. E5 is the big one — real, but stage it.

Suggested first change: **E1+E2 together** (the `CalibrationAnchor` value object plus the
`CalibrationMethod`/`Confidence` enums), as a single OpenSpec change with the consumer
migration list and tests.
