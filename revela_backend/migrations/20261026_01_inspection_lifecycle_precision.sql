-- MANUAL, GUARDED MIGRATION ONLY. Run through
-- scripts/migrate_inspection_lifecycle_precision.py after a verified backup.
-- The runner checks the selected database and exact current column metadata.
-- Existing DATETIME(0) values become .000000; missing fractions CANNOT be recovered.
-- Future log_inspection_event() UTC_TIMESTAMP(6) writes retain their precision.
-- Deploy the matching application build that writes enforcement_events.createdAt
-- with UTC_TIMESTAMP(6), independent of the database session's time zone.
-- Do not reinterpret or rewrite historical enforcement events: their original
-- session time zone is not recoverable from this structure-only export.
ALTER TABLE inspection_lifecycle_events
    MODIFY COLUMN eventTimestamp DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6);
