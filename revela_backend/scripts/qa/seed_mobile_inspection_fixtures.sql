-- REVELA Mobile synthetic inspection QA fixtures
--
-- Target schema only: revela_test_mobile_phase72.
-- The script is guarded to insert only when DATABASE() is exactly the QA
-- schema and none of the synthetic identifiers/data already exist.
-- It intentionally leaves the transaction open: review the postflight result
-- and issue COMMIT manually only when every expected count and relationship is
-- correct. On any SQL error, blocked preflight, or mismatch, issue ROLLBACK.
-- This file has no cleanup/update/delete statements and must not be run against
-- production or another QA database.
--
-- Synthetic mobile login:
--   Email:    qa.inspector.76a@example.invalid
--   Password: REVELA-QA-Only-2026!
-- The bcrypt hash was generated and verified with the backend's bcrypt
-- hashpw(..., gensalt()) / checkpw() implementation.
--
-- Fictional map coordinates are clustered near the mobile map's local test
-- area. They do not identify a real business or address.

START TRANSACTION;

-- Preflight: default to blocked, then allow inserts only when the current
-- schema is exact and no complete or partial fixture markers already exist.
-- The identifiers cover all fixture tables and relationships, so reruns and
-- partially seeded states are rejected without modifying existing rows.
SET @qa_fixture_seed_allowed := 0;
SELECT 1 INTO @qa_fixture_seed_allowed
FROM DUAL
WHERE DATABASE() = 'revela_test_mobile_phase72'
  AND NOT EXISTS (
    SELECT 1 FROM `revela_test_mobile_phase72`.`barangays`
    WHERE `barangayName` = 'QA Synthetic Barangay 7.6A'
  )
  AND NOT EXISTS (
    SELECT 1 FROM `revela_test_mobile_phase72`.`users`
    WHERE `email` = 'qa.inspector.76a@example.invalid'
  )
  AND NOT EXISTS (
    SELECT 1 FROM `revela_test_mobile_phase72`.`official_registry`
    WHERE `businessID` IN
      ('QA-MOB-76A-001', 'QA-MOB-76A-002', 'QA-MOB-76A-003')
       OR `businessName` IN (
         'QA Fictional Corner Market 7.6A',
         'QA Fictional Garden Supply 7.6A',
         'QA Fictional Paper Lantern Shop 7.6A'
       )
  )
  AND NOT EXISTS (
    SELECT 1 FROM `revela_test_mobile_phase72`.`geospatial_logs`
    WHERE `businessID` IN
      ('QA-MOB-76A-001', 'QA-MOB-76A-002', 'QA-MOB-76A-003')
       OR `detectedName` IN (
         'QA Fictional Corner Market 7.6A',
         'QA Fictional Garden Supply 7.6A',
         'QA Fictional Paper Lantern Shop 7.6A'
       )
  )
  AND NOT EXISTS (
    SELECT 1
    FROM `revela_test_mobile_phase72`.`inspection_reports` AS ir
    LEFT JOIN `revela_test_mobile_phase72`.`users` AS u
      ON u.`userID` = ir.`userID`
    LEFT JOIN `revela_test_mobile_phase72`.`geospatial_logs` AS g
      ON g.`logID` = ir.`targetID`
    WHERE u.`email` = 'qa.inspector.76a@example.invalid'
       OR g.`businessID` IN
         ('QA-MOB-76A-001', 'QA-MOB-76A-002', 'QA-MOB-76A-003')
  )
  AND NOT EXISTS (
    SELECT 1
    FROM `revela_test_mobile_phase72`.`inspection_lifecycle_events` AS e
    LEFT JOIN `revela_test_mobile_phase72`.`inspection_reports` AS ir
      ON ir.`reportID` = e.`reportID`
    LEFT JOIN `revela_test_mobile_phase72`.`geospatial_logs` AS g
      ON g.`logID` = e.`targetLogID`
    LEFT JOIN `revela_test_mobile_phase72`.`users` AS assigned_user
      ON assigned_user.`userID` = e.`assignedToUserID`
    LEFT JOIN `revela_test_mobile_phase72`.`users` AS actor_user
      ON actor_user.`userID` = e.`actorUserID`
    WHERE (ir.`reportID` IS NOT NULL
           AND (
             ir.`userID` = (
               SELECT `userID`
               FROM `revela_test_mobile_phase72`.`users`
               WHERE `email` = 'qa.inspector.76a@example.invalid'
             )
             OR ir.`targetID` IN (
               SELECT `logID`
               FROM `revela_test_mobile_phase72`.`geospatial_logs`
               WHERE `businessID` IN
                 ('QA-MOB-76A-001', 'QA-MOB-76A-002', 'QA-MOB-76A-003')
             )
           ))
       OR g.`businessID` IN
         ('QA-MOB-76A-001', 'QA-MOB-76A-002', 'QA-MOB-76A-003')
       OR assigned_user.`email` = 'qa.inspector.76a@example.invalid'
       OR actor_user.`email` = 'qa.inspector.76a@example.invalid'
  );

-- Inspect this result before proceeding. A value of 0 means the script below
-- is gated off. Stop and ROLLBACK unless it is 1.
SELECT
  DATABASE() AS current_schema,
  @qa_fixture_seed_allowed AS seed_allowed;

-- Fictional location used by all three test businesses.
INSERT INTO `revela_test_mobile_phase72`.`barangays` (`barangayName`)
SELECT 'QA Synthetic Barangay 7.6A'
WHERE @qa_fixture_seed_allowed = 1;

-- Inspector permitted by the mobile login role gate. 2FA is disabled for
-- this synthetic account; password changes are not required during QA login.
INSERT INTO `revela_test_mobile_phase72`.`users`
  (`fullName`, `email`, `userRole`, `userPassword`, `mustChangePassword`,
   `is_2fa_enabled`, `isActive`)
SELECT
  'QA Inspector Fixture 7.6A',
  'qa.inspector.76a@example.invalid',
  'Inspector',
  'REVELA-QA-Only-2026!',
  0, 0, 1
WHERE @qa_fixture_seed_allowed = 1;

-- All businesses are fictional. Pending registry status maps to Yellow in
-- the backend; addresses and Google Place IDs are intentionally absent.
INSERT INTO `revela_test_mobile_phase72`.`official_registry`
  (`businessID`, `barangayID`, `businessName`, `businessType`,
   `lineOfBusiness`, `businessAddress`, `latitude`, `longitude`,
   `applicationStatus`)
SELECT
  'QA-MOB-76A-001', b.`barangayID`, 'QA Fictional Corner Market 7.6A',
  'Retail', 'Synthetic QA fixture', NULL, 13.96670000, 121.11670000,
  'Pending'
FROM `revela_test_mobile_phase72`.`barangays` AS b
WHERE b.`barangayName` = 'QA Synthetic Barangay 7.6A'
  AND @qa_fixture_seed_allowed = 1;

INSERT INTO `revela_test_mobile_phase72`.`official_registry`
  (`businessID`, `barangayID`, `businessName`, `businessType`,
   `lineOfBusiness`, `businessAddress`, `latitude`, `longitude`,
   `applicationStatus`)
SELECT
  'QA-MOB-76A-002', b.`barangayID`, 'QA Fictional Garden Supply 7.6A',
  'Retail', 'Synthetic QA fixture', NULL, 13.96680000, 121.11680000,
  'Pending'
FROM `revela_test_mobile_phase72`.`barangays` AS b
WHERE b.`barangayName` = 'QA Synthetic Barangay 7.6A'
  AND @qa_fixture_seed_allowed = 1;

INSERT INTO `revela_test_mobile_phase72`.`official_registry`
  (`businessID`, `barangayID`, `businessName`, `businessType`,
   `lineOfBusiness`, `businessAddress`, `latitude`, `longitude`,
   `applicationStatus`)
SELECT
  'QA-MOB-76A-003', b.`barangayID`, 'QA Fictional Paper Lantern Shop 7.6A',
  'Retail', 'Synthetic QA fixture', NULL, 13.96660000, 121.11660000,
  'Pending'
FROM `revela_test_mobile_phase72`.`barangays` AS b
WHERE b.`barangayName` = 'QA Synthetic Barangay 7.6A'
  AND @qa_fixture_seed_allowed = 1;

-- Create three Yellow map flags tied to their synthetic registry records.
INSERT INTO `revela_test_mobile_phase72`.`geospatial_logs`
  (`barangayID`, `businessID`, `detectedName`, `latitude`, `longitude`,
   `flagColor`, `noticeLevel`, `reportedByUserID`)
SELECT r.`barangayID`, r.`businessID`, r.`businessName`,
       r.`latitude`, r.`longitude`, 'Yellow', 0, u.`userID`
FROM `revela_test_mobile_phase72`.`official_registry` AS r
JOIN `revela_test_mobile_phase72`.`users` AS u
  ON u.`email` = 'qa.inspector.76a@example.invalid'
WHERE r.`businessID` = 'QA-MOB-76A-001'
  AND @qa_fixture_seed_allowed = 1;

INSERT INTO `revela_test_mobile_phase72`.`geospatial_logs`
  (`barangayID`, `businessID`, `detectedName`, `latitude`, `longitude`,
   `flagColor`, `noticeLevel`, `reportedByUserID`)
SELECT r.`barangayID`, r.`businessID`, r.`businessName`,
       r.`latitude`, r.`longitude`, 'Yellow', 0, u.`userID`
FROM `revela_test_mobile_phase72`.`official_registry` AS r
JOIN `revela_test_mobile_phase72`.`users` AS u
  ON u.`email` = 'qa.inspector.76a@example.invalid'
WHERE r.`businessID` = 'QA-MOB-76A-002'
  AND @qa_fixture_seed_allowed = 1;

INSERT INTO `revela_test_mobile_phase72`.`geospatial_logs`
  (`barangayID`, `businessID`, `detectedName`, `latitude`, `longitude`,
   `flagColor`, `noticeLevel`, `reportedByUserID`)
SELECT r.`barangayID`, r.`businessID`, r.`businessName`,
       r.`latitude`, r.`longitude`, 'Yellow', 0, u.`userID`
FROM `revela_test_mobile_phase72`.`official_registry` AS r
JOIN `revela_test_mobile_phase72`.`users` AS u
  ON u.`email` = 'qa.inspector.76a@example.invalid'
WHERE r.`businessID` = 'QA-MOB-76A-003'
  AND @qa_fixture_seed_allowed = 1;

-- Match the application's first-dispatch row: one report references the
-- assigned log through targetID and uses targetType='geospatial_log'.
-- targetID intentionally has no declared FK in the verified schema.
INSERT INTO `revela_test_mobile_phase72`.`inspection_reports`
  (`userID`, `targetID`, `targetType`, `verificationStatus`, `wasReassigned`)
SELECT u.`userID`, g.`logID`, 'geospatial_log', 'Assigned', 0
FROM `revela_test_mobile_phase72`.`users` AS u
JOIN `revela_test_mobile_phase72`.`geospatial_logs` AS g
  ON g.`businessID` = 'QA-MOB-76A-001'
WHERE u.`email` = 'qa.inspector.76a@example.invalid'
  AND u.`userRole` = 'Inspector'
  AND @qa_fixture_seed_allowed = 1;

-- Initial assignment cycle: cycleID stays NULL, as in assign_inspection().
-- Mobile task retrieval uses COALESCE(cycleID, eventID), so this event's
-- generated eventID is the assignmentCycleID returned to the app.
-- actorUserID is NULL because this seed does not create a synthetic admin
-- account or claim that the inspector dispatched their own assignment.
INSERT INTO `revela_test_mobile_phase72`.`inspection_lifecycle_events`
  (`reportID`, `targetLogID`, `cycleID`, `eventType`, `actorUserID`,
   `assignedToUserID`, `flagColorAtEvent`)
SELECT ir.`reportID`, ir.`targetID`, NULL, 'dispatched', NULL,
       ir.`userID`, g.`flagColor`
FROM `revela_test_mobile_phase72`.`inspection_reports` AS ir
JOIN `revela_test_mobile_phase72`.`geospatial_logs` AS g
  ON g.`logID` = ir.`targetID`
JOIN `revela_test_mobile_phase72`.`users` AS u
  ON u.`userID` = ir.`userID`
WHERE u.`email` = 'qa.inspector.76a@example.invalid'
  AND g.`businessID` = 'QA-MOB-76A-001'
  AND ir.`targetType` = 'geospatial_log'
  AND ir.`verificationStatus` = 'Assigned'
  AND @qa_fixture_seed_allowed = 1;

-- Postflight: expected counts are 1 barangay, 1 user, 3 registry rows,
-- 3 reported Yellow logs, 1 Assigned report, and 1 dispatched event.
-- Confirm all counts and the identity row below before manually committing.
-- If any statement failed, any count differs, or preflight seed_allowed=0,
-- issue ROLLBACK in this same connection. This file deliberately does not
-- commit, so Workbench continuing after an error cannot persist a partial seed.
SELECT
  @qa_fixture_seed_allowed AS seed_allowed,
  (SELECT COUNT(*) FROM `revela_test_mobile_phase72`.`barangays`
   WHERE `barangayName` = 'QA Synthetic Barangay 7.6A') AS barangay_count,
  (SELECT COUNT(*) FROM `revela_test_mobile_phase72`.`users`
   WHERE `email` = 'qa.inspector.76a@example.invalid') AS inspector_count,
  (SELECT COUNT(*) FROM `revela_test_mobile_phase72`.`official_registry`
   WHERE `businessID` IN
     ('QA-MOB-76A-001', 'QA-MOB-76A-002', 'QA-MOB-76A-003')) AS registry_count,
  (SELECT COUNT(*) FROM `revela_test_mobile_phase72`.`geospatial_logs`
   WHERE `businessID` IN
     ('QA-MOB-76A-001', 'QA-MOB-76A-002', 'QA-MOB-76A-003')
     AND `flagColor` = 'Yellow'
     AND `reportedByUserID` = (
       SELECT `userID` FROM `revela_test_mobile_phase72`.`users`
       WHERE `email` = 'qa.inspector.76a@example.invalid'
     )) AS reported_yellow_log_count,
  (SELECT COUNT(*) FROM `revela_test_mobile_phase72`.`inspection_reports` AS ir
   JOIN `revela_test_mobile_phase72`.`geospatial_logs` AS g
     ON g.`logID` = ir.`targetID`
   JOIN `revela_test_mobile_phase72`.`users` AS u
     ON u.`userID` = ir.`userID`
   WHERE u.`email` = 'qa.inspector.76a@example.invalid'
     AND g.`businessID` = 'QA-MOB-76A-001'
     AND ir.`targetType` = 'geospatial_log'
     AND ir.`verificationStatus` = 'Assigned') AS assigned_report_count,
  (SELECT COUNT(*) FROM `revela_test_mobile_phase72`.`inspection_lifecycle_events` AS e
   JOIN `revela_test_mobile_phase72`.`inspection_reports` AS ir
     ON ir.`reportID` = e.`reportID`
   JOIN `revela_test_mobile_phase72`.`geospatial_logs` AS g
     ON g.`logID` = e.`targetLogID`
   WHERE g.`businessID` = 'QA-MOB-76A-001'
     AND e.`eventType` = 'dispatched'
     AND e.`cycleID` IS NULL) AS dispatched_event_count;

-- assignmentCycleID is the dispatched eventID while cycleID is NULL, as in
-- the backend task query. This row also provides the IDs to use in later tests.
SELECT
  u.`userID`,
  u.`email`,
  b.`barangayID`,
  ir.`reportID`,
  ir.`targetID` AS `logID`,
  COALESCE(e.`cycleID`, e.`eventID`) AS `assignmentCycleID`,
  e.`eventID` AS `dispatchedEventID`,
  ir.`verificationStatus`,
  g.`detectedName`,
  g.`flagColor`
FROM `revela_test_mobile_phase72`.`users` AS u
JOIN `revela_test_mobile_phase72`.`inspection_reports` AS ir
  ON ir.`userID` = u.`userID`
JOIN `revela_test_mobile_phase72`.`geospatial_logs` AS g
  ON g.`logID` = ir.`targetID`
JOIN `revela_test_mobile_phase72`.`barangays` AS b
  ON b.`barangayID` = g.`barangayID`
JOIN `revela_test_mobile_phase72`.`inspection_lifecycle_events` AS e
  ON e.`reportID` = ir.`reportID`
 AND e.`eventType` = 'dispatched'
WHERE u.`email` = 'qa.inspector.76a@example.invalid'
  AND g.`businessID` = 'QA-MOB-76A-001'
ORDER BY e.`eventID` DESC
LIMIT 1;
