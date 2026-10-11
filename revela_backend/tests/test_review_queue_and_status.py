import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from api.flags.service import get_flags, update_flag_color
from api.inspections import service as inspection_service
from api.registry.places_resolver import list_review_queue, decide_review


class ReviewQueueAndStatusExposureTests(unittest.TestCase):

    @patch("api.flags.service.mysql")
    def test_expired_registry_flags_are_returned_as_red(self, mock_mysql):
        mock_cursor = MagicMock()
        mock_mysql.connection.cursor.return_value = mock_cursor
        mock_cursor.fetchone.return_value = {"total": 0}
        mock_cursor.fetchall.return_value = []

        result, error = get_flags(color="Red")

        self.assertIsNone(error)
        self.assertEqual(result["data"], [])
        count_sql, count_params = mock_cursor.execute.call_args_list[0].args
        self.assertEqual(count_params, ["Red", "Expired", "Expired"])
        fetch_sql = mock_cursor.execute.call_args_list[1].args[0]
        self.assertIn("r_chk.applicationStatus = %s", count_sql)
        self.assertIn("ir.verificationStatus = 'Verified'", count_sql)
        self.assertIn("ir.inspectionResult = 'Orange'", count_sql)
        self.assertIn("ir.targetID = g.logID", count_sql)
        self.assertIn("r.applicationStatus = 'Expired' THEN 'Red'", fetch_sql)
        self.assertIn("applicationStatus = 'Expired' THEN 'Red'", fetch_sql)
        self.assertNotIn("applicationStatus = 'Expired' THEN 'Orange'", fetch_sql)

    @patch("api.flags.service.mysql")
    def test_orange_filter_selects_explicit_geospatial_flags(self, mock_mysql):
        mock_cursor = MagicMock()
        mock_mysql.connection.cursor.return_value = mock_cursor
        mock_cursor.fetchone.return_value = {"total": 0}
        mock_cursor.fetchall.return_value = []

        result, error = get_flags(color="Orange")

        self.assertIsNone(error)
        self.assertEqual(result["data"], [])
        count_sql, count_params = mock_cursor.execute.call_args_list[0].args
        self.assertEqual(count_params, [])
        self.assertIn("ir.verificationStatus = 'Verified'", count_sql)
        self.assertIn("ir.inspectionResult = 'Orange'", count_sql)
        self.assertIn("r_chk.applicationStatus = 'Expired'", count_sql)
        self.assertIn("g.flagColor = 'Orange'", count_sql)

    @patch("api.inspections.service.log_inspection_event")
    @patch("api.inspections.service._ensure_gps_columns")
    @patch("api.inspections.service.mysql")
    def test_dispatch_keeps_existing_flag_color(
        self, mock_mysql, _ensure_gps_columns, _log_event
    ):
        mock_cursor = MagicMock()
        mock_mysql.connection.cursor.return_value = mock_cursor
        mock_cursor.fetchone.side_effect = [
            {"logID": 22, "flagColor": "Red"},
            {"userID": 9, "fullName": "Inspector", "userRole": "Inspector"},
            None,
        ]
        mock_cursor.lastrowid = 31

        result, error = inspection_service.assign_inspection(
            log_id=22,
            inspector_user_id=9,
            deadline=None,
            assigned_by=2,
        )

        self.assertIsNone(error)
        self.assertEqual(result["status"], "Assigned")
        self.assertFalse(any(
            "UPDATE geospatial_logs" in call.args[0]
            for call in mock_cursor.execute.call_args_list
        ))

    @patch("api.flags.service.mysql")
    def test_confirmed_orange_is_excluded_from_expired_red_filter(self, mock_mysql):
        mock_cursor = MagicMock()
        mock_mysql.connection.cursor.return_value = mock_cursor
        mock_cursor.fetchone.return_value = {"total": 0}
        mock_cursor.fetchall.return_value = []

        result, error = get_flags(color="Red")

        self.assertIsNone(error)
        self.assertEqual(result["data"], [])
        count_sql, count_params = mock_cursor.execute.call_args_list[0].args
        self.assertEqual(count_params, ["Red", "Expired", "Expired"])
        self.assertIn("ir.verificationStatus = 'Verified'", count_sql)
        self.assertIn("ir.inspectionResult = 'Orange'", count_sql)

    @patch("api.flags.service.mysql")
    def test_registry_only_flag_cannot_turn_orange_into_expired(self, mock_mysql):
        mock_cursor = MagicMock()
        mock_mysql.connection.cursor.return_value = mock_cursor

        success, error = update_flag_color(-5, "Orange")

        self.assertFalse(success)
        self.assertIn("verified inspection warning", error)
        mock_cursor.execute.assert_not_called()

    @patch("api.inspections.service.log_inspection_event")
    @patch("api.inspections.service.get_latest_inspection_cycle_id", return_value=None)
    @patch("api.inspections.service._ensure_gps_columns")
    @patch("api.inspections.service.mysql")
    def test_submitted_orange_report_does_not_change_existing_flag(
        self, mock_mysql, _ensure_gps_columns, _cycle_id, _log_event
    ):
        mock_cursor = MagicMock()
        mock_mysql.connection.cursor.return_value = mock_cursor
        mock_cursor.fetchone.side_effect = [
            {"reportID": 7, "irTimestamp": "2026-10-11 12:00:00"},
            {"mins": 5},
            {"flagColor": "Red"},
        ]

        result, error = inspection_service.submit_inspection(
            log_id=22,
            user_id=9,
            inspection_result="Orange",
            notice_level=1,
        )

        self.assertIsNone(error)
        self.assertEqual(result["status"], "Submitted")
        self.assertEqual(result["flagColor"], "Red")
        self.assertTrue(any(
            "verificationStatus  = 'Submitted'" in call.args[0]
            for call in mock_cursor.execute.call_args_list
        ))
        self.assertFalse(any(
            "UPDATE geospatial_logs" in call.args[0]
            for call in mock_cursor.execute.call_args_list
        ))

    @patch("api.inspections.service.log_inspection_event")
    @patch("api.inspections.service.get_latest_inspection_cycle_id", return_value=None)
    @patch("api.inspections.service._ensure_gps_columns")
    @patch("api.inspections.service.mysql")
    def test_report_sent_back_for_redo_is_not_approved_orange(
        self, mock_mysql, _ensure_gps_columns, _cycle_id, _log_event
    ):
        mock_cursor = MagicMock()
        mock_mysql.connection.cursor.return_value = mock_cursor
        mock_cursor.fetchone.side_effect = [
            {"reportID": 8, "targetID": 22, "verificationStatus": "Submitted"},
            {"userID": 9, "fullName": "Inspector", "userRole": "Inspector"},
            {"flagColor": "Red"},
        ]

        result, error = inspection_service.reassign_submitted_report(
            report_id=8,
            inspector_user_id=9,
            deadline=None,
            assigned_by=2,
        )

        self.assertIsNone(error)
        self.assertEqual(result["status"], "Reassigned")
        reset_sql = next(
            call.args[0] for call in mock_cursor.execute.call_args_list
            if "UPDATE inspection_reports" in call.args[0]
        )
        self.assertIn("verificationStatus = 'Reassigned'", reset_sql)
        self.assertIn("inspectionResult = NULL", reset_sql)
        self.assertFalse(any(
            "UPDATE geospatial_logs" in call.args[0]
            for call in mock_cursor.execute.call_args_list
        ))

    @patch("api.inspections.service.log_inspection_event")
    @patch("api.inspections.service.get_latest_inspection_cycle_id", return_value=None)
    @patch("api.inspections.service._ensure_gps_columns")
    @patch("api.inspections.service.mysql")
    def test_verified_warning_inspection_sets_explicit_orange_designation(
        self, mock_mysql, _ensure_gps_columns, _cycle_id, _log_event
    ):
        mock_cursor = MagicMock()
        mock_mysql.connection.cursor.return_value = mock_cursor
        mock_cursor.fetchone.side_effect = [
            {
                "reportID": 4,
                "targetID": 22,
                "userID": 9,
                "inspectionResult": "Orange",
                "noticeLevel": 1,
                "verificationStatus": "Submitted",
                "verifiedLatitude": None,
                "verifiedLongitude": None,
                "verifiedAccuracy": None,
                "nearestLandmark": None,
                "detectedName": "Warned Shop",
                "barangayID": 1,
            },
            {"flagColor": "Red"},
        ]

        result, error = inspection_service.verify_inspection(
            4, verified_by_user_id=2
        )

        self.assertIsNone(error)
        self.assertEqual(result["newFlagColor"], "Orange")
        geospatial_update = next(
            call for call in mock_cursor.execute.call_args_list
            if "UPDATE geospatial_logs" in call.args[0]
        )
        self.assertEqual(geospatial_update.args[1], ("Orange", 1, 22))
        self.assertFalse(any(
            "UPDATE official_registry" in call.args[0]
            for call in mock_cursor.execute.call_args_list
        ))

    @patch("api.flags.service.mysql")
    def test_get_flags_includes_confidence_semantics(self, mock_mysql):
        """get_flags must include matchStatus, coordSource, matchScore, and businessID in returned rows."""
        mock_cursor = MagicMock()
        mock_mysql.connection.cursor.return_value = mock_cursor

        mock_cursor.fetchone.return_value = {"total": 2}
        mock_cursor.fetchall.return_value = [
            {
                "logID": 101,
                "businessID": "BIZ-FLAG-01",
                "detectedName": "Silva Pharmacy",
                "latitude": 13.965,
                "longitude": 121.115,
                "flagColor": "Green",
                "detectedDate": "2026-10-08 12:00:00",
                "matchStatus": "auto",
                "coordSource": "places",
                "matchScore": 0.95
            },
            {
                "logID": -202,
                "businessID": "BIZ-FLAG-02",
                "detectedName": "Jose Bakery",
                "latitude": 13.960,
                "longitude": 121.110,
                "flagColor": "Yellow",
                "detectedDate": "2026-10-08 12:00:00",
                "matchStatus": "review",
                "coordSource": "geocode",
                "matchScore": 0.60
            }
        ]

        res, err = get_flags()
        self.assertIsNone(err)
        self.assertEqual(len(res["data"]), 2)

        row1 = res["data"][0]
        self.assertEqual(row1["businessID"], "BIZ-FLAG-01")
        self.assertEqual(row1["matchStatus"], "auto")
        self.assertEqual(row1["coordSource"], "places")
        self.assertEqual(row1["matchScore"], 0.95)

        row2 = res["data"][1]
        self.assertEqual(row2["businessID"], "BIZ-FLAG-02")
        self.assertEqual(row2["matchStatus"], "review")
        self.assertEqual(row2["coordSource"], "geocode")
        self.assertEqual(row2["matchScore"], 0.60)

    @patch("api.registry.places_resolver.mysql")
    def test_list_review_queue_returns_candidates(self, mock_mysql):
        """list_review_queue must return records with matchStatus='review' including barangayName and mapsUrl."""
        mock_cursor = MagicMock()
        mock_mysql.connection.cursor.return_value = mock_cursor

        mock_cursor.fetchone.return_value = {"c": 1}
        mock_cursor.fetchall.return_value = [
            {
                "businessID": "BIZ-REV-01",
                "barangayID": 1,
                "barangayName": "Barangay I",
                "businessName": "Candidate Store",
                "businessAddress": "Main St",
                "latitude": 13.962,
                "longitude": 121.112,
                "placeID": "place_google_rev",
                "coordSource": "places",
                "matchScore": 0.65,
                "matchStatus": "review"
            }
        ]

        res, err = list_review_queue()
        self.assertIsNone(err)
        self.assertEqual(res["total"], 1)
        self.assertEqual(len(res["data"]), 1)

        item = res["data"][0]
        self.assertEqual(item["businessID"], "BIZ-REV-01")
        self.assertEqual(item["barangayName"], "Barangay I")
        self.assertEqual(item["matchStatus"], "review")
        self.assertEqual(item["matchScore"], 0.65)
        self.assertIn("place_google_rev", item["mapsUrl"])

    @patch("api.registry.places_resolver.mysql")
    def test_review_accept_locks_pin(self, mock_mysql):
        """Accepting a review candidate must set matchStatus='approved' and coordSource='manual'."""
        mock_cursor = MagicMock()
        mock_mysql.connection.cursor.return_value = mock_cursor

        mock_cursor.fetchone.return_value = {
            "barangayID": 1,
            "businessName": "Candidate Store",
            "latitude": 13.962,
            "longitude": 121.112,
            "placeID": "place_google_rev"
        }

        ok, err = decide_review("BIZ-REV-01", approve=True)
        self.assertTrue(ok)
        self.assertIsNone(err)

        update_calls = [
            c for c in mock_cursor.execute.call_args_list
            if "UPDATE official_registry SET matchStatus='approved'" in c[0][0]
        ]
        self.assertEqual(len(update_calls), 1)
        sql = update_calls[0][0][0]
        self.assertIn("coordSource='manual'", sql)
        self.assertEqual(update_calls[0][0][1], ("BIZ-REV-01",))

    @patch("api.registry.places_resolver.mysql")
    def test_review_reject_records_rejected_place_and_detaches_coords(self, mock_mysql):
        """Rejecting a candidate must insert into registry_rejected_places, set rejected status, and clear coords."""
        mock_cursor = MagicMock()
        mock_mysql.connection.cursor.return_value = mock_cursor

        mock_cursor.fetchone.return_value = {
            "barangayID": 1,
            "businessName": "Candidate Store",
            "latitude": 13.962,
            "longitude": 121.112,
            "placeID": "bad_place_candidate"
        }

        ok, err = decide_review("BIZ-REV-01", approve=False)
        self.assertTrue(ok)
        self.assertIsNone(err)

        # Verify insert into registry_rejected_places
        rej_calls = [
            c for c in mock_cursor.execute.call_args_list
            if "INSERT IGNORE INTO registry_rejected_places" in c[0][0]
        ]
        self.assertEqual(len(rej_calls), 1)
        self.assertEqual(rej_calls[0][0][1], ("BIZ-REV-01", "bad_place_candidate"))

        # Verify detachment of coordinates on official_registry
        detach_calls = [
            c for c in mock_cursor.execute.call_args_list
            if "UPDATE official_registry SET matchStatus='rejected'" in c[0][0]
        ]
        self.assertEqual(len(detach_calls), 1)
        detach_sql = detach_calls[0][0][0]
        self.assertIn("latitude=NULL", detach_sql)
        self.assertIn("longitude=NULL", detach_sql)
        self.assertIn("placeID=NULL", detach_sql)

    @patch("api.registry.places_resolver._update_pin")
    @patch("api.registry.places_resolver.mysql")
    def test_approving_reverify_proposal_moves_pin_only_after_admin_approval(
        self, mock_mysql, update_pin
    ):
        cursor = MagicMock()
        cursor.fetchone.side_effect = [
            {
                "barangayID": 1,
                "businessName": "Candidate Store",
                "latitude": 13.962,
                "longitude": 121.112,
                "placeID": "existing_place",
            },
            {
                "reviewHistoryID": 42,
                "newLat": 13.965,
                "newLng": 121.115,
                "placeID": "proposed_place",
                "score": 0.68,
            },
        ]
        cursor.rowcount = 1
        mock_mysql.connection.cursor.return_value = cursor

        ok, error = decide_review("BIZ-REV-02", approve=True)

        self.assertTrue(ok)
        self.assertIsNone(error)
        proposal_update = next(
            call for call in cursor.execute.call_args_list
            if "SET latitude=%s, longitude=%s, placeID=%s" in call.args[0]
        )
        self.assertEqual(
            proposal_update.args[1],
            (13.965, 121.115, "proposed_place", 0.68, "BIZ-REV-02"),
        )
        update_pin.assert_called_once_with(
            cursor, 1, "Candidate Store", 13.962, 121.112, 13.965, 121.115,
            business_id="BIZ-REV-02",
        )
        self.assertTrue(any(
            "review_approved" in call.args[0]
            for call in cursor.execute.call_args_list
        ))

    @patch("api.registry.places_resolver._update_pin")
    @patch("api.registry.places_resolver.mysql")
    def test_rejecting_reverify_proposal_keeps_original_pin(self, mock_mysql, update_pin):
        cursor = MagicMock()
        cursor.fetchone.side_effect = [
            {
                "barangayID": 1,
                "businessName": "Candidate Store",
                "latitude": 13.962,
                "longitude": 121.112,
                "placeID": "existing_place",
            },
            {
                "reviewHistoryID": 43,
                "newLat": 13.965,
                "newLng": 121.115,
                "placeID": "proposed_place",
                "score": 0.68,
            },
        ]
        mock_mysql.connection.cursor.return_value = cursor

        ok, error = decide_review("BIZ-REV-03", approve=False)

        self.assertTrue(ok)
        self.assertIsNone(error)
        update_pin.assert_not_called()
        self.assertNotIn(
            "latitude=NULL",
            "\n".join(call.args[0] for call in cursor.execute.call_args_list),
        )
        rejected = next(
            call for call in cursor.execute.call_args_list
            if "INSERT IGNORE INTO registry_rejected_places" in call.args[0]
        )
        self.assertEqual(rejected.args[1], ("BIZ-REV-03", "proposed_place"))


if __name__ == "__main__":
    unittest.main()
