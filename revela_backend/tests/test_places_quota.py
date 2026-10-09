import unittest
from unittest.mock import MagicMock, patch

from api.utils import places_quota


class PlacesQuotaLedgerTests(unittest.TestCase):

    def setUp(self):
        places_quota._table_ready = False

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
        self.assertTrue(all("requestCount < %s" in query for query in update_queries))
        connection.commit.assert_called_once()
        connection.rollback.assert_not_called()

    @patch("api.utils.places_quota._ensure_table")
    def test_daily_denial_refunds_monthly_reservation(self, _ensure):
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
        self.assertTrue(any(
            "requestCount = requestCount - 1" in call.args[0]
            for call in cursor.execute.call_args_list
        ))
        connection.commit.assert_called_once()

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
