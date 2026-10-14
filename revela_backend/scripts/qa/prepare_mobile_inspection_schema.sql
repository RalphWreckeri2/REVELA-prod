-- REVELA Mobile isolated QA inspection schema
--
-- Target: revela_test_mobile_phase72 only.
-- This script creates empty tables; it contains no production records.
-- Review the complete script before execution. Do not run against any
-- database other than the explicitly provisioned local QA database.
--
-- The five core table definitions are derived from the structure-only
-- Dump20261013.sql export. Export AUTO_INCREMENT counters and dump/session
-- commands are intentionally omitted. Runtime-owned table definitions are
-- copied from the backend SQL definitions listed in the source comments.
--
-- All tables and referenced tables are explicitly schema-qualified.
-- No CREATE DATABASE/USER, DROP, data inserts, or FK-check overrides are used.

-- Source: Dump20261013.sql, table `barangays`.
CREATE TABLE `revela_test_mobile_phase72`.`barangays` (
  `barangayID` int NOT NULL AUTO_INCREMENT,
  `barangayName` varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  PRIMARY KEY (`barangayID`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Source: Dump20261013.sql, table `users`.
CREATE TABLE `revela_test_mobile_phase72`.`users` (
  `userID` int NOT NULL AUTO_INCREMENT,
  `fullName` varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  `email` varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  `phone` varchar(20) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `userRole` varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  `userPassword` varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  `createdAt` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updatedAt` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  `lastLoginAt` datetime DEFAULT NULL,
  `mustChangePassword` tinyint(1) NOT NULL DEFAULT '0',
  `is_2fa_enabled` tinyint(1) DEFAULT '0',
  `two_factor_secret` varchar(32) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `isActive` tinyint(1) DEFAULT '1',
  `resetRequested` tinyint(1) DEFAULT '0',
  `fcm_token` text COLLATE utf8mb4_unicode_ci,
  PRIMARY KEY (`userID`),
  UNIQUE KEY `email` (`email`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Source: Dump20261013.sql, table `official_registry`.
-- Depends on barangays.
CREATE TABLE `revela_test_mobile_phase72`.`official_registry` (
  `businessID` varchar(50) COLLATE utf8mb4_unicode_ci NOT NULL,
  `barangayID` int NOT NULL,
  `businessName` varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  `businessType` varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `lineOfBusiness` varchar(500) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `businessAddress` varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `latitude` decimal(10,8) DEFAULT NULL,
  `longitude` decimal(11,8) DEFAULT NULL,
  `placeID` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `placeIDKind` enum('poi','address') COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `coordSource` enum('csv','places','geocode','manual') COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `coordFetchedAt` datetime DEFAULT NULL,
  `matchScore` decimal(4,3) DEFAULT NULL,
  `matchStatus` enum('auto','review','approved','rejected') COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `applicationStatus` enum('Active','Expired','Revoked','Pending','Closed') CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT 'Pending',
  `lastRenewalDate` datetime DEFAULT NULL,
  `businessSize` varchar(50) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `registrationType` varchar(50) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `resolveKey` char(40) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  PRIMARY KEY (`businessID`),
  KEY `fk_registry_barangay` (`barangayID`),
  KEY `idx_reg_status` (`applicationStatus`),
  KEY `idx_reg_renewal` (`lastRenewalDate`),
  KEY `idx_reg_barangay_stat` (`barangayID`,`applicationStatus`),
  KEY `idx_reg_barangay_name` (`barangayID`,`businessName`(100)),
  KEY `idx_reg_coord_expiry` (`coordSource`,`coordFetchedAt`),
  KEY `idx_reg_match_status` (`matchStatus`),
  KEY `idx_reg_place` (`placeID`),
  CONSTRAINT `fk_registry_barangay`
    FOREIGN KEY (`barangayID`)
    REFERENCES `revela_test_mobile_phase72`.`barangays` (`barangayID`)
    ON DELETE RESTRICT ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Source: Dump20261013.sql, table `inspection_reports`.
-- Depends on users. The GPS columns are present in the export and also match
-- scripts/add_inspection_verified_gps.sql.
CREATE TABLE `revela_test_mobile_phase72`.`inspection_reports` (
  `reportID` int NOT NULL AUTO_INCREMENT,
  `userID` int NOT NULL,
  `targetID` int NOT NULL,
  `targetType` varchar(50) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  `deadline` datetime DEFAULT NULL,
  `inspectionResult` varchar(50) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `verificationStatus` varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `photoPath` text CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci,
  `remarks` varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `irTimestamp` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `submittedAt` datetime(6) DEFAULT NULL,
  `submissionReceivedAt` datetime(6) DEFAULT NULL,
  `resolutionTime` int DEFAULT NULL,
  `nearestLandmark` varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `verifiedLatitude` decimal(10,8) DEFAULT NULL,
  `verifiedLongitude` decimal(11,8) DEFAULT NULL,
  `verifiedAccuracy` decimal(8,2) DEFAULT NULL,
  `syncStatus` varchar(20) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT 'synced',
  `clientUpdatedAt` datetime DEFAULT NULL,
  `clientDeviceId` varchar(100) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `noticeLevel` int DEFAULT '0',
  `wasReassigned` tinyint(1) NOT NULL DEFAULT '0',
  `deadlineReminderSentAt` datetime DEFAULT NULL,
  PRIMARY KEY (`reportID`),
  KEY `fk_report_user` (`userID`),
  KEY `idx_ir_target_type` (`targetID`,`targetType`),
  KEY `idx_ir_status` (`verificationStatus`),
  KEY `idx_ir_target_report` (`targetID`,`reportID`),
  CONSTRAINT `fk_report_user`
    FOREIGN KEY (`userID`)
    REFERENCES `revela_test_mobile_phase72`.`users` (`userID`)
    ON DELETE RESTRICT ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Source: Dump20261013.sql, table `geospatial_logs`.
-- Depends on barangays, official_registry, and inspection_reports.
CREATE TABLE `revela_test_mobile_phase72`.`geospatial_logs` (
  `logID` int NOT NULL AUTO_INCREMENT,
  `barangayID` int NOT NULL,
  `businessID` varchar(50) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `reportID` int DEFAULT NULL,
  `detectedName` varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `latitude` decimal(10,8) DEFAULT NULL,
  `longitude` decimal(11,8) DEFAULT NULL,
  `detectedDate` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `nearestLandmark` varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `placeTypes` json DEFAULT NULL,
  `flagColor` varchar(50) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `placeID` varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `reportedByUserID` int DEFAULT NULL,
  `notes` text CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci,
  `noticeLevel` int DEFAULT '0',
  PRIMARY KEY (`logID`),
  KEY `fk_geo_barangay` (`barangayID`),
  KEY `fk_geo_report` (`reportID`),
  KEY `idx_geo_flagcolor` (`flagColor`),
  KEY `idx_geo_brgy_flag` (`barangayID`,`flagColor`),
  KEY `idx_geo_detecteddate` (`detectedDate`),
  KEY `idx_geo_reporter` (`reportedByUserID`),
  KEY `idx_geo_barangay_name` (`barangayID`,`detectedName`(100)),
  KEY `idx_geo_business` (`businessID`),
  KEY `idx_geo_place` (`placeID`),
  CONSTRAINT `fk_geo_barangay`
    FOREIGN KEY (`barangayID`)
    REFERENCES `revela_test_mobile_phase72`.`barangays` (`barangayID`)
    ON DELETE RESTRICT ON UPDATE CASCADE,
  CONSTRAINT `fk_geo_business`
    FOREIGN KEY (`businessID`)
    REFERENCES `revela_test_mobile_phase72`.`official_registry` (`businessID`)
    ON DELETE SET NULL ON UPDATE CASCADE,
  CONSTRAINT `fk_geo_report`
    FOREIGN KEY (`reportID`)
    REFERENCES `revela_test_mobile_phase72`.`inspection_reports` (`reportID`)
    ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Source: api/auth/sessions.py::_ensure_session_table.
-- No foreign key is declared by the backend definition.
CREATE TABLE `revela_test_mobile_phase72`.`user_active_sessions` (
  `userID` INT NOT NULL PRIMARY KEY,
  `sessionID` CHAR(32) NOT NULL,
  `clientType` VARCHAR(16) NOT NULL,
  `issuedAt` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  KEY `idx_session_id` (`sessionID`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Source: scripts/create_inspection_lifecycle_events.sql.
-- The backend definition declares indexes but no foreign keys.
CREATE TABLE `revela_test_mobile_phase72`.`inspection_lifecycle_events` (
  `eventID` int NOT NULL AUTO_INCREMENT,
  `reportID` int NOT NULL,
  `targetLogID` int NOT NULL,
  `cycleID` int DEFAULT NULL,
  `eventType` enum(
    'dispatched',
    'reassigned',
    'submitted',
    'verified',
    'cancelled'
  ) COLLATE utf8mb4_unicode_ci NOT NULL,
  `actorUserID` int DEFAULT NULL,
  `assignedToUserID` int DEFAULT NULL,
  `flagColorAtEvent` varchar(50) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `inspectionResult` varchar(50) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `remarks` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `eventTimestamp` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`eventID`),
  KEY `idx_report` (`reportID`),
  KEY `idx_target` (`targetLogID`),
  KEY `idx_cycle` (`cycleID`),
  KEY `idx_type_timestamp` (`eventType`, `eventTimestamp`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Source: api/notifications/service.py::_ensure_tables.
-- Assignment routes persist in-app notifications. The backend definition
-- creates both notification tables together and declares no foreign keys.
CREATE TABLE `revela_test_mobile_phase72`.`revela_notifications` (
  `id` INT AUTO_INCREMENT PRIMARY KEY,
  `recipientUserId` INT NOT NULL,
  `type` VARCHAR(64) NOT NULL,
  `title` VARCHAR(255) NOT NULL,
  `body` TEXT,
  `link` VARCHAR(512),
  `readAt` DATETIME NULL,
  `createdAt` DATETIME DEFAULT CURRENT_TIMESTAMP,
  INDEX `idx_recipient` (`recipientUserId`, `readAt`),
  INDEX `idx_created` (`createdAt`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE `revela_test_mobile_phase72`.`user_app_preferences` (
  `userID` INT PRIMARY KEY,
  `email_inspection_alerts` TINYINT(1) NOT NULL DEFAULT 1,
  `updatedAt` DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
