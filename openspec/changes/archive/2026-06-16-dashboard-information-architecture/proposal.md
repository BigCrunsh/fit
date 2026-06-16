## Why

The dashboard has five tabs but no clear information architecture. The **Overview is a dumping ground** (attention panel, physiology card, objectives, next workouts, readiness sparklines, checkpoints, coach's take, concepts glossary) — it duplicates detail that belongs in the deep tabs instead of *summarizing and routing* to them. Tabs lack a single stated job, the same metric (e.g. load/CTL) shows up in several places without a shared story, and there is **no way to drill from a summary into the tab that owns it** — you have to hunt.

`marathon-durability-model` is the trigger to fix this: it gives the dashboard a *spine* (fitness / durability / effort → a race-day forecast). Organizing the tabs around that spine — with the Overview as a hub that links into each detail tab — turns a pile of cards into one navigable story.

## What Changes

### Each tab gets one job

| Tab | The one question it answers | Owns |
|---|---|---|
| **Overview** | *Am I on track for the goal, and what's my next move?* | the synthesis: forecast + limiter + next action, **links out** |
| **Readiness** | *Can I absorb training — am I fresh & recovering?* | recovery + freshness (TSB = CTL−ATL), HRV/RHR/sleep/stress, injury risk |
| **Training** | *Am I doing the work?* | fitness build (CTL/load), volume, plan adherence, objectives |
| **Profile** | *Who am I as a runner — and what will race day give?* | engine + dimensions + anchors + the model's forecast/decomposition |
| **Coach** | *What's the plan, and why?* | the narrative, levers, correlations, coaching notes |

This is the coaching triage order (recovery → consistency → physiology/performance → synthesis), and **CTL is the thread** through all of them.

> Scope note: this change owns **co-locating the fitness dimensions with the model coefficients (β_d/φ/κ)** on the Profile tab — reassigned here from `marathon-durability-model` (its task was scoped to "confirm with user"; it's a tab-IA decision, not a model deliverable).

### Overview becomes a hub (summary + drill-in links), not a detail page

Readability of this tab is the priority — it answers *am I on track?* and *what's the one thing to do?* in its first two lines, and carries nothing else.

**Primary glance (the two-line answer):**
- **Goal verdict** = predicted time + interval + P(goal) + countdown on the phase timeline (the `marathon-durability-model` output — one source of truth), **plus a one-line plain-language reading**: on track, or the projected gap and the lever.
- **The limiter** = the lever in that verdict, named once: the domain with the largest gap *relative to its phase-target / goal-required level* (fitness / durability / effort-efficiency / recovery) → links to the owning tab. **Verdict and limiter are one reconciled story — a single "one thing to do", never two.**

**Below it (secondary):**
- **The single next action** — by fixed precedence: safety > consistency > the limiter's lever (deterministic).
- **A secondary status strip** — four cards (**Fitness** → Training, **Recovery** → Readiness, **Physiology** → Profile, **Coach** → Coach), each value + compact trend + a shared `safe`/`caution`/`danger` status (coloured only against a defensible reference, else neutral) + a `→ <Tab>` link. Compact summaries, never detail panels.

When there's no goal / unfit model / thin history, the Overview degrades to the anchor estimate + a "set a goal / log runs" prompt — never blanks.

### Detail moves out of Overview to the tab that owns it

- Objectives → **Training**; the "Your Physiology" card → **Profile**; readiness sparklines → **Readiness**; Concepts glossary → a help/footer (or collapsed); Checkpoints + Coach's Take → a one-line summary on Overview linking to **Coach**.

### Explicit cross-tab navigation

A reusable "→ open in <Tab>" affordance (anchor link) that activates the target tab and scrolls to the named section. Must cooperate with the existing chart-init-while-revealed flow (charts are built during the reveal-all pass, so deep-linking a hidden tab must not reintroduce the 0×0-chart bug).

### Consistency carried across tabs

CTL is one canonical load signal (Readiness freshness, Training build, model spend, Overview summary) — never contradictory; the forecast is one model output shared by Overview/Profile/Coach; durability is shown as two lenses (resilience drift-onset + `beta_d`); all charts keep the shared time-axis / phase-band / colour conventions.

## Capabilities

### Modified Capabilities
- `dashboard`: defines the per-tab job, restructures the Overview into a summary-and-links hub, relocates detail to the owning tabs, and adds explicit drill-in navigation between tabs.

## Impact
- **Code:** `fit/report/templates/dashboard.html` (Overview restructure + per-tab section moves + link affordance), `showTab()` JS (accept a target section to scroll to, preserving the reveal-during-init behaviour), `fit/report/sections/cards.py` (a small Overview-summary builder per domain), `design_system.css` (hub cards + the `→ Tab` link component).
- **Tests:** template guards (Overview contains the headline + the four domain links; detail sections live under their owning tab; `showTab` still reveals-all-then-restores; deep-link scroll target exists).
- **Data/Schema:** none.
- **Depends on:** `marathon-durability-model` for the Overview headline (forecast + P(goal)); degrades to the current prediction if the model isn't fit.

## Risks / Trade-offs
- **Losing information in the move.** Mitigation: nothing is deleted — detail relocates to its owning tab; Overview keeps a one-line summary + link to each.
- **Deep-link + hidden-tab charts.** Activating a tab via a link must use the same path as the tab buttons (charts already init while revealed); a link that bypasses it would hit the 0×0-chart bug we fixed. Mitigation: route links through `showTab`.
- **Over-summarizing.** Too terse an Overview hides things people relied on. Mitigation: keep the attention panel and next-workout prominent; summaries carry the one number that matters + the link.

## Resolved decisions (2026-06-11)
1. **Overview headline = the phase-timeline countdown chart** (goal verdict — predicted time + interval + P(goal) — on it); the domain summaries sit as cards below. One chart, the rest cards.
2. **Domain-summary strip = four cards** — Fitness · Recovery · Physiology · Coach (each one number + a `→ <Tab>` link); Training-execution folds into the Fitness card / next-action, not a fifth card.
3. **Drill-in links route through `showTab` AND update the URL hash** — deep links are shareable/bookmarkable and survive reload (charts still init via the reveal-all pass).
4. **Tabs reorder to the triage order** — Overview · Readiness · Training · Profile · Coach (recovery → consistency → physiology → synthesis) — and each tab shows its one-line job as a subtitle.
