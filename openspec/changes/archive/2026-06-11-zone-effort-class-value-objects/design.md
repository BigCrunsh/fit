## Context

Zone rules are spread across `analysis.py` (the zone→effort-class dict), `plan.py`
(`_zone_to_number` ordering + run-type tuples), and `cards.py` (threshold checks), and invalid
zones degrade silently. This is a behaviour-preserving refactor (E3) — the existing
zone/run-type/classification tests are the oracle. Light by design; no elaborate spec needed.

## Goals / Non-Goals

**Goals:** one typed home for zone identity, ordering, and the zone→effort-class map; reject
invalid zones instead of mislabeling them `Easy`; type-safety at the threshold/membership sites.

**Non-Goals:** no data migration (the enum maps to the persisted `"Z1".."Z5"` strings); zone
boundary numbers stay in config; display/chart/config zone literals untouched; no other DDD items.

## Decisions

### D1 — `Zone(IntEnum)` Z1..Z5 owns identity, ordering, and the effort-class map
```python
class EffortClass(Enum):
    RECOVERY = "Recovery"; EASY = "Easy"; MODERATE = "Moderate"; HARD = "Hard"; VERY_HARD = "Very Hard"

class Zone(IntEnum):
    Z1 = 1; Z2 = 2; Z3 = 3; Z4 = 4; Z5 = 5
    @classmethod
    def parse(cls, s: str) -> "Zone":            # "Z3"/"z3" -> Zone.Z3; raises on junk/None
        return cls[s.strip().upper()]
    @classmethod
    def parse_or_none(cls, s):                   # preserves the existing None / missing handling
        try: return cls.parse(s)
        except (KeyError, AttributeError, TypeError): return None
    @property
    def effort_class(self) -> EffortClass:        # the ONE zone->class map lives here
        return _ZONE_EFFORT[self]
```
Case-insensitive parse matches today's `_zone_to_number` (`'z3'` worked). Home: `fit/analysis.py`
next to `compute_hr_zones`.

### D2 — Reject invalid zones loudly; preserve `None`
`compute_effort_class(zone: str | None) -> str | None`: `None → None` (unchanged); a valid
zone → its `EffortClass.value` string (unchanged outputs); an **invalid** zone → raises (was
silently `"Easy"`). The string return type is kept so callers/stored values don't change — only
the silent-mislabel path is removed.

**The one verification gate (see tasks):** in normal operation the input is always a
`compute_hr_zones` output (Z1–Z5 or `None`), so the raise never fires — it's a bug-catching
guard. Before finalising, grep every `compute_effort_class` / zone-parse caller to confirm no
live path can feed an invalid string. If one can, that caller degrades via `parse_or_none`
(→ `None`) rather than crashing a render.

### D3 — Orderings collapse; run-type *sets* stay sets
Threshold checks (`zone in ("Z3","Z4","Z5")`, `_zone_to_number(z) >= 3`) → `Zone.parse(z) >= Zone.Z3`.
The run-type→zone rules (`tempo = ("Z3","Z4")`, plan.py:772–777) are genuinely *sets* — they stay
sets, just typed as `{Zone.Z3, Zone.Z4}`. Don't force them into the ordering.

## Risks / Trade-offs

- **[A live path feeds an invalid zone → the new raise crashes a render]** → the D2 verification
  gate (grep callers; confirm inputs are `compute_hr_zones` outputs); `parse_or_none` for any
  caller that legitimately handles unknown/missing. The existing suite + a regression test guard it.
- **[A migrated membership check subtly changes a run-type/classification]** → keep set semantics
  for the run-type rules; run the full suite and treat `test_analysis`/`test_plan` as the spec.

## Migration Plan

1. Add `EffortClass`, `Zone`, `_ZONE_EFFORT` (no behaviour change yet); unit-test in isolation.
2. Rewire `compute_effort_class` onto them (None→None, invalid→raise); suite green.
3. Replace `plan._zone_to_number` + caller and the threshold/membership sites; suite green.
4. Verification gate (D2): confirm no live invalid-zone path. No DB migration; rollback = revert branch.
