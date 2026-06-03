## ADDED Requirements

### Requirement: Each tab has one defined job
Every dashboard tab SHALL have a single, stated purpose, and its content SHALL match that purpose: **Overview** = the synthesis (on-track verdict + next move), **Readiness** = recovery & freshness, **Training** = fitness build & plan execution, **Profile** = physiology & the race-day forecast, **Coach** = the narrative & levers. Content that belongs to a tab's job SHALL live in that tab, not be duplicated elsewhere.

#### Scenario: Detail lives in its owning tab, not on Overview
- **WHEN** the dashboard renders
- **THEN** objectives are on Training, the physiology engine detail on Profile, recovery sparklines on Readiness, and the coaching narrative on Coach — Overview shows only summaries of these, not their full detail

### Requirement: Overview is a hub — summary plus drill-in links
The Overview SHALL be a routing hub: a goal headline (predicted time + interval + P(goal) + countdown on the phase timeline, from `marathon-durability-model`), the current limiter, the single highest-priority action/attention item, and a domain-summary strip — one card each for Fitness, Recovery, Physiology, and Coach. Each summary card SHALL show the one number that matters plus an explicit link into the tab that owns it.

#### Scenario: Headline is the single forecast source
- **WHEN** the Overview headline renders
- **THEN** it shows the model's predicted time + 90% interval + P(goal), the same figures the Profile forecast and the coaching context use (no separately-computed prediction)

#### Scenario: Domain cards link to their tab
- **WHEN** the Overview domain strip renders
- **THEN** the Fitness / Recovery / Physiology / Coach cards each carry an explicit "open in <Tab>" link to Training / Readiness / Profile / Coach respectively

### Requirement: Cross-tab drill-in routes through the tab activator
A drill-in link SHALL activate the target tab and scroll to the named section using the same `showTab` path the tab buttons use — so charts in the target tab still initialise via the reveal-all-during-init pass and never render at 0×0.

#### Scenario: Deep link does not break hidden-tab charts
- **WHEN** the athlete clicks a "→ Profile" link that targets a charted section
- **THEN** the Profile tab is shown via `showTab` (not a raw anchor jump), its charts are sized correctly, and the view scrolls to the target section

#### Scenario: Target section exists
- **WHEN** a drill-in link names a section anchor
- **THEN** that anchor exists in the target tab (no dead links)
