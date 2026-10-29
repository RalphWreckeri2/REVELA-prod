ALTER TABLE registry_sector_review_queue
    MODIFY COLUMN review_status
        ENUM('ambiguous', 'unmatched', 'resolved') NOT NULL;
