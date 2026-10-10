import unittest
from unittest.mock import MagicMock

from api.analytics import filters, routes


class AnalyticsRegistryCompatibilityTests(unittest.TestCase):

    def test_registration_type_column_detection_uses_current_database_schema(self):
        cursor = MagicMock()
        cursor.fetchone.return_value = {"column_count": 0}

        self.assertFalse(routes._registry_has_registration_type(cursor))
        query = cursor.execute.call_args.args[0]
        self.assertIn("information_schema.COLUMNS", query)
        self.assertIn("TABLE_SCHEMA = DATABASE()", query)
        self.assertEqual(cursor.execute.call_args.args[1:], ())

    def test_unsupported_registration_type_filter_returns_no_matches(self):
        sql, params = filters.registry_sql(
            "o",
            {
                "registration_type": "New",
                "registration_type_supported": False,
            },
        )

        self.assertEqual(sql, " AND 1=0")
        self.assertEqual(params, [])

    def test_registration_type_filter_is_preserved_when_column_exists(self):
        sql, params = filters.registry_sql(
            "o",
            {
                "registration_type": "New",
                "registration_type_supported": True,
            },
        )

        self.assertEqual(sql, " AND o.registrationType = %s")
        self.assertEqual(params, ["New"])


if __name__ == "__main__":
    unittest.main()
