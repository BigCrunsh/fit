## Context

`fit/calibration.py` is the model context for the rest of the app (`DATA_LINEAGE.md §6`), yet its central concept — the calibration anchor — is a bare `dict`, and the trust taxonomy that decides "which source wins" is four module-level string-sets plus a hand-unrolled `if/elif` ladder (`calibration.py:382–400`). Two consequences:

1. `get_calibration_anchor` can return `{"value": None, …}` (`:399`), so ≈9 consumers each re-check `anchor.get("value")`.
2. A new `method` string silently has no trust tier; the precedence is implicit in the ladder's ordering rather than expressed as the total order it is.

This is a **behavior-preserving** refactor (E1+E2 of `DDD_REVIEW.md`). The selection a given database produces today must be identical after the change; only the *types* and the *absence representation* change. The existing scenario tests (`test_calibration_governance.py`, `test_anchor_policy.py`, `test_calibration_asof.py`) are the oracle.

## Goals / Non-Goals

**Goals:**
- Make "anchor with no value" unrepresentable: `CalibrationAnchor` with `value: float`, and `get_calibration_anchor → CalibrationAnchor | None`.
- Express the trust taxonomy as types: `TrustTier`, `Confidence`, `CalibrationMethod` — a method without a tier can't be constructed; an unknown stored method degrades to `LEGACY`.
- Collapse the precedence ladder to a tier-ordered selection while preserving the exact current outcome.
- Keep the MCP coaching context's *output* byte-identical.

**Non-Goals:**
- No deep typing of `suggestion`/`inputs` — they stay a dict / list-of-dicts on the object (bounds blast radius; they're display/audit payloads). Typing them is a later chunk.
- No data migration; no change to which value is selected for existing rows.
- K3 (`vo2max` metric-key provenance), E3–E5, N1–N3, P1–P5 — out of scope.
- No change to aggregation policy, windows, staleness thresholds, or zone/boundary config.

## Decisions

### D1 — `CalibrationAnchor` retains today's fields, adds `metric`/`source_date`, never holds `value=None`
Frozen dataclass:
```python
@dataclass(frozen=True)
class CalibrationAnchor:
    metric: str
    value: float                 # invariant: a real number (never None)
    confidence: str | None       # 'high'/'medium'/'low' — display string, as today
    method: str                  # resolved method string, e.g. 'confirmed'/'device_lt'/'policy'
    source_date: str | None      # ISO date of the source effort (drives staleness)
    stale: bool | None
    inputs: list[dict]           # contributing rows (kept as dicts — display/audit)
    suggestion: dict | None      # policy estimate {value, confidence, reason, inputs, differs}
```
Keeping `inputs`/`suggestion` as-is preserves the diagnostics card and the sync accept/reject flow without touching them. The previous `{"value": None, …}` branch becomes `return None`.

**Public fields stay string-valued (revised during apply).** The draft typed `method`/`confidence` as enums. But `cards.py:182–185` passes `anchor.confidence` straight into the dashboard payload and derives a display label from `anchor.method` (`"confirmed" if method in ("manual","confirmed")`), and `cards.py:761` compares `method == "device_vo2max"` — so enum-typing the *public* fields would change the dashboard/MCP serialization, the very contract we must preserve. Resolution: the **enums (`TrustTier`/`Confidence`/`CalibrationMethod`) are internal to selection** (E2's win — typed precedence, no untiered method, graceful legacy); the anchor's *public* `method`/`confidence` remain the same strings the dict exposed. Migration is then purely `anchor.get("x")` → `anchor.x` + `is None` handling, with zero semantic change at display/emit sites. Deeper public typing is a later refinement, not E1+E2.

*Alternative considered:* drop `inputs` (the DDD sketch did). Rejected — `cards.py` reads it; dropping it widens the change for no correctness gain.

### D2 — `TrustTier` ordering preserves the legacy last-resort fallback
```python
class TrustTier(IntEnum):
    INFORMATIONAL = 0   # race_observation, effort_observation — history/chart, never an anchor
    REFERENCE     = 1   # device_vo2max — context only, never an anchor/estimator input
    LEGACY        = 2   # unrecognised / un-tiered active row — last-resort fallback
    POLICY        = 3   # windowed policy estimate (what races imply)
    DEVICE        = 4   # device_lt — instrument measurement
    CONFIRMED     = 5   # manual, confirmed — human-owned, sticky
```
`is_anchor_eligible = tier >= LEGACY` (i.e. excludes only `INFORMATIONAL`/`REFERENCE`). This is the one place the review's sketch (`is_anchor_eligible = tier >= POLICY`) was **wrong**: the current code (`:393`) selects a legacy active row as a last resort, so dropping it would be a behavior change. We keep it. Precedence among eligible candidates = `max(key=(tier, source_date))`, which reproduces `confirmed > device > policy > legacy`.

### D3 — `CalibrationMethod` maps every known string to a tier; unknown → `LEGACY` via a lookup, not the constructor
```python
class CalibrationMethod(Enum):
    MANUAL             = ("manual",             TrustTier.CONFIRMED)
    CONFIRMED          = ("confirmed",          TrustTier.CONFIRMED)
    DEVICE_LT          = ("device_lt",          TrustTier.DEVICE)
    DEVICE_VO2MAX      = ("device_vo2max",      TrustTier.REFERENCE)
    RACE_OBSERVATION   = ("race_observation",   TrustTier.INFORMATIONAL)
    EFFORT_OBSERVATION = ("effort_observation", TrustTier.INFORMATIONAL)
    RACE_CANDIDATE     = ("race_candidate",     TrustTier.LEGACY)   # auto-derived observation; feeds the estimator
    ACTIVITY_MAX       = ("activity_max",       TrustTier.LEGACY)
    DRIFT_TEST         = ("drift_test",         TrustTier.LEGACY)
    SCALE              = ("scale",              TrustTier.LEGACY)
```
- A `classmethod resolve(s) -> CalibrationMethod | None` maps a stored string to a member, returning a sentinel `LEGACY` method (or `None` handled as legacy) for anything unrecognised — so historical/garbage rows never crash.
- **`POLICY` is not a stored method.** It is the tier of the *synthesized* windowed-suggestion candidate only; the `"policy"` provenance label (`:392`) is its marker. No stored `method` string maps to `POLICY`.
- **Auto-derived candidate methods (`race_candidate`/`activity_max`/`drift_test`/`scale`) are `LEGACY`, not `POLICY`** — confirmed against the code and tests (resolves the prior open question). They are *observation* rows: their **values** feed the windowed estimator and surface through the synthesized `POLICY` suggestion, but the **row itself**, when it is the active row, is only ever selected at the legacy level. The precedence ladder makes the suggestion (`:390`) outrank the legacy active row (`:393`), and `test_anchor_policy.py` pins both halves: `test_maxhr_max_family_365d_window` (a `race_candidate`/`activity_max` pair produces the *suggestion*, value 192) and `test_metric_without_policy_uses_legacy_selection` (a `scale` row on the policy-less `weight` metric is taken via the legacy single-row path). Mapping them to `POLICY` would let a fresh candidate active row tie-break *over* the suggestion — a behavior change. `LEGACY` reproduces today's selection exactly.

### D4 — Two separate concerns kept separate
- **Observation eligibility** (rows fed to the estimator): unchanged filter — exclude `REFERENCE` and `DEVICE` methods.
- **Active-value precedence**: the tier order above.
These are orthogonal today and stay orthogonal; the enum just gives each a typed predicate (`method.trust_tier`) instead of set membership.

### D5 — Consumer migration is mechanical and uniform
Each site `anchor.get("value")` / `anchor and anchor.get("value") is not None` → `anchor is not None` + `anchor.value`. The `{value:None}` "degraded anchor" callers (`cards.py:319/922`, `mcp/server.py:297`) collapse to an `is None` branch. `get_calibration_status` and `get_calibration_history` (which read raw rows, not the anchor) are untouched.

### D6 — MCP / coaching contract
`mcp/server.py` (`get_coaching_context`, the VDOT/Garmin gap at `:302`) reads `anchor["value"]`. After migration it reads `anchor.value`; the *emitted* coaching context must be unchanged. Verify against `tests/` and a manual `get_coaching_context` diff. Expectation: `SKILL.md` needs **no** change (it documents semantics, not the dict shape) — to be confirmed and stated in the PR.

## Risks / Trade-offs

- **[Subtle selection drift from collapsing the ladder to `max()`]** → Implement the enum-backed predicates first while keeping the existing `if/elif` control flow, run the full suite green, *then* collapse to `max(key=(tier, source_date))` and re-run. Only keep the collapse if selection is identical on the existing scenarios. The legacy-fallback tier (D2) is the highest-risk spot.
- **[A candidate-method tier regresses selection]** → tiers are pinned to `LEGACY` per D3 (resolved against the suite); `test_anchor_policy.py` exercises VDOT/LTHR/AeT/weight selection with these rows, so any mis-tier shows as a red test. Treat the suite as the spec.
- **[Unknown method string in old DBs]** → `resolve()` returns LEGACY rather than raising; add a regression test with a junk method string.
- **[Return-type break reaches an unmigrated consumer]** → grep-driven migration list (9 sites) + `mypy`/ruff and the report/MCP tests catch stragglers; the type change is loud, not silent.

## Migration Plan

1. Add the three enums + `CalibrationAnchor` (no behavior change yet; `get_calibration_anchor` still returns a dict).
2. Switch `get_calibration_anchor` to return `CalibrationAnchor | None`; migrate the 9 consumers in the same commit; suite green.
3. Replace the `*_METHODS` sets + `_CONFIDENCE_RANK` with enum-backed predicates, control flow unchanged; suite green.
4. Collapse the precedence ladder to the tier-ordered selection; suite green and selection-identical, else revert step 4 only.
5. Verify MCP coaching context output unchanged. No DB migration. Rollback = revert the branch (no persisted state touched).

## Open Questions

- ~~Auto-derived candidate method tiers~~ — **resolved** (D3): they are `LEGACY`, confirmed against `test_anchor_policy.py`.
- How should `anchor.method` type the synthesized policy suggestion — a `POLICY`-tier sentinel member so `anchor.method` is always a `CalibrationMethod`, or keep a plain `"policy"` string marker on a `method=None` object? Leaning: sentinel member, for a uniformly-typed `method`. Resolve during step 3.3.
