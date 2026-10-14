import queue
import unittest
from unittest.mock import MagicMock, patch

from flask import Flask, request

from api.middleware import decorators
from api.notifications import routes


class NotificationStreamSecurityTests(unittest.TestCase):

    def setUp(self):
        app = Flask(__name__)
        app.config["TESTING"] = True
        app.register_blueprint(
            routes.notifications_bp,
            url_prefix="/api/notifications",
        )
        self.client = app.test_client()

        def verify_bearer_header():
            if request.headers.get("Authorization") != (
                "Bearer test-only-qa-access-token"
            ):
                raise RuntimeError("A valid bearer token is required")

        self.check_active_session = MagicMock(return_value=(True, None))
        patches = (
            (decorators, "verify_jwt_in_request", verify_bearer_header),
            (decorators, "get_jwt_identity", lambda: 7),
            (
                decorators,
                "get_jwt",
                lambda: {"role": "Admin", "session_id": "qa-test-session"},
            ),
            (decorators, "get_current_role", lambda: "Admin"),
            (
                decorators,
                "check_active_session",
                self.check_active_session,
            ),
            (
                decorators,
                "find_user_by_id",
                lambda _user_id: {
                    "isActive": True,
                    "userRole": "Admin",
                },
            ),
            (routes, "get_jwt_identity", lambda: 7),
            (routes.hub, "subscribe", lambda _user_id: queue.Queue()),
            (routes.hub, "unsubscribe", lambda _user_id, _sub: None),
        )
        for module, name, value in patches:
            patcher = patch.object(module, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_query_string_jwt_is_not_accepted(self):
        response = self.client.get(
            "/api/notifications/stream?token=not-a-real-token"
        )

        self.assertEqual(response.status_code, 401)
        self.check_active_session.assert_not_called()

    def test_missing_or_invalid_authorization_is_rejected(self):
        for authorization in (None, "Bearer invalid-test-token"):
            with self.subTest(authorization=authorization):
                headers = {}
                if authorization is not None:
                    headers["Authorization"] = authorization

                response = self.client.get(
                    "/api/notifications/stream",
                    headers=headers,
                )

                self.assertEqual(response.status_code, 401)
        self.check_active_session.assert_not_called()

    def test_bearer_authenticated_stream_starts(self):
        response = self.client.get(
            "/api/notifications/stream",
            headers={"Authorization": "Bearer test-only-qa-access-token"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, "text/event-stream")
        self.assertIn(b'"type": "connected"', next(response.response))
        self.check_active_session.assert_called_once_with(7, "qa-test-session")
        response.close()


if __name__ == "__main__":
    unittest.main()
