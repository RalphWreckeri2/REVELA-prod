"""Real MySQL regressions; run with scripts/run_registry_sync_audit.py.

Only that runner can provide the fresh server connection factory. Ordinary test
discovery skips these tests rather than using application database credentials.
"""

from contextlib import ExitStack, contextmanager
import csv
from datetime import date, datetime
from io import BytesIO, StringIO
import unittest
from unittest.mock import patch

from api.flags import service as flags
from api.inspections import service as inspections
from api.models import app_settings, geospatial
from api.models.inspection_lifecycle_events import log_inspection_event
from api.registry import places_resolver, service as registry
from api.registry.history_schema import ALL_HISTORY_COLUMNS
from api.analytics import routes as analytics


connect_to_disposable_mysql = None


class IsolatedMySQL:
    def __init__(self, connection):
        self.connection = connection

    @property
    def connect(self):
        return connect_to_disposable_mysql()


class RegistryInspectionSyncTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if connect_to_disposable_mysql is None:
            raise unittest.SkipTest("Use scripts/run_registry_sync_audit.py (disposable MySQL only)")
        cls.db = connect_to_disposable_mysql()
        statements = [
            """CREATE TABLE barangays (barangayID INT PRIMARY KEY, barangayName VARCHAR(80))""",
            """CREATE TABLE users (userID INT PRIMARY KEY, fullName VARCHAR(80), userRole VARCHAR(30), isActive INT DEFAULT 1)""",
            """CREATE TABLE official_registry (
                fixtureRowID INT AUTO_INCREMENT PRIMARY KEY,
                businessID VARCHAR(50) NOT NULL UNIQUE, barangayID INT NOT NULL,
                businessName VARCHAR(120), businessType VARCHAR(80), lineOfBusiness VARCHAR(120),
                businessAddress TEXT, applicationStatus VARCHAR(30), lastRenewalDate DATETIME,
                businessSize VARCHAR(30), registrationType VARCHAR(30),
                latitude DECIMAL(10,8), longitude DECIMAL(11,8), coordSource VARCHAR(24),
                placeID VARCHAR(255), placeIDKind VARCHAR(32), coordFetchedAt DATETIME,
                matchScore DECIMAL(4,3), matchStatus VARCHAR(24), resolveKey CHAR(40)
            ) ENGINE=InnoDB""",
            """CREATE TABLE geospatial_logs (
                logID INT AUTO_INCREMENT PRIMARY KEY, businessID VARCHAR(50), barangayID INT,
                reportID INT, detectedName VARCHAR(120), latitude DECIMAL(10,8), longitude DECIMAL(11,8),
                flagColor VARCHAR(30), nearestLandmark TEXT, notes TEXT,
                placeID VARCHAR(255), placeTypes JSON, reportedByUserID INT,
                noticeLevel INT DEFAULT 0, detectedDate DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (businessID) REFERENCES official_registry(businessID)
            ) ENGINE=InnoDB""",
            """CREATE TABLE inspection_reports (
                reportID INT AUTO_INCREMENT PRIMARY KEY, targetID INT, targetType VARCHAR(30), userID INT,
                inspectionResult VARCHAR(30), verificationStatus VARCHAR(30), wasReassigned INT DEFAULT 0,
                noticeLevel INT DEFAULT 0, remarks TEXT, photoPath TEXT, nearestLandmark TEXT,
                verifiedLatitude DECIMAL(10,8), verifiedLongitude DECIMAL(11,8), verifiedAccuracy DECIMAL(8,2),
                irTimestamp DATETIME(6), submittedAt DATETIME(6), submissionReceivedAt DATETIME(6),
                deadline DATETIME, resolutionTime INT,
                FOREIGN KEY (targetID) REFERENCES geospatial_logs(logID)
            ) ENGINE=InnoDB""",
            """CREATE TABLE inspection_lifecycle_events (
                eventID INT AUTO_INCREMENT PRIMARY KEY, reportID INT NOT NULL, targetLogID INT NOT NULL,
                cycleID INT, eventType VARCHAR(30), actorUserID INT, assignedToUserID INT,
                flagColorAtEvent VARCHAR(50), inspectionResult VARCHAR(50), remarks VARCHAR(255),
                eventTimestamp DATETIME(6), KEY idx_target (targetLogID)
            ) ENGINE=InnoDB""",
            """CREATE TABLE places_api_usage (
                usageDate DATE NOT NULL, kind VARCHAR(32) NOT NULL, requestCount INT NOT NULL DEFAULT 0,
                PRIMARY KEY (usageDate, kind)
            ) ENGINE=InnoDB""",
        ]
        columns = []
        for name, kind, nullable, default, extra in ALL_HISTORY_COLUMNS:
            column = f"`{name}` {kind} {'NULL' if nullable == 'YES' else 'NOT NULL'}"
            if default:
                column += f" DEFAULT {default}"
            if extra == "auto_increment":
                column += " AUTO_INCREMENT PRIMARY KEY"
            columns.append(column)
        statements.append("CREATE TABLE registry_pin_history (" + ",".join(columns) + ") ENGINE=InnoDB")
        with cls.db.cursor() as cursor:
            for statement in statements:
                cursor.execute(statement)
            cursor.execute("INSERT INTO barangays VALUES (1, 'Barangay I'), (2, 'Barangay II')")
            cursor.execute("INSERT INTO users VALUES (9, 'Isolated Inspector', 'Inspector', 1)")
        cls.db.commit()

    @classmethod
    def tearDownClass(cls):
        cls.db.close()

    def setUp(self):
        self.db.rollback()
        with self.db.cursor() as cursor:
            for table in ("inspection_lifecycle_events", "inspection_reports", "geospatial_logs",
                          "official_registry", "registry_pin_history", "places_api_usage"):
                cursor.execute(f"DELETE FROM {table}")
        self.db.commit()
        self.mysql = IsolatedMySQL(self.db)
        self.guards = ExitStack()
        self.addCleanup(self.guards.close)
        for module in (registry, flags, inspections, places_resolver, geospatial, app_settings):
            self.guards.enter_context(patch.object(module, "mysql", self.mysql))
        self.guards.enter_context(patch("api.notifications.hub.publish_to_admins"))
        self.guards.enter_context(patch.object(registry, "_log_registry_places_summary"))
        self.resolver = self.guards.enter_context(patch.object(
            registry, "_resolve_location", side_effect=AssertionError("Unexpected Google resolution in isolated test"),
        ))

    def query(self, sql, params=(), *, db=None):
        with (db or self.db).cursor() as cursor:
            cursor.execute(sql, params)
            return cursor.fetchall() if cursor.description else cursor.lastrowid

    @contextmanager
    def other_transaction(self):
        other = connect_to_disposable_mysql()
        previous = self.mysql.connection
        self.mysql.connection = other
        try:
            yield other
        finally:
            self.mysql.connection = previous
            other.close()

    def seed(self, status="Active", color="Green", verification="Assigned", result=None,
             business_id="AUDIT-001", *, verified_event=False):
        name = f"ISOLATED SHOP {business_id}"
        renewal = f"{date.today().year}-01-01"
        key = places_resolver.compute_resolve_key(name, "1 MAIN STREET", 1)
        self.query("""INSERT INTO official_registry
            (businessID, barangayID, businessName, businessType, lineOfBusiness, businessAddress,
             applicationStatus, lastRenewalDate, businessSize, registrationType, latitude, longitude,
             coordSource, matchStatus, resolveKey)
            VALUES (%s,1,%s,'RETAIL','GROCERY','1 MAIN STREET',%s,%s,'SMALL','RENEWAL',
                    13.9667,121.1167,'csv',NULL,%s)""", (business_id, name, status, renewal, key))
        log_id = self.query("""INSERT INTO geospatial_logs
            (businessID,barangayID,detectedName,latitude,longitude,flagColor,noticeLevel,notes,nearestLandmark)
            VALUES (%s,1,%s,13.9667,121.1167,%s,2,'Keep map remarks','1 MAIN STREET')""",
                            (business_id, name, color))
        report_id = self.query("""INSERT INTO inspection_reports
            (targetID,targetType,userID,inspectionResult,verificationStatus,noticeLevel,remarks,photoPath,
             nearestLandmark,verifiedLatitude,verifiedLongitude,verifiedAccuracy,irTimestamp,submittedAt,
             submissionReceivedAt,deadline,resolutionTime)
            VALUES (%s,'geospatial_log',9,%s,%s,2,'Keep field remarks','["/isolated/photo.jpg"]',
                    '13.9667,121.1167',13.9667,121.1167,8.25,'2026-01-01 00:00:00',
                    '2026-02-01 00:00:00','2026-02-01 00:00:01','2026-12-31',37)""",
                               (log_id, result, verification))
        with self.db.cursor() as cursor:
            cycle = log_inspection_event(cursor, report_id, log_id, "dispatched", assigned_to_user_id=9)
            if verified_event:
                log_inspection_event(cursor, report_id, log_id, "verified", inspection_result=result, cycle_id=cycle)
        self.db.commit()
        return business_id, log_id, report_id, cycle

    def frame_row(self, business_id="AUDIT-001", **changes):
        row = {
            "Business ID": business_id, "Business Name": f"ISOLATED SHOP {business_id}",
            "Barangay": "Barangay I", "Business Type": "Retail", "Line of Business": "Grocery",
            "Business Address": "1 Main Street", "Status": "Active",
            "Last Renewal Date": f"{date.today().year}-01-01", "Size of Business": "Small",
            "Registration Type": "Renewal",
        }
        row.update(changes)
        return row

    def import_file(self, *rows):
        stream = StringIO()
        writer = csv.DictWriter(stream, fieldnames=list(dict.fromkeys(key for row in rows for key in row)))
        writer.writeheader()
        writer.writerows(rows)
        return BytesIO(stream.getvalue().encode())

    def sync(self, *rows, upload=False):
        summary, error = (registry.upload_registry if upload else registry.sync_registry)(
            self.import_file(*rows), ".csv",
        )
        self.assertIsNone(error, error)
        return summary

    def snapshot(self):
        return {
            table: self.query(f"SELECT * FROM {table} ORDER BY 1")
            for table in ("official_registry", "geospatial_logs", "inspection_reports", "inspection_lifecycle_events")
        }

    def assert_inspection_unchanged(self, before):
        after = self.snapshot()
        for table in ("inspection_reports", "inspection_lifecycle_events"):
            self.assertEqual(after[table], before[table], table)
        self.assertEqual([r["fixtureRowID"] for r in after["official_registry"]],
                         [r["fixtureRowID"] for r in before["official_registry"]])
        self.assertEqual([r["logID"] for r in after["geospatial_logs"]],
                         [r["logID"] for r in before["geospatial_logs"]])

    def assert_color(self, log_id, expected):
        self.assertEqual(self.query("SELECT flagColor FROM geospatial_logs WHERE logID=%s", (log_id,))[0]["flagColor"], expected)
        expression = analytics._effective_flag_color_sql("g")
        analytics_color = self.query(f"SELECT {expression} AS color FROM geospatial_logs g WHERE g.logID=%s", (log_id,))
        self.assertEqual(analytics_color[0]["color"], expected, "Analytics must agree with the map")
        result, error = flags.get_flags(per_page=100)
        self.assertIsNone(error, error)
        actual = next(row for row in result["data"] if row["logID"] == log_id)
        self.assertEqual(actual["flagColor"], expected, "Map read must agree with stored flag")
        filtered, error = flags.get_flags(color=expected, per_page=100)
        self.assertIsNone(error, error)
        self.assertIn(log_id, [r["logID"] for r in filtered["data"]])
        for color in {"Green", "Yellow", "Red", "Orange", "Black", "Purple"} - {expected}:
            result, error = flags.get_flags(color=color, per_page=100)
            self.assertIsNone(error, error)
            self.assertNotIn(log_id, [r["logID"] for r in result["data"]], f"Wrong {color} filter")

    def test_active_inspection_and_completed_reports_keep_all_owned_data(self):
        for verification in ("Assigned", "Reassigned", "In Progress", "Submitted", "Verified"):
            with self.subTest(verification=verification):
                business_id, log_id, _, _ = self.seed(verification=verification, business_id=f"AUDIT-{verification}")
                before = self.snapshot()
                summary = self.sync(self.frame_row(business_id, **{"Size of Business": "Large"}))
                self.assertEqual(summary["updated"], 1)
                self.assertEqual(self.query("SELECT businessSize FROM official_registry WHERE businessID=%s", (business_id,))[0]["businessSize"], "LARGE")
                self.assert_inspection_unchanged(before)
                self.assert_color(log_id, "Green")

    def test_verified_black_and_purple_are_not_cleared_by_unchanged_registry(self):
        for color in ("Black", "Purple"):
            with self.subTest(color=color):
                business_id, log_id, _, _ = self.seed(color=color, verification="Verified", result=color, business_id=f"AUDIT-{color}")
                before = self.snapshot()
                summary = self.sync(self.frame_row(business_id))
                self.assertEqual(summary["unchanged"], 1)
                self.assert_inspection_unchanged(before)
                self.assert_color(log_id, color)

    def test_verified_terminal_finding_and_imported_permit_are_separate(self):
        for color in ("Black", "Purple"):
            with self.subTest(color=color):
                business_id, log_id, _, _ = self.seed(status="Expired", color=color, verification="Verified", result=color, business_id=f"AUDIT-{color}")
                before = self.snapshot()
                self.sync(self.frame_row(business_id, Status="Active"))
                self.assertEqual(self.query("SELECT applicationStatus FROM official_registry WHERE businessID=%s", (business_id,))[0]["applicationStatus"], "Active")
                self.assert_inspection_unchanged(before)
                self.assert_color(log_id, color)

    def test_registry_derived_black_and_purple_can_change_with_permit(self):
        for status, color in (("Revoked", "Black"), ("Closed", "Purple")):
            with self.subTest(status=status):
                business_id, log_id, _, _ = self.seed(status, color, business_id=f"AUDIT-{color}")
                before = self.snapshot()
                self.sync(self.frame_row(business_id))
                self.assert_inspection_unchanged(before)
                self.assert_color(log_id, "Green")

    def test_verified_orange_survives_expired_but_valid_renewal_changes_compliance(self):
        for status, expected in (("Expired", "Orange"), ("Active", "Green"), ("Pending", "Yellow"), ("Revoked", "Black"), ("Closed", "Purple")):
            with self.subTest(status=status):
                business_id, log_id, _, _ = self.seed("Expired", "Orange", "Verified", "Orange", f"AUDIT-{status}")
                before = self.snapshot()
                self.sync(self.frame_row(business_id, Status=status))
                self.assert_inspection_unchanged(before)
                self.assert_color(log_id, expected)

    def test_new_year_expiration_does_not_complete_ongoing_inspection(self):
        business_id, log_id, _, _ = self.seed()
        before = self.snapshot()
        self.sync(self.frame_row(business_id, **{"Last Renewal Date": f"{date.today().year-1}-01-01"}))
        self.assert_inspection_unchanged(before)
        self.assert_color(log_id, "Red")

    def test_verified_finding_survives_redispatch_using_persisted_history(self):
        for color, status in (("Black", "Active"), ("Purple", "Active"), ("Orange", "Expired")):
            with self.subTest(color=color):
                business_id, log_id, _, _ = self.seed(status, color, "Verified", color, f"AUDIT-{color}", verified_event=True)
                result, error = inspections.assign_inspection(log_id, 9, None, 1)
                self.assertIsNone(error, error)
                self.assertEqual(result["status"], "Reassigned")
                before = self.snapshot()
                self.sync(self.frame_row(business_id, Status=status))
                self.assert_inspection_unchanged(before)
                self.assert_color(log_id, color)

    def test_explicit_admin_color_change_is_not_undone_by_old_verified_terminal_result(self):
        business_id, log_id, _, _ = self.seed(color="Purple", verification="Verified", result="Purple", verified_event=True)
        ok, error = flags.update_flag_color(log_id, "Green")
        self.assertTrue(ok, error)
        self.sync(self.frame_row(business_id))
        self.assert_color(log_id, "Green")

    def test_same_file_twice_no_duplicate_records_or_inspection_side_effects(self):
        business_id, log_id, _, _ = self.seed()
        before = self.snapshot()
        first = self.sync(self.frame_row(business_id, **{"Size of Business": "Large"}))
        second = self.sync(self.frame_row(business_id, **{"Size of Business": "Large"}))
        self.assertEqual((first["updated"], second["updated"], second["unchanged"]), (1, 0, 1))
        self.assert_inspection_unchanged(before)
        self.assert_color(log_id, "Green")

    def test_business_missing_from_import_is_untouched(self):
        self.seed()
        self.seed(business_id="AUDIT-OTHER")
        before = self.snapshot()
        self.sync(self.frame_row("AUDIT-OTHER"))
        self.assertEqual(self.snapshot(), before)

    def test_missing_and_duplicate_ids_are_skipped_first_valid_row_wins(self):
        business_id, _, _, _ = self.seed()
        before = self.snapshot()
        summary = self.sync(
            self.frame_row(business_id, **{"Size of Business": "Large"}),
            self.frame_row(f"#  {business_id.lower()}", **{"Size of Business": "Micro"}),
            self.frame_row(""),
        )
        self.assertEqual((summary["updated"], summary["inserted"], summary["skipped"]), (1, 0, 2))
        self.assertEqual(self.query("SELECT businessSize FROM official_registry")[0]["businessSize"], "LARGE")
        self.assert_inspection_unchanged(before)

    def test_upload_endpoint_skips_existing_business_instead_of_syncing_it(self):
        business_id, _, _, _ = self.seed(color="Black", verification="Verified", result="Black")
        before = self.snapshot()
        result = self.sync(self.frame_row(business_id, **{"Size of Business": "Large"}), upload=True)
        self.assertEqual((result["inserted"], result["skipped"]), (0, 1))
        self.assertEqual(self.snapshot(), before)

    def submit(self, ids, result="Orange"):
        _, log_id, report_id, cycle = ids
        result, error = inspections.submit_inspection(
            log_id, 9, result, notice_level=2, notes="Offline field notes",
            photo_url='["/isolated/offline-photo.jpg"]', verified_lat=13.9667,
            verified_lng=121.1167, verified_accuracy=8.25, report_id=report_id,
            assignment_cycle_id=cycle, submitted_at=datetime(2026, 10, 14, 2, 46),
        )
        self.assertIsNone(error, error)
        return result

    def test_offline_submission_after_import_keeps_identity_evidence_and_retry_idempotency(self):
        ids = self.seed()
        self.sync(self.frame_row(ids[0], Status="Expired"))
        submitted = self.submit(ids)
        before_retry = self.snapshot()
        retry = self.submit(ids)
        self.assertEqual(submitted["reportID"], ids[2])
        self.assertEqual(submitted["status"], "Submitted")
        self.assertTrue(retry["alreadyAccepted"])
        self.assertEqual(self.snapshot(), before_retry)
        self.assertEqual(before_retry["inspection_reports"][0]["remarks"], "Offline field notes")
        self.assert_color(ids[1], "Red")  # Submitted is not admin-verified.
        result, error = inspections.verify_inspection(ids[2], 1)
        self.assertIsNone(error, error)
        self.assertEqual(result["status"], "Verified")
        self.assert_color(ids[1], "Orange")

    def test_submission_can_commit_while_import_is_updating_registry(self):
        ids = self.seed()
        original = registry._sync_flag_color

        def submit_before_color_sync(*args, **kwargs):
            with self.other_transaction():
                self.submit(ids)
            return original(*args, **kwargs)

        with patch.object(registry, "_sync_flag_color", side_effect=submit_before_color_sync):
            self.sync(self.frame_row(ids[0], Status="Expired"))
        report = self.query("SELECT * FROM inspection_reports WHERE reportID=%s", (ids[2],))[0]
        self.assertEqual((report["verificationStatus"], report["remarks"]), ("Submitted", "Offline field notes"))
        self.assert_color(ids[1], "Red")

    def test_verification_committed_after_import_snapshot_is_not_overwritten(self):
        ids = self.seed("Expired", "Red", "Submitted", "Orange")
        original = registry._sync_flag_color

        def verify_before_color_sync(*args, **kwargs):
            with self.other_transaction():
                result, error = inspections.verify_inspection(ids[2], 1)
                self.assertIsNone(error, error)
                self.assertEqual(result["status"], "Verified")
            return original(*args, **kwargs)

        with patch.object(registry, "_sync_flag_color", side_effect=verify_before_color_sync):
            self.sync(self.frame_row(ids[0], Status="Expired"))
        self.assert_color(ids[1], "Orange")

    def test_failed_import_rolls_back_all_registry_writes(self):
        ids = self.seed()
        before = self.snapshot()
        with patch.object(registry, "_sync_flag_color", side_effect=RuntimeError("isolated failure")):
            stream = BytesIO(("Business ID,Business Name,Barangay,Status\n"
                              f"{ids[0]},ISOLATED SHOP {ids[0]},Barangay I,Expired\n").encode())
            summary, error = registry.sync_registry(stream, ".csv")
        self.assertIsNone(summary)
        self.assertIn("isolated failure", error)
        # Subsequent work on this request connection must not commit a failed import.
        self.db.commit()
        self.assertEqual(self.snapshot(), before)

    def test_quota_reservation_cannot_commit_a_partial_import(self):
        ids = self.seed()
        self.seed(business_id="AUDIT-RESOLVE")
        self.query("UPDATE official_registry SET coordSource=NULL, resolveKey=NULL WHERE businessID='AUDIT-RESOLVE'")
        self.db.commit()
        before = self.snapshot()

        def reserve_then_fail(*_args, **_kwargs):
            self.assertTrue(places_resolver.reserve_call("imp_ts", 100, 100))
            raise RuntimeError("isolated resolver failure after reservation")

        with patch.object(registry, "_resolve_location", side_effect=reserve_then_fail):
            summary, error = registry.sync_registry(self.import_file(
                self.frame_row(ids[0], **{"Size of Business": "Large"}),
                self.frame_row("AUDIT-RESOLVE"),
            ), ".csv")
        self.assertIsNone(summary)
        self.assertIn("isolated resolver failure", error)
        self.db.commit()
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.query("SELECT SUM(requestCount) AS total FROM places_api_usage")[0]["total"], 2)

    def test_legacy_geocode_reservation_owns_its_commit(self):
        self.seed()
        before = self.snapshot()
        self.query("UPDATE official_registry SET businessSize='LARGE'")
        with patch.object(registry.quota_settings, "cap", return_value=100):
            self.assertTrue(registry._reserve_geocode_call())
        self.db.rollback()
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.query("SELECT SUM(requestCount) AS total FROM places_api_usage")[0]["total"], 2)

    def test_cold_quota_settings_bootstrap_cannot_commit_import_records(self):
        self.seed()
        before = self.snapshot()
        self.query("UPDATE official_registry SET businessSize='LARGE'")
        registry.quota_settings.invalidate()
        with patch.object(app_settings, "_settings_table_ready", False):
            registry.quota_settings.cap("quota.text_search.monthly")
        self.db.rollback()
        self.assertEqual(self.snapshot(), before)

    def test_external_business_id_matches_independently_of_surrogate_and_name(self):
        ids = self.seed(business_id="000123")
        self.seed(business_id="AUDIT-OTHER")
        before = self.snapshot()
        summary = self.sync(self.frame_row("000123", **{"Business Name": "RENAMED ISOLATED SHOP"}))
        self.assertEqual((summary["updated"], summary["inserted"]), (1, 0))
        self.assert_inspection_unchanged(before)
        rows = self.query("SELECT businessID, businessName FROM official_registry ORDER BY businessID")
        self.assertEqual(rows[0]["businessID"], "000123")
        self.assertEqual(rows[0]["businessName"], "RENAMED ISOLATED SHOP")
        self.assertEqual(rows[1]["businessName"], "ISOLATED SHOP AUDIT-OTHER")
        self.assert_color(ids[1], "Green")

    def test_legacy_pin_is_linked_before_registry_name_changes(self):
        ids = self.seed(color="Black", verification="Verified", result="Black", verified_event=True)
        self.query("UPDATE geospatial_logs SET businessID=NULL WHERE logID=%s", (ids[1],))
        self.db.commit()
        before = self.snapshot()
        self.sync(self.frame_row(ids[0], **{"Business Name": "RENAMED ISOLATED SHOP"}))
        self.assert_inspection_unchanged(before)
        pins = self.query("SELECT logID, businessID FROM geospatial_logs")
        self.assertEqual(pins, ({"logID": ids[1], "businessID": ids[0]},))
        self.assert_color(ids[1], "Black")

    def test_initial_expired_import_reuses_existing_inspected_legacy_pin(self):
        ids = self.seed("Expired", "Orange", "Verified", "Orange")
        self.query("UPDATE geospatial_logs SET businessID=NULL WHERE logID=%s", (ids[1],))
        self.query("DELETE FROM official_registry WHERE businessID=%s", (ids[0],))
        self.db.commit()
        before = self.snapshot()
        summary = self.sync(self.frame_row(ids[0], Status="Expired", Latitude="13.9667", Longitude="121.1167"), upload=True)
        self.assertEqual(summary["inserted"], 1)
        for table in ("inspection_reports", "inspection_lifecycle_events"):
            self.assertEqual(self.snapshot()[table], before[table])
        self.assertEqual(self.query("SELECT logID FROM geospatial_logs"), ({"logID": ids[1]},))
        self.assert_color(ids[1], "Orange")

    def test_new_ids_and_duplicate_new_ids_are_inserted_only_once(self):
        row = self.frame_row("AUDIT-NEW", Latitude="13.9667", Longitude="121.1167")
        first = self.sync(row, dict(row))
        before = self.snapshot()
        second = self.sync(row)
        self.assertEqual((first["inserted"], first["skipped"], second["inserted"], second["unchanged"]), (1, 1, 0, 1))
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(len(before["geospatial_logs"]), 1)

    def test_excel_uses_the_same_business_id_and_inspection_preservation_rules(self):
        import pandas as pd

        ids = self.seed(color="Black", verification="Verified", result="Black")
        before = self.snapshot()
        stream = BytesIO()
        pd.DataFrame([self.frame_row(ids[0], **{"Size of Business": "Large"})]).to_excel(stream, index=False)
        stream.seek(0)
        summary, error = registry.sync_registry(stream, ".xlsx")
        self.assertIsNone(error, error)
        self.assertEqual(summary["updated"], 1)
        self.assert_inspection_unchanged(before)
        self.assert_color(ids[1], "Black")

    def test_scheduled_expiry_preserves_inspection_owned_colors_and_history(self):
        targets = []
        for color in ("Black", "Purple", "Orange"):
            targets.append(self.seed("Active", color, "Verified", color, f"AUDIT-{color}", verified_event=True))
        self.query("UPDATE official_registry SET lastRenewalDate=%s", (f"{date.today().year-1}-01-01",))
        self.db.commit()
        before = self.snapshot()
        result = registry.check_and_expire_old_permits()
        self.assertEqual(result["count"], 3)
        self.assert_inspection_unchanged(before)
        for ids, color in zip(targets, ("Black", "Purple", "Orange")):
            self.assert_color(ids[1], color)

    def test_detection_rematch_does_not_erase_verified_terminal_findings(self):
        for color in ("Black", "Purple"):
            with self.subTest(color=color):
                ids = self.seed(color=color, verification="Verified", result=color, business_id=f"AUDIT-{color}")
                before = self.snapshot()
                flags._match_registry_to_google(
                    f"isolated-place-{color}", ids[0], f"ISOLATED SHOP {ids[0]}",
                    target_color="Green", lat=13.9667, lng=121.1167, barangay_id=1, match_score=0.95,
                )
                self.assert_inspection_unchanged(before)
                self.assert_color(ids[1], color)

    def test_manual_pin_reapproval_and_import_do_not_modify_inspection_evidence(self):
        ids = self.seed(color="Purple", verification="Verified", result="Purple", verified_event=True)
        self.query("UPDATE official_registry SET coordSource='manual', matchStatus='approved'")
        self.db.commit()
        before = self.snapshot()
        self.sync(self.frame_row(ids[0], **{"Business Address": "2 New Street", "Latitude": "13.967", "Longitude": "121.117"}))
        self.assert_inspection_unchanged(before)
        business = self.query("SELECT * FROM official_registry")[0]
        self.assertEqual(business["matchStatus"], "review")
        self.assertEqual((business["latitude"], business["longitude"]),
                         (before["official_registry"][0]["latitude"], before["official_registry"][0]["longitude"]))
        self.assertEqual(self.query("SELECT reviewType FROM registry_pin_history")[0]["reviewType"], "address_reapproval")
        self.assert_color(ids[1], "Purple")

    def test_old_offline_assignment_after_explicit_redispatch_is_a_conflict(self):
        ids = self.seed(verification="Submitted", result="Orange")
        result, error = inspections.reassign_submitted_report(ids[2], 9, None, 1)
        self.assertIsNone(error, error)
        self.assertEqual(result["status"], "Reassigned")
        self.sync(self.frame_row(ids[0]))
        before = self.snapshot()
        _, error = inspections.submit_inspection(
            ids[1], 9, "Orange", report_id=ids[2], assignment_cycle_id=ids[3],
        )
        self.assertIsInstance(error, inspections.InspectionSubmissionConflict)
        self.assertEqual(self.snapshot(), before)
