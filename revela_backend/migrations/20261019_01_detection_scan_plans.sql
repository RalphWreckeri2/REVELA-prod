-- Own grid coordinates only: freeze the selected scope while a scan is partial.
-- Separate cycle IDs prevent Quick/Full completions from erasing one another.
CREATE TABLE IF NOT EXISTS detection_scan_plans (
    scopeKey VARCHAR(16) NOT NULL PRIMARY KEY,
    cycleID VARCHAR(16) NOT NULL,
    points LONGTEXT NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'running',
    updatedAt DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB;
