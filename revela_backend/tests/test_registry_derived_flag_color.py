"""Regression tests: the Registry page must report the same colour as the Map.

The Registry list and detail used to return geospatial_logs.flagColor (the
stored pin colour) while the Map returned a colour derived from
official_registry.applicationStatus. A business whose pin was stale therefore
showed Green on the Map and Green/Red on the Registry page.

There is no test database in this project, so these tests assert the contract
at the SQL level: that both registry readers embed the *same* shared
expression the Map uses, that they still expose it under the `flagColor` key
the frontend reads, and that the expression's precedence makes the registry
status win over the stored pin colour.
"""
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..")))

from api.registry import service
from api.registry.colors import _effective_flag_color_sql


def _colour_query(calls):
    """Pick the query that actually selects flagColor.

    The readers now call ladder_columns_available(), which issues its own
    information_schema probe on the same cursor before the real query. That
    shifts the query's position in the call list, so selecting by index is no
    longer reliable; pick by content instead.
    """
    for call in calls:
        sql = call[0][0]
        if "AS flagColor" in sql:
            return sql
    raise AssertionError("no query selecting AS flagColor was executed")


class RegistryDerivedColourTests(unittest.TestCase):

    def _list_sql(self):
        cursor = MagicMock()
        cursor.fetchone.return_value = {"total": 0}
        cursor.fetchall.return_value = []
        connection = MagicMock()
        connection.cursor.return_value = cursor
        with patch.object(service, "mysql") as mock_mysql:
            mock_mysql.connection = connection
            data, error = service.get_all_businesses(barangay_id=1)
        self.assertIsNone(error)
        self.assertIsNotNone(data)
        return _colour_query(cursor.execute.call_args_list)

    def _detail_sql(self):
        cursor = MagicMock()
        cursor.fetchone.return_value = {
            "businessID": "BIZ-1",
            "businessName": "ACME STORE",
            "applicationStatus": "Expired",
            "flagColor": "Red",
            "lastRenewalDate": None,
            "latitude": None,
            "longitude": None,
            "matchScore": None,
        }
        connection = MagicMock()
        connection.cursor.return_value = cursor
        with patch.object(service, "mysql") as mock_mysql:
            mock_mysql.connection = connection
            row, error = service.get_business_by_id("BIZ-1")
        self.assertIsNone(error)
        # get_business_by_id runs the registry row query, then the inspection
        # history. The colour comes from the first.
        return _colour_query(cursor.execute.call_args_list)

    # -- the registry must no longer select the raw stored pin colour ---------

    def test_list_does_not_select_raw_pin_colour(self):
        sql = self._list_sql()
        self.assertIn("AS flagColor", sql)
        self.assertNotIn("\n                g.flagColor\n", sql)

    def test_detail_does_not_select_raw_pin_colour(self):
        sql = self._detail_sql()
        self.assertIn("AS flagColor", sql)
        self.assertNotIn("\n                g.flagColor\n", sql)

    # -- and must use the identical expression the Map uses ------------------

    def test_list_and_detail_embed_the_map_expression(self):
        expected = _effective_flag_color_sql("g")
        for sql in (self._list_sql(), self._detail_sql()):
            self.assertIn(expected, sql)

    def test_map_and_registry_share_one_expression(self):
        """The Map (analytics) and the Registry page cannot drift apart."""
        try:
            from api.analytics import routes as analytics_routes
        except ImportError as exc:
            # api/analytics/routes.py imports google-genai at module load.
            # That dependency is declared in requirements.txt but may be absent
            # from a local venv; the shared-module import above is what
            # actually guarantees agreement, this only cross-checks it.
            self.skipTest(f"analytics blueprint unavailable locally: {exc}")
        self.assertEqual(
            analytics_routes._effective_flag_color_sql("g"),
            _effective_flag_color_sql("g"),
            "analytics must re-export the shared expression unchanged",
        )

    # -- the rule itself: stale pin Green + registry Expired -> Red ----------

    def test_expired_status_maps_to_red_before_the_stored_pin_colour(self):
        expression = _effective_flag_color_sql("g")
        # The registry status arms must all precede the stored-pin fallback,
        # which is what makes a stale Green pin render as Red.
        expired_arm = "= 'Expired' THEN 'Red'"
        fallback = "ELSE g.flagColor"
        self.assertIn(expired_arm, expression)
        self.assertIn(fallback, expression)
        self.assertLess(expression.index(expired_arm),
                        expression.index(fallback))

    def test_registry_status_is_the_source_not_the_pin(self):
        expression = _effective_flag_color_sql("g")
        self.assertIn("SELECT r_chk.applicationStatus", expression)
        self.assertIn("FROM official_registry r_chk", expression)

    def test_every_registry_status_has_an_arm(self):
        expression = _effective_flag_color_sql("g")
        for status, colour in (("'Active'", "'Green'"),
                               ("'Expired'", "'Red'"),
                               ("'Pending'", "'Yellow'"),
                               ("'Closed'", "'Purple'")):
            self.assertIn(f"= {status} THEN {colour}", expression)
        self.assertIn("IN ('Revoked', 'Blacklisted') THEN 'Black'", expression)

    # -- response contract: frontend key must not change ---------------------

    def test_flag_color_key_is_preserved_for_the_frontend(self):
        for sql in (self._list_sql(), self._detail_sql()):
            self.assertRegex(sql, r"AS flagColor\b")


class RegistryFlagFilterTests(unittest.TestCase):

    def _count_sql(self, **filters):
        cursor = MagicMock()
        cursor.fetchone.return_value = {"total": 0}
        cursor.fetchall.return_value = []
        connection = MagicMock()
        connection.cursor.return_value = cursor
        with patch.object(service, "mysql") as mock_mysql, \
                patch.object(service, "ladder_columns_available", return_value=True), \
                patch.object(service, "_has_enforcement_columns", return_value=True):
            mock_mysql.connection = connection
            data, error = service.get_all_businesses(**filters)
        self.assertIsNone(error)
        self.assertIsNotNone(data)
        call = cursor.execute.call_args_list[0][0]
        return call[0], call[1]

    def test_warning_is_the_effective_permit_status_and_filter(self):
        sql, params = self._count_sql(status="Warning")

        self.assertIn("THEN 'Warning'", sql)
        self.assertIn("COALESCE(", sql)
        self.assertLess(
            sql.index("r.applicationStatus IN ('Revoked', 'Blacklisted')"),
            sql.index("THEN 'Warning'"),
        )
        self.assertEqual(params, ["Warning"])

    def test_cleared_warning_keeps_the_active_effective_permit_status(self):
        sql, params = self._count_sql(status="Active")

        self.assertIn("THEN 'Warning'", sql)
        self.assertIn("ELSE r.applicationStatus END = %s", sql)
        self.assertNotIn("warningClearedAt", sql)
        self.assertNotIn("THEN 'Clear'", sql)
        self.assertEqual(params, ["Active"])

    def test_legacy_clear_filter_is_treated_as_active(self):
        _, params = self._count_sql(status="Clear")

        self.assertEqual(params, ["Active"])

    def test_free_text_search_includes_the_derived_status(self):
        sql, params = self._count_sql(search="Warning")

        self.assertIn("THEN 'Warning'", sql)
        self.assertIn("r.applicationStatus LIKE %s", sql)
        self.assertEqual(params, [
            "%Warning%", "%Warning%", "%Warning%", "%Warning%", "%Warning%",
            "%Warning%", "%Warning%", "%Warning%", "%Warning%", "%Warning%",
        ])

    def test_registry_list_and_details_include_pending_inspection_state(self):
        for sql in (RegistryDerivedColourTests()._list_sql(),
                    RegistryDerivedColourTests()._detail_sql()):
            self.assertIn("AS hasNonVerifiedInspection", sql)
            self.assertIn("pending.verificationStatus <> 'Verified'", sql)


if __name__ == "__main__":
    unittest.main()