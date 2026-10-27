"""MySQL 8 disposable-server workload/source regressions.

Run only through scripts/run_registry_sync_audit.py --test tests.test_dashboard_mysql.
This module cannot connect to an existing database by itself.
"""
from datetime import datetime, timedelta
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from api.inspections.workload import build_summary, current_rows, hidden_open_count, list_page
from api.registry.colors import reset_ladder_column_cache


connect_to_disposable_mysql = None
flags = None
inspections = None
reset_source_column_cache = None


class DashboardMySQLTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if connect_to_disposable_mysql is None:
            raise unittest.SkipTest("Disposable MySQL runner required; never use application credentials")
        global flags, inspections, reset_source_column_cache
        from api.flags import service as flags
        from api.inspections import service as inspections
        from api.models.geospatial import reset_source_column_cache
        cls.db = connect_to_disposable_mysql()
        with cls.db.cursor() as cur:
            cur.execute("SELECT VERSION() AS version, @@SESSION.sql_mode AS mode, DATABASE() AS db")
            details = cur.fetchone()
            assert details["db"] == "revela_registry_sync_audit"
            assert details["version"].startswith("8.4."), details
            assert "STRICT_TRANS_TABLES" in details["mode"] and "ONLY_FULL_GROUP_BY" in details["mode"]
            print("Isolated dashboard MySQL:", details, flush=True)
            for statement in (
                "CREATE TABLE barangays (barangayID INT PRIMARY KEY, barangayName VARCHAR(80)) ENGINE=InnoDB",
                """CREATE TABLE official_registry (
                    businessID VARCHAR(50) PRIMARY KEY, barangayID INT NOT NULL,
                    businessName VARCHAR(255), businessAddress VARCHAR(255), businessSize VARCHAR(50),
                    latitude DECIMAL(10,8), longitude DECIMAL(11,8), placeID VARCHAR(255),
                    confirmedLogID INT NULL, applicationStatus VARCHAR(30), lastRenewalDate DATETIME,
                    matchStatus VARCHAR(30), coordSource VARCHAR(30), matchScore DECIMAL(4,3)
                ) ENGINE=InnoDB""",
                """CREATE TABLE geospatial_logs (
                    logID INT PRIMARY KEY, businessID VARCHAR(50) NULL, barangayID INT NOT NULL,
                    detectedName VARCHAR(255), detectedDate DATETIME, flagColor VARCHAR(30),
                    latitude DECIMAL(10,8), longitude DECIMAL(11,8), placeID VARCHAR(255),
                    source VARCHAR(24) NOT NULL DEFAULT 'unknown', nearestLandmark VARCHAR(255),
                    reportedByUserID INT, notes TEXT, noticeLevel INT DEFAULT 0
                ) ENGINE=InnoDB""",
                """CREATE TABLE inspection_reports (
                    reportID INT PRIMARY KEY, userID INT, targetID INT, targetType VARCHAR(50),
                    verificationStatus VARCHAR(30), inspectionResult VARCHAR(30),
                    irTimestamp DATETIME(6), deadline DATETIME(6), resolutionTime INT,
                    submittedAt DATETIME(6), submissionReceivedAt DATETIME(6),
                    verifiedLatitude DECIMAL(10,8), verifiedLongitude DECIMAL(11,8),
                    verifiedAccuracy DECIMAL(8,2), wasReassigned INT DEFAULT 0,
                    noticeLevel INT DEFAULT 0, remarks VARCHAR(255), photoPath TEXT,
                    nearestLandmark VARCHAR(255)
                ) ENGINE=InnoDB""",
                """CREATE TABLE inspection_lifecycle_events (
                    eventID INT PRIMARY KEY, reportID INT, targetLogID INT, cycleID INT,
                    eventType VARCHAR(30), eventTimestamp DATETIME(6), actorUserID INT,
                    assignedToUserID INT, inspectionResult VARCHAR(30), remarks VARCHAR(255),
                    flagColorAtEvent VARCHAR(30)
                ) ENGINE=InnoDB""",
                "CREATE TABLE users (userID INT PRIMARY KEY, fullName VARCHAR(80), userRole VARCHAR(30)) ENGINE=InnoDB",
            ):
                cur.execute(statement)
        cls.db.commit()

    @classmethod
    def tearDownClass(cls):
        cls.db.close()

    def setUp(self):
        self.db.rollback()
        with self.db.cursor() as cur:
            for table in ("inspection_lifecycle_events", "inspection_reports", "geospatial_logs",
                          "official_registry", "barangays", "users"):
                cur.execute(f"DELETE FROM {table}")
            cur.execute("INSERT INTO barangays VALUES (1,'Barangay One'),(2,'Barangay Two')")
            cur.execute("INSERT INTO users VALUES (9,'Fixture Inspector','Inspector')")
            cur.execute("SELECT UTC_TIMESTAMP(0) AS now")
            self.as_of = cur.fetchone()["now"]
        self.db.commit()
        reset_source_column_cache()
        reset_ladder_column_cache()
        self.flag_patch = patch.object(flags, "mysql", SimpleNamespace(connection=self.db))
        self.inspection_patch = patch.object(inspections, "mysql", SimpleNamespace(connection=self.db))
        self.flag_patch.start()
        self.inspection_patch.start()
        self.addCleanup(self.flag_patch.stop)
        self.addCleanup(self.inspection_patch.stop)

    def seed(self, log_id, status=None, *, report_id=None, barangay=1, source="detection",
             business_id=None, deadline=None, start=None, received=None, minutes=None, ir_timestamp=None):
        with self.db.cursor() as cur:
            cur.execute("""INSERT INTO geospatial_logs
                (logID,businessID,barangayID,detectedName,detectedDate,flagColor,latitude,longitude,source)
                VALUES (%s,%s,%s,%s,%s,'Red',13.9667,121.1167,%s)""",
                (log_id, business_id, barangay, f"Fixture {log_id}", self.as_of - timedelta(days=5), source))
            if report_id is not None:
                self.report(cur, report_id, log_id, status, deadline, start, received, minutes, ir_timestamp)
        self.db.commit()

    def report(self, cur, report_id, log_id, status, deadline=None, start=None,
               received=None, minutes=None, ir_timestamp=None):
        cur.execute("""INSERT INTO inspection_reports
            (reportID,userID,targetID,targetType,verificationStatus,irTimestamp,deadline,
             submissionReceivedAt,resolutionTime)
            VALUES (%s,9,%s,'geospatial_log',%s,%s,%s,%s,%s)""",
            (report_id, log_id, status, ir_timestamp or self.as_of - timedelta(days=2),
             deadline, received, minutes))
        if start is not None:
            cur.execute("""INSERT INTO inspection_lifecycle_events
                (eventID,reportID,targetLogID,eventType,eventTimestamp)
                VALUES (%s,%s,%s,'dispatched',%s)""",
                (report_id * 10, report_id, log_id, start))

    def test_workload_summary_list_parity_in_supported_modes(self):
        for mode in ("server_default", "NO_AUTO_VALUE_ON_ZERO"):
            with self.subTest(mode=mode):
                with self.db.cursor() as cur:
                    if mode != "server_default":
                        cur.execute("SET SESSION sql_mode='NO_AUTO_VALUE_ON_ZERO'")
                    else:
                        cur.execute("SET SESSION sql_mode=DEFAULT")
                local_now = self.as_of + timedelta(hours=8)
                # Three consecutive open ages, an unknown start, and one stale
                # historical open report hidden behind a newer report on log 1.
                self.seed(1, "Reassigned", report_id=2, start=self.as_of - timedelta(days=4, hours=2),
                          deadline=local_now - timedelta(microseconds=1))
                with self.db.cursor() as cur:
                    self.report(cur, 1, 1, "Assigned", start=self.as_of - timedelta(days=20))
                    cur.execute("""INSERT INTO inspection_lifecycle_events
                        (eventID,reportID,targetLogID,eventType,eventTimestamp)
                        VALUES (21,2,1,'submitted',%s),(22,2,1,'reassigned',%s),
                               (23,2,1,'reassigned',%s)""",
                        (self.as_of - timedelta(days=2), self.as_of - timedelta(days=1),
                         self.as_of - timedelta(days=1)))
                self.seed(2, "Assigned", report_id=3, start=self.as_of - timedelta(days=8), deadline=local_now)
                self.seed(3, "Assigned", report_id=4, start=self.as_of - timedelta(days=16), deadline=local_now + timedelta(seconds=1))
                self.seed(4, "Assigned", report_id=5, barangay=2,
                          deadline=None, ir_timestamp=self.as_of - timedelta(days=100))
                self.seed(5, "Submitted", report_id=6, received=self.as_of - timedelta(days=30), minutes=0)
                self.seed(6, "Verified", report_id=7, received=self.as_of - timedelta(microseconds=1), minutes=20)
                self.seed(7, "Submitted", report_id=8, received=self.as_of - timedelta(days=1), minutes=-1)
                self.seed(8, "Verified", report_id=9, received=self.as_of, minutes=100)
                self.seed(9, "Submitted", report_id=10, received=None, minutes=55)
                self.seed(10, "In Progress", report_id=11, start=self.as_of - timedelta(days=3))
                self.db.commit()
                with self.db.cursor() as cur:
                    rows = current_rows(cur)
                    self.assertEqual(next(row for row in rows if row["reportID"] == 2)["cycleStart"],
                                     self.as_of - timedelta(days=1))
                    hidden = hidden_open_count(cur)
                    summary = build_summary(rows, self.as_of, hidden)
                    self.assertEqual({row["reportID"] for row in rows}, set(range(2, 12)))
                    self.assertEqual((summary["open"], summary["overdue"], summary["older_hidden_open_reports"]), (4, 1, 1))
                    self.assertEqual(summary["awaiting_verification"], 3)
                    self.assertEqual(summary["oldest_report_id"], 4)
                    self.assertEqual(summary["age_groups"], {"0-3": 1, "4-7": 0, "8-14": 1, "15+": 1})
                    self.assertEqual(summary["age_unavailable"], 1)
                    self.assertEqual((summary["resolution_sample_size"], summary["resolution_excluded"],
                                      summary["average_resolution_minutes"]), (2, 1, 10.0))
                    self.assertEqual(summary["missing_submission_received"], 1)
                    for view, count in (("open", summary["open"]), ("overdue", summary["overdue"]),
                                        ("awaiting_verification", summary["awaiting_verification"]),
                                        ("resolution", summary["resolution_sample_size"]),
                                        ("age_0-3", 1), ("age_8-14", 1), ("age_15+", 1),
                                        ("age_unavailable", 1), ("deadline_missing", 1)):
                        total, ids = list_page(cur, self.as_of, view, 1, 2)
                        self.assertEqual(total, count, view)
                        pages = [ids]
                        for page in range(2, (total + 1) // 2 + 1):
                            page_total, page_ids = list_page(cur, self.as_of, view, page, 2)
                            self.assertEqual(page_total, total)
                            pages.append(page_ids)
                        all_ids = [item for part in pages for item in part]
                        self.assertEqual(len(set(all_ids)), count, view)
                        self.assertNotIn(1, all_ids)  # hidden prior report
                        # Exercise Dispatch's detail lookup, not just ID selection.
                        for part in pages:
                            detail, error = inspections.get_all_inspections(report_ids=part, per_page=max(len(part), 1))
                            self.assertIsNone(error, (view, error))
                            self.assertEqual({r["reportID"] for r in detail["data"]}, set(part))
                    self.assertEqual(list_page(cur, self.as_of, "oldest", 1, 20, report_id=4)[1], [4])
                    self.assertEqual(list_page(cur, self.as_of, "deadline_day", 1, 20,
                                               deadline_date=local_now.date())[0], 3)
                    self.assertEqual(list_page(cur, self.as_of, "open", 1, 20, barangay_id=2)[1], [5])
                    scoped = build_summary([r for r in rows if r["barangayID"] == 2],
                                           self.as_of, hidden_open_count(cur, 2))
                    self.assertEqual((scoped["open"], scoped["age_unavailable"], scoped["older_hidden_open_reports"]),
                                     (1, 1, 0))
                    self.assertEqual(list_page(cur, self.as_of, "open", 1, 20, report_id=2, status="Reassigned")[1], [2])
                    self.assertEqual(list_page(cur, self.as_of, "open", 1, 20, status="Submitted")[0], 0)
                    self.assertEqual(list_page(cur, self.as_of, "open", 3, 2)[1], [])
                # Each subcase has an entirely fresh synthetic population.
                with self.db.cursor() as cur:
                    for table in ("inspection_lifecycle_events", "inspection_reports", "geospatial_logs"):
                        cur.execute(f"DELETE FROM {table}")
                self.db.commit()

    def test_source_count_list_match_and_unknown_is_never_guessed(self):
        with self.db.cursor() as cur:
            cur.execute("""INSERT INTO official_registry
                (businessID,barangayID,businessName,applicationStatus,latitude,longitude)
                VALUES ('REG-A',1,'Linked A','Active',13.9667,121.1167),
                       ('REG-B',1,'Linked B','Active',13.9667,121.1167),
                       ('REG-C',2,'Registry only','Pending',13.9667,121.1167)""")
        self.seed(1, source="registry_detected", business_id="REG-A")
        self.seed(2, source="manual", business_id="REG-B")
        for log_id in range(3, 8): self.seed(log_id, source="detection")
        for log_id in (8, 9): self.seed(log_id, source="manual")
        self.seed(15, source="manual", barangay=2)
        self.seed(10, source="unknown")
        self.seed(11, source="registry_detected")  # contradictory origin without a live link
        self.seed(12, source="registry")
        self.seed(13, source="unknown", business_id="REG-A")  # unknown origin, live registry link
        with self.db.cursor() as cur:
            cur.execute("UPDATE geospatial_logs SET detectedName='Linked A' WHERE logID=10")
            cur.execute("""INSERT INTO geospatial_logs
                (logID,barangayID,detectedName,detectedDate,flagColor,latitude,longitude)
                VALUES (14,1,'Legacy without source',%s,'Red',13.9667,121.1167)""", (self.as_of,))
        self.db.commit()
        # Do not infer a registry link merely from name, coordinates, or source.
        expected = {"detection": {3, 4, 5, 6, 7}, "manual": {8, 9, 15},
                    "unclassified": {10, 11, 12, 14}}
        for mode in ("server_default", "NO_AUTO_VALUE_ON_ZERO"):
            with self.subTest(mode=mode):
                with self.db.cursor() as cur:
                    cur.execute("SET SESSION sql_mode=DEFAULT" if mode == "server_default"
                                else "SET SESSION sql_mode='NO_AUTO_VALUE_ON_ZERO'")
                for origin, expected_ids in expected.items():
                    total = None
                    all_ids = []
                    for page in range(1, 5):
                        result, error = flags.get_flags(origin=origin, registry_link="unlinked", page=page, per_page=2)
                        self.assertIsNone(error, (origin, error))
                        if total is None: total = result["total"]
                        self.assertEqual(result["total"], total)
                        all_ids.extend(row["logID"] for row in result["data"])
                        for row in result["data"]:
                            self.assertFalse(row["registryLinked"])
                            if origin == "unclassified":
                                self.assertNotIn(row["originSource"], ("detection", "manual"))
                            else:
                                self.assertEqual(row["originSource"], origin)
                        if page == result["pages"]: break
                    self.assertEqual(total, len(expected_ids))
                    self.assertEqual(set(all_ids), expected_ids)
                    self.assertEqual(len(all_ids), total)
                for origin in expected:
                    result, error = flags.get_flags(origin=origin, registry_link="unlinked", barangay_id=2,
                                                    page=1, per_page=2)
                    self.assertIsNone(error, error)
                    self.assertEqual(result["total"], 1 if origin == "manual" else 0)
                    self.assertEqual([row["logID"] for row in result["data"]], [15] if origin == "manual" else [])
