-- Add a `flags` column to the calibration table.
--
-- Flags are a JSON array of stable tag strings (e.g. ["implausible_value"],
-- ["agrees_with_prior"], ["unexpected_direction"]) that explain WHY a row
-- got the confidence level it did. Auto-extract paths now always insert a
-- row — implausible/spike readings get `confidence='low'` plus a flag list
-- rather than being silently dropped. The history chart styles points by
-- confidence so anomalies stay visible without driving the active line.
--
-- Defaults to '[]' so existing rows are treated as "no flags" without a
-- backfill pass. Retroactive flagging (walking history to apply the
-- taxonomy) is a separate opportunity, not part of this migration.

ALTER TABLE calibration ADD COLUMN flags TEXT DEFAULT '[]';
