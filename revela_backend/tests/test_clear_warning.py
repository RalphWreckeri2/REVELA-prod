"""Clear Warning on registry-backed enforcement state.

Neither the colour logic nor _sync_flag_color is mocked. _clear_pin_mirror
runs the real shared builder against the real registry row; the tests read
the SQL that would have gone to the database rather than predicting a colour
from a copy of the rule.

Both column caches are reset per test: ladder_columns_available and
lock_column_available cache for the life of the process, so whichever test
touched them first would otherwise decide the answer for every test after it.
"""
from api.registry.locks import reset_lock_column_cache
from api.registry.colors import reset_ladder_column_cache
from api.registry import service as registry_service
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..")))


class LadderCursor:
    """A cursor that answers the statements Phase 3A issues.

    `columns` is what information_schema reports. `rows` maps a substring of a
    statement to the row fetchone should return. `pending` is the row the
    "is an inspection in flight" query returns. `rowcount` is what every
    UPDATE reports.
    """

    def __init__(self, *, columns=None, rows=None, pending=None,
                 rowcount=1, closed_ids=()):
        self.columns = set(columns if columns is not None else [
            "warningLevel", "warningBaseColor", "blackLocked",
            "warningClearedAt", "warningClearedBy", "warningClearReason",
            "blackDispatchUnlocked",
        ])
        self.rows = rows or {}
        self.pending = pending
        self.rowcount_value = rowcount
        self.calls = []
        self.lastrowid = 1

    @staticmethod
    def _flat(sql):
        return " ".join(sql.split())

    def execute(self, sql, params=()):
        self.calls.append((self._flat(sql), params))
        self.rowcount = self.rowcount_value

    def fetchone(self):
        flat = self.calls[-1][0] if self.calls else ""
        if "information_schema.COLUMNS" in flat:
            return None
        if "FROM inspection_reports ir" in flat:
            return self.pending
        for needle, value in self.rows.items():
            if needle in flat:
                return dict(value) if isinstance(value, dict) else value
        return None

    def fetchall(self):
        flat = self.calls[-1][0] if self.calls else ""
        if "information_schema.COLUMNS" in flat:
            return [(name,) for name in sorted(self.columns)]
        return []

    def close(self):
        pass

    def sqls(self, needle=None):
        return [sql for sql, _ in self.calls if needle is None or needle in sql]

    def writes(self, needle=None):
        return [s for s in self.sqls(needle)
                if s.upper().startswith(("UPDATE", "INSERT", "DELETE"))]


class Harness(unittest.TestCase):

    def setUp(self):
        reset_ladder_column_cache()
        reset_lock_column_cache()
        self.addCleanup(reset_ladder_column_cache)
        self.addCleanup(reset_lock_column_cache)

    def _clear(self, cursor, reason=None, user=2):
        with patch.object(registry_service, "mysql") as mock_mysql:
            mock_mysql.connection.cursor.return_value = cursor
            try:
                return registry_service.clear_warning(
                    "BIZ-1", user, reason)
            except (registry_service.RegistryLadderConflict,
                    registry_service.RegistryLadderUnavailable,
                    registry_service.RegistryNotFoundError) as exc:
                return None, exc

    def _unlock(self, cursor, reason=None, user=9):
        with patch.object(registry_service, "mysql") as mock_mysql:
            mock_mysql.connection.cursor.return_value = cursor
            try:
                return registry_service.unlock_black_dispatch(
                    "BIZ-1", user, reason)
            except (registry_service.RegistryLadderConflict,
                    registry_service.RegistryLadderUnavailable,
                    registry_service.RegistryNotFoundError) as exc:
                return None, exc

    @staticmethod
    def _row(**over):
        base = {"applicationStatus": "Active", "warningLevel": 2,
                "warningBaseColor": "Green",
                "blackLocked": 0, "warningClearedAt": None,
                "warningClearedBy": None, "warningClearReason": None,
                "blackDispatchUnlocked": 0}
        base.update(over)
        return base


# ── Clear Warning ────────────────────────────────────────────────────────────


class ClearWarningTests(Harness):

    def test_clears_the_level_and_stamps_the_record(self):
        cursor = LadderCursor(rows={
            "SELECT r.applicationStatus": self._row(warningLevel=2)})
        summary, error = self._clear(cursor, reason="repaired")
        self.assertIsNone(error)
        self.assertTrue(summary["warningCleared"])
        self.assertEqual(summary["previousWarningLevel"], 2)
        self.assertEqual(summary["warningLevel"], 0)
        update = [s for s in cursor.writes("UPDATE enforcement_state")
                  if "warningLevel = 0" in s]
        self.assertEqual(len(update), 1)
        self.assertIn("warningClearedAt = NOW()", update[0])
        self.assertIn("warningClearedBy = %s", update[0])
        self.assertIn("warningClearReason = %s", update[0])

    def test_writes_the_audit_row_with_both_levels(self):
        cursor = LadderCursor(rows={
            "SELECT r.applicationStatus": self._row(warningLevel=3)})
        self._clear(cursor, reason="fixed", user=42)
        events = cursor.writes("INSERT INTO enforcement_events")
        self.assertEqual(len(events), 1)
        sql, params = next((s, p) for s, p in cursor.calls
                           if "enforcement_events" in s)
        self.assertEqual(params[2], "warning_cleared")
        self.assertEqual(params[3], 42)
        self.assertEqual(params[4], "fixed")
        self.assertEqual(params[5], 3)   # previousLevel
        self.assertEqual(params[6], 0)   # newLevel

    def test_the_reason_is_optional(self):
        cursor = LadderCursor(rows={
            "SELECT r.applicationStatus": self._row(warningLevel=1)})
        summary, error = self._clear(cursor, reason=None)
        self.assertIsNone(error)
        self.assertTrue(summary["warningCleared"])

    def test_level_zero_is_refused(self):
        cursor = LadderCursor(rows={
            "SELECT r.applicationStatus": self._row(warningLevel=0)})
        summary, error = self._clear(cursor)
        self.assertIsNone(summary)
        self.assertIsInstance(error, registry_service.RegistryLadderConflict)
        self.assertIn("no warning to clear", str(error))

    def test_a_black_locked_business_is_refused(self):
        cursor = LadderCursor(rows={
            "SELECT r.applicationStatus": self._row(warningLevel=2,
                                                    blackLocked=1)})
        summary, error = self._clear(cursor)
        self.assertIsNone(summary)
        self.assertIsInstance(error, registry_service.RegistryLadderConflict)
        self.assertIn("Black locked", str(error))
        self.assertEqual(cursor.writes("UPDATE enforcement_state"), [])

    def test_missing_columns_refuse_closed(self):
        cursor = LadderCursor(columns=["applicationStatus", "warningLevel"])
        summary, error = self._clear(cursor)
        self.assertIsNone(summary)
        self.assertIsInstance(
            error, registry_service.RegistryLadderUnavailable)
        self.assertEqual(cursor.writes(), [])

    def test_a_row_that_will_not_update_is_refused_and_rolls_back(self):
        cursor = LadderCursor(
            rows={"SELECT r.applicationStatus": self._row(warningLevel=2)},
            rowcount=0)
        summary, error = self._clear(cursor)
        self.assertIsNone(summary)
        self.assertIsInstance(error, registry_service.RegistryLadderConflict)
        self.assertIn("could not be updated", str(error))

    def test_an_unknown_business_is_a_not_found(self):
        cursor = LadderCursor()
        summary, error = self._clear(cursor)
        self.assertIsInstance(error, registry_service.RegistryNotFoundError)


class ClearWarningInFlightTests(Harness):
    """An inspection that is not yet Verified blocks the clear."""

    def _cursor(self, status):
        return LadderCursor(
            rows={"SELECT r.applicationStatus": self._row(warningLevel=1)},
            pending={"reportID": 77, "verificationStatus": status})

    def test_every_non_verified_status_blocks(self):
        for status in ("Assigned", "Reassigned", "Submitted"):
            with self.subTest(status=status):
                summary, error = self._clear(self._cursor(status))
                self.assertIsNone(summary)
                self.assertIsInstance(
                    error, registry_service.RegistryLadderConflict)
                self.assertIn(status, str(error))

    def test_a_null_status_counts_as_not_verified(self):
        summary, error = self._clear(self._cursor(None))
        self.assertIsInstance(error,
                              registry_service.RegistryLadderConflict)

    def test_a_verified_inspection_does_not_block(self):
        cursor = LadderCursor(
            rows={"SELECT r.applicationStatus": self._row(warningLevel=1)},
            pending=None)
        summary, error = self._clear(cursor)
        self.assertIsNone(error)
        self.assertTrue(summary["warningCleared"])

    def test_the_message_names_the_report(self):
        _, error = self._clear(self._cursor("Submitted"))
        self.assertIn("#77", str(error))


class ClearWarningRestoresTheStatusColour(Harness):

    def test_the_pin_mirror_uses_the_shared_builder(self):
        cursor = LadderCursor(rows={
            "SELECT r.applicationStatus": self._row(warningLevel=1)})
        self._clear(cursor)
        pin = [s for s in cursor.writes("UPDATE geospatial_logs")]
        self.assertEqual(len(pin), 1)
        sql = pin[0]
        # The colour is not written as a literal: it is the shared expression.
        self.assertIn("g.noticeLevel = 0", sql)
        self.assertIn("SELECT r_chk.applicationStatus", sql)
        self.assertIn("= 'Active' THEN 'Green'", sql)
        self.assertIn("ELSE g.flagColor END", sql)
        # ...and the mirrored notice level goes to zero.
        self.assertNotIn("noticeLevel = %s", sql)

    def test_an_active_business_goes_back_to_green(self):
        """Proved by running the real builder, not by reading the SQL."""
        from api.registry.colors import _effective_flag_color_sql
        import re
        import sqlite3

        expression = _effective_flag_color_sql("g", ladder=False)
        status_lookup = re.compile(
            r"\(\s*SELECT\s+r_chk\.applicationStatus.*?LIMIT\s+1\s*\)",
            re.DOTALL)
        substituted = status_lookup.sub("'Active'", expression)
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
        try:
            con.execute(
                "INSERT INTO geospatial_logs VALUES (?,?,?,?,?,?)",
                (1, "BIZ-1", None, 7, "ACME", "Orange"))
            con.commit()
            colour = con.execute(
                f"SELECT ({substituted}) FROM geospatial_logs g").fetchone()[0]
        finally:
            con.close()
        self.assertEqual(colour, "Green")


class ClearWarningRouteTests(Harness):

    def _route(self, outcome, raiser=None):
        """`raiser` makes the service raise, which is how the service reports a
        refusal; without it the outcome tuple is returned directly."""
        from flask import Flask
        from api.registry import routes as registry_routes

        side_effect = raiser if raiser is not None else None
        with (
            patch.object(registry_routes, "clear_warning",
                         return_value=None if raiser else outcome,
                         side_effect=side_effect),
            patch.object(registry_routes, "get_jwt_identity", return_value=2),
        ):
            app = Flask(__name__)
            with app.test_request_context(
                    "/api/registry/BIZ-1/clear-warning", method="POST",
                    json={}):
                response = registry_routes.clear_warning_route.__wrapped__(
                    "BIZ-1")
        return response

    def test_a_refusal_answers_409_with_the_server_message(self):
        response = self._route(None, raiser=registry_service.RegistryLadderConflict(
            "This business is Black locked, so its warning cannot be cleared."))
        self.assertEqual(response[1], 409)
        body = response[0].get_json()
        self.assertEqual(body["code"], "warning_clear_refused")
        self.assertIn("Black locked", body["error"])

    def test_a_missing_schema_answers_409(self):
        response = self._route(
            None, raiser=registry_service.RegistryLadderUnavailable(
                "no ladder columns"))
        self.assertEqual(response[1], 409)

    def test_success_answers_200(self):
        response = self._route(({"warningCleared": True}, None))
        self.assertEqual(response[1], 200)

    def test_an_unknown_business_answers_404(self):
        response = self._route(
            None, raiser=registry_service.RegistryNotFoundError("nope"))
        self.assertEqual(response[1], 404)


if __name__ == "__main__":
    unittest.main()
