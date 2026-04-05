## ADDED Requirements

### Requirement: Cross-domain correlation analysis using Spearman rank
The system SHALL compute correlations using **Spearman rank correlation** (not Pearson) as default, since most pairs involve ordinal (sleep_quality) or skewed (alcohol) data. Pearson MAY be used alongside for continuous-continuous pairs. Results stored in a `correlations` table with: metric_pair, lag_days, spearman_r, pearson_r, p_value, sample_size, confidence (high/moderate/low), status (computed/insufficient_data), last_computed, data_count_at_compute.

Predefined pairs:
- alcohol → next-day HRV (lag 1)
- alcohol → next-day RHR (lag 1)
- alcohol → same-night sleep_quality (lag 0)
- sleep_duration + sleep_quality → next-day HR-at-pace (lag 1)
- weight → RPE at constant pace (lag 0, weekly)
- temp_at_start_c → speed_per_bpm (lag 0, per run)
- water_liters → next-day HRV (lag 1)

Uses **differenced values** for trended metrics (change in HRV vs alcohol, not raw HRV) to avoid autocorrelation.

#### Scenario: Spearman computed for ordinal pair
- **WHEN** alcohol (0-3 drinks, skewed) and next-day HRV are correlated
- **THEN** Spearman rank correlation is used (not Pearson), producing a valid coefficient for non-normal data

#### Scenario: Minimum sample size 20 for reporting
- **WHEN** a correlation pair has 15 data points
- **THEN** it is stored as status='insufficient_data' with sample_size=15, not displayed in dashboard

#### Scenario: Minimum sample size 30 for coaching context
- **WHEN** a correlation has n=22 (above 20, below 30)
- **THEN** it appears in the dashboard as "preliminary" but is NOT included in `get_coaching_context()`

#### Scenario: Confounders noted
- **WHEN** temperature → drift correlation is displayed
- **THEN** a note explains: "May be confounded by seasonal fitness changes"

### Requirement: Real-time alerts engine
A separate `fit/alerts.py` module SHALL run simple threshold checks on fresh data after each sync. This is a **rule engine**, not a correlation. Rules fire immediately when conditions are met.

Rules:
- 2+ drinks last night AND today's HRV dropped >15% below 7-day baseline → "Alcohol impact detected"
- Z2 compliance < 50% over rolling 2 weeks → "All runs too hard"
- Weekly volume increase > 10% AND < 8 consecutive training weeks → "Volume ramp guard"
- Readiness < 30 AND planned workout is quality session → "Recommend swap to easy/rest"
- Long run distance trend projection won't reach 32km by peak phase start → "Long run progression too slow"

#### Scenario: Alcohol + HRV drop alert
- **WHEN** `fit sync` ingests today's HRV at 22ms and yesterday's checkin had alcohol=3
- **THEN** an alert fires: "HRV 22ms (↓18% from 7d avg 27ms) — 3 drinks last night. Rest day recommended."

#### Scenario: Alert stored and surfaced
- **WHEN** alerts fire
- **THEN** they are stored in an `alerts` table and included in `get_coaching_context()` and the Today tab headline

### Requirement: Correlation results surfaced on Coach tab with visual storytelling
Correlations SHALL be displayed on the **Coach tab** (not Fitness — already 6+ charts). Visualization: **diverging bar chart** (bars anchored at zero, green for positive effects, red for negative, length = |r|). Labels in plain language ("Alcohol worsens next-day HRV") not r-values. Click to expand **scatter plot drill-down** with trend line (using existing progressive disclosure pattern).

Additional: **before/after comparison bars** for the strongest correlations (e.g., "avg HRV after 0 drinks: 31ms" vs "avg HRV after 1+ drinks: 24ms").

Data freshness indicator: show "N new data points since last compute" if correlations are stale.

#### Scenario: Dashboard correlation bar chart
- **WHEN** 5+ correlations are computed with n >= 20
- **THEN** the Coach tab shows diverging bars with plain-language labels and effect sizes

#### Scenario: Scatter plot drill-down
- **WHEN** user clicks a correlation bar
- **THEN** an inline scatter plot expands showing individual data points + trend line

### Requirement: fit correlate command with stale detection
`fit correlate` SHALL recompute all correlations. Track `data_count_at_compute` to skip pairs whose underlying data hasn't changed. Also run automatically at the end of `fit sync`.

#### Scenario: Skip unchanged pairs
- **WHEN** `fit correlate` runs and alcohol→HRV has the same data count as last compute
- **THEN** that pair is skipped (not recomputed)
