## Context

Presentation-layer restructure (no data/compute change). Today the Overview tab is ~365
lines (`dashboard.html:30–395`) carrying alerts, Needs-Your-Attention, *Your Physiology*,
the race/forecast card, Checkpoints + Coach's Take, the full *Fitness Profile* dimensions,
and *Objectives* — a dumping ground. The 5 tabs (`overview·profile·training·readiness·coach`)
have no stated job and there's no cross-tab drill-in. The forecast is now the durability
model (`chart-pred-trend`) — the trigger this change waited on. The four UX questions are
resolved (proposal §Resolved decisions).

## Goals / Non-Goals

**Goals:** Overview = a synthesis hub (phase-timeline headline + four domain-summary cards +
the single highest-priority attention/next action), each card linking into the tab that owns
the detail; detail relocated to its owning tab; triage tab order + one-line job subtitles;
drill-in links that route through `showTab` and update the URL hash.

**Non-Goals:** no metric/computation changes — the numbers are unchanged, this moves *where*
they're shown and adds routing. No new data/schema. CTL/forecast/durability are already
single-source (D2/D3/D4 in `DATA_LINEAGE`); this only links to them. Nothing is deleted.

## Decisions

### D1 — Overview hub composition (what stays, what moves)
**Stays on Overview:** alerts (safety) · Needs-Your-Attention (the one highest-priority item) ·
the **phase-timeline countdown chart as the headline** (goal verdict — predicted time +
interval + P(goal) — on it) · the next workout · a **four-card domain strip**, each = one
number + a `→ <Tab>` link:
- **Fitness** → Training (CTL/weekly volume) · **Recovery** → Readiness (readiness + ACWR) ·
  **Physiology** → Profile (effective VDOT + current limiter) · **Coach** → Coach (top note).

**Relocates to its owning tab:** the full *Fitness Profile* dimension sparklines + *Your
Physiology* anchors → **Profile**; *Objectives* → **Training**; *Checkpoints* + *Coach's Take* →
**Coach** (Overview keeps a one-line summary + link). Nothing deleted — each card carries the
one number that matters and the link.

### D2 — Drill-in via `showTab` + URL hash
Extend `showTab(id, btn)` → `showTab(id, btn, section=null)`: activate the tab through the
**existing reveal-all-then-restore path** (so charts in the now-shown tab init at real size,
not 0×0), then if `section` is given scroll to that anchor, and set
`location.hash = id` (or `id/section`). On load, if a valid hash is present route through
`showTab` (deep links shareable + survive reload); else default to `overview`. A reusable
`→ <Tab>` link component calls `showTab` — **never a raw `<a href="#...">` anchor jump**, which
would bypass the reveal pass and reintroduce the 0×0-chart bug.

### D3 — Tab order + job subtitles
Reorder the `tabs` list in `generator.py` to the triage order **Overview · Readiness · Training ·
Profile · Coach**; add a one-line `job` per tab (rendered as a subtitle under the tab bar / at
the top of each tab). `showTab` toggles by `id`, so the tab-content DOM order need not change —
only the button list + the per-tab subtitle. (Reordering the DOM divs is optional cleanup.)

### D4 — A small Overview-hub builder, reusing existing values
Add `_overview_hub(conn)` in `cards.py` returning the four domain summaries
(`{label, value, sub, tab, anchor}` each). It **reuses already-computed values** (the same
`fitness_profile` / readiness / ACWR / coaching-note sources the detail sections use) — no new
computation, so a card and its tab can't disagree.

## Risks / Trade-offs

- **[Information lost in the move]** → nothing is deleted; detail relocates and Overview keeps a
  one-line summary + link. Template guards assert each relocated section now lives under its
  owning tab and that every `→` link's target anchor exists (no dead links).
- **[Deep-link → 0×0 charts in a hidden tab]** → all drill-in routes go through `showTab`'s
  reveal path; a guard test deep-links a charted section and asserts the chart is sized.
- **[Hash routing breaks the default load]** → on load, validate the hash against known tab ids;
  unknown/empty → `overview`.
- **[Large template diff]** → stage it (migration plan): the mechanical JS/order/subtitle change
  first (low risk), then the Overview recomposition + relocations.

## Migration Plan

1. `generator.py`: triage tab order + a `job` string per tab.
2. `showTab` JS: optional target section (scroll after reveal), URL-hash read/write, on-load hash routing.
3. `cards.py`: `_overview_hub` builder (4 domain summaries + tab/anchor), reusing existing values.
4. `dashboard.html`: Overview → timeline headline + attention + next-action + 4 domain cards; relocate Fitness-Profile/Physiology → Profile, Objectives → Training, Checkpoints/Coach's-Take → Coach (one-line summary + link on Overview); add per-tab subtitle + the `→ <Tab>` link affordance.
5. `design_system.css`: hub-card + `→ <Tab>` link component (no one-off inline styles).
6. Tests: template guards (Overview has the headline + 4 domain links; relocated detail lives under its owning tab; `showTab` still reveals-all-then-restores; deep-link target anchors exist; hash routing). No data tests (no compute change). Rollback = revert branch (presentation only).
