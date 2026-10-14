-- Run once before deploying the backend that reads/writes these fields.
-- Existing rows intentionally remain NULL: irTimestamp is the dispatch time,
-- and no reliable inspector submission time can be inferred from it.

SELECT DATABASE() AS selected_database, VERSION() AS mysql_version;

SELECT COLUMN_NAME, COLUMN_TYPE, IS_NULLABLE
FROM information_schema.COLUMNS
WHERE TABLE_SCHEMA = DATABASE()
  AND TABLE_NAME = 'inspection_reports'
  AND COLUMN_NAME IN ('submittedAt', 'submissionReceivedAt')
ORDER BY COLUMN_NAME;

ALTER TABLE inspection_reports
    ADD COLUMN submittedAt DATETIME(6) NULL DEFAULT NULL AFTER irTimestamp,
    ADD COLUMN submissionReceivedAt DATETIME(6) NULL DEFAULT NULL
        AFTER submittedAt;

SELECT COLUMN_NAME, COLUMN_TYPE, IS_NULLABLE
FROM information_schema.COLUMNS
WHERE TABLE_SCHEMA = DATABASE()
  AND TABLE_NAME = 'inspection_reports'
  AND COLUMN_NAME IN ('submittedAt', 'submissionReceivedAt')
ORDER BY COLUMN_NAME;
