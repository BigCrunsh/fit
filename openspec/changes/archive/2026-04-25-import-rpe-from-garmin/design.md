## Context

Today, RPE flows from `fit checkin run` into `checkins.rpe` (one row per date) and is then cross-written to all running activities sharing that date. The `activities.rpe` column already exists and is consumed by `compute_srpe()` (sRPE = rpe × duration_min) and the dashboard's per-run cards.

Investigation against the Garmin Connect API confirmed that three relevant fields are exposed on `summaryDTO` of `api.get_activity(id)` when the user has populated them:

| Garmin field | Range | Semantic |
| --- | --- | --- |
| `directWorkoutRpe` | 10/20/.../100 | RPE 1-10 (×10 buckets) |
| `directWorkoutFeel` | 0/25/50/75/100 | "How did you feel?" 5-point scale |
| `directWorkoutComplianceScore` | 0-100 | Plan adherence score |

These fields are **not** present in the bulk `get_activities_by_date` response — only in the per-activity detail response. No description/notes field is exposed.

Constraints:
- Public-repo data hygiene: backfill must not commit personal data.
- Garmin rate limits: existing `_request_with_retry` handles 429 (60s wait) — backfill must use it.
- Test suite uses in-memory SQLite with the full migration chain — schema migration must be additive.
- The codebase prefers `INSERT ON CONFLICT` over `INSERT OR REPLACE` to preserve derived metrics (per CLAUDE.md).

## Goals / Non-Goals

**Goals:**
- Per-activity RPE, feel, and compliance, sourced from Garmin (no duplicate entry).
- Multi-activity days correctly attribute different RPE to different sessions.
- Backfill historical activities once; daily sync keeps fresh activities in sync, including user edits in Garmin Connect.
- sRPE and any RPE-driven analysis read from `activities.rpe` directly.
- Dashboard surfaces all three signals.

**Non-Goals:**
- Migrating historical `checkins.rpe` values into `activities.rpe`. The Garmin import provides authoritative data; legacy values stay in `checkins` as orphaned but non-breaking.
- Free-text run summaries — Garmin's API doesn't expose them.
- Real-time sync of RPE edits in Garmin (we sync on the next `fit sync` run, not via webhooks).

## Decisions

**1. Add columns directly to `activities`, don't reuse `checkins`.**
RPE is a per-activity attribute. The `checkins` table is per-date and has different semantics (sleep, hydration, etc.). Keeping the existing `activities.rpe` column and adding `feel` + `compliance_score` alongside avoids a join in the hot path (sRPE, dashboard) and matches Garmin's data shape.

*Alternative considered:* a separate `activity_rpe` table. Rejected — three nullable columns on the existing row is simpler, and sRPE already lives on `activities`.

**2. Detail-fetch happens during sync, not as a separate step.**
The natural place to fetch detail is right after the bulk activity fetch in `run_sync()`, before enrichment. This keeps a single sync pipeline and ensures derived metrics (sRPE, run-type classification) see RPE values on first computation.

*Alternative:* a separate `fit fetch-rpe` command. Rejected — would require users to remember a second command. Backfill remains a one-shot, but routine sync handles the steady state.

**3. Re-fetch policy: "fill-NULL beyond 14 days, refresh within."**
Users may edit RPE in Garmin Connect days after the run. We refresh activities ≤14 days old on every sync (catches edits) and fill only NULL fields beyond that (avoids overwriting any local-only edits we may add later, and reduces API calls).

*Alternative:* always refresh all activities in the sync window. Rejected — when `--full` runs over months, this would be wasteful. The 14-day window is a heuristic balancing freshness and cost.

**4. Mapping is fixed, not configurable.**
- `rpe = directWorkoutRpe / 10` (clamped 1-10, NULL passthrough)
- `feel = directWorkoutFeel / 25 + 1` (1-5, NULL passthrough)
- `compliance_score = directWorkoutComplianceScore` (direct, NULL passthrough)

Garmin only emits the discrete bucket values listed above, so the mapping is exact.

**5. Backfill is a CLI command (`fit backfill rpe`), not auto-triggered.**
Users explicitly opt in. Backfill walks all running activities lacking RPE/feel/compliance and calls `get_activity` for each, with a progress bar. One-shot — re-running is idempotent.

*Alternative:* fold into `fit recompute`. Rejected — `fit recompute` re-derives metrics from existing data, never makes external API calls. Mixing those concerns would be surprising.

**6. Remove RPE from check-in entirely; do not deprecate slowly.**
The check-in's RPE prompt and the cross-write are both removed. `checkins.rpe` column stays (legacy), but new check-ins write NULL there. This is a clean break — no dual-write phase, no deprecation warnings.

*Alternative:* keep both, prefer Garmin. Rejected — duplicate entry was the original problem; preserving the prompt undermines the change.

**7. sRPE switches source.**
`compute_srpe()` currently reads `checkins.rpe` and applies it to all running activities on that date. New version reads `activities.rpe` directly per-row. The trigger inside `fit checkin` is removed; only the trigger in `fit sync` (after RPE import) remains.

## Risks / Trade-offs

- **Risk:** Garmin returns no RPE for activities the user hasn't tagged → sRPE coverage drops vs. checkin-based system where one date filled all activities.
  - **Mitigation:** Acceptable. The user has confirmed they will enter RPE in Garmin going forward. Coverage will recover within days; historical activities without RPE simply have no sRPE (which is correct — we don't have the data).

- **Risk:** Backfill cost — ~600 detail calls × ~0.3s each ≈ 3 minutes, plus possible 429 backoff.
  - **Mitigation:** Progress bar, `_request_with_retry` already handles 429 with 60s sleep. One-time cost.

- **Risk:** User edits RPE in Garmin >14 days after the activity → we won't pick it up automatically.
  - **Mitigation:** Backfill command can be re-run. Could add a `--refresh` flag that re-fetches even non-NULL fields. Document the 14-day window.

- **Risk:** New columns added to `activities` change the row shape — migration runs against existing in-memory test DBs and the user's production DB.
  - **Mitigation:** Additive migration, both columns nullable. Tests use the full migration chain so this is exercised on every CI run.

- **Risk:** Existing `activities.rpe` may have legacy cross-written values from check-ins. After this change, those become a mix of "from Garmin" and "from old checkin." sRPE numbers may shift.
  - **Mitigation:** Acceptable — sRPE is a coaching signal, not a precise metric. Document in the change log. Users running backfill will see Garmin-sourced values overwrite NULLs but not non-NULLs. If desired, we could add a migration that NULLs `activities.rpe` before backfill, but the user did not request this.

- **Trade-off:** Adding 3 columns vs. JSON blob. Columns chosen for query simplicity and existing pattern in `activities`.

## Migration Plan

1. Add migration file under `migrations/` that adds `feel INTEGER` and `compliance_score INTEGER` columns to `activities`. Both nullable.
2. Tests run the migration via the existing `tests/conftest.py` chain — no test-data migration needed.
3. Production: `fit sync` auto-runs migrations on next invocation. No downtime.
4. Backfill is opt-in via `fit backfill rpe` — users run it once when convenient.
5. **Rollback**: the migration is additive; rolling back the code without the migration leaves the columns unused but valid. If columns must be dropped, a follow-up migration would do so. No data loss either direction.

## Open Questions

- None blocking. Document the 14-day refresh window in the backfill command's help text so users know how to force a full refresh.
