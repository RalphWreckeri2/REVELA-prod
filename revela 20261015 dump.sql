-- MySQL dump 10.13  Distrib 8.0.45, for Win64 (x86_64)
--
-- Host: altaria.proxy.rlwy.net    Database: railway
-- ------------------------------------------------------
-- Server version	9.7.2

/*!40101 SET @OLD_CHARACTER_SET_CLIENT=@@CHARACTER_SET_CLIENT */
;
/*!40101 SET @OLD_CHARACTER_SET_RESULTS=@@CHARACTER_SET_RESULTS */
;
/*!40101 SET @OLD_COLLATION_CONNECTION=@@COLLATION_CONNECTION */
;
/*!50503 SET NAMES utf8 */
;
/*!40103 SET @OLD_TIME_ZONE=@@TIME_ZONE */
;
/*!40103 SET TIME_ZONE='+00:00' */
;
/*!40014 SET @OLD_UNIQUE_CHECKS=@@UNIQUE_CHECKS, UNIQUE_CHECKS=0 */
;
/*!40014 SET @OLD_FOREIGN_KEY_CHECKS=@@FOREIGN_KEY_CHECKS, FOREIGN_KEY_CHECKS=0 */
;
/*!40101 SET @OLD_SQL_MODE=@@SQL_MODE, SQL_MODE='NO_AUTO_VALUE_ON_ZERO' */
;
/*!40111 SET @OLD_SQL_NOTES=@@SQL_NOTES, SQL_NOTES=0 */
;
SET @MYSQLDUMP_TEMP_LOG_BIN = @@SESSION.SQL_LOG_BIN;

SET @@SESSION.SQL_LOG_BIN = 0;

--
-- GTID state at the beginning of the backup
--

SET
    @@GLOBAL.GTID_PURGED = /*!80000 '+'*/ '';

--
-- Table structure for table `barangays`
--

DROP TABLE IF EXISTS `barangays`;
/*!40101 SET @saved_cs_client     = @@character_set_client */
;
/*!50503 SET character_set_client = utf8mb4 */
;
CREATE TABLE `barangays` (
    `barangayID` int NOT NULL AUTO_INCREMENT,
    `barangayName` varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
    PRIMARY KEY (`barangayID`)
) ENGINE = InnoDB AUTO_INCREMENT = 17 DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */
;

--
-- Table structure for table `detection_runs`
--

DROP TABLE IF EXISTS `detection_runs`;
/*!40101 SET @saved_cs_client     = @@character_set_client */
;
/*!50503 SET character_set_client = utf8mb4 */
;
CREATE TABLE `detection_runs` (
    `runID` int NOT NULL AUTO_INCREMENT,
    `triggeredByUserID` int DEFAULT NULL,
    `startedAt` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `completedAt` datetime DEFAULT NULL,
    `status` varchar(50) COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT 'running',
    `newFlags` int DEFAULT '0',
    `totalChecked` int DEFAULT '0',
    PRIMARY KEY (`runID`),
    KEY `fk_detection_user` (`triggeredByUserID`),
    CONSTRAINT `fk_detection_user` FOREIGN KEY (`triggeredByUserID`) REFERENCES `users` (`userID`) ON DELETE SET NULL ON UPDATE CASCADE
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */
;

--
-- Table structure for table `geospatial_logs`
--

DROP TABLE IF EXISTS `geospatial_logs`;
/*!40101 SET @saved_cs_client     = @@character_set_client */
;
/*!50503 SET character_set_client = utf8mb4 */
;
CREATE TABLE `geospatial_logs` (
    `logID` int NOT NULL AUTO_INCREMENT,
    `barangayID` int NOT NULL,
    `businessID` varchar(50) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT NULL,
    `reportID` int DEFAULT NULL,
    `detectedName` varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT NULL,
    `latitude` decimal(10, 8) DEFAULT NULL,
    `longitude` decimal(11, 8) DEFAULT NULL,
    `detectedDate` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `nearestLandmark` varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT NULL,
    `source` varchar(24) COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT 'unknown' COMMENT 'Where this pin came from: registry | registry_detected | detection | manual | unknown.',
    `placeTypes` json DEFAULT NULL,
    `flagColor` varchar(50) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT NULL,
    `placeID` varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT NULL,
    `reportedByUserID` int DEFAULT NULL,
    `notes` text CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci,
    `noticeLevel` int DEFAULT '0',
    `clientSubmissionID` char(36) CHARACTER SET ascii COLLATE ascii_bin DEFAULT NULL,
    PRIMARY KEY (`logID`),
    UNIQUE KEY `uq_geo_reporter_submission` (
        `reportedByUserID`,
        `clientSubmissionID`
    ),
    KEY `fk_geo_barangay` (`barangayID`),
    KEY `fk_geo_report` (`reportID`),
    KEY `idx_geo_flagcolor` (`flagColor`),
    KEY `idx_geo_brgy_flag` (`barangayID`, `flagColor`),
    KEY `idx_geo_detecteddate` (`detectedDate`),
    KEY `idx_geo_reporter` (`reportedByUserID`),
    KEY `idx_geo_barangay_name` (
        `barangayID`,
        `detectedName` (100)
    ),
    KEY `idx_geo_business` (`businessID`),
    KEY `idx_geo_place` (`placeID`),
    CONSTRAINT `fk_geo_barangay` FOREIGN KEY (`barangayID`) REFERENCES `barangays` (`barangayID`) ON DELETE RESTRICT ON UPDATE CASCADE,
    CONSTRAINT `fk_geo_business` FOREIGN KEY (`businessID`) REFERENCES `official_registry` (`businessID`) ON DELETE SET NULL ON UPDATE CASCADE,
    CONSTRAINT `fk_geo_report` FOREIGN KEY (`reportID`) REFERENCES `inspection_reports` (`reportID`) ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE = InnoDB AUTO_INCREMENT = 15 DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */
;

--
-- Table structure for table `inspection_lifecycle_events`
--

DROP TABLE IF EXISTS `inspection_lifecycle_events`;
/*!40101 SET @saved_cs_client     = @@character_set_client */
;
/*!50503 SET character_set_client = utf8mb4 */
;
CREATE TABLE `inspection_lifecycle_events` (
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
    ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
    `actorUserID` int DEFAULT NULL,
    `assignedToUserID` int DEFAULT NULL,
    `flagColorAtEvent` varchar(50) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT NULL,
    `inspectionResult` varchar(50) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT NULL,
    `remarks` varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT NULL,
    `eventTimestamp` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (`eventID`),
    KEY `idx_report` (`reportID`),
    KEY `idx_target` (`targetLogID`),
    KEY `idx_cycle` (`cycleID`),
    KEY `idx_type_timestamp` (`eventType`, `eventTimestamp`)
) ENGINE = InnoDB AUTO_INCREMENT = 7 DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */
;

--
-- Table structure for table `inspection_reports`
--

DROP TABLE IF EXISTS `inspection_reports`;
/*!40101 SET @saved_cs_client     = @@character_set_client */
;
/*!50503 SET character_set_client = utf8mb4 */
;
CREATE TABLE `inspection_reports` (
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
    `verifiedLatitude` decimal(10, 8) DEFAULT NULL,
    `verifiedLongitude` decimal(11, 8) DEFAULT NULL,
    `verifiedAccuracy` decimal(8, 2) DEFAULT NULL,
    `syncStatus` varchar(20) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT 'synced',
    `clientUpdatedAt` datetime DEFAULT NULL,
    `clientDeviceId` varchar(100) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT NULL,
    `noticeLevel` int DEFAULT '0',
    `wasReassigned` tinyint(1) NOT NULL DEFAULT '0',
    `deadlineReminderSentAt` datetime DEFAULT NULL,
    PRIMARY KEY (`reportID`),
    KEY `fk_report_user` (`userID`),
    KEY `idx_ir_target_type` (`targetID`, `targetType`),
    KEY `idx_ir_status` (`verificationStatus`),
    KEY `idx_ir_target_report` (`targetID`, `reportID`),
    CONSTRAINT `fk_report_user` FOREIGN KEY (`userID`) REFERENCES `users` (`userID`) ON DELETE RESTRICT ON UPDATE CASCADE
) ENGINE = InnoDB AUTO_INCREMENT = 3 DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */
;

--
-- Table structure for table `official_registry`
--

DROP TABLE IF EXISTS `official_registry`;
/*!40101 SET @saved_cs_client     = @@character_set_client */
;
/*!50503 SET character_set_client = utf8mb4 */
;
CREATE TABLE `official_registry` (
    `businessID` varchar(50) COLLATE utf8mb4_unicode_ci NOT NULL,
    `barangayID` int NOT NULL,
    `businessName` varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
    `businessType` varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT NULL,
    `lineOfBusiness` varchar(500) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT NULL,
    `businessAddress` varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT NULL,
    `latitude` decimal(10, 8) DEFAULT NULL,
    `longitude` decimal(11, 8) DEFAULT NULL,
    `placeID` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
    `placeIDKind` enum('poi', 'address') COLLATE utf8mb4_unicode_ci DEFAULT NULL,
    `coordSource` enum(
        'csv',
        'places',
        'geocode',
        'manual'
    ) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
    `coordFetchedAt` datetime DEFAULT NULL,
    `matchScore` decimal(4, 3) DEFAULT NULL,
    `matchStatus` enum(
        'auto',
        'review',
        'approved',
        'rejected'
    ) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
    `applicationStatus` enum(
        'Active',
        'Expired',
        'Revoked',
        'Pending',
        'Closed'
    ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT 'Pending',
    `warningLevel` tinyint unsigned NOT NULL DEFAULT '0' COMMENT 'Verified Orange warnings issued, 0..3. Clamped at 3.',
    `blackLocked` tinyint(1) NOT NULL DEFAULT '0' COMMENT '1 = permanent habitual-offender lock. Cleared only by a SUPER_ADMIN unlock.',
    `blackLockedAt` datetime DEFAULT NULL,
    `blackLockedBy` int DEFAULT NULL COMMENT 'users.userID of the verifying admin who applied the lock.',
    `blackLockReason` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
    `blackDispatchUnlocked` tinyint(1) NOT NULL DEFAULT '0' COMMENT '1 = a SUPER_ADMIN granted exactly one inspection. Does not lift blackLocked.',
    `blackUnlockedAt` datetime DEFAULT NULL,
    `blackUnlockedBy` int DEFAULT NULL COMMENT 'users.userID of the SUPER_ADMIN who granted it.',
    `blackUnlockReason` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
    `warningClearedAt` datetime DEFAULT NULL,
    `warningClearedBy` int DEFAULT NULL COMMENT 'users.userID of whoever cleared the Orange warning.',
    `warningClearReason` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
    `lastInspectionResult` varchar(10) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT 'Most recent verified inspection result: Green/Red/Yellow/Orange/Black/Purple.',
    `lastInspectedAt` datetime(6) DEFAULT NULL COMMENT 'When that result was verified.',
    `lastRenewalDate` datetime DEFAULT NULL,
    `businessSize` varchar(50) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT NULL,
    `registrationType` varchar(50) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
    `resolveKey` char(40) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
    PRIMARY KEY (`businessID`),
    KEY `fk_registry_barangay` (`barangayID`),
    KEY `idx_reg_status` (`applicationStatus`),
    KEY `idx_reg_renewal` (`lastRenewalDate`),
    KEY `idx_reg_barangay_stat` (
        `barangayID`,
        `applicationStatus`
    ),
    KEY `idx_reg_barangay_name` (
        `barangayID`,
        `businessName` (100)
    ),
    KEY `idx_reg_coord_expiry` (
        `coordSource`,
        `coordFetchedAt`
    ),
    KEY `idx_reg_match_status` (`matchStatus`),
    KEY `idx_reg_place` (`placeID`),
    KEY `idx_reg_black_locked` (`blackLocked`),
    KEY `idx_reg_warning_level` (`warningLevel`),
    KEY `idx_reg_black_unlocked` (`blackDispatchUnlocked`),
    CONSTRAINT `fk_registry_barangay` FOREIGN KEY (`barangayID`) REFERENCES `barangays` (`barangayID`) ON DELETE RESTRICT ON UPDATE CASCADE
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */
;

--
-- Table structure for table `places_api_usage`
--

DROP TABLE IF EXISTS `places_api_usage`;
/*!40101 SET @saved_cs_client     = @@character_set_client */
;
/*!50503 SET character_set_client = utf8mb4 */
;
CREATE TABLE `places_api_usage` (
    `usageDate` date NOT NULL,
    `kind` varchar(20) NOT NULL,
    `requestCount` int NOT NULL DEFAULT '0',
    PRIMARY KEY (`usageDate`, `kind`)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */
;

--
-- Table structure for table `registry_enforcement_events`
--

DROP TABLE IF EXISTS `registry_enforcement_events`;
/*!40101 SET @saved_cs_client     = @@character_set_client */
;
/*!50503 SET character_set_client = utf8mb4 */
;
CREATE TABLE `registry_enforcement_events` (
    `eventID` bigint NOT NULL AUTO_INCREMENT,
    `businessID` varchar(50) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
    `eventType` enum(
        'warning_issued',
        'warning_cleared',
        'black_locked',
        'black_unlocked',
        'black_relocked'
    ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
    `actorUserID` int DEFAULT NULL COMMENT 'users.userID of the actor. NULL only for system actions.',
    `reason` varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT NULL,
    `previousLevel` tinyint unsigned DEFAULT NULL,
    `newLevel` tinyint unsigned DEFAULT NULL,
    `previousBlack` tinyint(1) DEFAULT NULL,
    `newBlack` tinyint(1) DEFAULT NULL,
    `createdAt` datetime(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    PRIMARY KEY (`eventID`),
    KEY `idx_ree_business` (`businessID`, `eventID`),
    KEY `idx_ree_type_time` (`eventType`, `createdAt`)
) ENGINE = InnoDB AUTO_INCREMENT = 4 DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */
;

--
-- Table structure for table `registry_pin_history`
--

DROP TABLE IF EXISTS `registry_pin_history`;
/*!40101 SET @saved_cs_client     = @@character_set_client */
;
/*!50503 SET character_set_client = utf8mb4 */
;
CREATE TABLE `registry_pin_history` (
    `id` bigint NOT NULL AUTO_INCREMENT,
    `businessID` varchar(50) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
    `attemptedAt` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `outcome` varchar(20) COLLATE utf8mb4_unicode_ci NOT NULL,
    `reason` varchar(30) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
    `stackSize` int DEFAULT NULL,
    `oldLat` decimal(10, 8) DEFAULT NULL,
    `oldLng` decimal(11, 8) DEFAULT NULL,
    `newLat` decimal(10, 8) DEFAULT NULL,
    `newLng` decimal(11, 8) DEFAULT NULL,
    `placeID` varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT NULL,
    `score` decimal(4, 3) DEFAULT NULL,
    `failReason` varchar(30) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
    `bestName` varchar(120) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
    `bestScore` decimal(4, 3) DEFAULT NULL,
    `reviewType` varchar(24) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
    `reviewKey` char(40) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
    `candidateSource` varchar(20) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
    `oldCoordSource` varchar(24) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
    `newCoordSource` varchar(24) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
    `oldPlaceID` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
    `oldPlaceIDKind` varchar(32) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
    `oldMatchScore` decimal(4, 3) DEFAULT NULL,
    `oldMatchStatus` varchar(24) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
    `oldAddress` text COLLATE utf8mb4_unicode_ci,
    `newAddress` text COLLATE utf8mb4_unicode_ci,
    `oldBarangayID` int DEFAULT NULL,
    `newBarangayID` int DEFAULT NULL,
    `actorUserID` bigint DEFAULT NULL,
    `decisionAt` datetime DEFAULT NULL,
    PRIMARY KEY (`id`),
    KEY `idx_pinhist_business` (`businessID`, `attemptedAt`)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */
;

--
-- Table structure for table `registry_rejected_places`
--

DROP TABLE IF EXISTS `registry_rejected_places`;
/*!40101 SET @saved_cs_client     = @@character_set_client */
;
/*!50503 SET character_set_client = utf8mb4 */
;
CREATE TABLE `registry_rejected_places` (
    `businessID` varchar(50) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
    `placeID` varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
    `rejectedAt` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (`businessID`, `placeID`),
    CONSTRAINT `fk_rej_business` FOREIGN KEY (`businessID`) REFERENCES `official_registry` (`businessID`) ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */
;

--
-- Table structure for table `revela_app_settings`
--

DROP TABLE IF EXISTS `revela_app_settings`;
/*!40101 SET @saved_cs_client     = @@character_set_client */
;
/*!50503 SET character_set_client = utf8mb4 */
;
CREATE TABLE `revela_app_settings` (
    `settingKey` varchar(96) COLLATE utf8mb4_unicode_ci NOT NULL,
    `settingValue` text COLLATE utf8mb4_unicode_ci NOT NULL,
    `updatedBy` int DEFAULT NULL,
    `updatedAt` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (`settingKey`),
    KEY `idx_settings_updated` (`updatedAt`)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */
;

--
-- Table structure for table `revela_notifications`
--

DROP TABLE IF EXISTS `revela_notifications`;
/*!40101 SET @saved_cs_client     = @@character_set_client */
;
/*!50503 SET character_set_client = utf8mb4 */
;
CREATE TABLE `revela_notifications` (
    `id` int NOT NULL AUTO_INCREMENT,
    `recipientUserId` int NOT NULL,
    `type` varchar(64) NOT NULL,
    `title` varchar(255) NOT NULL,
    `body` text,
    `link` varchar(512) DEFAULT NULL,
    `readAt` datetime DEFAULT NULL,
    `createdAt` datetime DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (`id`),
    KEY `idx_recipient` (`recipientUserId`, `readAt`),
    KEY `idx_created` (`createdAt`),
    KEY `idx_notif_recipient_type` (
        `recipientUserId`,
        `type`,
        `readAt`
    )
) ENGINE = InnoDB AUTO_INCREMENT = 7 DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */
;

--
-- Table structure for table `revela_places_fixtures`
--

DROP TABLE IF EXISTS `revela_places_fixtures`;
/*!40101 SET @saved_cs_client     = @@character_set_client */
;
/*!50503 SET character_set_client = utf8mb4 */
;
CREATE TABLE `revela_places_fixtures` (
    `fixtureKey` varchar(191) COLLATE utf8mb4_unicode_ci NOT NULL,
    `fixtureKind` varchar(32) COLLATE utf8mb4_unicode_ci NOT NULL,
    `payload` longtext COLLATE utf8mb4_unicode_ci NOT NULL,
    `createdAt` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `lastUsedAt` datetime DEFAULT NULL,
    `hitCount` int NOT NULL DEFAULT '0',
    PRIMARY KEY (`fixtureKey`),
    KEY `idx_fixtures_created` (`createdAt`),
    KEY `idx_fixtures_kind` (`fixtureKind`)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */
;

--
-- Table structure for table `scan_point_log`
--

DROP TABLE IF EXISTS `scan_point_log`;
/*!40101 SET @saved_cs_client     = @@character_set_client */
;
/*!50503 SET character_set_client = utf8mb4 */
;
CREATE TABLE `scan_point_log` (
    `pointKey` varchar(64) NOT NULL,
    `completedAt` datetime NOT NULL,
    PRIMARY KEY (`pointKey`)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */
;

--
-- Table structure for table `user_active_sessions`
--

DROP TABLE IF EXISTS `user_active_sessions`;
/*!40101 SET @saved_cs_client     = @@character_set_client */
;
/*!50503 SET character_set_client = utf8mb4 */
;
CREATE TABLE `user_active_sessions` (
    `userID` int NOT NULL,
    `sessionID` char(32) NOT NULL,
    `clientType` varchar(16) NOT NULL,
    `issuedAt` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (`userID`),
    KEY `idx_session_id` (`sessionID`)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */
;

--
-- Table structure for table `user_app_preferences`
--

DROP TABLE IF EXISTS `user_app_preferences`;
/*!40101 SET @saved_cs_client     = @@character_set_client */
;
/*!50503 SET character_set_client = utf8mb4 */
;
CREATE TABLE `user_app_preferences` (
    `userID` int NOT NULL,
    `email_inspection_alerts` tinyint(1) NOT NULL DEFAULT '1',
    `updatedAt` datetime DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (`userID`)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */
;

--
-- Table structure for table `user_password_resets`
--

DROP TABLE IF EXISTS `user_password_resets`;
/*!40101 SET @saved_cs_client     = @@character_set_client */
;
/*!50503 SET character_set_client = utf8mb4 */
;
CREATE TABLE `user_password_resets` (
    `uprID` int NOT NULL AUTO_INCREMENT,
    `userID` int NOT NULL,
    `pwToken` char(5) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
    `createdAt` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `expiresAt` datetime NOT NULL,
    `isUsed` tinyint(1) NOT NULL DEFAULT '0',
    PRIMARY KEY (`uprID`),
    KEY `fk_upr_user` (`userID`),
    CONSTRAINT `fk_upr_user` FOREIGN KEY (`userID`) REFERENCES `users` (`userID`) ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE = InnoDB AUTO_INCREMENT = 22 DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */
;

--
-- Table structure for table `users`
--

DROP TABLE IF EXISTS `users`;
/*!40101 SET @saved_cs_client     = @@character_set_client */
;
/*!50503 SET character_set_client = utf8mb4 */
;
CREATE TABLE `users` (
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
) ENGINE = InnoDB AUTO_INCREMENT = 26 DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */
;

--
-- Table structure for table `wlc_config`
--

DROP TABLE IF EXISTS `wlc_config`;
/*!40101 SET @saved_cs_client     = @@character_set_client */
;
/*!50503 SET character_set_client = utf8mb4 */
;
CREATE TABLE `wlc_config` (
    `id` int NOT NULL DEFAULT '1',
    `w1_risk` decimal(5, 2) DEFAULT '40.00',
    `w2_sector` decimal(5, 2) DEFAULT '40.00',
    `w3_distance` decimal(5, 2) DEFAULT '20.00',
    `bplo_lat` decimal(10, 8) DEFAULT '13.96670000',
    `bplo_lng` decimal(11, 8) DEFAULT '121.11670000',
    `sector_scores` json DEFAULT NULL,
    `updated_at` timestamp NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (`id`)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */
;
SET @@SESSION.SQL_LOG_BIN = @MYSQLDUMP_TEMP_LOG_BIN;
/*!40103 SET TIME_ZONE=@OLD_TIME_ZONE */
;

/*!40101 SET SQL_MODE=@OLD_SQL_MODE */
;
/*!40014 SET FOREIGN_KEY_CHECKS=@OLD_FOREIGN_KEY_CHECKS */
;
/*!40014 SET UNIQUE_CHECKS=@OLD_UNIQUE_CHECKS */
;
/*!40101 SET CHARACTER_SET_CLIENT=@OLD_CHARACTER_SET_CLIENT */
;
/*!40101 SET CHARACTER_SET_RESULTS=@OLD_CHARACTER_SET_RESULTS */
;
/*!40101 SET COLLATION_CONNECTION=@OLD_COLLATION_CONNECTION */
;
/*!40111 SET SQL_NOTES=@OLD_SQL_NOTES */
;

-- Dump completed on 2026-10-15 19:46:55