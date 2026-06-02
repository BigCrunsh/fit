## Why

The four fitness anchors — VDOT, LTHR, MaxHR, AeT — are derived four different ways, and the dashboard reads them inconsistently. Concretely, "current VDOT" appears as **three different numbers** at once:

| Where | Rule | Value today |
|---|---|---|
| Marathon forecast | raw Garmin VO2max | 49 (→ 3:43) |
| Dashboard VDOT Trend + Pace Zones | `get_fitness_anchors` — *latest* qualifying effort | 35.7 (→ trail HM) |
| `effective_vdot` (CLI `fit status`, Fitness Dimensions, objectives) | best race in last 180 days | 35.8 |

The 35.7/35.8 figure is pinned to a single **trail half-marathon** (Müggelturm, 2:01:48) — the only road races at VDOT ~40–41 aged out of the hard 180-day window. So the dashboard tells the athlete to "trust 35.7" and then prescribes an 8:23/km easy pace, *slower than the 6:59/km their own "Today" card says they cruise*, and far off a sub-4:00 goal.

Two root causes:

1. **No shared aggregation layer.** `get_active_calibration()` picks *one* row (non-stale → highest confidence → most recent). Each metric's estimate-generation is bespoke, and VDOT isn't in the `calibration` table at all — it lives in separate `effective_vdot`/`get_fitness_anchors` code paths. There is no single function that says "this is the canonical VDOT/LTHR/MaxHR/AeT, computed the right way for *that* metric."

2. **One aggregation rule applied to metrics with different statistics.** "Best in a window" is correct for VDOT and wrong for LTHR/AeT — because VDOT observations are *one-sided* (a race is bounded above by fitness; bad conditions only make it slower) while HR-threshold observations are *two-sided* (a reading can err high or low: a hot day inflates avg HR without raising the threshold). Taking the max of a two-sided metric is a bias generator.

This change introduces a standardizing calibration layer with a per-metric aggregation policy, makes VDOT a first-class calibration metric, gives all four a calibration-history time series, and unifies every dashboard read on the single active anchor — with the human as owner of the active value and the heuristic as a reasoned suggestion.

Builds on `calibration-history` (confidence/flags rubric, history charts) and complements `aet-anchored-zones` (AeT calibration metric).

## What Changes

### A shared standardizing anchor layer (the core)

A single function per metric — `get_calibration_anchor(conn, metric) -> {value, confidence, method, inputs, suggestion}` — becomes the **one** way any consumer obtains a fitness anchor. It applies the metric's declared aggregation policy over the metric's observation rows and returns the active value plus the heuristic suggestion and the inputs it used (for display and audit).

Every consumer reads through it: the dashboard VDOT Trend section, Pace Zones, the marathon forecast, the Fitness Dimensions, CLI `fit status`, and the MCP coaching context. No consumer re-derives an anchor on its own. (This subsumes `get_fitness_anchors`'s "latest effort" path and folds `effective_vdot` into the VDOT policy.)

### Per-metric aggregation policy

Each metric declares an `AGGREGATION_POLICY`. **One uniform shape:** a trailing window · `staleness = window` · sticky-confirm · no hard gates (plausibility and effort-hardness ride along as *confidence*, surfaced at the confirm prompt — never an auto-filter). Just two estimator families:

| Metric | family | window = staleness | min_samples | differs | notes |
|---|---|---|---|---|---|
| **VDOT** | `max` | 180 d | 1 | 1.0 | one-sided (a race is bounded above by fitness) |
| **MaxHR** | `max` | 365 d | 1 | 2 bpm | a ceiling, hit only ~yearly → longer window; strap glitches handled as low-confidence, not a hard gate |
| **LTHR** | `median` | 180 d | 3 | 2 bpm | two-sided (a hot day inflates HR without raising the threshold) |
| **AeT** | `median` | 180 d | 3 | 3 bpm | two-sided, noisiest signal |

The unifying rule: *one-sided / ceiling metrics take a **max**; two-sided noisy thresholds take a **median**.* Everything metric-specific reduces to three facts: **(1) max vs median** (which also sets `min_samples` 1 vs 3), **(2) MaxHR's 365-day window** (you hit max HR only ~yearly), and **(3) what physically measures it** (observation source). No age decay, no trim, no per-metric method allowlists, no auto-accept exception. Observations = the metric's rows minus reference-only methods (Garmin VO2max for VDOT); below `min_samples`, a median falls back to the most-recent single row at low confidence.

**Confidence, not gates.** Plausibility envelopes (`_PLAUSIBLE`) and effort-hardness (HR vs LTHR, pace CV) are not filters — an out-of-envelope or off-effort observation is recorded at low confidence with a reason, and the confirm prompt explains it (*"MaxHR 240 — implausibly high vs 196, strap glitch?"*). The human decides; nothing is auto-dropped, so a real effort (e.g. a track 5k at HR just under LTHR) is never silently excluded.

**VDOT specifics.** The *suggestion* is the max over qualifying efforts inside a 6-month window; the *active* value is **sticky** — the athlete's last-confirmed VDOT, never auto-overwritten by the window. Two consequences fall out, and neither needs manual tagging:

- **Slow/distorted efforts are free to ignore.** A trail or not-all-out race produces a low VDOT, which a max never selects. (The Müggelturm 35.7 only became the anchor under the old "latest effort" rule.)
- **Downward trends are captured by the window, not a decay model.** A once-fast effort ages out of the 6-month window; if nothing fresh replaces it, the active value goes **stale** and the dashboard prompts a re-test rather than guessing a decayed number. Detraining therefore surfaces as *staleness → re-test → confirm the new (lower) value* — consistent with "human confirms." This matches the physiology: VO₂max is maintained by continued training and falls only on a real layoff, so an unrefreshed value should prompt re-measurement, not silently drift.

### Two models, complementary — Daniels and Riegel (not redundant)

VDOT's downstream uses run on two models with different jobs; both stay, and their assumptions are documented in code (at each entry point) and surfaced on the dashboard (the section `def-box`s):

- **Daniels** (`compute_vdot_from_race` → `vdot_to_race_time`) drives the **anchor + pace zones** — "how sharp is my engine now." *Assumes population-average running economy* (VDOT is a performance index, not a measured VO₂max; real economy ±10–15%, tracked separately as Aerobic Efficiency) and a clean, evenly-paced effort on a flat fair-conditions course.
- **Riegel** (`predict_race_time`) drives the **marathon forecast + durability** — "what will race day give, accounting for how I fade." *Assumes* the power law `T₂ = T₁·(D₂/D₁)^b`; default `b = 1.06` (population-average fade), with the personalized exponent fit to the athlete's own multi-distance races as the durability signal Daniels' fixed endurance curve can't express. Assumes clean source races (a terrain/heat-distorted long race overstates fade).

They agree per-race only at the default exponent (within ~2 min); the value of keeping both is that Daniels-VDOT trending up = fitter, Riegel-exponent trending down = more durable — two distinct, useful signals.

### VDOT becomes a first-class calibration metric

`vdot` joins `lthr`/`max_hr`/`aet`/`weight` in the `calibration` table. Race results write **informational** `race_estimate` VDOT rows (the same Option-A pattern as LTHR — they never auto-activate, they feed the aggregation and the history chart). The Garmin VO2max estimate is retained as an informational row too, clearly labelled. The active VDOT is produced by the VDOT aggregation policy, confirmable by the human.

### Calibration history for all four metrics

The Profile-tab Calibration History (from `calibration-history`) SHALL render a time-series chart for **each** of VDOT, LTHR, MaxHR, AeT — observations over time, the active value highlighted, bounds/confidence encoded per the existing marker rubric. VDOT gains a history it never had.

### Governance: anchors never change silently — confirmed at sync, not hand-selected

The active anchor SHALL never change on its own. After ingesting new data, `fit sync` SHALL compute each metric's policy suggestion and compare it to the current active value; when a suggestion **differs materially** from active (per-metric threshold), it raises a **pending calibration suggestion**. The athlete confirms with a single accept/reject — never by hand-picking from a list:

- **Interactive `fit sync` (TTY):** prompts inline — *"VDOT: suggest 40.4 (Müggelsee HM, 2025-10-19, recency-decayed) — active is 35.8. Accept? [y/N]"*. Accept → writes the active calibration (`method='confirmed'`, `confidence='high'`). Reject → active unchanged.
- **Non-interactive sync (cron/headless):** does NOT block. The suggestion is **persisted as pending** and surfaced in `fit status`, the dashboard Needs-Your-Attention panel, and `fit calibrate <metric>` for later one-tap accept/reject.

A **suggestion ledger** prevents nagging: a rejected suggestion is recorded with its value; the same suggestion is not re-raised until the policy output **changes materially** from the rejected value. `fit calibrate <metric>` remains available for an explicit manual override at any time. The heuristic proposes; the human confirms; nothing auto-flips.

## Capabilities

### Modified Capabilities

- `fitness-profile`: gains a shared `get_calibration_anchor()` layer and a per-metric `AGGREGATION_POLICY`; `vdot` becomes a tracked calibration metric; `effective_vdot` is redefined as the output of the VDOT policy (best, recency-decayed) rather than best-in-hard-180-day-window; all anchor consumers read through the shared layer.
- `dashboard`: VDOT Trend section, Pace Zones, and the marathon forecast read the single active VDOT anchor; Calibration History renders a time series for all four metrics including VDOT.
- `data-ingestion`: sync writes informational `race_estimate` VDOT rows from completed races (alongside the existing LTHR estimates), feeding the VDOT aggregation and history.

## Impact

- **Code**:
  - `fit/calibration.py`: new `AGGREGATION_POLICY` table; new `get_calibration_anchor(conn, metric)` returning value + confidence + suggestion + inputs; estimator helpers (`_max_recency_decayed`, `_plausibility_gated_max`, `_robust_center`). `get_active_calibration()` stays as the row-selector primitive the policy builds on.
  - `fit/fitness.py`: `_get_race_vdot`/`_compute_effective_vdot` reimplemented via the VDOT policy (recency decay, no cliff); `get_fitness_profile` reads the shared anchor; `get_fitness_anchors` retained only as the qualifying-effort *detector* that feeds estimate rows (no longer a consumer-facing anchor).
  - `fit/report/sections/cards.py`: `_vdot_comparison`, `_pace_zones`, `_race_countdown` read `get_calibration_anchor(conn, 'vdot')`; Calibration History builder includes VDOT.
  - `fit/sync.py`: write `race_estimate` VDOT rows from completed races (mirror the LTHR path).
  - `fit/cli.py`: `fit calibrate <metric>` shows suggestion + reasoning + accept/override flow; `vdot` added to calibrate/doctor/status surfaces.
  - `mcp/server.py`: coaching context reads the shared anchor (keeps the MCP/skill contract in sync per CLAUDE.md).
- **Schema**: `vdot` is a new value of the existing `metric` column on `calibration` — no table change. Depends on `calibration-history` (flags, confidence).
- **Tests**:
  - `tests/test_calibration.py`: per-policy estimators (max-recency-decayed, plausibility-gated-max + age decay, robust-center); `get_calibration_anchor` for each metric; suggestion payload shape.
  - `tests/test_fitness.py`: `effective_vdot` no longer cliffs at 180d; an older road best outranks a recent trail race once decay is applied; trail-tagged race excluded.
  - `tests/test_pace_anchor.py` (exists): update to assert paces follow the standardized VDOT anchor, not latest-effort.
  - `tests/test_calibration_history.py`: VDOT series renders.
- **Data**: one-off `fit backfill vdot` writes `race_estimate` VDOT rows over race history (mirrors `fit backfill rpe`/`aet`). No destructive change — informational rows only.
- **External**: none.

## Risks / Trade-offs

- **Recency-decay half-life is a free parameter.** Too short re-creates the cliff; too long lets a stale PR dominate. **Mitigation**: make it a per-metric config (`calibration.vdot_decay_half_life_days`, default ~210); show the decayed contributors in the `fit calibrate` suggestion so the choice is auditable.
- **Terrain/conditions are invisible to the formula** — but need no manual fix. A max estimator can't be dragged down by a slow trail/hot race (it's never selected), and a spuriously *fast* race is caught at the sync-confirm prompt. No tagging chore; `exclude_from_anchor` is dropped.
- **Median needs a minimum sample size.** With 1–2 LTHR/AeT estimates a median is just the latest. **Mitigation**: policy declares `min_samples`; below it, fall back to the single best-confidence row and mark confidence `low`.
- **Changing `effective_vdot` shifts downstream numbers** (predictions, objectives, dimensions) the moment it ships. **Mitigation**: it shifts them toward *consistency* (one number everywhere); the first run surfaces the shift as a sync-confirm prompt rather than silently; annotate the VDOT history chart at the cutover.
- **Sync prompt in non-interactive runs.** A blocking prompt would hang cron. **Mitigation**: TTY-detect — prompt interactively, else persist as a pending suggestion surfaced in `fit status` / attention panel; never block.
- **Re-prompt fatigue.** Without memory, a rejected suggestion re-fires every sync. **Mitigation**: the suggestion ledger re-raises only when the policy output changes materially from the last rejected value.

## Resolved Decisions

- **Governance** (was Q3): never auto-flip. `fit sync` computes the policy suggestion and, when it differs materially from active, prompts accept/reject interactively or persists a pending suggestion when headless. A suggestion ledger prevents re-nagging. Manual `fit calibrate` override always available.
- **Terrain** (was Q1b): no manual `exclude_from_anchor`. The VDOT max estimator ignores slow outliers by construction; a spuriously fast race is caught at the sync-confirm prompt.
- **Interim pace-zones edit** (was Q6): committed as a documented interim (`ba220e5`); it is superseded when the VDOT policy lands and `_pace_zones` reads `get_calibration_anchor`.
- **VDOT estimator** (was Q1): **max within a trailing window**, no decay model. The active value is **sticky/last-confirmed**; the window drives only the suggestion and the staleness flag. Detraining is captured by efforts ageing out → stale → re-test prompt.
- **VDOT window = staleness = 6 months** (one parameter): defines which efforts may set the suggestion AND when the confirmed value is flagged stale.
- **Bootstrap**: seed the active VDOT as a confirmed 41 (from the Oct road HM) — "as if confirmed". The trail 35.7 is an informational/rejected observation. So the live dashboard reads 41, flagged stale, prompting a refresh.
- **Defaults** (configurable): VDOT window 180 d, `differs_materially` 1.0 VDOT; LTHR median over 270 d, `min_samples` 3, staleness 180 d; AeT trimmed median over 120 d, `min_samples` 3, staleness 56 d; MaxHR plausibility-gated all-time max, ~0.7 bpm/yr age decay, staleness 730 d.

## Open Questions

1. **LTHR / AeT** — median vs trimmed mean exact form, and `min_samples` (default 3) before the heuristic is trusted.
2. **"Differs materially" thresholds** for raising a sync suggestion — per metric (VDOT ±1.0 set; LTHR/AeT/MaxHR ±2 bpm?).
3. **MaxHR plausibility gate** — absolute (age-predicted + margin) vs relative (established max + N bpm), or both.
4. **Do LTHR/AeT/MaxHR also become "sticky/last-confirmed"** like VDOT, or keep windowed-suggestion-as-active? (VDOT is sticky because a single bad effort is common; revisit per metric in Phase 5.)
5. **Sequencing** — VDOT-first vertical slice (ship the live fix + prove the sync-confirm UX), then LTHR/AeT/MaxHR policies.
