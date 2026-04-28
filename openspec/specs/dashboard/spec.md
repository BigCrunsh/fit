## ADDED Requirements

### Requirement: fit report generates a self-contained HTML dashboard
`fit report` SHALL generate a single self-contained HTML file with Chart.js 4.4.7 (+ chartjs-plugin-annotation for event markers + chartjs-adapter-date-fns for time-scaled x-axes) for charting. All three JS libraries are vendored and inlined. The dashboard SHALL use a dark theme (`#07070c` background), monospace numerics (JetBrains Mono), and an information-dense layout. The output file SHALL be viewable in any browser without a build step or server. Generation uses Jinja2 templates (`fit/report/templates/dashboard.html`).

#### Scenario: Default report generation
- **WHEN** user runs `fit report`
- **THEN** `reports/dashboard.html` is generated (or overwritten) and a success message is displayed

#### Scenario: Report is self-contained
- **WHEN** the generated HTML file is opened in a browser with no internet
- **THEN** all charts render correctly (Chart.js + annotation plugin inlined)

### Requirement: Dashboard has 5 tabs
The dashboard SHALL have 5 tabs: **Today**, **Training**, **Body**, **Fitness**, and **Coach**. Today is the landing tab. Tab switching SHALL work via client-side JavaScript with no page reload.

#### Scenario: Tab navigation
- **WHEN** user clicks a tab header
- **THEN** the corresponding tab content is shown and others are hidden

#### Scenario: Today is the default tab
- **WHEN** the dashboard is opened
- **THEN** the Today tab is shown first

### Requirement: Time-scaled x-axes on time-series charts
All time-series charts SHALL use `chartjs-adapter-date-fns` for proper date-scaled x-axes. This ensures that gaps in data (e.g., training breaks) are visually proportional to their duration, rather than equally spaced.

### Requirement: Two-palette color system
The dashboard SHALL use two distinct color palettes to avoid semantic confusion:

**Health/Safety palette** (evaluative — is this good or bad?):
- Green = good / safe / on track
- Yellow/amber = caution / approaching limit
- Red = alert / danger / action needed
- Used for: readiness, ACWR, staleness, phase compliance, sleep quality mismatches, RPE mismatches, calibration status

**Intensity palette** (descriptive — how hard was this?):
- Cool blue/cyan = Z1-Z2 (low intensity)
- Warm amber/gold = Z3 (moderate)
- Hot orange/magenta = Z4-Z5 (high intensity)
- Used for: zone distribution, training load bars, run type colors, HR per run bars

#### Scenario: Z4 interval not confused with danger
- **WHEN** a training load bar shows a Z4 interval session
- **THEN** the bar uses the intensity palette (hot orange), not the safety palette (red), because a hard session is intentional training, not a problem

#### Scenario: ACWR uses safety palette
- **WHEN** ACWR gauge shows 1.6
- **THEN** it uses the safety palette red (danger), distinct from the intensity orange used for hard workouts

### Requirement: Today tab provides daily synthesis and actionable headline
The Today tab SHALL display: (1) a **headline sentence** synthesizing readiness, ACWR safety, phase compliance, and a recommendation for today (rule-based, no Claude needed), (2) status cards with 4-week rolling deltas (readiness, RHR, sleep, HRV, VO2max, weight, ACWR safety color, consistency streak), (3) latest check-in (hydration, alcohol, legs, sleep quality, RPE, notes), (4) ACWR gauge (prominent, safety-colored with trend), (5) active phase compliance mini-scorecard (on/off track per dimension), (6) calibration + data source health panel (collapsed by default, expandable), (7) **journey timeline** showing the marathon goal with phase progression.

#### Scenario: Ready for quality session
- **WHEN** readiness ≥ 75, ACWR 0.8-1.3, phase is on track, and active phase allows quality sessions
- **THEN** headline reads: "Ready for training. Phase 2 allows a tempo session today. ACWR is safe at 1.1."

#### Scenario: Recovery day recommended
- **WHEN** readiness < 50 OR ACWR > 1.3 OR sleep_quality is "Poor"
- **THEN** headline reads: "Recovery day recommended. Readiness is 42, ACWR at 1.4. Easy walk or rest."

#### Scenario: Stale check-in prompt
- **WHEN** last check-in was > 1 day ago
- **THEN** headline includes: "No check-in today. Run `fit checkin` before training."

#### Scenario: Phase 1 with no quality sessions
- **WHEN** active phase is Phase 1 (quality_sessions_per_week = 0) and readiness is high
- **THEN** headline reads: "Ready for an easy Z2 run. Phase 1: base building only, no hard efforts yet."

### Requirement: Goal progress cards with hover tooltips on Today tab
The Today tab SHALL display goal progress cards for tracked metrics: VO2max (current vs target with percentage), Weight (current vs target with progress bar), Streak (consecutive weeks vs target), and next race countdown (days remaining). Each card includes a hover tooltip with contextual explanation (e.g., "Each kg lost saves ~2-3 sec/km over 42km").

#### Scenario: Goal progress with next race
- **WHEN** a registered race exists in race_calendar
- **THEN** a countdown card shows days remaining, distance, and target time on hover

### Requirement: Recent alerts displayed on Today tab
The Today tab SHALL show unacknowledged alerts from the last 7 days, rendered as colored alert boxes with the alert message.

### Requirement: Correlation cards on Coach tab
The Coach tab SHALL display correlation results as horizontal bar cards, sorted by absolute Spearman r. Each card shows: label (with underscores replaced and lag notation), r value (formatted as +/-0.XX), sample size, confidence level, bar width proportional to |r|, and color (green for positive, red for negative correlations).

### Requirement: Journey timeline visualization
The Today tab SHALL display a horizontal journey timeline for the primary goal, showing: all training phases as segments (colored by status: completed=solid, active=gradient, planned=outline), the current position marked ("You are here — Week 3 of Phase 1"), key metrics below each phase (current vs target), and the race date at the end. This provides emotional context — where you are in the story.

#### Scenario: Journey timeline with active Phase 1
- **WHEN** Phase 1 is active and 3 weeks in
- **THEN** the timeline shows Phase 1 partially filled, Phases 2-4 as outlines, race day at the end, with "Week 3 of Phase 1" marker and current vs target metrics

#### Scenario: Phase transition visible
- **WHEN** Phase 1 is completed and Phase 2 is active
- **THEN** Phase 1 shows as solid (with actual metrics), Phase 2 partially filled, remaining phases as outlines

### Requirement: Status cards show current state with 4-week rolling deltas
The Today tab header SHALL display status cards for: Readiness (latest, safety-colored), RHR (latest, 4-week delta), Sleep (latest hours, deep + REM), HRV (latest, weekly avg, 4-week delta), VO2max (latest, peak ref, 4-week delta), Weight (latest, race target, 4-week delta), and Consistency (streak weeks). Each card uses the health/safety palette for delta direction. Status cards are visible on the Today tab.

#### Scenario: Status cards with 4-week delta
- **WHEN** current RHR is 57, RHR 4 weeks ago was 61
- **THEN** RHR card shows "57 bpm ↓4" with green (improving)

#### Scenario: Insufficient data for delta
- **WHEN** fewer than 28 days of data
- **THEN** delta annotations omitted

### Requirement: Latest check-in displayed on Today tab
The Today tab SHALL display the most recent check-in: hydration, alcohol, legs, sleep quality, RPE, and notes.

#### Scenario: Check-in displayed
- **WHEN** at least one check-in exists
- **THEN** latest check-in date and values shown

#### Scenario: No check-ins exist
- **WHEN** no check-ins
- **THEN** "No check-ins yet. Run `fit checkin` to start."

### Requirement: Calibration and data source health panel (collapsed by default)
The Today tab SHALL include a collapsible calibration + data health panel. Collapsed by default (showing only a summary: "2 warnings" or "All healthy"). When expanded: calibration status per metric (value, method, date, staleness color), data source status per source (active/stale/missing with Garmin instructions), active test prompts.

#### Scenario: Panel collapsed with warnings
- **WHEN** LTHR is stale and SpO2 is missing
- **THEN** collapsed panel shows "2 warnings" badge; expanded shows details

#### Scenario: All healthy collapsed
- **WHEN** all calibrations current and all sources active
- **THEN** collapsed panel shows "All healthy ✓" in green

### Requirement: Training tab shows training structure (smart date range)
The Training tab SHALL display purpose-driven sections in this order: (1) **Last 7 Days hero card** (from `training-week-summary` capability), (2) **Objectives row** (from `training-week-summary` capability), (3) **Last 7 Days** per-run detail cards (from `run-detail-analysis` capability), (4) **Plan Adherence** multi-week summary (from `training-week-summary` capability), (4b) **Planned vs Actual (per day)** mirrored bars, (5) **Volume Trend** stacked-by-run-type chart (Volume Trend and Run Type Mix are merged into a single stacked bar chart `chart-volume`, with phase target as shaded band using box annotation matching established chart style, gap annotations for breaks >14 days), (6) **Plan Compliance Trend** scatter (per-run Garmin adherence score with rolling average). Training Load per Run chart is removed — per-run load data is folded into Last 7 Days card headers. The smart date range and zoom toggle apply to the Volume Trend chart.

#### Scenario: Training tab section order
- **WHEN** the Training tab is opened with sufficient data
- **THEN** sections render top-to-bottom: Last 7 Days hero, Objectives, Last 7 Days, Plan Adherence, Planned vs Actual, Volume Trend, Plan Compliance Trend

#### Scenario: Volume chart smart range default
- **WHEN** 20+ ISO weeks of data exist
- **THEN** the Volume Trend chart defaults to a recent window via the JS smart-range / zoom toggle (`timeScaleCharts`), not all-time

#### Scenario: Phase target band on volume chart
- **WHEN** active phase has weekly_km target [30, 40]
- **THEN** a shaded band (box annotation, 40+ hex opacity) marks the 30-40km target range on the volume chart

#### Scenario: Stacked run-type breakdown on volume chart
- **WHEN** the Volume Trend chart renders
- **THEN** each weekly bar is stacked by run type (easy, long, tempo, progression, intervals, recovery, race) — fulfilling the Run Type Mix requirement within the same chart

#### Scenario: Smart date range default
- **WHEN** Phase 1 started Apr 1 and current date is Jun 15
- **THEN** the default view starts from Apr 1 (current cycle), not from all-time

#### Scenario: Zoom toggle
- **WHEN** user clicks a zoom toggle
- **THEN** the Volume Trend chart rescales to the selected range

#### Scenario: Training Load per Run chart removed
- **WHEN** the Training tab renders
- **THEN** there is no standalone Training Load per Run chart; load data appears in Last 7 Days card headers

### Requirement: Event annotations on time-series charts
All time-series charts (VO2max, weight, training load, volume, speed_per_bpm, cadence) SHALL display event annotations as vertical markers at key dates. Event sources: races (from `run_type = 'race'`), training gaps (> 7 days no activity), phase transitions (from `training_phases`), calibration changes (from `calibration`), goal milestones (from `goal_log`). Markers are subtle (thin vertical line) with labels on hover via Chart.js annotation plugin.

#### Scenario: Race annotation on VO2max chart
- **WHEN** a HM race occurred on Oct 19 and VO2max peaked at 51
- **THEN** a vertical marker labeled "HM Race" appears at Oct 19 on the VO2max chart

#### Scenario: Gap annotation
- **WHEN** a 100-day training gap occurred Nov-Feb
- **THEN** a shaded region labeled "100d gap" appears on time-series charts

#### Scenario: Phase transition annotation
- **WHEN** Phase 1 → Phase 2 transition on Jun 1
- **THEN** a vertical marker labeled "Phase 2 start" appears on all time-series charts

### Requirement: Body tab shows recovery and physiology (last 14-21 days)
The Body tab SHALL display recent-state data (last 14-21 days, configurable): readiness+RHR+HRV combo chart (readiness bars safety-colored, RHR line, HRV dashed line), sleep composition stacked bars (deep/REM/light) with average annotations, **sleep quality mismatch flags** (Garmin hours vs subjective quality), weight trend (with race target and event annotations), stress vs body battery chart.

#### Scenario: Sleep quality mismatch
- **WHEN** Garmin reports 8h sleep but checkin sleep_quality is "Poor"
- **THEN** that day's sleep bar has a warning badge: "8h but felt Poor"

#### Scenario: Recovery charts render
- **WHEN** 16 days of daily_health data
- **THEN** all Body tab charts render with data points

### Requirement: Fitness tab shows performance trends (last 90 days, smart zoom)
The Fitness tab SHALL display last 90 days (with zoom toggle): (1) **speed_per_bpm trend** as the hero chart (dual lines: raw + Z2-filtered, higher = better, with peak reference and event annotations — this IS the fitness signal), (2) VO2max trend (area chart with sub-4:00 reference line and event annotations), (3) zone distribution by training TIME vs **active phase targets** (not fixed 80/20), (4) cadence trend with low-threshold reference (165 spm), (5) **race prediction** (Riegel + VDOT range display with confidence), (6) **RPE: predicted vs actual time series** (dual lines over time, widening gap = accumulating fatigue), (7) training gaps with duration and fitness impact annotation.

#### Scenario: Speed_per_bpm as hero chart
- **WHEN** the Fitness tab is opened
- **THEN** the speed_per_bpm trend is the largest, most prominent chart — it's the primary fitness signal

#### Scenario: Zone distribution vs phase targets
- **WHEN** active Phase 1 has z12_pct_target: 90 and actual is 72%
- **THEN** the zone chart compares actual to Phase 1 target (90%)

#### Scenario: RPE predicted vs actual over time
- **WHEN** 10+ runs have RPE data
- **THEN** a dual-line chart shows predicted RPE (from HR zone) vs actual RPE (from check-in) over time. Widening gap = fatigue accumulation warning.

#### Scenario: Race prediction range
- **WHEN** a recent HM race exists and VO2max is 49
- **THEN** display: "Riegel (from Oct HM): ~3:52, VDOT (VO2max 49): ~3:55, post-gap estimate: ~4:10-4:15" with confidence explanation

#### Scenario: Cadence trend with threshold
- **WHEN** 10+ runs with cadence
- **THEN** cadence trend line with 165 spm reference and annotation of runs below threshold

### Requirement: ACWR gauge prominently displayed
The ACWR gauge SHALL appear on BOTH the Today tab and the Body tab. It uses the safety palette (green 0.8-1.3, yellow 1.3-1.5, red >1.5 or <0.6) and shows the current value with a mini trend line of the last 4-6 weeks.

#### Scenario: ACWR danger zone
- **WHEN** current ACWR is 1.6
- **THEN** gauge shows red with: "Training spike detected. Reduce load this week."

### Requirement: Coach tab displays stored coaching insights
The Coach tab SHALL read from `reports/coaching.json` and render insight boxes (type/title/body), generation timestamp, and stale indicator. Coaching operates on a **weekly cadence** — it is a structured weekly review artifact, not a reactive post-sync output. Staleness SHALL be determined by age: coaching notes are stale when `report_date` is more than 7 days ago, NOT when `report_date` is before the last sync. This reflects the coaching model: most Claude interactions are ephemeral conversations (pre-run go/no-go, post-run questions); coaching notes are the weekly summary.

#### Scenario: Current coaching (within 7 days)
- **WHEN** coaching.json exists and report_date is 3 days ago
- **THEN** insight boxes rendered with timestamp, no stale indicator — even if sync has run since

#### Scenario: Stale coaching (older than 7 days)
- **WHEN** coaching.json report_date is 9 days ago
- **THEN** stale warning shown: "Last coaching review was 9 days ago. Ask Claude for a weekly review."

#### Scenario: No coaching
- **WHEN** coaching.json does not exist
- **THEN** placeholder with instructions

### Requirement: Metric definitions use progressive disclosure
Metric definitions SHALL be collapsed by default, shown via a small `ⓘ` icon next to each chart title. Clicking the icon expands a contextual definition that references the user's actual data, not generic text. Example: "Your VO2max is 49, which predicts a ~3:55 marathon. At your peak (53) you could run ~3:35. For sub-4:00 at your weight, you need ≥50."

#### Scenario: Definition collapsed by default
- **WHEN** a chart is displayed
- **THEN** only the chart title and a small `ⓘ` icon are visible; the definition is hidden

#### Scenario: Definition expanded with context
- **WHEN** user clicks `ⓘ` next to the VO2max chart
- **THEN** a contextual definition appears referencing the user's current VO2max, peak, and what the number means for their specific goal

### Requirement: Week-over-week comparison
The week-over-week comparison SHALL be absorbed into the Last 7 Days hero card as a subtitle sentence generated by `generate_wow_sentence()`. There SHALL NOT be a standalone WoW section or card on the Training tab. The comparison SHALL use **rolling 7-day windows**: the last 7 days vs the prior 7 days (days -13 to -7). This eliminates the ISO-week boundary problem where Monday resets the comparison to zero. The narrative sentence shows: delta in total km, run count change, zone compliance change, and ACWR status.

#### Scenario: WoW as hero card subtitle (rolling)
- **WHEN** last 7 days: 28km, 4 runs, z12_pct 82% vs prior 7 days: 22km, 3 runs, z12_pct 75%
- **THEN** the hero card subtitle reads: "Volume up 27% to 28km, zone compliance improved from 75% to 82%."

#### Scenario: Monday is not a reset
- **WHEN** today is Monday, with a long run Saturday and easy run Sunday in the 7-day window
- **THEN** the subtitle includes those weekend runs in the current 7-day total, not a fresh-start comparison

### Requirement: Training phase progress display
The Today tab SHALL display the active training phase with: phase name, date range, targets vs current actuals as a multi-dimensional mini-scorecard (on/off track per dimension, safety-colored), and the journey timeline. The Training tab SHALL show phase-specific context on charts (phase boundary annotations).

#### Scenario: Active phase scorecard
- **WHEN** Phase 1 targets weekly_km [25,30] and current avg is 22
- **THEN** volume shows "22 km/wk" in yellow (below target 25-30)

### Requirement: Daily and weekly snapshot reports
`fit report` SHALL support `--daily` and `--weekly` flags for timestamped snapshots.

#### Scenario: Daily snapshot
- **WHEN** `fit report --daily` on 2026-04-05
- **THEN** `reports/2026-04-05.html` + `reports/dashboard.html` updated

#### Scenario: Weekly snapshot
- **WHEN** `fit report --weekly` during W14
- **THEN** `reports/2026-W14.html` + `reports/dashboard.html` updated

### Requirement: Report generation is cron-friendly
`fit report` SHALL exit 0 on success, no interactive prompts, writes only to reports directory.

#### Scenario: Cron execution
- **WHEN** `fit report --daily` by cron with no TTY
- **THEN** silent generation, exit 0

### Requirement: Stress vs Body Battery chart on Body tab
The Body tab SHALL display a dual-line chart showing average stress level and body battery peak over the last 21 days. Battery is rendered as a filled area (green), stress as a red line. This shows the interplay between energy reserves and physiological stress.

### Requirement: ACWR trend chart on Body tab
The Body tab SHALL display an ACWR bar chart over all weeks with data. Each bar is safety-colored (green 0.8-1.3, yellow 1.3-1.5, red >1.5). Horizontal annotation lines mark the safe range (0.8, 1.3) and danger threshold (1.5).

### Requirement: Marathon prediction trend on Fitness tab
The Fitness tab SHALL display a monthly marathon prediction trend line using VDOT estimates from monthly average VO2max. Y-axis is reversed (lower = faster). A horizontal annotation line marks the sub-4:00 target (240 minutes).

### Requirement: RPE chart uses Garmin Training Effect as proxy
The Fitness tab RPE chart SHALL use Garmin's `aerobic_te` (Training Effect, 1-5 scale) mapped to RPE 1-10 scale (TE * 2) as the "predicted" effort line. When check-in RPE data exists, a second "actual" line is overlaid. The gap between lines indicates fatigue accumulation.

### Requirement: Sleep quality mismatch flags on Body tab
The dashboard SHALL detect and display sleep quality mismatches: cases where Garmin reports ≥7h sleep but the check-in records "Poor" quality (possible stress/disruption), or <6h sleep but "Good" quality (monitor for cumulative deficit). Mismatches are shown as warning badges in the sleep section.

### Requirement: Contextual metric definitions with user data
Each chart's info icon (`i`) SHALL expand a definition that references the user's actual current values, not generic text. For example: "Your VO2max is 49, which predicts a ~3:55 marathon. For sub-4:00 at ~75kg, you need ≥50." Definitions are generated in `generator.py` using live DB queries.

### Requirement: Dashboard color constants
The generator SHALL define color constants matching the two-palette system: `SAFE = "#22c55e"`, `CAUTION = "#eab308"`, `DANGER = "#ef4444"` (safety palette), `Z12 = "#38bdf8"`, `Z3 = "#f59e0b"`, `Z45 = "#f97316"` (intensity palette), `ACCENT = "#818cf8"` (highlight/info).

## Post-Phase 2 Additions

### Requirement: Decomposed generator as sections/ package
The dashboard generator SHALL be decomposed into a `fit/report/sections/` package: `engine.py` (main `generate_dashboard()` orchestrator + template loading, ~117 lines), `cards.py` (status cards, milestone cards, alert cards), `charts.py` (all chart data generation), `predictions.py` (race prediction + pacing strategy section). The top-level `generator.py` becomes a thin wrapper re-exporting from sections/.

#### Scenario: Modular imports
- **WHEN** code imports from `fit.report.generator`
- **THEN** it gets the same API as before (backward compatible), delegating to sections/ internally

### Requirement: All sections always render with empty states
Every dashboard section SHALL always render, even when data is insufficient. Empty states show actionable instructions (e.g., "Need 4+ weeks of data for efficiency trends", "Run `fit checkin` to enable RPE tracking"). Sections are NEVER hidden silently.

#### Scenario: No check-in data
- **WHEN** no check-ins exist
- **THEN** RPE chart renders with message: "No check-in data. Run `fit checkin` after training to enable RPE tracking."

#### Scenario: Insufficient correlation data
- **WHEN** fewer than 20 check-ins exist
- **THEN** correlation section shows a progress bar toward 20 check-in threshold: "12/20 check-ins — 8 more needed for correlation analysis"

### Requirement: Trend badges inside Race Anchor Card
Trend badges (efficiency, VO2max, Z2 compliance, volume) SHALL be rendered inside the Race Anchor Card on the Today tab, not as a standalone section. This consolidates race-focused context in one place.

#### Scenario: Trend badges in race card
- **WHEN** race anchor card renders with sufficient trend data
- **THEN** pill badges appear within the card below the race countdown

### Requirement: Status cards show action text
Status cards SHALL include action text based on current state: "Easy run or rest" when recovery recommended, "Build volume" during base phase, "Quality session OK" when readiness is high.

#### Scenario: Recovery status card
- **WHEN** readiness < 50
- **THEN** status card shows action text: "Easy run or rest"

### Requirement: ACWR spike annotations scoped to ACWR chart only
ACWR spike annotations (top 3 highest values) SHALL appear ONLY on the ACWR chart, not on all time-series charts. Previously annotations flooded unrelated charts.

#### Scenario: ACWR spikes on ACWR chart
- **WHEN** ACWR chart renders with historical spikes
- **THEN** top 3 ACWR spikes are annotated on the ACWR chart only

#### Scenario: Other charts unaffected
- **WHEN** efficiency or VO2max charts render
- **THEN** no ACWR spike annotations appear on those charts

### Requirement: ACWR y-axis capped at 3.0
The ACWR chart y-axis SHALL be capped at 3.0 to prevent outlier spikes from compressing the meaningful range (0.6-1.5).

#### Scenario: Extreme ACWR value
- **WHEN** ACWR has a value of 5.0 (after long gap)
- **THEN** y-axis max is 3.0, the spike is clipped at the top

### Requirement: First Z2 run annotation marker
Training charts SHALL show an annotation marker on the date of the first Z2 run in the dataset. This marks the beginning of aerobic base building.

#### Scenario: First Z2 run marked
- **WHEN** the first Z2 run occurred on 2026-03-15
- **THEN** a vertical annotation "First Z2 run" appears on training charts at that date

### Requirement: Run Timeline gap markers
The Run Timeline visualization is replaced by the Last 7 Days per-run detail cards. Gap markers for training breaks (>14 days) SHALL appear as annotations on the Volume Trend chart instead of inline in a timeline. The Volume Trend chart SHALL show a shaded region labeled with the gap duration (e.g., "100d gap") for any break exceeding 14 days.

#### Scenario: Long training gap on volume chart
- **WHEN** there is a 100-day gap between training weeks
- **THEN** the Volume Trend chart shows a shaded region spanning the gap, labeled "100d gap"

#### Scenario: No standalone run timeline
- **WHEN** the Training tab renders
- **THEN** there is no horizontal bar timeline; recent runs appear as Last 7 Days cards

### Requirement: WoW as narrative sentence
The week-over-week narrative sentence generated by `generate_wow_sentence()` SHALL be updated to accept rolling 7-day window data instead of ISO-week data, and rendered as the subtitle of the Last 7 Days hero card. There SHALL NOT be a standalone WoW card or section.

#### Scenario: WoW narrative in hero card (rolling)
- **WHEN** rolling 7d data shows volume +27%, z12_pct 75%->82%
- **THEN** the hero card subtitle reads: "Volume up 27% to 28km, zone compliance improved from 75% to 82%."

#### Scenario: First 7 days of training
- **WHEN** no prior 7-day data exists for comparison (fewer than 14 days of history)
- **THEN** the hero card subtitle reads "First tracked week" or is omitted

### Requirement: Body tab opening narrative
The Body tab SHALL have an opening narrative paragraph generated by `generate_body_summary()` that connects recovery signals: sleep, HRV, readiness, weight trends. Example: "Recovery signals mixed: HRV trending up but sleep quality dropped this week. Weight stable at 76.2kg."

#### Scenario: Body summary rendered
- **WHEN** Body tab renders with health data
- **THEN** opening paragraph connects HRV, sleep, readiness, and weight into a narrative sentence

### Requirement: Prediction range prominent with collapsed detail
The race prediction SHALL show the prediction range prominently (e.g., "3:48-4:05") with the detail table (per-race extrapolations, VDOT, confidence breakdown) collapsed by default behind a "Show details" toggle.

#### Scenario: Prediction display
- **WHEN** prediction section renders
- **THEN** range "3:48-4:05" is prominent, detail table is collapsed

### Requirement: Stale coaching banner
When coaching notes are stale (older than 7 days), the Coach tab SHALL show a full-width banner. The banner message SHALL reflect weekly cadence, not sync freshness. The banner includes regeneration instructions referencing the weekly coaching workflow.

#### Scenario: Stale coaching banner
- **WHEN** coaching.json report_date is more than 7 days ago
- **THEN** full-width banner: "Last coaching review was 9 days ago. Time for a weekly check-in — ask Claude to review your week."

#### Scenario: Recent coaching after multiple syncs
- **WHEN** coaching.json report_date is 2 days ago but 3 syncs have occurred since
- **THEN** no stale banner — coaching is fresh on a weekly cadence

### Requirement: Correlation empty state with progress bar
When insufficient check-in data exists for correlations, the correlation section SHALL show a progress bar toward the 20 check-in threshold, not just a text message.

#### Scenario: Partial progress
- **WHEN** 12 check-ins exist (threshold is 20)
- **THEN** progress bar shows 12/20 with text: "8 more check-ins needed for correlation analysis"

### Requirement: Run type color palette
Run types SHALL use specific colors: easy=#60a5fa, recovery=#93c5fd, long=#34d399, tempo=#fbbf24, intervals=#f97316, race=#c084fc. These are consistent across all charts (run timeline, run type breakdown, training load).

#### Scenario: Color consistency
- **WHEN** a tempo run appears in both run timeline and run type breakdown
- **THEN** both charts use #fbbf24 for tempo

### Requirement: Per-run cards display RPE, feel, and compliance from Garmin
The dashboard's last-7-days run cards SHALL display the Garmin-imported `rpe` (1-10), `feel` (1-5), and `compliance_score` (0-100) for each running activity when present. The fields SHALL render in the activity detail line alongside training_load, with `—` placeholders when NULL. Feel SHALL be rendered as a 5-point label (e.g., "Bad/Poor/Neutral/Good/Great") for readability, while RPE and compliance render as numeric values.

#### Scenario: Activity has all three fields populated
- **WHEN** a run has `rpe = 7`, `feel = 4`, `compliance_score = 95`
- **THEN** the card displays `RPE 7 · Feel: Good · Compliance 95%` alongside other metrics

#### Scenario: Activity has none of the fields populated
- **WHEN** a run has `rpe`, `feel`, and `compliance_score` all NULL
- **THEN** the card displays `RPE — · Feel — · Compliance —` (or omits these labels entirely; rendering MUST be consistent across runs)

#### Scenario: Partial fields populated
- **WHEN** a run has `rpe = 5` but `feel` and `compliance_score` are NULL
- **THEN** the card displays the available value and `—` for missing ones (no visual gap or layout shift)

### Requirement: Chart.js annotation collision handling
When multiple annotations target the same or nearby data points, the system SHALL stack annotations vertically with 2px offset per layer. Maximum 3 annotations per point; beyond that, collapse into a summary tooltip showing all factors.

#### Scenario: Three annotations on same point
- **WHEN** a run has "worst efficiency", "heat affected", and "after poor sleep" annotations
- **THEN** three markers stacked vertically with 2px offset each

#### Scenario: More than 3 annotations
- **WHEN** a run has 4+ overlapping annotations
- **THEN** 3 are shown stacked, remainder collapsed into tooltip: "4 factors"
