-- REVELA migration 20261016_01: Black dispatch unlock.
--
-- Run ONCE, before any code reads or writes these fields.
--
-- MySQL has no ADD COLUMN IF NOT EXISTS and no ADD KEY IF NOT EXISTS (those
-- are MariaDB), so the pre-check below is for a human to read, not a guard:
-- re-running this file fails with ERROR 1060 Duplicate column name or
-- ERROR 1061 Duplicate key name. A multi-column ADD COLUMN is one atomic
-- rebuild, so if any single column already exists the whole ALTER is
-- rejected and nothing is added. Do not re-run.
--
-- Additive only. It changes no existing column, no existing index and no
-- existing row. Every new column is NOT NULL with a constant default or
-- nullable, so it is safe to apply while the application is running.
--
-- What these columns mean:
--   blackDispatchUnlocked  A SUPER_ADMIN has granted ONE inspection of a
--               Black locked business. It does not lift the lock: the business
--               stays Black, blackLocked stays 1 and applicationStatus is
--               untouched. It only opens the eligibility gate so an inspector
--               can be dispatched exactly once.
--               Single use. When that inspection reaches a terminal state -
--               verified, cancelled, or reassigned away - the grant is
--               consumed and the column returns to 0, and a black_relocked
--               event is written. The unlock reason and its author are kept
--               as history; a new grant overwrites the previous one's who and
--               when, which is why registry_enforcement_events is the durable
--               record.
--   blackUnlockedAt/By/Reason  Who granted the current grant and why.
--               blackUnlockReason is optional - the reason is for the audit
--               trail, not for enforcement.
--
-- Why this is not a colour change:
--   The Map renders Black because blackLocked wins the ladder precedence.
--   blackDispatchUnlocked is deliberately NOT part of that precedence. A
--   business that has been granted one inspection must still read Black on
--   every screen, or the unlock would silently become a clearance.
--
-- Where the code stays safe if this has not been applied:
--   Every reader treats a missing blackDispatchUnlocked as 0, so Black stays
--   blocked exactly as it is today. Nothing about the current behaviour
--   depends on this file having run.
--
-- registry_enforcement_events.eventType is an ENUM. Widening it needs the
-- full five-value list in the MODIFY COLUMN; MySQL has no "add a value to an
-- ENUM" operation, so this statement is not idempotent and must run once.
-- The values added here are 'black_unlocked' and 'black_relocked'. If your
-- server already accepts them, skip the MODIFY and run only the ALTERs.

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
        'blackDispatchUnlocked',
        'blackUnlockedAt',
        'blackUnlockedBy',
        'blackUnlockReason'
    )
ORDER BY COLUMN_NAME;

SELECT COLUMN_TYPE
FROM information_schema.COLUMNS
WHERE
    TABLE_SCHEMA = DATABASE()
    AND TABLE_NAME = 'registry_enforcement_events'
    AND COLUMN_NAME = 'eventType';

-- ── official_registry: the one-inspection grant ──────────────────────────────
ALTER TABLE official_registry
ADD COLUMN blackDispatchUnlocked TINYINT(1) NOT NULL DEFAULT 0 COMMENT '1 = a SUPER_ADMIN granted exactly one inspection. Does not lift blackLocked.' AFTER blackLockReason,
ADD COLUMN blackUnlockedAt DATETIME NULL DEFAULT NULL AFTER blackDispatchUnlocked,
ADD COLUMN blackUnlockedBy INT NULL DEFAULT NULL COMMENT 'users.userID of the SUPER_ADMIN who granted it.' AFTER blackUnlockedAt,
ADD COLUMN blackUnlockReason VARCHAR(255) NULL DEFAULT NULL AFTER blackUnlockedBy;

-- Non-unique and low-cardinality, deliberately.
ALTER TABLE official_registry
ADD KEY idx_reg_black_unlocked (blackDispatchUnlocked);

-- ── registry_enforcement_events: widen the event vocabulary ─────────────────
-- 'black_unlocked' = a grant was made.
-- 'black_relocked' = the single use grant was consumed. The business was
--   Black throughout; nothing was cleared, which is why this is a distinct
--   event rather than a black_locked.
ALTER TABLE registry_enforcement_events
MODIFY COLUMN eventType ENUM(
    'warning_issued',
    'warning_cleared',
    'black_locked',
    'black_unlocked',
    'black_relocked'
) COLLATE utf8mb4_unicode_ci NOT NULL COMMENT 'black_relocked = the one-inspection grant was consumed, not a new lock.';

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
        'blackDispatchUnlocked',
        'blackUnlockedAt',
        'blackUnlockedBy',
        'blackUnlockReason'
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
    AND INDEX_NAME = 'idx_reg_black_unlocked'
GROUP BY
    INDEX_NAME,
    NON_UNIQUE;

-- The enum must now accept all five values, or every unlock insert fails.
SELECT COLUMN_TYPE
FROM information_schema.COLUMNS
WHERE
    TABLE_SCHEMA = DATABASE()
    AND TABLE_NAME = 'registry_enforcement_events'
    AND COLUMN_NAME = 'eventType';

-- Existing rows must read as "no grant" without backfill. If this returns
-- anything other than 0 and 0, something wrote to the column before the
-- migration landed, which should not be possible.
SELECT COUNT(*) AS total_rows, SUM(blackDispatchUnlocked <> 0) AS unlocked_rows
FROM official_registry;