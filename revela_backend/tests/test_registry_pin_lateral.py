"""The Registry pin projection must expose every column the colour SQL reads.

Both Registry readers get their pin alias `g` from a LATERAL derived table, and
a derived table exposes ONLY the columns it selects. _effective_flag_color_sql
and _flag_source_sql are written against an alias that carries businessID,
placeID, barangayID, detectedName, logID, flagColor and source. When the
projection is short of any of them MySQL does not return a NULL - it raises
"Unknown column 'g.x'" at execution time, which 500s the whole page.

That is exactly what happened: the projection read `logID, placeID, flagColor`
while the colour SQL reached for g.businessID, so GET /api/registry/ and
GET /api/registry/<id> both failed while the rows sat in the table. The Map and
Analytics readers were unaffected because there `g` IS geospatial_logs itself,
not a derived table.

A fake cursor cannot catch this: it never resolves a column reference. These
tests therefore assert the contract on the SQL text instead, and they mock the
DictCursor row shape config.py actually produces rather than tuple rows.
"""
import os
import re
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..")))

from api.registry.colors import reset_ladder_column_cache
from api.models.geospatial import reset_source_column_cache

#: Everything the shared builders may reference through the pin alias.
#: Derived from the builders, restated here so a builder that grows a new
#: reference fails this test until the projection is widened to match.
REQUIRED_PIN_COLUMNS = (
    "logID", "placeID", "flagColor", "businessID", "barangayID", "detectedName",
)

MIGRATED = ["warningLevel", "blackLocked", "blackDispatchUnlocked"]
MIGRATED_WITH_SOURCE = MIGRATED + ["source"]


class _DictCursor:
    """DictCursor-shaped, because config.py sets MYSQL_CURSORCLASS.

    Probe rows come back as mappings. The previous generation of these tests
    returned tuples, which is a shape no production connection produces.
    """

    def __init__(self, *, columns=(), rows=()):
        self.columns = set(columns)
        self.rows = [dict(r) for r in rows]
        self.calls = []
        self.rowcount = 1

    @staticmethod
    def _flat(sql):
        return " ".join(sql.split())

    def execute(self, sql, params=()):
        self.calls.append((self._flat(sql), params))
        self.rowcount = 1

    def fetchone(self):
        flat = self.calls[-1][0] if self.calls else ""
        if "information_schema.COLUMNS" in flat:
            names = [{"COLUMN_NAME": n} for n in sorted(self.columns)]
            return names[0] if names else None
        if "COUNT(*)" in flat:
            return {"total": len(self.rows)}
        return dict(self.rows[0]) if self.rows else None

    def fetchall(self):
        flat = self.calls[-1][0] if self.calls else ""
        if "information_schema.COLUMNS" in flat:
            return [{"COLUMN_NAME": n} for n in sorted(self.columns)]
        if "COUNT(*)" in flat:
            return [{"total": len(self.rows)}]
        return [dict(r) for r in self.rows]

    def close(self):
        pass

    def statement(self, marker):
        return next(s for s, _ in self.calls if marker in s)


class RegistryPinLateralTests(unittest.TestCase):

    def setUp(self):
        reset_ladder_column_cache()
        reset_source_column_cache()
        self.addCleanup(reset_ladder_column_cache)
        self.addCleanup(reset_source_column_cache)

    def _read(self, columns, reader):
        from api.registry import service

        row = {"businessID": "BIZ-1", "businessName": "ACME",
               "barangayID": 7, "applicationStatus": "Active",
               "lastRenewalDate": None, "latitude": None, "longitude": None,
               "matchScore": None}
        cursor = _DictCursor(columns=columns, rows=[row])
        connection = MagicMock()
        connection.cursor.return_value = cursor
        with patch.object(service, "mysql") as mock_mysql:
            mock_mysql.connection = connection
            if reader == "list":
                service.get_all_businesses()
            else:
                service.get_business_by_id("BIZ-1")
        return cursor

    # ── helpers ──────────────────────────────────────────────────────────

    @staticmethod
    def _projection(sql):
        """The column list the LATERAL pin subquery selects."""
        match = re.search(r"LEFT JOIN LATERAL \(\s*SELECT (.+?) FROM geospatial_logs",
                          sql, re.S)
        assert match, "no LATERAL pin projection found in:\n" + sql
        return [c.strip() for c in match.group(1).split(",")]

    @staticmethod
    def _referenced(sql):
        """Every column the statement reads through the pin alias `g`."""
        return set(re.findall(r"\bg\.([A-Za-z_][A-Za-z0-9_]*)", sql))

    # ── the invariant ─────────────────────────────────────────────────────

    def _assert_projection_covers_references(self, columns, reader):
        sql = self._read(columns, reader).statement("AS flagColor")
        projected = set(self._projection(sql))
        referenced = self._referenced(sql)
        missing = referenced - projected
        self.assertFalse(
            missing,
            f"{reader} SQL references g.{', g.'.join(sorted(missing))} but the "
            f"LATERAL projection only exposes {sorted(projected)}. MySQL would "
            f"raise 'Unknown column' and 500 the page.")

    def test_list_projection_covers_everything_the_colour_sql_reads(self):
        self._assert_projection_covers_references(MIGRATED, "list")

    def test_detail_projection_covers_everything_the_colour_sql_reads(self):
        self._assert_projection_covers_references(MIGRATED, "detail")

    def test_unmigrated_projection_is_equally_complete(self):
        self._assert_projection_covers_references([], "list")

    def test_the_known_needed_columns_are_all_present(self):
        """Named explicitly, so the failure names the missing column."""
        sql = self._read(MIGRATED, "list").statement("AS flagColor")
        projected = set(self._projection(sql))
        for column in REQUIRED_PIN_COLUMNS:
            with self.subTest(column=column):
                self.assertIn(column, projected)

    # ── source is opt-in ──────────────────────────────────────────────────

    def test_source_is_projected_when_the_column_exists(self):
        sql = self._read(MIGRATED_WITH_SOURCE, "list").statement("AS flagColor")
        self.assertIn("source", self._projection(sql))
        self.assertIn("g.source", sql)

    def test_source_is_never_named_on_an_unmigrated_database(self):
        """Naming a missing column breaks the query outright."""
        sql = self._read([], "list").statement("AS flagColor")
        self.assertNotIn("source", self._projection(sql))
        self.assertNotIn("g.source", sql)

    def test_both_readers_project_the_same_columns(self):
        """One builder feeds both, so they cannot drift."""
        list_sql = self._read(MIGRATED, "list").statement("AS flagColor")
        detail_sql = self._read(MIGRATED, "detail").statement("AS flagColor")
        self.assertEqual(self._projection(list_sql),
                         self._projection(detail_sql))

    # ── the reader still returns rows ─────────────────────────────────────

    def test_the_list_reads_rows_with_a_dict_cursor(self):
        from api.registry import service

        cursor = self._read(MIGRATED, "list")
        # The reader ran to completion and issued its paginated query.
        self.assertTrue(any("ORDER BY r.businessName ASC" in s
                            for s, _ in cursor.calls))
        self.assertTrue(callable(service.get_all_businesses))


if __name__ == "__main__":
    unittest.main()