-- Enforcement ladder schema: Orange warning levels and the Black lock.
--
-- Run ONCE, before any code reads or writes these fields.
--
-- This file is additive only. It adds columns and one new table; it changes
-- no existing column, no existing index and no existing row. Every new column
-- is either NOT NULL with a constant default or nullable, so it is safe to
-- apply while the application is running.
--
-- It is NOT safe to re-run. MySQL has no ADD COLUMN IF NOT EXISTS and no
-- ADD KEY IF NOT EXISTS (those are MariaDB), so the pre-check below is for a
-- human to read, not a guard: re-running this file fails with
-- ERROR 1060 Duplicate column name or ERROR 1061 Duplicate key name. A
-- multi-column ADD COLUMN is applied as one atomic rebuild, so if any single
-- column already exists the whole ALTER is rejected and nothing is added.
-- A half-applied run cannot be resumed by re-running; drop the columns that
-- did land first. Only the CREATE TABLE IF NOT EXISTS is re-runnable.
--
-- No application code reads or writes these columns yet. Behaviour ships
-- separately (see the ladder design).
--
-- Semantics intended by these columns:
--   warningLevel  0..3. 0 = no warning. Incremented only by a verified Orange
--               inspection result, clamped at 3. Never touched by sync,
--               import, rollover or manual edit.
--   blackLocked  permanent habitual-offender lock, independent of
--               applicationStatus. Only a SUPER_ADMIN unlock path may clear
--               it; no other role, route, sync or rollover may.
--   The *_At / *_By / *Reason triplets record who set what and why. They are
--       the durable record; registry_enforcement_events is the append-only
--       history.
--
-- Do not infer or backfill historical values here. Backfilling warningLevel
-- from inspection history is a separate, reviewed script run after the
-- preview queries have been inspected.

SELECT DATABASE() AS selected_database, VERSION() AS mysql_version;

-- ── Pre-check: what already exists ───────────────────────────────────────────
SELECT
    COLUMN_NAME,
    COLUMN_TYPE,
    IS_NULLABLE,
    COLUMN_DEFAULT
FROM information_schema.COLUMNS
WHERE
    TABLE_SCHEMA = DATABASE()
    AND TABLE_NAME = 'official_registry'
    AND COLUMN_NAME IN (
        'warningLevel',
        'blackLocked',
        'blackLockedAt',
        'blackLockedBy',
        'blackLockReason',
        'warningClearedAt',
        'warningClearedBy',
        'warningClearReason',
        'lastInspectionResult',
        'lastInspectedAt'
    )
ORDER BY COLUMN_NAME;

SELECT TABLE_NAME
FROM information_schema.TABLES
WHERE
    TABLE_SCHEMA = DATABASE()
    AND TABLE_NAME = 'registry_enforcement_events';

-- ── official_registry: ladder state ──────────────────────────────────────────
ALTER TABLE official_registry
ADD COLUMN warningLevel TINYINT UNSIGNED NOT NULL DEFAULT 0 COMMENT 'Verified Orange warnings issued, 0..3. Clamped at 3.' AFTER applicationStatus,
ADD COLUMN blackLocked TINYINT(1) NOT NULL DEFAULT 0 COMMENT '1 = permanent habitual-offender lock. Cleared only by a SUPER_ADMIN unlock.' AFTER warningLevel,
ADD COLUMN blackLockedAt DATETIME NULL DEFAULT NULL AFTER blackLocked,
ADD COLUMN blackLockedBy INT NULL DEFAULT NULL COMMENT 'users.userID of the verifying admin who applied the lock.' AFTER blackLockedAt,
ADD COLUMN blackLockReason VARCHAR(255) NULL DEFAULT NULL AFTER blackLockedBy,
ADD COLUMN warningClearedAt DATETIME NULL DEFAULT NULL AFTER blackLockReason,
ADD COLUMN warningClearedBy INT NULL DEFAULT NULL COMMENT 'users.userID of whoever cleared the Orange warning.' AFTER warningClearedAt,
ADD COLUMN warningClearReason VARCHAR(255) NULL DEFAULT NULL AFTER warningClearedBy,
ADD COLUMN lastInspectionResult VARCHAR(10) NULL DEFAULT NULL COMMENT 'Most recent verified inspection result: Green/Red/Yellow/Orange/Black/Purple.' AFTER warningClearReason,
ADD COLUMN lastInspectedAt DATETIME(6) NULL DEFAULT NULL COMMENT 'When that result was verified.' AFTER lastInspectionResult;

-- Non-unique indexes: they only ever narrow a scan, and the columns are
-- low-cardinality, so they are deliberately not UNIQUE.
ALTER TABLE official_registry
ADD KEY idx_reg_black_locked (blackLocked),
ADD KEY idx_reg_warning_level (warningLevel);

-- ── registry_enforcement_events: append-only audit ───────────────────────────
-- Separate from inspection_lifecycle_events, which is keyed on a required
-- reportID and therefore cannot record an unlock or a clearance that has no
-- inspection behind it. Also separate from registry_workflow_events, which
-- has no actorUserID column at all.
CREATE TABLE IF NOT EXISTS registry_enforcement_events (
    eventID BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    businessID VARCHAR(50) COLLATE utf8mb4_unicode_ci NOT NULL,
    eventType ENUM(
        'warning_issued',
        'warning_cleared',
        'black_locked',
        'black_unlocked'
    ) COLLATE utf8mb4_unicode_ci NOT NULL,
    actorUserID INT NULL DEFAULT NULL COMMENT 'users.userID of the actor. NULL only for system actions.',
    reason VARCHAR(255) COLLATE utf8mb4_unicode_ci NULL DEFAULT NULL,
    previousLevel TINYINT UNSIGNED NULL DEFAULT NULL,
    newLevel TINYINT UNSIGNED NULL DEFAULT NULL,
    previousBlack TINYINT(1) NULL DEFAULT NULL,
    newBlack TINYINT(1) NULL DEFAULT NULL,
    createdAt DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    KEY idx_ree_business (businessID, eventID),
    KEY idx_ree_type_time (eventType, createdAt)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_unicode_ci;

-- ── Post-check: confirm what is now present ─────────────────────────────────
SELECT
    COLUMN_NAME,
    COLUMN_TYPE,
    IS_NULLABLE,
    COLUMN_DEFAULT
FROM information_schema.COLUMNS
WHERE
    TABLE_SCHEMA = DATABASE()
    AND TABLE_NAME = 'official_registry'
    AND COLUMN_NAME IN (
        'warningLevel',
        'blackLocked',
        'blackLockedAt',
        'blackLockedBy',
        'blackLockReason',
        'warningClearedAt',
        'warningClearedBy',
        'warningClearReason',
        'lastInspectionResult',
        'lastInspectedAt'
    )
ORDER BY COLUMN_NAME;

SELECT
    INDEX_NAME,
    NON_UNIQUE,
    GROUP_CONCAT(
        COLUMN_NAME
        ORDER BY SEQ_IN_INDEX
    ) AS columns_in_index
FROM information_schema.STATISTICS
WHERE
    TABLE_SCHEMA = DATABASE()
    AND TABLE_NAME = 'official_registry'
    AND INDEX_NAME IN (
        'idx_reg_black_locked',
        'idx_reg_warning_level'
    )
GROUP BY
    INDEX_NAME,
    NON_UNIQUE;

SELECT
    COLUMN_NAME,
    COLUMN_TYPE,
    IS_NULLABLE
FROM information_schema.COLUMNS
WHERE
    TABLE_SCHEMA = DATABASE()
    AND TABLE_NAME = 'registry_enforcement_events'
ORDER BY ORDINAL_POSITION;

-- Existing rows must read as "no warning, not locked" without backfill:
SELECT
    COUNT(*) AS total_rows,
    SUM(warningLevel <> 0) AS nonzero_warning_level,
    SUM(blackLocked <> 0) AS locked_rows
FROM official_registry;