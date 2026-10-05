-- Run once with migration/admin credentials in the target database before deployment.
CREATE TABLE IF NOT EXISTS `inspection_lifecycle_events` (
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
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_unicode_ci;