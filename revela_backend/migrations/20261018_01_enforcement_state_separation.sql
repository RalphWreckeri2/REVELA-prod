-- Enforcement state separation (additive migration; reviewed against the
-- 2026-10-15 MySQL dump for database railway).
--
-- This moves the ownership of enforcement state out of official_registry so
-- it can later cover both registered businesses and unregistered map pins.
-- It does not change application code, drop old columns, or delete old events.
-- The current application still reads/writes those old columns and
-- registry_enforcement_events. Cleanup is unsafe until a later application
-- cutover has been deployed and verified.
--
-- Subject keys used by the future application code:
--   ('business', businessID)       for an official_registry business
--   ('geospatial_log', CAST(logID AS CHAR)) for an unregistered detection pin
--
-- No foreign keys are used because the target is polymorphic and enforcement
-- history must remain addressable even if a registry row or pin is removed.
-- Deletion/archive behavior for those subjects must be settled before the app
-- starts writing to these tables.
--
-- Preflight: confirm this is the intended database and that both source
-- tables exist. The source columns are retained after the copy for a later,
-- separately reviewed application cutover and cleanup migration.
SELECT DATABASE() AS selected_database, VERSION() AS mysql_version;

SELECT COUNT(*) AS registry_rows_to_copy FROM official_registry;

SELECT COUNT(*) AS registry_events_to_copy
FROM registry_enforcement_events;

SELECT
    COUNT(*) AS unregistered_black_pins_to_copy
FROM geospatial_logs g
WHERE
    g.flagColor = 'Black'
    AND NOT EXISTS (
        SELECT 1
        FROM official_registry r
        WHERE (
                g.businessID IS NOT NULL
                AND r.businessID = g.businessID
            )
            OR (
                g.placeID IS NOT NULL
                AND r.placeID = g.placeID
                AND (
                    g.businessID IS NULL
                    OR r.businessID = g.businessID
                )
            )
            OR (
                g.businessID IS NULL
                AND r.barangayID = g.barangayID
                AND r.businessName = g.detectedName
            )
    );

SELECT
    COUNT(*) AS unregistered_orange_pins_needing_review
FROM geospatial_logs g
WHERE
    g.flagColor = 'Orange'
    AND NOT EXISTS (
        SELECT 1
        FROM official_registry r
        WHERE (
                g.businessID IS NOT NULL
                AND r.businessID = g.businessID
            )
            OR (
                g.placeID IS NOT NULL
                AND r.placeID = g.placeID
                AND (
                    g.businessID IS NULL
                    OR r.businessID = g.businessID
                )
            )
            OR (
                g.businessID IS NULL
                AND r.barangayID = g.barangayID
                AND r.businessName = g.detectedName
            )
    )
    AND (
        (
            NOT EXISTS (
                SELECT 1
                FROM inspection_lifecycle_events e
                WHERE
                    e.targetLogID = g.logID
                    AND e.eventType = 'verified'
                    AND e.inspectionResult = 'Orange'
            )
            AND NOT EXISTS (
                SELECT 1
                FROM inspection_reports ir
                WHERE
                    ir.targetType = 'geospatial_log'
                    AND ir.targetID = g.logID
                    AND ir.verificationStatus = 'Verified'
                    AND ir.inspectionResult = 'Orange'
            )
        )
        OR NOT EXISTS (
            SELECT 1
            FROM inspection_lifecycle_events e
            WHERE
                e.targetLogID = g.logID
                AND e.eventType IN ('dispatched', 'reassigned')
                AND e.flagColorAtEvent IN (
                    'Red',
                    'Yellow',
                    'Green',
                    'Purple'
                )
        )
    );

CREATE TABLE IF NOT EXISTS enforcement_state (
    enforcementID BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    subjectType ENUM('business', 'geospatial_log') NOT NULL,
    subjectID VARCHAR(50) COLLATE utf8mb4_unicode_ci NOT NULL,
    warningLevel TINYINT UNSIGNED NOT NULL DEFAULT 0 COMMENT 'Verified Orange warning level, 0..3.',
    warningBaseColor VARCHAR(50) COLLATE utf8mb4_unicode_ci NULL DEFAULT NULL COMMENT 'Non-Orange color to restore when the warning is cleared.',
    blackLocked TINYINT(1) NOT NULL DEFAULT 0 COMMENT 'Permanent Black enforcement lock.',
    blackLockedAt DATETIME NULL DEFAULT NULL,
    blackLockedBy INT NULL DEFAULT NULL,
    blackLockReason VARCHAR(255) COLLATE utf8mb4_unicode_ci NULL DEFAULT NULL,
    blackDispatchUnlocked TINYINT(1) NOT NULL DEFAULT 0 COMMENT 'Single-use SUPER_ADMIN dispatch grant; does not clear Black.',
    blackUnlockedAt DATETIME NULL DEFAULT NULL,
    blackUnlockedBy INT NULL DEFAULT NULL,
    blackUnlockReason VARCHAR(255) COLLATE utf8mb4_unicode_ci NULL DEFAULT NULL,
    warningClearedAt DATETIME NULL DEFAULT NULL,
    warningClearedBy INT NULL DEFAULT NULL,
    warningClearReason VARCHAR(255) COLLATE utf8mb4_unicode_ci NULL DEFAULT NULL,
    lastInspectionResult VARCHAR(10) COLLATE utf8mb4_unicode_ci NULL DEFAULT NULL,
    lastInspectedAt DATETIME(6) NULL DEFAULT NULL,
    UNIQUE KEY uq_enforcement_state_subject (subjectType, subjectID),
    KEY idx_enforcement_state_warning (warningLevel),
    KEY idx_enforcement_state_black (blackLocked),
    KEY idx_enforcement_state_dispatch (blackDispatchUnlocked)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS enforcement_events (
    eventID BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    subjectType ENUM('business', 'geospatial_log') NOT NULL,
    subjectID VARCHAR(50) COLLATE utf8mb4_unicode_ci NOT NULL,
    eventType ENUM(
        'warning_issued',
        'warning_cleared',
        'black_locked',
        'black_unlocked',
        'black_relocked'
    ) COLLATE utf8mb4_unicode_ci NOT NULL,
    actorUserID INT NULL DEFAULT NULL,
    reason VARCHAR(255) COLLATE utf8mb4_unicode_ci NULL DEFAULT NULL,
    previousLevel TINYINT UNSIGNED NULL DEFAULT NULL,
    newLevel TINYINT UNSIGNED NULL DEFAULT NULL,
    previousBlack TINYINT(1) NULL DEFAULT NULL,
    newBlack TINYINT(1) NULL DEFAULT NULL,
    createdAt DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    KEY idx_enforcement_events_subject (
        subjectType,
        subjectID,
        eventID
    ),
    KEY idx_enforcement_events_type_time (eventType, createdAt)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_unicode_ci;

-- Copy every registry row so the future state reader can use one consistent
-- source. INSERT IGNORE makes a partially completed additive migration
-- resumable without overwriting state already present in the new table.
INSERT IGNORE INTO
    enforcement_state (
        subjectType,
        subjectID,
        warningLevel,
        warningBaseColor,
        blackLocked,
        blackLockedAt,
        blackLockedBy,
        blackLockReason,
        blackDispatchUnlocked,
        blackUnlockedAt,
        blackUnlockedBy,
        blackUnlockReason,
        warningClearedAt,
        warningClearedBy,
        warningClearReason,
        lastInspectionResult,
        lastInspectedAt
    )
SELECT
    'business',
    businessID,
    warningLevel,
    CASE
        WHEN warningLevel > 0 THEN CASE applicationStatus
            WHEN 'Active' THEN 'Green'
            WHEN 'Expired' THEN 'Red'
            WHEN 'Revoked' THEN 'Black'
            WHEN 'Blacklisted' THEN 'Black'
            WHEN 'Pending' THEN 'Yellow'
            WHEN 'Closed' THEN 'Purple'
            ELSE NULL
        END
        ELSE NULL
    END,
    blackLocked,
    blackLockedAt,
    blackLockedBy,
    blackLockReason,
    blackDispatchUnlocked,
    blackUnlockedAt,
    blackUnlockedBy,
    blackUnlockReason,
    warningClearedAt,
    warningClearedBy,
    warningClearReason,
    lastInspectionResult,
    lastInspectedAt
FROM official_registry;

-- Seed enforcement state for unregistered pins. Their current Black color is
-- direct state, so it can be carried over without inventing an actor or a
-- reason. Orange is copied only when a verified Orange result is recorded;
-- its level uses the pin's noticeLevel, bounded by 3. Pins with no verified
-- Orange history are deliberately omitted and listed below for human review.
INSERT IGNORE INTO
    enforcement_state (
        subjectType,
        subjectID,
        warningLevel,
        warningBaseColor,
        blackLocked,
        blackDispatchUnlocked
    )
SELECT
    'geospatial_log',
    CAST(g.logID AS CHAR),
    CASE
        WHEN g.flagColor = 'Orange' THEN LEAST(
            GREATEST(
                COALESCE(g.noticeLevel, 0),
                COALESCE(
                    orange_events.orangeCount,
                    orange_reports.orangeCount,
                    0
                )
            ),
            3
        )
        ELSE 0
    END,
    CASE
        WHEN g.flagColor = 'Orange' THEN (
            SELECT e.flagColorAtEvent
            FROM inspection_lifecycle_events e
            WHERE
                e.targetLogID = g.logID
                AND e.eventType IN ('dispatched', 'reassigned')
                AND e.flagColorAtEvent IN (
                    'Red',
                    'Yellow',
                    'Green',
                    'Purple'
                )
            ORDER BY e.eventID ASC
            LIMIT 1
        )
        ELSE NULL
    END,
    CASE
        WHEN g.flagColor = 'Black' THEN 1
        ELSE 0
    END,
    0
FROM
    geospatial_logs g
    LEFT JOIN (
        SELECT targetLogID, COUNT(*) AS orangeCount
        FROM inspection_lifecycle_events
        WHERE
            eventType = 'verified'
            AND inspectionResult = 'Orange'
        GROUP BY
            targetLogID
    ) orange_events ON orange_events.targetLogID = g.logID
    LEFT JOIN (
        SELECT targetID, COUNT(*) AS orangeCount
        FROM inspection_reports
        WHERE
            targetType = 'geospatial_log'
            AND verificationStatus = 'Verified'
            AND inspectionResult = 'Orange'
        GROUP BY
            targetID
    ) orange_reports ON orange_reports.targetID = g.logID
WHERE (
        g.flagColor = 'Black'
        OR (
            g.flagColor = 'Orange'
            AND COALESCE(
                orange_events.orangeCount,
                orange_reports.orangeCount,
                0
            ) > 0
        )
    )
    AND NOT EXISTS (
        SELECT 1
        FROM official_registry r
        WHERE (
                g.businessID IS NOT NULL
                AND r.businessID = g.businessID
            )
            OR (
                g.placeID IS NOT NULL
                AND r.placeID = g.placeID
                AND (
                    g.businessID IS NULL
                    OR r.businessID = g.businessID
                )
            )
            OR (
                g.businessID IS NULL
                AND r.barangayID = g.barangayID
                AND r.businessName = g.detectedName
            )
    );

-- NOT GUESSED: review Orange pins if either verified Orange history or a
-- non-Orange baseline color is missing. They cannot be safely cleared yet.
SELECT g.logID, g.detectedName, g.barangayID, g.noticeLevel
FROM geospatial_logs g
WHERE
    g.flagColor = 'Orange'
    AND NOT EXISTS (
        SELECT 1
        FROM official_registry r
        WHERE (
                g.businessID IS NOT NULL
                AND r.businessID = g.businessID
            )
            OR (
                g.placeID IS NOT NULL
                AND r.placeID = g.placeID
                AND (
                    g.businessID IS NULL
                    OR r.businessID = g.businessID
                )
            )
            OR (
                g.businessID IS NULL
                AND r.barangayID = g.barangayID
                AND r.businessName = g.detectedName
            )
    )
    AND (
        (
            NOT EXISTS (
                SELECT 1
                FROM inspection_lifecycle_events e
                WHERE
                    e.targetLogID = g.logID
                    AND e.eventType = 'verified'
                    AND e.inspectionResult = 'Orange'
            )
            AND NOT EXISTS (
                SELECT 1
                FROM inspection_reports ir
                WHERE
                    ir.targetType = 'geospatial_log'
                    AND ir.targetID = g.logID
                    AND ir.verificationStatus = 'Verified'
                    AND ir.inspectionResult = 'Orange'
            )
        )
        OR NOT EXISTS (
            SELECT 1
            FROM inspection_lifecycle_events e
            WHERE
                e.targetLogID = g.logID
                AND e.eventType IN ('dispatched', 'reassigned')
                AND e.flagColorAtEvent IN (
                    'Red',
                    'Yellow',
                    'Green',
                    'Purple'
                )
        )
    );

-- Preserve the current append-only audit history under the generalized key.
-- Requires the existing registry_enforcement_events table, including its
-- createdAt column and black_relocked event value.
INSERT IGNORE INTO
    enforcement_events (
        eventID,
        subjectType,
        subjectID,
        eventType,
        actorUserID,
        reason,
        previousLevel,
        newLevel,
        previousBlack,
        newBlack,
        createdAt
    )
SELECT
    eventID,
    'business',
    businessID,
    eventType,
    actorUserID,
    reason,
    previousLevel,
    newLevel,
    previousBlack,
    newBlack,
    createdAt
FROM registry_enforcement_events;

-- Post-checks: copied values and event totals.
SELECT
    subjectType,
    COUNT(*) AS state_rows,
    SUM(warningLevel > 0) AS warned_subjects,
    SUM(blackLocked = 1) AS black_locked_subjects
FROM enforcement_state
GROUP BY
    subjectType;

SELECT subjectType, COUNT(*) AS event_rows
FROM enforcement_events
GROUP BY
    subjectType;

-- Intentionally no DROP statements in this migration. The running backend
-- still depends on the source columns and registry_enforcement_events.