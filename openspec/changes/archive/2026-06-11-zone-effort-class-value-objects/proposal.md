## Why

The HR zone ladder is the project's central intensity model, yet a zone is a bare string
`"Z1".."Z5"` with its rules scattered: the zone→effort-class map lives in one dict in
`analysis.compute_effort_class`, the ordering ("Z3+ is hard") is re-derived in
`plan._zone_to_number`, and run-type/threshold checks hardcode zone tuples across
`analysis.py`, `plan.py`, and `cards.py`. Worse, invalid zones are **silently swallowed** —
`compute_effort_class("Z9")` returns `"Easy"` (a typo is mislabeled, not caught) and
`_zone_to_number` maps junk to `0`. This is DDD_REVIEW.md item **E3**, the next tactical
chunk after E1+E2.

## What Changes

- **`Zone` value object** (`IntEnum` Z1..Z5) owning zone *identity, ordering, and the
  effort-class mapping*: `Zone.parse(s)` rejects an invalid string instead of degrading;
  ordering is intrinsic (`Zone.Z3` comparisons); an `effort_class` property is the single
  home of the zone→class map. A None-safe helper preserves the existing `None` handling.
- **`EffortClass` enum** — the documented 5 levels (Recovery / Easy / Moderate / Hard /
  Very Hard).
- **`analysis.compute_effort_class`** rewired onto `Zone`/`EffortClass` — **the silent-`"Easy"`
  fallthrough is removed** (invalid zone → rejected, not mislabeled); `None → None` preserved.
- **`plan._zone_to_number`** (and its caller) replaced by `Zone` ordering.
- **Ordering/membership sites** migrated where it adds type-safety: the hard/easy threshold
  checks collapse to `>= Zone.Z3`; the run-type→zone *sets* (e.g. `tempo = {Z3, Z4}`) keep
  set semantics but become typed.
- **The one behaviour change:** an *invalid* zone string is now rejected rather than silently
  mapped to `"Easy"`/`0`. Valid inputs (Z1–Z5, `None`) are unchanged.

**Not in scope:** the ~82 `"Z1".."Z5"` literals that are display/chart labels or config keys;
zone *boundary numbers* (stay in config); other DDD items.

## Capabilities

### New Capabilities
<!-- none -->

### Modified Capabilities
- `fitness-profile`: the HR-zone / effort-class model gains a typed home — zone identity,
  ordering, and the zone→effort-class mapping live in one place, and an unrecognised zone is
  rejected rather than silently classified `Easy`.

## Impact

- **Code:** new `Zone` / `EffortClass` in `fit/analysis.py` (alongside `compute_hr_zones` /
  `compute_effort_class`); `compute_effort_class` rewired; `plan._zone_to_number` + caller
  replaced; ~10 ordering/membership sites in `analysis.py`, `plan.py`, `report/sections/cards.py`
  migrated.
- **No data migration.** `activities.hr_zone` / `hr_zone_lthr` / `hr_zone_maxhr` are persisted
  as `"Z1".."Z5"` text; `Zone` maps to those existing strings — nothing stored is rewritten,
  no new migration. Boundary numbers stay in config (`zones_lthr`, `zones_max_hr_pct`).
- **Behaviour-preserving for valid inputs.** The only change is rejecting invalid zones; must
  confirm no live path feeds one (`hr_zone` is always Z1–Z5 or `None` from `compute_hr_zones`).
- **Tests:** existing zone / run-type / classification tests stay green; new `Zone`/`EffortClass`
  unit tests + the silent-`"Easy"` regression (2:1 unhappy:happy).
