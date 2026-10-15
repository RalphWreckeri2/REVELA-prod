-- Remove the legacy enforcement copies after the generalized backend is live.
--
-- Preconditions:
--   1. The enforcement-state separation migration has been applied.
--   2. Railway is running the backend build that reads/writes enforcement_state
--      and enforcement_events.
--   3. A database backup exists.
--
-- This is a separate, destructive cleanup migration. It intentionally does
-- not TRUNCATE official_registry or any other table. The old enforcement
-- columns and legacy audit table are removed; all other registry data remains.
-- Run the preflight SELECTs first and inspect their results before the DDL.

SELECT DATABASE() AS selected_database, VERSION() AS mysql_version;

-- Every registry business must have generalized business state before the
-- legacy columns are removed.
SELECT
    COUNT(*) AS registry_rows,
    SUM(es.enforcementID IS NULL) AS registry_rows_missing_state
FROM
    official_registry r
    LEFT JOIN enforcement_state es ON es.subjectType COLLATE utf8mb4_unicode_ci = _utf8mb4 'business' COLLATE utf8mb4_unicode_ci
    AND es.subjectID COLLATE utf8mb4_unicode_ci = CAST(
        r.businessID AS CHAR CHARACTER SET utf8mb4
    ) COLLATE utf8mb4_unicode_ci;

-- All old audit rows must already exist, unchanged, in the generalized event
-- table. New-only events in enforcement_events are expected after cutover.
SELECT
    COUNT(*) AS legacy_event_rows,
    SUM(e.eventID IS NULL) AS missing_generalized_events,
    SUM(
        e.eventID IS NOT NULL
        AND (
            NOT(
                legacy.businessID COLLATE utf8mb4_unicode_ci <=> e.subjectID COLLATE utf8mb4_unicode_ci
            )
            OR NOT(
                legacy.eventType COLLATE utf8mb4_unicode_ci <=> e.eventType COLLATE utf8mb4_unicode_ci
            )
            OR NOT(
                legacy.actorUserID <=> e.actorUserID
            )
            OR NOT(
                legacy.reason COLLATE utf8mb4_unicode_ci <=> e.reason COLLATE utf8mb4_unicode_ci
            )
            OR NOT(
                legacy.previousLevel <=> e.previousLevel
            )
            OR NOT(
                legacy.newLevel <=> e.newLevel
            )
            OR NOT(
                legacy.previousBlack <=> e.previousBlack
            )
            OR NOT(
                legacy.newBlack <=> e.newBlack
            )
            OR NOT(
                legacy.createdAt <=> e.createdAt
            )
        )
    ) AS mismatched_generalized_events
FROM
    registry_enforcement_events legacy
    LEFT JOIN enforcement_events e ON e.eventID = legacy.eventID
    AND e.subjectType COLLATE utf8mb4_unicode_ci = _utf8mb4 'business' COLLATE utf8mb4_unicode_ci;

-- Informational only: old columns may differ after the backend cutover. The
-- generalized enforcement_state is authoritative; do not copy old values back.
SELECT
    COUNT(*) AS registry_rows,
    SUM(
        NOT(
            es.warningLevel <=> r.warningLevel
        )
        OR NOT(
            es.blackLocked <=> r.blackLocked
        )
        OR NOT(
            es.blackLockedAt <=> r.blackLockedAt
        )
        OR NOT(
            es.blackLockedBy <=> r.blackLockedBy
        )
        OR NOT(
            es.blackLockReason COLLATE utf8mb4_unicode_ci <=> r.blackLockReason COLLATE utf8mb4_unicode_ci
        )
        OR NOT(
            es.blackDispatchUnlocked <=> r.blackDispatchUnlocked
        )
        OR NOT(
            es.blackUnlockedAt <=> r.blackUnlockedAt
        )
        OR NOT(
            es.blackUnlockedBy <=> r.blackUnlockedBy
        )
        OR NOT(
            es.blackUnlockReason COLLATE utf8mb4_unicode_ci <=> r.blackUnlockReason COLLATE utf8mb4_unicode_ci
        )
        OR NOT(
            es.warningClearedAt <=> r.warningClearedAt
        )
        OR NOT(
            es.warningClearedBy <=> r.warningClearedBy
        )
        OR NOT(
            es.warningClearReason COLLATE utf8mb4_unicode_ci <=> r.warningClearReason COLLATE utf8mb4_unicode_ci
        )
        OR NOT(
            es.lastInspectionResult COLLATE utf8mb4_unicode_ci <=> r.lastInspectionResult COLLATE utf8mb4_unicode_ci
        )
        OR NOT(
            es.lastInspectedAt <=> r.lastInspectedAt
        )
    ) AS rows_with_legacy_state_drift
FROM
    official_registry r
    JOIN enforcement_state es ON es.subjectType COLLATE utf8mb4_unicode_ci = _utf8mb4 'business' COLLATE utf8mb4_unicode_ci
    AND es.subjectID COLLATE utf8mb4_unicode_ci = CAST(
        r.businessID AS CHAR CHARACTER SET utf8mb4
    ) COLLATE utf8mb4_unicode_ci;

-- Destructive DDL: execute only after reviewing the preflight results above.
ALTER TABLE official_registry
DROP INDEX idx_reg_black_locked,
DROP INDEX idx_reg_warning_level,
DROP INDEX idx_reg_black_unlocked,
DROP COLUMN warningLevel,
DROP COLUMN blackLocked,
DROP COLUMN blackLockedAt,
DROP COLUMN blackLockedBy,
DROP COLUMN blackLockReason,
DROP COLUMN blackDispatchUnlocked,
DROP COLUMN blackUnlockedAt,
DROP COLUMN blackUnlockedBy,
DROP COLUMN blackUnlockReason,
DROP COLUMN warningClearedAt,
DROP COLUMN warningClearedBy,
DROP COLUMN warningClearReason,
DROP COLUMN lastInspectionResult,
DROP COLUMN lastInspectedAt;

DROP TABLE registry_enforcement_events;