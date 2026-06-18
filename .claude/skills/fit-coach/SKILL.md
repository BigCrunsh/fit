---
name: fit-coach
description: Coaching and training analysis for the fit running platform. Use whenever the user asks how their running or marathon training is going, wants a check-in or feedback on their running, what to focus on, whether they're overtraining or recovered, whether to do or adjust a run or long run, or how their pacing/zones/mileage/load look — phrased any way, casual or formal, even without the words "coach" or "review". Do NOT use for non-running reviews. This skill now redirects to the `fit coach` CLI command.
---

# Fit Coach — moved to the CLI

Coaching now lives in the **`fit coach`** command, not this skill. It owns one source of truth: the
coaching context-assembly and the coaching instructions both live in `fit/coaching/`, and the
command shells out to the Claude CLI to produce and save the analysis. This replaced the old
MCP-tools + skill split (which had to be kept in sync by hand).

**To run a coaching review, run the command** (or tell the user to):

```
fit coach              # full read; saves to reports/coaching.json, then `fit report`
fit coach --no-save    # print without writing
fit coach --json       # raw insights JSON
```

It assembles ACWR/safety, zone compliance, phase fit, recovery, the marathon forecast, plan
adherence, the athlete's own correlations, and previous-coaching continuity, then asks Claude for a
prioritized coach's read and writes the notes the dashboard renders.

The **fit MCP server** still exists for free-form data exploration (`execute_sql_query`,
`get_health_summary`, `get_run_context`, `explore_database_structure`, `get_table_details`,
`check_dashboard_freshness`) — but it no longer assembles coaching context or writes coaching notes.
