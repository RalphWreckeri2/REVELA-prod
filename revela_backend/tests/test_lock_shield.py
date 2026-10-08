import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from api.flags.service import _match_registry_to_google, update_flag_location


class LockShieldTests(unittest.TestCase):

    @patch("api.flags.service.mysql")
    def test_match_registry_skips_coords_when_coord_source_manual(self, mock_mysql):
        """Automated sweep must NOT overwrite coordinates on rows with coordSource = 'manual'."""
        mock_cursor = MagicMock()
        mock_mysql.connection.cursor.return_value = mock_cursor

        # official_registry lookup returns a manually locked row
        mock_cursor.fetchone.return_value = {
            "coordSource": "manual",
            "matchStatus": "auto",
            "latitude": 13.96500000,
            "longitude": 121.11500000
        }
        # geospatial_logs lookup returns existing log
        mock_cursor.fetchall.return_value = [
            {
                "logID": 101,
                "placeID": "place_google_123",
                "flagColor": "Green",
                "latitude": 13.96500000,
                "longitude": 121.11500000
            }
        ]

        _match_registry_to_google(
            place_id="place_google_123",
            business_id="BIZ-001",
            detected_name="Silva's Pharmacy",
            target_color="Green",
            lat=14.00000000,  # New discovered Google coordinates
            lng=122.00000000,
            barangay_id=1,
            match_score=0.95
        )

        # Inspect all SQL executions
        executed_sqls = [call[0][0] for call in mock_cursor.execute.call_args_list]

        # 1. official_registry UPDATE should NOT have run
        update_reg_calls = [sql for sql in executed_sqls if "UPDATE official_registry" in sql]
        self.assertEqual(len(update_reg_calls), 0, "Locked row official_registry was updated!")

        # 2. geospatial_logs UPDATE should preserve locked coordinates (13.965, 121.115), NOT new (14.0, 122.0)
        update_geo_calls = [call for call in mock_cursor.execute.call_args_list if "UPDATE geospatial_logs" in call[0][0]]
        self.assertEqual(len(update_geo_calls), 1)
        args = update_geo_calls[0][0][1]
        self.assertEqual(args[4], 13.96500000, "Latitude should be preserved from locked row")
        self.assertEqual(args[5], 121.11500000, "Longitude should be preserved from locked row")

    @patch("api.flags.service.mysql")
    def test_match_registry_skips_coords_when_match_status_approved(self, mock_mysql):
        """Automated sweep must NOT overwrite coordinates on rows with matchStatus = 'approved'."""
        mock_cursor = MagicMock()
        mock_mysql.connection.cursor.return_value = mock_cursor

        mock_cursor.fetchone.return_value = {
            "coordSource": "places",
            "matchStatus": "approved",
            "latitude": 13.96550000,
            "longitude": 121.11550000
        }
        mock_cursor.fetchall.return_value = [
            {
                "logID": 102,
                "placeID": "place_google_456",
                "flagColor": "Green",
                "latitude": 13.96550000,
                "longitude": 121.11550000
            }
        ]

        _match_registry_to_google(
            place_id="place_google_456",
            business_id="BIZ-002",
            detected_name="Silva Drugstore",
            target_color="Green",
            lat=14.11111111,
            lng=122.22222222,
            barangay_id=1,
            match_score=0.91
        )

        executed_sqls = [call[0][0] for call in mock_cursor.execute.call_args_list]
        update_reg_calls = [sql for sql in executed_sqls if "UPDATE official_registry" in sql]
        self.assertEqual(len(update_reg_calls), 0, "Approved row official_registry was overwritten!")

    @patch("api.flags.service.mysql")
    def test_match_registry_updates_coords_and_stamps_provenance_when_unlocked(self, mock_mysql):
        """Unlocked rows should receive discovered coordinates with coordSource='places', matchStatus='auto'."""
        mock_cursor = MagicMock()
        mock_mysql.connection.cursor.return_value = mock_cursor

        mock_cursor.fetchone.return_value = {
            "coordSource": None,
            "matchStatus": "auto",
            "latitude": None,
            "longitude": None
        }
        mock_cursor.fetchall.return_value = [
            {
                "logID": 103,
                "placeID": None,
                "flagColor": "Green",
                "latitude": None,
                "longitude": None
            }
        ]

        _match_registry_to_google(
            place_id="place_google_789",
            business_id="BIZ-003",
            detected_name="Silva Drugstore",
            target_color="Green",
            lat=13.96800000,
            lng=121.11800000,
            barangay_id=2,
            match_score=0.88
        )

        # official_registry UPDATE should have been called
        update_reg_calls = [call for call in mock_cursor.execute.call_args_list if "UPDATE official_registry" in call[0][0]]
        self.assertEqual(len(update_reg_calls), 1)
        params = update_reg_calls[0][0][1]
        # (lat, lng, place_id, match_score, business_id)
        self.assertEqual(params[0], 13.96800000)
        self.assertEqual(params[1], 121.11800000)
        self.assertEqual(params[2], "place_google_789")
        self.assertEqual(params[3], 0.880)
        self.assertEqual(params[4], "BIZ-003")

        # geospatial_logs should receive new coordinates
        update_geo_calls = [call for call in mock_cursor.execute.call_args_list if "UPDATE geospatial_logs" in call[0][0]]
        self.assertEqual(len(update_geo_calls), 1)
        geo_params = update_geo_calls[0][0][1]
        self.assertEqual(geo_params[4], 13.96800000)
        self.assertEqual(geo_params[5], 121.11800000)

    @patch("api.flags.service._get_barangay_id_by_coords", return_value=1)
    @patch("api.flags.service.mysql")
    def test_update_flag_location_sets_manual_and_approved_and_clears_place_id(self, mock_mysql, mock_get_brgy):
        """Dragging a pin must stamp coordSource='manual', matchStatus='approved', clear placeID, and key by businessID."""
        mock_cursor = MagicMock()
        mock_mysql.connection.cursor.return_value = mock_cursor

        # 1. geospatial_logs fetch returns the flag being moved
        mock_cursor.fetchone.side_effect = [
            # First fetchone: get flag details from geospatial_logs
            {"detectedName": "Silva Pharmacy", "barangayID": 1, "placeID": "google_poi_123", "latitude": 13.9, "longitude": 121.1},
            # Second fetchone: find businessID in official_registry via placeID
            {"businessID": "BIZ-101"}
        ]

        success, err = update_flag_location(log_id=505, lat=13.96900000, lng=121.11900000)
        self.assertTrue(success)
        self.assertIsNone(err)

        # Verify geospatial_logs update clears placeID
        update_geo_calls = [call for call in mock_cursor.execute.call_args_list if "UPDATE geospatial_logs" in call[0][0]]
        self.assertEqual(len(update_geo_calls), 1)
        self.assertIn("placeID = NULL", update_geo_calls[0][0][0])

        # Verify official_registry update keys strictly by businessID = 'BIZ-101'
        update_reg_calls = [call for call in mock_cursor.execute.call_args_list if "UPDATE official_registry" in call[0][0]]
        self.assertEqual(len(update_reg_calls), 1)
        sql, params = update_reg_calls[0][0][0], update_reg_calls[0][0][1]
        self.assertIn("coordSource = 'manual'", sql)
        self.assertIn("matchStatus = 'approved'", sql)
        self.assertIn("placeID = NULL", sql)
        self.assertIn("WHERE businessID = %s", sql)
        self.assertEqual(params[-1], "BIZ-101")

    @patch("api.flags.service._get_barangay_id_by_coords", return_value=1)
    @patch("api.flags.service.mysql")
    def test_update_flag_location_virtual_flag(self, mock_mysql, mock_get_brgy):
        """Dragging a virtual flag (log_id < 0) updates official_registry with manual/approved."""
        mock_cursor = MagicMock()
        mock_mysql.connection.cursor.return_value = mock_cursor

        success, err = update_flag_location(log_id=-99, lat=13.97000000, lng=121.12000000)
        self.assertTrue(success)
        self.assertIsNone(err)

        update_reg_calls = [call for call in mock_cursor.execute.call_args_list if "UPDATE official_registry" in call[0][0]]
        self.assertEqual(len(update_reg_calls), 1)
        sql, params = update_reg_calls[0][0][0], update_reg_calls[0][0][1]
        self.assertIn("coordSource = 'manual'", sql)
        self.assertIn("matchStatus = 'approved'", sql)
        self.assertIn("WHERE businessID = %s", sql)
        self.assertEqual(params[-1], 99)

    @patch("api.registry.service._sync_flag_color")
    @patch("api.registry.service._load_barangay_lookup", return_value={"barangay i": 1})
    @patch("api.registry.service.mysql")
    def test_sync_registry_preserves_locked_records(self, mock_mysql, mock_lookup, mock_sync_flag):
        """sync_registry must ignore new CSV coordinates when record is locked ('manual' or 'approved')."""
        import io
        from api.registry.service import sync_registry

        mock_cursor = MagicMock()
        mock_mysql.connection.cursor.return_value = mock_cursor

        # Existing record is manually locked
        mock_cursor.fetchone.side_effect = [
            {
                "businessID": "BIZ-LOCK",
                "latitude": 13.96000000,
                "longitude": 121.11000000,
                "coordSource": "manual",
                "matchStatus": "approved"
            },
            None  # For _sync_flag_color geospatial_logs lookup
        ]

        csv_content = (
            "Business ID,Business Name,Barangay,Latitude,Longitude\n"
            "BIZ-LOCK,Silva Pharmacy,Barangay I,14.50000000,122.50000000\n"
        )
        file_obj = io.BytesIO(csv_content.encode("utf-8"))

        summary, err = sync_registry(file_obj, ".csv")
        self.assertIsNone(err)
        self.assertEqual(summary["updated"], 1)

        # Inspect UPDATE official_registry
        update_reg_calls = [call for call in mock_cursor.execute.call_args_list if "UPDATE official_registry" in call[0][0]]
        self.assertEqual(len(update_reg_calls), 1)
        params = update_reg_calls[0][0][1]
        final_lat = params[5]
        final_lng = params[6]
        self.assertEqual(final_lat, 13.96000000, "Locked coordinates should NOT be overwritten by CSV")
        self.assertEqual(final_lng, 121.11000000, "Locked coordinates should NOT be overwritten by CSV")

    @patch("api.registry.service._resolve_location")
    @patch("api.registry.service._load_barangay_lookup", return_value={"barangay i": 1})
    @patch("api.registry.service.mysql")
    def test_sync_registry_skips_resolver_for_rejected_records(self, mock_mysql, mock_lookup, mock_resolve):
        """sync_registry must NOT call _resolve_location for records where matchStatus='rejected'."""
        import io
        from api.registry.service import sync_registry

        mock_cursor = MagicMock()
        mock_mysql.connection.cursor.return_value = mock_cursor

        # Existing record is rejected
        mock_cursor.fetchone.side_effect = [
            {
                "businessID": "BIZ-REJ",
                "latitude": None,
                "longitude": None,
                "coordSource": None,
                "matchStatus": "rejected"
            },
            None  # For _sync_flag_color geospatial_logs lookup
        ]

        csv_content = (
            "Business ID,Business Name,Barangay,Business Address\n"
            "BIZ-REJ,Silva Pharmacy,Barangay I,123 Main Street\n"
        )
        file_obj = io.BytesIO(csv_content.encode("utf-8"))

        summary, err = sync_registry(file_obj, ".csv")
        self.assertIsNone(err)
        mock_resolve.assert_not_called()


if __name__ == "__main__":
    unittest.main()

