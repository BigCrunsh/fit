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

Each metric declares an `AGGREGATION_POLICY` describing its estimator, window, and outlier handling. The policy matches the metric's statistical nature:

| Metric | Nature | Estimator | Window / memory | Outlier handling |
|---|---|---|---|---|
| **VDOT** | performance, bounded **above** by fitness | **max**, recency-decayed | exponential decay (half-life ~6–9 mo), no hard cliff | conditions/terrain tag can exclude a race |
| **MaxHR** | true physiological **ceiling** | **max** of validated obs | long (years) + age decay (~1 bpm/yr) | reject readings implausibly above established ceiling / age-predicted max |
| **LTHR** | noisy central **threshold** | **median** (or trimmed mean) of recent qualifying efforts | recent (~6–12 mo), recency-weighted | median is intrinsically robust |
| **AeT** | noisiest central **threshold** (drift tests) | **median / trimmed mean** of recent tests | recent (~season), recency-weighted | trim extremes; negative-drift tests excluded upstream |

The unifying rule: *one-sided-bounded-above or literal-ceiling metrics take the **max**; two-sided physiological thresholds take a **robust center**.*

This corrects two flaws in today's VDOT logic specifically: the hard 180-day cliff (→ recency decay, so an 8-month-old 40.9 still outranks a fresh trail 35.8) and terrain-blindness (→ a conditions tag, at minimum the ability to mark a race non-anchoring).

### VDOT becomes a first-class calibration metric

`vdot` joins `lthr`/`max_hr`/`aet`/`weight` in the `calibration` table. Race results write **informational** `race_estimate` VDOT rows (the same Option-A pattern as LTHR — they never auto-activate, they feed the aggregation and the history chart). The Garmin VO2max estimate is retained as an informational row too, clearly labelled. The active VDOT is produced by the VDOT aggregation policy, confirmable by the human.

### Calibration history for all four metrics

The Profile-tab Calibration History (from `calibration-history`) SHALL render a time-series chart for **each** of VDOT, LTHR, MaxHR, AeT — observations over time, the active value highlighted, bounds/confidence encoded per the existing marker rubric. VDOT gains a history it never had.

### `fit calibrate` suggests, the human confirms (governance)

`fit calibrate <metric>` SHALL display: the current active value, the **heuristic suggestion with its reasoning** (e.g. *"median of 4 drift tests in 90d = 152; latest single = 155"*, or *"best race in last 9 mo, recency-decayed = 40.4 (Müggelsee HM, 2025-10-19); the trail HM 35.8 is excluded as off-road"*), and the inputs used — then let the user **accept** (writes the active calibration) or **override** with a manual value (`confidence='high'`). The heuristic proposes; the human owns the active value.

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
- **Terrain tagging is manual.** The system can't detect trail vs road reliably. **Mitigation**: recency-decay alone fixes the present case (road 40.9 outranks trail 35.8); the tag is an optional refinement, not a blocker. Default: all races anchor unless explicitly excluded.
- **Median needs a minimum sample size.** With 1–2 LTHR/AeT estimates a median is just the latest. **Mitigation**: policy declares `min_samples`; below it, fall back to the single best-confidence row and mark confidence `low`.
- **Changing `effective_vdot` shifts downstream numbers** (predictions, objectives, dimensions) the moment it ships. **Mitigation**: it shifts them toward *consistency* (one number everywhere); call it out in the changelog and annotate the VDOT history chart at the cutover.
- **Governance friction.** Requiring confirmation on every calibration is tedious; auto-activating silently is what caused the drift. **Mitigation**: see Open Question 3 — propose auto-activate at high confidence, confirm only on low/conflicting.

## Open Questions

1. **VDOT decay half-life** — 6 vs 9 months? And do we add a surface/conditions tag on `race_calendar` now, or rely on decay alone for v1?
2. **LTHR / AeT** — median vs trimmed mean, window length (6–12 mo for LTHR, season for AeT), and `min_samples` before the heuristic is trusted.
3. **Governance** — does the active value require explicit confirmation, or does the heuristic auto-activate at `high` confidence and only prompt on `low`/conflicting? (Friction vs. control.)
4. **Per-metric staleness thresholds** — MaxHR long (years), LTHR/VDOT medium (~weeks–months), AeT short. Today they're near-uniform; set them explicitly.
5. **MaxHR plausibility gate** — absolute ceiling (e.g. age-predicted + margin) vs. relative (reject > established max + N bpm)?
6. **Interim code state** — the uncommitted Pace-Zones edit currently reads `get_fitness_anchors` (latest effort); revert to status-quo until this lands, or leave it pointing at the soon-to-be-standardized path?
