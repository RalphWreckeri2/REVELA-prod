"""Feature regressions: real shared colour/evidence SQL and actual workflows.

All data is synthetic SQLite memory. The existing adapter preserves every
production CASE arm; this feature-only adapter adds INSERT IGNORE compatibility
for exercising the real upload path, without changing any baseline fixture.
"""
from datetime import date
from io import BytesIO
from unittest.mock import patch

import pytest
from flask import Flask
from flask_jwt_extended import JWTManager, create_access_token

from api.flags import compliance_report, routes, service as flags
from api.inspections import service as inspections
from api.models import geospatial
from api.registry import service as registry
from api.registry.history_schema import ALL_HISTORY_COLUMNS
from registry_sqlite import RegistryCursor, RegistryDB


VERIFIED_AT = "2026-10-16 01:02:03.123456"


class FeatureCursor(RegistryCursor):
    def execute(self, sql, params=()):
        self.schema_rows = None
        if "information_schema.COLUMNS" in sql and "registry_pin_history" in sql:
            self.connection.calls.append((sql, params))
            present = {row["name"] for row in self.connection.db.execute("PRAGMA table_info(registry_pin_history)")}
            self.schema_rows = [dict(zip(
                ("COLUMN_NAME", "COLUMN_TYPE", "IS_NULLABLE", "COLUMN_DEFAULT", "EXTRA"), definition,
            )) for definition in ALL_HISTORY_COLUMNS if definition[0] in present]
            return self
        return super().execute(sql.replace("INSERT IGNORE INTO", "INSERT OR IGNORE INTO"), params)

    def fetchall(self):
        if self.schema_rows is not None:
            return self.schema_rows
        return super().fetchall()


class FeatureDB(RegistryDB):
    def __init__(self):
        super().__init__()
        columns = [f"{name} {kind}" for name, kind, *_ in ALL_HISTORY_COLUMNS]
        self.db.execute("CREATE TABLE registry_pin_history (" + ",".join(columns) + ")")

    def cursor(self):
        return FeatureCursor(self)


@pytest.fixture
def db():
    database = FeatureDB()
    with (
        patch.object(flags, "mysql", database),
        patch.object(inspections, "mysql", database),
        patch.object(compliance_report, "mysql", database),
        patch.object(registry, "mysql", database),
        patch.object(geospatial, "mysql", database),
        patch("api.notifications.hub.publish_to_admins"),
        patch.object(registry, "_log_registry_places_summary"),
    ):
        yield database
    database.close()


def pin(db, log_id=17, *, source="detection", linked=False, color="Red", name="L & U BIGASAN"):
    business_id = f"REG-{log_id}" if linked else None
    if linked:
        db.db.execute("""INSERT INTO official_registry
            (businessID,businessName,barangayID,applicationStatus,businessAddress,latitude,longitude)
            VALUES (?, ?, 1, 'Active', '1 MAIN STREET',13.9667,121.1167)""", (business_id, name))
    db.db.execute("""INSERT INTO geospatial_logs
        (logID,businessID,barangayID,detectedName,flagColor,source,nearestLandmark,latitude,longitude,placeID)
        VALUES (?, ?, 1, ?, ?, ?, '1 MAIN STREET',13.9667,121.1167,?)""",
                  (log_id, business_id, name, color, source, f"place-{log_id}"))
    db.commit()


def verify_green(db, log_id=17):
    db.db.execute("""INSERT INTO inspection_reports
        (reportID,targetID,targetType,userID,verificationStatus,inspectionResult,noticeLevel,
         irTimestamp,submittedAt,submissionReceivedAt)
        VALUES (?, ?, 'geospatial_log',9,'Submitted','Green',0,
                '2001-01-01','2002-02-02','2003-03-03')""", (log_id, log_id))
    db.commit()
    result, error = inspections.verify_inspection(log_id, verified_by_user_id=2)
    assert error is None
    assert result["status"] == "Verified"
    db.db.execute("UPDATE inspection_lifecycle_events SET eventTimestamp=? WHERE reportID=?",
                  (VERIFIED_AT, log_id))
    db.commit()


def map_pin(log_id=17):
    payload, error = flags.get_flags()
    assert error is None, error
    return next(row for row in payload["data"] if row["logID"] == log_id)


def report_ids():
    return [row["detectionReference"] for row in compliance_report.get_inspection_verified_compliant()["data"]]


@pytest.mark.parametrize("linked", [False, True])
def test_verified_detection_is_current_compliant_with_independent_link(db, linked):
    pin(db, linked=linked)
    verify_green(db)
    row = map_pin()
    assert row["flagColor"] == "Green"
    assert row["inspectionVerifiedCompliant"] is True
    assert row["registryLinked"] is linked
    assert row["originSource"] == "detection"
    assert report_ids() == [17]
    if not linked:
        assert db.rows("SELECT * FROM official_registry") == []


@pytest.mark.parametrize("linked", [False, True])
def test_verified_manual_report_is_included_only_when_not_registry_linked(db, linked):
    pin(db, source="manual", linked=linked)
    verify_green(db)
    row = map_pin()
    assert row["originSource"] == "manual"
    assert row["inspectionVerifiedCompliant"] is True
    assert report_ids() == ([] if linked else [17])


def test_green_without_qualifying_verification_is_not_evidence(db):
    pin(db, color="Green")
    assert map_pin()["inspectionVerifiedCompliant"] is False
    assert report_ids() == []


@pytest.mark.parametrize("color", ["Red", "Yellow", "Orange", "Purple", "Black"])
def test_old_green_superseded_by_current_non_green_is_excluded(db, color):
    pin(db)
    verify_green(db)
    db.db.execute("UPDATE geospatial_logs SET flagColor=?", (color,))
    db.commit()
    assert map_pin()["flagColor"] == color
    assert map_pin()["inspectionVerifiedCompliant"] is False
    assert report_ids() == []


def test_active_warning_excludes_green_even_with_stored_green(db):
    pin(db)
    verify_green(db)
    db.db.execute("""INSERT INTO enforcement_state
        (subjectType,subjectID,warningLevel,warningBaseColor) VALUES ('geospatial_log','17',1,'Red')""")
    db.commit()
    assert map_pin()["flagColor"] == "Orange"  # Real shared CASE, not a colour mock.
    assert map_pin()["inspectionVerifiedCompliant"] is False
    assert report_ids() == []


def test_clear_warning_to_a_green_base_does_not_invent_verified_compliance(db):
    pin(db, color="Green")
    db.db.execute("""INSERT INTO inspection_reports
        (reportID,targetID,targetType,userID,verificationStatus,inspectionResult,noticeLevel)
        VALUES (17,17,'geospatial_log',9,'Submitted','Orange',1)""")
    db.commit()
    _, error = inspections.verify_inspection(17, verified_by_user_id=2)
    assert error is None
    _, error = registry.clear_pin_warning(17, 2, "Clear warning only")
    assert error is None
    assert map_pin()["flagColor"] == "Green"
    assert map_pin()["inspectionVerifiedCompliant"] is False
    assert report_ids() == []


@pytest.mark.parametrize("source", ["registry", "registry_detected", "unknown", "unexpected-source"])
def test_registry_and_unknown_origins_are_excluded_from_report(db, source):
    pin(db, source=source)
    verify_green(db)
    assert map_pin()["originSource"] == source
    assert report_ids() == []


def test_registry_active_name_match_does_not_count_as_link_or_verified_compliance(db):
    pin(db, color="Red")
    db.db.execute("""INSERT INTO official_registry (businessID,businessName,barangayID,applicationStatus)
        VALUES ('IMPORTED','L & U BIGASAN',1,'Active')""")
    db.commit()
    row = map_pin()
    assert row["flagColor"] == "Green"  # Preserve existing colour matching semantics.
    assert row["registryLinked"] is False  # No actual FK, despite the derived Green.
    assert row["inspectionVerifiedCompliant"] is False
    assert report_ids() == []


def test_dangling_business_id_is_not_a_registry_link(db):
    pin(db)
    verify_green(db)
    db.db.execute("UPDATE geospatial_logs SET businessID='MISSING' WHERE logID=17")
    db.commit()
    assert map_pin()["registryLinked"] is False


def test_missing_source_column_does_not_infer_detection_origin(db):
    pin(db)
    verify_green(db)
    db.db.execute("ALTER TABLE geospatial_logs DROP COLUMN source")
    db.commit()
    geospatial.reset_source_column_cache()
    assert map_pin()["originSource"] == "unknown"
    assert report_ids() == []


@pytest.mark.parametrize("event_type", ["submitted", "reassigned", "dispatched", "cancelled", "verified"])
def test_later_workflow_or_result_invalidates_historical_green(db, event_type):
    pin(db, linked=True)
    verify_green(db)
    db.db.execute("""INSERT INTO inspection_lifecycle_events
        (reportID,targetLogID,eventType,inspectionResult,actorUserID,eventTimestamp)
        VALUES (17,17,?,'Red',2,'2026-10-16 02:00:00')""", (event_type,))
    db.commit()
    assert map_pin()["flagColor"] == "Green"
    assert map_pin()["inspectionVerifiedCompliant"] is False
    assert report_ids() == []


def test_later_enforcement_then_clear_does_not_reuse_old_green(db):
    pin(db)
    verify_green(db)
    db.db.execute("""INSERT INTO enforcement_events
        (subjectType,subjectID,eventType,actorUserID,createdAt)
        VALUES ('geospatial_log','17','warning_issued',2,'2026-10-16 02:00:00')""")
    db.commit()
    assert map_pin()["flagColor"] == "Green"
    assert map_pin()["inspectionVerifiedCompliant"] is False
    assert report_ids() == []


@pytest.mark.parametrize("missing", ["event", "actor", "timestamp", "current_report"])
def test_unreliable_legacy_verification_is_excluded_without_invented_dates(db, missing):
    pin(db)
    verify_green(db)
    statements = {
        "event": "DELETE FROM inspection_lifecycle_events",
        "actor": "UPDATE inspection_lifecycle_events SET actorUserID=NULL",
        "timestamp": "UPDATE inspection_lifecycle_events SET eventTimestamp=NULL",
        "current_report": "UPDATE inspection_reports SET verificationStatus='Reassigned',inspectionResult=NULL",
    }
    db.db.execute(statements[missing])
    db.commit()
    assert map_pin()["inspectionVerifiedCompliant"] is False
    assert report_ids() == []


def test_verified_on_is_actual_admin_event_time_in_utc(db):
    pin(db)
    verify_green(db)
    report = compliance_report.get_inspection_verified_compliant()
    assert report["data"][0]["verifiedOn"] == "2026-10-16T01:02:03.123456Z"
    assert map_pin()["verifiedGreenAt"] == report["data"][0]["verifiedOn"]
    assert "businessID" not in report["data"][0]
    assert report["data"][0]["detectionReference"] == 17


@pytest.mark.parametrize("mode", ["upload", "sync"])
def test_import_links_existing_detection_without_duplicate_or_lost_provenance(db, mode):
    pin(db)
    verify_green(db)
    events_before = db.rows("SELECT * FROM inspection_lifecycle_events")
    csv = ("Business ID,businessName,barangay,businessAddress,Status,lastRenewalDate,Latitude,Longitude\n"
           f"IMPORTED-17,L & U BIGASAN,Barangay I,1 MAIN STREET,Active,{date.today().year}-01-01,13.9667,121.1167\n")
    result, error = (registry.upload_registry if mode == "upload" else registry.sync_registry)(BytesIO(csv.encode()), ".csv")
    assert error is None, error
    assert result["inserted"] == 1
    assert db.rows("SELECT logID,businessID,source FROM geospatial_logs") == [
        {"logID": 17, "businessID": "IMPORTED-17", "source": "detection"}]
    assert db.rows("SELECT * FROM inspection_lifecycle_events") == events_before
    payload, error = flags.get_flags()
    assert error is None
    assert payload["total"] == 1
    assert map_pin()["registryLinked"] is True
    assert map_pin()["originSource"] == "detection"
    assert report_ids() == [17]
    _, error = (registry.upload_registry if mode == "upload" else registry.sync_registry)(BytesIO(csv.encode()), ".csv")
    assert error is None
    assert len(db.rows("SELECT * FROM geospatial_logs")) == 1
    assert map_pin()["originSource"] == "detection"


def test_detection_only_verified_green_survives_redetection_and_refresh(db):
    pin(db)
    verify_green(db)
    # Detection's existing empty-registry safeguard is preserved. This unrelated
    # registry row merely permits the synthetic scan; it does not match the pin.
    db.db.execute("""INSERT INTO official_registry (businessID,businessName,barangayID,applicationStatus)
        VALUES ('OTHER','UNRELATED SHOP',1,'Active')""")
    db.commit()
    before = db.rows("SELECT * FROM geospatial_logs WHERE logID=17")
    evidence = db.rows("SELECT * FROM inspection_lifecycle_events")

    def scan(process_places, _progress, state, **_kwargs):
        assert process_places([{
            "place_id": "place-17", "name": "L & U BIGASAN",
            "geometry": {"location": {"lat": 13.9667, "lng": 121.1167}},
        }]) is True
        state.update(total_points=1, done_keys=["synthetic-point"])

    with (
        patch.dict(flags._places_run_state.__dict__, {}, clear=False),
        patch.object(flags, "get_detection_quota_info", return_value={"is_limit_reached": False}),
        patch.object(flags, "create_detection_run", return_value=1),
        patch.object(flags, "update_detection_run_status"),
        patch.object(flags, "_ensure_place_types_column"),
        patch.object(flags, "_load_rejected_place_pairs", return_value=set()),
        patch.object(flags, "reconcile_existing_flags"),
        patch.object(flags, "_detection_points_for_mode", return_value=[(13.9667, 121.1167)]),
        patch.object(flags, "_scan_grid", side_effect=scan),
        patch.object(flags, "_log_detection_summary", return_value={}),
        patch.object(flags.quota_settings, "cap", return_value=100),
        patch.object(flags, "is_cancelled", return_value=False),
    ):
        result, error = flags.run_detection(mode="quick")
    assert error is None, error
    assert result["new_flags"] == 0
    assert db.rows("SELECT * FROM geospatial_logs WHERE logID=17") == before
    assert db.rows("SELECT * FROM inspection_lifecycle_events") == evidence
    assert map_pin()["flagColor"] == "Green"
    assert map_pin()["registryLinked"] is False
    assert report_ids() == [17]


def test_upload_reuse_does_not_adopt_or_modify_a_pin_with_an_open_inspection(db):
    pin(db)
    db.db.execute("""INSERT INTO inspection_reports
        (reportID,targetID,targetType,userID,verificationStatus)
        VALUES (17,17,'geospatial_log',9,'Assigned')""")
    db.commit()
    before = db.rows("SELECT * FROM geospatial_logs WHERE logID=17")
    inspections_before = db.rows("SELECT * FROM inspection_reports")
    csv = ("Business ID,businessName,barangay,Status,lastRenewalDate,Latitude,Longitude\n"
           f"IMPORTED-17,L & U BIGASAN,Barangay I,Active,{date.today().year}-01-01,13.9667,121.1167\n")
    _, error = registry.upload_registry(BytesIO(csv.encode()), ".csv")
    assert error is None, error
    assert db.rows("SELECT * FROM geospatial_logs WHERE logID=17") == before
    assert db.rows("SELECT * FROM inspection_reports") == inspections_before


def test_report_is_available_with_empty_official_registry_and_beyond_first_page(db):
    for log_id in range(1, 24):
        pin(db, log_id, name=f"DETECTED SHOP {log_id:02}")
        verify_green(db, log_id)
    assert db.rows("SELECT * FROM official_registry") == []
    snapshot = compliance_report.get_inspection_verified_compliant()
    assert snapshot["total"] == 23
    assert [row["detectionReference"] for row in snapshot["data"]] == list(range(1, 24))
    assert all(row["registryLinked"] is False for row in snapshot["data"])


@pytest.mark.parametrize("role,status", [(None, 401), ("Inspector", 403), ("Admin", 200), ("SUPER_ADMIN", 200)])
def test_report_route_reuses_admin_authorization_and_works_without_registry(db, role, status):
    app = Flask(__name__)
    app.config["JWT_SECRET_KEY"] = "offline-feature-test-key-at-least-32-chars"
    JWTManager(app)
    app.register_blueprint(routes.flags_bp, url_prefix="/api/flags")
    headers = {}
    if role:
        with app.app_context():
            token = create_access_token(identity="2", additional_claims={"role": role})
        headers["Authorization"] = f"Bearer {token}"
    with patch("api.middleware.decorators._verify_user_and_session", return_value=None):
        response = app.test_client().get("/api/flags/inspection-verified-compliant", headers=headers)
    assert response.status_code == status
    if status == 200:
        assert response.get_json()["data"] == []


def test_report_query_failure_is_an_error_not_a_false_empty_success(db):
    app = Flask(__name__)
    with app.test_request_context("/api/flags/inspection-verified-compliant"), patch.object(
        compliance_report, "get_inspection_verified_compliant", side_effect=RuntimeError("private SQL detail")
    ):
        response, status = routes.inspection_verified_compliant_route.__wrapped__()
    assert status == 500
    assert "private SQL detail" not in response.get_json()["error"]
