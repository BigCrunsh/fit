-- Per-activity RPE, feel, and compliance imported from Garmin
-- (directWorkoutRpe, directWorkoutFeel, directWorkoutComplianceScore on summaryDTO).
-- activities.rpe already exists (REAL); add feel and compliance_score.
ALTER TABLE activities ADD COLUMN feel INTEGER;
ALTER TABLE activities ADD COLUMN compliance_score INTEGER;
