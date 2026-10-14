import unittest
from unittest.mock import MagicMock, patch

from api.flags import service as flag_service


class YellowFlagIdempotencyTests(unittest.TestCase):
    def setUp(self):
        self.connection = MagicMock()
        self.cursor = MagicMock()
        self.connection.cursor.return_value = self.cursor
        self.existing = {
            "barangayID": 2,
            "detectedName": "Sample Store",
            "latitude": 14.0,
            "longitude": 121.0,
            "notes": "Check this location",
            "flagColor": "Yellow",
            "reportedByUserID": 9,
        }

    @patch("api.notifications.service.notify_yellow_flag_reported")
    @patch("api.flags.service._within_municipality", return_value=True)
    @patch("api.flags.service.mysql")
    def test_retry_returns_existing_flag_without_second_record_or_notice(
        self, mock_mysql, _within, notify
    ):
        mock_mysql.connection = self.connection
        self.cursor.rowcount = 0
        self.cursor.lastrowid = 41
        self.cursor.fetchone.return_value = self.existing

        result, error = flag_service.insert_yellow_flag(
            business_name="Sample Store",
            lat=14.0,
            lng=121.0,
            barangay_id=2,
            notes="Check this location",
            reported_by_user_id=9,
            client_submission_id="c34cc4d8-7427-42ad-9e2a-15efdd2ed854",
        )

        self.assertIsNone(error)
        self.assertEqual(result["logID"], 41)
        self.assertTrue(result["alreadyAccepted"])
        self.connection.commit.assert_called_once()
        self.assertEqual(self.cursor.execute.call_count, 2)
        notify.assert_not_called()

    @patch("api.flags.service._within_municipality", return_value=True)
    @patch("api.flags.service.mysql")
    def test_reused_key_with_different_data_is_rejected(self, mock_mysql, _within):
        mock_mysql.connection = self.connection
        self.cursor.rowcount = 0
        self.cursor.lastrowid = 41
        self.cursor.fetchone.return_value = self.existing

        result, error = flag_service.insert_yellow_flag(
            business_name="Different Store",
            lat=14.0,
            lng=121.0,
            barangay_id=2,
            notes="Check this location",
            reported_by_user_id=9,
            client_submission_id="c34cc4d8-7427-42ad-9e2a-15efdd2ed854",
        )

        self.assertIsNone(result)
        self.assertIsInstance(error, flag_service.YellowFlagSubmissionConflict)
        self.connection.rollback.assert_called_once()
        self.connection.commit.assert_not_called()

    @patch("api.flags.service._within_municipality", return_value=True)
    @patch("api.flags.service.mysql")
    def test_first_submission_returns_created_flag(self, mock_mysql, _within):
        mock_mysql.connection = self.connection
        self.cursor.rowcount = 1
        self.cursor.lastrowid = 42
        self.cursor.fetchone.return_value = {
            **self.existing,
            "detectedName": "New Store",
        }

        result, error = flag_service.insert_yellow_flag(
            business_name="New Store",
            lat=14.0,
            lng=121.0,
            barangay_id=2,
            notes="Check this location",
            reported_by_user_id=9,
            client_submission_id="5ed7089a-d3dd-40be-aea9-35a1efb4d7e1",
        )

        self.assertIsNone(error)
        self.assertEqual(result["logID"], 42)
        self.assertFalse(result["alreadyAccepted"])
        self.connection.commit.assert_called_once()


if __name__ == "__main__":
    unittest.main()
