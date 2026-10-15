-- REVELA migration 20261017_01: remember where each map pin came from.
--
-- Run ONCE, before any code reads or writes this column.
--
-- MySQL has no ADD COLUMN IF NOT EXISTS (that is MariaDB), so the pre-check
-- below is for a human to read, not a guard: re-running this file fails with
-- ERROR 1060 Duplicate column name. A single-column ADD COLUMN is one atomic
-- rebuild, so if the column already exists the whole statement is rejected.
-- Do not re-run.
--
-- Additive only. One NOT NULL column with a constant default, so it is safe
-- to apply while the application is running and safe for concurrent readers.
--
-- What this fixes:
--   The Map used to answer "where did this pin come from?" by guessing from
--   which columns happened to be set: a businessID meant "registry", a placeID
--   meant "also on Google". That guess is wrong for every pin created before
--   today, because a pin can be created by a scan and later linked to the
--   registry by reconcile - after which it looks like it was always a
--   registry pin. The column stores the answer at insert time instead.
--
-- Allowed values, and where each one is written:
--   registry           insert_green_flag (import/sync seed),
--                      _sync_flag_color seed, snap_unresolved_pins
--   registry_detected  _match_registry_to_google: an official_registry
--                      business that Google Places also returned
--   detection          _insert_red_flag: found by a scan, no registry link
--   manual             insert_yellow_flag, both the idempotent and the plain
--                      branch: an inspector reporting from the field
--   unknown            anything we cannot tell. The default, on purpose.
--
-- 'unknown' rather than a guess: a wrong label is worse than an absent one,
-- because a wrong label is believed.
--
-- The value is a VARCHAR, not an ENUM, deliberately. Adding a value to a
-- MySQL ENUM means a MODIFY COLUMN that rewrites the table and cannot be
-- re-run safely - the exact failure mode this file's own header warns about.
-- The allowed set is documented above and in api/models/geospatial.py
-- (SOURCE_VALUES), and with_source() rejects anything else before it reaches
-- the database.
--
-- Where the code stays safe if this has not been applied:
--   Every insert checks the column first and omits it when it is missing,
--   because MySQL raises "Unknown column" at execution time for a column that
--   is not there - naming it would break the insert, not just skip a label.
--   The Map and Registry readers fall back to the old inferred label. Until
--   this migration runs, existing pins read 'unknown' rather than being
--   backfilled from their columns; see scripts/backfill_geospatial_source.py,
--   which is a dry run until you pass --apply.

SELECT DATABASE() AS selected_database, VERSION() AS mysql_version;

-- ── Pre-check: what already exists ───────────────────────────────────────────
SELECT COLUMN_NAME, COLUMN_TYPE, IS_NULLABLE, COLUMN_DEFAULT
FROM information_schema.COLUMNS
WHERE TABLE_SCHEMA = DATABASE()
  AND TABLE_NAME = 'geospatial_logs'
  AND COLUMN_NAME = 'source';

-- ── The column ───────────────────────────────────────────────────────────────
ALTER TABLE geospatial_logs
    ADD COLUMN source VARCHAR(16) NOT NULL DEFAULT 'unknown'
        COMMENT 'Where this pin came from: registry | registry_detected | detection | manual | unknown.'
        AFTER nearestLandmark;

-- ── Post-check: confirm what is now present ─────────────────────────────────
SELECT COLUMN_NAME, COLUMN_TYPE, IS_NULLABLE, COLUMN_DEFAULT
FROM information_schema.COLUMNS
WHERE TABLE_SCHEMA = DATABASE()
  AND TABLE_NAME = 'geospatial_logs'
  AND COLUMN_NAME = 'source';

-- Every existing row must read 'unknown'. They are NOT backfilled from their
-- columns here: a pin's businessID may have been attached by reconcile long
-- after the pin was created by a scan, so inferring the source would invent
-- history. scripts/backfill_geospatial_source.py lists what it would change
-- and writes nothing until you pass --apply.
SELECT source, COUNT(*) AS pins
FROM geospatial_logs
GROUP BY source;

-- Anything outside the documented set would mean a writer bypassed
-- with_source(). This should return no rows.
SELECT source, COUNT(*) AS pins
FROM geospatial_logs
WHERE source NOT IN (
    'registry', 'registry_detected', 'detection', 'manual', 'unknown'
)
GROUP BY source;
