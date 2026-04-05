Generate coaching insights for the fit platform.

**Steps:**

1. Call the `check_dashboard_freshness()` MCP tool to see if data is current.
   - If the dashboard hasn't been generated recently, suggest running `fit report` first.

2. Call the `get_coaching_context()` MCP tool to get the structured data summary.
   - This includes: zone boundaries (IMPORTANT: Z2 ceiling from config, NOT 150 bpm), ACWR, phase targets vs actuals, run type breakdown, speed_per_bpm trends, calibration staleness, health metrics, goals.

3. Analyze the coaching context. Focus on:
   - **ACWR safety**: Is the training load safe? Spike risk?
   - **Zone compliance**: How does actual Z1+Z2% compare to the active phase target?
   - **Training structure**: Run type mix — enough easy runs? Quality sessions appropriate for the phase?
   - **Efficiency trend**: Is speed_per_bpm improving or declining?
   - **Consistency**: How many consecutive weeks with 3+ runs?
   - **Calibration gaps**: Any stale calibrations that need attention?
   - **Recovery signals**: RHR, HRV, sleep, readiness trends
   - **Actionable recommendation**: What should the athlete do THIS WEEK?

4. If deeper investigation is needed, use `execute_sql_query()` to dig into specific data points.

5. Format insights as a JSON array and call `save_coaching_notes()` to persist them:
   ```json
   [
     {"type": "critical|warning|positive|info|target", "title": "Short title", "body": "Analysis with specific numbers from the data."}
   ]
   ```
   Types: `critical` (action needed now), `warning` (caution), `positive` (good news), `info` (context), `target` (goal progress).

6. After saving, suggest running `fit report` to update the dashboard with the new coaching notes.

**IMPORTANT:**
- Always use the zone boundaries from `get_coaching_context()`. NEVER default to HR 150 for "easy" — use the actual Z2 ceiling from the config.
- Reference specific numbers from the data in every insight.
- Be direct and actionable, not generic.
- **EVERY insight MUST have a `body` field** with the full analysis paragraph (2-5 sentences, specific numbers, actionable). The tool will REJECT insights with empty or missing body text. Do NOT save title-only insights — the dashboard renders both title AND body.
