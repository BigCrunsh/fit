# CLAUDE.md — fit project

Personal fitness data platform. SQLite database, Python CLI, MCP server, HTML dashboard.

## Quick Commands

```bash
pip install -e .                      # install
pip install -e '.[analysis]'          # install with fitparse for .fit file analysis
pytest tests/ -v                      # run tests
pytest tests/ -v --tb=short           # compact output
fit sync --days 7                     # daily: pull Garmin + enrich + weather + aggregate
fit sync --full && fit recompute      # init: pull all history + re-enrich
fit backfill rpe                      # one-shot: import directWorkoutRpe/Feel/ComplianceScore from Garmin for all running activities
fit report                            # generate dashboard → ~/.fit/reports/dashboard.html
fit coach                             # coaching analysis via the claude CLI → reports/coaching.json
fit status                            # quick overview: countdown, phase, ACWR, last 7 days
fit doctor                            # validate pipeline health
fit mcp install                       # register the MCP data tools with Claude Desktop / Code (free-form exploration)
```

## Design Decisions That Prevent Mistakes

- **Coaching is CLI-owned (`fit/coaching/`)** — `fit coach` shells out to the `claude` CLI; the context-assembly (`context.py`), the coaching prompt (`prompt.py`), and the notes writer (`save.py`) are one source of truth. This **replaced** the former MCP-tools + `.claude/skills/fit-coach/SKILL.md` split (which had to be hand-synced; the skill is now a redirect stub). The MCP (`mcp/server.py`) now exposes only its 6 read-only data tools. The contract is now internal: `prompt.py`/`context.py` still encode the same zone model, metrics, calibrations, phases, and forecast semantics as the dashboard — change a zone/metric/anchor rule and update them too. A byte-for-byte test pins `assemble_coaching_context` to its prior output (the SSOT regression guard).
- **Failures we anticipated raise `FitError` (`fit/errors.py`); everything else is a bug** — a `FitError` carries a one-sentence `message` plus a separate `hint` (the next step), and the CLI renders it as `✗ <message>` / `→ <hint>` with no traceback. Keep the two fields separate and never fold a wrapped exception's text into the message: concatenating layers is what produced `Sync failed: Garmin auth probe failed: Authentication failed: API Error 401 - . Run \`fit auth login\`…`, where the only useful words came last. Chain the original with `raise … from e` instead — the traceback still reaches `~/.fit/logs/sync.log`, and `-v` shows it on the console. `GarminAuthError` (re-authenticate) is deliberately distinct from a plain `FitError` for a network or Cloudflare failure (wait and retry); sending someone through a full MFA login because of a DNS blip is the wrong instruction. `FitGroup.invoke` in `cli.py` catches any `FitError` that escapes a command's own handler, so config/DB setup before the `try` can't leak a stack trace either. Commands that print their own failure log it with `extra={ALREADY_SHOWN: True}` so the console doesn't repeat it in log format.
- **INSERT ON CONFLICT**, not INSERT OR REPLACE — derived metrics are preserved on re-sync
- **Rolling 7-day window, not ISO weeks** — `compute_rolling_week()` (today-6 → today). ACWR is hybrid: rolling 7d acute + ISO-week chronic. **Consistency and volume-change are rolling too** (see next bullet); no decision or display reads an ISO-week bucket.
- **Consistency is a rolling RATE, not an ISO-week streak — `compute_run_frequency()`/`compute_volume_change()` (`analysis.py`)** — ISO buckets made a plan that runs every other day look erratic: a week boundary splitting seven completed runs 3/2/2 reported "0 weeks of consistency", and comparing a 4-day-old week against a complete one reported a "61% volume jump" when the rolling windows showed volume **down 36%**. Nothing had been skipped — the plan scheduled exactly those days. The requirement is **day-shift invariance**: moving a session by a day or two must not change a verdict. A rolling window gives that for volume; for frequency it is *not sufficient*, because an all-or-nothing "3+ runs in the trailing 7 days" test sits right at a 3-runs-a-week cadence and flickers 2↔4 as the window slides, so a *streak* of such windows still collapses. Hence a **rate** (`runs_per_week` over 28d) plus the **share of trailing-7d windows that held the target** (`base_pct` over 56d, → `sustained_weeks`), neither of which resets on one gap. All consumers read these — the `volume_ramp` alert (fire **and** auto-dismiss via the shared `_volume_ramp_state`, so they cannot drift into a D12-style un-dismissable alert), `fit status`, the Overview + Training objective strips and their sparkline, the consistency objective, and the coaching context. `weekly_agg.consecutive_weeks_3plus` is still **written** for historical continuity but **nothing reads it**; a test in `tests/test_rolling_consistency_wiring.py` fails if any module under `fit/` outside `analysis.py` references it. Thresholds: `analysis.frequency_target_runs`, `analysis.frequency_base_thin_pct`, `analysis.weekly_volume_increase_max_pct`. **`sustained_weeks` is capped by its window, so anything displaying it against a target must judge it over the TARGET's own length** — use `compute_sustained_weeks(conn, target_weeks=…)`, never a fixed 8-week base, or a 12-week marathon objective is unreachable by construction (the tile and its sparkline must pass the same target). Related: the Overview tiles match derived objectives to tile keys **by name prefix** (`_OVERVIEW_TARGET_PREFIXES`) — slugifying the whole name ("Consistency 12wk" → `consistency_12wk`) matched nothing, so every tile silently fell back to hardcoded defaults and showed no volume/long-run target at all.
- **Phase-specific targets** — compare against active training phase targets, not fixed 80/20
- **Zone distribution by TIME** (duration_min), not by run count
- **speed_per_bpm** (higher = better), not cardiac_efficiency (lower = better)
- **5-level effort class**: Recovery / Easy / Moderate / Hard / Very Hard
- **Prediction = conservative (upper bound)** — slowest prediction across all methods. Deliberately pessimistic.
- **Long run dual condition** — (>30% weekly AND ≥8km) OR ≥12km absolute override
- **Monotony = mean/stdev** (Foster's formula), NOT stdev alone. Strain = weekly_load × monotony
- **Wellness deviations have ONE source — `wellness_snapshot()` (`fit/wellness.py`)** — the alert rules (`respiration_elevated`/`rhr_elevated`/`recovery_cliff`), their auto-dismiss re-evaluation, the coaching-context respiration line, and the Readiness-tab respiration chart band all read it. Baseline = 28d rolling median strictly BEFORE the evaluated days (min 14 obs); missing days break streaks; sleep- and waking-respiration series never mix. Never inline a second baseline computation — that recreates the fire-then-instant-dismiss bugs (D6/D12).
- **Readiness is Garmin's score, and its explanation has ONE source — `readiness_breakdown()` (`fit/wellness.py`)** — `training_readiness` is copied verbatim from Garmin's Training Readiness endpoint; we never compute or rescale it. The score alone cannot say WHY it is low, so migration 020 also stores Garmin's own factor ratings (recovery time still counting down, plus 0-100 ratings for recovery/sleep/HRV/load-ratio/sleep-history/stress-history) and `readiness_breakdown` names the lowest-rated input. The `readiness_gate` alert message and the coaching-context readiness line both read it — never re-derive a driver inline. **A low score is usually recovery-time debt from a hard session** (readiness 1 on 2026-08-27 = 64 h still counting down, every other input rated GOOD), which self-resolves and is *not* the same finding as an HRV collapse; rows synced before 020 have NULL factors and must report "no driver" rather than a guessed cause. Distinct from `recovery_cliff`, which still requires RHR up **and** HRV `LOW` **and** readiness low on the same row.
- **Coaching context must label its windows** — single-day readings and multi-day averages go on separate lines, the same-day line marked `[single-day readings, not averages]`. Collapsing them is what let a review report "readiness bottomed out … with RHR at 55.1, HRV at 35.6" — one same-day score beside two 7-day means, read as three signals failing together. The "7d" average is `date >= date('now','-6 days')` (7 days inclusive, matching `compute_rolling_week`); `-7 days` spans **eight**. The prompt (`prompt.py`) forbids quoting an average as a same-day reading, forbids asserting a recovery cliff or a prior-review finding the context doesn't contain, and rules that recovery-time debt alone is not `critical`.
- **Objectives auto-derived only** — from target race via `derive_objectives()`. No manual CRUD.
- **Goals = "objectives" in UI** — DB table stays `goals`, user-facing text says "objectives"
- **RPE/Feel/Compliance source = Garmin** — `activities.rpe`, `activities.feel`, `activities.compliance_score` come from `summaryDTO.directWorkoutRpe/Feel/ComplianceScore` of the activity detail endpoint. Sync re-fetches the last 14 days every run; older activities are fill-NULL-only. Use `fit backfill rpe` to populate history.
- **sRPE source = activities.rpe** — `compute_srpe()` reads per-activity RPE directly. Triggered from sync and backfill.
- **Race calendar is manual** — not auto-detected from Garmin activity names
- **Aerobic SSOT = effective VDOT (`_effective_vdot`), shown as an integer** — the Physiology card's 4th tile, the Aerobic fitness dimension, and the Daniels pace zones all read `_effective_vdot` (confirmed VDOT > recent race ≤180d > Garmin−overestimate). Garmin VO2max reads ~5–10 high and is **reference/diagnostic only** (the Anchor-vs-Garmin chart, the small "Garmin VO2max N" sub-line) — never a headline number. Don't reintroduce raw Garmin VO2max or a raw latest-qualifying-anchor VDOT as a displayed value. (We deliberately do **not** surface a "VDOT disagrees with Garmin" attention item — that gap is the structural Garmin overestimate, not an actionable signal; only "no qualifying anchor at all" warrants a nudge.)
- **Device-measured LTHR (`device_lt`) is the trusted anchor** — calibration precedence is **confirmed > device > policy** (`get_calibration_anchor`). When the active LTHR is `device_lt` (Garmin auto-detected lactate threshold), HR-derived LTHR re-calibration nudges are suppressed: the policy suggestion (`evaluate_suggestions`) and the race-derived nudge (`_attention_items`'s `lthr_suggestion`) both skip — nagging to change a device value toward a lower-precedence estimate is self-contradictory. They re-enable automatically if the device stops providing an LT.
- **The "Needs Your Attention" panel (`_attention_items`) is part of the SSOT contract** — every item must read the same anchors/metrics/sources as the dashboard cards and coaching context (VDOT via `_effective_vdot`, LTHR via the device-aware anchor, etc.). Change an anchor/zone/metric rule → check `_attention_items` too, or the panel silently contradicts the cards.
- **Grade-adjusted to flat-equivalent** — cardiac-drift onset, economy/threshold `speed_per_bpm`, and the marathon model's effort time all use flat-equivalent values via `grade_adjusted_duration_min` / `_ga_spb_series` (linearised Minetti: +12 s/km per +1% climb, −6 per 1% descent). A rolling training course is read as its flat equivalent, so the flat-Berlin forecast isn't penalised for hilly training. Near-no-op on flat ground.
- **Drift onset has ONE source** — `compute_cardiac_drift` (grade-adjusted). The resilience dimension, the drift-onset chart, and the marathon resilience all read it; never recompute drift inline.
- **Maximal-effort schedule is duration-keyed (`effort_schedule` → `effort_h_for_distance` in `predict.py`)** — the forecast's assumed race HR is `offset(t)=β·(log t − log T₀)` keyed on the model's predicted **duration**, not distance (distance-keying smuggles in a fitness assumption — the confound the model removes). **T₀** (threshold-duration) is data-driven: a prior (~55 min) updated by the athlete's *at-or-above-threshold* races, recency- and representativeness-weighted, shrinking to the prior when thin. **β is fitted (prior-regularized) from maximal RACES** (`maximal-effort-flag`): a weighted-regression slope of offset vs log-duration Bayes-combined with the −6.5 population prior, so it stays ≈ −6.5 on thin/narrow data and personalises as maximal evidence accrues (currently −6.20±1.16 from 4 maximal races). Maximality = **RPE ≥ 9** (Garmin) or a sticky manual override (`fit effort maximal <id> [--no|--auto]`); **Garmin `feel` is NOT a signal** (strong↔weak, orthogonal to exertion — all-out RPE-10 races read feel 1–2); the HR-near-ceiling heuristic is a deferred follow-on. Only sustained **races** feed β — a tempo/interval's recovery-diluted avg HR would flatten the slope. T₀ keeps its at-threshold (offset≥0) proxy (more data, incl. HMs) but now uses the fitted β. The earlier "≈−2.5 contaminated fit" was the failure of fitting from ALL races indiscriminately; the maximality flag is what makes the fit safe. All callers go via `effort_h_for_distance` (two-pass coupling); never re-key on distance. The MaxHR-reserve cap rides along. **The forecast interval also carries the schedule's own uncertainty** (`effort-schedule-uncertainty`): `effort_schedule` returns `beta_sd` (the fitted β's posterior SE when β is fitted from maximal races, else the hand-set `EFFORT_BETA_PRIOR_SD`) and `t0_sd` (a precision-weighted posterior log-SD with prior `EFFORT_T0_PRIOR_LOG_SD` and an obs floor so a single race can't collapse it); `effort_h_for_distance(draws=True)` samples (β,T₀) per draw on a **separate RNG substream** from the wall penalty, and `predict` takes the **median from point β/T₀ (headline never moves), the 5/95 from the draws**. Widening grows with `|log t_goal − log T₀|` (largest at the marathon; σ_β barely moves it — the data-derived σ_T₀ dominates there). β/T₀ drawn independently (documented approximation, revisited under `maximal-effort-flag`). The Profile-tab **effort-schedule inspection panel** (`effort_schedule_panel`) visualises it. (**D15 resolved**: the population Riegel endurance-fade exponent is now the single `RIEGEL_EXPONENT` constant in `analysis.py` — all six extrapolation sites read it, distinct from the fitted per-athlete `β_d`.)

## Zone Model

5-zone. **Default: Friel %LTHR** (anchored to calibrated LTHR), with fall-through to %MaxHR when LTHR is missing. The textbook 70%-MaxHR Z2 ceiling (= 134 at MaxHR=192) is too strict for trained runners with high LTHR/MaxHR ratio; %LTHR with LTHR=172 gives a Z2 ceiling of 153, which matches actual upper-aerobic effort.

```
                 %LTHR (primary)     %MaxHR (diagnostic)
Z1 Recovery      <85% (<146)         <60% (<117)
Z2 Easy          85-89% (146-153)    60-70% (117-136)
Z3 Tempo         90-94% (154-161)    70-80% (137-156)
Z4 Threshold     95-99% (163-170)    80-90% (156-175)
Z5 VO2max        ≥100% (≥172)        ≥90% (≥176)
```

(Numbers above are for LTHR=172, MaxHR=195 — the active calibrations as of 2026-06-01.)

Zone boundaries must come from config (`zones_lthr` for the primary model, `zones_max_hr_pct` for the diagnostic), never from memory or common defaults. AeT-anchored Z2 ceiling is planned (`aet-anchored-zones` change) — when AeT lands, Z2 ceiling refines to AeT directly; everything Z3 and above stays LTHR-anchored.

Override the default via `profile.zone_model: max_hr` in `config.local.yaml` if you want the strict textbook model.

## Dashboard & Visualization

- **Always use the design system** — `fit/report/templates/design_system.css` is the single source of truth for colors, typography, spacing, and components. Never hardcode hex colors or styles that duplicate or contradict it.
  - Colors: use CSS variables (`var(--safe)`, `var(--z2)`, `var(--text-muted)`, etc.) in HTML. In Python/Chart.js where CSS vars aren't available, use the exact hex values defined in `:root`.
  - Components: reuse existing classes (`.card`, `.badge`, `.chart-box`, `.run-bar`, etc.) before inventing inline styles.
  - If a new color or component is needed, propose adding it to `design_system.css` first — don't inline a one-off.
- **Annotation bands** use 40+ hex opacity (e.g., `#60a5fa40`), never `0c`/`10`/`18`.
- **Consistent time x-axis** — all charts use `type: 'time'` with ISO date labels. Weekly aggregations (volume, run types) always use `unit: 'week'`. Other charts auto-select: `month` (>180d), `week` (42-180d), `day` (<42d). Profile charts share a fixed range (first phase - 2w → race + 10d). Weekly data uses ISO dates (Sunday of each week), never ISO week strings.
- **3 vendored JS files** inlined into HTML: chartjs.min.js, chartjs-annotation.min.js, chartjs-date-adapter.min.js

## Testing

Tests use in-memory SQLite with full migration suite. Fixtures in `tests/conftest.py`.

## Public Repo Rules

- NEVER commit personal data: config.local.yaml, *.db, *.csv, garmin tokens
- config.yaml is a template with `${VAR}` placeholders — no real values
