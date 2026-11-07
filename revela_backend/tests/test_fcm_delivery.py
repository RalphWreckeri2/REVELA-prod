import sys
import types
from unittest.mock import MagicMock, patch

from firebase_admin._messaging_utils import UnregisteredError

from api.models import user
from api.notifications import fcm


def test_messaging_client_accepts_concurrent_default_app_initialization(monkeypatch):
    firebase_admin = types.ModuleType("firebase_admin")
    firebase_admin.__path__ = []
    firebase_admin._apps = {}
    firebase_admin.get_app = MagicMock(return_value=object())

    def initialize_app(_credential):
        firebase_admin._apps["[DEFAULT]"] = object()
        raise ValueError("The default Firebase app already exists.")

    firebase_admin.initialize_app = MagicMock(side_effect=initialize_app)
    credentials = types.ModuleType("firebase_admin.credentials")
    credentials.Certificate = MagicMock(return_value=object())
    messaging = types.ModuleType("firebase_admin.messaging")
    monkeypatch.setitem(sys.modules, "firebase_admin", firebase_admin)
    monkeypatch.setitem(sys.modules, "firebase_admin.credentials", credentials)
    monkeypatch.setitem(sys.modules, "firebase_admin.messaging", messaging)
    monkeypatch.setenv(
        "FIREBASE_SERVICE_ACCOUNT_JSON",
        '{"project_id":"test-project","private_key":"test-key"}',
    )
    monkeypatch.delenv("FIREBASE_SERVICE_ACCOUNT_PATH", raising=False)

    assert fcm._messaging_client() is messaging
    assert fcm._messaging_client() is messaging
    firebase_admin.initialize_app.assert_called_once()
    firebase_admin.get_app.assert_called_once()


def test_unregistered_inspector_token_is_removed_without_traceback():
    messaging = MagicMock()
    messaging.send.side_effect = UnregisteredError("NotRegistered")

    with (
        patch.object(fcm, "get_fcm_token", return_value="stale-token"),
        patch.object(fcm, "_messaging_client", return_value=messaging),
        patch.object(fcm, "clear_fcm_token") as clear_token,
        patch.object(fcm.logger, "exception") as log_exception,
    ):
        assert fcm.send_inspection_dispatch_push(35, 14, "Test business") is False

    clear_token.assert_called_once_with(14, expected_token="stale-token")
    log_exception.assert_not_called()


def test_clear_fcm_token_only_removes_the_expected_stale_token():
    cursor = MagicMock()
    mysql = MagicMock()
    mysql.connection.cursor.return_value = cursor

    with (
        patch.object(user, "mysql", mysql),
        patch.object(user, "_ensure_fcm_token_column"),
    ):
        user.clear_fcm_token(14, expected_token="stale-token")

    query, params = cursor.execute.call_args.args
    assert "AND fcm_token = %s" in query
    assert params == (14, "stale-token")
    mysql.connection.commit.assert_called_once()
