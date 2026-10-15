"""Phase 1, Part 3: the Black-lock guard in api/registry/locks.py.

Nothing calls this yet. These tests pin the behaviour it must have before
Phase 2 wires it into the verify write path, the sync path and manual edits.

The most important one is the fail-safe rule: if
migrations/20261015_01_enforcement_ladder_schema.sql has not been applied,
official_registry.blackLocked does not exist, and the guard must report "not
locked" rather than freezing every write path on every unmigrated database.
"""
import os
import sys
import unittest
from unittest.mock import MagicMock

sys.path.insert(0, os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..")))

from api.registry import locks


# ── 4. The Black guard ────────────────────────────────────────────────────────


def _locked_cursor(*, column_present, rows):
    """A fake cursor answering the probe then the row read."""
    cursor = MagicMock()
    state = {"probed": False}

    def execute(sql, params=()):
        if "information_schema" in sql:
            state["probed"] = True
            cursor.fetchone.return_value = ("blackLocked",) if column_present \
                else None
        else:
            cursor.fetchone.return_value = rows.get(params[0])
        return cursor

    cursor.execute.side_effect = execute
    return cursor


class BlackLockGuardTests(unittest.TestCase):

    def setUp(self):
        locks.reset_lock_column_cache()
        self.addCleanup(locks.reset_lock_column_cache)

    def test_unmigrated_database_is_treated_as_not_locked(self):
        """Fail-safe: a missing column must not freeze every write path."""
        cursor = _locked_cursor(column_present=False, rows={})
        self.assertFalse(locks.is_black_locked(cursor, "BIZ-1"))
        self.assertTrue(locks.assert_not_black_locked(
            cursor, "BIZ-1", action="verify"))

    def test_a_locked_row_raises(self):
        cursor = _locked_cursor(column_present=True, rows={"BIZ-1": (1,)})
        self.assertTrue(locks.is_black_locked(cursor, "BIZ-1"))
        with self.assertRaises(locks.BlackLockedError):
            locks.assert_not_black_locked(cursor, "BIZ-1",
                                          action="verify this inspection")

    def test_the_error_carries_the_action_and_the_business_id(self):
        cursor = _locked_cursor(column_present=True, rows={"BIZ-1": (1,)})
        with self.assertRaises(locks.BlackLockedError) as caught:
            locks.assert_not_black_locked(cursor, "BIZ-1", action="sync")
        self.assertEqual(caught.exception.action, "sync")
        self.assertEqual(caught.exception.business_id, "BIZ-1")
        self.assertIn("BIZ-1", str(caught.exception))
        self.assertIn("SUPER_ADMIN", str(caught.exception))

    def test_an_unlocked_row_passes(self):
        cursor = _locked_cursor(column_present=True, rows={"BIZ-1": (0,)})
        self.assertFalse(locks.is_black_locked(cursor, "BIZ-1"))
        self.assertTrue(locks.assert_not_black_locked(
            cursor, "BIZ-1", action="sync"))

    def test_a_missing_row_is_not_locked(self):
        cursor = _locked_cursor(column_present=True, rows={})
        self.assertFalse(locks.is_black_locked(cursor, "BIZ-1"))

    def test_a_null_column_is_not_locked(self):
        cursor = _locked_cursor(column_present=True, rows={"BIZ-1": (None,)})
        self.assertFalse(locks.is_black_locked(cursor, "BIZ-1"))

    def test_a_missing_business_id_never_queries(self):
        cursor = _locked_cursor(column_present=True, rows={})
        for value in (None, "", 0):
            with self.subTest(business_id=value):
                self.assertFalse(locks.is_black_locked(cursor, value))
        cursor.execute.assert_not_called()

    def test_reads_a_dict_row(self):
        cursor = _locked_cursor(column_present=True,
                                rows={"BIZ-1": {"blackLocked": 1}})
        self.assertTrue(locks.is_black_locked(cursor, "BIZ-1"))

    def test_tolerates_a_string_valued_column(self):
        for raw, locked in (("1", True), ("0", False), ("", False),
                            ("true", True), ("NULL", False)):
            with self.subTest(raw=raw):
                cursor = _locked_cursor(column_present=True,
                                        rows={"BIZ-1": (raw,)})
                self.assertEqual(locks.is_black_locked(cursor, "BIZ-1"),
                                 locked)

    def test_the_probe_is_cached(self):
        first = _locked_cursor(column_present=True, rows={"BIZ-1": (1,)})
        self.assertTrue(locks.is_black_locked(first, "BIZ-1"))
        calls_after_probe = first.execute.call_count

        # The lock has since been cleared, but the cached probe means we still
        # read the row; the point is that the information_schema query is not
        # repeated on every call.
        second = _locked_cursor(column_present=True, rows={"BIZ-1": (0,)})
        self.assertFalse(locks.is_black_locked(second, "BIZ-1"))
        self.assertEqual(second.execute.call_count, calls_after_probe - 1)
        locks.reset_lock_column_cache()


class BlackGuardIsNotWiredInTests(unittest.TestCase):
    """Phase 1 rule: nothing may call the guard yet."""

    def test_no_production_module_imports_locks(self):
        import pathlib

        api_root = pathlib.Path(__file__).resolve().parents[1] / "api"
        offenders = []
        for path in api_root.rglob("*.py"):
            if path.name == "locks.py":
                continue
            if "registry import locks" in path.read_text(encoding="utf-8") \
                    or "from .locks" in path.read_text(encoding="utf-8") \
                    or "from api.registry.locks" in path.read_text(
                        encoding="utf-8"):
                offenders.append(path.relative_to(api_root))
        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()
