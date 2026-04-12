## ADDED Requirements

### Requirement: Last 7 Days per-run detail cards on Training tab
The Training tab SHALL display a "Last 7 Days" section showing one expandable card per run from the last 7 days. Each card header SHALL show: date, run type, distance, duration, average pace, average HR, and effort class badge. Clicking a card SHALL expand it to reveal detailed analysis. This section replaces the flat Run Timeline — there SHALL NOT be a separate horizontal bar timeline for recent runs.

#### Scenario: 4 runs in last 7 days
- **WHEN** 4 runs exist in the last 7 days
- **THEN** 4 cards render in reverse chronological order, each collapsed by default showing the header summary

#### Scenario: No runs in last 7 days
- **WHEN** no activities exist in the last 7 days
- **THEN** the section shows "No runs in the last 7 days. Next planned workout: <from _next_workouts()>" or "No runs and no plan loaded."

#### Scenario: Card expansion
- **WHEN** user clicks a run card header
- **THEN** the card expands to show split analysis, plan comparison, and adaptation signals (JS toggle, no page reload)

### Requirement: Plan comparison per run
Each expanded run card SHALL show plan comparison when a matching planned workout exists: planned vs actual distance, planned vs actual workout type, and a pacing verdict ("on target", "too fast", "too slow") based on the planned workout's zone intent. Matching uses the same date-matching logic as `compute_plan_adherence()`.

#### Scenario: Easy run matches plan
- **WHEN** a planned "Easy 8km Z2" exists and the actual run was 8.2km at avg HR in Z2
- **THEN** the plan comparison shows "Planned: Easy 8km Z2 | Actual: 8.2km Z2 | On target"

#### Scenario: Tempo run too fast
- **WHEN** a planned "Tempo 6km Z3" exists and the actual run averaged Z4
- **THEN** the pacing verdict shows "Too fast — planned Z3, ran Z4" in amber

#### Scenario: Unplanned run
- **WHEN** no planned workout matches the run date
- **THEN** the plan comparison shows "Unplanned run" with no verdict

#### Scenario: Missed planned workout
- **WHEN** a planned workout exists for a date with no activity
- **THEN** no card renders for that date (missed workouts are shown in the plan adherence section, not here)

### Requirement: Per-km split analysis in run detail cards
Each expanded run card SHALL show per-km split data when `activity_splits` data exists for that run. The display SHALL include: pace per km as horizontal bars (colored by zone), elevation gain per split, and cardiac drift from `compute_cardiac_drift()`. Splits without data SHALL show "No split data — enable .fit file sync with `fit sync --splits`".

#### Scenario: 10km run with splits
- **WHEN** a 10km run has 10 splits in `activity_splits`
- **THEN** 10 horizontal pace bars render, colored by the HR zone of each split, with elevation overlay and cardiac drift percentage

#### Scenario: Workout phase overlay on splits
- **WHEN** the matched planned workout has phases (e.g., 2km warmup + 4km tempo + 2km cooldown) AND splits exist
- **THEN** splits are grouped under phase labels: "Warmup (km 1-2)", "Tempo (km 3-6)", "Cooldown (km 7-8)"

#### Scenario: No split data available
- **WHEN** `splits_status` is NULL or 'pending' for the activity
- **THEN** the split section shows "No split data — run `fit sync --splits` to download .fit files"

#### Scenario: Cardiac drift displayed
- **WHEN** cardiac drift is computed for the run (>= 20 min duration)
- **THEN** a drift percentage is shown (e.g., "Cardiac drift: +4.2%") with color: green <5%, amber 5-10%, red >10%

### Requirement: Four-week rolling adaptation signals per run
Each expanded run card SHALL show adaptation signals comparing the current run to the same run type over the prior 4 weeks. Signals SHALL include: pace trend (4-week rolling average for same run type, direction arrow), efficiency trend (speed_per_bpm rolling average, direction arrow), and sRPE context (if sRPE exists for this run, show "sRPE: 340 — felt harder/easier than HR suggests"). Signals SHALL only display when sample size >= 2 runs of the same type in the 4-week window.

#### Scenario: Easy run with 4-week comparison
- **WHEN** 3 easy runs exist in the prior 4 weeks with avg pace 6:10/km, and this easy run was 5:55/km
- **THEN** pace signal shows "5:55/km vs 4wk avg 6:10/km" with a green down arrow (faster)

#### Scenario: Insufficient comparison data
- **WHEN** only 1 tempo run exists in the prior 4 weeks
- **THEN** no adaptation signals render for a tempo run (sample size < 2)

#### Scenario: sRPE context displayed
- **WHEN** a run has sRPE = 420 (RPE 7 x 60 min) and HR zone was Z2
- **THEN** sRPE line shows "sRPE: 420 — felt harder than HR zone suggests" in amber

#### Scenario: No sRPE data
- **WHEN** no check-in RPE exists for the run date
- **THEN** sRPE line is omitted (not shown as empty)

### Requirement: Training load per run shown in card header
Each run card header SHALL include the training load value (TRIMP or similar from the existing per-run load computation). This absorbs the standalone "Training Load per Run" chart — there SHALL NOT be a separate training load chart on the Training tab.

#### Scenario: Load in card header
- **WHEN** a run has a computed training load of 85
- **THEN** the card header shows "Load: 85" alongside pace and HR

#### Scenario: No load data
- **WHEN** training load cannot be computed (missing HR data)
- **THEN** the load field is omitted from the header
