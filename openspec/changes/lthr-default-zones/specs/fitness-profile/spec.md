## MODIFIED Requirements

### Requirement: HR zone primary selection follows a documented fallback chain
`compute_hr_zones()` SHALL select the primary `hr_zone` using this priority:

1. **AeT-anchored** (`hr_zone_aet`) — when an active `aet` calibration row exists. *Not yet implemented; reserved for `aet-anchored-zones`.*
2. **%LTHR (Friel)** (`hr_zone_lthr`) — when an active `lthr` calibration exists.
3. **%MaxHR** (`hr_zone_maxhr`) — as a last resort when neither AeT nor LTHR is available.

An explicit `profile.zone_model` config value (`max_hr` | `lthr` | `aet`) overrides the fallback chain. The default `zone_model` SHALL be `lthr`. `hr_zone_maxhr` and `hr_zone_lthr` SHALL continue to be computed in parallel as diagnostic outputs, regardless of which model is primary.

#### Scenario: LTHR calibrated, no AeT — primary is LTHR
- **WHEN** active `lthr = 172`, no active `aet`, `zone_model` unset
- **THEN** `hr_zone` matches `hr_zone_lthr`. avg HR 148 → Z2 (88% LTHR, in Friel Z2 band 85–89%).

#### Scenario: LTHR missing, falls back to %MaxHR
- **WHEN** no active `lthr` calibration, no active `aet`
- **THEN** `hr_zone` matches `hr_zone_maxhr` (%MaxHR textbook model)

#### Scenario: Explicit override wins
- **WHEN** `profile.zone_model = max_hr` is set in `config.local.yaml`, LTHR is calibrated
- **THEN** `hr_zone` matches `hr_zone_maxhr` (user override beats fallback)

#### Scenario: Diagnostic zones always computed
- **WHEN** any running activity with `avg_hr` is enriched
- **THEN** `hr_zone_maxhr` is populated (always), `hr_zone_lthr` is populated (when LTHR cal exists), and the primary `hr_zone` matches the active model

### Requirement: Recompute path applies the active calibration to historical activities
`fit recompute --force` SHALL re-enrich every activity using the current calibration values, regardless of whether `hr_zone` is already populated. After a calibration change or a zone-model switch, running `fit recompute --force` SHALL produce a consistent zone classification across all history.

#### Scenario: Zone model switched
- **WHEN** user changes `zone_model` from `max_hr` to `lthr` and runs `fit recompute --force`
- **THEN** all 231 historical activities have their `hr_zone` recomputed against the Friel %LTHR model; `weekly_agg.z12_pct` recomputes accordingly

#### Scenario: Default recompute leaves zoned activities alone
- **WHEN** user runs `fit recompute` (no `--force`)
- **THEN** only activities with `hr_zone IS NULL` are re-enriched (post-sync gap-filling behavior, unchanged from today)
