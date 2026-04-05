## ADDED Requirements

### Requirement: Download and cache .fit files
The system SHALL download .fit files via Garmin API, gated behind **`sync.download_fit_files: true`** config or `fit sync --splits` flag (not every sync by default). Files cached in `~/.fit/fit-files/{activity_id}.fit`. Track download status via `fit_file_path` column on activities and `splits_status` column (pending/parsed/failed/skipped). Max downloads per sync: configurable, default 20.

#### Scenario: Download gated by config
- **WHEN** `sync.download_fit_files` is false (default) and user runs `fit sync`
- **THEN** no .fit files are downloaded

#### Scenario: Download with --splits flag
- **WHEN** user runs `fit sync --splits`
- **THEN** .fit files are downloaded for new running activities (up to max_fit_downloads_per_sync)

#### Scenario: Cached file reused
- **WHEN** a .fit file already exists in ~/.fit/fit-files/
- **THEN** it is not re-downloaded

#### Scenario: Per-file parse failure
- **WHEN** a .fit file is corrupt or unsupported (swim, treadmill)
- **THEN** splits_status='failed' is set, error logged, sync continues with other files

### Requirement: Per-km split extraction with extended metrics
Parse .fit files into `activity_splits` table: activity_id, split_num, distance_km, time_sec, pace_sec_per_km, avg_hr, avg_cadence, elevation_gain_m, avg_speed_m_s, **time_above_z2_ceiling_sec** (seconds HR exceeded Z2 ceiling within this split), start_distance_m, end_distance_m.

#### Scenario: 10km run produces 10 splits
- **WHEN** a 10km .fit file is parsed
- **THEN** 10 rows in activity_splits, each covering ~1km with all fields populated

#### Scenario: Partial final split
- **WHEN** a 10.3km run is parsed
- **THEN** split 11 covers the final 0.3km, identifiable by start_distance_m and end_distance_m

### Requirement: Rolling cardiac drift detection
The system SHALL compute cardiac drift using a **rolling 1km window** that identifies the specific kilometer where HR begins decoupling from pace — not just first-half vs second-half average. The "drift onset km" is the athlete's current aerobic ceiling distance.

Additional: a **constant-pace filter** — if pace CV > 15% between halves, drift is flagged as "inconclusive (variable pace)".

#### Scenario: Drift onset detected at km 14
- **WHEN** an 18km run shows stable HR through km 13, then HR rises 10+ bpm/km
- **THEN** drift_onset_km = 14, drift_pct = computed, drift_status = "significant"

#### Scenario: Variable pace invalidates drift
- **WHEN** a hilly run has pace CV > 15% between halves
- **THEN** drift_status = "inconclusive_variable_pace"

### Requirement: Pace variability and cadence drift
The system SHALL compute **pace variability** (coefficient of variation across splits) as a consistency marker. Also **cadence drift** (same formula as cardiac drift but for cadence — cadence dropping in later splits signals form breakdown).

#### Scenario: High pace variability
- **WHEN** a run has splits ranging from 5:10 to 6:40/km
- **THEN** pace_cv is high, flagged as "inconsistent pacing"

#### Scenario: Cadence fade in long run
- **WHEN** cadence drops from 175 to 162 spm over the last 5km
- **THEN** cadence_drift flagged: "cadence faded 7% in final 5km — neuromuscular fatigue"

### Requirement: Split visualization with fade point
Training tab (collapsible section): **dual-axis bar+line chart** — pace per km as bars (zone-colored), HR per km as line on secondary axis. Target pace annotation from Runna plan if available. **Elevation profile** as subtle filled area background. **Fade point** highlighted with vertical annotation at the km where pace degrades >5% from first-half average.

Generate for **most recent long run only** in Phase 2 (run selector deferred).

**Cardiac drift gauge card** above the chart: single number, color-coded (<3% green, 3-5% caution, >5% danger), with one-line interpretation.

#### Scenario: Split chart with fade point
- **WHEN** an 18km long run has splits and pace fades at km 14
- **THEN** chart shows bars + HR line + elevation, with vertical dashed line at km 14 labeled "fade began"

### Requirement: Split data in coaching context
`get_coaching_context()` SHALL include split analysis for the most recent long run: drift_onset_km, drift_pct, pace_cv, cadence_drift, fade_point_km.

#### Scenario: Coaching references drift
- **WHEN** Claude generates coaching notes and last long run has split data
- **THEN** insights reference: "HR decoupled at km 14 — your current aerobic ceiling is ~14km"
