## ADDED Requirements

### Requirement: The Overview reads at a glance — verdict and limiter, one story
The Overview SHALL answer two questions in its first two lines — *am I on track?* and *what's the one thing to do?* — and SHALL carry nothing beyond what serves them. The **primary glance** is the **goal verdict** (the model's predicted time + 90% interval + P(goal) on the phase-timeline countdown, plus a one-line plain-language reading — the *most-likely outcome and its range*, never a single false-certain time, and how it has moved since last week) coupled with the **limiter**. These are **one reconciled story**: the lever named in the verdict IS the limiter, so the dashboard states a *single* "one thing to do", never two competing ones. Below the primary glance sit the single highest-priority **action** and a **secondary** four-card status strip; everything deeper lives in its owning tab, reachable by a link. The single action SHALL follow a fixed precedence — **safety (injury/illness) > consistency (missed/at-risk plan) > the limiter's lever** — so "the one move" is deterministic. Readability of this tab is the priority: the answer in two lines, detail a click away.

#### Scenario: Verdict and limiter are one story, from one source
- **WHEN** the Overview headline renders
- **THEN** it shows the predicted time + 90% interval + P(goal) AND a one-line reading whose lever **is** the current limiter — one "thing to do", not two competing ones — and the figures match the model output the Profile and the coaching context use (no separately-computed prediction)

#### Scenario: The reading conveys uncertainty, not false certainty
- **WHEN** the predicted time is ~3:50 with a 90% interval of 3:42–3:58
- **THEN** the reading states a most-likely outcome and its range (e.g. "≈3:50, likely 3:42–3:58") and how it moved since last week — not a single confident "3:50" (consistent with interval ≠ race-day spread)

#### Scenario: The single action follows the precedence
- **WHEN** a safety alert, an at-risk plan, and the limiter's lever all apply at once
- **THEN** the single highlighted next action is the safety one (safety > consistency > the limiter's lever)

#### Scenario: The Overview carries only synthesis
- **WHEN** the Overview renders
- **THEN** it contains the verdict, the limiter, the next action, and the secondary status strip — and NOT the full fitness-profile dimension sparklines, the physiology anchors, the objectives, or the coaching narrative (each lives in its owning tab, linked)

### Requirement: The current limiter is the coaching headline
The Overview SHALL **highlight** the single most-important limiter — the domain with the largest gap **relative to its phase-target or goal-required level** among fitness, durability, effort-efficiency, and recovery (a *relative* gap on a common scale, not the lowest absolute number). This is the *first thing to act on*, not the only problem: **every** domain below its target SHALL remain visible via its `caution`/`danger` status in the strip — the limiter is the highlight, the strip is the full picture (nothing hidden). The limiter SHALL be the lever named in the goal verdict (one reconciled story), stated in one line — what it is and a **concrete** lever (a specific session/volume/recovery change, not a restatement of the deficit) — with a link to the owning tab and, where one exists, a link to the **next workout that delivers that lever** (limiter → lever → session, one loop). When the forecast is on-track, the limiter SHALL reframe as *what to protect* rather than a deficit alarm.

#### Scenario: All below-target domains stay visible; only the top is highlighted
- **WHEN** two domains are below target (e.g. durability 20% under, recovery 8% under)
- **THEN** both show `caution`/`danger` in the status strip (neither hidden) AND durability is the highlighted limiter/lever (largest normalized gap) — first to act on, not the only one flagged

#### Scenario: The lever is concrete and links to the session that delivers it
- **WHEN** the limiter is durability
- **THEN** the lever names a concrete action (e.g. "extend the long run toward 28 km") and, if such a session is planned, links to that next workout — not a vague "improve durability"

#### Scenario: The limiter is the largest relative gap, not the lowest raw value
- **WHEN** fitness sits 5% under its target and durability 20% under its target
- **THEN** durability is named the limiter (largest relative gap), regardless of which has the lower raw number

#### Scenario: On-track reframes the limiter as what to protect
- **WHEN** the forecast verdict is on-track (P(goal) high)
- **THEN** the limiter line reads as the strength to maintain (e.g. "durability strong — keep the long runs"), still one lever, framed for the situation — not a contradicting alarm

### Requirement: Domain cards show value + trend + a shared, honest status encoding
The **secondary** four-card strip (Fitness → Training, Recovery → Readiness, Physiology → Profile, Coach → Coach) SHALL show each domain's current value, a compact trend direction, and a status — using **one shared encoding**, conveyed by an **icon/label AND colour** (the design-system `safe`/`caution`/`danger`; never colour alone, so it reads for colourblind users) so the four cards mean the same thing at a glance. A card SHALL colour its status ONLY against a defensible reference (phase target for fitness/load; goal-required for physiology; the established recovery thresholds for readiness/ACWR); with no defensible reference (e.g. no goal set) it SHALL show value + trend in a **neutral** state — never a judgment colour it cannot back. Trend SHALL use the domain's canonical window from the window policy (fitness-state = rolling-7d, history/cadence = ISO-week). Each card SHALL link to its owning tab and stay compact — not a detail panel.

#### Scenario: One status grammar across all four cards
- **WHEN** the four domain cards render
- **THEN** each uses the same encoding — an icon/label *plus* the `safe`/`caution`/`danger` colour (not colour alone) — tied to its on-track threshold, so a "Fitness ✓ on track" and a "Recovery ✓ on track" read identically

#### Scenario: No defensible reference → neutral, not a false colour
- **WHEN** a domain has no defensible target (e.g. Physiology with no goal race set)
- **THEN** its card shows value + trend in a neutral state — not a green/amber/red implying an on/off-track judgment it cannot justify

#### Scenario: A card is a summary, not the detail
- **WHEN** a domain card renders
- **THEN** it shows one value + trend + status + link — not the underlying chart or dimension breakdown (that lives in the owning tab)

### Requirement: The Overview degrades gracefully for thin or goalless data
When there is no goal race, the model is not fit, or history is too thin for a verdict/limiter, the Overview SHALL show a clear "what to do to light this up" state (e.g. set a goal race, log more runs) — never blanks, NaNs, or a broken layout — and the forecast SHALL degrade to the calibrated-VDOT anchor estimate (loud, no interval) per the forecast contract.

#### Scenario: New athlete / no goal set
- **WHEN** no goal race is registered and the model is not fit
- **THEN** the Overview shows the anchor-based estimate (or a prompt to set a goal / log runs) and a neutral status strip — not empty cards, NaNs, or a broken layout

### Requirement: Each tab has one defined job
Every dashboard tab SHALL have a single, stated purpose — framed as the decision it supports — and its content SHALL match that purpose: **Overview** = synthesis (on track? + the one move), **Readiness** = can I absorb training (recovery & freshness), **Training** = am I doing the work (fitness build & plan execution), **Profile** = who am I + what will race day give (physiology, dimensions, anchors, the forecast/decomposition), **Coach** = the plan & why (narrative, levers, correlations). Content that belongs to a tab's job SHALL live in that tab, not be duplicated elsewhere.

#### Scenario: Detail lives in its owning tab, not on Overview
- **WHEN** the dashboard renders
- **THEN** the objectives are on Training, the physiology engine + fitness-dimension detail on Profile, the recovery sparklines on Readiness, and the coaching narrative on Coach — the Overview shows only summaries of these, not their full detail

### Requirement: Each detail tab leads with its answer, then the evidence
A detail tab (Readiness, Training, Profile, Coach) SHALL open with a one-line answer to its own question — the lead — and only then present the supporting charts and detail. Relocating detail into the right tab is necessary but not sufficient: a drill-in SHALL land on a tab that states its conclusion first, not an unordered pile of cards.

#### Scenario: A drill-in lands on a conclusion, not a card pile
- **WHEN** the athlete drills into the Readiness tab
- **THEN** it opens with a one-line answer to "can I absorb training?" (e.g. "Recovered — readiness 82, HRV stable") above the supporting sparklines/charts — not a grid of metrics with no lead

### Requirement: Drill-in navigation routes through the tab activator
*(Supporting — navigation, not story.)* A drill-in link SHALL activate the target tab and scroll to the named section using the same `showTab` path the tab buttons use — so charts in the target tab still initialise via the reveal-all-during-init pass and never render at 0×0 — and SHALL update the URL hash so the deep link is shareable and survives reload.

#### Scenario: Deep link does not break hidden-tab charts
- **WHEN** the athlete clicks a "→ Profile" link that targets a charted section
- **THEN** the Profile tab is shown via `showTab` (not a raw anchor jump), its charts are sized correctly, the view scrolls to the target section, and the URL hash reflects the destination

#### Scenario: Target section exists
- **WHEN** a drill-in link names a section anchor
- **THEN** that anchor exists in the target tab (no dead links)
