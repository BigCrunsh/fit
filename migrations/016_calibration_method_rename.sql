-- Rename calibration.method strings to the ubiquitous-language taxonomy (DDD review).
--
-- The trust tiers and behaviour are unchanged — only the labels, so a name no longer
-- contradicts its meaning (see DATA_LINEAGE.md §6 Glossary). Homonyms that confused us
-- (race_extract vs race_estimate; garmin_lt vs garmin_estimate) become self-describing:
--
--   garmin_lt        -> device_lt          (DEVICE: instrument-measured threshold)
--   garmin_estimate  -> device_vo2max      (REFERENCE: wrist VO2max, context only)
--   race_estimate    -> race_observation   (INFORMATIONAL: history/chart row)
--   effort_estimate  -> effort_observation (INFORMATIONAL)
--   race_extract     -> race_candidate     (auto-derived anchor candidate)
--
-- Unchanged: manual, confirmed, activity_max, drift_test, scale.

UPDATE calibration SET method = 'device_lt'          WHERE method = 'garmin_lt';
UPDATE calibration SET method = 'device_vo2max'      WHERE method = 'garmin_estimate';
UPDATE calibration SET method = 'race_observation'   WHERE method = 'race_estimate';
UPDATE calibration SET method = 'effort_observation' WHERE method = 'effort_estimate';
UPDATE calibration SET method = 'race_candidate'     WHERE method = 'race_extract';
