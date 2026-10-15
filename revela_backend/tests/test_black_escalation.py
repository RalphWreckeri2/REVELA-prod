"""Admin escalation commits the real lock, pin and audit event together."""
from contextlib import ExitStack
from io import BytesIO
from unittest.mock import patch

import pytest
from flask import Flask
from flask_jwt_extended import JWTManager, create_access_token

from api.flags import routes, service as flags
from api.models import geospatial
from api.registry import service as registry
from registry_sqlite import RegistryDB


@pytest.fixture
def db():
    database = RegistryDB()
    with ExitStack() as stack:
        for module in (flags, registry, geospatial):
            stack.enter_context(patch.object(module, "mysql", database))
        stack.enter_context(patch("api.notifications.hub.publish_to_admins"))
        yield database
    database.close()


def map_and_registry(db):
    payload, error = flags.get_flags()
    assert error is None
    assert payload["total"] == 1
    business, error = registry.get_business_by_id("B-1")
    assert error is None
    listing, error = registry.get_all_businesses()
    assert error is None
    return payload["data"][0], business, listing["data"][0]


def test_orange_level_one_escalates_on_map_and_registry_and_survives_sync(db):
    db.seed(level=1, color="Yellow", report=False)
    assert {row["flagColor"] for row in map_and_registry(db)} == {"Orange"}
    ok, error = flags.escalate_to_black(1, actor_user_id=2)
    assert error is None
    assert ok
    assert {row["flagColor"] for row in map_and_registry(db)} == {"Black"}
    row = db.rows("SELECT * FROM official_registry")[0]
    assert row["applicationStatus"] == "Revoked"
    state = db.rows(
        "SELECT * FROM enforcement_state WHERE subjectType='business'")[0]
    assert state["warningLevel"] == 1
    assert state["blackLocked"] == 1
    assert state["blackLockedAt"] is not None
    assert state["blackLockedBy"] == 2
    assert db.rows("""SELECT eventType, subjectType, subjectID, actorUserID,
        previousLevel, newLevel, previousBlack, newBlack FROM enforcement_events""") == [
        {"eventType": "black_locked", "subjectType": "business", "subjectID": "B-1",
         "actorUserID": 2, "previousLevel": 1, "newLevel": 1,
         "previousBlack": 0, "newBlack": 1}]
    before = db.rows("SELECT * FROM official_registry")
    state_before = db.rows("SELECT * FROM enforcement_state")
    with patch.object(registry, "_log_registry_places_summary"):
        summary, error = registry.sync_registry(BytesIO(
            b"Business ID,businessName,barangay,Status\nB-1,ACME,Barangay I,Active\n"), ".csv")
    assert error is None
    assert summary["skipped_black_lock"] == 1
    assert db.rows("SELECT * FROM official_registry") == before
    assert db.rows("SELECT * FROM enforcement_state") == state_before
    assert {row["flagColor"] for row in map_and_registry(db)} == {"Black"}


@pytest.mark.parametrize("level", [0, 1, 2, 3])
@pytest.mark.parametrize("status", ["Pending", "Expired"])
def test_escalation_needs_neither_third_warning_nor_inspection(db, status, level):
    db.seed(status=status, level=level, report=False)
    ok, error = flags.escalate_to_black(1, actor_user_id=2)
    assert error is None
    assert ok
    assert db.rows("SELECT blackLocked FROM enforcement_state WHERE subjectType='business'") == [
        {"blackLocked": 1}]


@pytest.mark.parametrize("verification_status", [None, "Assigned", "Reassigned", "In Progress", "Submitted"])
def test_escalation_is_refused_while_pin_inspection_is_open(db, verification_status):
    db.seed(status="Pending", level=1, color="Orange", report=False)
    db.db.execute("""INSERT INTO inspection_reports
        (reportID, targetID, targetType, userID, verificationStatus)
        VALUES (8, 1, 'geospatial_log', 9, ?)""", (verification_status,))
    db.commit()
    registry_before = db.rows("SELECT * FROM official_registry")
    pin_before = db.rows("SELECT * FROM geospatial_logs")

    ok, error = flags.escalate_to_black(1, actor_user_id=2)

    assert not ok
    assert isinstance(error, flags.FlagEscalationConflict)
    assert "while an inspection is still open" in str(error)
    assert db.rows("SELECT * FROM official_registry") == registry_before
    assert db.rows("SELECT * FROM geospatial_logs") == pin_before
    assert db.rows("SELECT * FROM enforcement_events") == []


def test_escalation_checks_other_pins_linked_to_same_business(db):
    db.seed(status="Pending", level=1, color="Orange", report=False)
    db.db.execute("""INSERT INTO geospatial_logs
        (logID, businessID, barangayID, detectedName, flagColor)
        VALUES (2, 'B-1', 1, 'ACME', 'Orange')""")
    db.db.execute("""INSERT INTO inspection_reports
        (reportID, targetID, targetType, userID, verificationStatus)
        VALUES (8, 2, 'geospatial_log', 9, 'In Progress')""")
    db.commit()

    ok, error = flags.escalate_to_black(1, actor_user_id=2)

    assert not ok
    assert isinstance(error, flags.FlagEscalationConflict)
    assert "while an inspection is still open" in str(error)
    assert db.rows("SELECT blackLocked FROM enforcement_state WHERE subjectType='business'") == [
        {"blackLocked": 0}]
    assert db.rows("SELECT eventType FROM enforcement_events") == []


@pytest.mark.parametrize("status,locked", [("Revoked", 0), ("Active", 1), ("Active", 0), ("Closed", 0)])
def test_black_green_and_purple_are_refused_without_writes(db, status, locked):
    db.seed(status=status, level=0, locked=locked, report=False)
    before = db.rows("SELECT * FROM official_registry")
    pin_before = db.rows("SELECT * FROM geospatial_logs")
    ok, error = flags.escalate_to_black(1, actor_user_id=2)
    assert not ok
    assert isinstance(error, flags.FlagEscalationConflict)
    assert db.rows("SELECT * FROM official_registry") == before
    assert db.rows("SELECT * FROM geospatial_logs") == pin_before
    assert db.rows("SELECT * FROM enforcement_events") == []


def test_unregistered_pin_only_changes_the_pin(db):
    db.db.execute(
        "INSERT INTO geospatial_logs (logID, detectedName, flagColor) VALUES (1, 'NEW SHOP', 'Red')")
    db.commit()
    ok, error = flags.escalate_to_black(1, actor_user_id=2)
    assert error is None
    assert ok
    assert db.rows("SELECT flagColor FROM geospatial_logs") == [
        {"flagColor": "Black"}]
    assert db.rows("SELECT * FROM official_registry") == []
    assert db.rows("SELECT subjectType, subjectID, blackLocked FROM enforcement_state") == [
        {"subjectType": "geospatial_log", "subjectID": "1", "blackLocked": 1}]
    assert db.rows("SELECT subjectType, subjectID, eventType FROM enforcement_events") == [
        {"subjectType": "geospatial_log", "subjectID": "1", "eventType": "black_locked"}]


def test_virtual_registry_flag_gets_real_lock_and_black_color_without_a_pin(db):
    db.seed(report=False)
    db.db.execute("DELETE FROM geospatial_logs")
    db.db.execute("UPDATE official_registry SET businessID = '5'")
    db.commit()
    ok, error = flags.escalate_to_black(-5, actor_user_id=2)
    assert error is None
    assert ok
    payload, error = flags.get_flags()
    assert error is None
    assert payload["data"][0]["flagColor"] == "Black"
    business, error = registry.get_business_by_id("5")
    assert error is None
    assert business["flagColor"] == "Black"
    assert business["blackLocked"] == 1
    assert db.rows("SELECT blackLocked FROM enforcement_state WHERE subjectType='business'") == [
        {"blackLocked": 1}]


def test_missing_ladder_fails_clearly_without_writes():
    database = RegistryDB()
    try:
        database.db.execute("DROP TABLE enforcement_state")
        database.commit()
        with patch.object(flags, "mysql", database):
            ok, error = flags.escalate_to_black(1, actor_user_id=2)
        assert not ok
        assert isinstance(error, flags.FlagEscalationConflict)
        assert "enforcement_state is unavailable" in str(error)
        assert not any(sql.lstrip().startswith(
            ("UPDATE", "INSERT", "DELETE")) for sql, _ in database.calls)
    finally:
        database.close()


def test_audit_failure_rolls_back_lock_and_pin(db):
    db.seed(report=False)
    db.db.execute("DROP TABLE enforcement_events")
    db.commit()
    ok, error = flags.escalate_to_black(1, actor_user_id=2)
    assert not ok
    assert "enforcement_events" in error
    assert db.rows("SELECT applicationStatus FROM official_registry") == [
        {"applicationStatus": "Pending"}]
    assert db.rows("SELECT blackLocked FROM enforcement_state WHERE subjectType='business'") == [
        {"blackLocked": 0}]
    assert db.rows("SELECT flagColor FROM geospatial_logs") == [
        {"flagColor": "Orange"}]


def test_non_admin_service_call_is_forbidden(db):
    db.seed(report=False)
    ok, error = flags.escalate_to_black(1, actor_user_id=9)
    assert not ok
    assert isinstance(error, flags.FlagEscalationForbidden)
    assert db.rows("SELECT blackLocked FROM enforcement_state WHERE subjectType='business'") == [
        {"blackLocked": 0}]


@pytest.mark.parametrize("role,user_id,expected", [("Admin", 2, 200), ("Inspector", 9, 403)])
def test_http_route_checks_role_and_records_acting_admin(db, role, user_id, expected):
    db.seed(report=False)
    app = Flask(__name__)
    app.config["JWT_SECRET_KEY"] = "isolated-registry-test-secret-key-32-chars"
    JWTManager(app)
    app.register_blueprint(routes.flags_bp, url_prefix="/api/flags")
    with app.app_context():
        token = create_access_token(identity=str(
            user_id), additional_claims={"role": role})
    with patch("api.middleware.decorators._verify_user_and_session", return_value=None):
        response = app.test_client().patch(
            "/api/flags/1/black", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == expected
    assert db.rows("SELECT blackLocked FROM enforcement_state WHERE subjectType='business'")[
        0]["blackLocked"] == int(expected == 200)
    if expected == 200:
        assert db.rows("SELECT blackLockedBy FROM enforcement_state WHERE subjectType='business'")[
            0]["blackLockedBy"] == user_id
