# Design — maximal-effort-flag

## Context

`effort_schedule(ds)` keeps β at the population prior because the athlete's race HRs mix maximal
and sub-maximal efforts; a naive slope fit flattens (validated −2.3). The only missing piece is a
reliable per-effort maximality signal. We already ingest `activities.rpe`, `activities.feel`,
`activities.compliance_score` (Garmin) and `race_calendar` status — this change turns those (plus a
heuristic fallback and a manual override) into a flag, then gates β-fitting on it.

## Determining maximality (precedence)

1. **Explicit (preferred).** Garmin RPE ≈ 9–10 and/or a max-effort Feel = all-out; a `race_calendar`
   race with an entered chip time corroborates. These are the cleanest signals and need no tuning.
2. **Heuristic fallback** (when RPE/Feel absent). Maximal ⇔ avg HR within ~X bpm of the
   distance-expected ceiling AND even-or-negative pacing (split CV below a threshold / no large
   positive fade). Rationale: a maximal effort holds a high, distance-appropriate HR with controlled
   pacing; a sub-maximal parkrun sits below the ceiling, a blown-up effort fades positive.
3. **Manual override.** `fit effort maximal <activity_id> [--no]` to set/clear when the athlete knows
   (a race they jogged; a workout they secretly raced). Override always wins.

Store a per-effort `is_maximal` (bool) plus a `max_effort_source` (rpe/feel/race/heuristic/manual)
for transparency; optionally a `max_effort_confidence`.

## Fitting β (prior-regularized)

With maximal efforts identified, β = the recency-/representativeness-weighted slope of
`offset = avg_hr − LTHR` vs `log(duration)` over **maximal-flagged** efforts, **shrunk toward the
population prior −6.5** by the data precision (pseudo-count, as the existing T₀ shrinkage). Sparse
maximal data → β stays ≈ −6.5 (`defaulted`); enough consistent maximal data → β personalises. The
fit also yields β's standard error → feeds `effort-schedule-uncertainty` propagation.

T₀ moves from the current "avg HR ≥ LTHR" proxy to the maximal-flagged efforts (a cleaner anchor).

## Decisions

### Decision 1 — explicit RPE/Feel/race over heuristic over manual
We already have RPE/Feel, so lead with them; the heuristic is only for efforts lacking them; manual
overrides both. **Anti-recommendation: heuristic-only** (HR-near-ceiling) — rejected: fragile to
hot/cold days and GPS HR noise, and we'd be re-deriving what RPE/Feel already tell us.

### Decision 2 — β stays prior-regularized even with maximal-only data
Maximal races are sparse (a handful a year). An unregularised fit on 2–3 races is unstable.
**Anti-recommendation: hard-fit β from maximal efforts** — rejected: keep the prior as the floor so
β can't swing wildly off a couple of races; it only moves as maximal evidence accumulates.

### Decision 3 — a stored flag, derived at sync/backfill, not recomputed inline
Compute `is_maximal` once (ingest/backfill from RPE/Feel/race + heuristic) and store it, so the
schedule, the dashboard, and any audit read one source. **Anti-recommendation: derive maximality
inside `effort_schedule` each call** — rejected: it would hide the determination, can't be manually
overridden, and would re-key on transient heuristics.

### Decision 4 — don't break the conservative default
If the flag yields no maximal efforts (cold-start, or all sub-maximal), β stays at the population
prior exactly as today — this change never makes the forecast *less* robust, only more personalised
when the evidence is there.

## Migration

1. Migration: add `is_maximal` (+ `max_effort_source`) to `activities`.
2. Sync/backfill: populate from RPE/Feel/race-status, then the heuristic; idempotent (re-derive on
   re-sync, but never clobber a manual override).
3. `fit effort maximal <id> [--no]` CLI for manual override.
4. `effort_schedule`: fit β (prior-regularized) from maximal efforts; T₀ from maximal efforts;
   return β + its SE; fall back to the prior + `defaulted` when sparse.
5. Validate: with the current data, confirm which efforts flag maximal (the 3 K all-out vs the easy
   5 Ks), the fitted β is sane (between the prior and the data, not the contaminated −2.3), and the
   headline stays stable; confirm β's SE flows into `effort-schedule-uncertainty`.

## Risks

- **RPE/Feel coverage is partial** (only recent activities have them). Mitigation: heuristic fallback
  + backfill; until coverage is good, few efforts flag maximal and β stays at the prior (safe).
- **Heuristic false-positives/negatives.** Mitigation: it's the lowest-precedence source, only used
  absent RPE/Feel, and manual override exists; the prior caps the damage of a mis-flag.
- **Over-personalising on thin data.** Mitigation: Decision 2 (prior-regularized) — β barely moves
  until several consistent maximal efforts exist.
