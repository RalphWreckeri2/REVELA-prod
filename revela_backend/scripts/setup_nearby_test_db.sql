-- Empty MySQL 8.0 schema for the Nearby Search (New) local tests.
--
-- SAFETY:
--   * Connect only to the separately verified loopback-only local MySQL server.
--   * This script targets only `revela_test_nearby_phase2`.
--   * Review @@hostname, @@port, and listener binding before execution.
--   * Do not run against Railway or any production/shared server.
--   * The database must already exist. This script does not create it.
--   * No DROP, TRUNCATE, INSERT, or production data is used.

SELECT
    'revela_test_nearby_phase2' AS target_database,
    CURRENT_USER() AS authenticated_account,
    @@hostname AS server_hostname,
    @@port AS server_port,
    VERSION() AS mysql_version;

-- Minimal referenced identity table required by detection_runs' user FK.
CREATE TABLE IF NOT EXISTS `revela_test_nearby_phase2`.`users` (
    `userID` INT NOT NULL AUTO_INCREMENT,
    `fullName` VARCHAR(255) DEFAULT NULL,
    PRIMARY KEY (`userID`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `revela_test_nearby_phase2`.`barangays` (
    `barangayID` INT NOT NULL,
    `barangayName` VARCHAR(128) NOT NULL,
    PRIMARY KEY (`barangayID`),
    UNIQUE KEY `uq_local_barangay_name` (`barangayName`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `revela_test_nearby_phase2`.`official_registry` (
    `businessID` VARCHAR(50) NOT NULL,
    `barangayID` INT DEFAULT NULL,
    `businessName` VARCHAR(255) NOT NULL,
    `applicationStatus` VARCHAR(32) DEFAULT NULL,
    `businessType` VARCHAR(128) DEFAULT NULL,
    `lineOfBusiness` VARCHAR(255) DEFAULT NULL,
    `businessAddress` TEXT,
    `placeID` VARCHAR(255) DEFAULT NULL,
    `placeIDKind` VARCHAR(32) DEFAULT NULL,
    `coordSource` VARCHAR(32) DEFAULT NULL,
    `coordFetchedAt` DATETIME DEFAULT NULL,
    `matchScore` DECIMAL(4,3) DEFAULT NULL,
    `matchStatus` VARCHAR(24) DEFAULT NULL,
    `latitude` DECIMAL(10,8) DEFAULT NULL,
    `longitude` DECIMAL(11,8) DEFAULT NULL,
    PRIMARY KEY (`businessID`),
    KEY `idx_local_registry_place` (`placeID`),
    KEY `idx_local_registry_barangay` (`barangayID`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `revela_test_nearby_phase2`.`geospatial_logs` (
    `logID` BIGINT NOT NULL AUTO_INCREMENT,
    `barangayID` INT DEFAULT NULL,
    `businessID` VARCHAR(50) DEFAULT NULL,
    `reportID` INT DEFAULT NULL,
    `detectedName` VARCHAR(255) DEFAULT NULL,
    `latitude` DECIMAL(10,8) DEFAULT NULL,
    `longitude` DECIMAL(11,8) DEFAULT NULL,
    `flagColor` VARCHAR(24) DEFAULT NULL,
    `placeID` VARCHAR(255) DEFAULT NULL,
    `nearestLandmark` TEXT,
    `placeTypes` JSON DEFAULT NULL,
    PRIMARY KEY (`logID`),
    KEY `idx_local_geo_place` (`placeID`),
    KEY `idx_local_geo_business` (`businessID`),
    KEY `idx_local_geo_color_coords` (`flagColor`, `latitude`, `longitude`),
    KEY `idx_local_geo_detected_barangay` (`detectedName`, `barangayID`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `revela_test_nearby_phase2`.`registry_rejected_places` (
    `businessID` VARCHAR(50) NOT NULL,
    `placeID` VARCHAR(255) NOT NULL,
    PRIMARY KEY (`businessID`, `placeID`),
    KEY `idx_local_rejected_place` (`placeID`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `revela_test_nearby_phase2`.`inspection_reports` (
    `reportID` BIGINT NOT NULL AUTO_INCREMENT,
    `targetType` VARCHAR(32) DEFAULT NULL,
    `targetID` BIGINT DEFAULT NULL,
    `verificationStatus` VARCHAR(32) DEFAULT NULL,
    `inspectionResult` VARCHAR(32) DEFAULT NULL,
    PRIMARY KEY (`reportID`),
    KEY `idx_local_inspection_target` (`targetType`, `targetID`),
    KEY `idx_local_inspection_verification` (
        `targetType`, `targetID`, `verificationStatus`, `inspectionResult`
    )
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Persistent scan bookkeeping schemas, matching the runtime DDL's columns.
-- `detection_runs.triggeredByUserID` is the explicit FK present in the
-- application-owned run-table DDL. Registry/log/barangay/place associations
-- are logical rather than enforced FKs in this minimal fixture schema.
CREATE TABLE IF NOT EXISTS `revela_test_nearby_phase2`.`detection_runs` (
    `runID` INT NOT NULL AUTO_INCREMENT,
    `triggeredByUserID` INT DEFAULT NULL,
    `startedAt` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `completedAt` DATETIME DEFAULT NULL,
    `status` VARCHAR(50) NOT NULL DEFAULT 'running',
    `newFlags` INT DEFAULT 0,
    `totalChecked` INT DEFAULT 0,
    PRIMARY KEY (`runID`),
    KEY `idx_local_detection_started_status` (`startedAt`, `status`),
    KEY `idx_local_detection_user` (`triggeredByUserID`),
    CONSTRAINT `fk_detection_user`
        FOREIGN KEY (`triggeredByUserID`)
        REFERENCES `revela_test_nearby_phase2`.`users` (`userID`)
        ON DELETE SET NULL ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `revela_test_nearby_phase2`.`scan_point_log` (
    `pointKey` VARCHAR(64) NOT NULL,
    `completedAt` DATETIME NOT NULL,
    PRIMARY KEY (`pointKey`),
    KEY `idx_local_scan_completed` (`completedAt`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `revela_test_nearby_phase2`.`places_api_usage` (
    `usageDate` DATE NOT NULL,
    `kind` VARCHAR(20) NOT NULL,
    `requestCount` INT NOT NULL DEFAULT 0,
    PRIMARY KEY (`usageDate`, `kind`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `revela_test_nearby_phase2`.`registry_workflow_events` (
    `eventID` BIGINT NOT NULL AUTO_INCREMENT,
    `businessID` VARCHAR(50) NOT NULL,
    `eventType` VARCHAR(24) NOT NULL,
    `resultStatus` VARCHAR(24) DEFAULT NULL,
    `placeID` VARCHAR(255) DEFAULT NULL,
    `latitude` DECIMAL(10,8) DEFAULT NULL,
    `longitude` DECIMAL(11,8) DEFAULT NULL,
    `matchScore` DECIMAL(4,3) DEFAULT NULL,
    `eventAt` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (`eventID`),
    KEY `idx_local_registry_workflow_type_time` (`eventType`, `eventAt`),
    KEY `idx_local_registry_workflow_business` (`businessID`, `eventID`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- All tables are intentionally empty. The integration harness inserts and
-- removes its own synthetic fixtures.
