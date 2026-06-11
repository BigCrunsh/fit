## ADDED Requirements

### Requirement: Zone identity, ordering, and effort-class mapping have one typed home
The system SHALL represent an HR zone as a `Zone` value with an intrinsic total order
(`Z1 < Z2 < Z3 < Z4 < Z5`) and a single `EffortClass` mapping (`Z1`→Recovery, `Z2`→Easy,
`Z3`→Moderate, `Z4`→Hard, `Z5`→Very Hard). The zone ordering and the zone→effort-class mapping
SHALL be defined in exactly one place and SHALL NOT be re-derived elsewhere. An unrecognised
zone string SHALL be rejected (not silently classified), and a `None` zone SHALL map to no
effort class (`None`). This requirement changes representation only — it SHALL NOT rewrite any
persisted zone string (`activities.hr_zone`/`hr_zone_lthr`/`hr_zone_maxhr`) and SHALL NOT move
zone *boundary numbers* out of config.

#### Scenario: Each zone maps to its documented effort class
- **WHEN** the effort class of `Z1`…`Z5` is requested
- **THEN** it is Recovery, Easy, Moderate, Hard, Very Hard respectively — the single mapping,
  not a per-call-site copy

#### Scenario: A missing zone has no effort class
- **WHEN** `compute_effort_class` is given `None`
- **THEN** it returns `None` (unchanged from today)

#### Scenario: An invalid zone is rejected, not mislabeled Easy
- **WHEN** a zone string outside `Z1`–`Z5` (a typo or junk) reaches the effort-class mapping
- **THEN** it is rejected (raises) rather than silently returning `"Easy"` — the prior
  `{...}.get(zone, "Easy")` fallthrough is gone

#### Scenario: Intensity thresholds read the intrinsic order
- **WHEN** logic needs "Z3 and above is hard effort"
- **THEN** it compares the typed `Zone` order (`zone >= Zone.Z3`), not a separately re-derived
  zone-to-number conversion

#### Scenario: Run-type zone rules keep set semantics
- **WHEN** a run type is classified against its allowed zones (e.g. tempo = `{Z3, Z4}`)
- **THEN** membership is unchanged — the rule stays a typed *set*, not collapsed into an
  ordering
