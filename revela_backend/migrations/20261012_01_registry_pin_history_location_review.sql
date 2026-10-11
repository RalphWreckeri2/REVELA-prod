-- REVELA migration 20261012_01: read-only diagnostics only.
-- Do not execute this file as a schema migration. MySQL 9.7 has no
-- ALTER TABLE ADD COLUMN IF NOT EXISTS syntax.
-- The guarded migration is scripts/migrate_registry_pin_history.py; it checks
-- database, table engine, all 30 definitions, and applies only missing columns
-- after explicit --apply. A failed preflight never reaches its ALTER statement.

-- Preflight: confirm the database, table, server version, and current column state.
SELECT DATABASE() AS selected_database, VERSION() AS mysql_version;

SELECT TABLE_NAME
FROM information_schema.TABLES
WHERE
    TABLE_SCHEMA = DATABASE()
    AND TABLE_NAME = 'registry_pin_history';

SELECT
    expected.column_name,
    CASE
        WHEN actual.COLUMN_NAME IS NULL THEN 'MISSING'
        ELSE 'PRESENT'
    END AS state
FROM (
        SELECT 'reviewType' AS column_name
        UNION ALL
        SELECT 'reviewKey'
        UNION ALL
        SELECT 'candidateSource'
        UNION ALL
        SELECT 'oldCoordSource'
        UNION ALL
        SELECT 'newCoordSource'
        UNION ALL
        SELECT 'oldPlaceID'
        UNION ALL
        SELECT 'oldPlaceIDKind'
        UNION ALL
        SELECT 'oldMatchScore'
        UNION ALL
        SELECT 'oldMatchStatus'
        UNION ALL
        SELECT 'oldAddress'
        UNION ALL
        SELECT 'newAddress'
        UNION ALL
        SELECT 'oldBarangayID'
        UNION ALL
        SELECT 'newBarangayID'
        UNION ALL
        SELECT 'actorUserID'
        UNION ALL
        SELECT 'decisionAt'
    ) AS expected
    LEFT JOIN information_schema.COLUMNS AS actual ON actual.TABLE_SCHEMA = DATABASE()
    AND actual.TABLE_NAME = 'registry_pin_history'
    AND actual.COLUMN_NAME = expected.column_name
ORDER BY expected.column_name;

-- Read-only postflight view. The runner performs blocking type/nullability
-- validation after DDL; this query is for human inspection only.
SELECT
    expected.column_name,
    CASE
        WHEN actual.COLUMN_NAME IS NULL THEN 'MISSING'
        ELSE 'PRESENT'
    END AS state
FROM (
        SELECT 'reviewType' AS column_name
        UNION ALL
        SELECT 'reviewKey'
        UNION ALL
        SELECT 'candidateSource'
        UNION ALL
        SELECT 'oldCoordSource'
        UNION ALL
        SELECT 'newCoordSource'
        UNION ALL
        SELECT 'oldPlaceID'
        UNION ALL
        SELECT 'oldPlaceIDKind'
        UNION ALL
        SELECT 'oldMatchScore'
        UNION ALL
        SELECT 'oldMatchStatus'
        UNION ALL
        SELECT 'oldAddress'
        UNION ALL
        SELECT 'newAddress'
        UNION ALL
        SELECT 'oldBarangayID'
        UNION ALL
        SELECT 'newBarangayID'
        UNION ALL
        SELECT 'actorUserID'
        UNION ALL
        SELECT 'decisionAt'
    ) AS expected
    LEFT JOIN information_schema.COLUMNS AS actual ON actual.TABLE_SCHEMA = DATABASE()
    AND actual.TABLE_NAME = 'registry_pin_history'
    AND actual.COLUMN_NAME = expected.column_name
ORDER BY expected.column_name;

-- Rollback limitation: dropping these columns later requires a separate ALTER
-- TABLE and permanently deletes any location-review audit values written after
-- deployment. Do not roll back by dropping them once the application is live.