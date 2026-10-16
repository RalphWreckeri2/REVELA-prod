import unittest
from unittest.mock import MagicMock, patch

from api.flags import service


class YellowFlagIdempotencyTests(unittest.TestCase):
    def setUp(self):
        self.mysql = MagicMock()
        self.connection = self.mysql.connection
        self.cursor = self.connection.cursor.return_value
        self.existing = {
            "barangayID": 2,
            "detectedName": "Sample Store",
            "latitude": 14.0,
            "longitude": 121.0,
            "notes": "Check this location",
            "flagColor": "Yellow",
            "reportedByUserID": 9,
        }
        for target, value in (
            ("api.flags.service.mysql", self.mysql),
            ("api.flags.service._within_municipality", MagicMock(return_value=True)),
            ("api.flags.service._validate_yellow_flag_barangay", MagicMock()),
        ):
            mock = patch(target, value)
            mock.start()
            self.addCleanup(mock.stop)
        notification = patch("api.notifications.service.notify_yellow_flag_reported")
        self.notify = notification.start()
        self.addCleanup(notification.stop)
        self.cursor.lastrowid = 41
        self.cursor.fetchone.return_value = self.existing

    def submit(self, **changes):
        payload = dict(
            business_name="Sample Store", lat=14.0, lng=121.0, barangay_id=2,
            notes="Check this location", reported_by_user_id=9,
            client_submission_id="c34cc4d8-7427-42ad-9e2a-15efdd2ed854",
        )
        payload.update(changes)
        return service.insert_yellow_flag(**payload)

    def test_retry_returns_existing_identity_without_second_notification(self):
        self.cursor.rowcount = 0
        result, error = self.submit()
        self.assertIsNone(error)
        self.assertEqual(result["logID"], 41)
        self.assertTrue(result["alreadyAccepted"])
        self.connection.commit.assert_called_once()
        # Per-test cache resets add the source probe before INSERT + retry read.
        self.assertEqual(self.cursor.execute.call_count, 3)
        self.assertIn("information_schema.COLUMNS", self.cursor.execute.call_args_list[0].args[0])
        self.assertIn("ON DUPLICATE KEY UPDATE", self.cursor.execute.call_args_list[1].args[0])
        self.notify.assert_not_called()

    def test_different_data_cannot_overwrite_an_existing_key(self):
        self.cursor.rowcount = 0
        result, error = self.submit(business_name="Different Store")
        self.assertIsNone(result)
        self.assertIsInstance(error, service.YellowFlagSubmissionConflict)
        self.connection.rollback.assert_called_once()
        self.connection.commit.assert_not_called()
        self.notify.assert_not_called()

    def test_retry_preserves_address_and_changed_address_conflicts(self):
        address = "Purok Makisig, behind the unnamed chapel"
        self.existing["nearestLandmark"] = address
        self.cursor.rowcount = 0
        result, error = self.submit(business_address=address)
        self.assertIsNone(error)
        self.assertEqual(result["businessAddress"], address)
        self.assertTrue(result["alreadyAccepted"])
        self.connection.commit.reset_mock()
        result, error = self.submit(business_address="Another landmark")
        self.assertIsNone(result)
        self.assertIsInstance(error, service.YellowFlagSubmissionConflict)
        self.connection.commit.assert_not_called()
        self.connection.rollback.assert_called_once()
        self.notify.assert_not_called()

    def test_first_submission_keeps_created_response_and_notification(self):
        self.cursor.rowcount = 1
        result, error = self.submit()
        self.assertIsNone(error)
        self.assertEqual(result["lat"], 14.0)
        self.assertFalse(result["alreadyAccepted"])
        self.connection.commit.assert_called_once()
        self.notify.assert_called_once()

    def test_legacy_submission_without_uuid_retains_insert_path(self):
        result, error = self.submit(client_submission_id=None)
        self.assertIsNone(error)
        self.assertFalse(result["alreadyAccepted"])
        # One source probe, then the same single legacy INSERT.
        self.assertEqual(self.cursor.execute.call_count, 2)
        self.assertIn("information_schema.COLUMNS", self.cursor.execute.call_args_list[0].args[0])
        self.assertNotIn("clientSubmissionID", self.cursor.execute.call_args.args[0])
        self.notify.assert_called_once()

    def test_database_failure_rolls_back_and_closes_cursor(self):
        self.cursor.execute.side_effect = RuntimeError("offline database failure")
        result, error = self.submit()
        self.assertIsNone(result)
        self.assertEqual(error, "offline database failure")
        self.connection.rollback.assert_called_once()
        self.cursor.close.assert_called_once()
        self.notify.assert_not_called()
