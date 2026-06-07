# Tasks — duration-keyed-effort-schedule

Spec-first: nothing is implemented until the proposal + design are approved.

## 1. Schedule core (`fit/marathon/predict.py`)
- [ ] `EFFORT_T0_MIN` (population fallback ~55) + `EFFORT_BETA` (~−6.5) constants, derived/justified per design (least-squares β over the duration-anchors; cite the validation table)
- [ ] `effort_t0(ds)` — personalised T₀ from the nearest-LTHR genuine maximal effort (races / `effort_class ≥ Hard`); population fallback + `defaulted` flag/reason (mirror `extrapolation_prior`)
- [ ] `maximal_effort_h(predicted_minutes, hr_reserve=None)` — re-key on duration; keep the MaxHR-reserve `min`-cap
- [ ] `effort_h_for_distance(idata, ds, d, *, c, extrapolation_scale, nu, seed=0)` — the two-pass coupling (seed h=0 → predict → recompute h → predict); assert |Δoffset| < 0.05 bpm

## 2. Rewire callers
- [ ] `forecast`, `derived_metrics`, `required_chronic_for_goal`, `durability_panel`, `trend_series` → `effort_h_for_distance` (drop direct `maximal_effort_h(distance)`)
- [ ] Display callers: `cli` forecast `eff_hr`, `cards._model_week_trend` → same helper
- [ ] Confirm goal-switch (marathon → HM) still reads the right point (regression check)

## 3. Tests (`tests/test_marathon_model.py`, `test_marathon_features.py`)
- [ ] Law reproduces the validated anchors within tolerance (5 K ≤0.5 bpm, M ≤1.5 bpm) at the athlete's durations
- [ ] T₀ personalised from the nearest-LTHR effort; population fallback + `defaulted` when none; 2:1 unhappy (no efforts, all-submaximal, missing LTHR)
- [ ] One-pass coupling converges (two-pass Δ < 0.05 bpm); seed-independence
- [ ] MaxHR-reserve cap still binds for a low-reserve synthetic athlete; no-op at reserve 22
- [ ] Duration-keying is goal-independent (same distance → same h regardless of goal)

## 4. Validation (real data)
- [ ] Before/after forecast diff; confirm marathon shift ≤ ~2 min and headline ≈ stable
- [ ] Re-validate against the athlete's actual race max-HRs (10 K 179, HM 173) as in the original schedule
- [ ] Regenerate dashboard; confirm cross-surface consistency (hero / block / Panel A / Panel B / CLI / MCP) holds

## 5. Docs
- [ ] marathon `design.md` "Constants & assumptions": swap the `_MAXIMAL_HR_OFFSET` rows for (T₀, β) + validation table
- [ ] `DATA_LINEAGE.md` glossary: maximal-effort schedule → duration-keyed law
- [ ] Note the prior→posterior follow-on (Decision 4) in the marathon "Improvements identified" backlog
