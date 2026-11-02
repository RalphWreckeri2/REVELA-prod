import datetime
import unittest
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from api.models import detection_runs


MANILA = ZoneInfo("Asia/Manila")


class DetectionMonthlyQuotaTests(unittest.TestCase):
    def test_month_window_uses_manila_month_boundaries_in_utc(self):
        now = datetime.datetime(2026, 11, 1, 1, 0, tzinfo=MANILA)

        start, end = detection_runs._manila_month_utc_window(now)

        self.assertEqual(start, datetime.datetime(2026, 10, 31, 16, 0))
        self.assertEqual(end, datetime.datetime(2026, 11, 30, 16, 0))

    def test_month_window_handles_december_rollover(self):
        now = datetime.datetime(2026, 12, 31, 23, 59, tzinfo=MANILA)

        start, end = detection_runs._manila_month_utc_window(now)

        self.assertEqual(start, datetime.datetime(2026, 11, 30, 16, 0))
        self.assertEqual(end, datetime.datetime(2026, 12, 31, 16, 0))

    def test_monthly_count_queries_utc_bounds_for_manila_month(self):
        now = datetime.datetime(2026, 11, 1, 1, 0, tzinfo=MANILA)
        cursor = MagicMock()
        cursor.fetchone.return_value = {"cnt": 4}
        connection = MagicMock()
        connection.cursor.return_value = cursor

        with (
            patch.object(detection_runs, "ensure_detection_runs_table"),
            patch.object(detection_runs, "mysql") as mock_mysql,
        ):
            mock_mysql.connection = connection
            count = detection_runs.get_monthly_detection_count(now)

        self.assertEqual(count, 4)
        query, params = cursor.execute.call_args.args
        self.assertIn("startedAt >= %s", query)
        self.assertIn("startedAt < %s", query)
        self.assertIn("status = 'completed'", query)
        self.assertNotIn("completed_with_gaps", query)
        self.assertNotIn("CURRENT_DATE()", query)
        self.assertEqual(
            params,
            (
                datetime.datetime(2026, 10, 31, 16, 0),
                datetime.datetime(2026, 11, 30, 16, 0),
            ),
        )
        cursor.close.assert_called_once()

    def test_latest_detection_run_excludes_incomplete_legacy_status(self):
        cursor = MagicMock()
        connection = MagicMock()
        connection.cursor.return_value = cursor

        with (
            patch.object(detection_runs, "ensure_detection_runs_table"),
            patch.object(detection_runs, "mysql") as mock_mysql,
        ):
            mock_mysql.connection = connection
            detection_runs.get_latest_detection_run()

        query = cursor.execute.call_args.args[0]
        self.assertIn("WHERE r.status = 'completed'", query)
        self.assertNotIn("completed_with_gaps", query)
        cursor.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
