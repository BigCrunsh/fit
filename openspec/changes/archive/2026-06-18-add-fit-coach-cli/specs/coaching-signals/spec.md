## ADDED Requirements

### Requirement: Coaching analysis via the `fit coach` CLI
The system SHALL provide a `fit coach` command that produces coaching analysis from the terminal by
shelling out to the headless Claude CLI, replacing the former MCP-server + coaching-skill split with
a single CLI-owned source of truth (the context-assembly and the coaching instructions both live in
the shared `fit/coaching/` core).

`fit coach` SHALL: (1) assemble the structured coaching context — ACWR + safety status, calibration
staleness, data-source health, active-phase targets vs actuals (compliance), zone distribution by
time, run-type breakdown, speed_per_bpm and cadence trends, RPE predicted-vs-actual patterns, sleep
mismatches, race predictions, cross-domain correlations, active alerts, today's run, plan adherence,
and a previous-coaching summary for continuity; (2) feed that context plus the coaching instructions
to the Claude CLI (headless, batched); (3) parse the returned insights and validate them (`type` ∈
{warning, critical, positive, info, target}, title and body present, body ≥ 20 chars); (4) archive
the prior `reports/coaching.json` to `coaching_history.json` and write the new notes atomically.

The command SHALL **fail closed**: if the Claude CLI is missing, unauthenticated, times out, exits
non-zero, or returns an unparseable/invalid response, it prints an actionable message and **writes
nothing** — `reports/coaching.json` is never corrupted. `--no-save` runs and prints without writing;
the context window defaults to all available data (dashboard parity).

#### Scenario: Coaching analysis is produced and saved
- **WHEN** the athlete runs `fit coach` and the Claude CLI returns valid insights
- **THEN** the analysis is printed and `reports/coaching.json` is updated (prior notes archived to `coaching_history.json`), in the same format the dashboard already reads

#### Scenario: Failure never corrupts the notes file
- **WHEN** the Claude CLI is missing/unauthenticated, times out, exits non-zero, or returns unparseable or schema-invalid insights
- **THEN** `fit coach` prints an actionable error and leaves `reports/coaching.json` untouched

#### Scenario: Insight validation matches the prior writer
- **WHEN** a returned insight has a body shorter than 20 characters or a type outside the allowed set
- **THEN** it is rejected with the same validation error the previous note-writer used, and nothing is written

#### Scenario: Dry run does not write
- **WHEN** the athlete runs `fit coach --no-save`
- **THEN** the analysis is printed and no file is written
