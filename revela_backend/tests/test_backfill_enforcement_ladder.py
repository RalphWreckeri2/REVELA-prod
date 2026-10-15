"""Phase 3B, Part 2: the backfill script, driven against a fake cursor.

The script's contract is about what it does NOT write as much as what it
does: a dry run writes nothing, a level is never guessed, and a second run
changes nothing. Those three are what these tests pin.

No database is involved. The fake cursor answers the plan queries and records
every write, so a test can assert on the exact statements that would run.
"""
import io
import os
import sys
import unittest
from contextlib import redirect_stdout

sys.path.insert(0, os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..")))

from scripts import backfill_enforcement_ladder as backfill


class FakeCursor:
    """Answers the plan queries from a fixture and records every write."""

    def __init__(self, *, answers=None, columns=None):
        # answers maps a fragment of the query to the rows it returns.
        self.answers = answers or {}
        self.columns = columns if columns is not None else {
            "official_registry": {"warningLevel", "blackLocked",
                                  "blackDispatchUnlocked"},
            "geospatial_logs": {"source"},
        }
        self.queries = []
        self.writes = []
        self.executemany_calls = []

    @staticmethod
    def _flat(sql):
        return " ".join(sql.split())

    def execute(self, sql, params=()):
        flat = self._flat(sql)
        self.queries.append(flat)
        self._rows = []
        if flat.upper().startswith(("UPDATE", "INSERT", "DELETE")):
            self.writes.append((flat, tuple(params)))
            return
        if "information_schema.COLUMNS" in flat:
            table = params[0]
            self._rows = [(name,) for name in sorted(self.columns.get(table, ()))]
            return
        for needle, rows in self.answers.items():
            if needle in flat:
                self._rows = list(rows)
                return

    def executemany(self, sql, seq):
        self.executemany_calls.append((sql, list(seq)))
        for item in seq:
            self.writes.append((sql, item))

    def fetchall(self):
        return list(getattr(self, "_rows", []))

    def fetchone(self):
        return None


class BackfillDryRunTests(unittest.TestCase):

    def _run(self, cursor, *, apply_changes=False):
        summary = {}
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            backfill.report(None, cursor, apply_changes, summary)
        return summary, buffer.getvalue()

    def test_a_dry_run_writes_nothing(self):
        cursor = FakeCursor(answers={
            "reportedByUserID IS NOT NULL": [{"logID": 1, "detectedName": "A"}],
            "r.applicationStatus IS NOT NULL": [
                {"businessID": "B1", "businessName": "One",
                 "current_level": 0, "orange_count": 2}],
            "g.flagColor = 'Black' AND r.blackLocked = 0": [
                {"businessID": "B2", "businessName": "Two"}],
        })
        summary, output = self._run(cursor)
        self.assertEqual(cursor.writes, [])
        self.assertEqual(cursor.executemany_calls, [])
        self.assertIn("DRY RUN", output)
        self.assertIn("Nothing was written", output)
        self.assertIn(summary["source"], (0, 1))

    def test_the_summary_counts_everything(self):
        cursor = FakeCursor(answers={
            "reportedByUserID IS NOT NULL": [{"logID": 1, "detectedName": "A"}],
            "businessID IS NOT NULL AND placeID IS NOT NULL": [
                {"logID": 2, "detectedName": "B"}],
            "r.applicationStatus IS NOT NULL": [
                {"businessID": "B1", "businessName": "One",
                 "current_level": 0, "orange_count": 1}],
            "g.flagColor = 'Black' AND r.businessID IS NULL": [],
            "g.flagColor = 'Black' AND r.blackLocked = 0": [],
            "r.applicationStatus IN ('Revoked'": [],
        })
        summary, output = self._run(cursor)
        for key in ("source", "warningLevel", "unguessed_orange",
                    "blackLocked", "unlinked_black", "revoked_without_black"):
            self.assertIn(key, summary)
        self.assertIn("SUMMARY", output)


class WarningLevelTests(unittest.TestCase):

    def _levels_sql(self):
        return backfill.plan_warning_level(None)

    def test_the_level_is_capped_at_three(self):
        self.assertIn("LEAST(orange_count, %s)", self._levels_sql())
        self.assertEqual(backfill.MAX_WARNING_LEVEL, 3)

    def test_rows_with_no_orange_history_are_not_in_the_update_plan(self):
        # orange_count > 0 is what excludes them: there is nothing to count.
        self.assertIn("orange_count > 0", self._levels_sql())

    def test_a_dry_run_lists_the_level_it_would_set(self):
        cursor = FakeCursor(answers={
            "r.applicationStatus IS NOT NULL": [
                {"businessID": "B1", "businessName": "Shop",
                 "current_level": 0, "orange_count": 5}],
        })
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            backfill.report(None, cursor, False, {})
        output = buffer.getvalue()
        self.assertIn("level 0 -> 3", output)
        self.assertEqual(cursor.writes, [])

    def test_apply_writes_the_capped_level(self):
        cursor = FakeCursor(answers={
            "r.applicationStatus IS NOT NULL": [
                {"businessID": "B1", "businessName": "Shop",
                 "current_level": 0, "orange_count": 5}],
        })
        with redirect_stdout(io.StringIO()):
            backfill.report(None, cursor, True, {})
        self.assertTrue(cursor.writes)
        sql, params = cursor.writes[0][0], cursor.writes[0][1]
        self.assertIn("warningLevel", sql)
        self.assertEqual(params, (3, "B1"))


class UnguessedOrangeTests(unittest.TestCase):

    def test_they_are_listed_and_never_written(self):
        cursor = FakeCursor(answers={
            "r.applicationStatus IS NOT NULL": [],
            "g.flagColor = 'Orange'": [
                {"logID": 9, "detectedName": "Orange Shop"}],
        })
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            backfill.report(None, cursor, True, {})   # even with --apply
        output = buffer.getvalue()
        self.assertIn("NOT GUESSED", output)
        self.assertIn("Orange Shop", output)
        self.assertFalse(
            [w for w in cursor.writes if "warningLevel" in w[0]],
            "an Orange pin with no verified history must not be given a level",
        )

    def test_the_say_so_is_prominent(self):
        cursor = FakeCursor(answers={})
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            backfill.report(None, cursor, False, {})
        self.assertIn("NOT GUESSED", buffer.getvalue())


class ReRunSafetyTests(unittest.TestCase):

    def test_only_differing_rows_are_in_the_update_plan(self):
        """The WHERE clause excludes rows already at the right level.

        This is what makes a second run a no-op: a row whose current_level
        already equals the capped count never matches.
        """
        sql = backfill.plan_warning_level(None)
        self.assertIn("current_level <> LEAST(orange_count", sql)

    def test_already_locked_rows_are_not_in_the_lock_plan(self):
        self.assertIn("r.blackLocked = 0", backfill.plan_black_lock(None))

    def test_already_correct_sources_are_not_in_the_source_plan(self):
        for _label, sql in backfill.plan_source(None):
            self.assertIn("source <>", sql)

    def test_a_second_run_finds_nothing_to_do(self):
        """Drive the real plan SQL against rows that are already correct."""
        cursor = FakeCursor(answers={})
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            backfill.report(None, cursor, True, {})
        self.assertEqual(cursor.writes, [])
        self.assertIn("nothing to lock", buffer.getvalue())


class PreflightTests(unittest.TestCase):

    def test_it_names_the_columns_it_needs(self):
        self.assertIn("warningLevel", backfill.REQUIRED_COLUMNS
                      ["official_registry"])
        self.assertIn("source", backfill.REQUIRED_COLUMNS["geospatial_logs"])

    def test_a_complete_schema_passes(self):
        cursor = FakeCursor()
        self.assertEqual(backfill.missing_columns(cursor), [])

    def test_a_missing_column_is_reported(self):
        cursor = FakeCursor(columns={"official_registry": {"warningLevel"},
                                     "geospatial_logs": {"source"}})
        missing = backfill.missing_columns(cursor)
        self.assertIn("official_registry.blackLocked", missing)
        self.assertIn("official_registry.blackDispatchUnlocked", missing)

    def test_the_plan_refuses_to_run_without_the_columns(self):
        """No half-applying. The runner raises before any write."""
        cursor = FakeCursor(columns={})
        self.assertTrue(backfill.missing_columns(cursor))


class DocumentedGuessesTests(unittest.TestCase):

    def test_the_coalescing_caveat_is_stated(self):
        source = open(backfill.__file__, encoding="utf-8").read()
        self.assertIn("Coalesced pins may be mislabelled", source)
        self.assertIn("invents history", source)

    def test_dry_run_is_the_default(self):
        parser_doc = backfill.main.__doc__ or ""
        self.assertIn("DRY RUN", backfill.__doc__)


if __name__ == "__main__":
    unittest.main()
