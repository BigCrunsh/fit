## 1. Tab order + job subtitles (mechanical, low-risk)

- [x] 1.1 `generator.py`: reorder the `tabs` list to triage order — `overview · readiness · training · profile · coach` — and add a one-line `job` (the decision it supports) to each.
- [x] 1.2 `dashboard.html`: render each tab's `job` as a subtitle; reuse a design-system text style.
- [x] 1.3 Suite green; `fit report` builds (new tab order + subtitles present).

## 2. `showTab` — target section + URL hash

- [x] 2.1 Extend `showTab(id, btn)` → `showTab(id, btn, section=null)`: keep the reveal-all-then-restore pass (charts init at real size), then scroll to `section`, and set `location.hash` to `id` (or `id/section`).
- [x] 2.2 On load: a valid hash routes through `showTab`; unknown/empty → `overview`.
- [x] 2.3 Reusable `→ <Tab>` link affordance (calls `showTab`, never a raw anchor jump) + its `design_system.css` component.

## 3. Overview-hub builder (the story logic)

- [x] 3.1 `_overview_hub(conn)` in `cards.py`, reusing existing computed values (no new compute). Produces:
- [x] 3.2 **Goal verdict** — predicted time + 90% interval + P(goal) (the model output, same as Profile/coaching) + a one-line reading: *most-likely + range* (never a single false-certain time) and the Δ since last week.
- [x] 3.3 **Limiter** — the domain with the largest gap *relative to its phase-target/goal-required level* (fitness/durability/effort/recovery); a **concrete** lever (a session/volume/recovery change, not a restatement); link to the owning tab + to the **next workout** that delivers the lever when one is planned; on-track → reframe as *what to protect*. The lever in the verdict reading IS this limiter (one story).
- [x] 3.4 **Single next action** by fixed precedence: safety (injury/illness) > consistency (missed/at-risk plan) > the limiter's lever.
- [x] 3.5 **Four status cards** (Fitness→Training, Recovery→Readiness, Physiology→Profile, Coach→Coach): value + trend (over the domain's canonical window per the window policy) + status as **icon/label + `safe`/`caution`/`danger` colour** (not colour-only); colour only against a defensible reference, else **neutral**; compact + a `→ <Tab>` link.
- [x] 3.6 Wire `_overview_hub` into the report context (`generator.py`).

## 4. Recompose Overview + relocate detail + lead the detail tabs

- [x] 4.1 Overview: the synthesis hub is the headline — verdict (line 1) + limiter (line 2) = the two-line answer, then the single next action and the four status cards; the phase-timeline countdown + prediction-trend card sits directly below as the timeline/evidence. Alerts stay at top. (Hub-as-headline with the countdown card adjacent, rather than fusing days-left into the verdict line — flagged for the visual review.)
- [x] 4.2 Relocated: full *Fitness Profile* snapshot sparklines + *Your Physiology* anchors → **Profile** (`prof-snapshot`, `prof-physiology`); *Objectives* → **Training** (`train-objectives`; the Overview copy was a duplicate of the Training objectives, so dropped not moved); *Checkpoints* → **Coach** (`#checkpoints-table`, rendered by id from the trend IIFE); *Coach's Take* → **Coach** (`coach-insights`), Overview keeps a one-line summary + link. *Next Workouts* dropped (Training "Next Up" is canonical). Every hub target has a stable, unique anchor.
- [x] 4.3 Each detail tab leads with its one-line answer: Profile "what will race day give?" (forecast), Training "am I doing the work?" (7-day km + plan%), Readiness "can I absorb training?" (body summary), Coach "the plan & why" (top insight) — `.tab-lead`, above the charts.
- [x] 4.4 **Graceful empty/degraded Overview**: hub degrades to a neutral strip / `hub-empty` prompt (test_overview_hub); Profile & Coach leads have an empty-state else; thin/empty-DB render builds without blanks or NaNs (test_dashboard_ia + the empty-DB smoke test).

## 5. Consistency

- [x] 5.1 The Overview verdict reuses `_marathon_forecast(conn)` — the *same* builder the race card, the Profile tab and the coaching context read; no separately-computed prediction (verified).
- [x] 5.2 The Fitness card's volume == the Training-tab figure: `compute_rolling_week().run_km` == `_last_7_days_hero().volume_km` (one canonical 7-day signal; verified equal on live data).

## 6. Tests (template/structure guards — no compute change)

- [x] 6.1 Overview: the verdict shows time + interval + P(goal) + a range-bearing reading (test_overview_hub); the four domain `→` links resolve (test_dashboard_ia `TestNoDeadLinks`).
- [x] 6.2 Limiter = largest *relative* gap (not lowest raw value); names a concrete lever; verdict's lever == the limiter (test_overview_hub `TestPickLimiter` + verdict reading).
- [x] 6.3 Status uses icon/label + colour (`_HUB_STATUS_ICON` + `.hub-*` colour classes) and is **neutral** when no defensible reference exists (test_overview_hub).
- [x] 6.4 Each relocated detail section lives under its owning tab and is gone from the Overview; each detail tab opens with a one-line lead (test_dashboard_ia).
- [x] 6.5 `showTab` is the 3-arg target+hash path, the reveal-all-then-restore pass is present (no 0×0), `routeFromHash` runs on load, and every `→` link target anchor exists & is unique (test_dashboard_ia).
- [x] 6.6 Graceful empty: hub → neutral/empty prompt, no blanks/NaNs (test_overview_hub integration + empty-DB render).
- [x] 6.7 Full suite green (1111); `ruff` clean; `fit report` builds (thin/empty-DB render exercises the forecast-absent degrade path).
