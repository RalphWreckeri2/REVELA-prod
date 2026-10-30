import unittest
from unittest.mock import MagicMock, patch

from api.registry.places_resolver import _update_pin


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


if __name__ == "__main__":
    unittest.main()
