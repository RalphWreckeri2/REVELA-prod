import os
import sys
import unittest
from unittest.mock import MagicMock, patch

# Ensure backend package resolves from test execution
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from api.registry.service import delete_business
from api.flags.service import delete_flag


class DeleteIsolationTests(unittest.TestCase):

    @patch("api.registry.service.mysql")
    def test_delete_business_leaves_same_named_branch_intact(self, mock_mysql):
        """In a barangay with two branches named '7-Eleven', deleting branch A leaves branch B's pins and inspection history intact."""
        mock_cursor = MagicMock()
        mock_mysql.connection.cursor.return_value = mock_cursor

        # 1. Fetch official_registry for BIZ-7E-A
        mock_cursor.fetchone.return_value = {
            "businessID": "BIZ-7E-A",
            "businessName": "7-Eleven",
            "barangayID": 1,
            "latitude": 13.96100000,
            "longitude": 121.11100000,
            "placeID": "place_7e_a"
        }

        # 2. Query geospatial_logs by businessID returns strictly Branch A's log (100)
        mock_cursor.fetchall.side_effect = [
            # businessID query returns Branch A
            [{"logID": 100}]
        ]

        success, err = delete_business("BIZ-7E-A")
        self.assertTrue(success)
        self.assertIsNone(err)

        # Inspect all DELETE queries
        executed_calls = [call[0] for call in mock_cursor.execute.call_args_list]

        # Inspect geospatial_logs deletions: strictly log 100 (Branch A), never log 200 (Branch B)
        deleted_log_ids = [
            call[1][0] for call in executed_calls if "DELETE FROM geospatial_logs" in call[0]
        ]
        self.assertIn(100, deleted_log_ids, "Branch A log (100) should have been deleted")
        self.assertNotIn(200, deleted_log_ids, "Branch B log (200) MUST NOT be deleted!")

        # Inspect inspection_reports deletions
        deleted_report_targets = [
            call[1][0] for call in executed_calls if "DELETE FROM inspection_reports" in call[0]
        ]
        self.assertIn(100, deleted_report_targets, "Branch A inspections should be deleted")
        self.assertNotIn(200, deleted_report_targets, "Branch B inspections MUST NOT be deleted!")

        # Inspect official_registry deletions
        deleted_biz_ids = [
            call[1][0] for call in executed_calls if "DELETE FROM official_registry" in call[0]
        ]
        self.assertEqual(deleted_biz_ids, ["BIZ-7E-A"])

    @patch("api.registry.service.mysql")
    def test_delete_business_never_deletes_unlinked_same_name_logs(self, mock_mysql):
        """Deleting a business with no matching businessID or placeID in geospatial_logs must NEVER delete same-named logs."""
        mock_cursor = MagicMock()
        mock_mysql.connection.cursor.return_value = mock_cursor

        # Registry row exists
        mock_cursor.fetchone.return_value = {
            "businessID": "BIZ-7E-A",
            "businessName": "7-Eleven",
            "barangayID": 1,
            "latitude": 13.96100000,
            "longitude": 121.11100000,
            "placeID": None
        }

        # businessID query returns empty (no linked log)
        mock_cursor.fetchall.return_value = []

        success, err = delete_business("BIZ-7E-A")
        self.assertTrue(success)
        self.assertIsNone(err)

        executed_calls = [call[0] for call in mock_cursor.execute.call_args_list]

        # Geospatial logs must NOT have any deletions because identity could not be verified
        geo_deletes = [call for call in executed_calls if "DELETE FROM geospatial_logs" in call[0]]
        self.assertEqual(len(geo_deletes), 0, "No geospatial logs should be deleted without explicit identity match!")

        # Registry row itself IS deleted
        reg_deletes = [call for call in executed_calls if "DELETE FROM official_registry" in call[0]]
        self.assertEqual(len(reg_deletes), 1)
        self.assertEqual(reg_deletes[0][1][0], "BIZ-7E-A")

    @patch("api.flags.service.mysql")
    def test_delete_flag_isolates_to_single_log_id(self, mock_mysql):
        """Deleting a map pin must only delete that specific logID and NOT delete the official business."""
        mock_cursor = MagicMock()
        mock_mysql.connection.cursor.return_value = mock_cursor

        # Fetch flag details
        mock_cursor.fetchone.side_effect = [
            # Flag being deleted
            {
                "logID": 100,
                "businessID": "BIZ-7E-A",
                "reportID": None,
                "detectedName": "7-Eleven",
                "barangayID": 1,
                "placeID": "place_7e_a",
                "latitude": 13.961,
                "longitude": 121.111
            },
            # Surviving duplicate check by businessID: None
            None,
            # Surviving duplicate check by placeID: None
            None
        ]
        # Inspection reports check: None
        mock_cursor.fetchall.return_value = []

        success, err = delete_flag(100)
        self.assertTrue(success)
        self.assertIsNone(err)

        executed_calls = [call[0] for call in mock_cursor.execute.call_args_list]

        # 1. geospatial_logs delete must strictly be for 100
        geo_deletes = [call for call in executed_calls if "DELETE FROM geospatial_logs" in call[0]]
        self.assertEqual(len(geo_deletes), 1)
        self.assertEqual(geo_deletes[0][1][0], 100)

        # 2. official_registry MUST NOT be deleted!
        reg_deletes = [call for call in executed_calls if "DELETE FROM official_registry" in call[0]]
        self.assertEqual(len(reg_deletes), 0, "Deleting a map pin must NOT delete the registered business!")

    @patch("api.flags.service.mysql")
    def test_delete_flag_repoints_inspections_to_surviving_log_by_explicit_identity(self, mock_mysql):
        """When deleting a duplicate flag, inspection reports must repoint to surviving log with matching businessID/placeID."""
        mock_cursor = MagicMock()
        mock_mysql.connection.cursor.return_value = mock_cursor

        mock_cursor.fetchone.side_effect = [
            # Flag being deleted: duplicate pin 101
            {
                "logID": 101,
                "businessID": "BIZ-SILVA",
                "reportID": 5,
                "detectedName": "Silva Pharmacy",
                "barangayID": 1,
                "placeID": "place_silva",
                "latitude": 13.965,
                "longitude": 121.115
            },
            # Surviving duplicate log found by businessID: 102
            {
                "logID": 102,
                "reportID": None
            }
        ]
        # Flag 101 has inspection report
        mock_cursor.fetchall.return_value = [{"reportID": 5}]

        success, err = delete_flag(101)
        self.assertTrue(success)
        self.assertIsNone(err)

        executed_calls = [call[0] for call in mock_cursor.execute.call_args_list]

        # Verify inspection_reports was REPOINTED, not deleted
        repoint_calls = [call for call in executed_calls if "UPDATE inspection_reports SET targetID" in call[0]]
        self.assertEqual(len(repoint_calls), 1)
        # targetID updated from 101 -> 102: params are (surviving_log_id, old_log_id)
        self.assertEqual(repoint_calls[0][1], (102, 101))

        # Verify inspection_reports was NOT deleted
        report_deletes = [call for call in executed_calls if "DELETE FROM inspection_reports" in call[0]]
        self.assertEqual(len(report_deletes), 0, "Inspections must be preserved on the surviving log!")

        # Verify only log 101 was deleted
        geo_deletes = [call for call in executed_calls if "DELETE FROM geospatial_logs" in call[0]]
        self.assertEqual(len(geo_deletes), 1)
        self.assertEqual(geo_deletes[0][1][0], 101)

    @patch("api.flags.service.mysql")
    def test_delete_flag_never_repoints_to_unlinked_same_name_store(self, mock_mysql):
        """When deleting a flag without matching businessID or placeID, inspections must NEVER be repointed by name alone."""
        mock_cursor = MagicMock()
        mock_mysql.connection.cursor.return_value = mock_cursor

        mock_cursor.fetchone.side_effect = [
            # Flag 101 has no businessID and no placeID
            {
                "logID": 101,
                "businessID": None,
                "reportID": 5,
                "detectedName": "Silva's Apartment",
                "barangayID": 1,
                "placeID": None,
                "latitude": 13.965,
                "longitude": 121.115
            }
        ]
        # Flag 101 has inspection report
        mock_cursor.fetchall.return_value = [{"reportID": 5}]

        success, err = delete_flag(101)
        self.assertTrue(success)
        self.assertIsNone(err)

        executed_calls = [call[0] for call in mock_cursor.execute.call_args_list]

        # No repointing should have occurred!
        repoint_calls = [call for call in executed_calls if "UPDATE inspection_reports SET targetID" in call[0]]
        self.assertEqual(len(repoint_calls), 0, "Must NEVER repoint inspections to an unlinked store by name!")

        # The inspection for flag 101 is dropped with the deleted flag
        report_deletes = [call for call in executed_calls if "DELETE FROM inspection_reports" in call[0]]
        self.assertEqual(len(report_deletes), 1)
        self.assertEqual(report_deletes[0][1], (101,))

    @patch("api.flags.service.mysql")
    def test_delete_flag_virtual_flag_removes_from_registry(self, mock_mysql):
        """Deleting a virtual flag (log_id < 0) deletes from official_registry."""
        mock_cursor = MagicMock()
        mock_mysql.connection.cursor.return_value = mock_cursor

        success, err = delete_flag(-88)
        self.assertTrue(success)
        self.assertIsNone(err)

        executed_calls = [call[0] for call in mock_cursor.execute.call_args_list]
        reg_deletes = [call for call in executed_calls if "DELETE FROM official_registry" in call[0]]
        self.assertEqual(len(reg_deletes), 1)
        self.assertEqual(reg_deletes[0][1][0], 88)


if __name__ == "__main__":
    unittest.main()
