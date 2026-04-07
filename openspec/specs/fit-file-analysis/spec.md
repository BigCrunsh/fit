## ADDED Requirements

### Requirement: .fit file download with opt-in and caching
The system SHALL download .fit files gated behind `sync.download_fit_files` config toggle (default false) or `fit sync --splits` flag. Files cached in `~/.fit/fit-files/{activity_id}.fit`. Track status via `fit_file_path` and `splits_status` columns on activities (pending/parsed/failed/skipped). Max downloads per sync: configurable (default 20). Backfill: `fit splits --backfill` with rate control (max 20 per batch, 2s delay to avoid Garmin throttling).

#### Scenario: Download disabled by default
- **WHEN** `sync.download_fit_files` is false and user runs `fit sync`
- **THEN** no .fit files downloaded

#### Scenario: Per-file failure handling
- **WHEN** a .fit file is corrupt or from an unsupported activity (swim, treadmill)
- **THEN** splits_status='failed', error logged, sync continues

#### Scenario: Rate-limited backfill
- **WHEN** `fit splits --backfill` processes 200+ activities
- **THEN** downloads 20 at a time with 2s delay between batches

### Requirement: Per-km split extraction with zone time
Parse .fit files into `activity_splits` table with: activity_id, split_num, distance_km, time_sec, pace_sec_per_km, avg_hr, avg_cadence, elevation_gain_m, avg_speed_m_s, time_above_z2_ceiling_sec, start_distance_m, end_distance_m. The time_above_z2_ceiling_sec per split fixes the "entire run = one zone" problem.

#### Scenario: Zone time per split
- **WHEN** a 10km run has 3km in Z2 (HR 128) and 7km in Z3-Z4
- **THEN** splits 1-3 have time_above_z2_ceiling_sec=0, splits 4-10 have positive values
- **AND** weekly zone aggregation uses split-level data (not avg HR per run)

### Requirement: Rolling cardiac drift detection
Compute drift using a rolling 1km window — identify the specific km where HR begins decoupling from pace (drift_onset_km). Constant-pace filter: if pace CV > 15% between halves, flag as "inconclusive (variable pace)."

#### Scenario: Drift onset at km 14
- **WHEN** an 18km run shows stable HR:pace ratio through km 13, then HR rises without pace change
- **THEN** drift_onset_km=14, drift_pct computed, drift_status="significant"

#### Scenario: Variable pace invalidates drift
- **WHEN** a hilly run has pace CV > 15%
- **THEN** drift_status="inconclusive_variable_pace"

### Requirement: Pace variability and cadence drift
Compute pace CV (coefficient of variation across splits) as a consistency marker. Cadence drift = same formula as cardiac drift but for cadence.

#### Scenario: Cadence fade in long run
- **WHEN** cadence drops from 175 to 162 spm over the last 5km
- **THEN** cadence_drift flagged: "cadence faded 7% in final 5km"

### Requirement: Heat-adjusted zone flags
Runs at >25°C or >70% humidity SHALL be flagged as "heat-affected" with a zone penalty annotation. Update `get_coaching_context()` and `generate_headline()`: "Last run was in 30°C heat — HR was ~1 zone higher than true effort."

**Temperature data fallback chain:** (1) .fit file recorded data (if available and contains temp/humidity), (2) Open-Meteo hourly weather already stored on the activity (temp_c, humidity_pct columns — always available for synced runs), (3) if neither exists, skip heat flag. Since Open-Meteo data is populated during sync, most runs will have heat data even without .fit files.

#### Scenario: Hot run flagged
- **WHEN** a run has temp_at_start_c=31 and humidity_at_start_pct=75
- **THEN** activity flagged heat_affected=True, coaching context mentions heat impact

#### Scenario: Heat flag from weather data (no .fit file)
- **WHEN** a run has no .fit file but Open-Meteo data shows temp_c=28
- **THEN** activity flagged heat_affected=True using weather data

### Requirement: Split visualization (dual-panel)
Display as dual-panel chart on Training tab (collapsible): top panel = pace bars colored by zone, bottom panel = HR line with expected-HR reference. Elevation profile as subtle background. Drift onset marked with vertical annotation. Most recent long run only inline; historical behind "View splits" link.

**Drift gauge card** above the split chart shows: drift_pct (e.g., "+11%"), drift_onset_km (e.g., "km 14"), drift_status (significant/mild/none/inconclusive), and a color indicator (green <5%, yellow 5-10%, red >10%). If drift_status = inconclusive_variable_pace, show "Pace too variable for drift analysis" instead.

#### Scenario: Split chart for 18km run
- **WHEN** 18km run with splits, drift onset at km 14
- **THEN** pace bars show zone colors, HR line shows decoupling at km 14, vertical annotation "drift onset"
- **AND** drift gauge card shows "+11% | onset km 14 | significant" in red

### Requirement: Heat acclimatization tracking
Track temperature-adjusted efficiency over time: efficiency per run plotted against temperature. Project expected race-day conditions (Berlin late September: ~15°C). Show trend: "Your heat-adjusted efficiency is improving — you're acclimating."

#### Scenario: Acclimatization trend
- **WHEN** runs at >25°C show improving efficiency over 4+ weeks
- **THEN** coaching: "Heat efficiency improving. Race day forecast ~15°C — conditions will be favorable."

### Requirement: Test fixture
Bundle a minimal synthetic .fit fixture in tests/fixtures/ (not real files — keep tests fast, avoid licensing). Test full pipeline: parse → splits → drift → DB.

#### Scenario: Synthetic fixture test
- **WHEN** test parses the synthetic .fit fixture
- **THEN** correct splits, drift detection, and DB storage verified

## Post-Phase 2 Additions

### Requirement: Garmin .fit file ZIP extraction
Garmin downloads .fit files as ZIP archives, not raw .fit files. The system SHALL detect ZIP files using `zipfile.is_zipfile()` and automatically extract the .fit file before parsing.

#### Scenario: ZIP file downloaded from Garmin
- **WHEN** a downloaded file is a ZIP archive containing a .fit file
- **THEN** the system extracts the .fit file from the ZIP before parsing

#### Scenario: Raw .fit file (not zipped)
- **WHEN** a downloaded file is already a raw .fit file (not a ZIP)
- **THEN** the system parses it directly without extraction

#### Scenario: ZIP with no .fit file inside
- **WHEN** a downloaded ZIP does not contain a .fit file
- **THEN** splits_status='failed', error logged, processing continues
