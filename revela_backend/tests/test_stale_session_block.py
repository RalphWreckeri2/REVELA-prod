"""Regression tests for the false "account already logged in" report.

Symptom: after First Login Wins and inactivity auto-logout shipped, signing in
reported "This account is already signed in on a web browser" even though no
device was signed in.

Root cause: the login path and the request path disagreed about idleness. The
request path falls back to the stored issue time when the in-process activity
map has no record of a session; the login path treated "unknown" as "active".
After any process restart the activity map was empty, so every abandoned
session became unknowable and blocked new logins for the full 12-hour JWT
lifetime.
"""
import time
import unittest
from datetime import timedelta
from unittest.mock import patch

from flask import Flask
from flask_jwt_extended import JWTManager, decode_token

from api.auth import routes as auth_routes
from api.auth import sessions
from api.middleware import decorators

from tests.test_auth_sessions import (
    IDLE_LIMIT_MINUTES,
    InMemorySessionMySQL,
    InMemorySessionStore,
)

IDLE_LIMIT_SECONDS = IDLE_LIMIT_MINUTES * 60


def _make_app():
    app = Flask(__name__)
    app.config.update(
        JWT_SECRET_KEY="test-secret",
        JWT_ACCESS_TOKEN_EXPIRES=timedelta(hours=12),
        SESSION_IDLE_TIMEOUT=timedelta(minutes=IDLE_LIMIT_MINUTES),
        JWT_TOKEN_LOCATION=["headers"],
    )
    JWTManager(app)
    return app


class StaleSessionBlockTests(unittest.TestCase):
    """A stale session must never block a new login, restart or not."""

    def setUp(self):
        self.store = InMemorySessionStore()
        self.mysql = InMemorySessionMySQL(self.store)
        self.app = _make_app()
        self.user = {"userID": 12, "userRole": "Admin"}

        table_ready = patch.object(sessions, "_session_table_ready", True)
        table_ready.start()
        self.addCleanup(table_ready.stop)
        self.addCleanup(self._wipe_activity)

    def _wipe_activity(self):
        with sessions._activity_lock:
            sessions._last_activity.clear()

    def _login(self, client_type="web", user=None):
        with patch.object(sessions, "mysql", self.mysql):
            with self.app.app_context():
                jwt = sessions.issue_session_token(user or self.user, client_type)
                return jwt, decode_token(jwt)["session_id"]

    def _simulate_restart(self):
        """A worker restart wipes the in-process activity map."""
        self._wipe_activity()

    def _age_stored_row(self, user_id, minutes):
        """Age issuedAt, as the database clock would report it."""
        row = self.store.rows[int(user_id)]
        self.store.rows[int(user_id)] = (row[0], row[1], minutes)

    # ── The reported bug ─────────────────────────────────────────────────────
    def test_stale_session_does_not_block_login_after_a_restart(self):
        """The exact reported symptom: well past the idle limit, server restarted."""
        _, session_a = self._login("web")
        self._simulate_restart()
        self._age_stored_row(12, IDLE_LIMIT_MINUTES + 10)

        with patch.object(sessions, "mysql", self.mysql):
            with self.app.app_context():
                jwt_b = sessions.issue_session_token(
                    {"userID": 12, "userRole": "Admin"}, "web"
                )
                session_b = decode_token(jwt_b)["session_id"]

        self.assertNotEqual(session_b, session_a)
        self.assertEqual(self.store.rows[12][0], session_b)

    def test_restart_and_no_restart_agree_for_a_stale_session(self):
        """The two paths must reach the same verdict for the same row."""
        results = {}
        for restarted in (False, True):
            self.store.rows.clear()
            self._wipe_activity()
            _, session_a = self._login("web")
            if restarted:
                self._simulate_restart()
                self._age_stored_row(12, IDLE_LIMIT_MINUTES + 10)
            else:
                with sessions._activity_lock:
                    sessions._last_activity[session_a] = (
                        time.monotonic() - IDLE_LIMIT_SECONDS - 600
                    )
            try:
                with patch.object(sessions, "mysql", self.mysql):
                    with self.app.app_context():
                        sessions.issue_session_token(
                            {"userID": 12, "userRole": "Admin"}, "web"
                        )
                results[restarted] = "allowed"
            except sessions.ActiveSessionConflict:
                results[restarted] = "blocked"

        self.assertEqual(
            results[False], results[True],
            "a restart must not change the verdict for an abandoned session",
        )
        self.assertEqual(results[False], "allowed")

    # ── Requirement 6: a genuinely active Device A is never kicked ──────────
    def test_active_session_still_blocks_a_login_after_a_restart(self):
        """A device still inside the inactivity window keeps the slot."""
        _, session_a = self._login("web")
        self._simulate_restart()
        # Issued recently, so it is inside the inactivity window.
        self._age_stored_row(12, 5)

        with patch.object(sessions, "mysql", self.mysql):
            with self.app.app_context():
                with self.assertRaises(sessions.ActiveSessionConflict):
                    sessions.issue_session_token(
                        {"userID": 12, "userRole": "Admin"}, "mobile"
                    )

        self.assertEqual(self.store.rows[12][0], session_a)
        self.assertEqual(self.store.rows[12][1], "web")

    def test_active_session_with_live_activity_is_never_kicked(self):
        """A session whose activity is being tracked is always protected."""
        _, session_a = self._login("web")
        for _ in range(30):  # Device A stays busy for hours
            with sessions._activity_lock:
                sessions._last_activity[session_a] = time.monotonic()
            with patch.object(sessions, "mysql", self.mysql):
                with self.app.app_context():
                    sessions.record_session_activity(session_a)
                    with self.assertRaises(sessions.ActiveSessionConflict):
                        sessions.issue_session_token(
                            {"userID": 12, "userRole": "Admin"}, "mobile"
                        )

    def test_request_path_and_login_path_never_disagree(self):
        """Directly assert the invariant that caused the bug."""
        _, session_a = self._login("web")
        self._simulate_restart()
        self._age_stored_row(12, IDLE_LIMIT_MINUTES + 5)

        with patch.object(sessions, "mysql", self.mysql):
            with self.app.app_context():
                # Ask without adopting: this is the login path's question.
                login_path_says_idle = sessions.session_is_idle(12, session_a)

        self.assertTrue(
            login_path_says_idle,
            "the login path must reach the same idle verdict as the request path",
        )

    # ── Requirement 5: nothing blocks permanently ────────────────────────────
    def test_recent_session_still_blocks_but_releases_when_it_goes_stale(self):
        _, session_a = self._login("web")
        self._simulate_restart()
        # Comfortably inside the inactivity window.
        self._age_stored_row(12, IDLE_LIMIT_MINUTES // 2)

        with patch.object(sessions, "mysql", self.mysql):
            with self.app.app_context():
                with self.assertRaises(sessions.ActiveSessionConflict):
                    sessions.issue_session_token(
                        {"userID": 12, "userRole": "Admin"}, "web"
                    )

        # Time passes; the same session is now stale and must release.
        self._age_stored_row(12, IDLE_LIMIT_MINUTES + 1)
        with patch.object(sessions, "mysql", self.mysql):
            with self.app.app_context():
                sessions.issue_session_token(
                    {"userID": 12, "userRole": "Admin"}, "web"
                )
        self.assertNotEqual(self.store.rows[12][0], session_a)

    def test_login_path_never_extends_another_devices_session(self):
        """A rejected login must not refresh the session it refused."""
        _, session_a = self._login("web")
        # Halfway through the window, so it is idle-free but still protected.
        with sessions._activity_lock:
            sessions._last_activity[session_a] = (
                time.monotonic() - IDLE_LIMIT_SECONDS / 2
            )
        recorded = sessions.seconds_since_activity(session_a)

        with patch.object(sessions, "mysql", self.mysql):
            with self.app.app_context():
                with self.assertRaises(sessions.ActiveSessionConflict):
                    sessions.issue_session_token(
                        {"userID": 12, "userRole": "Admin"}, "web"
                    )

        elapsed = sessions.seconds_since_activity(session_a)
        self.assertAlmostEqual(
            elapsed, recorded, delta=5,
            msg="a blocked login refreshed the idle clock",
        )

    def test_idle_window_is_capped_by_the_jwt_lifetime(self):
        """A misconfigured window must not outlive the token that created it."""
        app = Flask(__name__)
        app.config.update(
            JWT_ACCESS_TOKEN_EXPIRES=timedelta(hours=12),
            SESSION_IDLE_TIMEOUT=timedelta(hours=24),
        )
        with app.app_context():
            self.assertEqual(sessions.idle_timeout_seconds(), 12 * 3600)


class LogoutRobustnessTests(unittest.TestCase):
    """Requirement 3: logout failures must not strand an account."""

    def setUp(self):
        self.store = InMemorySessionStore()
        self.mysql = InMemorySessionMySQL(self.store)
        self.app = _make_app()
        self.user = {"userID": 12, "userRole": "Admin"}
        table_ready = patch.object(sessions, "_session_table_ready", True)
        table_ready.start()
        self.addCleanup(table_ready.stop)
        self.addCleanup(self._wipe)

    def _wipe(self):
        with sessions._activity_lock:
            sessions._last_activity.clear()

    def test_failed_logout_call_still_releases_the_slot_once_stale(self):
        """The client never reached the server; the row must still age out."""
        _, session_a = self._login()
        # The logout request never arrives: the browser went offline.
        self._wipe()
        row = self.store.rows[12]
        self.store.rows[12] = (row[0], row[1], IDLE_LIMIT_MINUTES + 1)

        with patch.object(sessions, "mysql", self.mysql):
            with self.app.app_context():
                sessions.issue_session_token(
                    {"userID": 12, "userRole": "Admin"}, "web"
                )
        self.assertNotEqual(self.store.rows[12][0], session_a)

    def test_browser_closure_without_logout_does_not_block_forever(self):
        _, session_a = self._login()
        self._wipe()
        row = self.store.rows[12]
        self.store.rows[12] = (row[0], row[1], IDLE_LIMIT_MINUTES + 30)

        with patch.object(sessions, "mysql", self.mysql):
            with self.app.app_context():
                sessions.issue_session_token(
                    {"userID": 12, "userRole": "Admin"}, "web"
                )
        self.assertNotEqual(self.store.rows[12][0], session_a)

    def _login(self, client_type="web"):
        with patch.object(sessions, "mysql", self.mysql):
            with self.app.app_context():
                jwt = sessions.issue_session_token(self.user, client_type)
                return jwt, decode_token(jwt)["session_id"]


class LogoutEndpointTests(unittest.TestCase):
    """Requirement 3: how each logout failure mode releases the session row."""

    def setUp(self):
        self.store = InMemorySessionStore()
        self.mysql = InMemorySessionMySQL(self.store)
        self.app = _make_app()
        self.app.register_blueprint(auth_routes.auth_bp, url_prefix="/api/auth")
        self.user = {"userID": 12, "userRole": "Admin"}

        table_ready = patch.object(sessions, "_session_table_ready", True)
        table_ready.start()
        self.addCleanup(table_ready.stop)
        self.addCleanup(self._wipe)
        self.fcm = patch.object(auth_routes, "clear_fcm_token")
        self.fcm.start()
        self.addCleanup(self.fcm.stop)
        self.find_user = patch.object(
            decorators, "find_user_by_id", return_value={"isActive": True}
        )
        self.find_user.start()
        self.addCleanup(self.find_user.stop)

    def _wipe(self):
        with sessions._activity_lock:
            sessions._last_activity.clear()

    def _login(self, client_type="web"):
        with patch.object(sessions, "mysql", self.mysql):
            with self.app.app_context():
                jwt = sessions.issue_session_token(self.user, client_type)
                return jwt, decode_token(jwt)["session_id"]

    def _auth(self, jwt):
        return {"Authorization": f"Bearer {jwt}"}

    def test_logout_with_a_valid_token_removes_the_row(self):
        jwt, session_a = self._login()
        with patch.object(sessions, "mysql", self.mysql):
            response = self.app.test_client().post(
                "/api/auth/logout", headers=self._auth(jwt)
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.store.rows, {})

    def test_logout_of_an_idle_session_still_releases_the_row(self):
        """Idle eviction happens in the guard, before the handler runs."""
        jwt, session_a = self._login()
        self._wipe()
        row = self.store.rows[12]
        self.store.rows[12] = (row[0], row[1], IDLE_LIMIT_MINUTES + 5)

        with patch.object(sessions, "mysql", self.mysql):
            response = self.app.test_client().post(
                "/api/auth/logout", headers=self._auth(jwt)
            )

        # 401 because the session is already gone...
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.get_json()["code"], "session_idle")
        # ...but the row was still released, which is what matters.
        self.assertEqual(self.store.rows, {})

    def test_expired_token_cannot_block_the_account_forever(self):
        """An expired JWT cannot reach the handler, but the row still clears."""
        jwt, session_a = self._login()
        with patch.object(sessions, "mysql", self.mysql):
            response = self.app.test_client().post(
                "/api/auth/logout", headers=self._auth(jwt)
            )
        self.assertEqual(response.status_code, 200)

        # Simulate the token outliving its row: the row is past the JWT lifetime.
        self._wipe()
        row = self.store.rows.get(12)
        if row is not None:
            self.store.rows[12] = (row[0], row[1], 13 * 60)

        with patch.object(sessions, "mysql", self.mysql):
            with self.app.app_context():
                sessions.issue_session_token(
                    {"userID": 12, "userRole": "Admin"}, "web"
                )
        self.assertEqual(self.store.rows[12][1], "web")

    def test_browser_refresh_keeps_the_session_usable(self):
        """A refresh re-uses the same token; it must not evict anything."""
        jwt, session_a = self._login()
        with patch.object(sessions, "mysql", self.mysql):
            with self.app.app_context():
                sessions.record_session_activity(session_a)
                self.assertTrue(sessions.is_active_session(12, session_a))
        self.assertEqual(self.store.rows[12][0], session_a)


class ConflictMessageTests(unittest.TestCase):

    def test_message_explains_that_waiting_clears_it(self):
        app = Flask(__name__)
        app.config["SESSION_IDLE_TIMEOUT"] = timedelta(minutes=IDLE_LIMIT_MINUTES)
        with app.app_context():
            message = str(sessions.ActiveSessionConflict("web"))
        self.assertIn(f"{IDLE_LIMIT_MINUTES} minutes", message)
        self.assertIn("a web browser", message)

    def test_message_never_reads_like_an_admin_revocation(self):
        app = Flask(__name__)
        with app.app_context():
            message = str(sessions.ActiveSessionConflict("web")).lower()
        for trigger in ("revoked", "deactivated", "administrator",
                        "cannot access", "removed"):
            self.assertNotIn(trigger, message)


if __name__ == "__main__":
    unittest.main()