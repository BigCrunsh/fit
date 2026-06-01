## Why

The dashboard surfaces derived metrics (VDOT, weight, aerobic trend, ACWR, monotony…) but never explicitly shows the underlying **physiological anchors** that everything else is derived from — MaxHR, LTHR, AeT, VO2max. A reader who returns to the dashboard after weeks away has no way to see at a glance: *what does the system believe about my physiology right now?*

The per-chart "i" def-toggle popovers explain individual metrics, but they're scattered across tabs and only readable one at a time. There is no first-page primer that explains what these concepts mean and why they matter for marathon training.

Additionally, with `lthr-default-zones` landing, **pace zones (Daniels E/M/T/I/R)** become trivially derivable from LTHR and can be shown alongside HR zones — giving prescriptive paces for workouts, not just descriptive HR bands.

## What Changes

### Your Physiology card (Overview tab, top of page)

A new card showing the four anchors side-by-side:

| Anchor | Display | Source |
|---|---|---|
| **LTHR** | value + "primary anchor" badge + days since calibration + trend (`stable`/`+N bpm in M weeks`) | `calibration[metric=lthr, active=1]` |
| **MaxHR** | value + days since calibration + trend | `calibration[metric=max_hr, active=1]` |
| **AeT** | value if calibrated, else "Not measured → run a 15+km steady-pace effort" with a link to drift-test instructions | `calibration[metric=aet, active=1]` (the link points to `aet-anchored-zones` workflow) |
| **VO2max** | value + Garmin/race source + trend | `calibration[metric=vo2max, active=1]` |

Each metric has a one-line description right under its value:

- LTHR: *Lactate threshold. Sustainable hard-effort ceiling — anchors your training zones.*
- MaxHR: *Peak HR observed. Hardware ceiling. Auto-updates from race data.*
- AeT: *Aerobic threshold. The boundary that matters most for marathon endurance.*
- VO2max: *Aerobic capacity. Predicts race times via VDOT (Daniels).*

Each value is clickable to scroll to its calibration history chart on the Profile tab (when `calibration-history` ships) — until then, clicking a value scrolls to the existing trend chart for that metric.

### Daniels pace zones from LTHR

A "Pace Zones" panel inside the Profile tab (under the existing Fitness Dimensions section). Derives Daniels training paces from LTHR using the standard formulas:

- **E** (Easy): pace ~30–60 sec/km slower than M pace
- **M** (Marathon): vVO2max × ~0.84
- **T** (Threshold / Tempo): pace at LTHR — ~LTHR pace
- **I** (Interval, ~vVO2max): pace where 5K race time falls
- **R** (Repetition, faster than vVO2max): pace ~6 sec/400m faster than I

Each pace shown as min/km range, with a one-line description. Sources LTHR from calibration table; derives vVO2max via Daniels' formulas. When LTHR is missing, the panel shows "Calibrate LTHR to compute pace zones."

### Trend indicators on physiology values

Each metric value in the Physiology card carries a small trend tag:

- `stable` (no calibration change >= 2 bpm over last 6 months)
- `+N bpm in M weeks` (delta vs prior calibration, signed)
- `↑ improving` / `↓ declining` for VO2max (semantic direction)

### Concepts section at bottom of Overview tab

A collapsible (`<details>`) section labeled "Concepts" containing 2-line explanations of:

- MaxHR, LTHR, AeT — the three thresholds
- VO2max, VDOT — aerobic capacity
- ACWR — Acute:Chronic Workload Ratio
- Monotony, Strain — Foster's training-load metrics
- Cardiac Drift — HR rise at constant pace
- Z2 ceiling / Effort Class — zone-based intensity classification
- Run Type — sync's classifier (easy / long / tempo / intervals / race / recovery)

Existing per-chart def-toggle popovers remain unchanged (they're contextual; the Concepts section is the canonical glossary).

## Capabilities

### Modified Capabilities

- `dashboard`: gains the Physiology card on Overview tab, a Pace Zones panel on Profile tab, and a collapsible Concepts glossary. Existing per-chart def-toggles remain.

## Impact

- **Code**:
  - `fit/report/sections/cards.py`: new `_physiology()` builder, new `_pace_zones()` builder, new `_concepts()` static text section.
  - `fit/analysis.py`: new helper `compute_daniels_paces(lthr, vo2max) -> dict` returning min/km ranges per pace zone (E, M, T, I, R).
  - `fit/report/templates/dashboard.html`: new Physiology card markup near the top of Overview; new Pace Zones panel on Profile tab; new Concepts collapsible at bottom of Overview.
  - `fit/report/templates/design_system.css`: new `.physiology-card`, `.physiology-anchor`, `.anchor-trend`, `.pace-zone-row` classes following existing design-system conventions.
- **Schema**: none.
- **Tests**:
  - `tests/test_analysis.py::TestDanielsPaces` — compute_daniels_paces returns correct ranges for known LTHR/VO2max inputs, NaN handling when inputs missing.
  - `tests/test_report.py` (or section-specific test): physiology card renders all four anchors; AeT card shows the "Not measured" prompt with link when calibration absent.
- **Data**: none.
- **External**: none.

## Risks / Trade-offs

- **AeT card is mostly aspirational.** Until `aet-anchored-zones` ships, the AeT card just says "Not measured" with a link. That's visible value (it tells the user something is missing) but also dashboard real estate consumed by a non-actionable card.
- **Daniels pace zones assume well-conditioned LTHR.** If LTHR is stale, the derived paces are stale too. Mitigation: stale LTHR causes the pace panel to warn (using staleness data from existing `calibration.is_stale()`).
- **Concepts glossary risks bloat.** Limited to 11 concepts, 2 lines each, ~250 words total. Anything longer goes into per-chart def-toggle popovers.

## Open Questions

1. Should the Physiology card live above or below the race countdown card? Above gives more prominence to physiology; below preserves the race anchor as the visual focal point.
2. Pace zones tied to LTHR vs VDOT: which is the better source for E/M paces? Daniels' table is VDOT-anchored; LTHR gives T/I/R more reliably. Hybrid: use VDOT for E/M, LTHR for T/I/R.
3. The "trend" tag on MaxHR: an upward MaxHR trend in your 30s+ is unusual. Should it be flagged as "verify"? Or trusted as evidence of fitness gain?
