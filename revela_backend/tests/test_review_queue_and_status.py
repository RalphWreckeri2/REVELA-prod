import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from api.flags.service import get_flags
from api.registry.places_resolver import list_review_queue, decide_review


class ReviewQueueAndStatusExposureTests(unittest.TestCase):

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


if __name__ == "__main__":
    unittest.main()
