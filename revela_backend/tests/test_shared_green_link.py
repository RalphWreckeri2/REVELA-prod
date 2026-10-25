"""Both Green transitions require an existing official record; synthetic DB only."""
from unittest.mock import patch
from datetime import date
from io import BytesIO

import pytest
from flask import Flask
from flask_jwt_extended import JWTManager, create_access_token

from api.inspections import service as inspections
from api.flags import service as flags
from api.models import geospatial
from api.inspections.routes import inspections_bp
from api.flags.routes import flags_bp
from api.registry import service as registry
from api.registry.inspection_link import GreenRegistryLinkError
from test_map_compliance import FeatureDB


@pytest.fixture
def db():
    database = FeatureDB()
    database.db.execute("""INSERT INTO official_registry
        (businessID,businessName,barangayID,applicationStatus,latitude,longitude)
        VALUES ('OFFICIAL-1','FIELD SHOP',1,'Pending',13.97,121.12)""")
    database.db.execute("""INSERT INTO geospatial_logs
        (logID,barangayID,detectedName,flagColor,latitude,longitude,source)
        VALUES (30,1,'FIELD SHOP','Yellow',13.9667,121.1167,'detection')""")
    database.db.execute("""INSERT INTO inspection_reports
        (reportID,targetID,targetType,userID,inspectionResult,verificationStatus,noticeLevel)
        VALUES (31,30,'geospatial_log',9,'Green','Submitted',0)""")
    database.commit()
    with (patch.object(inspections, "mysql", database),
          patch.object(registry, "mysql", database),
          patch.object(flags, "mysql", database),
          patch.object(geospatial, "mysql", database),
          patch.object(registry, "_log_registry_places_summary"),
          patch("api.notifications.hub.publish_to_admins")):
        yield database
    database.close()


def snapshot(db):
    return tuple(db.rows(f"SELECT * FROM {table}") for table in (
        "official_registry", "geospatial_logs", "inspection_reports",
        "inspection_lifecycle_events", "enforcement_state", "enforcement_events"))


def review(path, business_id):
    return (inspections.preview_green_registry_link(31, business_id)
            if path == "inspection" else registry.preview_pin_compliance(30, business_id))


@pytest.mark.parametrize("path", ["inspection", "office"])
def test_existing_record_linked_without_new_pin_or_inspection(path, db):
    if path == "office":
        db.db.execute("DELETE FROM inspection_reports")
        db.commit()
    before = snapshot(db)
    plan, error = review(path, "official-1")
    assert error is None, error
    assert plan["registryExists"] is True
    assert snapshot(db) == before
    if path == "inspection":
        result, error = inspections.verify_inspection(31, 2, business_id="official-1",
            registry_review_token=plan["reviewToken"], confirm_establishment=True)
    else:
        result, error = registry.confirm_pin_compliance(30, "official-1", 2, "Office record",
            registry_review_token=plan["reviewToken"], confirm_establishment=True)
    assert error is None, error
    assert result["businessID"] == "OFFICIAL-1"
    assert db.rows("SELECT logID,businessID,flagColor,latitude,longitude,source FROM geospatial_logs") == [
        {"logID": 30, "businessID": "OFFICIAL-1", "flagColor": "Green",
         "latitude": 13.9667, "longitude": 121.1167, "source": "detection"}]
    assert db.rows("SELECT businessID,confirmedLogID,applicationStatus FROM official_registry") == [
        {"businessID": "OFFICIAL-1", "confirmedLogID": 30, "applicationStatus": "Active"}]
    assert db.rows("SELECT verificationStatus FROM inspection_reports") == (
        [{"verificationStatus": "Verified"}] if path == "inspection" else [])
    assert len(db.rows("SELECT * FROM inspection_lifecycle_events")) == (1 if path == "inspection" else 0)
    assert len(db.rows("SELECT * FROM enforcement_events")) == (0 if path == "inspection" else 1)


@pytest.mark.parametrize("path", ["inspection", "office"])
@pytest.mark.parametrize("business_id", [None, "", "N/A", "<bad>"])
def test_invalid_id_never_creates_registry_record(path, business_id, db):
    before = snapshot(db)
    result, error = review(path, business_id)
    assert result is None
    assert isinstance(error, GreenRegistryLinkError)
    assert snapshot(db) == before


@pytest.mark.parametrize("path", ["inspection", "office"])
def test_office_issued_id_creates_minimal_record_then_import_enriches_without_moving_pin(path, db):
    db.db.execute("DELETE FROM official_registry")
    if path == "office":
        db.db.execute("DELETE FROM inspection_reports")
    db.commit()
    plan, error = review(path, "office-1")
    assert error is None and not plan["registryExists"]
    assert plan["missingRequiredFields"] == []
    assert plan["pin"]["source"] == "detection"
    if path == "inspection":
        result, error = inspections.verify_inspection(31, 2, business_id="office-1",
            registry_review_token=plan["reviewToken"], confirm_establishment=True)
    else:
        result, error = registry.confirm_pin_compliance(30, "office-1", 2,
            registry_review_token=plan["reviewToken"], confirm_establishment=True)
    assert error is None, error
    assert result["businessID"] == "OFFICE-1"
    created = db.rows("SELECT * FROM official_registry")
    assert len(created) == 1 and created[0]["confirmedLogID"] == 30
    for key in ("businessAddress", "businessType", "lineOfBusiness", "businessSize", "registrationType", "lastRenewalDate"):
        assert created[0][key] is None
    original = db.rows("SELECT * FROM geospatial_logs")
    csv = ("Business ID,businessName,barangay,businessAddress,Status,lastRenewalDate,Latitude,Longitude\n"
           f"OFFICE-1,UPDATED OFFICIAL SHOP,Barangay I,1 MAIN STREET,Active,{date.today().year}-01-01,13.9700,121.1200\n")
    for importer in (registry.upload_registry, registry.sync_registry):
        summary, error = importer(BytesIO(csv.encode()), ".csv")
        assert error is None, error
        assert summary["inserted"] == 0
        assert db.rows("SELECT * FROM geospatial_logs") == original
        row = db.rows("SELECT * FROM official_registry")[0]
        assert row["confirmedLogID"] == 30
        assert (row["latitude"], row["longitude"]) == (13.9667, 121.1167)
        assert row["businessAddress"] == "1 MAIN STREET"
        assert row["businessName"] == "UPDATED OFFICIAL SHOP"
    assert len(db.rows("SELECT * FROM official_registry")) == 1


@pytest.mark.parametrize("path", ["inspection", "office"])
def test_missing_required_name_must_be_supplied_from_office_record(path, db):
    db.db.execute("DELETE FROM official_registry")
    db.db.execute("UPDATE geospatial_logs SET detectedName=NULL WHERE logID=30")
    if path == "office":
        db.db.execute("DELETE FROM inspection_reports")
    db.commit()
    plan, error = review(path, "OFFICE-1")
    assert error is None and plan["missingRequiredFields"] == ["businessName"]
    before = snapshot(db)
    if path == "inspection":
        result, error = inspections.verify_inspection(31, 2, business_id="OFFICE-1",
            registry_review_token=plan["reviewToken"], confirm_establishment=True)
    else:
        result, error = registry.confirm_pin_compliance(30, "OFFICE-1", 2,
            registry_review_token=plan["reviewToken"], confirm_establishment=True)
    assert result is None and isinstance(error, GreenRegistryLinkError)
    assert snapshot(db) == before
    fields = {"businessName": "Office-confirmed name"}
    if path == "inspection":
        result, error = inspections.verify_inspection(31, 2, business_id="OFFICE-1",
            registry_review_token=plan["reviewToken"], confirm_establishment=True,
            registry_fields=fields)
    else:
        result, error = registry.confirm_pin_compliance(30, "OFFICE-1", 2,
            registry_review_token=plan["reviewToken"], confirm_establishment=True,
            registry_fields=fields)
    assert error is None, error
    assert db.rows("SELECT businessName FROM official_registry") == [{"businessName": "Office-confirmed name"}]
    assert db.rows("SELECT source,latitude,longitude FROM geospatial_logs") == [
        {"source": "detection", "latitude": 13.9667, "longitude": 121.1167}]
    before = snapshot(db)
    if path == "inspection":
        result, error = inspections.verify_inspection(31, 2, business_id="OFFICE-1",
            registry_review_token=plan["reviewToken"], confirm_establishment=True,
            registry_fields=fields)
    else:
        result, error = registry.confirm_pin_compliance(30, "OFFICE-1", 2,
            registry_review_token=plan["reviewToken"], confirm_establishment=True,
            registry_fields=fields)
    assert error is None and result.get("alreadyVerified", result.get("alreadyConfirmed"))
    assert snapshot(db) == before


@pytest.mark.parametrize("path", ["inspection", "office"])
def test_registry_record_appearing_after_preview_requires_fresh_review(path, db):
    db.db.execute("DELETE FROM official_registry")
    if path == "office":
        db.db.execute("DELETE FROM inspection_reports")
    db.commit()
    plan, error = review(path, "OFFICE-1")
    assert error is None and not plan["registryExists"]
    db.db.execute("""INSERT INTO official_registry
        (businessID,businessName,barangayID,applicationStatus)
        VALUES ('OFFICE-1','FIELD SHOP',1,'Pending')""")
    db.commit()
    before = snapshot(db)
    if path == "inspection":
        result, error = inspections.verify_inspection(31, 2, business_id="OFFICE-1",
            registry_review_token=plan["reviewToken"], confirm_establishment=True)
    else:
        result, error = registry.confirm_pin_compliance(30, "OFFICE-1", 2,
            registry_review_token=plan["reviewToken"], confirm_establishment=True)
    assert result is None and error.conflict
    assert snapshot(db) == before


@pytest.mark.parametrize("path", ["inspection", "office"])
def test_conflict_and_stale_review_do_not_write(path, db):
    if path == "office":
        db.db.execute("DELETE FROM inspection_reports")
        db.commit()
    plan, error = review(path, "OFFICIAL-1")
    assert error is None
    db.db.execute("UPDATE official_registry SET businessAddress='Changed' WHERE businessID='OFFICIAL-1'")
    db.commit()
    before = snapshot(db)
    if path == "inspection":
        result, error = inspections.verify_inspection(31, 2, business_id="OFFICIAL-1",
            registry_review_token=plan["reviewToken"], confirm_establishment=True)
    else:
        result, error = registry.confirm_pin_compliance(30, "OFFICIAL-1", 2,
            registry_review_token=plan["reviewToken"], confirm_establishment=True)
    assert result is None and error.conflict
    assert snapshot(db) == before
    db.db.execute("UPDATE official_registry SET confirmedLogID=99")
    db.commit()
    before = snapshot(db)
    result, error = review(path, "OFFICIAL-1")
    assert result is None and error.conflict
    assert snapshot(db) == before


def test_office_refuses_active_inspection_without_discarding_assignment(db):
    before = snapshot(db)
    result, error = registry.preview_pin_compliance(30, "OFFICIAL-1")
    assert result is None and error.conflict
    assert snapshot(db) == before


@pytest.mark.parametrize("path", ["inspection", "office"])
def test_pin_already_linked_to_different_id_is_refused(path, db):
    db.db.execute("UPDATE geospatial_logs SET businessID='OTHER-ID' WHERE logID=30")
    db.commit()
    before = snapshot(db)
    result, error = review(path, "OFFICIAL-1")
    assert result is None and error.conflict
    assert snapshot(db) == before


@pytest.mark.parametrize("path", ["inspection", "office"])
def test_repeat_confirmation_has_no_additional_audit(path, db):
    if path == "office":
        db.db.execute("DELETE FROM inspection_reports")
        db.commit()
    plan, error = review(path, "OFFICIAL-1")
    assert error is None
    if path == "inspection":
        result, error = inspections.verify_inspection(31, 2, business_id="OFFICIAL-1",
            registry_review_token=plan["reviewToken"], confirm_establishment=True)
    else:
        result, error = registry.confirm_pin_compliance(30, "OFFICIAL-1", 2,
            registry_review_token=plan["reviewToken"], confirm_establishment=True)
    assert error is None, error
    before = snapshot(db)
    if path == "inspection":
        result, error = inspections.verify_inspection(31, 2, business_id="OFFICIAL-1",
            registry_review_token=plan["reviewToken"], confirm_establishment=True)
    else:
        result, error = registry.confirm_pin_compliance(30, "OFFICIAL-1", 2,
            registry_review_token=plan["reviewToken"], confirm_establishment=True)
    assert error is None and result.get("alreadyVerified", result.get("alreadyConfirmed"))
    assert snapshot(db) == before


@pytest.mark.parametrize("path", ["inspection", "office"])
def test_audit_failure_rolls_back_link_and_green(path, db):
    if path == "office":
        db.db.execute("DELETE FROM inspection_reports")
        db.commit()
    plan, error = review(path, "OFFICIAL-1")
    assert error is None
    before = snapshot(db)
    module, audit = (inspections, "log_inspection_event") if path == "inspection" else (registry, "record_enforcement_event")
    with patch.object(module, audit, side_effect=RuntimeError("isolated audit failure")):
        if path == "inspection":
            result, error = inspections.verify_inspection(31, 2, business_id="OFFICIAL-1",
                registry_review_token=plan["reviewToken"], confirm_establishment=True)
        else:
            result, error = registry.confirm_pin_compliance(30, "OFFICIAL-1", 2,
                registry_review_token=plan["reviewToken"], confirm_establishment=True)
    assert result is None and error
    assert snapshot(db) == before


@pytest.mark.parametrize("path", [
    "/api/inspections/31/green-registry-link?businessID=OFFICIAL-1",
    "/api/inspections/31/verify",
    "/api/flags/30/compliance-review?businessID=OFFICIAL-1",
    "/api/flags/30/confirm-compliance",
])
def test_both_routes_keep_admin_authorization(path):
    app = Flask(__name__)
    app.config["JWT_SECRET_KEY"] = "offline-green-link-test-key-at-least-32-chars"
    JWTManager(app)
    app.register_blueprint(inspections_bp, url_prefix="/api/inspections")
    app.register_blueprint(flags_bp, url_prefix="/api/flags")
    method = "get" if "review" in path or "green-registry-link" in path else "post"
    client = app.test_client()
    assert getattr(client, method)(path).status_code == 401
    with app.app_context():
        token = create_access_token(identity="9", additional_claims={"role": "Inspector"})
    with patch("api.middleware.decorators._verify_user_and_session", return_value=None):
        assert getattr(client, method)(path, headers={"Authorization": f"Bearer {token}"}).status_code == 403
