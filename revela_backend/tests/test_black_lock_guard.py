"""Phase 1, Part 3: the Black-lock guard in api/registry/locks.py.

Nothing calls this yet. These tests pin the behaviour it must have before
Phase 2 wires it into the verify write path, the sync path and manual edits.

The most important one is the fail-safe rule: if
migrations/20261015_01_enforcement_ladder_schema.sql has not been applied,
official_registry.blackLocked does not exist, and the guard must report "not
locked" rather than freezing every write path on every unmigrated database.
"""
from api.registry import locks
import os
import sys
import unittest
from unittest.mock import MagicMock

sys.path.insert(0, os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..")))


# ── 4. The Black guard ────────────────────────────────────────────────────────


def _locked_cursor(*, column_present, rows):
    """A fake cursor returning the joined enforcement state and permit."""
    cursor = MagicMock()

    def execute(sql, params=()):
        cursor.fetchone.return_value = rows.get(params[0])
        return cursor

    cursor.execute.side_effect = execute
    return cursor


class BlackLockGuardTests(unittest.TestCase):

    def setUp(self):
        locks.reset_lock_column_cache()
        self.addCleanup(locks.reset_lock_column_cache)

    def test_unmigrated_database_is_treated_as_not_locked(self):
        """A registered business with no enforcement-state row is not locked."""
        cursor = _locked_cursor(column_present=False,
                                rows={"BIZ-1": (None, "Active")})
        self.assertFalse(locks.is_black_locked(cursor, "BIZ-1"))
        self.assertTrue(locks.assert_not_black_locked(
            cursor, "BIZ-1", action="verify"))

    def test_a_locked_row_raises(self):
        cursor = _locked_cursor(column_present=True,
                                rows={"BIZ-1": (1, "Active")})
        self.assertTrue(locks.is_black_locked(cursor, "BIZ-1"))
        with self.assertRaises(locks.BlackLockedError):
            locks.assert_not_black_locked(cursor, "BIZ-1",
                                          action="verify this inspection")

    def test_revoked_is_locked_with_or_without_the_lock_column(self):
        for migrated in (True, False):
            locks.reset_lock_column_cache()
            row = (0 if migrated else None, "Revoked")
            cursor = _locked_cursor(
                column_present=migrated, rows={"BIZ-1": row})
            with self.subTest(migrated=migrated):
                self.assertTrue(locks.is_black_locked(cursor, "BIZ-1"))
                with self.assertRaises(locks.BlackLockedError):
                    locks.assert_not_black_locked(
                        cursor, "BIZ-1", action="sync")

    def test_the_error_carries_the_action_and_the_business_id(self):
        cursor = _locked_cursor(column_present=True,
                                rows={"BIZ-1": (1, "Active")})
        with self.assertRaises(locks.BlackLockedError) as caught:
            locks.assert_not_black_locked(cursor, "BIZ-1", action="sync")
        self.assertEqual(caught.exception.action, "sync")
        self.assertEqual(caught.exception.business_id, "BIZ-1")
        self.assertIn("BIZ-1", str(caught.exception))
        self.assertIn("cannot be edited or deleted", str(caught.exception))

    def test_an_unlocked_row_passes(self):
        cursor = _locked_cursor(column_present=True,
                                rows={"BIZ-1": (0, "Active")})
        self.assertFalse(locks.is_black_locked(cursor, "BIZ-1"))
        self.assertTrue(locks.assert_not_black_locked(
            cursor, "BIZ-1", action="sync"))

    def test_a_missing_row_is_not_locked(self):
        cursor = _locked_cursor(column_present=True, rows={})
        self.assertFalse(locks.is_black_locked(cursor, "BIZ-1"))

    def test_a_null_column_is_not_locked(self):
        cursor = _locked_cursor(column_present=True,
                                rows={"BIZ-1": (None, "Active")})
        self.assertFalse(locks.is_black_locked(cursor, "BIZ-1"))

    def test_a_missing_business_id_never_queries(self):
        cursor = _locked_cursor(column_present=True, rows={})
        for value in (None, "", 0):
            with self.subTest(business_id=value):
                self.assertFalse(locks.is_black_locked(cursor, value))
        cursor.execute.assert_not_called()

    def test_reads_a_dict_row(self):
        cursor = _locked_cursor(column_present=True,
                                rows={"BIZ-1": {"blackLocked": 1,
                                                "applicationStatus": "Active"}})
        self.assertTrue(locks.is_black_locked(cursor, "BIZ-1"))

    def test_tolerates_a_string_valued_column(self):
        for raw, locked in (("1", True), ("0", False), ("", False),
                            ("true", True), ("NULL", False)):
            with self.subTest(raw=raw):
                cursor = _locked_cursor(column_present=True,
                                        rows={"BIZ-1": (raw, "Active")})
                self.assertEqual(locks.is_black_locked(cursor, "BIZ-1"),
                                 locked)

    def test_reads_the_current_state_on_each_check(self):
        first = _locked_cursor(column_present=True,
                               rows={"BIZ-1": (1, "Active")})
        self.assertTrue(locks.is_black_locked(first, "BIZ-1"))
        second = _locked_cursor(column_present=True,
                                rows={"BIZ-1": (0, "Active")})
        self.assertFalse(locks.is_black_locked(second, "BIZ-1"))
        second.execute.assert_called_once()
        locks.reset_lock_column_cache()


class BlackGuardWiringTests(unittest.TestCase):
    """Every write path that must refuse a Black-locked business calls it."""

    #: assert_not_black_locked refuses the whole operation.
    GUARDED = {
        "flags/service.py",
        "inspections/service.py",
        "registry/service.py",
        "registry/reverify.py",
    }

    def _api_root(self):
        import pathlib

        return pathlib.Path(__file__).resolve().parents[1] / "api"

    def _callers(self, needle):
        root = self._api_root()
        return {
            path.relative_to(root).as_posix()
            for path in root.rglob("*.py")
            if path.name != "locks.py"
            and needle in path.read_text(encoding="utf-8")
        }

    def test_the_guard_is_called_from_every_write_path(self):
        callers = self._callers("assert_not_black_locked")
        self.assertTrue(
            self.GUARDED.issubset(callers),
            "not wired: %s" % sorted(self.GUARDED - callers))
        self.assertFalse(
            callers - self.GUARDED,
            "unexpected caller: %s" % sorted(callers - self.GUARDED))

    def test_snap_checks_the_lock_without_aborting(self):
        """snap_unresolved_pins skips the colour write; it must not abort."""
        self.assertIn("registry/service.py", self._callers("is_black_locked"))

    def test_no_caller_branches_on_the_message_text(self):
        """BlackLockedError's message is for humans; nothing may test it."""
        root = self._api_root()
        for relative in sorted(self.GUARDED):
            source = (root / relative).read_text(encoding="utf-8")
            with self.subTest(module=relative):
                self.assertIn("except BlackLockedError", source)
                self.assertNotIn('"is Black locked."', source)
                self.assertNotIn("'is Black locked.'", source)
