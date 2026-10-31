import unittest
from unittest.mock import patch

from flask import Flask, request

from api.middleware import decorators
from api.notifications import routes, service


class NotificationPaginationTests(unittest.TestCase):
    def setUp(self):
        app = Flask(__name__)
        app.config["TESTING"] = True
        app.register_blueprint(routes.notifications_bp, url_prefix="/api/notifications")
        self.client = app.test_client()

        for module, name, value in (
            (decorators, "verify_jwt_in_request", lambda: None),
            (decorators, "get_jwt_identity", lambda: 7),
            (decorators, "get_jwt", lambda: {}),
            (decorators, "_verify_user_and_session", lambda _identity, _claims: None),
            (routes, "get_jwt_identity", lambda: 7),
        ):
            patcher = patch.object(module, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_route_passes_valid_page_and_preserves_default(self):
        with patch.object(routes.notif_service, "list_notifications", return_value=({"data": [], "total": 52}, None)) as listing:
            response = self.client.get("/api/notifications?limit=3&offset=6")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json["total"], 52)
            listing.assert_called_once_with(7, limit=3, offset=6)

            self.client.get("/api/notifications")
            listing.assert_called_with(7, limit=50, offset=0)

    def test_route_rejects_invalid_page_parameters(self):
        for query in ("limit=0", "limit=51", "limit=abc", "offset=-1", "offset=abc"):
            with self.subTest(query=query):
                self.assertEqual(self.client.get(f"/api/notifications?{query}").status_code, 400)

    def test_service_fetches_older_notifications_for_only_this_recipient(self):
        with patch.object(service, "_ensure_tables"), patch.object(service, "mysql") as mysql:
            cursor = mysql.connection.cursor.return_value
            cursor.fetchone.return_value = {"n": 52}
            cursor.fetchall.return_value = [{"id": 42, "createdAt": "2026-10-31 10:00:00", "readAt": None}]

            result, error = service.list_notifications(7, limit=3, offset=6)

            self.assertIsNone(error)
            self.assertEqual(result["total"], 52)
            self.assertEqual(result["data"][0]["id"], 42)
            count_query, select_query = cursor.execute.call_args_list
            self.assertIn("recipientUserId = %s", count_query.args[0])
            self.assertEqual(count_query.args[1], (7,))
            self.assertIn("ORDER BY createdAt DESC, id DESC", select_query.args[0])
            self.assertEqual(select_query.args[1], (7, 3, 6))


if __name__ == "__main__":
    unittest.main()
