"""Phase 3B, Part 1: geospatial_logs.source.

Each insert point is checked for the value it writes, with the column present
and absent. The colour logic and _sync_flag_color are not mocked: the seed
test runs the real _sync_flag_color against a fake cursor and reads the
statement it would have run.

The source-column cache is reset per test; it is process-global, so whichever
test answered the probe first would decide it for every test after it.
"""
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..")))

from api.models import geospatial
from api.models.geospatial import (
    SOURCE_DETECTION,
    SOURCE_MANUAL,
    SOURCE_REGISTRY,
    SOURCE_REGISTRY_DETECTED,
    SOURCE_UNKNOWN,
    SOURCE_VALUES,
    reset_source_column_cache,
    with_source,
)


class _ProbeCursor:
    """A fake cursor that answers the source probe and records everything.

    `row_for` maps a fragment of the statement to the row fetchone should
    return, so a caller under test can be fed a pin that exists or does not.
    """

    def __init__(self, *, has_column, rows=None):
        self.has_column = has_column
        self.rows = rows or {}
        self.calls = []
        self.lastrowid = 7
        self.rowcount = 1

    @staticmethod
    def _flat(sql):
        return " ".join(sql.split())

    def execute(self, sql, params=()):
        self.calls.append((self._flat(sql), tuple(params)))

    def _last(self):
        return self.calls[-1][0] if self.calls else ""

    def fetchone(self):
        flat = self._last()
        if "information_schema.COLUMNS" in flat:
            return ("source",) if self.has_column else None
        for needle, value in self.rows.items():
            if needle in flat:
                return dict(value) if isinstance(value, dict) else value
        return None

    def fetchall(self):
        if "information_schema.COLUMNS" in self._last():
            return [("source",)] if self.has_column else []
        return []

    def close(self):
        pass

    def inserts(self):
        return [(s, p) for s, p in self.calls
                if s.upper().startswith("INSERT INTO GEOSPATIAL_LOGS")]


class WithSourceTests(unittest.TestCase):

    def setUp(self):
        reset_source_column_cache()
        self.addCleanup(reset_source_column_cache)

    def _with(self, *, has_column, source=SOURCE_REGISTRY):
        cursor = _ProbeCursor(has_column=has_column)
        columns, values, params = with_source(
            cursor, "(a, b)", "(%s, %s)", (1, 2), source)
        return columns, values, params

    def test_appends_the_column_when_it_exists(self):
        columns, values, params = self._with(has_column=True)
        # The closing paren must move with the added item, or this is not a
        # column list at all.
        self.assertEqual(columns, "(a, b, source)")
        self.assertEqual(values, "(%s, %s, %s)")
        self.assertEqual(params, (1, 2, SOURCE_REGISTRY))

    def test_returns_the_insert_untouched_when_it_does_not(self):
        columns, values, params = self._with(has_column=False)
        self.assertEqual(columns, "(a, b)")
        self.assertEqual(values, "(%s, %s)")
        self.assertEqual(params, (1, 2))

    def test_rejects_a_source_outside_the_documented_set(self):
        cursor = _ProbeCursor(has_column=True)
        for bad in ("maps_only", "inspector_reported", "", None, "REGISTRY"):
            with self.subTest(source=bad):
                with self.assertRaises(ValueError):
                    with_source(cursor, "(a)", "(%s)", (1,), bad)

    def test_the_probe_is_cached(self):
        cursor = _ProbeCursor(has_column=True)
        with_source(cursor, "(a)", "(%s)", (1,), SOURCE_REGISTRY)
        cursor.execute.assert_not_called() if isinstance(
            cursor.execute, MagicMock) else None
        second = _ProbeCursor(has_column=False)
        with_source(second, "(a)", "(%s)", (1,), SOURCE_REGISTRY)
        self.assertEqual(len(second.calls), 0, "the cache should short-circuit")

    def test_every_allowed_value_is_accepted(self):
        cursor = _ProbeCursor(has_column=True)
        for source in SOURCE_VALUES:
            with self.subTest(source=source):
                columns, _, params = with_source(
                    cursor, "(a)", "(%s)", (1,), source)
                self.assertIn("source", columns)
                self.assertEqual(params[-1], source)


class InsertPointTests(unittest.TestCase):

    def setUp(self):
        reset_source_column_cache()
        self.addCleanup(reset_source_column_cache)

    def _seed_cursor(self, *, has_column, exists=True):
        rows = ({"SELECT g.logID": {"logID": 5, "has_verified_orange": 0}}
                if exists else {})
        return _ProbeCursor(has_column=has_column, rows=rows)

    def _seeded_source(self, *, has_column):
        from api.registry import service

        # exists=False: the seed branch only runs when the business has no
        # pin yet, which is the only path that INSERTs.
        cursor = self._seed_cursor(has_column=has_column, exists=False)
        service._sync_flag_color(
            cursor, 7, "ACME", "Active", 13.9, 121.1, "Somewhere",
            business_id="BIZ-1")
        inserts = cursor.inserts()
        assert len(inserts) == 1, inserts
        sql, params = inserts[0]
        if has_column:
            self.assertIn("source", sql)
            self.assertEqual(params[-1], SOURCE_REGISTRY)
        else:
            self.assertNotIn("source", sql)
            self.assertEqual(len(params), 7)

    def test_sync_flag_color_seed_writes_registry(self):
        self._seeded_source(has_column=True)

    def test_sync_flag_color_seed_omits_it_when_missing(self):
        self._seeded_source(has_column=False)

    def test_insert_green_flag_writes_registry(self):
        connection = MagicMock()
        cursor = self._seed_cursor(has_column=True)
        connection.cursor.return_value = cursor
        with patch.object(geospatial, "mysql") as mock_mysql:
            mock_mysql.connection = connection
            geospatial.insert_green_flag(7, "ACME", 13.9, 121.1, business_id="B")
        sql, params = cursor.inserts()[0]
        self.assertIn("source", sql)
        self.assertEqual(params[-1], SOURCE_REGISTRY)

    def test_insert_green_flag_omits_it_when_missing(self):
        connection = MagicMock()
        cursor = self._seed_cursor(has_column=False)
        connection.cursor.return_value = cursor
        with patch.object(geospatial, "mysql") as mock_mysql:
            mock_mysql.connection = connection
            geospatial.insert_green_flag(7, "ACME", 13.9, 121.1, business_id="B")
        sql, params = cursor.inserts()[0]
        self.assertNotIn("source", sql)


class ReadSideTests(unittest.TestCase):
    """The readers prefer the stored source and keep the old label otherwise."""

    def setUp(self):
        reset_source_column_cache()
        reset_source_column_cache()
        self.addCleanup(reset_source_column_cache)

    def _flag_source_sql(self, *, has_column):
        from api.registry import service

        cursor = _ProbeCursor(has_column=has_column)
        return service._flag_source_sql("g", "'old_label'", cursor)

    def test_prefers_the_stored_column_when_it_exists(self):
        sql = self._flag_source_sql(has_column=True)
        self.assertIn("COALESCE(g.source,", sql)
        self.assertIn("'old_label'", sql, "the fallback must remain")

    def test_falls_back_when_the_column_is_absent(self):
        sql = self._flag_source_sql(has_column=False)
        self.assertNotIn("g.source", sql)
        self.assertIn("'old_label'", sql)

    def test_the_registry_fallback_still_answers_the_pin_question(self):
        from api.registry import service

        self.assertIn("g.logID IS NULL", service._OLD_REGISTRY_FLAG_SOURCE)
        self.assertIn("'registry_detected'", service._OLD_REGISTRY_FLAG_SOURCE)
        self.assertIn("'registry'", service._OLD_REGISTRY_FLAG_SOURCE)

    def test_the_map_fallback_speaks_the_stored_vocabulary(self):
        """One vocabulary on the wire, so the frontend carries one."""
        from api.flags import service

        # The fallback is a four-way guess and never says "unknown": a pin
        # always matches one of the arms. 'unknown' is what the stored column
        # holds for a pin nobody can place.
        for label in ("manual", "registry_detected", "registry", "detection"):
            self.assertIn(f"'{label}'", service._OLD_MAP_FLAG_SOURCE)
        for old in ("registry_only", "registry_and_maps", "maps_only",
                    "inspector_reported"):
            self.assertNotIn(old, service._OLD_MAP_FLAG_SOURCE)

    def test_the_insert_modules_route_through_with_source(self):
        """No call site may hand-roll the check.

        A site that named the column directly would break every insert on an
        un-migrated database. The defence is that the decision is made in
        exactly one place, so every insert statement here is an f-string built
        from with_source's output rather than a literal.
        """
        import inspect as _inspect

        from api.flags import service as flags_service
        from api.registry import service as registry_service

        for module in (flags_service, registry_service):
            source = _inspect.getsource(module)
            inserts = [line for line in source.splitlines()
                       if "INSERT INTO geospatial_logs" in line]
            with self.subTest(module=module.__name__):
                self.assertTrue(inserts)
                for line in inserts:
                    # Every statement is an f-string that splices in
                    # with_source's output. A literal INSERT would name the
                    # column and break on an un-migrated database.
                    self.assertIn(
                        "{", line,
                        "geospatial_logs INSERT must be an f-string built "
                        "from with_source: %r" % (line,))
                self.assertIn("with_source(", source)

    def test_the_dev_script_is_left_as_unknown(self):
        """simulate_new_year.py seeds test data and stays untouched."""
        import pathlib as _pathlib

        script = (_pathlib.Path(__file__).resolve().parents[1]
                  / "scripts" / "simulate_new_year.py")
        source = script.read_text(encoding="utf-8")
        self.assertIn("INSERT INTO geospatial_logs", source)
        self.assertNotIn("source", source.split(
            "INSERT INTO geospatial_logs")[1][:200])

    def test_red_flag_insert_writes_detection(self):
        from api.flags import service as flags_service

        cursor = _ProbeCursor(has_column=True)
        with (
            patch.object(flags_service, "mysql") as mock_mysql,
            patch.object(flags_service, "_detection_execute",
                         side_effect=lambda c, sql, params=(): c.execute(sql, params)),
            patch.object(flags_service, "_detection_commit"),
        ):
            mock_mysql.connection.cursor.return_value = cursor
            flags_service._insert_red_flag(
                "P1", "Shop", 13.9, 121.1, 7, commit=False)
        sql, params = cursor.inserts()[0]
        self.assertIn("source", sql)
        self.assertEqual(params[-1], SOURCE_DETECTION)

    def test_red_flag_insert_omits_it_when_missing(self):
        from api.flags import service as flags_service

        cursor = _ProbeCursor(has_column=False)
        with (
            patch.object(flags_service, "mysql") as mock_mysql,
            patch.object(flags_service, "_detection_execute",
                         side_effect=lambda c, sql, params=(): c.execute(sql, params)),
            patch.object(flags_service, "_detection_commit"),
        ):
            mock_mysql.connection.cursor.return_value = cursor
            flags_service._insert_red_flag(
                "P1", "Shop", 13.9, 121.1, 7, commit=False)
        sql, params = cursor.inserts()[0]
        self.assertNotIn("source", sql)

    def test_the_parens_survive_the_append(self):
        """Regression: appending after the closing paren is not a column list."""
        cursor = _ProbeCursor(has_column=True)
        columns, values, _ = with_source(
            cursor, "(a, b, c)", "(%s, %s, %s)", (1, 2, 3), SOURCE_REGISTRY)
        self.assertTrue(columns.endswith(")"))
        self.assertTrue(values.endswith(")"))
        self.assertNotIn("), source", columns)


if __name__ == "__main__":
    unittest.main()
