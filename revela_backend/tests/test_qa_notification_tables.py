import unittest
from unittest.mock import MagicMock, patch

from flask import Flask

from api.auth import routes as auth_routes
from api.middleware import decorators
from api.notifications import routes as notification_routes
from api.notifications import service as notification_service


class QaNotificationTableTests(unittest.TestCase):

    def setUp(self):
        self.cursor = MagicMock()
        self.connection = MagicMock()
        self.connection.cursor.return_value = self.cursor
        self.mysql_patch = patch.object(
            notification_service,
            "mysql",
            MagicMock(connection=self.connection),
        )
        self.mysql_patch.start()
        self.addCleanup(self.mysql_patch.stop)

        self.tables_ready_patch = patch.object(
            notification_service, "_tables_ready", False
        )
        self.tables_ready_patch.start()
        self.addCleanup(self.tables_ready_patch.stop)
        self.qa_validated_patch = patch.object(
            notification_service, "_qa_tables_validated", False
        )
        self.qa_validated_patch.start()
        self.addCleanup(self.qa_validated_patch.stop)

    def _queries(self):
        return [
            " ".join(call.args[0].lower().split())
            for call in self.cursor.execute.call_args_list
        ]

    def test_qa_validates_required_columns_on_both_tables_without_writes(self):
        with patch.object(notification_service, "is_qa_mode", return_value=True):
            notification_service._ensure_tables()

        queries = self._queries()
        self.assertEqual(len(queries), 2)
        self.assertIn("`id`", queries[0])
        self.assertIn("`recipientuserid`", queries[0])
        self.assertIn("`readat`", queries[0])
        self.assertIn(
            "from `revela_test_mobile_phase72`.`revela_notifications` limit 0",
            queries[0],
        )
        self.assertIn("`email_inspection_alerts`", queries[1])
        self.assertIn("`updatedat`", queries[1])
        self.assertIn(
            "from `revela_test_mobile_phase72`.`user_app_preferences` limit 0",
            queries[1],
        )
        self.assertFalse(any("create " in query or "alter " in query for query in queries))
        self.assertFalse(any("drop " in query or "insert " in query for query in queries))
        self.connection.commit.assert_not_called()
        self.assertTrue(notification_service._tables_ready)
        self.assertTrue(notification_service._qa_tables_validated)
        self.cursor.close.assert_called_once()

    def test_missing_table_or_column_fails_closed_without_caching_readiness(self):
        self.cursor.execute.side_effect = [
            None,
            RuntimeError("unknown column"),
        ]

        with patch.object(notification_service, "is_qa_mode", return_value=True):
            with self.assertRaisesRegex(
                RuntimeError,
                "Required pre-provisioned QA notification tables",
            ):
                notification_service._ensure_tables()

        self.assertEqual(len(self._queries()), 2)
        self.assertFalse(notification_service._tables_ready)
        self.assertFalse(notification_service._qa_tables_validated)
        self.connection.commit.assert_not_called()
        self.cursor.close.assert_called_once()

    def test_missing_first_table_fails_without_checking_or_creating_other_tables(self):
        notification_service._tables_ready = True
        self.cursor.execute.side_effect = RuntimeError("table does not exist")

        with patch.object(notification_service, "is_qa_mode", return_value=True):
            with self.assertRaisesRegex(
                RuntimeError,
                "Required pre-provisioned QA notification tables",
            ):
                notification_service._ensure_tables()

        queries = self._queries()
        self.assertEqual(len(queries), 1)
        self.assertIn("revela_notifications", queries[0])
        self.assertFalse(notification_service._tables_ready)
        self.assertFalse(notification_service._qa_tables_validated)
        self.connection.commit.assert_not_called()
        self.cursor.close.assert_called_once()

    def test_qa_mode_never_falls_through_to_production_initializer(self):
        notification_service._tables_ready = True
        self.cursor.execute.side_effect = RuntimeError("missing QA table")

        with patch.object(notification_service, "is_qa_mode", return_value=True):
            with self.assertRaisesRegex(RuntimeError, "pre-provisioned QA"):
                notification_service._ensure_tables()

        queries = self._queries()
        self.assertEqual(len(queries), 1)
        self.assertIn("revela_test_mobile_phase72", queries[0])
        self.assertFalse(any("create table" in query for query in queries))
        self.assertFalse(notification_service._qa_tables_validated)
        self.connection.commit.assert_not_called()

    def test_non_qa_retains_existing_create_table_behavior(self):
        with patch.object(notification_service, "is_qa_mode", return_value=False):
            notification_service._ensure_tables()

        queries = self._queries()
        self.assertEqual(len(queries), 2)
        self.assertIn("create table if not exists revela_notifications", queries[0])
        self.assertIn("create table if not exists user_app_preferences", queries[1])
        self.connection.commit.assert_called_once()
        self.assertTrue(notification_service._tables_ready)
        self.assertFalse(notification_service._qa_tables_validated)

    def _make_qa_client(self):
        app = Flask(__name__)
        app.config.update(
            TESTING=True,
            REVELA_QA_MODE=True,
        )
        app.register_blueprint(auth_routes.auth_bp, url_prefix="/api/auth")
        app.register_blueprint(
            notification_routes.notifications_bp,
            url_prefix="/api/notifications",
        )

        patches = (
            patch.object(decorators, "verify_jwt_in_request"),
            patch.object(decorators, "get_jwt_identity", return_value="42"),
            patch.object(decorators, "get_jwt", return_value={"session_id": "fake"}),
            patch.object(
                decorators,
                "find_user_by_id",
                return_value={"isActive": True, "userRole": "Inspector"},
            ),
            patch.object(decorators, "check_active_session", return_value=(True, None)),
            patch.object(auth_routes, "get_jwt_identity", return_value="42"),
            patch.object(auth_routes, "get_jwt", return_value={"role": "Inspector"}),
            patch.object(
                auth_routes,
                "find_user_by_id",
                return_value={
                    "userID": 42,
                    "fullName": "Synthetic QA Inspector",
                    "email": "qa.inspector@example.invalid",
                    "userRole": "Inspector",
                    "isActive": True,
                },
            ),
            patch.object(notification_routes, "get_jwt_identity", return_value="42"),
        )
        for patcher in patches:
            patcher.start()
            self.addCleanup(patcher.stop)
        return app.test_client()

    def test_qa_auth_me_uses_validated_preprovisioned_tables(self):
        self.cursor.fetchone.return_value = {"email_inspection_alerts": 1}
        client = self._make_qa_client()

        response = client.get("/api/auth/me")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["emailInspectionAlerts"])
        queries = self._queries()
        self.assertEqual(len(queries), 3)
        self.assertTrue(all("create table" not in query for query in queries))
        self.connection.commit.assert_not_called()

    def test_qa_unread_count_uses_validated_preprovisioned_tables(self):
        self.cursor.fetchone.return_value = {"n": 3}
        client = self._make_qa_client()

        response = client.get("/api/notifications/unread-count")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"count": 3})
        queries = self._queries()
        self.assertEqual(len(queries), 3)
        self.assertTrue(all("create table" not in query for query in queries))
        self.connection.commit.assert_not_called()


if __name__ == "__main__":
    unittest.main()
