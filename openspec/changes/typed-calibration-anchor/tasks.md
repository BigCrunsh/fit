## 1. Types (no behavior change)

- [ ] 1.1 Add `TrustTier(IntEnum)` to `fit/calibration.py` with ordering `INFORMATIONAL < REFERENCE < LEGACY < POLICY < DEVICE < CONFIRMED` and an `is_anchor_eligible` property (`>= LEGACY`).
- [ ] 1.2 Add `Confidence(IntEnum)` (`LOW < MEDIUM < HIGH`) with `from_str`/`to_str` helpers mapping the stored `'low'/'medium'/'high'` strings.
- [ ] 1.3 Add `CalibrationMethod(Enum)` mapping every known stored string → `TrustTier` (per design D3), plus a `resolve(s) -> CalibrationMethod` classmethod that returns a `LEGACY`-tier marker for unknown/None strings (never raises) and a `POLICY` sentinel for the synthesized policy provenance.
- [ ] 1.4 Add the frozen `CalibrationAnchor` dataclass (fields per design D1; `value: float` invariant, `inputs`/`suggestion` kept as dict/list).
- [ ] 1.5 Unit-test the types in isolation: tier ordering, `is_anchor_eligible` (LEGACY eligible; INFORMATIONAL/REFERENCE not), `Confidence` ordering, `CalibrationMethod.resolve` on every known string + on an unknown string + on `None`.

## 2. `CalibrationAnchor | None` return + consumer migration (one commit)

- [ ] 2.1 Change `get_calibration_anchor` to construct and return a `CalibrationAnchor`; replace the `{"value": None, …}` branch (`:399`) with `return None`. Keep the existing `if/elif` precedence control flow for now (D-migration step 2, not yet collapsed).
- [ ] 2.2 Migrate `fit/marathon/features.py:75/85` to `anchor is None` + `anchor.value`.
- [ ] 2.3 Migrate `fit/fitness.py:79/351` to the typed anchor.
- [ ] 2.4 Migrate `fit/report/sections/predictions.py:196` and `fit/report/sections/cards.py:319/324/922/2737` (incl. the diagnostics card reading `inputs`).
- [ ] 2.5 Migrate `mcp/server.py:297/302` (VDOT/Garmin gap); confirm emitted coaching context is unchanged.
- [ ] 2.6 Run the full suite — must be green with the existing scenarios (selection unchanged).

## 3. Typed trust taxonomy (replace string-sets + ranks)

- [ ] 3.1 Replace `CONFIRMED_METHODS` / `DEVICE_METHODS` / `REFERENCE_METHODS` / `INFORMATIONAL_METHODS` membership checks with `method.trust_tier` predicates; replace `_CONFIDENCE_RANK` with `Confidence` ordering in `get_active_calibration` / `derive_confidence`. Control flow unchanged.
- [ ] 3.2 Run the full suite — green and selection-identical.
- [ ] 3.3 Collapse the precedence ladder (`:382–400`) to `max(eligible_candidates, key=lambda a: (a.method.trust_tier, a.source_date))` with the synthesized POLICY suggestion as a candidate. Run the suite; **keep only if selection is identical** on `test_anchor_policy.py` / `test_calibration_governance.py` / `test_calibration_asof.py`, else retain step 3.1's explicit flow and note why in the PR.

## 4. Tests (2:1 unhappy:happy)

- [ ] 4.1 Happy: confirmed-beats-device; device-beats-policy; suggestion/inputs/stale preserved on the object.
- [ ] 4.2 Unhappy: no anchor-eligible value → `None` (not `{value:None}`); reference/informational-only metric → `None`; unknown legacy method string → LEGACY, no crash; precedence tie broken by `source_date`; a previously-`{value:None}` consumer path now takes the `is None` branch.
- [ ] 4.3 Regression guard: a junk/legacy `method` row loads via `get_calibration_history` and `get_calibration_anchor` without error.
- [ ] 4.4 Confirm `test_calibration_governance.py`, `test_anchor_policy.py`, `test_calibration_asof.py` unchanged and green.

## 5. Contract & docs

- [ ] 5.1 Verify MCP coaching context output is byte-identical (diff `get_coaching_context` before/after on a fixture DB); confirm `.claude/skills/fit-coach/SKILL.md` needs no change, or update it.
- [ ] 5.2 Run `ruff` + type check; ensure no consumer still calls `.get("value")` on an anchor (grep clean).
- [ ] 5.3 Note in the PR: no DB migration, no persisted value rewritten; K3 deferred.
