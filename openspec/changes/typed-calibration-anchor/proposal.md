## Why

The calibration anchor is the most important concept in the physio-calibration context — "the single canonical **value** per metric" (`DATA_LINEAGE.md §6`) — yet it is the least typed. `get_calibration_anchor()` returns a bare `dict` whose `value` can be `None` (`calibration.py:399`), so an "anchor with no value" — a contradiction in the ubiquitous language — is expressible. Every consumer therefore re-derives the "is there actually an anchor?" check (≈9 sites across `marathon/`, `fitness.py`, `report/`, `mcp/`), the exact duplication the SSOT contract was meant to prevent. Alongside it, the trust taxonomy (`CONFIRMED > DEVICE > POLICY > LEGACY`) — a real domain concept — lives as four parallel string-sets plus a hand-unrolled precedence ladder, where a new method string silently defaults to no tier.

This is the first implementation chunk of the merged DDD review (`DDD_REVIEW.md`, items **E1 + E2** — the review's own top pick: high-leverage, low-blast-radius). It introduces types only where their absence costs correctness; it does not "wrap everything in a class."

## What Changes

- **E1 — `CalibrationAnchor` value object.** Add a frozen dataclass `CalibrationAnchor(metric, value, method, confidence, source_date, stale, suggestion)` with the invariant `value` is always a real number. `get_calibration_anchor()` returns `CalibrationAnchor | None` — **absence is `None`**, replacing the `{"value": None, …}` payload. The `suggestion` (policy estimate + `differs`/`reason`/`inputs`) is retained on the object.
  - **BREAKING (internal API):** the return type changes from `dict` to `CalibrationAnchor | None`. ≈9 consumer sites migrate from `anchor.get("value")` re-checks to `anchor is None` + `anchor.value`.
- **E2 — typed trust taxonomy.** Replace the four `*_METHODS` string-sets, the `_CONFIDENCE_RANK` dict, and the manual precedence ladder (`calibration.py:382–400`) with:
  - `TrustTier(IntEnum)` where ordering **is** the precedence (`LEGACY < INFORMATIONAL < REFERENCE < POLICY < DEVICE < CONFIRMED`);
  - `Confidence(IntEnum)` (`LOW < MEDIUM < HIGH`), replacing `_CONFIDENCE_RANK`;
  - `CalibrationMethod(Enum)` mapping each **existing** stored method string to a `TrustTier`, with an `is_anchor_eligible` property.
  - Precedence collapses to `max(candidates, key=lambda a: (a.method.trust_tier, a.source_date))`. A new method *must* declare a tier or fail to construct.
- **Graceful legacy handling (non-breaking):** an unknown/legacy stored `method` string resolves to `TrustTier.LEGACY` rather than raising — historical rows must keep loading.
- **Resolved as a side effect:** Appendix A's `active` 3-way homonym (the anchor value is now a distinct typed thing) and the `fitness anchor` synonym/homonym (K1/K2).

**Not in scope:** K3 (the `vo2max` *metric* key dropping its Garmin provenance) — doc-only and persisted, deferred. E3–E5, N1–N3, P1–P5 — later chunks.

## Capabilities

### New Capabilities
<!-- none -->

### Modified Capabilities
- `fitness-profile`: the "single standardizing anchor layer" requirement is refined — `get_calibration_anchor` returns a typed `CalibrationAnchor` whose `value` is guaranteed present, or `None` when no anchor exists (no valueless-anchor payload); trust precedence is expressed as a typed, totally-ordered tier rather than ad-hoc set membership; an unrecognised stored method degrades to the lowest tier instead of having no tier.

## Impact

- **Code (calibration core):** `fit/calibration.py` — new value object + enums; `get_calibration_anchor`, `get_active_calibration`, `derive_confidence`, and the precedence ladder rewired onto the types.
- **Consumers migrated to `CalibrationAnchor | None`:** `fit/marathon/features.py` (75/85), `fit/fitness.py` (79/351), `fit/report/sections/predictions.py` (196), `fit/report/sections/cards.py` (319/324/922/2737), `mcp/server.py` (297/302).
- **MCP / coaching contract (CLAUDE.md SSOT):** `mcp/server.py` (`get_coaching_context` et al.) reads the anchor; `.claude/skills/fit-coach/SKILL.md` consumes the same anchors. The return-type change is internal-only and must keep the coaching context's *output* identical — verify and update if needed; flag whether `SKILL.md` requires a touch (expected: no).
- **No data migration.** `calibration.method` strings are persisted and were already renamed by migration 016. The `CalibrationMethod` enum maps to those existing strings; no stored value is rewritten and no new migration is added. Numeric zone/boundary config is untouched — this types identity, ordering, and precedence only.
- **Tests:** `tests/test_calibration_governance.py`, `tests/test_anchor_policy.py`, `tests/test_calibration_asof.py` must stay green; new typed-anchor + enum tests added (2:1 unhappy:happy).
