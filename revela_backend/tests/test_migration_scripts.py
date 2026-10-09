import unittest
from unittest.mock import MagicMock

from scripts.migrate_ticket05 import _ensure_index


class Ticket05MigrationTests(unittest.TestCase):

    def test_missing_place_id_index_is_added(self):
        cursor = MagicMock()
        cursor.fetchall.return_value = []

        _ensure_index(cursor, "geospatial_logs", "idx_geo_place", "placeID")

        self.assertEqual(cursor.execute.call_count, 2)
        self.assertIn(
            "ALTER TABLE `geospatial_logs` ADD KEY `idx_geo_place` (`placeID`)",
            cursor.execute.call_args.args[0],
        )

    def test_existing_index_is_not_added_again(self):
        cursor = MagicMock()
        cursor.fetchall.return_value = [(None, None, "idx_geo_place")]

        _ensure_index(cursor, "geospatial_logs", "idx_geo_place", "placeID")

        cursor.execute.assert_called_once_with(
            "SHOW INDEX FROM `geospatial_logs`"
        )


if __name__ == "__main__":
    unittest.main()
