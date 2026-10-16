-- `registry_detected` is 17 characters; VARCHAR(16) made matched POI inserts fail.
ALTER TABLE geospatial_logs
MODIFY COLUMN source VARCHAR(24) COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT 'unknown' COMMENT 'Where this pin came from: registry | registry_detected | detection | manual | unknown.';