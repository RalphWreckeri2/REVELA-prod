import unittest
from unittest.mock import MagicMock, patch

from flask import Flask

from api.auth import routes as auth_routes
from api.auth import sessions
from api.inspections import routes as inspection_routes
from api.middleware import decorators


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

    def test_login_replaces_existing_user_session(self):
        with patch.object(
            sessions, "create_access_token", return_value="signed-token"
        ):
            token = sessions.issue_session_token(
                {"userID": 12, "userRole": "Inspector"}, "mobile"
            )

        self.assertEqual(token, "signed-token")
        query, params = self.cursor.execute.call_args.args
        self.assertIn("ON DUPLICATE KEY UPDATE", query)
        self.assertEqual(params[0], 12)
        self.assertEqual(params[2], "mobile")
        self.connection.commit.assert_called_once()

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

    def test_login_rejects_mobile_user_agent_for_web_source(self):
        app = Flask(__name__)
        app.register_blueprint(auth_routes.auth_bp, url_prefix="/api/auth")

        with app.test_client() as client:
            with patch.object(
                auth_routes,
                "login_user",
                return_value=(True, None),
            ), patch.object(
                auth_routes,
                "find_user_by_email",
                return_value={
                    "userID": 12,
                    "userRole": "Admin",
                    "fullName": "Jane Admin",
                    "email": "admin@example.com",
                    "phone": "",
                    "mustChangePassword": False,
                    "is_2fa_enabled": False,
                },
            ), patch.object(
                auth_routes,
                "issue_session_token",
                return_value="signed-token",
            ):
                response = client.post(
                    "/api/auth/login",
                    json={
                        "email": "admin@example.com",
                        "password": "password",
                        "source": "web",
                    },
                    headers={"User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X)"},
                )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.get_json()["code"], "desktop_access_required")

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
