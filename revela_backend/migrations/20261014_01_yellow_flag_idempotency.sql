-- Additive prerequisite for offline Yellow Flag retries.
-- Review the selected database and geospatial_logs schema before applying.
-- Existing rows remain unchanged; legacy clients may continue to omit the key.
ALTER TABLE geospatial_logs
    ADD COLUMN clientSubmissionID CHAR(36)
        CHARACTER SET ascii COLLATE ascii_bin NULL;

CREATE UNIQUE INDEX uq_geo_reporter_submission
    ON geospatial_logs (reportedByUserID, clientSubmissionID);
