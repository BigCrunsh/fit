## ADDED Requirements

### Requirement: Coaching auto-detection alerts
The alerts engine (`fit/alerts.py`) SHALL fire coaching signals based on real-time data after each sync:

- **All runs too hard**: Z2 compliance < 50% over rolling 2-week window
- **Volume ramp guard**: weekly volume increase > 10% AND < 8 consecutive training weeks
- **Readiness gate**: readiness < 30 AND planned workout is quality session → recommend swap
- **Long run projection**: project longest_run_km trend and alert if won't reach 32km by peak phase
- **Heat acclimatization**: compute temperature-adjusted efficiency to project Berlin race day conditions
- **Alcohol impact**: 2+ drinks + HRV drop > 15% below baseline

#### Scenario: All runs too hard alert
- **WHEN** zero Z2 runs in last 14 days
- **THEN** alert: "No easy runs in 14 days. Your aerobic base cannot develop at this intensity."

#### Scenario: Readiness gate
- **WHEN** readiness=25, planned workout=tempo
- **THEN** alert: "Readiness 25 — swap planned tempo to easy/rest"

### Requirement: Run Story narrative
For the most recent long run (with split data), the system SHALL generate a **synthesized narrative** combining: split analysis (drift, fade point), correlations (previous night checkin), weather, and phase context. Displayed on Coach tab.

Example: "Sunday's 18km: held 5:45/km through km 14, then faded to 6:10. HR drifted +11%. 2 drinks Saturday, sleep quality 'poor'. Recommendation: stay dry before long runs."

#### Scenario: Run Story generated
- **WHEN** a long run with splits + previous-night checkin exists
- **THEN** a narrative paragraph is generated and displayed on the Coach tab

### Requirement: Milestone and personal best tracking
The system SHALL track **milestones**: new longest run, new best efficiency, first 3-run week, first 4-week streak, new VO2max peak. Displayed on Today tab as celebration cards when achieved.

#### Scenario: New longest run
- **WHEN** a run's distance exceeds all previous runs
- **THEN** Today tab shows: "New longest run: 18.2km (previous: 15.0km)"

#### Scenario: Streak milestone
- **WHEN** consecutive_weeks_3plus reaches 4 for the first time
- **THEN** Today tab shows: "Milestone: 4 consecutive weeks with 3+ runs"

### Requirement: Individual goal setting and tracking
The system SHALL support creating, updating, and tracking **individual goals** beyond the marathon. Goals can be: race (with target time), metric (VO2max, weight, efficiency), or habit (runs per week, check-in streak). Each goal has: name, type, target_value, target_unit, target_date, active status, and progress tracking.

`fit goal add` creates a goal interactively. `fit goal list` shows all active goals with progress. `fit goal complete <id>` marks a goal as achieved. Goals are displayed in `fit status` and the Today tab.

#### Scenario: Add a metric goal
- **WHEN** user runs `fit goal add` and enters "VO2max 51 by August"
- **THEN** a goal is created: name="VO2max 51", type=metric, target_value=51, target_unit=ml/kg/min, target_date=2026-08-01

#### Scenario: Progress tracking
- **WHEN** current VO2max is 49 and goal is 51
- **THEN** `fit status` shows: "VO2max: 49/51 (96% of target)"

#### Scenario: Goal displayed on Today tab
- **WHEN** active goals exist
- **THEN** the Today tab shows a goals section with current progress bars/values for each

#### Scenario: Habit goal tracking
- **WHEN** user creates a habit goal "3+ runs per week for 8 consecutive weeks"
- **THEN** the system tracks the streak from weekly_agg and shows progress: "4/8 weeks"
