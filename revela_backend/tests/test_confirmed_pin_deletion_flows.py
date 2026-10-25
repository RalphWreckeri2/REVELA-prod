"""Delete entry points against isolated synthetic rows; no configured DB access."""
from unittest.mock import patch

import pytest
from flask import Flask
from flask_jwt_extended import JWTManager, create_access_token

from api.flags import routes as flag_routes, service as flags
from api.inspections import service as inspections
from api.registry import service as registry
from test_map_compliance import FeatureDB


@pytest.fixture
def db():
    database = FeatureDB()
    with (patch.object(registry, "mysql", database),
          patch.object(inspections, "mysql", database),
          patch.object(flags, "mysql", database),
          patch("api.notifications.hub.publish_to_admins")):
        yield database
    database.close()


def confirmed_pin(db, path):
    db.db.execute("""INSERT INTO geospatial_logs
        (logID,barangayID,detectedName,flagColor,latitude,longitude,source)
        VALUES (30,1,'ORIGINAL SHOP','Yellow',13.9667,121.1167,'detection')""")
    if path == "inspection":
        db.db.execute("""INSERT INTO inspection_reports
            (reportID,targetID,targetType,userID,verificationStatus,inspectionResult)
            VALUES (31,30,'geospatial_log',9,'Submitted','Green')""")
    db.commit()
    if path == "office":
        review, error = registry.preview_pin_compliance(30, "OFFICE-030")
        assert error is None
        result, error = registry.confirm_pin_compliance(30, "OFFICE-030", 2,
            registry_review_token=review["reviewToken"], confirm_establishment=True)
    else:
        review, error = inspections.preview_green_registry_link(31, "OFFICE-030")
        assert error is None
        result, error = inspections.verify_inspection(31, 2, business_id="OFFICE-030",
            registry_review_token=review["reviewToken"], confirm_establishment=True)
    assert error is None, error
    assert result["businessID"] == "OFFICE-030"
    assert db.rows("SELECT confirmedLogID FROM official_registry") == [{"confirmedLogID": 30}]


def snapshot(db):
    return [db.rows(f"SELECT * FROM {table}") for table in (
        "official_registry", "geospatial_logs", "inspection_reports",
        "inspection_lifecycle_events", "enforcement_events")]


@pytest.mark.parametrize("path", ["office", "inspection"])
def test_delete_only_original_pin_preserves_registry_and_audit(db, path):
    confirmed_pin(db, path)
    original_audit = (db.rows("SELECT * FROM inspection_lifecycle_events"),
                      db.rows("SELECT * FROM enforcement_events"))
    db.calls.clear()
    ok, error = flags.delete_flag(30, actor_role="Admin")
    assert ok and error is None, error
    assert db.rows("SELECT * FROM geospatial_logs") == []
    assert db.rows("SELECT * FROM inspection_reports") == []
    assert (db.rows("SELECT * FROM inspection_lifecycle_events"),
            db.rows("SELECT * FROM enforcement_events")) == original_audit
    assert db.rows("SELECT businessID,confirmedLogID,latitude,longitude FROM official_registry") == [
        {"businessID": "OFFICE-030", "confirmedLogID": None,
         "latitude": 13.9667, "longitude": 121.1167}]
    statements = [sql for sql, _ in db.calls]
    assert next(i for i, sql in enumerate(statements) if "UPDATE official_registry SET confirmedLogID = NULL" in sql) < next(
        i for i, sql in enumerate(statements) if "DELETE FROM geospatial_logs" in sql)
    assert not any("DELETE FROM official_registry" in sql for sql in statements)


@pytest.mark.parametrize("path", ["office", "inspection"])
def test_delete_business_clears_link_then_deletes_its_original_pin(db, path):
    confirmed_pin(db, path)
    audit_before = (db.rows("SELECT * FROM inspection_lifecycle_events"),
                    db.rows("SELECT * FROM enforcement_events"))
    ok, error = registry.delete_business("OFFICE-030", actor_role="Admin")
    assert ok and error is None, error
    assert db.rows("SELECT * FROM official_registry") == []
    assert db.rows("SELECT * FROM geospatial_logs") == []
    assert db.rows("SELECT * FROM inspection_reports") == []
    assert (db.rows("SELECT * FROM inspection_lifecycle_events"),
            db.rows("SELECT * FROM enforcement_events")) == audit_before


@pytest.mark.parametrize("entry", ["map", "registry"])
def test_failure_after_link_release_restores_all_related_rows(db, entry):
    confirmed_pin(db, "inspection")
    before = snapshot(db)
    original_cursor = db.cursor

    def failing_cursor():
        cursor = original_cursor()
        execute = cursor.execute

        def fail_pin_delete(sql, params=()):
            if "DELETE FROM geospatial_logs" in sql:
                raise RuntimeError(1451, "isolated FK failure after release")
            return execute(sql, params)

        cursor.execute = fail_pin_delete
        return cursor

    with patch.object(db, "cursor", side_effect=failing_cursor):
        result, error = (flags.delete_flag(30, actor_role="Admin") if entry == "map"
                         else registry.delete_business("OFFICE-030", actor_role="Admin"))
    assert not result and error
    assert "isolated FK failure" not in str(error)
    assert snapshot(db) == before


def test_map_delete_endpoint_removes_pin_without_deleting_registry(db):
    confirmed_pin(db, "office")
    app = Flask(__name__)
    app.config["JWT_SECRET_KEY"] = "isolated-pin-delete-test-key-at-least-32-chars"
    JWTManager(app)
    app.register_blueprint(flag_routes.flags_bp, url_prefix="/api/flags")
    with app.app_context():
        token = create_access_token(identity="2", additional_claims={"role": "Admin"})
    with patch("api.middleware.decorators._verify_user_and_session", return_value=None):
        response = app.test_client().delete("/api/flags/30",
            headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    assert db.rows("SELECT businessID,confirmedLogID FROM official_registry") == [
        {"businessID": "OFFICE-030", "confirmedLogID": None}]


def test_audit_repoint_failure_rolls_back_pin_link_and_report(db):
    confirmed_pin(db, "inspection")
    db.db.execute("""INSERT INTO geospatial_logs
        (logID,barangayID,businessID,detectedName,flagColor,source)
        VALUES (32,1,'OFFICE-030','Legacy registry marker','Green','registry')""")
    db.commit()
    before = snapshot(db)
    original_cursor = db.cursor

    def failing_cursor():
        cursor = original_cursor()
        execute = cursor.execute

        def fail_event_update(sql, params=()):
            if "UPDATE inspection_lifecycle_events SET targetLogID" in sql:
                raise RuntimeError("isolated lifecycle update failure")
            return execute(sql, params)

        cursor.execute = fail_event_update
        return cursor

    with patch.object(db, "cursor", side_effect=failing_cursor):
        result, error = flags.delete_flag(30, actor_role="Admin")
    assert not result and error
    assert snapshot(db) == before


def test_stale_virtual_pin_id_cannot_delete_a_now_linked_registry_business(db):
    db.db.execute("""INSERT INTO official_registry
        (businessID,businessName,barangayID,applicationStatus,confirmedLogID)
        VALUES ('88','ORIGINAL SHOP',1,'Active',30)""")
    db.db.execute("""INSERT INTO geospatial_logs
        (logID,barangayID,businessID,detectedName,flagColor,source)
        VALUES (30,1,'88','ORIGINAL SHOP','Green','detection')""")
    db.commit()
    before = snapshot(db)
    ok, error = flags.delete_flag(-88, actor_role="Admin")
    assert not ok and isinstance(error, flags.PinDeletionConflict)
    assert snapshot(db) == before
