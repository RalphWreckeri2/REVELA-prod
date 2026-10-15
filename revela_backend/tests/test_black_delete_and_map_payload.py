"""Black deletion authorization and the real Map UNION payload."""
import json
from unittest.mock import patch

import pytest
from flask import Flask
from flask_jwt_extended import JWTManager, create_access_token

from api.flags import routes as flag_routes, service as flags
from api.registry import routes as registry_routes, service as registry
from api.registry.locks import BlackBusinessDeletionForbidden
from registry_sqlite import RegistryDB


@pytest.fixture
def db():
    database = RegistryDB()
    with patch.object(registry, "mysql", database), patch.object(flags, "mysql", database), patch("api.notifications.hub.publish_to_admins"):
        yield database
    database.close()


@pytest.mark.parametrize("status,locked", [("Revoked", 0), ("Active", 1)])
@pytest.mark.parametrize("role", ["Admin", "System Administrator", "super_admin", "SUPER_ADMIN ", None])
def test_only_exact_super_admin_can_delete_black(db, status, locked, role):
    db.seed(status=status, locked=locked)
    before = db.rows("SELECT * FROM official_registry")
    ok, error = registry.delete_business("B-1", actor_role=role)
    assert not ok
    assert isinstance(error, BlackBusinessDeletionForbidden)
    assert db.rows("SELECT * FROM official_registry") == before
    assert len(db.rows("SELECT * FROM geospatial_logs")) == 1
    assert len(db.rows("SELECT * FROM inspection_reports")) == 1
    assert not any(sql.lstrip().startswith("DELETE") for sql, _ in db.calls)


@pytest.mark.parametrize("status,locked", [("Revoked", 0), ("Active", 1)])
def test_super_admin_can_delete_black_business_and_linked_pin(db, status, locked):
    db.seed(status=status, locked=locked)
    ok, error = registry.delete_business("B-1", actor_role="SUPER_ADMIN")
    assert error is None
    assert ok
    assert db.rows("SELECT * FROM official_registry") == []
    assert db.rows("SELECT * FROM geospatial_logs") == []
    assert db.rows("SELECT * FROM inspection_reports") == []


def test_unmigrated_revoked_still_requires_super_admin(db):
    db.seed(status="Revoked", locked=0)
    db.db.execute("ALTER TABLE official_registry DROP COLUMN warningLevel")
    db.db.execute("ALTER TABLE official_registry DROP COLUMN blackLocked")
    db.commit()
    ok, error = registry.delete_business("B-1", actor_role="Admin")
    assert not ok
    assert isinstance(error, BlackBusinessDeletionForbidden)


@pytest.mark.parametrize("virtual", [False, True])
@pytest.mark.parametrize("role,expected", [("Admin", 403), ("System Administrator", 403), ("SUPER_ADMIN", 200)])
def test_registry_and_virtual_map_delete_routes_enforce_black_role(db, virtual, role, expected):
    db.seed(status="Revoked", report=False)
    if virtual:
        db.db.execute("DELETE FROM geospatial_logs")
        db.db.execute("UPDATE official_registry SET businessID = '5'")
        db.commit()
    app = Flask(__name__)
    app.config["JWT_SECRET_KEY"] = "isolated-registry-test-secret-key-32-chars"
    JWTManager(app)
    app.register_blueprint(registry_routes.registry_bp, url_prefix="/api/registry")
    app.register_blueprint(flag_routes.flags_bp, url_prefix="/api/flags")
    with app.app_context():
        token = create_access_token(identity="2", additional_claims={"role": role})
    with patch("api.middleware.decorators._verify_user_and_session", return_value=None):
        response = app.test_client().delete("/api/flags/-5" if virtual else "/api/registry/B-1",
                                            headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == expected
    if expected == 403:
        assert response.get_json()["code"] == "black_delete_forbidden"
        assert len(db.rows("SELECT * FROM official_registry")) == 1
    else:
        assert db.rows("SELECT * FROM official_registry") == []


@pytest.mark.parametrize("virtual", [False, True])
@pytest.mark.parametrize("unlocked", [0, 1])
def test_actual_map_payload_exposes_unlock_without_changing_black_color(db, virtual, unlocked):
    db.seed(status="Revoked", locked=1, report=False)
    db.db.execute("UPDATE official_registry SET blackDispatchUnlocked = ?", (unlocked,))
    if virtual:
        db.db.execute("DELETE FROM geospatial_logs")
        db.db.execute("UPDATE official_registry SET businessID = '5'")
    db.commit()
    payload, error = flags.get_flags()
    assert error is None
    payload = json.loads(json.dumps(payload))
    assert payload["total"] == 1
    assert payload["data"][0]["flagColor"] == "Black"
    assert payload["data"][0]["blackDispatchUnlocked"] == unlocked
    assert "logID" in payload["data"][0]
    assert "flagSource" in payload["data"][0]


def test_map_payload_without_unlock_column_is_zero(db):
    db.seed(status="Revoked", locked=1, report=False)
    db.db.execute("ALTER TABLE official_registry DROP COLUMN blackDispatchUnlocked")
    db.commit()
    payload, error = flags.get_flags()
    assert error is None
    assert payload["data"][0]["flagColor"] == "Black"
    assert payload["data"][0]["blackDispatchUnlocked"] == 0
