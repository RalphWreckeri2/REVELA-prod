import unittest
from unittest.mock import MagicMock, patch

from flask import Flask

from api.analytics import filters, routes


class AnalyticsRegistryCompatibilityTests(unittest.TestCase):

    def test_uncached_all_route_tracks_inflight_counter(self):
        app = Flask(__name__)
        cursor = MagicMock()
        cursor.fetchone.return_value = None
        mysql_stub = MagicMock()
        mysql_stub.connection.cursor.return_value = cursor

        def run_inner(_filters):
            self.assertEqual(routes._analytics_inflight, 1)
            return {"ok": True}, 200

        with app.test_request_context("/api/analytics/all"):
            with patch.object(routes, "_analytics_cache", {}), \
                    patch.object(routes, "parse_analytics_filters", return_value={}), \
                    patch.object(routes, "_get_all_analytics_inner", side_effect=run_inner), \
                    patch.object(routes, "get_jwt_identity", return_value="1"), \
                    patch.object(routes, "mysql", mysql_stub):
                response, status_code = routes.get_all_analytics.__wrapped__()

        self.assertEqual(status_code, 200)
        self.assertTrue(response.get_json()["ok"])
        self.assertEqual(routes._analytics_inflight, 0)

    def test_effective_analytics_color_uses_only_verified_orange_reports(self):
        expression = routes._effective_flag_color_sql("g")

        self.assertIn("ir.verificationStatus = 'Verified'", expression)
        self.assertIn("ir.inspectionResult = 'Orange'", expression)
        # The verified-Orange predicate used to require the matched registry
        # row to be Expired. A verified Orange report now makes the pin Orange
        # whatever the status, so the restriction must be gone.
        self.assertNotIn("r_chk.applicationStatus = 'Expired'", expression)
        self.assertIn("THEN 'Orange'", expression)
        self.assertIn("WHEN (", expression)
        self.assertIn("THEN 'Red'", expression)

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
