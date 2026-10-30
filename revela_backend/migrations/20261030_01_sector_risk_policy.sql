CREATE TABLE IF NOT EXISTS sector_risk_policy (
    policy_id TINYINT UNSIGNED NOT NULL,
    version BIGINT UNSIGNED NOT NULL,
    fallback_score TINYINT UNSIGNED NOT NULL DEFAULT 50,
    categories JSON NOT NULL,
    updated_by INT NULL,
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
        ON UPDATE CURRENT_TIMESTAMP(6),
    PRIMARY KEY (policy_id),
    CONSTRAINT chk_sector_risk_policy_singleton CHECK (policy_id = 1),
    CONSTRAINT chk_sector_risk_policy_fallback CHECK (fallback_score = 50)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS sector_risk_policy_audit (
    audit_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    version BIGINT UNSIGNED NOT NULL,
    actor_user_id INT NOT NULL,
    old_values JSON NOT NULL,
    new_values JSON NOT NULL,
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    PRIMARY KEY (audit_id),
    UNIQUE KEY uq_sector_risk_policy_audit_version (version),
    KEY idx_sector_risk_policy_audit_actor_time (actor_user_id, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

INSERT INTO sector_risk_policy
    (policy_id, version, fallback_score, categories)
VALUES (
    1,
    1,
    50,
    JSON_OBJECT(
        'Manufacturing', 90,
        'Construction and utilities', 85,
        'Wholesale and vehicles', 80,
        'Retail', 80,
        'Food and drink', 75,
        'Hospitality, arts and recreation', 75,
        'Transport and storage', 70,
        'Real estate', 60,
        'Finance and professional', 50,
        'Information and communication', 50,
        'Education, health and other services', 40,
        'Agriculture and mining', 30
    )
)
ON DUPLICATE KEY UPDATE policy_id = VALUES(policy_id);
