"""Clear Warning eligibility comes from current business state, not a loaded page."""
from unittest.mock import patch

import pytest
from flask import Flask
from flask_jwt_extended import JWTManager, create_access_token

from api.inspections import service as inspections
from api.registry import service as registry, routes
from api.flags.routes import flags_bp
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
    assert db.rows("SELECT noticeLevel FROM geospatial_logs") == [
        {"noticeLevel": 0}]


def seed_unregistered_orange_pin(db, *, base_color="Red", locked=0, status="Verified"):
    db.db.execute("""INSERT INTO geospatial_logs
        (logID, businessID, barangayID, detectedName, flagColor, noticeLevel)
        VALUES (20, NULL, 1, 'FIELD SHOP', 'Orange', 2)""")
    db.db.execute("""INSERT INTO enforcement_state
        (subjectType, subjectID, warningLevel, warningBaseColor, blackLocked)
        VALUES ('geospatial_log', '20', 2, ?, ?)""", (base_color, locked))
    db.db.execute("""INSERT INTO inspection_reports
        (reportID, targetID, targetType, userID, verificationStatus, inspectionResult)
        VALUES (20, 20, 'geospatial_log', 9, ?, 'Orange')""", (status,))
    db.commit()


def test_unregistered_pin_warning_survives_later_green_and_clears_to_base(db):
    db.seed()
    db.db.execute("""INSERT INTO geospatial_logs
        (logID, businessID, barangayID, detectedName, flagColor, noticeLevel)
        VALUES (20, NULL, 1, 'FIELD SHOP', 'Yellow', 0)""")
    db.db.execute("""INSERT INTO inspection_reports
        (reportID, targetID, targetType, userID, verificationStatus, inspectionResult, noticeLevel)
        VALUES (20, 20, 'geospatial_log', 9, 'Submitted', 'Orange', 1)""")
    db.commit()

    result, error = inspections.verify_inspection(20, verified_by_user_id=2)
    assert error is None
    assert result["status"] == "Verified"
    assert db.rows("SELECT warningLevel, warningBaseColor FROM enforcement_state WHERE subjectID = '20'") == [
        {"warningLevel": 1, "warningBaseColor": "Yellow"}]

    db.db.execute("""INSERT INTO inspection_reports
        (reportID, targetID, targetType, userID, verificationStatus, inspectionResult, noticeLevel)
        VALUES (21, 20, 'geospatial_log', 9, 'Submitted', 'Green', 1)""")
    db.commit()
    # A Green finding alone no longer verifies an unregistered pin. It needs
    # an explicit official ID review, then retains its existing warning.
    db.db.execute("UPDATE geospatial_logs SET latitude=13.9667, longitude=121.1167 WHERE logID=20")
    db.commit()
    review, error = inspections.preview_green_registry_link(21, "FIELD-20")
    assert error is None
    result, error = inspections.verify_inspection(21, verified_by_user_id=2,
        business_id="FIELD-20", confirm_establishment=True, registry_review_token=review["reviewToken"])
    assert error is None
    payload, error = inspections.get_all_inspections()
    assert error is None
    latest = next(row for row in payload["data"] if row["reportID"] == 21)
    assert latest["flagColor"] == "Orange"
    assert latest["warningLevel"] == 1
    assert latest["warningBaseColor"] == "Yellow"

    result, error = registry.clear_warning("FIELD-20", 2, "Complied")
    assert error is None
    assert result["warningCleared"]
    assert db.rows("SELECT flagColor, noticeLevel FROM geospatial_logs WHERE logID = 20") == [
        {"flagColor": "Green", "noticeLevel": 0}]


def test_unregistered_pin_clear_resets_warning_restores_base_and_audits_reason(db):
    db.seed()
    seed_unregistered_orange_pin(db, base_color="Yellow")

    result, error = registry.clear_pin_warning(20, 2, "Complied")

    assert error is None
    assert result == {
        "logID": 20,
        "subjectType": "geospatial_log",
        "warningCleared": True,
        "previousWarningLevel": 2,
        "warningLevel": 0,
        "flagColor": "Yellow",
    }
    assert db.rows("SELECT flagColor, noticeLevel FROM geospatial_logs WHERE logID = 20") == [
        {"flagColor": "Yellow", "noticeLevel": 0}]
    assert db.rows("SELECT warningLevel, warningBaseColor, warningClearReason FROM enforcement_state WHERE subjectID = '20'") == [
        {"warningLevel": 0, "warningBaseColor": None, "warningClearReason": "Complied"}]
    assert db.rows("SELECT subjectType, subjectID, eventType, reason, previousLevel, newLevel FROM enforcement_events") == [
        {"subjectType": "geospatial_log", "subjectID": "20", "eventType": "warning_cleared",
         "reason": "Complied", "previousLevel": 2, "newLevel": 0}]


@pytest.mark.parametrize("changes, message", [
    ({"base_color": None}, "pre-warning color is unknown"),
    ({"locked": 1}, "Black-locked"),
])
def test_unregistered_pin_clear_refuses_unsafe_state_without_writes(db, changes, message):
    db.seed()
    seed_unregistered_orange_pin(db, **changes)

    result, error = registry.clear_pin_warning(20, 2, "test")

    assert result is None
    assert isinstance(error, registry.RegistryLadderConflict)
    assert message in str(error)
    assert db.rows("SELECT warningLevel FROM enforcement_state WHERE subjectID = '20'") == [
        {"warningLevel": 2}]
    assert db.rows("SELECT flagColor FROM geospatial_logs WHERE logID = 20") == [
        {"flagColor": "Orange"}]
    assert db.rows("SELECT * FROM enforcement_events") == []


def test_unregistered_pin_clear_refuses_an_open_inspection(db):
    db.seed()
    seed_unregistered_orange_pin(db, status="In Progress")

    result, error = registry.clear_pin_warning(20, 2)

    assert result is None
    assert isinstance(error, registry.RegistryLadderConflict)
    assert "not yet Verified" in str(error)
    assert db.rows("SELECT * FROM enforcement_events") == []


def test_unregistered_pin_clear_route_is_admin_only_and_uses_pin_id(db):
    db.seed()
    seed_unregistered_orange_pin(db)
    app = Flask(__name__)
    app.config["JWT_SECRET_KEY"] = "isolated-registry-test-secret-key-32-chars"
    JWTManager(app)
    app.register_blueprint(flags_bp, url_prefix="/api/flags")
    with app.app_context():
        token = create_access_token(
            identity="2", additional_claims={"role": "Admin"})
    with patch("api.middleware.decorators._verify_user_and_session", return_value=None):
        response = app.test_client().post(
            "/api/flags/20/clear-warning", json={"reason": "Verified"},
            headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    assert response.get_json()["logID"] == 20
    assert db.rows("SELECT reason FROM enforcement_events") == [
        {"reason": "Verified"}]


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
    assert db.rows("SELECT warningLevel FROM official_registry") == [
        {"warningLevel": 1}]


@pytest.mark.parametrize("role,status,expected", [("Admin", "Pending", 200), ("Inspector", "Pending", 403), ("Admin", "Revoked", 409)])
def test_existing_clear_route_enforces_role_and_maps_returned_typed_conflicts(db, role, status, expected):
    db.seed(status=status, locked=0)
    app = Flask(__name__)
    app.config["JWT_SECRET_KEY"] = "isolated-registry-test-secret-key-32-chars"
    JWTManager(app)
    app.register_blueprint(routes.registry_bp, url_prefix="/api/registry")
    with app.app_context():
        token = create_access_token(
            identity="2", additional_claims={"role": role})
    with patch("api.middleware.decorators._verify_user_and_session", return_value=None):
        response = app.test_client().post("/api/registry/B-1/clear-warning", json={},
                                          headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == expected
    if expected == 409:
        assert response.get_json()["code"] == "warning_clear_refused"
    assert db.rows("SELECT applicationStatus FROM official_registry")[
        0]["applicationStatus"] == status


def test_revoked_without_lock_cannot_receive_a_dispatch_grant(db):
    db.seed(status="Revoked", locked=0)
    result, error = registry.unlock_black_dispatch("B-1", 2)
    assert result is None
    assert isinstance(error, registry.RegistryLadderConflict)
    assert db.rows("SELECT applicationStatus, blackLocked, blackDispatchUnlocked FROM official_registry") == [
        {"applicationStatus": "Revoked", "blackLocked": 0, "blackDispatchUnlocked": 0}]


@pytest.mark.parametrize("initial_status", ["Pending", "Expired", "Closed"])
@pytest.mark.parametrize("result_color", ["Yellow", "Red", "Purple", "Green", "Orange", "Black"])
def test_verified_yellow_red_or_purple_can_end_in_any_color(db, initial_status, result_color):
    db.seed(status=initial_status, level=0)
    notice = 1 if result_color == "Orange" else 0
    db.db.execute(
        "UPDATE inspection_reports SET verificationStatus = 'Submitted', inspectionResult = ?, noticeLevel = ?", (result_color, notice))
    db.commit()
    args = {}
    if result_color == "Green":
        review, error = inspections.preview_green_registry_link(1, "B-1")
        assert error is None
        args = dict(business_id="B-1", confirm_establishment=True, registry_review_token=review["reviewToken"])
    result, error = inspections.verify_inspection(1, verified_by_user_id=2, **args)
    assert error is None
    assert result["status"] == "Verified"
    assert report_one()["flagColor"] == result_color
    if result_color == "Black":
        # Existing verified-Black semantics: lock it, preserve permit status.
        row = db.rows("""SELECT r.applicationStatus, es.blackLocked
                         FROM official_registry r JOIN enforcement_state es
                         ON es.subjectType='business' AND es.subjectID=r.businessID""")[0]
        assert row == {"applicationStatus": initial_status, "blackLocked": 1}
