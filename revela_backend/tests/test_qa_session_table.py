import unittest
from datetime import timedelta
from unittest.mock import MagicMock, patch

from flask import Flask

from api.auth import sessions


class QaSessionTableTests(unittest.TestCase):

    def setUp(self):
        self.cursor = MagicMock()
        self.connection = MagicMock()
        self.connection.cursor.return_value = self.cursor
        self.mysql = MagicMock(connection=self.connection)
        self.mysql_patch = patch.object(sessions, "mysql", self.mysql)
        self.mysql_patch.start()
        self.addCleanup(self.mysql_patch.stop)
        self.qa_ready_patch = patch.object(sessions, "_qa_session_table_ready", False)
        self.qa_ready_patch.start()
        self.addCleanup(self.qa_ready_patch.stop)
        self.normal_ready_patch = patch.object(sessions, "_session_table_ready", False)
        self.normal_ready_patch.start()
        self.addCleanup(self.normal_ready_patch.stop)
        self.app = Flask(__name__)
        self.app.config.update(
            REVELA_QA_MODE=True,
            JWT_ACCESS_TOKEN_EXPIRES=timedelta(hours=12),
        )

    def test_qa_checks_existing_table_without_ddl_or_commit(self):
        with self.app.app_context():
            sessions._ensure_session_table()

        query = self.cursor.execute.call_args.args[0]
        self.assertEqual(
            " ".join(query.lower().split()),
            "select 1 from user_active_sessions limit 0",
        )
        self.connection.commit.assert_not_called()
        self.assertTrue(sessions._qa_session_table_ready)

    def test_missing_qa_table_fails_clearly_without_fallback(self):
        self.cursor.execute.side_effect = RuntimeError("table is missing")

        with self.app.app_context():
            with self.assertRaisesRegex(
                RuntimeError,
                "Required pre-provisioned QA table 'user_active_sessions' is unavailable",
            ):
                sessions._ensure_session_table()

        self.assertFalse(sessions._qa_session_table_ready)
        self.assertFalse(sessions._session_table_ready)
        self.connection.commit.assert_not_called()
        self.assertNotIn(
            "create table",
            " ".join(call.args[0].lower() for call in self.cursor.execute.call_args_list),
        )

    def test_qa_session_issuance_uses_only_select_and_insert(self):
        self.cursor.fetchone.return_value = None

        with patch.object(sessions, "create_access_token", return_value="qa-token"):
            with self.app.app_context():
                token = sessions.issue_session_token(
                    {"userID": 42, "userRole": "Inspector"},
                    "mobile",
                )

        self.assertEqual(token, "qa-token")
        queries = [
            " ".join(call.args[0].lower().split())
            for call in self.cursor.execute.call_args_list
        ]
        self.assertEqual(len(queries), 2)
        self.assertTrue(queries[0].startswith("select 1 from user_active_sessions limit 0"))
        self.assertTrue(queries[1].startswith("insert into user_active_sessions"))
        self.assertFalse(any("create table" in query or "alter table" in query for query in queries))
        self.connection.commit.assert_called_once()

    def test_normal_mode_retains_existing_create_behavior(self):
        normal_app = Flask(__name__)
        normal_app.config["REVELA_QA_MODE"] = False

        with normal_app.app_context():
            sessions._ensure_session_table()

        query = self.cursor.execute.call_args.args[0]
        self.assertIn("CREATE TABLE IF NOT EXISTS user_active_sessions", query)
        self.connection.commit.assert_called_once()
        self.assertTrue(sessions._session_table_ready)
        self.assertFalse(sessions._qa_session_table_ready)


if __name__ == "__main__":
    unittest.main()
