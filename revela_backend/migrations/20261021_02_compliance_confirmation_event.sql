ALTER TABLE enforcement_events
    MODIFY COLUMN eventType ENUM(
        'warning_issued',
        'warning_cleared',
        'black_locked',
        'black_unlocked',
        'black_relocked',
        'compliance_confirmed'
    ) COLLATE utf8mb4_unicode_ci NOT NULL;
