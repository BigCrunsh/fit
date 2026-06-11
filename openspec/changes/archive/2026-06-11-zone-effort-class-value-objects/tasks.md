## 1. Types (no behaviour change)

- [x] 1.1 Add `EffortClass(Enum)` (Recovery/Easy/Moderate/Hard/Very Hard) and `Zone(IntEnum)` Z1..Z5 to `fit/analysis.py`, with `Zone.parse` (case-insensitive, raises on junk), `Zone.parse_or_none` (None/missing-safe), and a `Zone.effort_class` property backed by one `_ZONE_EFFORT` map.
- [x] 1.2 Unit-test the types: ordering (`Z3 < Z4`), `parse` on valid/lower-case/whitespace, `parse` raises on junk, `parse_or_none(None)` → None, `effort_class` for all five.

## 2. Rewire `compute_effort_class`

- [x] 2.1 Reimplement `analysis.compute_effort_class` on `Zone`/`EffortClass`: `None → None`; valid zone → its `EffortClass.value` string (identical outputs); invalid zone → raises (remove the `{...}.get(zone, "Easy")` fallthrough).
- [x] 2.2 Run the full suite — green (valid-input behaviour unchanged).

## 3. Replace ordering / membership sites

- [x] 3.1 Replace `plan._zone_to_number` (`plan.py:821`) + its caller (`:813`) with `Zone` ordering.
- [x] 3.2 Migrate threshold checks to `Zone.parse(z) >= Zone.Z3`: `plan.py:674`, `analysis.py:233/249/260`, `cards.py:2521/2523`.
- [x] 3.3 Type the run-type→zone *sets* (`plan.py:772–777`, `tempo`/`easy`/… ) as `{Zone…}` — keep set membership semantics, do NOT collapse to an ordering.
- [x] 3.4 Run the full suite — green and classification-identical (treat `test_analysis.py`/`test_plan.py` as the oracle).

## 4. Verification gate (the one behaviour change)

- [x] 4.1 Grep every caller that feeds a zone into `compute_effort_class` / `Zone.parse` and confirm the input is always a `compute_hr_zones` output (`Z1`–`Z5` or `None`) — so the new "reject invalid" raise never fires in normal operation. Any caller that legitimately handles unknown/missing degrades via `parse_or_none`, not a crash.
- [x] 4.2 Confirm no persisted zone string is rewritten and no new migration is added; boundary numbers still come from config.

## 5. Tests (2:1 unhappy:happy)

- [x] 5.1 Happy: each `Zone` → correct `EffortClass`; ordering comparisons; run-type set membership unchanged.
- [x] 5.2 Unhappy/edge: `compute_effort_class` on an invalid zone **raises** (regression for the silent-`"Easy"` bug); `None` → `None`; `parse` rejects junk; lower-case/whitespace parse; a once-`_zone_to_number`-junk→0 input now handled explicitly.
- [x] 5.3 Existing zone / run-type / classification tests stay green; `ruff` clean.
