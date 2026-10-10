import unittest
import threading
import queue
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from unittest.mock import MagicMock, patch

from flask import Flask
from flask_jwt_extended import JWTManager, create_access_token
from MySQLdb import IntegrityError

from api.auth import routes as auth_routes
from api.auth import sessions
from api.inspections import routes as inspection_routes
from api.middleware import decorators
from api.notifications import hub


SESSION_LIFETIME_HOURS = 12
IDLE_LIMIT_MINUTES = 10


def _duplicate_entry():
    """The exact error MySQL raises when the userID primary key collides."""
    return IntegrityError(1062, "Duplicate entry for key 'PRIMARY'")


class InMemorySessionStore:
    """Models user_active_sessions: one row per userID, with issuedAt expiry."""

    def __init__(self):
        # userID -> (sessionID, clientType, issuedAtMinutesAgo)
        self.rows = {}
        self.lock = threading.RLock()

    def active(self, user_id, session_id):
        with self.lock:
            row = self.rows.get(int(user_id))
            if row is None or row[0] != session_id:
                return False
            return row[2] < SESSION_LIFETIME_HOURS * 60

    def session_of(self, user_id):
        with self.lock:
            return self.rows.get(int(user_id))

    def age_session(self, user_id, minutes):
        """Age a stored row, simulating the passage of time."""
        with self.lock:
            row = self.rows[int(user_id)]
            self.rows[int(user_id)] = (row[0], row[1], minutes)


class InMemorySessionCursor:
    def __init__(self, store):
        self.store = store
        self.result = None
        self.rowcount = 0

    def execute(self, query, params=None):
        normalized = " ".join(query.lower().split())
        self.result = None
        self.rowcount = 0

        if normalized.startswith("insert into user_active_sessions"):
            user_id, session_id, client_type = params
            with self.store.lock:
                if int(user_id) in self.store.rows:
                    # Primary key collision -- the login loses the race.
                    raise _duplicate_entry()
                self.store.rows[int(user_id)] = (session_id, client_type, 0)
                self.rowcount = 1

        elif normalized.startswith("select sessionid, clienttype"):
            # Only sessions still inside their lifetime hold the slot.
            user_id, lifetime_hours = params
            with self.store.lock:
                row = self.store.rows.get(int(user_id))
                if row is not None and row[2] < lifetime_hours * 60:
                    self.result = {"sessionID": row[0], "clientType": row[1]}

        elif (
            normalized.startswith("select 1 from user_active_sessions")
            and "interval %s second" in normalized
        ):
            # Inactivity bootstrap: issued more than N seconds ago?
            user_id, session_id, idle_seconds = params
            with self.store.lock:
                row = self.store.rows.get(int(user_id))
                aged_out = (
                    row is not None
                    and row[0] == session_id
                    and row[2] >= (idle_seconds / 60.0)
                )
                self.result = (1,) if aged_out else None

        elif normalized.startswith("select 1 from user_active_sessions"):
            # JWT-lifetime liveness check.
            user_id, session_id, lifetime_hours = params
            with self.store.lock:
                row = self.store.rows.get(int(user_id))
                live = (
                    row is not None
                    and row[0] == session_id
                    and row[2] < lifetime_hours * 60
                )
                self.result = (1,) if live else None

        elif normalized.startswith("delete from user_active_sessions where userid = %s and issuedat <="):
            # Expiry cleanup: the predicate can never match a live session.
            user_id, lifetime_hours = params
            with self.store.lock:
                key = int(user_id)
                row = self.store.rows.get(key)
                if row is not None and row[2] >= lifetime_hours * 60:
                    del self.store.rows[key]
                    self.rowcount = 1

        elif normalized.startswith("delete from user_active_sessions"):
            # Logout / idle eviction: revoke only the presented session.
            user_id, session_id = params
            with self.store.lock:
                row = self.store.rows.get(int(user_id))
                if row is not None and row[0] == session_id:
                    del self.store.rows[int(user_id)]
                    self.rowcount = 1

        else:
            raise AssertionError(f"Unexpected session query: {query}")

    def fetchone(self):
        return self.result

    def fetchall(self):
        return [self.result] if self.result is not None else []

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

    def _store_app(self, include_auth_routes=False):
        """Build a JWT app bound to a fresh in-memory session table."""
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

    # ── 1. Allow login when no valid active session exists ────────────────────
    def test_first_login_claims_the_slot(self):
        store = InMemorySessionStore()
        user = {"userID": 12, "userRole": "Inspector"}

        with patch.object(sessions, "mysql", InMemorySessionMySQL(store)), patch.object(
            sessions, "create_access_token", return_value="signed-token"
        ):
            with self._store_app().app_context():
                token = sessions.issue_session_token(user, "mobile")

        self.assertEqual(token, "signed-token")
        self.assertEqual(store.rows[12], (store.rows[12][0], "mobile", 0))
        self.assertTrue(store.active(12, store.rows[12][0]))

    # ── 2. Reject a second login while the first is valid ────────────────────
    def test_second_login_is_rejected_while_first_is_valid(self):
        store = InMemorySessionStore()
        user = {"userID": 12, "userRole": "Inspector"}

        with patch.object(sessions, "mysql", InMemorySessionMySQL(store)), patch.object(
            sessions, "create_access_token", return_value="signed-token"
        ):
            with self._store_app().app_context():
                sessions.issue_session_token(user, "web")
                with self.assertRaises(sessions.ActiveSessionConflict) as caught:
                    sessions.issue_session_token(user, "mobile")

        self.assertEqual(caught.exception.active_client_type, "web")
        # Only the first device's session exists.
        self.assertEqual(len(store.rows), 1)
        self.assertEqual(store.rows[12][1], "web")

    # ── 3. Never overwrite or invalidate the first device's session ───────────
    def test_rejected_login_leaves_first_session_fully_intact(self):
        store = InMemorySessionStore()
        user = {"userID": 12, "userRole": "Inspector"}
        app = self._store_app()

        with patch.object(sessions, "mysql", InMemorySessionMySQL(store)), patch.object(
            decorators, "find_user_by_id", return_value={"isActive": True}
        ):
            with app.app_context():
                first_token = sessions.issue_session_token(user, "web")
            first_session = store.rows[12][0]

            with app.app_context():
                with self.assertRaises(sessions.ActiveSessionConflict):
                    sessions.issue_session_token(user, "mobile")

            # The first device still holds its exact session id and can work.
            self.assertEqual(store.rows[12][0], first_session)
            client = app.test_client()
            self.assertEqual(
                client.get("/private", headers=self._authorization(first_token)).status_code,
                200,
            )

    def test_conflict_message_names_the_active_client_type(self):
        self.assertIn(
            "a web browser",
            str(sessions.ActiveSessionConflict("web")),
        )
        self.assertIn(
            "a mobile device",
            str(sessions.ActiveSessionConflict("mobile")),
        )
        # Must not read like an admin revocation to the clients' text matchers.
        message = str(sessions.ActiveSessionConflict("web")).lower()
        for trigger in ("revoked", "deactivated", "administrator", "removed", "cannot access"):
            self.assertNotIn(trigger, message)

    # ── 4. Allow a new login after logout or expiry ──────────────────────────
    def test_login_succeeds_again_after_logout(self):
        store = InMemorySessionStore()
        user = {"userID": 12, "userRole": "Inspector"}
        app = self._store_app(include_auth_routes=True)

        with patch.object(sessions, "mysql", InMemorySessionMySQL(store)), patch.object(
            decorators, "find_user_by_id", return_value={"isActive": True}
        ), patch.object(auth_routes, "clear_fcm_token"):
            with app.app_context():
                first = sessions.issue_session_token(user, "web")

            client = app.test_client()
            logout = client.post(
                "/api/auth/logout", headers=self._authorization(first)
            )
            self.assertEqual(logout.status_code, 200)
            self.assertEqual(store.rows, {})

            with patch.object(
                sessions, "create_access_token", return_value="second-token"
            ):
                with app.app_context():
                    second = sessions.issue_session_token(user, "web")

        self.assertEqual(second, "second-token")
        self.assertNotEqual(store.rows[12][0], first)

    def test_login_succeeds_again_after_session_expires(self):
        store = InMemorySessionStore()
        user = {"userID": 12, "userRole": "Inspector"}

        with patch.object(sessions, "mysql", InMemorySessionMySQL(store)), patch.object(
            sessions, "create_access_token", return_value="fresh-token"
        ):
            with self._store_app().app_context():
                # A first login takes the slot.
                sessions.issue_session_token(user, "web")

                # While it is valid, later logins are refused.
                with self.assertRaises(sessions.ActiveSessionConflict):
                    sessions.issue_session_token(user, "mobile")

                # issuedAt ages past the 12h JWT lifetime.
                with store.lock:
                    old = store.rows[12]
                    store.rows[12] = (old[0], old[1], SESSION_LIFETIME_HOURS * 60 + 1)

                # The expired session no longer holds the slot.
                token = sessions.issue_session_token(user, "mobile")

        self.assertEqual(token, "fresh-token")
        self.assertEqual(store.rows[12][1], "mobile")
        self.assertEqual(store.rows[12][2], 0)

    def test_expiry_window_matches_jwt_lifetime(self):
        app = Flask(__name__)
        app.config["JWT_ACCESS_TOKEN_EXPIRES"] = timedelta(hours=8)
        with app.app_context():
            self.assertEqual(sessions.session_lifetime_hours(), 8.0)

        default_app = Flask(__name__)
        with default_app.app_context():
            self.assertEqual(sessions.session_lifetime_hours(), 12.0)

    # ── 6. Applied to normal login and 2FA completion ────────────────────────
    def test_login_endpoint_returns_409_when_already_signed_in(self):
        app = Flask(__name__)
        app.config["JWT_ACCESS_TOKEN_EXPIRES"] = timedelta(hours=12)
        app.register_blueprint(auth_routes.auth_bp, url_prefix="/api/auth")
        store = InMemorySessionStore()
        admin = {
            "userID": 12,
            "userRole": "Admin",
            "fullName": "Jane Admin",
            "email": "admin@example.com",
            "phone": "",
            "mustChangePassword": False,
            "is_2fa_enabled": False,
        }

        with patch.object(sessions, "mysql", InMemorySessionMySQL(store)), patch.object(
            auth_routes, "login_user", return_value=(True, None)
        ), patch.object(
            auth_routes, "find_user_by_email", return_value=admin
        ), patch.object(
            sessions, "create_access_token", return_value="first-token"
        ):
            client = app.test_client()
            body = {
                "email": "admin@example.com",
                "password": "password",
                "source": "web",
            }
            first = client.post("/api/auth/login", json=body)
            self.assertEqual(first.status_code, 200)

            second = client.post("/api/auth/login", json=body)

        self.assertEqual(second.status_code, 409)
        payload = second.get_json()
        self.assertEqual(payload["code"], "account_in_use")
        self.assertIn("a web browser", payload["message"])
        # No "error" key, so the web client renders only the clean message.
        self.assertNotIn("error", payload)
        # The first device's token is untouched.
        self.assertEqual(store.rows[12][1], "web")

    def test_two_factor_completion_returns_409_when_already_signed_in(self):
        app = self._store_app(include_auth_routes=True)
        store = InMemorySessionStore()
        user = {
            "userID": 12,
            "userRole": "Inspector",
            "fullName": "Field Inspector",
            "email": "inspector@example.com",
            "is_2fa_enabled": True,
        }

        with patch.object(sessions, "mysql", InMemorySessionMySQL(store)), patch.object(
            auth_routes, "find_user_by_id", return_value=user
        ), patch.object(
            auth_routes, "get_user_2fa_secret", return_value="SECRET"
        ), patch.object(
            auth_routes, "verify_totp_code", return_value=True
        ), patch.object(
            sessions, "create_access_token", return_value="real-token"
        ), patch.object(decorators, "find_user_by_id", return_value={"isActive": True}):
            client = app.test_client()

            # First device completes 2FA and wins the session.
            with app.app_context():
                first_pending = create_access_token(
                    identity="12",
                    additional_claims={"2fa_pending": True, "client_type": "web"},
                    expires_delta=timedelta(minutes=5),
                )
            first = client.post(
                "/api/auth/verify-2fa-login",
                json={"code": "123456"},
                headers=self._authorization(first_pending),
            )
            self.assertEqual(first.status_code, 200)

            # A second device passing 2FA is refused, and does not take over.
            with app.app_context():
                second_pending = create_access_token(
                    identity="12",
                    additional_claims={"2fa_pending": True, "client_type": "mobile"},
                    expires_delta=timedelta(minutes=5),
                )
            second = client.post(
                "/api/auth/verify-2fa-login",
                json={"code": "123456"},
                headers=self._authorization(second_pending),
            )

            self.assertEqual(second.status_code, 409)
            self.assertEqual(second.get_json()["code"], "account_in_use")
            self.assertIn("a web browser", second.get_json()["message"])
            self.assertEqual(store.rows[12][1], "web")

    # ── 7. Simultaneous logins cannot both succeed ───────────────────────────
    def test_simultaneous_logins_allow_exactly_one_winner(self):
        store = InMemorySessionStore()
        mysql = InMemorySessionMySQL(store)
        user = {"userID": 12, "userRole": "Inspector"}
        barrier = threading.Barrier(8)

        def issue(client_type):
            # Release all eight logins at the same instant so they contend for
            # the single userID primary key.
            barrier.wait(timeout=5)
            try:
                return sessions.issue_session_token(user, client_type)
            except sessions.ActiveSessionConflict:
                return None

        client_types = ("web", "mobile", "web", "mobile",
                        "web", "mobile", "web", "mobile")
        with patch.object(sessions, "mysql", mysql), patch.object(
            sessions, "create_access_token",
            side_effect=lambda identity, additional_claims: additional_claims["session_id"],
        ):
            with ThreadPoolExecutor(max_workers=8) as pool:
                results = list(pool.map(issue, client_types))

        winners = [token for token in results if token is not None]
        self.assertEqual(len(winners), 1, f"expected exactly one winner, got {results}")
        self.assertEqual(len(store.rows), 1)
        self.assertTrue(store.active(12, winners[0]))

    # ── 8. Preserved web and Flutter behaviour ────────────────────────────────
    def test_first_device_keeps_working_after_second_login_is_refused(self):
        app = self._store_app()
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
                with self.assertRaises(sessions.ActiveSessionConflict):
                    sessions.issue_session_token(user, "web")

            # Device A was never kicked.
            self.assertEqual(
                client.get("/private", headers=self._authorization(device_a)).status_code,
                200,
            )

    def test_logout_revokes_only_the_presented_session(self):
        sessions.revoke_session(12, "old-session")

        query, params = self.cursor.execute.call_args.args
        self.assertIn("DELETE FROM user_active_sessions", query)
        self.assertEqual(params, (12, "old-session"))
        self.connection.commit.assert_called_once()

    def test_active_session_requires_exact_session_id(self):
        store = InMemorySessionStore()
        user = {"userID": 12, "userRole": "Inspector"}

        with patch.object(sessions, "mysql", InMemorySessionMySQL(store)), patch.object(
            sessions, "create_access_token", return_value="signed-token"
        ):
            with self._store_app().app_context():
                sessions.issue_session_token(user, "web")
                current = store.rows[12][0]

                self.assertTrue(sessions.is_active_session(12, current))
                self.assertFalse(sessions.is_active_session(12, "old-session"))
                self.assertFalse(sessions.is_active_session(12, None))

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

    def test_web_login_allows_every_ipad_browser(self):
        """REGRESSION: iPadOS sends `Mobile/15E148` even in Safari.

        The previous /Mobile/ pattern rejected every iPad, locking tablets out
        of the portal. Tablets must take precedence over the phone markers.
        """
        ipad_user_agents = [
            "Mozilla/5.0 (iPad; CPU OS 17_0 like Mac OS X) AppleWebKit/605.1.15 "
            "(KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
            "Mozilla/5.0 (iPad; CPU OS 17_0 like Mac OS X) AppleWebKit/605.1.15 "
            "(KHTML, like Gecko) CriOS/120.0.6099.119 Mobile/15E148 Safari/604.1",
            "Mozilla/5.0 (iPad; CPU OS 17_0 like Mac OS X) AppleWebKit/605.1.15 "
            "(KHTML, like Gecko) FxiOS/120.0 Mobile/15E148 Safari/605.1.15",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
            "(KHTML, like Gecko) Version/17.0 Safari/605.1.15",
            "Mozilla/5.0 (Linux; Android 14; SM-X200) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
        ]
        for user_agent in ipad_user_agents:
            self.assertFalse(
                auth_routes._is_phone_user_agent(user_agent),
                f"tablet must not be classified as a phone: {user_agent[:60]}",
            )

    def test_web_login_rejects_phone_user_agents_including_desktop_site_mode(self):
        phone_user_agents = [
            "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
            "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 "
            "Mobile/15E148 Safari/604.1",
            # "Request Desktop Website" inflates the layout viewport but keeps
            # the Mobile/15E148 token.
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
            "(KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
            "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/130.0.0.0 Mobile Safari/537.36",
        ]
        for user_agent in phone_user_agents:
            self.assertTrue(
                auth_routes._is_phone_user_agent(user_agent),
                f"phone must be rejected: {user_agent[:60]}",
            )

    def test_device_gate_does_not_alter_authentication_or_roles(self):
        """The gate is a usability check; role rules stay authoritative."""
        app = Flask(__name__)
        app.register_blueprint(auth_routes.auth_bp, url_prefix="/api/auth")
        inspector = {
            "userID": 24,
            "userRole": "Inspector",
            "fullName": "Field Inspector",
            "email": "inspector@example.com",
            "phone": "",
            "mustChangePassword": False,
            "is_2fa_enabled": False,
        }
        with app.test_client() as client:
            with patch.object(
                auth_routes, "login_user", return_value=(True, None)
            ), patch.object(
                auth_routes, "find_user_by_email", return_value=inspector
            ):
                response = client.post(
                    "/api/auth/login",
                    json={
                        "email": "inspector@example.com",
                        "password": "password",
                        "source": "web",
                    },
                    headers={
                        "User-Agent": (
                            "Mozilla/5.0 (iPad; CPU OS 17_0 like Mac OS X) "
                            "AppleWebKit/605.1.15 (KHTML, like Gecko) "
                            "Version/17.0 Mobile/15E148 Safari/604.1"
                        )
                    },
                )
        # A tablet passes the device gate, then hits the unchanged web role gate.
        self.assertEqual(response.status_code, 403)
        self.assertIn("Admin and Super Admin", response.get_json()["error"])

    def test_mobile_source_bypasses_the_web_device_gate_entirely(self):
        app = Flask(__name__)
        app.register_blueprint(auth_routes.auth_bp, url_prefix="/api/auth")
        inspector = {
            "userID": 24,
            "userRole": "Inspector",
            "fullName": "Field Inspector",
            "email": "inspector@example.com",
            "phone": "",
            "mustChangePassword": False,
            "is_2fa_enabled": False,
        }
        with app.test_client() as client:
            with patch.object(
                auth_routes, "login_user", return_value=(True, None)
            ), patch.object(
                auth_routes, "find_user_by_email", return_value=inspector
            ), patch.object(
                auth_routes, "issue_session_token", return_value="mobile-token"
            ):
                response = client.post(
                    "/api/auth/login",
                    json={
                        "email": "inspector@example.com",
                        "password": "password",
                        "source": "mobile",
                    },
                    headers={
                        "User-Agent": (
                            "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
                            "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 "
                            "Mobile/15E148 Safari/604.1"
                        )
                    },
                )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["access_token"], "mobile-token")

    def test_empty_user_agent_is_not_treated_as_a_phone(self):
        self.assertFalse(auth_routes._is_phone_user_agent(""))
        self.assertFalse(auth_routes._is_phone_user_agent(None))

    def test_mobile_client_authenticates_with_a_phone_user_agent(self):
        app = self._store_app(include_auth_routes=True)
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

    def test_logout_and_jwt_expiration_reject_protected_requests(self):
        app = self._store_app(include_auth_routes=True)
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
                store.rows[12] = ("expired-session", "mobile", 0)

            self.assertEqual(
                client.get(
                    "/private", headers=self._authorization(expired_token)
                ).status_code,
                401,
            )

    def test_session_replacement_notice_is_not_published_on_login(self):
        """First-login-wins means no session is ever replaced."""
        store = InMemorySessionStore()
        user = {"userID": 12, "userRole": "Inspector"}
        with patch.object(sessions, "mysql", InMemorySessionMySQL(store)), patch.object(
            sessions, "create_access_token", return_value="token"
        ):
            with patch.object(sessions, "hub", create=True) as unused_hub:
                with self._store_app().app_context():
                    sessions.issue_session_token(user, "web")
                unused_hub.publish_to_user.assert_not_called()

    def test_notification_stream_stays_scoped_to_its_user(self):
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
            ), patch.object(
                decorators, "check_active_session", return_value=(True, None)
            ):
                self.assertIsNone(decorators._verify_user_and_session(
                    "12", {"2fa_pending": True}
                ))

        with app.test_request_context("/api/private"):
            with patch.object(
                decorators, "find_user_by_id", return_value={"isActive": True}
            ), patch.object(
                decorators, "check_active_session", return_value=(False, "session_ended")
            ):
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
            decorators, "check_active_session", return_value=(True, None)
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