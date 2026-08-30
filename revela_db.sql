-- MySQL dump 10.13  Distrib 8.0.45, for Win64 (x86_64)
--
-- Host: 127.0.0.1    Database: revela_db
-- ------------------------------------------------------
-- Server version	8.4.8

/*!40101 SET @OLD_CHARACTER_SET_CLIENT=@@CHARACTER_SET_CLIENT */;
/*!40101 SET @OLD_CHARACTER_SET_RESULTS=@@CHARACTER_SET_RESULTS */;
/*!40101 SET @OLD_COLLATION_CONNECTION=@@COLLATION_CONNECTION */;
/*!50503 SET NAMES utf8 */;
/*!40103 SET @OLD_TIME_ZONE=@@TIME_ZONE */;
/*!40103 SET TIME_ZONE='+00:00' */;
/*!40014 SET @OLD_UNIQUE_CHECKS=@@UNIQUE_CHECKS, UNIQUE_CHECKS=0 */;
/*!40014 SET @OLD_FOREIGN_KEY_CHECKS=@@FOREIGN_KEY_CHECKS, FOREIGN_KEY_CHECKS=0 */;
/*!40101 SET @OLD_SQL_MODE=@@SQL_MODE, SQL_MODE='NO_AUTO_VALUE_ON_ZERO' */;
/*!40111 SET @OLD_SQL_NOTES=@@SQL_NOTES, SQL_NOTES=0 */;

--
-- Table structure for table `barangays`
--

DROP TABLE IF EXISTS `barangays`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `barangays` (
  `barangayID` int NOT NULL AUTO_INCREMENT,
  `barangayName` varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL,
  PRIMARY KEY (`barangayID`)
) ENGINE=InnoDB AUTO_INCREMENT=17 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `barangays`
--

LOCK TABLES `barangays` WRITE;
/*!40000 ALTER TABLE `barangays` DISABLE KEYS */;
INSERT INTO `barangays` VALUES (1,'Barangay I'),(2,'Barangay II'),(3,'Barangay II-A'),(4,'Barangay III'),(5,'Barangay IV'),(6,'Barangay Bayorbor'),(7,'Barangay Bubuyan'),(8,'Barangay Calingatan'),(9,'Barangay Loob'),(10,'Barangay Lumanglipa'),(11,'Barangay Kinalaglagan'),(12,'Barangay Manggahan'),(13,'Barangay Nangkaan'),(14,'Barangay San Sebastian'),(15,'Barangay Santol'),(16,'Barangay Upa');
/*!40000 ALTER TABLE `barangays` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `detection_runs`
--

DROP TABLE IF EXISTS `detection_runs`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
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
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `geospatial_logs`
--

DROP TABLE IF EXISTS `geospatial_logs`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `geospatial_logs` (
  `logID` int NOT NULL AUTO_INCREMENT,
  `barangayID` int NOT NULL,
  `reportID` int DEFAULT NULL,
  `detectedName` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `latitude` decimal(10,8) DEFAULT NULL,
  `longitude` decimal(11,8) DEFAULT NULL,
  `detectedDate` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `nearestLandmark` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `flagColor` varchar(50) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `placeID` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `reportedByUserID` int DEFAULT NULL,
  `notes` text COLLATE utf8mb4_unicode_ci,
  `noticeLevel` int DEFAULT '0',
  PRIMARY KEY (`logID`),
  KEY `fk_geo_barangay` (`barangayID`),
  KEY `fk_geo_report` (`reportID`),
  CONSTRAINT `fk_geo_barangay` FOREIGN KEY (`barangayID`) REFERENCES `barangays` (`barangayID`) ON DELETE RESTRICT ON UPDATE CASCADE,
  CONSTRAINT `fk_geo_report` FOREIGN KEY (`reportID`) REFERENCES `inspection_reports` (`reportID`) ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB AUTO_INCREMENT=2307 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `geospatial_logs`
--

LOCK TABLES `geospatial_logs` WRITE;
/*!40000 ALTER TABLE `geospatial_logs` DISABLE KEYS */;
/*!40000 ALTER TABLE `geospatial_logs` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `inspection_reports`
--

DROP TABLE IF EXISTS `inspection_reports`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `inspection_reports` (
  `reportID` int NOT NULL AUTO_INCREMENT,
  `userID` int NOT NULL,
  `targetID` int NOT NULL,
  `targetType` varchar(50) COLLATE utf8mb4_unicode_ci NOT NULL,
  `deadline` datetime DEFAULT NULL,
  `inspectionResult` varchar(50) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `verificationStatus` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `photoPath` text COLLATE utf8mb4_unicode_ci,
  `remarks` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `irTimestamp` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `resolutionTime` int DEFAULT NULL,
  `nearestLandmark` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `syncStatus` varchar(20) COLLATE utf8mb4_unicode_ci DEFAULT 'synced',
  `clientUpdatedAt` datetime DEFAULT NULL,
  `clientDeviceId` varchar(100) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `noticeLevel` int DEFAULT '0',
  `wasReassigned` tinyint(1) NOT NULL DEFAULT '0',
  PRIMARY KEY (`reportID`),
  KEY `fk_report_user` (`userID`),
  CONSTRAINT `fk_report_user` FOREIGN KEY (`userID`) REFERENCES `users` (`userID`) ON DELETE RESTRICT ON UPDATE CASCADE
) ENGINE=InnoDB AUTO_INCREMENT=6 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `inspection_reports`
--

LOCK TABLES `inspection_reports` WRITE;
/*!40000 ALTER TABLE `inspection_reports` DISABLE KEYS */;
/*!40000 ALTER TABLE `inspection_reports` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `local_inspections`
--

--
-- Dumping data for table `local_inspections`
--

LOCK TABLES `local_inspections` WRITE;
/*!40000 ALTER TABLE `local_inspections` DISABLE KEYS */;
/*!40000 ALTER TABLE `local_inspections` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `official_registry`
--

DROP TABLE IF EXISTS `official_registry`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `official_registry` (
  `businessID` int NOT NULL AUTO_INCREMENT,
  `barangayID` int NOT NULL,
  `businessName` varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL,
  `businessType` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `lineOfBusiness` varchar(500) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `businessAddress` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `latitude` decimal(10,8) DEFAULT NULL,
  `longitude` decimal(11,8) DEFAULT NULL,
  `applicationStatus` enum('Active','Expired','Revoked','Pending','Closed') COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT 'Pending',
  `lastRenewalDate` datetime DEFAULT NULL,
  `businessSize` varchar(50) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  PRIMARY KEY (`businessID`),
  KEY `fk_registry_barangay` (`barangayID`),
  CONSTRAINT `fk_registry_barangay` FOREIGN KEY (`barangayID`) REFERENCES `barangays` (`barangayID`) ON DELETE RESTRICT ON UPDATE CASCADE
) ENGINE=InnoDB AUTO_INCREMENT=1582 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `official_registry`
--

LOCK TABLES `official_registry` WRITE;
/*!40000 ALTER TABLE `official_registry` DISABLE KEYS */;
/*!40000 ALTER TABLE `official_registry` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `revela_notifications`
--

DROP TABLE IF EXISTS `revela_notifications`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
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
  KEY `idx_recipient` (`recipientUserId`,`readAt`),
  KEY `idx_created` (`createdAt`)
) ENGINE=InnoDB AUTO_INCREMENT=297 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `revela_notifications`
--

--
-- Table structure for table `user_app_preferences`
--

DROP TABLE IF EXISTS `user_app_preferences`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `user_app_preferences` (
  `userID` int NOT NULL,
  `email_inspection_alerts` tinyint(1) NOT NULL DEFAULT '1',
  `updatedAt` datetime DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`userID`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `user_app_preferences`
--

LOCK TABLES `user_app_preferences` WRITE;
/*!40000 ALTER TABLE `user_app_preferences` DISABLE KEYS */;
INSERT INTO `user_app_preferences` VALUES (1,0,'2026-07-25 15:29:10'),(7,1,'2026-07-20 08:56:33');
/*!40000 ALTER TABLE `user_app_preferences` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `user_password_resets`
--

DROP TABLE IF EXISTS `user_password_resets`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `user_password_resets` (
  `uprID` int NOT NULL AUTO_INCREMENT,
  `userID` int NOT NULL,
  `pwToken` char(5) COLLATE utf8mb4_unicode_ci NOT NULL,
  `createdAt` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `expiresAt` datetime NOT NULL,
  `isUsed` tinyint(1) NOT NULL DEFAULT '0',
  PRIMARY KEY (`uprID`),
  KEY `fk_upr_user` (`userID`),
  CONSTRAINT `fk_upr_user` FOREIGN KEY (`userID`) REFERENCES `users` (`userID`) ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB AUTO_INCREMENT=15 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `user_password_resets`
--


--
-- Table structure for table `users`
--

DROP TABLE IF EXISTS `users`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `users` (
  `userID` int NOT NULL AUTO_INCREMENT,
  `fullName` varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL,
  `email` varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL,
  `phone` varchar(20) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `userRole` varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL,
  `userPassword` varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL,
  `createdAt` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updatedAt` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  `lastLoginAt` datetime DEFAULT NULL,
  `mustChangePassword` tinyint(1) NOT NULL DEFAULT '0',
  `is_2fa_enabled` tinyint(1) DEFAULT '0',
  `two_factor_secret` varchar(32) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `isActive` tinyint(1) DEFAULT '1',
  `resetRequested` tinyint(1) DEFAULT '0',
  PRIMARY KEY (`userID`),
  UNIQUE KEY `email` (`email`)
) ENGINE=InnoDB AUTO_INCREMENT=14 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `users`
--

LOCK TABLES `users` WRITE;
/*!40000 ALTER TABLE `users` DISABLE KEYS */;
INSERT INTO `users` VALUES (1,'Ralph','ralphmatthew.samonte@gmail.com','09928037409','SUPER_ADMIN','$2b$12$tqf8rBI7DyDlyRZTsxcL7ujNOAxY9DxPGki3En08S.gY6xQujqWjy','2026-05-05 19:59:08','2026-08-28 20:54:58','2026-08-28 20:54:58',0,0,'WNPHH2O5XA67FB5HK2WVPN45BN55M5CR',1,0);
/*!40000 ALTER TABLE `users` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `wlc_config`
--

DROP TABLE IF EXISTS `wlc_config`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `wlc_config` (
  `id` int NOT NULL DEFAULT '1',
  `w1_risk` decimal(5,2) DEFAULT '40.00',
  `w2_sector` decimal(5,2) DEFAULT '40.00',
  `w3_distance` decimal(5,2) DEFAULT '20.00',
  `bplo_lat` decimal(10,8) DEFAULT '13.96670000',
  `bplo_lng` decimal(11,8) DEFAULT '121.11670000',
  `sector_scores` json DEFAULT NULL,
  `updated_at` timestamp NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `wlc_config`
--

LOCK TABLES `wlc_config` WRITE;
/*!40000 ALTER TABLE `wlc_config` DISABLE KEYS */;
INSERT INTO `wlc_config` VALUES (1,40.00,40.00,20.00,13.96670000,121.11670000,'{}','2026-05-10 08:54:24');
/*!40000 ALTER TABLE `wlc_config` ENABLE KEYS */;
UNLOCK TABLES;
/*!40103 SET TIME_ZONE=@OLD_TIME_ZONE */;

/*!40101 SET SQL_MODE=@OLD_SQL_MODE */;
/*!40014 SET FOREIGN_KEY_CHECKS=@OLD_FOREIGN_KEY_CHECKS */;
/*!40014 SET UNIQUE_CHECKS=@OLD_UNIQUE_CHECKS */;
/*!40101 SET CHARACTER_SET_CLIENT=@OLD_CHARACTER_SET_CLIENT */;
/*!40101 SET CHARACTER_SET_RESULTS=@OLD_CHARACTER_SET_RESULTS */;
/*!40101 SET COLLATION_CONNECTION=@OLD_COLLATION_CONNECTION */;
/*!40111 SET SQL_NOTES=@OLD_SQL_NOTES */;

-- Dump completed on 2026-08-28 21:05:25
