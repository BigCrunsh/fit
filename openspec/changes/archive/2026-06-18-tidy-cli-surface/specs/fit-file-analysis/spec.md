## MODIFIED Requirements

### Requirement: .fit file download with opt-in and caching
The system SHALL download .fit files gated behind `sync.download_fit_files` config toggle (default false) or `fit sync --splits` flag. Files cached in `~/.fit/fit-files/{activity_id}.fit`. Track status via `fit_file_path` and `splits_status` columns on activities (pending/parsed/failed/skipped). Max downloads per sync: configurable (default 20). Bulk backfill: `fit sync --splits --backfill` with rate control (max 20 per batch, 2s delay to avoid Garmin throttling). `fit splits --activity-id <id>` remains for one-off per-activity replay; `fit splits --backfill` is a deprecated alias of `fit sync --splits --backfill` (warns, still runs for one release).

#### Scenario: Download disabled by default
- **WHEN** `sync.download_fit_files` is false and user runs `fit sync`
- **THEN** no .fit files downloaded

#### Scenario: Per-file failure handling
- **WHEN** a .fit file is corrupt or from an unsupported activity (swim, treadmill)
- **THEN** splits_status='failed', error logged, sync continues

#### Scenario: Rate-limited backfill
- **WHEN** `fit sync --splits --backfill` processes 200+ activities
- **THEN** downloads 20 at a time with 2s delay between batches

#### Scenario: Deprecated `fit splits --backfill` still works
- **WHEN** user runs `fit splits --backfill` (the former command)
- **THEN** it runs the same bulk backfill and prints a one-line deprecation notice pointing at `fit sync --splits --backfill`
