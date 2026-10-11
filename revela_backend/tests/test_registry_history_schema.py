import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock

from api.registry import reverify
from api.registry.history_schema import ALL_HISTORY_COLUMNS, BASELINE_HISTORY_COLUMNS


class RegistryHistorySchemaTests(unittest.TestCase):
    def setUp(self):
        reverify._HISTORY_SCHEMA_CACHE.clear()
        self.cursor = MagicMock()
        self.cursor.connection = SimpleNamespace(db="test_registry_history")

    def tearDown(self):
        reverify._HISTORY_SCHEMA_CACHE.clear()

    @staticmethod
    def _metadata_rows(definitions):
        return [
            {
                "COLUMN_NAME": name,
                "COLUMN_TYPE": column_type,
                "IS_NULLABLE": nullable,
                "COLUMN_DEFAULT": default,
                "EXTRA": extra,
            }
            for name, column_type, nullable, default, extra in definitions
        ]

    def test_required_schema_is_detected_and_metadata_is_cached(self):
        self.cursor.fetchall.return_value = self._metadata_rows(
            ALL_HISTORY_COLUMNS)

        reverify._ensure_history_table(self.cursor)
        reverify._ensure_history_table(self.cursor)

        self.cursor.execute.assert_called_once()
        sql = self.cursor.execute.call_args.args[0]
        self.assertIn("information_schema.COLUMNS", sql)
        self.assertNotIn("CREATE", sql.upper())
        self.assertNotIn("ALTER", sql.upper())

    def test_missing_required_columns_fail_clearly_without_ddl(self):
        self.cursor.fetchall.return_value = self._metadata_rows(
            BASELINE_HISTORY_COLUMNS)

        with self.assertRaisesRegex(RuntimeError, "Database migration is required") as error:
            reverify._ensure_history_table(self.cursor)

        self.assertIn("reviewType", str(error.exception))
        self.assertIn(
            "revela_backend/scripts/migrate_registry_pin_history.py",
            str(error.exception),
        )
        self.assertEqual(self.cursor.execute.call_count, 1)
        sql = self.cursor.execute.call_args.args[0]
        self.assertNotIn("CREATE", sql.upper())
        self.assertNotIn("ALTER", sql.upper())

    def test_wrong_type_and_nullability_fail_closed(self):
        for target_type, nullable in (("varchar(8)", "YES"), ("varchar(24)", "NO")):
            with self.subTest(target_type=target_type, nullable=nullable):
                definitions = [
                    (name, target_type if name == "reviewType" else column_type,
                     nullable if name == "reviewType" else is_nullable,
                     default, extra)
                    for name, column_type, is_nullable, default, extra
                    in ALL_HISTORY_COLUMNS
                ]
                self.cursor.connection.db = f"invalid_{target_type}_{nullable}"
                self.cursor.fetchall.return_value = self._metadata_rows(
                    definitions)

                with self.assertRaisesRegex(RuntimeError, "incompatible schema"):
                    reverify._ensure_history_table(self.cursor)

    def test_invalid_schema_blocks_location_approval_before_mutation(self):
        from api.registry.places_resolver import decide_review
        from unittest.mock import patch

        cursor = MagicMock()
        cursor.connection = SimpleNamespace(db="invalid_approval_schema")
        definitions = [
            (name, "varchar(8)" if name == "reviewType" else column_type,
             nullable, default, extra)
            for name, column_type, nullable, default, extra in ALL_HISTORY_COLUMNS
        ]
        cursor.fetchall.return_value = self._metadata_rows(definitions)

        with patch("api.registry.places_resolver.mysql") as mysql_mock:
            mysql_mock.connection.cursor.return_value = cursor
            ok, error = decide_review("BIZ-INVALID", approve=True)

        self.assertFalse(ok)
        self.assertIn("incompatible schema", error)
        mysql_mock.connection.rollback.assert_called_once()
        mysql_mock.connection.commit.assert_not_called()
        self.assertFalse(any(
            "UPDATE official_registry" in call.args[0]
            for call in cursor.execute.call_args_list
        ))

    def test_invalid_schema_rolls_back_manual_pin_correction(self):
        from api.flags.service import update_flag_location
        from unittest.mock import patch

        cursor = MagicMock()
        cursor.connection = SimpleNamespace(db="invalid_manual_schema")
        definitions = [
            (name, column_type, "NO" if name == "actorUserID" else nullable,
             default, extra)
            for name, column_type, nullable, default, extra in ALL_HISTORY_COLUMNS
        ]
        cursor.fetchall.return_value = self._metadata_rows(definitions)
        cursor.fetchone.return_value = {
            "businessID": 72,
            "businessName": "Example Shop",
            "businessAddress": "1 Main Street",
            "barangayID": 1,
            "latitude": 13.9,
            "longitude": 121.1,
            "coordSource": "places",
            "placeID": "place-72",
            "placeIDKind": "poi",
            "matchScore": 0.9,
            "matchStatus": "auto",
        }

        with (
            patch("api.flags.service.mysql") as mysql_mock,
            patch("api.flags.service._get_barangay_id_by_coords", return_value=1),
        ):
            mysql_mock.connection.cursor.return_value = cursor
            success, error = update_flag_location(-72, 13.95, 121.15)

        self.assertFalse(success)
        self.assertIn("incompatible schema", error)
        mysql_mock.connection.rollback.assert_called_once()
        mysql_mock.connection.commit.assert_not_called()
        self.assertFalse(any(
            "UPDATE official_registry" in call.args[0]
            for call in cursor.execute.call_args_list
        ))

    def test_existing_history_rows_remain_readable(self):
        self.cursor.fetchall.return_value = [("BIZ-1",), ("BIZ-2",)]

        self.assertEqual(reverify._recent_ids(self.cursor), {"BIZ-1", "BIZ-2"})
        self.assertIn("FROM registry_pin_history",
                      self.cursor.execute.call_args.args[0])


if __name__ == "__main__":
    unittest.main()
