-- Add columns available from Garmin API splits endpoint
ALTER TABLE activity_splits ADD COLUMN max_hr REAL;
ALTER TABLE activity_splits ADD COLUMN elevation_loss_m REAL;
ALTER TABLE activity_splits ADD COLUMN intensity_type TEXT;
ALTER TABLE activity_splits ADD COLUMN wkt_step_index INTEGER;
