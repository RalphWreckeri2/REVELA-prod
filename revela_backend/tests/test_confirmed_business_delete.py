"""Isolated deletion guards; never connects to the application database."""
from unittest.mock import MagicMock, patch

import pytest
from flask import Flask
from flask_jwt_extended import JWTManager, create_access_token

from api.registry import routes, service as registry
from registry_sqlite import RegistryDB


def test_confirmed_business_can_be_deleted_with_its_pin_and_reports():
    db = RegistryDB()
    try:
        db.seed(status="Active", level=0, locked=0, color="Green")
        db.db.execute("UPDATE official_registry SET confirmedLogID=1 WHERE businessID='B-1'")
        db.commit()
        db.calls.clear()
        with patch.object(registry, "mysql", db), patch("api.notifications.hub.publish_to_admins"):
            ok, error = registry.delete_business("B-1", actor_role="Admin")
            assert ok and error is None
        assert db.rows("SELECT * FROM official_registry") == []
        assert db.rows("SELECT * FROM geospatial_logs") == []
        assert db.rows("SELECT * FROM inspection_reports") == []
        writes = [sql for sql, _ in db.calls]
        assert next(i for i, sql in enumerate(writes) if "UPDATE official_registry SET confirmedLogID = NULL" in sql) < next(
            i for i, sql in enumerate(writes) if "DELETE FROM geospatial_logs" in sql)
    finally:
        db.close()


def test_unconfirmed_active_business_still_deletes():
    db = RegistryDB()
    try:
        db.seed(status="Active", level=0, locked=0)
        with patch.object(registry, "mysql", db), patch("api.notifications.hub.publish_to_admins"):
            ok, error = registry.delete_business("B-1", actor_role="Admin")
        assert ok and error is None
        assert db.rows("SELECT * FROM official_registry") == []
        assert db.rows("SELECT * FROM geospatial_logs") == []
    finally:
        db.close()


def test_racing_fk_refusal_rolls_back_and_never_leaks_database_message():
    cursor = MagicMock()
    cursor.fetchall.side_effect = [[{"Field": "confirmedLogID"}], [{"logID": 1}], [{"Field": "confirmedLogID"}]]
    cursor.fetchone.side_effect = [
        {"businessID": "B-1", "barangayID": 1, "placeID": None, "confirmedLogID": None},
        {"blackLocked": 0, "applicationStatus": "Active"},
        {"logID": 1}, None,
    ]

    def execute(sql, *_args):
        if "DELETE FROM geospatial_logs" in sql:
            raise RuntimeError(1451, "private database FK detail")

    cursor.execute.side_effect = execute
    with patch.object(registry, "mysql") as mysql:
        mysql.connection.cursor.return_value = cursor
        ok, error = registry.delete_business("B-1", actor_role="Admin")
        assert not ok and isinstance(error, registry.RegistryDeletionConflict)
        assert "private database" not in str(error)
        mysql.connection.rollback.assert_called_once()
        mysql.connection.commit.assert_not_called()


def test_confirmed_registry_delete_route_succeeds():
    db = RegistryDB()
    try:
        db.seed(status="Active", level=0, locked=0, color="Green")
        db.db.execute("UPDATE official_registry SET confirmedLogID=1 WHERE businessID='B-1'")
        db.commit()
        app = Flask(__name__)
        app.config["JWT_SECRET_KEY"] = "isolated-delete-test-key-at-least-32-chars"
        JWTManager(app)
        app.register_blueprint(routes.registry_bp, url_prefix="/api/registry")
        with app.app_context():
            token = create_access_token(identity="2", additional_claims={"role": "Admin"})
        with patch.object(registry, "mysql", db), patch("api.middleware.decorators._verify_user_and_session", return_value=None), patch(
                "api.notifications.hub.publish_to_admins"):
            response = app.test_client().delete("/api/registry/B-1",
                headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 200
        assert db.rows("SELECT * FROM official_registry") == []
        assert db.rows("SELECT * FROM geospatial_logs") == []
    finally:
        db.close()


@pytest.mark.parametrize("errno", [1205, 1213])
def test_concurrent_delete_lock_error_is_a_retryable_conflict(errno):
    cursor = MagicMock()
    cursor.fetchall.side_effect = [[{"Field": "confirmedLogID"}], [{"logID": 1}], [{"Field": "confirmedLogID"}]]
    cursor.fetchone.side_effect = [
        {"businessID": "B-1", "barangayID": 1, "placeID": None, "confirmedLogID": None},
        {"blackLocked": 0, "applicationStatus": "Active"},
        {"logID": 1}, None,
    ]

    def execute(sql, *_args):
        if "DELETE FROM geospatial_logs" in sql:
            raise RuntimeError(errno, "private lock detail")

    cursor.execute.side_effect = execute
    with patch.object(registry, "mysql") as mysql:
        mysql.connection.cursor.return_value = cursor
        ok, error = registry.delete_business("B-1", actor_role="Admin")
        assert not ok and isinstance(error, registry.RegistryDeletionConflict)
        assert "private lock detail" not in str(error)
        mysql.connection.rollback.assert_called_once()
        mysql.connection.commit.assert_not_called()
