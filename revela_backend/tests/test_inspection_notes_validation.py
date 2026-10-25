"""Final inspection remarks have one limit for the report and append-only event."""
from unittest.mock import MagicMock, patch

from flask import Flask
from flask_jwt_extended import JWTManager, create_access_token

from api.inspections.notes_policy import (
    InspectionNotesInvalid, MAX_INSPECTION_REMARKS_CHARACTERS, validate_inspection_notes,
)
from api.inspections import routes, service
from registry_sqlite import RegistryDB


def test_exact_boundary_and_generated_notice_prefixes():
    assert validate_inspection_notes("x" * 255) == "x" * 255
    assert validate_inspection_notes("[1st Notice Issued] " + "x" * (255 - len("[1st Notice Issued] ")))
    assert validate_inspection_notes("[Escalated to Black] " + "x" * (255 - len("[Escalated to Black] ")))
    assert MAX_INSPECTION_REMARKS_CHARACTERS == 255
    for text in ("x" * 256, "[1st Notice Issued] " + "x" * (256 - len("[1st Notice Issued] "))):
        try:
            validate_inspection_notes(text)
            assert False, "oversize notes must be refused"
        except InspectionNotesInvalid as error:
            assert "255" in str(error)


def test_oversize_direct_submission_refused_before_database_access():
    db = RegistryDB()
    try:
        db.seed()
        original = db.rows("SELECT * FROM inspection_reports")
        db.calls.clear()
        with patch.object(service, "mysql", db):
            result, error = service.submit_inspection(1, 9, "Green", notes="x" * 256)
        assert result is None and isinstance(error, InspectionNotesInvalid)
        assert not db.calls
        assert db.rows("SELECT * FROM inspection_reports") == original
        assert db.rows("SELECT * FROM inspection_lifecycle_events") == []
    finally:
        db.close()


def test_allowed_boundary_reaches_both_report_and_lifecycle_without_truncation():
    notes = "[1st Notice Issued] " + "a" * (255 - len("[1st Notice Issued] "))
    cursor = MagicMock()
    cursor.fetchone.side_effect = [
        {"reportID": 31, "targetID": 30, "userID": 9, "verificationStatus": "Assigned", "wasReassigned": 0},
        {"mins": 1}, {"submittedAt": None, "submissionReceivedAt": None},
        {"flagColor": "Yellow"},
    ]
    with (patch.object(service, "mysql") as mysql,
          patch.object(service, "_ensure_gps_columns"),
          patch.object(service, "get_latest_inspection_cycle_id", return_value=1),
          patch.object(service, "log_inspection_event") as log_event,
          patch("api.notifications.hub.publish_to_admins")):
        mysql.connection.cursor.return_value = cursor
        result, error = service.submit_inspection(30, 9, "Orange", notice_level=1,
            notes=notes, report_id=31)
        assert error is None and result["status"] == "Submitted"
        update_params = next(call.args[1] for call in cursor.execute.call_args_list
                             if "UPDATE inspection_reports" in call.args[0])
        assert update_params[2] == notes
        assert log_event.call_args.kwargs["remarks"] == notes
        mysql.connection.commit.assert_called_once()


def test_submission_route_returns_validation_message_not_a_server_error():
    app = Flask(__name__)
    app.config["JWT_SECRET_KEY"] = "isolated-inspection-notes-test-key-at-least-32-chars"
    JWTManager(app)
    app.register_blueprint(routes.inspections_bp, url_prefix="/api/inspections")
    with app.app_context():
        token = create_access_token(identity="9", additional_claims={"role": "Inspector"})
    with patch("api.middleware.decorators._verify_user_and_session", return_value=None), patch.object(
            service, "mysql", None):
        response = app.test_client().post("/api/inspections/submit",
            json={"logID": 1, "inspectionResult": "Green", "notes": "x" * 256},
            headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 400
    assert response.get_json()["code"] == "inspection_notes_invalid"
    assert "255" in response.get_json()["error"]
