## ADDED Requirements

### Requirement: sRPE as validated internal load metric
The system SHALL compute sRPE (session RPE × duration_min) for running activities where RPE data exists. Stored on activities.srpe column. Join strategy: checkin RPE → most recent same-day activity (if multiple, assign to the one with highest training_load). Shown in weekly_agg alongside Garmin EPOC load.

#### Scenario: sRPE computed for run with RPE
- **WHEN** a run has duration_min=50 and today's checkin has RPE=6
- **THEN** activities.srpe = 300 (50 × 6)

#### Scenario: Two runs same day
- **WHEN** two runs exist on the same day (morning easy 30min, evening tempo 45min) and RPE=7
- **THEN** sRPE assigned to the tempo run (higher training_load): 45 × 7 = 315

### Requirement: Training monotony and strain
The system SHALL compute weekly training monotony = mean(daily_loads) / stdev(daily_loads), and strain = weekly_load × monotony. Added to weekly_agg. These are classic Foster leading indicators — they flag overtraining 5-10 days before ACWR spikes. High monotony means every day is similar load (low variance → high mean/stdev ratio). Monotony > 2.0 is the standard warning threshold; strain > 6000 is the danger zone.

Guard: if stdev = 0 (all days identical or only 1 training day), set monotony = NULL (undefined, not infinite). Do not alert on NULL monotony.

#### Scenario: High monotony detected
- **WHEN** 7-day loads are [80, 82, 78, 81, 80, 79, 83] (mean=80.4, stdev=1.6, monotony=50.3)
- **THEN** monotony is extremely high (>2.0), strain = 563 × 50.3 triggers a warning

#### Scenario: Normal training variation
- **WHEN** 7-day loads are [100, 0, 60, 0, 80, 120, 0] (mean=51.4, stdev=49.0, monotony=1.05)
- **THEN** monotony is moderate (<2.0), no strain warning

#### Scenario: Single training day
- **WHEN** only 1 day has load, rest are 0 (stdev dominated by zeros)
- **THEN** monotony = NULL, no alert generated

### Requirement: Cycling volume in training model
The system SHALL track cycling_km and cycling_min per week in weekly_agg. Show cycling distance + time in `fit status` and Training tab. Factor into headline when preceding-day cycling was high. Add correlation pair: previous-day cycling_km → next-day run efficiency.

#### Scenario: High cycling day before run
- **WHEN** previous day had 30km cycling and today has a planned run
- **THEN** headline: "30km cycling yesterday — consider easy today"

### Requirement: SpO2 illness alert
The system SHALL alert when avg_spo2 < 95% (configurable) for 2+ consecutive days. This is a leading indicator for respiratory illness. Do NOT add SpO2 to dashboard charts (mostly flat 95-98% for sea-level runners).

#### Scenario: SpO2 drop detected
- **WHEN** SpO2 was 93% yesterday and 94% today (2 consecutive days <95%)
- **THEN** alert: "SpO2 below 95% for 2 days — possible illness, consider rest"

### Requirement: Deload/recovery week detection
The system SHALL detect when no deload week has occurred in 4+ consecutive build weeks. A deload week = volume drops 30-40% from the prior week. Alert if overdue.

#### Scenario: Deload overdue
- **WHEN** 5 consecutive weeks of increasing or stable volume with no drop ≥30%
- **THEN** alert: "No recovery week in 5 weeks — schedule a deload (30-40% volume reduction)"

### Requirement: Daniels VDOT lookup table
The race prediction SHALL use a proper Daniels lookup table (or polynomial fit accurate across VO2max 35-60) instead of the current linear approximation (base_seconds + (vo2max - 40) × -300) which diverges badly outside 45-55.

#### Scenario: VO2max 42 prediction
- **WHEN** VO2max is 42
- **THEN** Daniels table predicts ~4:28 marathon (current linear formula predicts ~4:30 — close here but diverges at extremes)

### Requirement: Long run dual-condition threshold
Long run classification SHALL use: (>30% of weekly volume AND ≥8km) OR (≥12km absolute floor regardless of percentage). The ≥12km floor is an override — any run ≥12km is always a long run. The percentage condition catches shorter runs that are long relative to the athlete's current volume. The ≥8km minimum prevents very short runs from qualifying on percentage alone.

#### Scenario: Short high-percentage run
- **WHEN** a 6km run is 40% of a 15km week
- **THEN** NOT classified as long run (passes >30% but fails ≥8km minimum)

#### Scenario: Long run at low percentage
- **WHEN** a 13km run is 20% of a 65km week
- **THEN** classified as long run (passes ≥12km absolute floor override)

#### Scenario: Moderate run at high percentage
- **WHEN** a 9km run is 35% of a 25km week
- **THEN** classified as long run (passes >30% AND ≥8km)

### Requirement: FitDays body composition import
The weight CSV importer SHALL parse body_fat_pct, muscle_mass_kg, visceral_fat from FitDays CSV (column name detection). Skip BMI, bone mass, body water, metabolic age, protein, subcutaneous fat (BIA noise). Add body fat trend to Body tab weight chart (second y-axis). Include body comp trend in coaching context.

#### Scenario: Full body comp imported
- **WHEN** FitDays CSV has columns weight_kg, body_fat, muscle_mass, visceral_fat
- **THEN** all four values stored in body_comp table

### Requirement: Return-to-run protocol
When chronic training load is near-zero (e.g., after a multi-week gap), ACWR is mathematically meaningless (dividing by ~0). The system SHALL detect a training gap (≥14 days with no runs) and switch to an absolute volume cap for the first 4 weeks: week 1 max = 50% of pre-gap 4-week average, ramping 10-15% per week. During this period, ACWR-based alerts are suppressed and replaced with: "Return-to-run protocol active — capped at {X}km this week."

#### Scenario: Return after 100-day gap
- **WHEN** no runs in 100 days, pre-gap average was 30km/week
- **THEN** week 1 cap = 15km, ACWR alerts suppressed, coaching: "Return-to-run: max 15km this week"

#### Scenario: Gap too short for protocol
- **WHEN** 10-day gap (illness)
- **THEN** normal ACWR applies (chronic load still meaningful)

### Requirement: Cycling cross-training load contribution
Cycling volume SHALL be factored into total training load as a weighted contribution (default: 0.3× equivalent running load based on duration). This prevents understating total musculoskeletal/cardiovascular load for athletes with high cycling volume. The weighting factor is configurable via `analysis.cycling_load_weight` in config.yaml.

#### Scenario: High cycling volume
- **WHEN** athlete cycles 75km/week (~5h) alongside 25km running
- **THEN** total load includes cycling contribution: 5h × 0.3 = 1.5h equivalent running load factored into weekly totals

### Requirement: Race prediction confidence band
Race prediction SHALL include a confidence range, not just a point estimate. Range width based on: data quantity (weeks of training), prediction model input quality (VO2max freshness, recent race data availability), and training phase. Display as "prediction: 3:48-4:05" with qualifier ("low confidence — base phase" / "moderate — 12 weeks data" / "high — recent race calibration").

#### Scenario: Early base phase prediction
- **WHEN** 4 weeks of data, base phase, no recent race
- **THEN** "prediction: 3:45-4:15 (low confidence — limited data, base phase)"

#### Scenario: Post-race prediction
- **WHEN** recent 10K race used for calibration + 16 weeks of data
- **THEN** "prediction: 3:48-3:58 (high confidence — race-calibrated)"

### Requirement: Adaptive readiness gate
The readiness threshold for downgrading quality sessions SHALL be adaptive based on training phase and return-to-run status. Default: readiness < 40 triggers swap recommendation. During return-to-run (first 4 weeks after gap): threshold raised to < 50. The threshold is configurable via `coaching.readiness_gate_threshold` in config.yaml.

#### Scenario: Detrained athlete low readiness
- **WHEN** return-to-run active, readiness=42, planned=Tempo
- **THEN** coaching: "Readiness 42 during return phase — swap Tempo to easy Dauerlauf"

#### Scenario: Established athlete low readiness
- **WHEN** 12+ weeks training, readiness=35, planned=Intervals
- **THEN** coaching: "Readiness 35 — swap Intervals to easy"

### Requirement: Correlation effect size filter
ALL correlation pairs (not just SpO2) SHALL have minimum thresholds before surfacing: minimum n≥15 data points AND minimum |r|≥0.2. Below threshold: pair is computed but not displayed in narratives or coaching context. This prevents spurious coaching signals from small samples.

#### Scenario: Weak correlation suppressed
- **WHEN** alcohol→HRV has r=-0.12 with n=20
- **THEN** correlation computed and stored but NOT shown in coaching or narratives

#### Scenario: Strong correlation surfaced
- **WHEN** sleep→efficiency has r=0.45 with n=25
- **THEN** shown in coaching: "Sleep quality correlates strongly with run efficiency"

### Requirement: Race-day pacing strategy
The system SHALL translate a marathon prediction into a race-day plan: target splits per 5km, HR ceiling per segment, fueling timing. Displayed in the Race Prediction section of the Fitness tab.

#### Scenario: Sub-4:00 pacing plan
- **WHEN** prediction is 3:52
- **THEN** show: "5km splits: 27:20 | HR ceiling: 165 | Fuel: gel at 45min, then every 30min"

## Post-Phase 2 Additions

### Requirement: Auto-populate weight calibration from Apple Health import
When Apple Health body comp data is imported (via `fit import-health` or auto-sync), the system SHALL automatically create or update a weight calibration entry with `method = 'scale'`, `confidence = 'high'`, using the most recent weight value.

#### Scenario: Weight calibration from Apple Health
- **WHEN** Apple Health import adds weight data with latest value 76.2kg
- **THEN** calibration table has an active weight entry: value=76.2, method='scale', confidence='high'

### Requirement: Auto-populate VO2max calibration from Garmin sync
When `fit sync` imports activities that include a VO2max estimate from Garmin, the system SHALL automatically create or update a VO2max calibration entry with `method = 'garmin_estimate'`, `confidence = 'medium'`, using the latest activity's VO2max value.

#### Scenario: VO2max calibration from sync
- **WHEN** sync imports an activity with vo2max=49.5
- **THEN** calibration table has an active vo2max entry: value=49.5, method='garmin_estimate', confidence='medium'

### Requirement: Prediction table shows all completed races grouped by distance
The race prediction section SHALL display ALL completed races (no LIMIT), grouped by distance category (HM, 10K, 5K, Other). VO2max-based predictions are shown in a separate row. Each race shows the original pace alongside the extrapolated pace for the target race distance.

#### Scenario: All races shown grouped
- **WHEN** race_calendar has 3 completed races (1x HM, 2x 10K) and VO2max is 49
- **THEN** prediction table shows HM group (1 row), 10K group (2 rows), VO2max row, no LIMIT applied

#### Scenario: Original pace alongside extrapolated
- **WHEN** a completed 10K race had pace 5:53/km and Riegel extrapolation to marathon gives 6:20/km
- **THEN** prediction row shows "6:20/km (ran 5:53/km)" for that race

### Requirement: Prediction summary adapts to target race distance
The prediction summary SHALL use the target race distance (from `get_target_race()`) for all extrapolations. Both Riegel and VDOT predictions are scaled to `target_km`. If no target race exists, default to marathon (42.195km).

#### Scenario: Target race is half marathon
- **WHEN** target race is a half marathon (21.1km)
- **THEN** all Riegel and VDOT predictions are extrapolated to 21.1km, not marathon

#### Scenario: No target race defaults to marathon
- **WHEN** no target race exists
- **THEN** predictions use 42.195km as default target distance
