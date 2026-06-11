## 1. Tab order + job subtitles (mechanical, low-risk)

- [x] 1.1 `generator.py`: reorder the `tabs` list to triage order — `overview · readiness · training · profile · coach` — and add a one-line `job` (the decision it supports) to each.
- [x] 1.2 `dashboard.html`: render each tab's `job` as a subtitle; reuse a design-system text style.
- [x] 1.3 Suite green; `fit report` builds (new tab order + subtitles present).

## 2. `showTab` — target section + URL hash

- [x] 2.1 Extend `showTab(id, btn)` → `showTab(id, btn, section=null)`: keep the reveal-all-then-restore pass (charts init at real size), then scroll to `section`, and set `location.hash` to `id` (or `id/section`).
- [x] 2.2 On load: a valid hash routes through `showTab`; unknown/empty → `overview`.
- [x] 2.3 Reusable `→ <Tab>` link affordance (calls `showTab`, never a raw anchor jump) + its `design_system.css` component.

## 3. Overview-hub builder (the story logic)

- [ ] 3.1 `_overview_hub(conn)` in `cards.py`, reusing existing computed values (no new compute). Produces:
- [ ] 3.2 **Goal verdict** — predicted time + 90% interval + P(goal) (the model output, same as Profile/coaching) + a one-line reading: *most-likely + range* (never a single false-certain time) and the Δ since last week.
- [ ] 3.3 **Limiter** — the domain with the largest gap *relative to its phase-target/goal-required level* (fitness/durability/effort/recovery); a **concrete** lever (a session/volume/recovery change, not a restatement); link to the owning tab + to the **next workout** that delivers the lever when one is planned; on-track → reframe as *what to protect*. The lever in the verdict reading IS this limiter (one story).
- [ ] 3.4 **Single next action** by fixed precedence: safety (injury/illness) > consistency (missed/at-risk plan) > the limiter's lever.
- [ ] 3.5 **Four status cards** (Fitness→Training, Recovery→Readiness, Physiology→Profile, Coach→Coach): value + trend (over the domain's canonical window per the window policy) + status as **icon/label + `safe`/`caution`/`danger` colour** (not colour-only); colour only against a defensible reference, else **neutral**; compact + a `→ <Tab>` link.
- [ ] 3.6 Wire `_overview_hub` into the report context (`generator.py`).

## 4. Recompose Overview + relocate detail + lead the detail tabs

- [ ] 4.1 Overview: phase-timeline countdown **as the headline** carrying the verdict, the limiter beside it (the two-line answer), then — secondary — the single next action and the four status cards. Alerts stay at top.
- [ ] 4.2 Relocate the full *Fitness Profile* dimension sparklines + *Your Physiology* anchors → **Profile**; *Objectives* → **Training**; *Checkpoints* + *Coach's Take* → **Coach** (Overview keeps a one-line summary + link). Every target gets a stable section anchor.
- [ ] 4.3 **Each detail tab leads with its one-line answer** (Readiness "can I absorb training?", Training "am I doing the work?", Profile "what will race day give?", Coach "the plan & why") above its supporting charts — conclusion-first, not a card pile.
- [ ] 4.4 **Graceful empty/degraded Overview**: no goal / unfit model / thin history → anchor estimate + a "set a goal / log runs" prompt + neutral status strip; never blanks, NaNs, or broken layout.

## 5. Consistency

- [ ] 5.1 The Overview verdict/forecast == the Profile + coaching-context output (one source — no separately-computed prediction).
- [ ] 5.2 The Fitness card's CTL/load == the Training-tab figure (one canonical signal).

## 6. Tests (template/structure guards — no compute change)

- [ ] 6.1 Overview: the verdict shows time + interval + P(goal) + a range-bearing reading; the four domain `→` links resolve.
- [ ] 6.2 Limiter = largest *relative* gap (not lowest raw value); names a concrete lever; links to the next workout when one is planned; verdict's lever == the limiter (one story).
- [ ] 6.3 Status uses icon/label + colour (not colour-only) and is **neutral** when no defensible reference exists (e.g. no goal set).
- [ ] 6.4 Each relocated detail section lives under its owning tab; each detail tab opens with a one-line answer (lead) before its charts.
- [ ] 6.5 `showTab` still reveals-all-then-restores (deep-linking a charted section sizes the chart, not 0×0); on-load hash routing lands on the named tab; unknown hash → overview; `→` link target anchors exist (no dead links).
- [ ] 6.6 Graceful empty: no goal + unfit model → anchor estimate + prompt + neutral strip, no blanks/NaNs.
- [ ] 6.7 Full suite green; `ruff` clean; `fit report` builds with and without the `forecast` extra.
