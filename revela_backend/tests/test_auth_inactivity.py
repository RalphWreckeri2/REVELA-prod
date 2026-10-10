"""Inactivity auto-logout: backend enforcement tests.

These cover the security backstop described in requirement 9: even if the
portal's client-side timer is bypassed or disabled, the backend refuses a
session that has gone too long without reported user interaction.
"""
import threading
import time
import unittest
from datetime import timedelta
from unittest.mock import patch

from flask import Flask
from flask_jwt_extended import JWTManager, create_access_token, decode_token

from api.auth import routes as auth_routes
from api.auth import sessions
from api.middleware import decorators

from tests.test_auth_sessions import (
    IDLE_LIMIT_MINUTES,
    InMemorySessionMySQL,
    InMemorySessionStore,
    SESSION_LIFETIME_HOURS,
)

IDLE_LIMIT_SECONDS = IDLE_LIMIT_MINUTES * 60


def _make_app(include_auth_routes=False, idle_timeout_minutes=IDLE_LIMIT_MINUTES):
    app = Flask(__name__)
    app.config.update(
        JWT_SECRET_KEY="test-secret",
        JWT_ACCESS_TOKEN_EXPIRES=timedelta(hours=12),
        SESSION_IDLE_TIMEOUT=timedelta(minutes=idle_timeout_minutes),
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


class InactivityTests(unittest.TestCase):

    def setUp(self):
        self.store = InMemorySessionStore()
        self.mysql = InMemorySessionMySQL(self.store)
        self.user = {"userID": 12, "userRole": "Inspector"}
        self.app = _make_app(include_auth_routes=True)
        self.addCleanup(sessions.forget_session, None)
        # The activity map is module-global; never let it leak between tests.
        self.addCleanup(self._reset_activity)
        # Skip the CREATE TABLE bootstrap so the in-memory cursor only ever sees
        # real session queries.
        table_ready = patch.object(sessions, "_session_table_ready", True)
        table_ready.start()
        self.addCleanup(table_ready.stop)

    def _reset_activity(self):
        with sessions._activity_lock:
            sessions._last_activity.clear()

    def _login(self, client_type="web"):
        """Log in for real; returns ``(signed_jwt, session_id)``.

        The JWT is genuinely signed so the endpoints can authenticate it, and
        the session id is read back out of the claims for age simulation.
        """
        with patch.object(sessions, "mysql", self.mysql):
            with self.app.app_context():
                jwt = sessions.issue_session_token(self.user, client_type)
                return jwt, decode_token(jwt)["session_id"]

    def _age_activity(self, session_id, seconds):
        """Simulate `seconds` passing since the last reported interaction."""
        with sessions._activity_lock:
            sessions._last_activity[session_id] = time.monotonic() - seconds

    # ── Requirement 9: backend enforcement ───────────────────────────────────
    def test_session_stays_active_while_activity_is_reported(self):
        token, session_id = self._login()
        with patch.object(sessions, "mysql", self.mysql):
            with self.app.app_context():
                for _ in range(50):
                    sessions.record_session_activity(session_id)
                    self.assertTrue(sessions.is_active_session(12, session_id))

    def test_backend_refuses_session_after_the_idle_limit_without_activity(self):
        token, session_id = self._login()
        with patch.object(sessions, "mysql", self.mysql):
            with self.app.app_context():
                self._age_activity(session_id, IDLE_LIMIT_SECONDS - 60)
                self.assertTrue(sessions.is_active_session(12, session_id))

                self._age_activity(session_id, IDLE_LIMIT_SECONDS + 1)
                active, code = sessions.check_active_session(12, session_id)

        self.assertFalse(active)
        self.assertEqual(code, "session_idle")

    def test_background_polling_does_not_count_as_activity(self):
        """Repeated liveness checks must never extend the idle window."""
        token, session_id = self._login()
        with patch.object(sessions, "mysql", self.mysql):
            with self.app.app_context():
                # A poll must not refresh the recorded interaction time.
                self._age_activity(session_id, 60)
                self.assertTrue(sessions.is_active_session(12, session_id))
                self.assertGreaterEqual(
                    sessions.seconds_since_activity(session_id), 60,
                    "a background poll reset the idle window",
                )

                # A dashboard polling every 20s for an hour with no input at all.
                elapsed = 0
                expired_after = None
                for _ in range(180):  # 180 * 20s = 60 minutes
                    elapsed += 20
                    self._age_activity(session_id, elapsed)
                    if not sessions.is_active_session(12, session_id):
                        expired_after = elapsed
                        break

        self.assertIsNotNone(expired_after, "polling kept an idle session alive")
        self.assertGreaterEqual(expired_after, IDLE_LIMIT_SECONDS)
        self.assertLessEqual(
            expired_after, IDLE_LIMIT_SECONDS + 20,
            "the polling traffic extended the inactivity window",
        )

    def test_protected_route_returns_inactivity_401_with_code(self):
        token, session_id = self._login()
        with patch.object(sessions, "mysql", self.mysql), patch.object(
            decorators, "find_user_by_id", return_value={"isActive": True}
        ):
            client = self.app.test_client()
            headers = {"Authorization": f"Bearer {token}"}
            self.assertEqual(client.get("/private", headers=headers).status_code, 200)

            with self.app.app_context():
                self._age_activity(session_id, IDLE_LIMIT_SECONDS + 1)

            response = client.get("/private", headers=headers)

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.get_json()["code"], "session_idle")
        self.assertIn("inactivity", response.get_json()["message"])

    # ── Requirement 7: the slot is released for the next device ──────────────
    def test_idle_session_row_is_deleted_so_the_slot_is_released(self):
        token, session_id = self._login()
        self.assertIn(12, self.store.rows)

        with patch.object(sessions, "mysql", self.mysql):
            with self.app.app_context():
                self._age_activity(session_id, IDLE_LIMIT_SECONDS + 1)
                sessions.is_active_session(12, session_id)

        self.assertNotIn(12, self.store.rows)

    def test_device_b_can_log_in_after_device_a_idles_out(self):
        device_a, session_a = self._login("web")

        with patch.object(sessions, "mysql", self.mysql):
            with self.app.app_context():
                self._age_activity(session_a, IDLE_LIMIT_SECONDS + 1)
                sessions.is_active_session(12, session_a)
                self.assertEqual(self.store.rows, {})

            # Device B is now able to claim the account.
            device_b, session_b = self._login("mobile")

        self.assertNotEqual(session_a, session_b)
        self.assertEqual(self.store.rows[12][1], "mobile")

    def test_idle_claim_is_released_even_without_a_prior_api_call(self):
        """A device that walked away must not hold the account for 12 hours."""
        device_a, session_a = self._login("web")

        # No further requests from Device A at all - it just went idle.
        with patch.object(sessions, "mysql", self.mysql):
            with self.app.app_context():
                self._age_activity(session_a, IDLE_LIMIT_SECONDS + 1)
            device_b, session_b = self._login("web")

        self.assertNotEqual(session_a, session_b)
        self.assertEqual(self.store.rows[12][0], session_b)

    # ── First-login-wins must keep working for live sessions ──────────────────
    def test_live_session_still_blocks_a_second_login(self):
        device_a, session_a = self._login("web")
        with patch.object(sessions, "mysql", self.mysql):
            with self.app.app_context():
                with self.assertRaises(sessions.ActiveSessionConflict):
                    sessions.issue_session_token(self.user, "mobile")

        self.assertEqual(self.store.rows[12][0], session_a)

    def test_activity_below_the_limit_still_blocks_a_second_login(self):
        device_a, session_a = self._login("web")
        with patch.object(sessions, "mysql", self.mysql):
            with self.app.app_context():
                self._age_activity(session_a, IDLE_LIMIT_SECONDS - 120)
                with self.assertRaises(sessions.ActiveSessionConflict):
                    sessions.issue_session_token(self.user, "mobile")

        self.assertEqual(self.store.rows[12][0], session_a)

    # ── Requirement 8: the 12-hour JWT ceiling is untouched ──────────────────
    def test_twelve_hour_lifetime_is_still_enforced_for_active_sessions(self):
        token, session_id = self._login()
        with patch.object(sessions, "mysql", self.mysql):
            with self.app.app_context():
                # Constantly "active", but issued over 12 hours ago.
                self._age_activity(session_id, 5)
                store_row = self.store.rows[12]
                self.store.rows[12] = (store_row[0], store_row[1],
                                       (SESSION_LIFETIME_HOURS + 1) * 60)
                active, code = sessions.check_active_session(12, session_id)

        self.assertFalse(active)
        self.assertEqual(code, "session_ended")

    def test_idle_limit_is_configurable_and_independent_of_jwt_lifetime(self):
        self.assertEqual(
            _make_app(idle_timeout_minutes=5).config["SESSION_IDLE_TIMEOUT"],
            timedelta(minutes=5),
        )
        with _make_app(idle_timeout_minutes=5).app_context():
            self.assertEqual(sessions.idle_timeout_seconds(), 300.0)
            # The JWT ceiling is untouched.
            self.assertEqual(sessions.session_lifetime_hours(), 12.0)

    # ── Restart bootstrap (no in-process knowledge of the session) ────────────
    def test_unknown_session_older_than_the_limit_is_refused(self):
        token, session_id = self._login()
        # Simulate a process restart: the map no longer knows this session.
        self._reset_activity()
        store_row = self.store.rows[12]
        self.store.rows[12] = (store_row[0], store_row[1], IDLE_LIMIT_MINUTES + 5)

        with patch.object(sessions, "mysql", self.mysql):
            with self.app.app_context():
                active, code = sessions.check_active_session(12, session_id)

        self.assertFalse(active)
        self.assertEqual(code, "session_idle")

    def test_unknown_session_inside_the_limit_is_granted_bootstrap_grace(self):
        token, session_id = self._login()
        self._reset_activity()
        store_row = self.store.rows[12]
        self.store.rows[12] = (store_row[0], store_row[1], IDLE_LIMIT_MINUTES - 10)

        with patch.object(sessions, "mysql", self.mysql):
            with self.app.app_context():
                active, _ = sessions.check_active_session(12, session_id)

        self.assertTrue(active)

    def test_unknown_session_fails_closed_for_a_claim(self):
        """Without knowledge of a session, a new login must not evict it."""
        device_a, session_a = self._login("web")
        self._reset_activity()

        with patch.object(sessions, "mysql", self.mysql):
            with self.app.app_context():
                with self.assertRaises(sessions.ActiveSessionConflict):
                    sessions.issue_session_token(self.user, "mobile")

        self.assertEqual(self.store.rows[12][0], session_a)

    # ── The /api/auth/activity endpoint ──────────────────────────────────────
    def test_activity_endpoint_resets_the_idle_window(self):
        token, session_id = self._login()
        self._age_activity(session_id, IDLE_LIMIT_SECONDS - 30)

        with patch.object(sessions, "mysql", self.mysql), patch.object(
            decorators, "find_user_by_id", return_value={"isActive": True}
        ):
            client = self.app.test_client()
            headers = {"Authorization": f"Bearer {token}"}
            response = client.post("/api/auth/activity", headers=headers)
            self.assertEqual(response.status_code, 200)

            # "Stay Logged In" pushed the deadline back out.
            self.assertLess(
                sessions.seconds_since_activity(session_id), IDLE_LIMIT_SECONDS - 25
            )
            self.assertEqual(client.get("/private", headers=headers).status_code, 200)

    def test_activity_endpoint_requires_authentication(self):
        client = self.app.test_client()
        self.assertEqual(client.post("/api/auth/activity").status_code, 401)

    def test_activity_is_only_reported_by_the_dedicated_endpoint(self):
        """No background surface may report activity on the user's behalf."""
        import inspect
        source = inspect.getsource(auth_routes)
        # Exactly one call site: POST /api/auth/activity.
        self.assertEqual(source.count("record_session_activity("), 1)
        self.assertIn('@auth_bp.route("/activity", methods=["POST"])', source)

    def test_sessions_of_different_users_do_not_interfere(self):
        token_a, session_a = self._login()
        self._age_activity(session_a, IDLE_LIMIT_SECONDS + 5)

        other = {"userID": 77, "userRole": "Admin"}
        with patch.object(sessions, "mysql", self.mysql):
            with self.app.app_context():
                jwt_b = sessions.issue_session_token(other, "web")
                session_b = decode_token(jwt_b)["session_id"]

        self.assertTrue(sessions.is_session_idle(session_a))
        self.assertFalse(sessions.is_session_idle(session_b))
        self.assertIn(12, self.store.rows)
        self.assertIn(77, self.store.rows)

    # ── Housekeeping ─────────────────────────────────────────────────────────
    def test_forget_session_clears_tracking(self):
        token, session_id = self._login()
        self.assertIsNotNone(sessions.seconds_since_activity(session_id))
        sessions.forget_session(session_id)
        self.assertIsNone(sessions.seconds_since_activity(session_id))
        self.assertFalse(sessions.is_session_idle(session_id))

    def test_is_session_idle_fails_closed_for_unknown_sessions(self):
        self.assertFalse(sessions.is_session_idle("never-seen"))
        self.assertIsNone(sessions.seconds_since_activity("never-seen"))

    def test_stale_entries_are_pruned_from_the_activity_map(self):
        ids = [f"stale-{i}" for i in range(50)]
        with sessions._activity_lock:
            for session_id in ids:
                sessions._last_activity[session_id] = time.monotonic() - 10_000
        sessions.record_session_activity("fresh")
        with sessions._activity_lock:
            remaining = set(sessions._last_activity)
        self.assertIn("fresh", remaining)
        self.assertFalse(remaining & set(ids))

    def test_concurrent_activity_reporting_stays_consistent(self):
        token, session_id = self._login()
        barrier = threading.Barrier(8)

        def report():
            barrier.wait(timeout=5)
            for _ in range(20):
                sessions.record_session_activity(session_id)

        threads = [threading.Thread(target=report) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        with patch.object(sessions, "mysql", self.mysql):
            with self.app.app_context():
                self.assertTrue(sessions.is_active_session(12, session_id))


if __name__ == "__main__":
    unittest.main()