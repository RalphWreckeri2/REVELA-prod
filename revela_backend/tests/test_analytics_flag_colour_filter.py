"""Regression tests: the analytics flag_colour filter must use the derived colour.

geo_sql/geo_on_extra filtered on the raw stored geospatial_logs.flagColor while
the analytics screens display the colour derived from
official_registry.applicationStatus. Filtering by Red could therefore return
rows that were rendered Green.

There is no test database in this project. These tests assert two things:

  1. Wiring - every analytics call site embeds the exact shared expression
     from api/registry/colors.py, so filter and display cannot drift.
  2. Behaviour - the real CASE arms are executed by SQLite against a real
     one-row fixture. Only the correlated registry-status lookup is replaced,
     with the value a database would supply for that row; every CASE arm,
     its precedence and the ELSE <stored colour> fallback are the shipped
     bytes. (SQLite cannot bind a correlated reference inside a subquery
     ORDER BY, which MySQL allows and this expression already relies on.)
"""
from api.registry.colors import _effective_flag_color_sql
from api.analytics import filters
import ast
import os
from pathlib import Path
import re
import sqlite3
import sys
import unittest

sys.path.insert(0, os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..")))


# The correlated registry-status lookup, as emitted by the shared builder.
_STATUS_LOOKUP = re.compile(
    r"\(\s*SELECT\s+r_chk\.applicationStatus.*?LIMIT\s+1\s*\)", re.DOTALL)

# The two ladder lookups. Present only when the builder is called with
# ladder=True; substituted here so these tests keep working either way.
_LOCK_LOOKUP = re.compile(
    r"\(\s*SELECT\s+r_chk\.blackLocked.*?LIMIT\s+1\s*\)", re.DOTALL)
_WARNING_LOOKUP = re.compile(
    r"\(\s*SELECT\s+r_chk\.warningLevel.*?LIMIT\s+1\s*\)", re.DOTALL)

# Aliases used by api/analytics/routes.py for geospatial_logs relations.
GEO_ALIASES = ("g", "g2")


def _with_registry_status(expression, status):
    """Replace the correlated lookups with the values the row resolves to.

    This asserts that no lookup was left behind, rather than how many there
    were. The old "expected 5" check was counting textual occurrences of the
    status subquery - one per CASE arm - so adding or removing an arm broke
    this test without any behaviour changing.
    """
    replacement = "NULL" if status is None else "'%s'" % status
    substituted = _STATUS_LOOKUP.sub(lambda m: replacement, expression)
    substituted = _LOCK_LOOKUP.sub("0", substituted)
    substituted = _WARNING_LOOKUP.sub("0", substituted)
    if "SELECT r_chk." in substituted:
        raise AssertionError(
            "a correlated registry lookup was not substituted; the shared "
            "builder grew a lookup this helper does not cover:\n%s" % substituted)
    return substituted


def _connection():
    con = sqlite3.connect(":memory:")
    con.executescript("""
        CREATE TABLE geospatial_logs (
            logID INTEGER, businessID TEXT, placeID TEXT, barangayID INTEGER,
            detectedName TEXT, flagColor TEXT);
        CREATE TABLE official_registry (
            businessID TEXT, barangayID INTEGER, businessName TEXT,
            applicationStatus TEXT, placeID TEXT);
        CREATE TABLE inspection_reports (
            targetType TEXT, targetID INTEGER, verificationStatus TEXT,
            inspectionResult TEXT);
    """)
    return con


class AnalyticsFilterWiringTests(unittest.TestCase):
    """The filter must reuse the shared expression, not a new mapping."""

    def test_total_flagged_kpi_uses_effective_flag_color(self):
        routes_path = Path(
            __file__).parents[1] / "api" / "analytics" / "routes.py"
        tree = ast.parse(routes_path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or len(node.args) < 3:
                continue
            if not (isinstance(node.args[1], ast.Constant)
                    and node.args[1].value == "kpi.total_flagged"):
                continue

            query_parts = [
                part for part in ast.walk(node.args[2])
                if isinstance(part, ast.JoinedStr)
            ]
            self.assertTrue(query_parts)
            self.assertTrue(any(
                isinstance(part, ast.FormattedValue)
                and isinstance(part.value, ast.Name)
                and part.value.id in {"effective_flag_color", "registry_flag_color"}
                for query_part in query_parts
                for part in query_part.values
            ))
            query_text = "".join(
                part.value
                for query_part in query_parts
                for part in query_part.values
                if isinstance(part, ast.Constant) and isinstance(part.value, str)
            )
            self.assertIn("!= 'Green'", query_text)
            self.assertIn("UNION ALL", query_text)
            self.assertIn("NOT EXISTS", query_text)
            return
        self.fail("kpi.total_flagged query was not found")

    def test_geo_sql_embeds_the_shared_expression(self):
        fragment, _ = filters.geo_sql("g", {"flag_color": "Red"})
        self.assertIn(_effective_flag_color_sql("g"), fragment)

    def test_every_call_site_alias_is_covered(self):
        for alias in GEO_ALIASES:
            with self.subTest(alias=alias):
                fragment, _ = filters.geo_sql(alias, {"flag_color": "Red"})
                self.assertIn(_effective_flag_color_sql(alias), fragment)

    def test_geo_on_extra_embeds_the_shared_expression(self):
        # geo_on_extra is spliced into JOIN ... ON, where the relation is the
        # raw geospatial_logs table, so the expression is usable there too.
        fragment, _ = filters.geo_on_extra("g", {"flag_color": "Red"})
        self.assertIn(_effective_flag_color_sql("g"), fragment)

    def test_filter_no_longer_compares_the_stored_column(self):
        for alias in GEO_ALIASES:
            fragment, _ = filters.geo_sql(alias, {"flag_color": "Red"})
            self.assertNotIn(f"{alias}.flagColor = %s", fragment)
            self.assertNotIn(f"{alias}.flagColor=", fragment)

    def test_filter_is_parenthesised(self):
        # The derived expression is a CASE, so it must be wrapped before =.
        fragment, _ = filters.geo_sql("g", {"flag_color": "Red"})
        self.assertRegex(fragment, r"(?s)AND \(CASE.*END\) = %s")

    def test_param_binding_is_unchanged(self):
        _, params = filters.geo_sql("g", {"flag_color": "Red"})
        self.assertEqual(params, ["Red"])
        _, params = filters.geo_sql("g", {"barangay_ids": [1, 2],
                                          "flag_color": "Yellow"})
        self.assertEqual(params, [1, 2, "Yellow"])

    def test_absent_filter_adds_no_fragment(self):
        fragment, params = filters.geo_sql("g", {"flag_color": None})
        self.assertEqual(fragment, "")
        self.assertEqual(params, [])


class AnalyticsFilterBehaviourTests(unittest.TestCase):
    """Execute the real CASE arms against a real fixture."""

    def _matching_log_ids(self, flag_color, *, stored_colour,
                          registry_status, business_id="BIZ-1",
                          place_id=None):
        """Run the real filter fragment for a single-pin fixture."""
        con = _connection()
        self.addCleanup(con.close)
        con.execute(
            "INSERT INTO geospatial_logs VALUES (?,?,?,?,?,?)",
            (1, business_id, place_id, 7, "ACME STORE", stored_colour))
        if registry_status is not None:
            con.execute(
                "INSERT INTO official_registry VALUES (?,?,?,?,?)",
                (business_id, 7, "ACME STORE", registry_status, None))
        con.commit()

        fragment, params = filters.geo_sql("g", {"flag_color": flag_color})
        fragment = _with_registry_status(fragment, registry_status)
        sql = ("SELECT g.logID FROM geospatial_logs g WHERE 1=1"
               + fragment.replace("%s", "?"))
        return [row[0] for row in con.execute(sql, params).fetchall()]

    # The requirement: a stale pin (Green) on an Expired registry row is Red.

    def test_stale_green_pin_expired_registry_is_returned_by_red_filter(self):
        self.assertEqual(
            self._matching_log_ids("Red", stored_colour="Green",
                                   registry_status="Expired"),
            [1],
        )

    def test_stale_green_pin_expired_registry_is_not_returned_by_green_filter(self):
        self.assertEqual(
            self._matching_log_ids("Green", stored_colour="Green",
                                   registry_status="Expired"),
            [],
        )

    # And the mirror image: a stale Red pin on an Active row is Green.

    def test_stale_red_pin_active_registry_is_not_returned_by_red_filter(self):
        self.assertEqual(
            self._matching_log_ids("Red", stored_colour="Red",
                                   registry_status="Active"),
            [],
        )

    def test_stale_red_pin_active_registry_is_returned_by_green_filter(self):
        self.assertEqual(
            self._matching_log_ids("Green", stored_colour="Red",
                                   registry_status="Active"),
            [1],
        )

    # Unregistered pins have no registry row, so the stored colour still rules.

    def test_unregistered_pin_falls_back_to_stored_colour(self):
        self.assertEqual(
            self._matching_log_ids("Red", stored_colour="Red",
                                   registry_status=None,
                                   business_id=None, place_id="PLACE-1"),
            [1],
        )
        self.assertEqual(
            self._matching_log_ids("Green", stored_colour="Red",
                                   registry_status=None,
                                   business_id=None, place_id="PLACE-1"),
            [],
        )

    # The rest of the registry vocabulary maps the same way.

    def test_remaining_statuses(self):
        expected = {"Pending": "Yellow", "Closed": "Purple",
                    "Revoked": "Black"}
        for status, colour in expected.items():
            with self.subTest(status=status):
                self.assertEqual(
                    self._matching_log_ids(colour, stored_colour="Green",
                                           registry_status=status),
                    [1])
                self.assertEqual(
                    self._matching_log_ids("Red", stored_colour="Green",
                                           registry_status=status),
                    [])


if __name__ == "__main__":
    unittest.main()
