CREATE TABLE IF NOT EXISTS psic_lines (
    psic_line_id BIGINT NOT NULL AUTO_INCREMENT,
    source_version VARCHAR(80) NOT NULL,
    source_row_number INT NOT NULL,
    major_type_raw VARCHAR(255) NOT NULL,
    major_type_clean VARCHAR(255) NOT NULL,
    normalized_major_type VARCHAR(255) NOT NULL,
    division VARCHAR(255) NULL,
    `group` VARCHAR(255) NULL,
    `class` VARCHAR(255) NULL,
    line_of_business VARCHAR(500) NOT NULL,
    normalized_line_of_business VARCHAR(500) NOT NULL,
    source_total INT NOT NULL DEFAULT 0,
    PRIMARY KEY (psic_line_id),
    UNIQUE KEY uq_psic_source_row (source_version, source_row_number),
    KEY idx_psic_line_normalized (source_version, normalized_line_of_business),
    KEY idx_psic_major_normalized (source_version, normalized_major_type)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS psic_active_version (
    singleton_id TINYINT NOT NULL,
    source_version VARCHAR(80) NOT NULL,
    activated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (singleton_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS display_sector (
    normalized_major_type VARCHAR(255) NOT NULL,
    source_version VARCHAR(80) NOT NULL,
    major_type_raw VARCHAR(255) NOT NULL,
    major_type_clean VARCHAR(255) NOT NULL,
    display_sector_key VARCHAR(64) NULL,
    display_sector_label VARCHAR(100) NULL,
    sort_order SMALLINT NOT NULL DEFAULT 0,
    is_active TINYINT(1) NOT NULL DEFAULT 1,
    PRIMARY KEY (normalized_major_type),
    KEY idx_display_sector_key (display_sector_key, is_active)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Registry joins explicitly collate the normalized lineOfBusiness expression
-- to utf8mb4_unicode_ci so it matches this table even when the source column
-- uses a different MySQL 8 collation.
CREATE TABLE IF NOT EXISTS registry_sector_map (
    normalized_line_of_business VARCHAR(500) NOT NULL,
    raw_line_of_business VARCHAR(500) NOT NULL,
    source_version VARCHAR(80) NOT NULL,
    match_status ENUM('matched', 'combo', 'ambiguous', 'unmatched') NOT NULL,
    primary_psic_line_id BIGINT NULL,
    display_sector_key VARCHAR(64) NULL,
    display_sector_label VARCHAR(100) NULL,
    candidate_count SMALLINT UNSIGNED NOT NULL DEFAULT 0,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (normalized_line_of_business),
    KEY idx_registry_sector_display (display_sector_key, match_status),
    KEY idx_registry_sector_version (source_version),
    CONSTRAINT fk_registry_sector_primary_line
        FOREIGN KEY (primary_psic_line_id) REFERENCES psic_lines (psic_line_id)
        ON DELETE RESTRICT ON UPDATE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS registry_sector_map_secondary (
    normalized_line_of_business VARCHAR(500) NOT NULL,
    psic_line_id BIGINT NOT NULL,
    PRIMARY KEY (normalized_line_of_business, psic_line_id),
    CONSTRAINT fk_registry_sector_secondary_map
        FOREIGN KEY (normalized_line_of_business)
        REFERENCES registry_sector_map (normalized_line_of_business)
        ON DELETE CASCADE ON UPDATE RESTRICT,
    CONSTRAINT fk_registry_sector_secondary_line
        FOREIGN KEY (psic_line_id) REFERENCES psic_lines (psic_line_id)
        ON DELETE RESTRICT ON UPDATE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS registry_sector_review_queue (
    normalized_line_of_business VARCHAR(500) NOT NULL,
    raw_line_of_business VARCHAR(500) NOT NULL,
    review_status ENUM('ambiguous', 'unmatched') NOT NULL,
    candidate_count SMALLINT UNSIGNED NOT NULL DEFAULT 0,
    first_seen_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_seen_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    reviewed_at DATETIME NULL,
    reviewed_by VARCHAR(255) NULL,
    PRIMARY KEY (normalized_line_of_business),
    KEY idx_sector_review_status (review_status, last_seen_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
