import unittest
from unittest.mock import MagicMock, patch

from api.registry.places_resolver import _update_pin, decide_review


class ReviewPinSyncTests(unittest.TestCase):
    @patch(
        "api.registry.inspection_link.confirmed_pin_column_available",
        return_value=True,
    )
    def test_explicit_review_move_updates_confirmed_pin(self, _column_available):
        cursor = MagicMock()
        cursor.fetchone.return_value = {"confirmedLogID": 42}

        _update_pin(
            cursor, 1, "Shop", 13.96, 121.11, 13.97, 121.12,
            business_id="BIZ-1", force_linked=True,
            place_id=None, new_place_id="new-place",
        )

        update = cursor.execute.call_args_list[-1]
        self.assertIn("WHERE logID=%s AND businessID=%s", update.args[0])
        self.assertEqual(
            update.args[1],
            (13.97, 121.12, "new-place", 42, "BIZ-1"),
        )

    @patch(
        "api.registry.inspection_link.confirmed_pin_column_available",
        return_value=True,
    )
    def test_automatic_sync_keeps_confirmed_pin_unchanged(self, _column_available):
        cursor = MagicMock()
        cursor.fetchone.return_value = {"confirmedLogID": 42}

        _update_pin(
            cursor, 1, "Shop", 13.96, 121.11, 13.97, 121.12,
            business_id="BIZ-1",
        )

        self.assertEqual(cursor.execute.call_count, 1)
        self.assertIn(
            "SELECT confirmedLogID",
            cursor.execute.call_args.args[0],
        )

    @patch("api.registry.reverify._ensure_history_table")
    @patch("api.registry.places_resolver._is_within_municipal_bounds", return_value=True)
    @patch("api.registry.places_resolver._update_pin")
    @patch("api.registry.places_resolver.mysql")
    def test_approval_syncs_pin_even_when_registry_coordinates_match_proposal(
        self, mock_mysql, update_pin, _in_boundary, _ensure_history_table
    ):
        cursor = MagicMock()
        cursor.fetchone.side_effect = [
            {
                "businessID": "BIZ-SAME-PIN",
                "barangayID": 1,
                "businessName": "Shop",
                "businessAddress": "Current address",
                "latitude": 13.963445,
                "longitude": 121.115545,
                "placeID": "old-place",
                "placeIDKind": "poi",
                "matchScore": 0.6,
                "coordSource": "places",
                "matchStatus": "review",
                "resolveKey": None,
            },
            None,
            {"reverifyHistoryID": 42},
            {
                "reviewHistoryID": 43,
                "newLat": 13.963445,
                "newLng": 121.115545,
                "placeID": "new-place",
                "score": 0.7,
            },
        ]
        cursor.rowcount = 1
        mock_mysql.connection.cursor.return_value = cursor

        ok, error = decide_review("BIZ-SAME-PIN", approve=True)

        self.assertTrue(ok, error)
        self.assertIsNone(error)
        update_pin.assert_called_once_with(
            cursor, 1, "Shop", 13.963445, 121.115545,
            13.963445, 121.115545,
            business_id="BIZ-SAME-PIN",
            force_linked=True,
            place_id="old-place",
            new_place_id="new-place",
        )


if __name__ == "__main__":
    unittest.main()
