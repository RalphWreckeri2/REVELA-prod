"""Clear Warning eligibility comes from current business state, not a loaded page."""
from unittest.mock import patch

import pytest
from flask import Flask
from flask_jwt_extended import JWTManager, create_access_token

from api.inspections import service as inspections
from api.registry import service as registry, routes
from registry_sqlite import RegistryDB


@pytest.fixture
def db():
    database = RegistryDB()
    with patch.object(inspections, "mysql", database), patch.object(registry, "mysql", database), patch("api.notifications.hub.publish_to_admins"):
        yield database
    database.close()


def report_one():
    payload, error = inspections.get_all_inspections()
    assert error is None
    return next(row for row in payload["data"] if row["reportID"] == 1)


def test_clear_refreshes_actual_inspection_payload_without_changing_permit_status(db):
    db.seed()
    before = report_one()
    assert before["warningLevel"] == 1
    assert before["hasNonVerifiedInspection"] == 0
    result, error = registry.clear_warning("B-1", 2)
    assert error is None
    assert result["warningCleared"]
    after = report_one()
    assert after["verificationStatus"] == "Verified"
    assert after["warningLevel"] == 0
    assert after["flagColor"] == "Yellow"
    assert after["applicationStatus"] == "Pending"
    assert after["noticeLevel"] == 1  # The historical report is preserved.
    assert db.rows("SELECT noticeLevel FROM geospatial_logs") == [{"noticeLevel": 0}]


@pytest.mark.parametrize("pending_status", ["Assigned", "Reassigned", "Submitted", None])
@pytest.mark.parametrize("legacy", [False, True])
def test_non_verified_inspection_on_another_pin_blocks_clear(db, pending_status, legacy):
    db.seed()
    db.db.execute("""INSERT INTO geospatial_logs (logID, businessID, detectedName, barangayID, flagColor)
        VALUES (2, ?, 'ACME', 1, 'Orange')""", (None if legacy else "B-1",))
    db.db.execute("""INSERT INTO inspection_reports (reportID, targetID, userID, verificationStatus)
        VALUES (2, 2, 9, ?)""", (pending_status,))
    db.commit()
    assert report_one()["hasNonVerifiedInspection"] == 1
    result, error = registry.clear_warning("B-1", 2)
    assert result is None
    assert isinstance(error, registry.RegistryLadderConflict)
    assert db.rows("SELECT warningLevel FROM official_registry") == [{"warningLevel": 1}]


@pytest.mark.parametrize("role,status,expected", [("Admin", "Pending", 200), ("Inspector", "Pending", 403), ("Admin", "Revoked", 409)])
def test_existing_clear_route_enforces_role_and_maps_returned_typed_conflicts(db, role, status, expected):
    db.seed(status=status, locked=0)
    app = Flask(__name__)
    app.config["JWT_SECRET_KEY"] = "isolated-registry-test-secret-key-32-chars"
    JWTManager(app)
    app.register_blueprint(routes.registry_bp, url_prefix="/api/registry")
    with app.app_context():
        token = create_access_token(identity="2", additional_claims={"role": role})
    with patch("api.middleware.decorators._verify_user_and_session", return_value=None):
        response = app.test_client().post("/api/registry/B-1/clear-warning", json={}, headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == expected
    if expected == 409:
        assert response.get_json()["code"] == "warning_clear_refused"
    assert db.rows("SELECT applicationStatus FROM official_registry")[0]["applicationStatus"] == status


def test_revoked_without_lock_can_receive_the_existing_single_use_dispatch_grant(db):
    db.seed(status="Revoked", locked=0)
    result, error = registry.unlock_black_dispatch("B-1", 2)
    assert error is None
    assert result["blackDispatchUnlocked"] is True
    assert result["blackLocked"] is False
    assert db.rows("SELECT applicationStatus, blackLocked, blackDispatchUnlocked FROM official_registry") == [
        {"applicationStatus": "Revoked", "blackLocked": 0, "blackDispatchUnlocked": 1}]


@pytest.mark.parametrize("initial_status", ["Pending", "Expired", "Closed"])
@pytest.mark.parametrize("result_color", ["Yellow", "Red", "Purple", "Green", "Orange", "Black"])
def test_verified_yellow_red_or_purple_can_end_in_any_color(db, initial_status, result_color):
    db.seed(status=initial_status, level=0)
    notice = 1 if result_color == "Orange" else 0
    db.db.execute("UPDATE inspection_reports SET verificationStatus = 'Submitted', inspectionResult = ?, noticeLevel = ?", (result_color, notice))
    db.commit()
    result, error = inspections.verify_inspection(1, verified_by_user_id=2)
    assert error is None
    assert result["status"] == "Verified"
    assert report_one()["flagColor"] == result_color
    if result_color == "Black":
        # Existing verified-Black semantics: lock it, preserve permit status.
        row = db.rows("SELECT applicationStatus, blackLocked FROM official_registry")[0]
        assert row == {"applicationStatus": initial_status, "blackLocked": 1}
