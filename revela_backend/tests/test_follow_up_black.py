"""Follow-up uses the real assignment gate and current Inspection payload."""
from unittest.mock import patch

import pytest
from flask import Flask

from api.inspections import routes, service as inspections
from registry_sqlite import RegistryDB


@pytest.fixture
def db():
    database = RegistryDB()
    with patch.object(inspections, "mysql", database), patch("api.notifications.hub.publish_to_admins"):
        yield database
    database.close()


@pytest.mark.parametrize("status,locked", [("Revoked", 0), ("Active", 1)])
def test_current_black_payload_and_typed_follow_up_refusal(db, status, locked):
    db.seed(status=status, locked=locked, color="Yellow")
    payload, error = inspections.get_all_inspections()
    assert error is None
    report = payload["data"][0]
    assert report["flagColor"] == "Black"
    assert report["inspectionResult"] == "Orange"
    assert report["blackDispatchUnlocked"] == 0
    before = db.rows("SELECT * FROM inspection_reports")
    result, error = inspections.assign_inspection(1, 9, None, 2)
    assert result is None
    assert isinstance(error, inspections.BlackInspectionAssignmentConflict)
    assert db.rows("SELECT * FROM inspection_reports") == before
    assert db.rows("SELECT * FROM inspection_lifecycle_events") == []


@pytest.mark.parametrize("legacy", [False, True])
def test_black_follow_up_accepts_grant_for_linked_and_legacy_pins(db, legacy):
    db.seed(status="Revoked", locked=0)
    db.db.execute("UPDATE official_registry SET blackDispatchUnlocked = 1")
    if legacy:
        db.db.execute("UPDATE geospatial_logs SET businessID = NULL")
    db.commit()
    payload, error = inspections.get_all_inspections()
    assert error is None
    assert payload["data"][0]["flagColor"] == "Black"
    assert payload["data"][0]["blackDispatchUnlocked"] == 1
    result, error = inspections.assign_inspection(1, 9, None, 2)
    assert error is None
    assert result["status"] == "Reassigned"


@pytest.mark.parametrize("status,level", [("Pending", 0), ("Expired", 0), ("Closed", 0), ("Pending", 1)])
def test_follow_up_accepts_other_inspectable_colors_without_notice_restriction(db, status, level):
    db.seed(status=status, level=level)
    result, error = inspections.assign_inspection(1, 9, None, 2)
    assert error is None
    assert result["status"] == "Reassigned"


def test_green_assignment_remains_blocked(db):
    db.seed(status="Active", level=0)
    result, error = inspections.assign_inspection(1, 9, None, 2)
    assert result is None
    assert isinstance(error, inspections.InspectionAssignmentConflict)
    assert db.rows("SELECT verificationStatus FROM inspection_reports") == [{"verificationStatus": "Verified"}]


@pytest.mark.parametrize("message", ["Black", "reworded", ""])
def test_black_gate_http_status_is_based_on_type_not_message(message):
    app = Flask(__name__)
    with patch.object(routes, "assign_inspection", return_value=(None, inspections.BlackInspectionAssignmentConflict(message))), patch.object(routes, "get_jwt_identity", return_value="2"):
        with app.test_request_context("/api/inspections/assign", method="POST", json={"logID": 1, "userID": 9}):
            response, status = routes.assign.__wrapped__()
    assert status == 409
    assert response.get_json()["code"] == "black_dispatch_locked"
