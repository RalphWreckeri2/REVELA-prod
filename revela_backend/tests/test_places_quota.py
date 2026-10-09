import unittest
from unittest.mock import MagicMock, patch

from api.utils import places_quota


class PlacesQuotaLedgerTests(unittest.TestCase):

    def setUp(self):
        places_quota._table_ready = False

    def test_detection_budget_setup_does_not_drop_or_truncate_tables(self):
        from api.flags import service

        cursor = MagicMock()
        with patch.object(service, "mysql") as mysql, \
                patch.object(service, "_budget_tables_ready", False):
            mysql.connection.cursor.return_value = cursor

            service._ensure_budget_tables()

        queries = [call.args[0].upper()
                   for call in cursor.execute.call_args_list]
        self.assertTrue(
            any("CREATE TABLE IF NOT EXISTS PLACES_API_USAGE" in q for q in queries))
        self.assertTrue(
            any("CREATE TABLE IF NOT EXISTS SCAN_POINT_LOG" in q for q in queries))
        self.assertFalse(
            any("DROP TABLE" in q or "TRUNCATE TABLE" in q for q in queries))
        mysql.connection.commit.assert_called_once()

    @patch("api.utils.places_quota._ensure_table")
    def test_reservation_uses_conditional_updates_and_commits(self, _ensure):
        connection = MagicMock()
        cursor = connection.cursor.return_value
        cursor.rowcount = 1

        allowed, reason = places_quota.reserve_usage_slot(
            connection, "imp_ts_month", "imp_ts_day", 2500, 75
        )

        self.assertTrue(allowed)
        self.assertIsNone(reason)
        update_queries = [
            call.args[0]
            for call in cursor.execute.call_args_list
            if "UPDATE places_api_usage SET requestCount = requestCount + 1" in call.args[0]
        ]
        self.assertEqual(len(update_queries), 2)
        self.assertTrue(
            all("requestCount < %s" in query for query in update_queries))
        connection.commit.assert_called_once()
        connection.rollback.assert_not_called()

    @patch("api.utils.places_quota._ensure_table")
    def test_daily_denial_rolls_back_monthly_reservation(self, _ensure):
        connection = MagicMock()
        cursor = connection.cursor.return_value
        cursor.rowcount = 1

        def execute(sql, _params=None):
            if "WHERE usageDate = CURDATE()" in sql and "requestCount = requestCount + 1" in sql:
                cursor.rowcount = 0
            else:
                cursor.rowcount = 1

        cursor.execute.side_effect = execute
        allowed, reason = places_quota.reserve_usage_slot(
            connection, "imp_ts_month", "imp_ts_day", 2500, 75
        )

        self.assertFalse(allowed)
        self.assertEqual(reason, "daily_quota_exceeded")
        connection.rollback.assert_called_once()
        connection.commit.assert_not_called()

    @patch("api.utils.places_quota._ensure_table")
    def test_shared_and_workflow_budgets_reserve_atomically(self, _ensure):
        connection = MagicMock()
        cursor = connection.cursor.return_value
        cursor.rowcount = 1

        allowed, reason = places_quota.reserve_usage_slot(
            connection,
            "imp_ts_month",
            "imp_ts_day",
            2500,
            400,
            additional_daily_limits=(("ts_snap_day", 100),),
        )

        self.assertTrue(allowed)
        self.assertIsNone(reason)
        increments = [
            call for call in cursor.execute.call_args_list
            if "UPDATE places_api_usage SET requestCount = requestCount + 1" in call.args[0]
        ]
        self.assertEqual(len(increments), 3)
        self.assertEqual(increments[0].args[1][0], "imp_ts_month")
        self.assertEqual(increments[1].args[1][0], "imp_ts_day")
        self.assertEqual(increments[2].args[1][0], "ts_snap_day")
        connection.commit.assert_called_once()
        connection.rollback.assert_not_called()

    @patch("api.utils.places_quota._ensure_table")
    def test_workflow_daily_denial_rolls_back_all_buckets(self, _ensure):
        connection = MagicMock()
        cursor = connection.cursor.return_value

        def execute(sql, params=None):
            if "UPDATE places_api_usage SET requestCount = requestCount + 1" in sql:
                cursor.rowcount = 0 if params[0] == "ts_snap_day" else 1
            else:
                cursor.rowcount = 1

        cursor.execute.side_effect = execute
        allowed, reason = places_quota.reserve_usage_slot(
            connection,
            "imp_ts_month",
            "imp_ts_day",
            2500,
            400,
            additional_daily_limits=(("ts_snap_day", 100),),
        )

        self.assertFalse(allowed)
        self.assertEqual(reason, "daily_quota_exceeded")
        connection.rollback.assert_called_once()
        connection.commit.assert_not_called()

    @patch("api.utils.places_quota._ensure_table")
    def test_monthly_denial_never_attempts_daily_increment(self, _ensure):
        connection = MagicMock()
        cursor = connection.cursor.return_value

        def execute(sql, _params=None):
            cursor.rowcount = (
                0 if "requestCount = requestCount + 1" in sql else 1
            )

        cursor.execute.side_effect = execute
        allowed, reason = places_quota.reserve_usage_slot(
            connection, "imp_ts_month", "imp_ts_day", 2500, 75
        )

        self.assertFalse(allowed)
        self.assertEqual(reason, "monthly_quota_exceeded")
        self.assertFalse(any(
            "WHERE usageDate = CURDATE()" in call.args[0]
            and "requestCount = requestCount + 1" in call.args[0]
            for call in cursor.execute.call_args_list
        ))

    @patch("api.utils.places_quota._ensure_table")
    def test_database_error_rolls_back_and_propagates(self, _ensure):
        connection = MagicMock()
        cursor = connection.cursor.return_value
        cursor.execute.side_effect = RuntimeError("database unavailable")

        with self.assertRaisesRegex(RuntimeError, "database unavailable"):
            places_quota.reserve_usage_slot(
                connection, "imp_ts_month", "imp_ts_day", 2500, 75
            )

        connection.rollback.assert_called_once()
        connection.commit.assert_not_called()


if __name__ == "__main__":
    unittest.main()
