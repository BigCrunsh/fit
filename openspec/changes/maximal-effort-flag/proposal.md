## Why

The duration-keyed effort schedule keeps the fade slope **β at the population prior (−6.5), not fitted per-athlete** — deliberately, because the athlete's race heart-rates are contaminated by **sub-maximal** efforts. Many "races" are parkruns run *at* threshold, not all-out, so a weighted fit of offset-vs-log-duration flattens to ≈ −2.5 and distorts the whole curve (validated: a fitted β makes a 5 K read +3 bpm instead of the correct ~+10). The blocker is purely identification: **we can't tell a maximal effort from a sub-maximal one.**

We already have most of the signal — `activities.rpe`, `activities.feel`, `activities.compliance_score` are ingested from Garmin, and `race_calendar` knows which efforts were races. We just don't *use* them to gate the schedule. Adding an explicit maximality flag unlocks fitting β from genuinely all-out efforts — and, paired with the `effort-schedule-uncertainty` change, the fitted β's posterior SD then propagates into the forecast interval automatically.

## What Changes

Add a per-effort **maximality signal** and use it to fit β:

- **A maximality determination per running effort**, by precedence:
  1. **Explicit** — Garmin RPE / Feel (we ingest both): RPE ≈ 9–10 or a max-effort Feel marks an all-out effort; a race-result chip time on a `race_calendar` race corroborates.
  2. **Heuristic fallback** — avg HR within a small margin of the distance-expected ceiling AND even/slightly-negative pacing (a maximal effort holds high HR with controlled splits, not a faded positive split).
  3. **Manual override** — a CLI to mark/unmark an effort maximal when the athlete knows better.
- **`effort_schedule` fits β from maximal-flagged efforts** (offset-vs-log-duration slope, recency-/representativeness-weighted) — **still prior-regularized** toward −6.5, because maximal races stay sparse and the prior must remain the safety net. When too few maximal efforts exist, β stays at the prior (today's behaviour) and is labelled `defaulted`.
- **T₀** likewise uses maximal-flagged efforts (sharper than today's "avg HR ≥ LTHR" proxy).

## Impact

- **β becomes the athlete's own fade once the data supports it** — the Decision-4 unlock from `duration-keyed-effort-schedule`, now actionable. A runner who fades more than average (β steeper) gets a more conservative marathon; one who holds on gets credit — without the sub-maximal-parkrun contamination.
- **Composes with `effort-schedule-uncertainty`** — the fitted β arrives with a posterior SD that drops straight into that change's interval propagation, replacing the prior SD; the forecast tightens as maximal evidence accrues.
- **Schema**: a maximality column on `activities` (e.g. `is_maximal` / `max_effort_confidence`), populated at sync/backfill from RPE/Feel/race + heuristic, manually overridable. Backfillable from existing RPE/Feel history.
- **Code**: ingest/derive the flag (`sync` / a `backfill` step); `effort_schedule` (`fit/marathon/predict.py`) filters β-fitting (and T₀) to maximal efforts; a `fit` CLI to override.
- **Specs**: `adaptive-predictions` — maximal efforts are identified, and β is fitted from them (prior-regularized) rather than fixed at the population value.

Affected capability: **adaptive-predictions** (+ a small `data-ingestion` touch for the flag). Depends on: `duration-keyed-effort-schedule`; composes with `effort-schedule-uncertainty`.
