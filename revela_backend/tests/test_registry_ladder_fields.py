"""Phase 3A follow-up: the Registry readers expose the ladder fields.

The Registry page's Clear Warning and Unlock buttons read
warningLevel, blackLocked and blackDispatchUnlocked off the row. Until the
readers returned them the buttons could never appear, however correct the
policy module was.

Safe on an un-migrated database: a column that does not exist is selected as a
literal 0, never named, because MySQL raises "Unknown column" at execution
time for a column that is not there.
"""
from api.registry.locks import reset_lock_column_cache
from api.registry.colors import reset_ladder_column_cache
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..")))


class _ReaderCursor:
    """Answers a registry reader's statements.

    `columns` is what information_schema reports. Both probe shapes are
    answered - _has_columns and ladder_columns_available use fetchall(), the
    Black guard uses fetchone() - because a reader that answers only one of
    them silently reads the ladder as absent.
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
            return ("warningLevel",) if self.columns else None
        if "COUNT(*)" in flat:
            return {"total": 0}
        return dict(self.rows[0]) if self.rows else None

    def fetchall(self):
        flat = self.calls[-1][0] if self.calls else ""
        if "information_schema.COLUMNS" in flat:
            return [(name,) for name in sorted(self.columns)]
        return []

    def close(self):
        pass

    def colour_sql(self):
        return next(s for s, _ in self.calls if "AS flagColor" in s)


MIGRATED = ["applicationStatus", "warningLevel", "blackLocked",
            "blackDispatchUnlocked"]


class LadderFieldTests(unittest.TestCase):

    def setUp(self):
        reset_ladder_column_cache()
        reset_lock_column_cache()
        self.addCleanup(reset_ladder_column_cache)
        self.addCleanup(reset_lock_column_cache)

    def _builder(self, columns):
        from api.registry import service

        return service._ladder_select_sql(_ReaderCursor(columns=columns))

    # ── the shared builder ─────────────────────────────────────────────────

    def test_reads_the_state_table_when_it_exists(self):
        sql = self._builder(MIGRATED)
        for column in ("es.warningLevel", "es.blackLocked",
                       "es.blackDispatchUnlocked"):
            self.assertIn(column, sql)
        self.assertNotIn("0 AS", sql)

    def test_returns_zeros_when_they_do_not_exist(self):
        sql = self._builder([])
        self.assertIn("0 AS warningLevel", sql)
        self.assertIn("0 AS blackLocked", sql)
        self.assertIn("0 AS blackDispatchUnlocked", sql)
        self.assertNotIn("es.warningLevel", sql)

    def test_handles_a_partially_migrated_database(self):
        """warningLevel landed but blackDispatchUnlocked did not."""
        sql = self._builder(["warningLevel", "blackLocked"])
        self.assertIn("es.warningLevel", sql)
        self.assertIn("es.blackLocked", sql)
        self.assertIn("0 AS blackDispatchUnlocked", sql)

    # ── both readers ───────────────────────────────────────────────────────

    def _read(self, columns, reader):
        from api.registry import service

        row = {"businessID": "BIZ-1", "businessName": "ACME",
               "barangayID": 7, "applicationStatus": "Active",
               "lastRenewalDate": None, "latitude": None, "longitude": None,
               "matchScore": None}
        cursor = _ReaderCursor(columns=columns, rows=[row])
        connection = MagicMock()
        connection.cursor.return_value = cursor
        with patch.object(service, "mysql") as mock_mysql:
            mock_mysql.connection = connection
            if reader == "list":
                service.get_all_businesses(barangay_id=1)
            else:
                service.get_business_by_id("BIZ-1")
        return cursor

    def test_the_list_selects_the_ladder_fields(self):
        sql = self._read(MIGRATED, "list").colour_sql()
        for column in ("es.warningLevel", "es.blackLocked",
                       "es.blackDispatchUnlocked"):
            self.assertIn(column, sql)

    def test_the_detail_selects_the_ladder_fields(self):
        sql = self._read(MIGRATED, "detail").colour_sql()
        for column in ("es.warningLevel", "es.blackLocked",
                       "es.blackDispatchUnlocked"):
            self.assertIn(column, sql)

    def test_the_list_returns_zeros_when_unmigrated(self):
        sql = self._read([], "list").colour_sql()
        self.assertNotIn("es.warningLevel", sql)
        self.assertIn("0 AS warningLevel", sql)
        self.assertIn("0 AS blackDispatchUnlocked", sql)

    def test_the_detail_returns_zeros_when_unmigrated(self):
        sql = self._read([], "detail").colour_sql()
        self.assertNotIn("es.blackLocked", sql)
        self.assertIn("0 AS blackLocked", sql)

    def test_both_readers_agree(self):
        """One builder feeds both, so they cannot drift."""
        list_sql = self._read(MIGRATED, "list").colour_sql()
        detail_sql = self._read(MIGRATED, "detail").colour_sql()
        for column in ("warningLevel", "blackLocked", "blackDispatchUnlocked"):
            self.assertEqual(column in list_sql, column in detail_sql)

    def test_the_wire_names_match_the_policy_module(self):
        """registryLadderPolicy.js reads exactly these keys."""
        import pathlib

        policy = pathlib.Path(__file__).resolve().parents[2] / "revela_web" \
            / "src" / "components" / "registryLadderPolicy.js"
        if not policy.exists():
            self.skipTest("web sources not available next to the backend")
        source = policy.read_text(encoding="utf-8")
        migrated = self._builder(MIGRATED)
        for key in ("warningLevel", "blackLocked"):
            with self.subTest(key=key):
                self.assertIn(key, source)
            self.assertIn(f"es.{key}", migrated)


if __name__ == "__main__":
    unittest.main()
