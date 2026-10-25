"""Run only through run_registry_sync_audit.py: disposable MySQL, HTTP blocked."""
from pathlib import Path
import threading
import unittest
from unittest.mock import patch

from flask_jwt_extended import create_access_token

from tests import test_registry_inspection_sync as audit
from api.inspections import service as inspections
from api.registry import service as registry
from api.registry.inspection_link import GreenRegistryLinkError
from api.models.geospatial import reset_source_column_cache
from api.registry.colors import reset_ladder_column_cache
from tests.green_link_http import ORIGIN, create_http_app


class GreenRegistryLinkTests(unittest.TestCase):
    query = audit.RegistryInspectionSyncTests.query
    frame_row = audit.RegistryInspectionSyncTests.frame_row
    import_file = audit.RegistryInspectionSyncTests.import_file

    @classmethod
    def setUpClass(cls):
        audit.RegistryInspectionSyncTests.setUpClass.__func__(cls)
        with cls.db.cursor() as cursor:
            cursor.execute("SET collation_connection = 'utf8mb4_unicode_ci'")
            cursor.execute("ALTER TABLE geospatial_logs ADD COLUMN source VARCHAR(24) NOT NULL DEFAULT 'unknown'")
            migration = Path(__file__).resolve().parents[1] / "migrations/20261021_01_confirmed_registry_pin.sql"
            cursor.execute(migration.read_text(encoding="utf-8"))
            cursor.execute("""CREATE TABLE enforcement_state (
                enforcementID INT AUTO_INCREMENT PRIMARY KEY,
                subjectType VARCHAR(30) NOT NULL, subjectID VARCHAR(50) NOT NULL,
                warningLevel INT NOT NULL DEFAULT 0, warningBaseColor VARCHAR(20),
                blackLocked INT NOT NULL DEFAULT 0, blackLockedAt DATETIME,
                blackLockedBy INT, blackLockReason VARCHAR(255),
                blackDispatchUnlocked INT NOT NULL DEFAULT 0,
                blackUnlockedAt DATETIME, blackUnlockedBy INT, blackUnlockReason VARCHAR(255),
                warningClearedAt DATETIME, warningClearedBy INT, warningClearReason VARCHAR(255),
                lastInspectionResult VARCHAR(20), lastInspectedAt DATETIME,
                UNIQUE(subjectType, subjectID)) ENGINE=InnoDB""")
            cursor.execute("""CREATE TABLE enforcement_events (
                eventID INT AUTO_INCREMENT PRIMARY KEY, subjectType VARCHAR(30), subjectID VARCHAR(50),
                eventType VARCHAR(50), actorUserID INT, reason VARCHAR(255), previousLevel INT,
                newLevel INT, previousBlack INT, newBlack INT,
                createdAt DATETIME DEFAULT CURRENT_TIMESTAMP) ENGINE=InnoDB""")
        cls.db.commit()

    @classmethod
    def tearDownClass(cls):
        cls.db.close()

    def setUp(self):
        self.db.rollback()
        self.query("UPDATE official_registry SET confirmedLogID = NULL")
        self.query("DELETE FROM enforcement_events")
        self.query("DELETE FROM enforcement_state")
        self.db.commit()
        reset_source_column_cache()
        reset_ladder_column_cache()
        audit.RegistryInspectionSyncTests.setUp(self)

    def seed(self, *, business_id="BPLO-001", existing=False, linked=False,
              source="manual", name="ISOLATED SHOP BPLO-001", result="Green", status="Submitted"):
        if existing or linked:
            self.query("""INSERT INTO official_registry
                (businessID, businessName, barangayID, applicationStatus, latitude, longitude, coordSource)
                VALUES (%s,%s,1,'Pending',13.9700,121.1200,'geocode')""", (business_id, name))
        log_id = self.query("""INSERT INTO geospatial_logs
            (businessID, barangayID, detectedName, latitude, longitude, flagColor, source,
             nearestLandmark, notes, reportedByUserID)
            VALUES (%s,1,%s,13.9667,121.1167,'Yellow',%s,'Near school','Original pin notes',9)""",
            (business_id if linked else None, name, source))
        report_id = self.query("""INSERT INTO inspection_reports
            (targetID,targetType,userID,inspectionResult,verificationStatus,noticeLevel,
             remarks,photoPath,verifiedLatitude,verifiedLongitude,verifiedAccuracy)
            VALUES (%s,'geospatial_log',9,%s,%s,0,'Original field notes','["/isolated/photo.jpg"]',13.9680,121.1180,8)""",
            (log_id, result, status))
        self.query("""INSERT INTO inspection_lifecycle_events
            (reportID,targetLogID,eventType,inspectionResult,remarks)
            VALUES (%s,%s,'submitted',%s,'Original submission')""", (report_id, log_id, result))
        self.db.commit()
        return log_id, report_id

    def review(self, report_id, business_id="BPLO-001"):
        result, error = inspections.preview_green_registry_link(report_id, business_id)
        self.assertIsNone(error, str(error))
        return result

    def confirm(self, report_id, business_id="BPLO-001", *, review=None, **changes):
        review = review or self.review(report_id, business_id)
        args = dict(business_id=business_id, confirm_establishment=True,
                    registry_review_token=review["reviewToken"])
        args.update(changes)
        return inspections.verify_inspection(report_id, 9, **args)

    def snapshot(self):
        return {table: self.query(f"SELECT * FROM {table} ORDER BY 1") for table in (
            "official_registry", "geospatial_logs", "inspection_reports",
            "inspection_lifecycle_events", "enforcement_state", "enforcement_events")}

    def assert_one_original_marker(self, log_id):
        result, error = audit.flags.get_flags(per_page=100)
        self.assertIsNone(error, error)
        self.assertEqual(result["total"], 1)
        self.assertEqual(len(result["data"]), 1)
        marker = result["data"][0]
        self.assertEqual((marker["logID"], marker["latitude"], marker["longitude"]),
                         (log_id, 13.9667, 121.1167))
        return marker

    def test_existing_registry_link_preserves_pin_and_all_history_one_marker(self):
        log_id, report_id = self.seed(existing=True)
        generated = self.query("""INSERT INTO geospatial_logs
            (businessID,barangayID,detectedName,latitude,longitude,flagColor,source)
            VALUES ('BPLO-001',1,'ISOLATED SHOP BPLO-001',13.9700,121.1200,'Yellow','registry')""")
        self.db.commit()
        before = self.snapshot()
        review = self.review(report_id)
        self.assertEqual(self.snapshot(), before, "Review must not write or recolour anything")
        result, error = self.confirm(report_id, review=review)
        self.assertIsNone(error, error)
        self.assertEqual(result["businessID"], "BPLO-001")
        after = self.snapshot()
        self.assertEqual(after["official_registry"][0]["fixtureRowID"], before["official_registry"][0]["fixtureRowID"])
        self.assertEqual(after["official_registry"][0]["confirmedLogID"], log_id)
        self.assertEqual(after["official_registry"][0]["applicationStatus"], "Active")
        old_pin = next(row for row in before["geospatial_logs"] if row["logID"] == log_id)
        pin = next(row for row in after["geospatial_logs"] if row["logID"] == log_id)
        for key in old_pin.keys() - {"businessID", "flagColor"}:
            self.assertEqual(pin[key], old_pin[key], key)
        self.assertTrue(any(row["logID"] == generated for row in after["geospatial_logs"]), "Retain old registry marker history")
        for key in before["inspection_reports"][0].keys() - {"verificationStatus"}:
            self.assertEqual(after["inspection_reports"][0][key], before["inspection_reports"][0][key], key)
        self.assertEqual(after["inspection_lifecycle_events"][:-1], before["inspection_lifecycle_events"])
        self.assertEqual(self.assert_one_original_marker(log_id)["flagSource"], "manual")

    def test_new_registry_uses_known_details_leaves_optional_values_null(self):
        log_id, report_id = self.seed(source="detection")
        review = self.review(report_id)
        self.assertFalse(review["registryExists"])
        self.assertEqual(review["missingRequiredFields"], [])
        result, error = self.confirm(report_id, review=review)
        self.assertIsNone(error, error)
        row = self.query("SELECT * FROM official_registry")[0]
        for key in ("businessAddress", "businessType", "lineOfBusiness", "businessSize", "registrationType", "lastRenewalDate", "coordSource"):
            self.assertIsNone(row[key], key)
        self.assertEqual(row["businessName"], "ISOLATED SHOP BPLO-001")
        self.assertEqual(self.assert_one_original_marker(log_id)["flagSource"], "detection")

    def test_office_creates_minimal_record_and_import_enriches_same_id_without_moving_pin(self):
        log_id = self.query("""INSERT INTO geospatial_logs
            (barangayID,detectedName,latitude,longitude,flagColor,source,notes)
            VALUES (1,'ISOLATED SHOP BPLO-001',13.9667,121.1167,'Yellow','detection','Original scan')""")
        self.db.commit()
        review, error = registry.preview_pin_compliance(log_id, "BPLO-001")
        self.assertIsNone(error, error)
        self.assertFalse(review["registryExists"])
        result, error = registry.confirm_pin_compliance(
            log_id, "BPLO-001", 9, "Office record",
            registry_review_token=review["reviewToken"], confirm_establishment=True)
        self.assertIsNone(error, error)
        self.assertEqual(result["flagColor"], "Green")
        original = self.query("SELECT * FROM geospatial_logs WHERE logID=%s", (log_id,))[0]
        official = self.query("SELECT * FROM official_registry WHERE businessID='BPLO-001'")[0]
        self.assertEqual(official["confirmedLogID"], log_id)
        for field in ("businessAddress", "businessType", "lineOfBusiness", "businessSize", "registrationType", "lastRenewalDate"):
            self.assertIsNone(official[field])
        self.assertFalse(self.query("SELECT * FROM inspection_reports"))
        row = self.frame_row("BPLO-001", **{"Business Address": "Office street", "Latitude": "13.9750", "Longitude": "121.1250"})
        for workflow in (registry.upload_registry, registry.sync_registry):
            summary, error = workflow(self.import_file(row), ".csv")
            self.assertIsNone(error, error)
            self.assertEqual(summary["inserted"], 0)
            self.assertEqual(self.query("SELECT * FROM geospatial_logs WHERE logID=%s", (log_id,))[0], original)
            self.assertEqual(self.query("SELECT confirmedLogID,latitude,longitude FROM official_registry WHERE businessID='BPLO-001'")[0]["confirmedLogID"], log_id)
        self.assertEqual(len(self.query("SELECT * FROM official_registry")), 1)
        self.assert_one_original_marker(log_id)

    def test_missing_required_name_requested_then_saved_without_guessing(self):
        log_id, report_id = self.seed(name=None)
        review = self.review(report_id)
        self.assertEqual(review["missingRequiredFields"], ["businessName"])
        before = self.snapshot()
        result, error = self.confirm(report_id, review=review)
        self.assertIsNone(result)
        self.assertIsInstance(error, GreenRegistryLinkError)
        self.assertEqual(self.snapshot(), before)
        result, error = self.confirm(report_id, review=review, registry_fields={"businessName": "Actual official name"})
        self.assertIsNone(error, str(error))
        self.assertEqual(self.query("SELECT businessName FROM official_registry")[0]["businessName"], "Actual official name")
        self.assert_one_original_marker(log_id)

    def test_invalid_ids_and_unreviewed_confirmation_write_nothing(self):
        _, report_id = self.seed()
        before = self.snapshot()
        for value in (None, "", "  ", "#", "N/A", "UNKNOWN", "X" * 51, "BAD\nID", "<script>", 123, [], {}):
            with self.subTest(value=value):
                result, error = inspections.verify_inspection(report_id, 9, business_id=value, confirm_establishment=True)
                self.assertIsNone(result)
                self.assertIsInstance(error, GreenRegistryLinkError)
                self.assertEqual(self.snapshot(), before)
        for changes in ({"confirm_establishment": False}, {"confirm_establishment": "true"},
                        {"registry_review_token": "outdated"}, {"update_location": True}):
            result, error = self.confirm(report_id, **changes)
            self.assertIsNone(result)
            self.assertIsInstance(error, GreenRegistryLinkError)
            self.assertEqual(self.snapshot(), before)

    def test_identity_mismatch_and_conflicting_ids_refuse_link(self):
        log_id, report_id = self.seed(existing=True)
        for update in ("businessName = 'ANOTHER ESTABLISHMENT'", "barangayID = 2", "confirmedLogID = 999"):
            if "999" in update:
                self.query("INSERT INTO geospatial_logs (logID,barangayID,source) VALUES (999,1,'manual')")
            self.query(f"UPDATE official_registry SET {update}")
            self.db.commit()
            before = self.snapshot()
            result, error = inspections.preview_green_registry_link(report_id, "BPLO-001")
            self.assertIsNone(result)
            self.assertTrue(error.conflict)
            self.assertEqual(self.snapshot(), before)
            self.query("UPDATE official_registry SET businessName = 'ISOLATED SHOP BPLO-001', barangayID = 1, confirmedLogID = NULL")
            self.db.commit()
        self.query("UPDATE geospatial_logs SET businessID = 'BPLO-001' WHERE logID = %s", (log_id,))
        self.db.commit()
        result, error = inspections.preview_green_registry_link(report_id, "OTHER-ID")
        self.assertIsNone(result)
        self.assertTrue(error.conflict)

    def test_another_field_pin_with_same_id_is_a_conflict(self):
        _, report_id = self.seed(existing=True)
        self.query("""INSERT INTO geospatial_logs
            (businessID,barangayID,detectedName,source) VALUES ('BPLO-001',1,'OTHER FIELD PIN','manual')""")
        self.db.commit()
        before = self.snapshot()
        result, error = inspections.preview_green_registry_link(report_id, "BPLO-001")
        self.assertIsNone(result)
        self.assertTrue(error.conflict)
        self.assertEqual(self.snapshot(), before)

    def test_changed_registry_identity_requires_another_review(self):
        _, report_id = self.seed(existing=True)
        review = self.review(report_id)
        self.query("UPDATE official_registry SET businessAddress = 'Changed official address'")
        self.db.commit()
        before = self.snapshot()
        result, error = self.confirm(report_id, review=review)
        self.assertIsNone(result)
        self.assertTrue(error.conflict)
        self.assertEqual(self.snapshot(), before)

    def test_repeated_confirmation_and_normalized_id_are_idempotent(self):
        log_id, report_id = self.seed()
        review = self.review(report_id, "# bplo-001 ")
        result, error = self.confirm(report_id, "# bplo-001 ", review=review)
        self.assertIsNone(error, error)
        before = self.snapshot()
        result, error = self.confirm(report_id, "bplo-001", review=review)
        self.assertIsNone(error, error)
        self.assertTrue(result["alreadyVerified"])
        self.assertEqual(self.snapshot(), before)
        self.assert_one_original_marker(log_id)

    def test_failure_after_link_rolls_back_registry_pin_verification_and_audit(self):
        _, report_id = self.seed()
        review = self.review(report_id)
        before = self.snapshot()
        with patch.object(inspections, "log_inspection_event", side_effect=RuntimeError("isolated audit failure")):
            result, error = self.confirm(report_id, review=review)
        self.assertIsNone(result)
        self.assertIn("isolated audit failure", str(error))
        self.db.commit()  # A later commit must not resurrect partial work.
        self.assertEqual(self.snapshot(), before)

    def test_import_and_sync_keep_one_original_marker_even_with_replacement_coordinates(self):
        log_id, report_id = self.seed(existing=True)
        result, error = self.confirm(report_id)
        self.assertIsNone(error, error)
        history = self.snapshot()
        for workflow in (registry.upload_registry, registry.sync_registry):
            for coordinates in ({}, {"Latitude": "13.9750", "Longitude": "121.1250"}):
                with self.subTest(workflow=workflow.__name__, coordinates=coordinates):
                    row = self.frame_row("BPLO-001", **{"Business Address": "Changed street", "Size of Business": "Large", **coordinates})
                    summary, error = workflow(self.import_file(row), ".csv")
                    self.assertIsNone(error, error)
                    self.assertEqual(summary["inserted"], 0)
                    self.assertEqual(self.query("SELECT businessSize FROM official_registry")[0]["businessSize"], "LARGE")
                    self.assertEqual(self.snapshot()["inspection_reports"], history["inspection_reports"])
                    self.assertEqual(self.snapshot()["inspection_lifecycle_events"], history["inspection_lifecycle_events"])
                    self.assert_one_original_marker(log_id)
                    registry_pin = self.query("SELECT latitude, longitude, confirmedLogID FROM official_registry")[0]
                    self.assertEqual((float(registry_pin["latitude"]), float(registry_pin["longitude"]), registry_pin["confirmedLogID"]), (13.9667, 121.1167, log_id))
        self.resolver.assert_not_called()

    def test_import_never_adopts_an_unlinked_green_pin_by_name(self):
        log_id, _ = self.seed(result="Green", status="Verified")
        before = self.query("SELECT * FROM geospatial_logs WHERE logID=%s", (log_id,))
        row = self.frame_row("DIFFERENT-ID", **{"Business Name": "ISOLATED SHOP BPLO-001", "Latitude": "13.9667", "Longitude": "121.1167"})
        result, error = registry.sync_registry(self.import_file(row), ".csv")
        self.assertIsNone(error, error)
        self.assertEqual(self.query("SELECT * FROM geospatial_logs WHERE logID=%s", (log_id,)), before)
        self.assertEqual(result["inserted"], 1)

    def test_import_and_sync_update_a_newly_created_link_without_duplicates(self):
        log_id, report_id = self.seed()
        result, error = self.confirm(report_id)
        self.assertIsNone(error, error)
        row = self.frame_row("# bplo-001", **{"Latitude": "13.9800", "Longitude": "121.1300"})
        for workflow in (registry.upload_registry, registry.sync_registry):
            summary, error = workflow(self.import_file(row, row), ".csv")
            self.assertIsNone(error, error)
            self.assertEqual(summary["inserted"], 0)
            self.assertEqual(summary["skipped"], 1)
            self.assertEqual(len(self.query("SELECT * FROM official_registry")), 1)
            self.assertEqual(len(self.query("SELECT * FROM geospatial_logs")), 1)
            self.assert_one_original_marker(log_id)
        self.resolver.assert_not_called()

    def test_confirmed_imports_still_freeze_closed_black_and_open_inspections(self):
        log_id, report_id = self.seed()
        result, error = self.confirm(report_id)
        self.assertIsNone(error, error)
        row = self.frame_row("BPLO-001", **{"Size of Business": "Large"})
        for status, counter in (("Closed", "skipped_closed"), ("Revoked", "skipped_black_lock")):
            self.query("UPDATE official_registry SET applicationStatus=%s", (status,))
            self.db.commit()
            before = self.snapshot()
            for workflow in (registry.upload_registry, registry.sync_registry):
                summary, error = workflow(self.import_file(row), ".csv")
                self.assertIsNone(error, error)
                self.assertEqual(summary[counter], 1)
                self.assertEqual(self.snapshot(), before)
        self.query("UPDATE official_registry SET applicationStatus='Active'")
        self.query("""INSERT INTO inspection_reports (targetID,targetType,userID,verificationStatus)
                      VALUES (%s,'geospatial_log',9,'Assigned')""", (log_id,))
        self.db.commit()
        before = self.snapshot()
        for workflow in (registry.upload_registry, registry.sync_registry):
            summary, error = workflow(self.import_file(row), ".csv")
            self.assertIsNone(error, error)
            self.assertEqual(summary["skipped_open_inspection"], 1)
            self.assertEqual(self.snapshot(), before)
        self.resolver.assert_not_called()

    def test_migration_enforces_unique_ids_unique_confirmed_pins_and_pin_reference(self):
        log_id, report_id = self.seed()
        result, error = self.confirm(report_id)
        self.assertIsNone(error, error)
        from MySQLdb import IntegrityError
        before = self.snapshot()
        for sql, params in (
            ("INSERT INTO official_registry (businessID,barangayID) VALUES ('bplo-001',1)", ()),
            ("INSERT INTO official_registry (businessID,barangayID,confirmedLogID) VALUES ('OTHER',1,%s)", (log_id,)),
            ("UPDATE official_registry SET confirmedLogID=999999", ()),
            ("DELETE FROM geospatial_logs WHERE logID=%s", (log_id,)),
        ):
            with self.subTest(sql=sql), self.assertRaises(IntegrityError):
                self.query(sql, params)
            self.db.rollback()
            self.assertEqual(self.snapshot(), before)

    def test_automatic_pin_update_does_not_move_confirmed_or_unlinked_pins(self):
        log_id, report_id = self.seed()
        result, error = self.confirm(report_id)
        self.assertIsNone(error, error)
        before = self.snapshot()
        with self.db.cursor() as cursor:
            audit.places_resolver._update_pin(cursor, 1, "ISOLATED SHOP BPLO-001",
                13.9667, 121.1167, 13.9800, 121.1300, business_id="BPLO-001")
        self.db.commit()
        self.assertEqual(self.snapshot(), before)
        self.assert_one_original_marker(log_id)

    def test_registry_black_lock_refuses_green_link_and_leaves_submission_pending(self):
        _, report_id = self.seed(existing=True)
        self.query("INSERT INTO enforcement_state (subjectType,subjectID,blackLocked) VALUES ('business','BPLO-001',1)")
        self.db.commit()
        review = self.review(report_id)
        before = self.snapshot()
        result, error = self.confirm(report_id, review=review)
        self.assertIsNone(result)
        self.assertIsInstance(error, GreenRegistryLinkError)
        self.assertEqual(self.snapshot(), before)

    def test_legacy_black_dispatch_grant_records_green_without_moving_or_recolouring(self):
        log_id, report_id = self.seed(linked=True)
        self.query("UPDATE official_registry SET applicationStatus='Revoked'")
        self.query("UPDATE geospatial_logs SET flagColor='Black'")
        self.query("""INSERT INTO enforcement_state (subjectType,subjectID,blackLocked,blackDispatchUnlocked)
                      VALUES ('business','BPLO-001',1,1)""")
        self.db.commit()
        original = self.query("SELECT * FROM geospatial_logs")
        result, error = self.confirm(report_id)
        self.assertIsNone(error, error)
        self.assertTrue(result["blackDispatchUnlockSpent"])
        self.assertEqual(self.query("SELECT * FROM geospatial_logs"), original)
        self.assertEqual(self.assert_one_original_marker(log_id)["flagColor"], "Black")
        self.assertEqual(self.query("SELECT applicationStatus FROM official_registry")[0]["applicationStatus"], "Revoked")

    def test_entering_id_does_not_complete_inspector_or_non_green_workflow(self):
        _, report_id = self.seed(result="Red")
        result, error = inspections.verify_inspection(report_id, 9, business_id="BPLO-001", confirm_establishment=True)
        self.assertIsNone(error, error)
        self.assertEqual(self.query("SELECT flagColor FROM geospatial_logs")[0]["flagColor"], "Red")
        self.assertFalse(self.query("SELECT * FROM official_registry"))
        _, assigned = self.seed(business_id="BPLO-002", status="Assigned")
        before = self.snapshot()
        result, error = inspections.verify_inspection(assigned, 9, business_id="BPLO-002", confirm_establishment=True)
        self.assertIsNone(result)
        self.assertEqual(self.snapshot(), before)

    def test_warning_and_black_lock_safeguards_survive_linking(self):
        log_id, report_id = self.seed()
        self.query("""INSERT INTO enforcement_state
            (subjectType,subjectID,warningLevel,warningBaseColor,blackLocked)
            VALUES ('geospatial_log',%s,2,'Yellow',1)""", (str(log_id),))
        self.db.commit()
        review = self.review(report_id)
        before = self.snapshot()
        result, error = self.confirm(report_id, review=review)
        self.assertIsNone(result)
        self.assertTrue(error.conflict)
        self.assertEqual(self.snapshot(), before)
        self.query("UPDATE enforcement_state SET blackLocked=0")
        self.db.commit()
        result, error = self.confirm(report_id, review=review)
        self.assertIsNone(result)
        self.assertTrue(error.conflict)
        self.assertEqual(self.assert_one_original_marker(log_id)["flagColor"], "Orange")
        self.assertFalse(self.query("SELECT * FROM enforcement_events"))

    def test_existing_link_is_shown_and_validated(self):
        log_id, report_id = self.seed(linked=True)
        review = self.review(report_id)
        self.assertEqual(review["pin"]["businessID"], "BPLO-001")
        result, error = self.confirm(report_id, review=review)
        self.assertIsNone(error, error)
        self.assert_one_original_marker(log_id)

    def test_admin_routes_require_review_and_inspector_cannot_confirm(self):
        _, report_id = self.seed()
        app = create_http_app(blueprint_only=True)
        with app.app_context():
            admin = create_access_token(identity="9", additional_claims={"role": "Admin"})
            inspector = create_access_token(identity="9", additional_claims={"role": "Inspector"})
        client = app.test_client()
        with patch("api.middleware.decorators._verify_user_and_session", return_value=None):
            for path, method, headers in (
                (f"/api/inspections/{report_id}/green-registry-link?businessID=BPLO-001", "GET", "authorization"),
                (f"/api/inspections/{report_id}/verify", "POST", "authorization,content-type"),
            ):
                preflight = client.options(path, headers={"Origin": ORIGIN,
                    "Access-Control-Request-Method": method, "Access-Control-Request-Headers": headers})
                self.assertEqual(preflight.status_code, 204)
                self.assertEqual(preflight.headers["Access-Control-Allow-Origin"], ORIGIN)
            self.assertEqual(client.post(f"/api/inspections/{report_id}/verify", json={}, headers={"Origin": ORIGIN, "Authorization": f"Bearer {admin}"}).status_code, 400)
            self.assertEqual(client.get(f"/api/inspections/{report_id}/green-registry-link?businessID=BPLO-001", headers={"Origin": ORIGIN, "Authorization": f"Bearer {inspector}"}).status_code, 403)
            before = self.snapshot()
            review = client.get(f"/api/inspections/{report_id}/green-registry-link?businessID=BPLO-001", headers={"Origin": ORIGIN, "Authorization": f"Bearer {admin}"})
            self.assertEqual(review.status_code, 200)
            self.assertEqual(review.headers["Access-Control-Allow-Origin"], ORIGIN)
            self.assertEqual(review.json["pin"]["logID"], before["geospatial_logs"][0]["logID"])
            self.assertEqual(review.json["registry"]["businessName"], "ISOLATED SHOP BPLO-001")
            self.assertFalse(review.json["registryExists"])
            self.assertEqual(review.json["missingRequiredFields"], [])
            self.assertTrue(review.json["reviewToken"])
            self.assertEqual(self.snapshot(), before, "Review must not modify any isolated record")
            response = client.post(f"/api/inspections/{report_id}/verify", json={
                "businessID": "BPLO-001", "confirmEstablishment": True,
                "registryReviewToken": review.json["reviewToken"],
            }, headers={"Origin": ORIGIN, "Authorization": f"Bearer {admin}"})
            self.assertEqual(response.status_code, 200, response.json)
            self.assertEqual(response.headers["Access-Control-Allow-Origin"], ORIGIN)

    def test_missing_migration_is_a_separate_authenticated_409_not_a_preflight_failure(self):
        _, report_id = self.seed()
        app = create_http_app(blueprint_only=True)
        with app.app_context():
            admin = create_access_token(identity="9", additional_claims={"role": "Admin"})
        before = self.snapshot()
        path = f"/api/inspections/{report_id}/green-registry-link?businessID=BPLO-001"
        with patch("api.middleware.decorators._verify_user_and_session", return_value=None), patch(
            "api.registry.inspection_link.confirmed_pin_column_available", return_value=False):
            client = app.test_client()
            preflight = client.options(path, headers={"Origin": ORIGIN,
                "Access-Control-Request-Method": "GET", "Access-Control-Request-Headers": "authorization"})
            self.assertEqual(preflight.status_code, 204)
            review = client.get(path, headers={"Origin": ORIGIN, "Authorization": f"Bearer {admin}"})
        self.assertEqual(review.status_code, 409)
        self.assertIn("migration", review.json["error"])
        self.assertEqual(review.headers["Access-Control-Allow-Origin"], ORIGIN)
        self.assertEqual(self.snapshot(), before)

    def test_read_only_schema_check_detects_the_applied_migration(self):
        from scripts.check_green_registry_link_schema import inspect_schema

        connection = audit.connect_to_disposable_mysql()
        try:
            with connection.cursor() as cursor:
                cursor.execute("SET SESSION TRANSACTION READ ONLY")
            result = inspect_schema(connection)
            self.assertEqual(result["status"], "ready", result)
            self.assertTrue(result["read_only"])
            self.assertTrue(all(result["checks"].values()))
        finally:
            connection.rollback()
            connection.close()

    def concurrent_confirmations(self, requests):
        local = threading.local()
        base = self.mysql

        class PerThreadMySQL:
            @property
            def connection(self):
                return getattr(local, "connection", base.connection)

        isolated = PerThreadMySQL()
        barrier = threading.Barrier(2)
        outcomes = []

        def worker(report_id, review):
            local.connection = audit.connect_to_disposable_mysql()
            try:
                with local.connection.cursor() as cursor:
                    cursor.execute("SET collation_connection = 'utf8mb4_unicode_ci'")
                barrier.wait(timeout=10)
                outcomes.append(self.confirm(report_id, review=review))
            finally:
                local.connection.close()

        with patch.object(inspections, "mysql", isolated):
            workers = [threading.Thread(target=worker, args=request) for request in requests]
            for worker_thread in workers:
                worker_thread.start()
            for worker_thread in workers:
                worker_thread.join(timeout=20)
                self.assertFalse(worker_thread.is_alive())
        self.db.rollback()
        return outcomes

    def test_concurrent_repeated_confirmation_commits_only_once(self):
        _, report_id = self.seed()
        review = self.review(report_id)
        outcomes = self.concurrent_confirmations([(report_id, review), (report_id, review)])
        self.assertEqual(len(outcomes), 2)
        self.assertTrue(all(error is None for _, error in outcomes), outcomes)
        self.assertEqual(sum(bool(result.get("alreadyVerified")) for result, _ in outcomes), 1)
        self.assertEqual(len(self.query("SELECT * FROM official_registry")), 1)
        self.assertEqual(len(self.query("SELECT * FROM inspection_lifecycle_events WHERE eventType='verified'")), 1)

    def test_two_pins_competing_for_same_new_business_id_cannot_both_link(self):
        _, first_report = self.seed()
        _, second_report = self.seed()
        outcomes = self.concurrent_confirmations([
            (first_report, self.review(first_report)), (second_report, self.review(second_report))])
        self.assertEqual(sum(error is None for _, error in outcomes), 1, outcomes)
        self.assertTrue(all(error is None or isinstance(error, GreenRegistryLinkError) and error.conflict for _, error in outcomes), outcomes)
        self.assertEqual(len(self.query("SELECT * FROM official_registry")), 1)
        self.assertEqual(len(self.query("SELECT * FROM geospatial_logs WHERE businessID IS NOT NULL")), 1)
        self.assertEqual(len(self.query("SELECT * FROM inspection_reports WHERE verificationStatus='Verified'")), 1)
