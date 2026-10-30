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
                    businessType VARCHAR(50), registrationType VARCHAR(50),
                    lineOfBusiness VARCHAR(500) CHARACTER SET utf8mb3 COLLATE utf8mb3_unicode_ci,
                    latitude DECIMAL(10,8), longitude DECIMAL(11,8), placeID VARCHAR(255),
                    confirmedLogID INT NULL, applicationStatus VARCHAR(30), lastRenewalDate DATETIME,
                    matchStatus VARCHAR(30), coordSource VARCHAR(30), matchScore DECIMAL(4,3)
                ) ENGINE=InnoDB""",
                """CREATE TABLE display_sector (
                    normalized_major_type VARCHAR(255) PRIMARY KEY,
                    display_sector_key VARCHAR(64), display_sector_label VARCHAR(100),
                    sort_order SMALLINT NOT NULL DEFAULT 0, is_active TINYINT(1) NOT NULL DEFAULT 1
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci""",
                """CREATE TABLE registry_sector_map (
                    normalized_line_of_business VARCHAR(500) PRIMARY KEY,
                    raw_line_of_business VARCHAR(500),
                    source_version VARCHAR(80),
                    display_sector_key VARCHAR(64), display_sector_label VARCHAR(100),
                    match_status ENUM('matched','combo','ambiguous','unmatched') NOT NULL,
                    primary_psic_line_id BIGINT NULL,
                    candidate_count SMALLINT UNSIGNED NOT NULL DEFAULT 0
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci""",
                """CREATE TABLE registry_sector_map_secondary (
                    normalized_line_of_business VARCHAR(500) NOT NULL,
                    psic_line_id BIGINT NOT NULL,
                    PRIMARY KEY (normalized_line_of_business, psic_line_id)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci""",
                """CREATE TABLE registry_sector_review_queue (
                    normalized_line_of_business VARCHAR(500) PRIMARY KEY,
                    raw_line_of_business VARCHAR(500) NOT NULL,
                    review_status ENUM('ambiguous','unmatched') NOT NULL,
                    candidate_count SMALLINT UNSIGNED NOT NULL DEFAULT 0,
                    first_seen_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    last_seen_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    reviewed_at DATETIME NULL,
                    reviewed_by VARCHAR(255) NULL
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci""",
                """CREATE TABLE psic_active_version (
                    singleton_id TINYINT PRIMARY KEY,
                    source_version VARCHAR(80) NOT NULL
                ) ENGINE=InnoDB""",
                """CREATE TABLE psic_lines (
                    psic_line_id BIGINT PRIMARY KEY,
                    source_version VARCHAR(80) NOT NULL,
                    source_row_number INT NOT NULL,
                    normalized_line_of_business VARCHAR(500) NOT NULL,
                    normalized_major_type VARCHAR(255) NOT NULL,
                    major_type_clean VARCHAR(255) NOT NULL,
                    line_of_business VARCHAR(500) NOT NULL
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
                """CREATE TABLE detection_runs (
                    runID INT PRIMARY KEY, startedAt DATETIME NOT NULL,
                    completedAt DATETIME NULL, status VARCHAR(32) NOT NULL,
                    newFlags INT DEFAULT 0, totalChecked INT DEFAULT 0
                ) ENGINE=InnoDB""",
                "CREATE TABLE users (userID INT PRIMARY KEY, fullName VARCHAR(80), userRole VARCHAR(30)) ENGINE=InnoDB",
                """CREATE TABLE revela_app_settings (
                    settingKey VARCHAR(96) PRIMARY KEY,
                    settingValue TEXT NOT NULL,
                    updatedBy INT NULL,
                    updatedAt DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                        ON UPDATE CURRENT_TIMESTAMP
                ) ENGINE=InnoDB""",
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
                          "detection_runs",
                          "registry_sector_map_secondary", "registry_sector_review_queue",
                          "registry_sector_map", "psic_active_version", "psic_lines",
                          "display_sector", "official_registry", "barangays", "users",
                          "revela_app_settings"):
                cur.execute(f"DELETE FROM {table}")
            reset_ladder_column_cache()
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

    def test_map_payload_keeps_pin_barangay_separate_from_registry_barangay(self):
        with self.db.cursor() as cur:
            cur.execute("""INSERT INTO official_registry
                (businessID,barangayID,businessName,applicationStatus,latitude,longitude)
                VALUES ('PIN-ID-MISMATCH',2,'Registry Barangay Two','Active',13.95,121.11)""")
            cur.execute("""INSERT INTO geospatial_logs
                (logID,businessID,barangayID,detectedName,detectedDate,flagColor,
                 latitude,longitude,source)
                VALUES (901,'PIN-ID-MISMATCH',1,'Pin stored in Barangay One',
                        UTC_TIMESTAMP(),'Green',13.95,121.11,'registry')""")
        self.db.commit()

        payload, error = flags.get_flags(per_page=100)

        self.assertIsNone(error, error)
        row = next(item for item in payload["data"] if item["logID"] == 901)
        self.assertEqual(row["barangayID"], 2)
        self.assertEqual(row["barangayName"], "Barangay Two")
        self.assertEqual(row["recordedBarangayID"], 1)

    def test_hotspots_endpoint_sql_runs_under_only_full_group_by_and_accounts_for_populations(self):
        from flask import Flask
        from api.analytics import routes as analytics_routes
        from api.analytics.hotspots import invalidate_hotspots_cache

        with self.db.cursor() as cur:
            cur.execute(
                "SET SESSION sql_mode=CONCAT(@@SESSION.sql_mode, ',ONLY_FULL_GROUP_BY')"
            )
            cur.execute("SELECT @@SESSION.sql_mode AS mode")
            self.assertIn("ONLY_FULL_GROUP_BY", cur.fetchone()["mode"])
            cur.execute("""INSERT INTO official_registry
                (businessID,barangayID,businessName,applicationStatus)
                VALUES ('HOTSPOT-LINKED',1,'Linked Registry Business','Expired')""")
            cur.execute("""INSERT INTO geospatial_logs
                (logID,businessID,barangayID,detectedName,detectedDate,flagColor,
                 latitude,longitude,source)
                VALUES
                (101,NULL,1,'Eligible detection',UTC_TIMESTAMP(),'Red',13.9667,121.1167,'detection'),
                (102,NULL,1,'Not detection',UTC_TIMESTAMP(),'Red',13.9668,121.1168,'manual'),
                (103,'HOTSPOT-LINKED',1,'Registry linked',UTC_TIMESTAMP(),'Red',13.9669,121.1169,'detection'),
                (104,NULL,1,'Missing coordinates',UTC_TIMESTAMP(),'Red',NULL,NULL,'detection')""")
            cur.execute(
                "INSERT INTO detection_runs (runID,startedAt,status) "
                "VALUES (1,UTC_TIMESTAMP(),'partial')"
            )
        self.db.commit()

        app = Flask(__name__)
        settings_mysql = SimpleNamespace(connection=self.db)
        with patch.object(analytics_routes, "mysql", settings_mysql), \
                patch.object(analytics_routes, "load_barangay_polygons", return_value=[]):
            with app.test_request_context("/api/analytics/hotspots?date_preset=7days"):
                invalidate_hotspots_cache()
                response, status = analytics_routes.get_analytics_hotspots.__wrapped__()
            payload = response.get_json()

            with self.db.cursor() as cur:
                cur.execute(
                    "INSERT INTO revela_app_settings (settingKey, settingValue) "
                    "VALUES ('hotspots.eps_m', '50')"
                )
            self.db.commit()

            with app.test_request_context("/api/analytics/hotspots?date_preset=7days"):
                source_response, source_status = (
                    analytics_routes.get_analytics_hotspots.__wrapped__()
                )
            source_payload = source_response.get_json()

            invalidate_hotspots_cache()
            with app.test_request_context(
                "/api/analytics/hotspots?date_preset=7days"
                "&population=unregistered_candidates"
            ):
                candidates_response, candidates_status = (
                    analytics_routes.get_analytics_hotspots.__wrapped__()
                )
            candidates_payload = candidates_response.get_json()

            invalidate_hotspots_cache()
            with app.test_request_context(
                "/api/analytics/hotspots?date_preset=7days"
                "&display_sector=retail&barangay_id=999"
            ):
                filtered_response, filtered_status = (
                    analytics_routes.get_analytics_hotspots.__wrapped__()
                )
            filtered_payload = filtered_response.get_json()

        self.assertEqual(status, 200)
        self.assertEqual(source_status, 200)
        self.assertEqual(candidates_status, 200)
        self.assertEqual(filtered_status, 200)
        self.assertEqual(payload["parameters_used"], {
            "eps_m": 50,
            "min_samples": 3,
            "metric": "haversine",
            "flags": ["Red", "Black"],
            "source": "default",
            "sources": {
                "eps_m": "default",
                "min_samples": "default",
                "flags": "default",
            },
        })
        self.assertEqual(payload["parameters_used"]["source"], "default")
        self.assertEqual(source_payload["parameters_used"]["source"], "setting")
        self.assertEqual(
            source_payload["parameters_used"]["sources"],
            {"eps_m": "setting", "min_samples": "default", "flags": "default"},
        )
        self.assertEqual(payload["population"]["considered_records"], 4)
        self.assertEqual(
            payload["population"]["considered_records"],
            payload["population"]["eligible_points"]
            + sum(payload["population"]["excluded"].values()),
        )
        self.assertEqual(payload["population"]["eligible_points"], 3)
        self.assertEqual(payload["population"]["excluded"], {
            "not_detection": 0,
            "registry_linked": 0,
            "business_id_present": 0,
            "missing_coordinates": 1,
        })
        self.assertEqual(payload["population"]["counts_by_flag"], {"Red": 4, "Black": 0})
        self.assertEqual(
            candidates_payload["population"]["name"],
            "unregistered_candidates",
        )
        self.assertEqual(candidates_payload["population"]["flags"], ["Red"])
        self.assertEqual(candidates_payload["population"]["eligible_points"], 1)
        self.assertEqual(candidates_payload["population"]["excluded"], {
            "not_detection": 1,
            "registry_linked": 1,
            "business_id_present": 0,
            "missing_coordinates": 1,
        })
        self.assertEqual(payload["last_detection_run"]["status"], "partial")
        self.assertIsNone(payload["last_detection_run"]["stop_reason"])
        self.assertEqual(filtered_payload["population"], payload["population"])
        self.assertEqual(filtered_payload["clusters"], payload["clusters"])
        self.assertEqual(filtered_payload["totals"], payload["totals"])

    def test_detection_run_stop_metadata_migration_and_pre_migration_fallback(self):
        from pathlib import Path

        from flask import Flask
        from api.analytics import routes as analytics_routes
        from api.analytics.hotspots import invalidate_hotspots_cache
        from api.models import detection_runs

        migration = (
            Path(__file__).resolve().parents[1]
            / "migrations"
            / "20261029_03_detection_run_stop_metadata.sql"
        )
        with self.db.cursor() as cur:
            cur.execute(
                "INSERT INTO detection_runs "
                "(runID,startedAt,status,newFlags,totalChecked) "
                "VALUES (9,UTC_TIMESTAMP(),'running',0,0)"
            )
        self.db.commit()

        database = SimpleNamespace(connection=self.db)
        with patch.object(detection_runs, "mysql", database):
            detection_runs.update_detection_run_status(
                9, "partial", new_flags=2, total_checked=15,
                stop_reason="work_budget", requests_used=8,
                max_requests=20, max_seconds=120,
            )

        with self.db.cursor() as cur:
            cur.execute(
                "SELECT status,newFlags,totalChecked FROM detection_runs "
                "WHERE runID=9"
            )
            legacy_row = cur.fetchone()
            self.assertEqual(
                (legacy_row["status"], legacy_row["newFlags"],
                 legacy_row["totalChecked"]),
                ("partial", 2, 15),
            )
            cur.execute(migration.read_text(encoding="utf-8"))
        self.db.commit()

        with patch.object(detection_runs, "mysql", database):
            detection_runs.update_detection_run_status(
                9, "partial", new_flags=3, total_checked=21,
                stop_reason="request_limit", requests_used=20,
                max_requests=20, max_seconds=120,
            )

        with self.db.cursor() as cur:
            cur.execute(
                """SELECT status,newFlags,totalChecked,stopReason,
                          requestsUsed,maxRequests,maxSeconds
                   FROM detection_runs WHERE runID=9"""
            )
            row = cur.fetchone()
        self.assertEqual(
            (row["status"], row["newFlags"], row["totalChecked"],
             row["stopReason"], row["requestsUsed"], row["maxRequests"],
             row["maxSeconds"]),
            ("partial", 3, 21, "request_limit", 20, 20, 120),
        )
        with patch.object(analytics_routes, "mysql", database):
            with Flask(__name__).test_request_context(
                "/api/analytics/hotspots?date_preset=all"
            ):
                invalidate_hotspots_cache()
                response, status = (
                    analytics_routes.get_analytics_hotspots.__wrapped__()
                )
                payload = response.get_json()
        invalidate_hotspots_cache()
        self.assertEqual(status, 200)
        self.assertEqual(
            payload["last_detection_run"]["stop_reason"], "request_limit"
        )

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

    def test_barangay_overview_sector_filter_on_mysql_8_full_group_by(self):
        from flask import Flask

        from api.analytics import routes
        from api.analytics.filters import registry_sql

        with self.db.cursor() as cur:
            cur.execute(
                "SET SESSION sql_mode='STRICT_TRANS_TABLES,ONLY_FULL_GROUP_BY'"
            )
            cur.execute("SELECT VERSION() AS version, @@SESSION.sql_mode AS mode")
            details = cur.fetchone()
            self.assertTrue(details["version"].startswith("8."), details)
            self.assertIn("ONLY_FULL_GROUP_BY", details["mode"])
            cur.executemany(
                "INSERT INTO barangays (barangayID, barangayName) VALUES (%s, %s)",
                [(bid, f"Barangay {bid}") for bid in range(3, 17)],
            )
            cur.executemany(
                """INSERT INTO display_sector
                       (normalized_major_type, display_sector_key,
                        display_sector_label, sort_order, is_active)
                   VALUES (%s, %s, %s, %s, 1)""",
                [
                    ("retail_trade", "retail", "Retail outlets", 2),
                    ("retail_other", "retail", "Retail", 1),
                    ("food_service", "food_drink", "Food and drink", 3),
                ],
            )
            cur.executemany(
                """INSERT INTO official_registry
                       (businessID, barangayID, businessName, businessSize,
                        businessType, registrationType, lineOfBusiness)
                   VALUES (%s, 1, %s, 'MICRO', 'SOLE', 'NEW', %s)""",
                [
                    ("SECTOR-RETAIL", "Retail test", "Retail activity"),
                    ("SECTOR-FOOD", "Food test", "Food activity"),
                ],
            )
            cur.executemany(
                """INSERT INTO registry_sector_map
                       (normalized_line_of_business, display_sector_key,
                        display_sector_label, match_status)
                   VALUES (%s, %s, %s, 'matched')""",
                [
                    ("retailactivity", "retail", "Retail"),
                    ("foodactivity", "food_drink", "Food and drink"),
                ],
            )
            cur.execute(
                """INSERT INTO geospatial_logs
                       (logID, barangayID, detectedName, detectedDate, flagColor,
                        latitude, longitude, source)
                   VALUES (901, 1, 'Sector-independent pin', %s, 'Green',
                           13.9667, 121.1167, 'manual')""",
                (self.as_of,),
            )
            cur.execute(
                """INSERT INTO inspection_reports
                       (reportID, userID, targetID, targetType,
                        verificationStatus, inspectionResult, irTimestamp)
                   VALUES (902, 9, 901, 'geospatial_log',
                           'Verified', 'Green', %s)""",
                (self.as_of,),
            )
        self.db.commit()

        filters = {"display_sector": "retail"}
        registry_where, registry_params = registry_sql("o", filters)
        with self.db.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) AS total FROM official_registry o WHERE 1=1"
                + registry_where,
                registry_params,
            )
            self.assertEqual(cur.fetchone()["total"], 1)

        app = Flask(__name__)
        original_mysql = routes.mysql
        routes.mysql = SimpleNamespace(connection=self.db)
        reset_ladder_column_cache()

        def overview(query):
            with app.test_request_context(
                f"/api/analytics/barangay-overview?{query}"
            ):
                response, status = routes.get_barangay_overview.__wrapped__()
            self.assertEqual(status, 200)
            return response.get_json()

        try:
            all_data = overview("")
            retail_data = overview("display_sector=retail")
        finally:
            routes.mysql = original_mysql
            reset_ladder_column_cache()

        self.assertEqual(all_data["overall"]["registry_total"], 2)
        self.assertEqual(retail_data["overall"]["registry_total"], 1)
        self.assertEqual(
            retail_data["overall"]["pins"],
            all_data["overall"]["pins"],
        )
        self.assertEqual(
            retail_data["overall"]["inspections"],
            all_data["overall"]["inspections"],
        )
        self.assertEqual(
            all_data["display_sectors"],
            [
                {"value": "retail", "label": "Retail"},
                {"value": "food_drink", "label": "Food and drink"},
            ],
        )

    def test_barangay_overview_primary_psic_filter_reconciles_under_full_group_by(self):
        from flask import Flask

        from api.analytics import routes
        with self.db.cursor() as cur:
            cur.execute(
                "SET SESSION sql_mode='STRICT_TRANS_TABLES,ONLY_FULL_GROUP_BY'"
            )
            cur.execute(
                """INSERT INTO display_sector
                       (normalized_major_type, display_sector_key,
                        display_sector_label, sort_order, is_active)
                   VALUES
                       ('retailtrade', 'retail', 'Retail', 1, 1),
                       ('educationhealth', 'education_health_other_services',
                        'Education, health and other services', 2, 1)"""
            )
            cur.execute(
                "INSERT INTO psic_active_version (singleton_id, source_version) "
                "VALUES (1, 'primary-filter-version')"
            )
            cur.executemany(
                """INSERT INTO psic_lines
                       (psic_line_id, source_version, source_row_number,
                        normalized_line_of_business, normalized_major_type,
                        major_type_clean, line_of_business)
                   VALUES (%s, 'primary-filter-version', %s, %s,
                           'retailtrade', 'Retail trade', %s)""",
                [
                    (1101, 1, "retailsellingingroceries", "Retail selling in groceries"),
                    (1102, 2, "retailsellinginsarisaristores",
                     "Retail selling in sari-sari stores"),
                    (1103, 3, "barbershopactivities", "Barber shop activities"),
                ],
            )
            cur.executemany(
                """INSERT INTO official_registry
                       (businessID, barangayID, businessName, lineOfBusiness)
                   VALUES (%s, 1, %s, %s)""",
                [
                    ("LOB-GROCERY", "Grocery", "Retail selling in groceries"),
                    (
                        "LOB-GROCERY-COMBO",
                        "Grocery combo",
                        "Retail selling in groceries, Retail selling in sari-sari stores",
                    ),
                    (
                        "LOB-SARI-COMBO",
                        "Sari-sari combo",
                        "Retail selling in sari-sari stores, Retail selling in groceries",
                    ),
                ],
            )
            cur.executemany(
                """INSERT INTO official_registry
                       (businessID, barangayID, businessName, lineOfBusiness)
                   VALUES (%s, 1, %s, 'Barber shop activities')""",
                [
                    (f"LOB-BARBER-{index}", f"Barber shop {index}")
                    for index in range(1, 9)
                ],
            )
            cur.executemany(
                """INSERT INTO registry_sector_map
                       (normalized_line_of_business, source_version,
                        match_status, primary_psic_line_id,
                        display_sector_key, display_sector_label)
                   VALUES (%s, 'primary-filter-version', %s, %s, %s, %s)""",
                [
                    ("retailsellingingroceries", "matched", 1101, "retail", "Retail"),
                    (
                        "retailsellingingroceriesretailsellinginsarisaristores",
                        "combo",
                        1101,
                        "retail",
                        "Retail",
                    ),
                    (
                        "retailsellinginsarisaristoresretailsellingingroceries",
                        "combo",
                        1102,
                        "retail",
                        "Retail",
                    ),
                    ("barbershopactivities", "matched", 1103,
                     "education_health_other_services",
                     "Education, health and other services"),
                ],
            )
            cur.execute(
                """INSERT INTO geospatial_logs
                       (logID, barangayID, detectedName, detectedDate, flagColor,
                        latitude, longitude, source)
                   VALUES (1103, 1, 'LOB-independent pin', %s, 'Green',
                           13.9667, 121.1167, 'manual')""",
                (self.as_of,),
            )
            cur.execute(
                """INSERT INTO inspection_reports
                       (reportID, userID, targetID, targetType,
                        verificationStatus, inspectionResult, irTimestamp)
                   VALUES (1104, 9, 1103, 'geospatial_log',
                           'Verified', 'Green', %s)""",
                (self.as_of,),
            )
        self.db.commit()

        app = Flask(__name__)
        original_mysql = routes.mysql
        routes.mysql = SimpleNamespace(connection=self.db)
        reset_ladder_column_cache()

        def overview(query):
            with app.test_request_context(
                f"/api/analytics/barangay-overview?{query}"
            ):
                response, status = routes.get_barangay_overview.__wrapped__()
            self.assertEqual(status, 200)
            return response.get_json()

        try:
            all_data = overview("")
            sector_data = overview("display_sector=retail")
            filtered_data = overview(
                "display_sector=retail"
                "&line_of_business_key=retailsellingingroceries"
            )
            barber_data = overview(
                "line_of_business_key=barbershopactivities"
            )
        finally:
            routes.mysql = original_mysql
            reset_ladder_column_cache()

        self.assertEqual(sector_data["overall"]["registry_total"], 3)
        self.assertEqual(filtered_data["overall"]["registry_total"], 2)
        self.assertEqual(all_data["overall"]["registry_total"], 11)
        self.assertEqual(barber_data["overall"]["registry_total"], 8)
        self.assertEqual(
            sum(row["registry_total"] for row in barber_data["barangays"]), 8
        )
        self.assertEqual(
            barber_data["overall"]["registry"]["display_sector"],
            [{
                "value": "education_health_other_services",
                "label": "Education, health and other services",
                "short_label": "Education, health and other services",
                "count": 8,
            }],
        )
        options = sector_data["line_of_business_options"]
        counts_by_value = {option["value"]: option["count"] for option in options}
        self.assertEqual(counts_by_value, {
            "retailsellingingroceries": 2,
            "retailsellinginsarisaristores": 1,
        })
        self.assertEqual(sum(counts_by_value.values()), 3)
        self.assertEqual(
            filtered_data["overall"]["pins"],
            sector_data["overall"]["pins"],
        )
        self.assertEqual(
            filtered_data["overall"]["inspections"],
            sector_data["overall"]["inspections"],
        )
        self.assertEqual(
            barber_data["overall"]["pins"],
            all_data["overall"]["pins"],
        )
        self.assertEqual(
            barber_data["overall"]["inspections"],
            all_data["overall"]["inspections"],
        )
        self.assertEqual(
            next(
                option for option in options
                if option["value"] == "retailsellingingroceries"
            )["label"],
            "Retail Selling In Groceries (2)",
        )

    def test_psic_loader_dry_run_reads_mysql_without_psic_migration_tables(self):
        from contextlib import redirect_stdout
        from io import StringIO
        from pathlib import Path
        from tempfile import TemporaryDirectory

        from openpyxl import Workbook

        from scripts.load_psic_sector_master import load_master, _print_result

        with self.db.cursor() as cur:
            cur.executemany(
                """INSERT INTO official_registry
                       (businessID, barangayID, businessName, lineOfBusiness)
                   VALUES (%s, 1, %s, %s)""",
                [
                    ("DRY-1", "Retail 1", "Retail activity"),
                    ("DRY-2", "Retail 2", "Retail activity"),
                    ("DRY-3", "Food", "Food activity"),
                    ("DRY-4", "Combo", "Retail activity, Food activity"),
                    ("DRY-5", "Unknown", "Unlisted activity"),
                ],
            )
            for table in (
                "registry_sector_map_secondary",
                "registry_sector_review_queue",
                "registry_sector_map",
                "psic_active_version",
                "psic_lines",
                "display_sector",
            ):
                cur.execute(f"DROP TABLE {table}")
        self.db.commit()

        try:
            with TemporaryDirectory() as temp_dir:
                workbook_path = Path(temp_dir) / "psic.xlsx"
                workbook = Workbook()
                sheet = workbook.active
                sheet.append(
                    ["No.", "Major Type", "Division", "Group", "Class",
                     "Line of Business", "Total"]
                )
                sheet.append([1, "RETAIL TRADE", "G", "G1", "G1.1", "Retail activity", 0])
                sheet.append([2, "FOOD SERVICE ACTIVITIES", "I", "I1", "I1.1", "Food activity", 0])
                workbook.save(workbook_path)
                workbook.close()

                result = load_master(
                    workbook_path,
                    dry_run=True,
                    connection=self.db,
                )
                output = StringIO()
                with redirect_stdout(output):
                    _print_result(result, dry_run=True)

            self.assertEqual(result["registry_rows"], 5)
            self.assertEqual(result["registry_values"], 4)
            self.assertEqual(
                result["outcomes"],
                {"matched": 2, "combo": 1, "unmatched": 1},
            )
            self.assertEqual(
                result["display_sector_rows"],
                {
                    "Retail": 3,
                    "Food and drink": 1,
                    "Needs classification": 1,
                },
            )
            self.assertEqual(
                result["combo_values"][0]["sectors"],
                ["Retail", "Food and drink"],
            )
            self.assertIn("DRY RUN — no database writes performed", output.getvalue())
            self.assertIn("matched: 2", output.getvalue())
            self.assertIn("combo: 1", output.getvalue())
            self.assertIn("unmatched: 1", output.getvalue())
            self.assertIn("Retail: 3", output.getvalue())
            self.assertIn(
                "Retail activity, Food activity (rows=1; primary=Retail): Retail, Food and drink",
                output.getvalue(),
            )
            self.assertIn("TOTAL: 5", output.getvalue())
            with self.db.cursor() as cur:
                cur.execute("SELECT COUNT(*) AS total FROM official_registry")
                self.assertEqual(cur.fetchone()["total"], 5)
                cur.execute("SHOW TABLES LIKE 'psic_lines'")
                self.assertIsNone(cur.fetchone())
                cur.execute("SHOW TABLES LIKE 'display_sector'")
                self.assertIsNone(cur.fetchone())
        finally:
            with self.db.cursor() as cur:
                for statement in (
                    """CREATE TABLE display_sector (
                        normalized_major_type VARCHAR(255) PRIMARY KEY,
                        display_sector_key VARCHAR(64), display_sector_label VARCHAR(100),
                        sort_order SMALLINT NOT NULL DEFAULT 0,
                        is_active TINYINT(1) NOT NULL DEFAULT 1
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci""",
                    """CREATE TABLE registry_sector_map (
                        normalized_line_of_business VARCHAR(500) PRIMARY KEY,
                        raw_line_of_business VARCHAR(500), source_version VARCHAR(80),
                        display_sector_key VARCHAR(64), display_sector_label VARCHAR(100),
                        match_status ENUM('matched','combo','ambiguous','unmatched') NOT NULL,
                        primary_psic_line_id BIGINT NULL,
                        candidate_count SMALLINT UNSIGNED NOT NULL DEFAULT 0
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci""",
                    """CREATE TABLE registry_sector_map_secondary (
                        normalized_line_of_business VARCHAR(500) NOT NULL,
                        psic_line_id BIGINT NOT NULL,
                        PRIMARY KEY (normalized_line_of_business, psic_line_id)
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci""",
                    """CREATE TABLE registry_sector_review_queue (
                        normalized_line_of_business VARCHAR(500) PRIMARY KEY,
                        raw_line_of_business VARCHAR(500) NOT NULL,
                        review_status ENUM('ambiguous','unmatched') NOT NULL,
                        candidate_count SMALLINT UNSIGNED NOT NULL DEFAULT 0,
                        first_seen_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        last_seen_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        reviewed_at DATETIME NULL, reviewed_by VARCHAR(255) NULL
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci""",
                    """CREATE TABLE psic_active_version (
                        singleton_id TINYINT PRIMARY KEY,
                        source_version VARCHAR(80) NOT NULL
                    ) ENGINE=InnoDB""",
                    """CREATE TABLE psic_lines (
                        psic_line_id BIGINT PRIMARY KEY,
                        source_version VARCHAR(80) NOT NULL,
                        source_row_number INT NOT NULL,
                        normalized_line_of_business VARCHAR(500) NOT NULL,
                        normalized_major_type VARCHAR(255) NOT NULL,
                        major_type_clean VARCHAR(255) NOT NULL,
                        line_of_business VARCHAR(500) NOT NULL
                    ) ENGINE=InnoDB""",
                ):
                    cur.execute(statement)
            self.db.commit()

    def test_sector_sync_resolves_same_sector_duplicates_and_preserves_review_history(self):
        from pathlib import Path

        from api.analytics.sector_mapping import (
            normalize_sector_text,
            sync_registry_sector_values,
        )

        migration = (
            Path(__file__).resolve().parents[1]
            / "migrations"
            / "20261029_02_sector_review_queue_resolved.sql"
        )
        with self.db.cursor() as cur:
            cur.execute(migration.read_text(encoding="utf-8"))
            cur.execute(
                """INSERT INTO psic_active_version (singleton_id, source_version)
                   VALUES (1, 'fixture-version')"""
            )
            cur.executemany(
                """INSERT INTO display_sector
                       (normalized_major_type, display_sector_key,
                        display_sector_label, sort_order, is_active)
                   VALUES (%s, %s, %s, 1, 1)""",
                [
                    (normalize_sector_text("MANUFACTURING"), "manufacturing", "Manufacturing"),
                    (normalize_sector_text("RETAIL TRADE"), "retail", "Retail"),
                    (normalize_sector_text("FOOD SERVICE ACTIVITIES"), "food_drink", "Food and drink"),
                ],
            )
            cur.executemany(
                """INSERT INTO psic_lines
                       (psic_line_id, source_version, source_row_number,
                        normalized_line_of_business, normalized_major_type,
                        major_type_clean, line_of_business)
                   VALUES (%s, 'fixture-version', %s, %s, %s, %s, %s)""",
                [
                    (1, 10, "duplicateactivity", normalize_sector_text("MANUFACTURING"),
                     "MANUFACTURING", "Duplicate activity"),
                    (2, 20, "duplicateactivity", normalize_sector_text("MANUFACTURING"),
                     "MANUFACTURING", "Duplicate-activity"),
                    (3, 30, "crosssectorduplicate", normalize_sector_text("RETAIL TRADE"),
                     "RETAIL TRADE", "Cross-sector duplicate"),
                    (4, 40, "crosssectorduplicate", normalize_sector_text("FOOD SERVICE ACTIVITIES"),
                     "FOOD SERVICE ACTIVITIES", "Cross-sector-duplicate"),
                ],
            )
            cur.execute(
                """INSERT INTO registry_sector_review_queue
                       (normalized_line_of_business, raw_line_of_business,
                        review_status, candidate_count, reviewed_at, reviewed_by)
                   VALUES ('duplicateactivity', 'Duplicate activity',
                           'ambiguous', 2, '2026-10-28 12:00:00', 'fixture-reviewer')"""
            )
            outcomes = sync_registry_sector_values(
                cur,
                ["Duplicate activity", "Cross-sector duplicate"],
            )
        self.db.commit()

        self.assertEqual(outcomes, {"matched": 1, "ambiguous": 1})
        with self.db.cursor() as cur:
            cur.execute(
                """SELECT review_status, reviewed_at, reviewed_by
                   FROM registry_sector_review_queue
                   WHERE normalized_line_of_business = 'duplicateactivity'"""
            )
            history = cur.fetchone()
            self.assertEqual(history["review_status"], "resolved")
            self.assertEqual(str(history["reviewed_at"]), "2026-10-28 12:00:00")
            self.assertEqual(history["reviewed_by"], "fixture-reviewer")
            cur.execute(
                """SELECT match_status, primary_psic_line_id, candidate_count
                   FROM registry_sector_map
                   WHERE normalized_line_of_business = 'duplicateactivity'"""
            )
            resolved = cur.fetchone()
            self.assertEqual(resolved["match_status"], "matched")
            self.assertEqual(resolved["primary_psic_line_id"], 1)
            self.assertEqual(resolved["candidate_count"], 2)
            cur.execute(
                """SELECT match_status FROM registry_sector_map
                   WHERE normalized_line_of_business = 'crosssectorduplicate'"""
            )
            self.assertEqual(cur.fetchone()["match_status"], "ambiguous")
