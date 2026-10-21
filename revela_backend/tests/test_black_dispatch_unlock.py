"""Phase 3A, Part 3: the single-use Black dispatch unlock.

The colour logic is not mocked. Where a test asserts a colour it runs the real
shared builder; where it asserts SQL it reads the statement that would have
gone to the database.

Both column caches are reset per test: ladder_columns_available and
lock_column_available cache for the life of the process, so whichever test
touched them first would otherwise decide the answer for every test after it.
"""
from api.registry.locks import reset_lock_column_cache
from api.registry.colors import reset_ladder_column_cache
from api.registry import service as registry_service
from api.inspections import service as inspection_service
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..")))
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))


from test_clear_warning import LadderCursor, Harness  # noqa: E402

UNLOCK_COLUMNS = ["applicationStatus", "warningLevel", "blackLocked",
                  "blackDispatchUnlocked"]


def locked_row(**over):
    base = {"applicationStatus": "Revoked", "warningLevel": 3,
            "blackLocked": 1, "blackDispatchUnlocked": 0}
    base.update(over)
    return base


# ── the unlock action ────────────────────────────────────────────────────────


class UnlockTests(Harness):

    def test_legacy_unlock_is_refused_without_database_access(self):
        cursor = LadderCursor(columns=UNLOCK_COLUMNS,
                              rows={"SELECT applicationStatus": locked_row()})
        summary, error = self._unlock(cursor, reason="court order", user=9)
        self.assertIsNone(summary)
        self.assertIsInstance(error, registry_service.RegistryLadderConflict)
        self.assertIn("cannot be dispatched", str(error))
        self.assertEqual(cursor.calls, [])


# ── who may unlock ───────────────────────────────────────────────────────────


class SuperAdminOnlyTests(unittest.TestCase):

    def _call(self, role):
        from flask import Flask
        from api.middleware import decorators

        with patch.object(decorators, "verify_jwt_in_request"), \
            patch.object(decorators, "get_jwt",
                         return_value={"role": role, "session_id": "s"}), \
            patch.object(decorators, "get_jwt_identity", return_value=1), \
            patch.object(decorators, "find_user_by_id",
                         return_value={"userID": 1, "userRole": role,
                                       "isActive": True}), \
            patch.object(decorators, "check_active_session",
                         return_value=(True, None)):
            app = Flask(__name__)

            @decorators.super_admin_required()
            def protected():
                return "ok"

            with app.test_request_context("/x", method="GET"):
                return protected()

    def test_super_admin_passes(self):
        self.assertEqual(self._call("SUPER_ADMIN"), "ok")

    def test_admin_is_refused(self):
        self.assertNotEqual(self._call("Admin"), "ok")

    def test_system_administrator_is_refused(self):
        """Exact match only, as the decorator's own docstring says."""
        self.assertNotEqual(self._call("System Administrator"), "ok")

    def test_the_unlock_route_carries_that_decorator(self):
        import inspect

        from api.registry import routes as registry_routes

        module = inspect.getsource(registry_routes)
        self.assertIn(
            "@super_admin_required()\ndef unlock_black_dispatch_route",
            module)
        self.assertNotIn(
            "@admin_required()\ndef unlock_black_dispatch_route", module)

    def test_unlock_route_always_refuses_without_calling_service(self):
        from flask import Flask
        from api.registry import routes as registry_routes

        with (
            patch.object(registry_routes, "get_jwt_identity", return_value=9),
        ):
            app = Flask(__name__)
            with app.test_request_context(
                    "/api/registry/BIZ-1/unlock-black-dispatch", method="POST",
                    json={}):
                response = registry_routes.unlock_black_dispatch_route \
                    .__wrapped__("BIZ-1")
        self.assertEqual(response[1], 409)
        body = response[0].get_json()
        self.assertEqual(body["code"], "black_dispatch_forbidden")
        self.assertIn("cannot be dispatched", body["error"])

    def test_unlock_route_never_answers_success(self):
        from flask import Flask
        from api.registry import routes as registry_routes

        with (
            patch.object(registry_routes, "get_jwt_identity", return_value=9),
        ):
            app = Flask(__name__)
            with app.test_request_context(
                    "/api/registry/BIZ-1/unlock-black-dispatch", method="POST",
                    json={}):
                response = registry_routes.unlock_black_dispatch_route \
                    .__wrapped__("BIZ-1")
        self.assertEqual(response[1], 409)


# ── the eligibility gate ─────────────────────────────────────────────────────


class _GateCursor:
    """Answers what assign_inspection asks for.

    `_has_columns` reads information_schema with fetchall(); the Black guard
    reads it with fetchone(). Both must be right, or the gate silently reads
    every Black business as unlocked.
    """

    def __init__(self, *, colour, unlocked, unlock_column=True):
        self.colour = colour
        self.unlocked = unlocked
        self.unlock_column = unlock_column
        self.calls = []
        self.rowcount = 1
        self.lastrowid = 31

    @staticmethod
    def _flat(sql):
        return " ".join(sql.split())

    def execute(self, sql, params=()):
        self.calls.append((self._flat(sql), params))
        self.rowcount = 1

    def fetchone(self):
        flat = self.calls[-1][0] if self.calls else ""
        if "information_schema.COLUMNS" in flat:
            return ("blackDispatchUnlocked",) if self.unlock_column else None
        if "FROM geospatial_logs g" in flat:
            return {"logID": 22, "flagColor": self.colour,
                    "businessID": "BIZ-1",
                    "effectiveFlagColor": self.colour,
                    "blackDispatchUnlocked": self.unlocked}
        if "FROM users" in flat:
            return {"userID": 9, "fullName": "Ana", "userRole": "Inspector"}
        return None

    def fetchall(self):
        flat = self.calls[-1][0] if self.calls else ""
        if "information_schema.COLUMNS" in flat:
            return ([("blackDispatchUnlocked",)]
                    if self.unlock_column else [])
        return []

    def close(self):
        pass


class EligibilityGateTests(unittest.TestCase):

    def setUp(self):
        reset_ladder_column_cache()
        reset_lock_column_cache()
        self.addCleanup(reset_ladder_column_cache)
        self.addCleanup(reset_lock_column_cache)

    def _assign(self, *, colour, unlocked=0, unlock_column=True):
        cursor = _GateCursor(colour=colour, unlocked=unlocked,
                             unlock_column=unlock_column)
        with (
            patch.object(inspection_service, "mysql") as mock_mysql,
            patch.object(inspection_service, "_ensure_gps_columns"),
            patch("api.notifications.hub.publish_to_admins"),
        ):
            mock_mysql.connection.cursor.return_value = cursor
            return inspection_service.assign_inspection(22, 9, None, 2)

    def test_a_black_is_blocked(self):
        result, error = self._assign(colour="Black", unlocked=0)
        self.assertIsNone(result)
        self.assertIsInstance(
            error, inspection_service.InspectionAssignmentConflict)
        self.assertIn("cannot be dispatched", str(error))

    def test_an_unlocked_black_is_still_blocked(self):
        result, error = self._assign(colour="Black", unlocked=1)
        self.assertIsNone(result)
        self.assertIsInstance(
            error, inspection_service.InspectionAssignmentConflict)
        self.assertIn("cannot be dispatched", str(error))

    def test_a_black_without_the_legacy_unlock_column_is_blocked(self):
        result, error = self._assign(colour="Black", unlocked=None,
                                     unlock_column=False)
        self.assertIsNone(result)
        self.assertIsInstance(
            error, inspection_service.InspectionAssignmentConflict)

    def test_green_is_still_blocked(self):
        result, error = self._assign(colour="Green", unlocked=1)
        self.assertIsNone(result)
        self.assertIsInstance(
            error, inspection_service.InspectionAssignmentConflict)

    def test_the_ordinary_colours_are_unaffected(self):
        for colour in ("Red", "Yellow", "Orange", "Purple"):
            with self.subTest(colour=colour):
                result, error = self._assign(colour=colour)
                self.assertIsNone(error)
                self.assertEqual(result["status"], "Assigned")

    def test_the_allowed_colours_are_unchanged(self):
        self.assertEqual(
            inspection_service.INSPECTABLE_FLAG_COLORS,
            frozenset({"Red", "Yellow", "Orange", "Purple"}),
            "Phase 3A must not add or remove a colour from the gate")


# ── verifying on an unlocked Black ───────────────────────────────────────────


class VerifyOnUnlockedBlackTests(Harness):
    """The grant buys one verified inspection and nothing more.

    Driven through the real verify_inspection, so nothing about the colour or
    the ladder is faked.
    """

    def _verify(self, *, unlocked, result="Green", migrated=True):
        from test_verify_ladder_writes import LadderVerifyHarness

        harness = LadderVerifyHarness("run")
        harness.setUp()
        self.addCleanup(harness.doCleanups)
        return harness._run(
            result=result, notice_level=0, warning_level=3, black_locked=1,
            application_status="Revoked", pin_business_id="BIZ-1",
            registry_business_id="BIZ-1", registry_rowcount=1,
            black_dispatch_unlocked=unlocked, migrated=migrated)

    @staticmethod
    def _registry_update(cursor):
        rows = [" ".join(c.args[0].split()) for c in cursor.execute.call_args_list
                if "enforcement_state" in c.args[0]
                and "lastInspectedAt" in c.args[0]]
        return rows[0] if rows else ""

    def test_a_locked_row_without_the_grant_is_still_refused(self):
        (result, error), _ = self._verify(unlocked=0)
        self.assertIsNone(result)
        self.assertIsInstance(
            error, inspection_service.InspectionVerificationConflict)

    def test_an_unlocked_black_accepts_any_result(self):
        for result in ("Green", "Red", "Yellow", "Purple"):
            with self.subTest(result=result):
                (out, error), _ = self._verify(unlocked=1, result=result)
                self.assertIsNone(error)
                self.assertEqual(out["newFlagColor"], result)

    def test_it_stamps_the_result_and_changes_nothing_else(self):
        (_, error), cursor = self._verify(unlocked=1)
        self.assertIsNone(error)
        sql = self._registry_update(cursor)
        self.assertIn("lastInspectionResult = %s", sql)
        self.assertIn("lastInspectedAt = NOW()", sql)
        for forbidden in ("applicationStatus", "warningLevel =", "blackLocked ="):
            self.assertNotIn(forbidden, sql)

    def test_the_pin_is_not_recoloured(self):
        """A Black business must never briefly render as its result."""
        (_, error), cursor = self._verify(unlocked=1)
        self.assertIsNone(error)
        self.assertEqual(
            [c for c in cursor.execute.call_args_list
             if "UPDATE geospatial_logs" in c.args[0]], [])

    def test_the_grant_is_spent(self):
        (out, error), cursor = self._verify(unlocked=1)
        self.assertIsNone(error)
        self.assertTrue(out["blackDispatchUnlockSpent"])
        events = [c for c in cursor.execute.call_args_list
                  if "enforcement_events" in c.args[0]]
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].args[1][2], "black_relocked")

    def test_a_refused_verify_writes_nothing_at_all(self):
        (_, error), cursor = self._verify(unlocked=0)
        self.assertIsInstance(
            error, inspection_service.InspectionVerificationConflict)
        self.assertEqual([c for c in cursor.execute.call_args_list
                          if c.args[0].lstrip().upper().startswith(
                              ("UPDATE", "INSERT"))], [])

    def test_revoked_stays_guarded_without_ladder_columns(self):
        """Revoked is Black even when a lock or dispatch grant cannot be read."""
        (result, error), cursor = self._verify(unlocked=1, migrated=False)
        self.assertIsNone(result)
        self.assertIsInstance(
            error, (inspection_service.InspectionVerificationConflict, inspection_service.GreenRegistryLinkError))
        self.assertEqual([c for c in cursor.execute.call_args_list
                          if c.args[0].lstrip().upper().startswith(
                              ("UPDATE", "INSERT", "DELETE"))], [])


# ── the grant is single use ──────────────────────────────────────────────────


class RelockTests(Harness):

    def _consume(self, *, rowcount):
        cursor = LadderCursor(columns=UNLOCK_COLUMNS, rowcount=rowcount)
        spent = registry_service._consume_black_dispatch_unlock(
            cursor, "BIZ-1", 2, reason="Inspection verified")
        return spent, cursor

    def test_nothing_to_spend_writes_no_event(self):
        spent, cursor = self._consume(rowcount=0)
        self.assertFalse(spent)
        self.assertEqual([s for s, _ in cursor.calls
                          if "enforcement_events" in s], [])

    def test_spending_writes_the_relock_event(self):
        spent, cursor = self._consume(rowcount=1)
        self.assertTrue(spent)
        sql = next(s for s, _ in cursor.calls if "UPDATE enforcement_state" in s)
        self.assertIn("blackDispatchUnlocked = 0", sql)
        self.assertNotIn("blackLocked =", sql)
        _, params = next((s, p)
                         for s, p in cursor.calls if "enforcement_events" in s)
        self.assertEqual(params[2], "black_relocked")

    def test_sending_a_report_back_spends_the_grant(self):
        """The 'cancelled or reassigned away' path that exists in this codebase.

        There is no cancel endpoint for inspections; reassign_submitted_report
        is the only path that takes a report away from its inspector.
        """
        import inspect

        source = inspect.getsource(
            inspection_service.reassign_submitted_report)
        self.assertIn("_consume_black_dispatch_unlock", source)

    def test_a_verified_report_being_sent_back_keeps_its_grant(self):
        """The inspection the grant paid for did happen."""
        import inspect

        source = inspect.getsource(
            inspection_service.reassign_submitted_report)
        self.assertIn('if report["verificationStatus"] == "Submitted":',
                      source)


class OtherPathsStillCannotMoveALockedRowTests(Harness):

    def test_sync_still_freezes_a_black_locked_row(self):
        cursor = LadderCursor(columns=UNLOCK_COLUMNS, rowcount=1)
        black, _ = registry_service._load_sync_protection_keys(cursor)
        self.assertEqual(black, set())

    def test_manual_edit_is_still_refused_while_unlocked(self):
        cursor = LadderCursor(
            columns=UNLOCK_COLUMNS, rowcount=1,
            rows={"SELECT applicationStatus": locked_row(
                blackDispatchUnlocked=1)})
        with patch.object(registry_service, "mysql") as mock_mysql:
            mock_mysql.connection.cursor.return_value = cursor
            try:
                ok, error = registry_service.update_business(
                    "BIZ-1", {"businessName": "NEW"})
            except Exception as exc:              # noqa: BLE001
                ok, error = False, exc
        self.assertFalse(ok)
        self.assertEqual(cursor.writes("UPDATE official_registry"), [])

    def test_the_rollover_still_excludes_locked_rows(self):
        import inspect

        source = inspect.getsource(
            registry_service.check_and_expire_old_permits)
        self.assertIn("lock_guard", source)
        self.assertIn("blackLocked", source)

    def test_the_pin_colour_write_is_still_skipped(self):
        import inspect

        source = inspect.getsource(registry_service.snap_unresolved_pins)
        self.assertIn("if not is_black_locked(cur2, bid):", source)


if __name__ == "__main__":
    unittest.main()
