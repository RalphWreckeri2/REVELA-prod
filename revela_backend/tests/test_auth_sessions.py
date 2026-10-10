import unittest
import threading
import queue
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from unittest.mock import MagicMock, patch

from flask import Flask
from flask_jwt_extended import JWTManager, create_access_token

from api.auth import routes as auth_routes
from api.auth import sessions
from api.inspections import routes as inspection_routes
from api.middleware import decorators
from api.notifications import hub


class InMemorySessionStore:
    def __init__(self):
        self.rows = {}
        self.lock = threading.Lock()

    def active(self, user_id, session_id):
        with self.lock:
            row = self.rows.get(int(user_id))
            return row is not None and row[0] == session_id


class InMemorySessionCursor:
    def __init__(self, store):
        self.store = store
        self.result = None

    def execute(self, query, params=None):
        normalized_query = " ".join(query.lower().split())
        if normalized_query.startswith("insert into user_active_sessions"):
            user_id, session_id, client_type = params
            with self.store.lock:
                self.store.rows[int(user_id)] = (session_id, client_type)
        elif normalized_query.startswith("select 1 from user_active_sessions"):
            user_id, session_id = params
            self.result = (
                (1,)
                if self.store.active(user_id, session_id)
                else None
            )
        elif normalized_query.startswith("delete from user_active_sessions"):
            user_id, session_id = params
            with self.store.lock:
                row = self.store.rows.get(int(user_id))
                if row is not None and row[0] == session_id:
                    del self.store.rows[int(user_id)]
        else:
            raise AssertionError(f"Unexpected session query: {query}")

    def fetchone(self):
        return self.result

    def close(self):
        pass


class InMemorySessionConnection:
    def __init__(self, store):
        self.store = store

    def cursor(self):
        return InMemorySessionCursor(self.store)

    def commit(self):
        pass

    def rollback(self):
        pass


class InMemorySessionMySQL:
    def __init__(self, store):
        self.connection = InMemorySessionConnection(store)


class ActiveSessionTests(unittest.TestCase):

    def setUp(self):
        self.cursor = MagicMock()
        self.connection = MagicMock()
        self.connection.cursor.return_value = self.cursor
        self.mysql_connection = patch.object(
            sessions, "mysql", MagicMock(connection=self.connection)
        )
        self.mysql_connection.start()
        self.addCleanup(self.mysql_connection.stop)
        self.table_ready = patch.object(sessions, "_session_table_ready", True)
        self.table_ready.start()
        self.addCleanup(self.table_ready.stop)

    def _make_jwt_app(self, include_auth_routes=False):
        app = Flask(__name__)
        app.config.update(
            JWT_SECRET_KEY="test-secret",
            JWT_ACCESS_TOKEN_EXPIRES=timedelta(hours=12),
            JWT_TOKEN_LOCATION=["headers"],
        )
        JWTManager(app)

        @decorators.jwt_required()
        def protected():
            return {"status": "ok"}, 200

        app.add_url_rule("/private", view_func=protected)
        if include_auth_routes:
            app.register_blueprint(auth_routes.auth_bp, url_prefix="/api/auth")
        return app

    @staticmethod
    def _authorization(token):
        return {"Authorization": f"Bearer {token}"}

    def test_login_replaces_existing_user_session(self):
        with patch.object(
            sessions, "create_access_token", return_value="signed-token"
        ), patch.object(sessions.hub, "publish_to_user") as publish_to_user:
            token = sessions.issue_session_token(
                {"userID": 12, "userRole": "Inspector"}, "mobile"
            )

        self.assertEqual(token, "signed-token")
        publish_to_user.assert_called_once()
        self.assertEqual(publish_to_user.call_args.args[0], 12)
        self.assertEqual(
            publish_to_user.call_args.args[1]["type"],
            "session_replaced",
        )
        query, params = self.cursor.execute.call_args.args
        self.assertIn("ON DUPLICATE KEY UPDATE", query)
        self.assertEqual(params[0], 12)
        self.assertEqual(params[2], "mobile")
        self.connection.commit.assert_called_once()

    def test_session_replacement_notice_is_sent_only_to_that_users_stream(self):
        user_stream = hub.subscribe("12")
        other_stream = hub.subscribe("13")
        self.addCleanup(hub.unsubscribe, "12", user_stream)
        self.addCleanup(hub.unsubscribe, "13", other_stream)

        hub.publish_to_user(12, {"type": "session_replaced"})

        self.assertEqual(
            user_stream.get_nowait(),
            {"type": "session_replaced"},
        )
        with self.assertRaises(queue.Empty):
            other_stream.get_nowait()

    def test_active_session_requires_exact_session_id(self):
        self.cursor.fetchone.return_value = (1,)
        self.assertTrue(sessions.is_active_session("12", "current-session"))

        self.cursor.fetchone.return_value = None
        self.assertFalse(sessions.is_active_session("12", "old-session"))
        self.assertFalse(sessions.is_active_session("12", None))

    def test_logout_revokes_only_the_presented_session(self):
        sessions.revoke_session(12, "old-session")

        query, params = self.cursor.execute.call_args.args
        self.assertIn("DELETE FROM user_active_sessions", query)
        self.assertEqual(params, (12, "old-session"))
        self.connection.commit.assert_called_once()

    def test_web_login_rejects_phone_user_agent(self):
        app = Flask(__name__)
        app.register_blueprint(auth_routes.auth_bp, url_prefix="/api/auth")

        with app.test_client() as client:
            response = client.post(
                "/api/auth/login",
                json={
                    "email": "admin@example.com",
                    "password": "password",
                    "source": "web",
                },
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X)"
                    )
                },
            )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(
            response.get_json()["code"], "desktop_access_required"
        )

    def test_web_login_allows_tablet_user_agent(self):
        app = Flask(__name__)
        app.register_blueprint(auth_routes.auth_bp, url_prefix="/api/auth")
        user = {
            "userID": 12,
            "userRole": "Admin",
            "fullName": "Jane Admin",
            "email": "admin@example.com",
            "phone": "",
            "mustChangePassword": False,
            "is_2fa_enabled": False,
        }

        with app.test_client() as client:
            with patch.object(
                auth_routes, "login_user", return_value=(True, None)
            ), patch.object(
                auth_routes, "find_user_by_email", return_value=user
            ), patch.object(
                auth_routes, "issue_session_token", return_value="signed-token"
            ) as issue_session:
                response = client.post(
                    "/api/auth/login",
                    json={
                        "email": "admin@example.com",
                        "password": "password",
                        "source": "web",
                    },
                    headers={
                        "User-Agent": (
                            "Mozilla/5.0 (Linux; Android 14; Tablet) "
                            "AppleWebKit/537.36 Chrome/130.0.0.0 Safari/537.36"
                        )
                    },
                )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["access_token"], "signed-token")
        issue_session.assert_called_once_with(user, "web")

    def test_device_b_login_revokes_device_a_at_protected_route(self):
        app = self._make_jwt_app()
        store = InMemorySessionStore()
        user = {"userID": 12, "userRole": "Inspector"}
        with patch.object(sessions, "mysql", InMemorySessionMySQL(store)), patch.object(
            decorators, "find_user_by_id", return_value={"isActive": True}
        ):
            with app.app_context():
                device_a = sessions.issue_session_token(user, "mobile")
            client = app.test_client()
            self.assertEqual(
                client.get("/private", headers=self._authorization(device_a)).status_code,
                200,
            )

            with app.app_context():
                device_b = sessions.issue_session_token(user, "web")

            self.assertEqual(
                client.get("/private", headers=self._authorization(device_b)).status_code,
                200,
            )
            self.assertEqual(
                client.get("/private", headers=self._authorization(device_a)).status_code,
                401,
            )

    def test_logout_and_jwt_expiration_reject_protected_requests(self):
        app = self._make_jwt_app(include_auth_routes=True)
        store = InMemorySessionStore()
        user = {"userID": 12, "userRole": "Inspector"}
        with patch.object(sessions, "mysql", InMemorySessionMySQL(store)), patch.object(
            decorators, "find_user_by_id", return_value={"isActive": True}
        ), patch.object(auth_routes, "clear_fcm_token"):
            with app.app_context():
                active_token = sessions.issue_session_token(user, "mobile")
            client = app.test_client()

            logout = client.post(
                "/api/auth/logout",
                headers=self._authorization(active_token),
            )
            self.assertEqual(logout.status_code, 200)
            self.assertEqual(
                client.get(
                    "/private", headers=self._authorization(active_token)
                ).status_code,
                401,
            )

            with app.app_context():
                expired_token = create_access_token(
                    identity="12",
                    additional_claims={
                        "session_id": "expired-session",
                        "client_type": "mobile",
                    },
                    expires_delta=timedelta(seconds=-1),
                )
            with store.lock:
                store.rows[12] = ("expired-session", "mobile")

            self.assertEqual(
                client.get(
                    "/private", headers=self._authorization(expired_token)
                ).status_code,
                401,
            )

    def test_simultaneous_logins_leave_exactly_one_active_session(self):
        store = InMemorySessionStore()
        mysql = InMemorySessionMySQL(store)
        login_barrier = threading.Barrier(8)
        user = {"userID": 12, "userRole": "Inspector"}

        def create_token(identity, additional_claims):
            login_barrier.wait(timeout=5)
            return additional_claims["session_id"]

        with patch.object(sessions, "mysql", mysql), patch.object(
            sessions, "create_access_token", side_effect=create_token
        ):
            with ThreadPoolExecutor(max_workers=8) as pool:
                tokens = list(pool.map(
                    lambda client_type: sessions.issue_session_token(
                        user, client_type
                    ),
                    ("web", "mobile", "web", "mobile",
                     "web", "mobile", "web", "mobile"),
                ))

        self.assertEqual(len(set(tokens)), 8)
        self.assertEqual(sum(store.active(12, token) for token in tokens), 1)

    def test_mobile_client_authenticates_with_a_phone_user_agent(self):
        app = self._make_jwt_app(include_auth_routes=True)
        store = InMemorySessionStore()
        inspector = {
            "userID": 24,
            "userRole": "Inspector",
            "fullName": "Field Inspector",
            "email": "inspector@example.com",
            "phone": "",
            "mustChangePassword": False,
            "is_2fa_enabled": False,
        }
        with patch.object(sessions, "mysql", InMemorySessionMySQL(store)), patch.object(
            auth_routes, "login_user", return_value=(True, None)
        ), patch.object(
            auth_routes, "find_user_by_email", return_value=inspector
        ), patch.object(
            decorators, "find_user_by_id", return_value={"isActive": True}
        ):
            client = app.test_client()
            response = client.post(
                "/api/auth/login",
                json={
                    "email": inspector["email"],
                    "password": "password",
                    "source": "mobile",
                },
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X)"
                    )
                },
            )

            self.assertEqual(response.status_code, 200)
            token = response.get_json()["access_token"]
            self.assertEqual(
                client.get(
                    "/private", headers=self._authorization(token)
                ).status_code,
                200,
            )

    def test_pending_two_factor_token_is_allowed_only_on_verify_endpoint(self):
        app = Flask(__name__)
        app.add_url_rule(
            "/api/auth/verify-2fa-login",
            endpoint="auth.verify_2fa_login",
            view_func=lambda: None,
        )
        with app.test_request_context("/api/auth/verify-2fa-login"):
            with patch.object(
                decorators, "find_user_by_id", return_value={"isActive": True}
            ), patch.object(decorators, "is_active_session", return_value=False):
                self.assertIsNone(decorators._verify_user_and_session(
                    "12", {"2fa_pending": True}
                ))

        with app.test_request_context("/api/private"):
            with patch.object(
                decorators, "find_user_by_id", return_value={"isActive": True}
            ), patch.object(decorators, "is_active_session", return_value=False):
                response, status = decorators._verify_user_and_session(
                    "12", {"2fa_pending": True}
                )
                self.assertEqual(status, 401)
                self.assertEqual(response.get_json()["message"],
                                 "Complete two-factor authentication first.")

    def test_calendar_scope_uses_current_database_role_not_stale_token_claim(self):
        app = Flask(__name__)
        app.register_blueprint(
            inspection_routes.inspections_bp,
            url_prefix="/api/inspections",
        )
        claims = {
            "role": "Admin",
            "session_id": "current-session",
        }
        with app.test_request_context(
            "/api/inspections/calendar?month=2026-10&date=2026-10-10"
        ), patch.object(
            decorators, "verify_jwt_in_request"
        ), patch.object(
            decorators, "get_jwt", return_value=claims
        ), patch.object(
            decorators, "get_jwt_identity", return_value="12"
        ), patch.object(
            decorators, "find_user_by_id", return_value={"isActive": True}
        ), patch.object(
            decorators, "is_active_session", return_value=True
        ), patch.object(
            inspection_routes, "get_jwt_identity", return_value="12"
        ), patch.object(
            inspection_routes,
            "find_user_by_id",
            return_value={"userRole": "Inspector"},
        ), patch.object(
            inspection_routes,
            "get_inspection_calendar",
            return_value=({"days": [], "activities": []}, None),
        ) as calendar:
            response = app.test_client().get(
                "/api/inspections/calendar?month=2026-10&date=2026-10-10"
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(calendar.call_args.kwargs["user_id"], "12")
