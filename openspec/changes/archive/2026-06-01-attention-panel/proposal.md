## Why

The dashboard surfaces information *about* the user (here's your readiness, here are your zones, here's your race countdown) but does not clearly surface what the user *needs to do*. Required user actions are spread across the rendering:

- Stale calibration prompts live inside the data-sources panel on the Coach tab
- Alerts are listed in fire order at the top of the Overview tab (no severity sort, no dedupe across fire-cycles, no actionability)
- Missing data sources (SpO2 disabled, no AeT measurement, weight log gap) show up only when the user runs `fit doctor`
- Missed check-ins are not surfaced at all on the dashboard
- "Coach's Take" can be 30+ days stale — surfaced now via the stale badge from a previous change, but the underlying "weekly coaching review overdue" action is still implicit

The result: a returning user has to scan multiple tabs to figure out what's expected of them. There is no single answer to *what's pending from me?*

## What Changes

### Needs Your Attention panel (Overview tab, above the race countdown)

A single prioritized panel that aggregates all pending actions in one place. Renders only when there is something to show — empty state = panel disappears entirely (no "you're all set" celebration card, just absence-of-noise).

Each row has:

- A severity icon: 🔴 critical, 🟡 warning, 🔵 info
- A one-line description in imperative voice ("Re-export Apple Health from iPhone")
- An optional inline command (`<code class="value-pill">fit ...</code>`) the user can copy
- An optional "Why" tooltip explaining what changes if the user does the action

Sources of attention items:

| Source | Severity rule |
|---|---|
| `data_health.check_data_sources()` returning `stale` or `missing` | `warning` (stale) / `critical` (missing for primary metrics like LTHR / weight) |
| `calibration.get_calibration_status()` returning a stale metric | `warning` |
| `coaching.json` older than 7 days | `warning` |
| Apple Health export older than 14 days | `warning` |
| Latest checkin older than 3 days | `info` |
| AeT not yet measured | `info` (until `aet-anchored-zones` lands; becomes `warning` after) |
| SpO2 not flowing through Garmin (watch setting off) | `info` |

### Severity-sorted alerts inbox (replaces the current alert list)

The existing alert list at the top of Overview SHALL be sorted by severity, not fire-order. Within a severity tier, sort by most-recent-first.

Alert types map to severity per the existing `alerts.py` rules:

- `critical`: `acwr_spike_danger` (>1.5), `readiness_gate` (<40), `volume_ramp` (>10% AND streak<8)
- `warning`: `all_runs_too_hard`, `alcohol_hrv_drop`, `monotony_high`
- `info`: anything else

Alert deduplication: only the most recent alert of each type SHALL render (already implemented in `_recent_alerts()` — confirm + spec it).

### Race countdown carries a prediction-confidence note

The race countdown card SHALL include a one-line confidence/uncertainty note when LTHR is stale or AeT is missing, since those reduce the prediction's reliability:

- "Prediction confidence: high" (all anchors fresh + within range)
- "Prediction confidence: medium — LTHR last calibrated 224 days ago"
- "Prediction confidence: low — AeT not measured, LTHR stale"

This sits inside the existing race countdown card, in the "Prediction Trend" header row.

## Capabilities

### Modified Capabilities

- `dashboard`: gains the Needs Your Attention panel on the Overview tab; alerts list becomes severity-sorted; race countdown gains a prediction confidence note.
- `coaching-signals`: alert severity is explicit (today inferred by alert type); a `severity` field SHALL be returned alongside the existing alert dict.

## Impact

- **Code**:
  - `fit/report/sections/cards.py`: new `_attention_items()` builder that aggregates data_health + calibration_status + coaching freshness + checkin gap + Apple Health export age; new `_prediction_confidence()` helper for the race countdown note.
  - `fit/alerts.py`: each alert rule gains an explicit `severity` field (`critical` | `warning` | `info`); `_recent_alerts()` sorts on severity then date.
  - `fit/report/templates/dashboard.html`: new Attention panel section at the top of the Overview tab (above race countdown); race countdown header row updated to include the confidence note.
  - `fit/report/templates/design_system.css`: new `.attention-panel`, `.attention-item`, `.attention-item-critical`, `.attention-item-warning`, `.attention-item-info` classes (extending the existing `.alert-item` pattern).
- **Schema**: none.
- **Tests**:
  - `tests/test_alerts.py`: every alert rule produces a `severity` field; `_recent_alerts()` returns severity-sorted results.
  - New `tests/test_attention.py`: `_attention_items()` returns the right rows given various combinations of stale data / missing calibrations / old checkins.
- **Data**: none.
- **External**: none.

## Risks / Trade-offs

- **The panel could become a wall of warnings.** Five stale sources × multiple alert types could produce 10+ rows. Mitigation: cap at 5 visible items; the rest collapse into a "+N more" link that expands. Also: dedupe — if LTHR is stale, that's one row, not three (calibration_status + data_health + coaching all flag the same fact).
- **Severity is debatable.** AeT-not-measured stays `info` permanently. AeT is a Z2-ceiling refinement, not a primary anchor replacement — LTHR remains the load-bearing calibration regardless of whether AeT lands. AeT-missing is a "you could be more precise" prompt, not a "your zones are broken" warning.
- **Prediction confidence is a heuristic.** "Medium" vs "high" is a judgment call; the rule here is "if any of {LTHR stale, AeT missing, fewer than 2 race data points in last 12 months} then medium." Risk of either over- or under-warning. Mitigation: tune after dogfooding.

## Open Questions

1. Should the Attention panel disappear when empty, or render an empty-state ("You're caught up — nothing pending")? Default proposed: disappear (no celebration noise).
2. Severity for `info`-tier items that are *always* true until acted on (e.g., AeT-not-measured persists forever until the user does the test): does that decay over time? Risk: the item becomes background noise the user stops seeing.
3. Should missed-checkin items aggregate ("5 checkins missed in last 14 days") or render per-day? Aggregation reduces noise but loses precision.
