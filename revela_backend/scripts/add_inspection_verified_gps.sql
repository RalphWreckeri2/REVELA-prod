-- Apply once to an existing REVELA database before deploying the GPS workflow.
ALTER TABLE inspection_reports
ADD COLUMN verifiedLatitude DECIMAL(10, 8) DEFAULT NULL AFTER nearestLandmark,
ADD COLUMN verifiedLongitude DECIMAL(11, 8) DEFAULT NULL AFTER verifiedLatitude,
ADD COLUMN verifiedAccuracy DECIMAL(8, 2) DEFAULT NULL AFTER verifiedLongitude;