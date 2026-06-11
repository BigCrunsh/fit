## 1. Types (no behavior change)

- [x] 1.1 Add `TrustTier(IntEnum)` to `fit/calibration.py` with ordering `INFORMATIONAL < REFERENCE < LEGACY < POLICY < DEVICE < CONFIRMED` and an `is_anchor_eligible` property (`>= LEGACY`).
- [x] 1.2 Add `Confidence(IntEnum)` (`LOW < MEDIUM < HIGH`) with `from_str`/`to_str` helpers mapping the stored `'low'/'medium'/'high'` strings.
- [x] 1.3 Add `CalibrationMethod(Enum)` mapping every known stored string → `TrustTier` (per design D3), plus a `resolve(s) -> CalibrationMethod` classmethod that returns a `LEGACY`-tier marker for unknown/None strings (never raises) and a `POLICY` sentinel for the synthesized policy provenance.
- [x] 1.4 Add the frozen `CalibrationAnchor` dataclass (fields per design D1; `value: float` invariant, `inputs`/`suggestion` kept as dict/list; `method`/`confidence` stay display strings — see D1 apply note).
- [x] 1.5 Unit-test the types in isolation: tier ordering, `is_anchor_eligible` (LEGACY eligible; INFORMATIONAL/REFERENCE not), `Confidence` ordering, `CalibrationMethod.resolve` on every known string + on an unknown string + on `None`. *(in `tests/test_typed_calibration_anchor.py`)*

## 2. `CalibrationAnchor | None` return + consumer migration (one commit)

- [ ] 2.1 Change `get_calibration_anchor` to construct and return a `CalibrationAnchor`; replace the `{"value": None, …}` branch (`:399`) with `return None`. Keep the existing `if/elif` precedence control flow for now (D-migration step 2, not yet collapsed).
- [ ] 2.2 Migrate `fit/marathon/features.py:75/85` to `anchor is None` + `anchor.value`.
- [ ] 2.3 Migrate `fit/fitness.py:79/351` to the typed anchor.
- [ ] 2.4 Migrate `fit/report/sections/predictions.py:196` and `fit/report/sections/cards.py:319/324/922/2737` (incl. the diagnostics card reading `inputs`).
- [ ] 2.5 Migrate `mcp/server.py:297/302` (VDOT/Garmin gap); confirm emitted coaching context is unchanged.
- [ ] 2.6 Run the full suite — must be green with the existing scenarios (selection unchanged).

## 3. Typed trust taxonomy (replace string-sets + ranks)

- [x] 3.1 Replace `CONFIRMED_METHODS` / `DEVICE_METHODS` / `REFERENCE_METHODS` / `INFORMATIONAL_METHODS` membership checks with `method.trust_tier` predicates; replace `_CONFIDENCE_RANK` with `Confidence` ordering in `get_active_calibration` / `get_calibration_anchor`. All four module-level sets + the rank dict removed. Also migrated the one external consumer (`cards.py` device-LT nudge-suppression). Control flow unchanged.
- [x] 3.2 Run the full suite — green (1037 passed), selection-identical.
- [~] 3.3 Collapse to `max()` — **NOT taken** (design allowed this). The synthesized POLICY suggestion and the active row carry different payloads (value/confidence/method/src_date) and the returned `inputs` provenance depends on whether the winner was the confirmed active row; a literal `max()` would have to reconstruct that, adding complexity for no behavioural gain. The typed if/elif already expresses precedence via `TrustTier` (the E2 goal) and keeps the string-sets gone. Kept as-is.

## 4. Tests (2:1 unhappy:happy)

- [x] 4.1 Happy: confirmed-beats-device; device-beats-policy (suggestion still carried); informational rows feed the policy; value always a real number.
- [x] 4.2 Unhappy: no rows → `None`; reference-only metric → `None` (not `{value:None}`); unknown legacy method string → LEGACY, no crash; active-row tie broken by recency; consumer `None` paths (`marathon.features._lthr` raises, `_max_hr` returns None).
- [x] 4.3 Regression guard: a junk `method` row loads via `get_calibration_history` and `get_calibration_anchor` without error.
- [x] 4.4 Existing `test_anchor_policy.py` / `test_calibration_governance.py` / `test_calibration_asof.py` migrated to attribute access (values unchanged) and green; full suite 1061 passed.

## 5. Contract & docs

- [x] 5.1 MCP coaching output preserved — `test_coaching_context.py` asserts the exact `Fitness anchor: VDOT 41` and `Fitness anchor: none yet` lines and passes. `.claude/skills/fit-coach/SKILL.md` has no dict-shape coupling → no change needed.
- [x] 5.2 `ruff check fit mcp` adds **no** new errors (the single E702 at `mcp/server.py:584` `_hms` is pre-existing, unrelated); grep confirms no consumer still does `.get("value")`/`["value"]` on an anchor.
- [x] 5.3 PR note: no DB migration, no persisted `method` rewritten (enum maps to existing strings); K3 (`vo2max` metric provenance) deferred; 3.3 `max()` collapse intentionally not taken.
