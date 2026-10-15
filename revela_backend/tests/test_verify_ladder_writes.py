"""Phase 2, Part 2: verify_inspection writes the enforcement ladder.

The colour logic is not mocked here. Where a test needs the derived colour it
uses the same SQLite substitution technique as
tests/test_analytics_flag_colour_filter.py: the correlated registry lookups
are replaced with the values a database would supply, and every CASE arm is
executed as shipped.

What is faked is the cursor, because there is no test database in this
project. The fake is a small SQL router: it answers the information_schema
probe, the report read, the registry read and the enforcement-event insert,
and it records every statement so the tests can assert on the SQL that would
have run.
"""
from api.registry.locks import reset_lock_column_cache
from api.registry.colors import reset_ladder_column_cache
from api.inspections.service import InspectionVerificationConflict
from api.inspections import service as inspection_service
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..")))


class LadderVerifyHarness(unittest.TestCase):
    """A fake cursor that understands the verify_inspection statement set."""

    def setUp(self):
        reset_ladder_column_cache()
        reset_lock_column_cache()
        self.addCleanup(reset_ladder_column_cache)
        self.addCleanup(reset_lock_column_cache)

    def _run(self, *, result, notice_level=0, ladder=True,
             pin_business_id="BIZ-1", registry_business_id="BIZ-1",
             warning_level=0, black_locked=0, application_status="Active",
             admin_user_id=2, registry_rowcount=1, black_dispatch_unlocked=0,
             migrated=True):
        cursor = MagicMock()
        cursor.lastrowid = 1
        # One router for both execute and fetchone, so a statement and the
        # row it returns can never drift apart.
        matched = {"has_row": False, "rowcount": 1, "state_subject": None}

        def classify(sql):
            flat = " ".join(sql.split())
            if "information_schema.COLUMNS" in flat:
                return "probe"
            if "information_schema.TABLES" in flat:
                return "table_probe"
            if "FROM inspection_reports ir" in flat:
                return "report"
            if "LEFT JOIN enforcement_state es" in flat and "FROM official_registry r" in flat:
                return "lock_read"
            if flat.startswith("SELECT applicationStatus"):
                return "registry_read"
            if "FROM enforcement_state" in flat and flat.startswith("SELECT"):
                return "state_read"
            if "SELECT flagColor, noticeLevel FROM geospatial_logs" in flat:
                return "pin_colour"
            if "UPDATE official_registry" in flat:
                return "registry_write"
            if "INSERT INTO enforcement_state" in flat:
                return "state_write"
            return "other"

        def execute(sql, params=()):
            kind = classify(sql)
            matched["has_row"] = False
            if kind == "probe":
                cursor.fetchall.return_value = (
                    [("warningLevel",), ("blackLocked",),
                     ("blackDispatchUnlocked",)] if (ladder and migrated)
                    else [])
                return
            if kind == "table_probe":
                cursor.fetchone.return_value = {
                    "TABLE_NAME": "enforcement_state"} if migrated else None
                return
            if kind == "state_read":
                matched["state_subject"] = params[0]
                return
            if kind in ("report", "registry_read", "lock_read", "pin_colour"):
                matched["has_row"] = True
                return
            matched["rowcount"] = (
                registry_rowcount if kind == "registry_write" else 1)
            cursor.rowcount = matched["rowcount"]

        def fetchone():
            kind = classify(cursor.execute.call_args.args[0])
            has_row = registry_business_id == pin_business_id
            if kind == "probe":
                # locks.lock_column_available() probes information_schema with
                # fetchone(). If this returns None the guard reads the column
                # as absent, and every Black refusal test silently passes for
                # the wrong reason.
                return ("blackLocked",) if migrated else None
            if kind == "table_probe":
                return {"TABLE_NAME": "enforcement_state"} if migrated else None
            if kind == "state_read":
                subject_id = matched["state_subject"]
                if subject_id == str(pin_business_id):
                    return {
                        "warningLevel": warning_level,
                        "blackLocked": black_locked,
                        "blackDispatchUnlocked": black_dispatch_unlocked,
                        "warningBaseColor": "Red",
                    }
                return None
            if kind == "report":
                return {
                    "reportID": 4, "targetID": 22, "userID": 9,
                    "inspectionResult": result, "noticeLevel": notice_level,
                    "verificationStatus": "Submitted",
                    "verifiedLatitude": None, "verifiedLongitude": None,
                    "verifiedAccuracy": None, "nearestLandmark": None,
                    "detectedName": "Warned Shop", "barangayID": 1,
                    "businessID": pin_business_id,
                }
            if kind == "pin_colour":
                return {"flagColor": "Red", "noticeLevel": 0}
            if kind == "lock_read":
                return {"blackLocked": black_locked,
                        "applicationStatus": application_status} if has_row else None
            if kind == "registry_read":
                if not has_row:
                    return None
                return {"applicationStatus": application_status}
            return None

        cursor.execute.side_effect = execute
        cursor.fetchone.side_effect = fetchone
        cursor.rowcount = 1

        with (
            patch.object(inspection_service, "mysql") as mock_mysql,
            patch.object(inspection_service, "_ensure_gps_columns"),
            patch.object(inspection_service, "get_latest_inspection_cycle_id",
                         return_value=None),
            patch.object(inspection_service, "log_inspection_event"),
            patch("api.notifications.hub.publish_to_admins"),
        ):
            mock_mysql.connection.cursor.return_value = cursor
            outcome = inspection_service.verify_inspection(
                4, verified_by_user_id=admin_user_id)
        return outcome, cursor

    # ── helpers over the recorded statements ─────────────────────────────────

    @staticmethod
    def _statements(cursor, needle):
        return [(" ".join(c.args[0].split()), c.args[1] if len(c.args) > 1 else ())
                for c in cursor.execute.call_args_list if needle in c.args[0]]

    @classmethod
    def _registry_update(cls, cursor):
        rows = [s for s in cls._statements(cursor, "INSERT INTO enforcement_state")
                if "lastInspectionResult" in s[0]]
        return rows[0] if rows else None

    @classmethod
    def _events(cls, cursor):
        return cls._statements(cursor, "INSERT INTO enforcement_events")

    @classmethod
    def _pin_update(cls, cursor):
        return cls._statements(cursor, "UPDATE geospatial_logs")[0]


# ── the ladder advances one step at a time ───────────────────────────────────


class OrangeLadderTests(LadderVerifyHarness):

    def test_zero_to_one_then_two_then_three(self):
        for current, submitted in ((0, 1), (1, 2), (2, 3)):
            with self.subTest(warning_level=current, notice_level=submitted):
                (result, error), cursor = self._run(
                    result="Orange", notice_level=submitted,
                    warning_level=current)
                self.assertIsNone(error)
                sql, params = self._registry_update(cursor)
                self.assertIn("warningLevel = VALUES(warningLevel)", sql)
                self.assertIn(submitted, params)
                self.assertTrue(result["registryUpdated"])

    def test_a_skipped_step_is_refused_with_409(self):
        for current, submitted in ((0, 2), (0, 3), (1, 3), (2, 1)):
            with self.subTest(warning_level=current, notice_level=submitted):
                (result, error), cursor = self._run(
                    result="Orange", notice_level=submitted,
                    warning_level=current)
                self.assertIsNone(result)
                self.assertIsInstance(error, InspectionVerificationConflict)
                self.assertIn("must be level", str(error))

    def test_a_level_outside_one_to_three_is_refused(self):
        for submitted in (0, 4, -1, 99):
            with self.subTest(notice_level=submitted):
                (result, error), _ = self._run(
                    result="Orange", notice_level=submitted, warning_level=0)
                self.assertIsNone(result)
                self.assertIsInstance(error, InspectionVerificationConflict)
                self.assertIn("1, 2 or 3", str(error))

    def test_a_refused_orange_writes_nothing(self):
        (result, error), cursor = self._run(
            result="Orange", notice_level=3, warning_level=0)
        self.assertIsInstance(error, InspectionVerificationConflict)
        # No report update, no pin update, no registry update, no event.
        self.assertEqual(self._statements(
            cursor, "UPDATE inspection_reports"), [])
        self.assertEqual(self._statements(
            cursor, "UPDATE geospatial_logs"), [])
        self.assertEqual(self._registry_update(cursor), None)
        self.assertEqual(self._events(cursor), [])

    def test_orange_leaves_application_status_untouched(self):
        (result, error), cursor = self._run(
            result="Orange", notice_level=1, warning_level=0,
            application_status="Active")
        self.assertIsNone(error)
        sql, _ = self._registry_update(cursor)
        self.assertNotIn("applicationStatus", sql)

    def test_orange_mirrors_the_level_onto_the_pin(self):
        (result, error), cursor = self._run(
            result="Orange", notice_level=2, warning_level=1)
        self.assertIsNone(error)
        self.assertEqual(self._pin_update(cursor)[1], ("Orange", 2, 22))

    def test_orange_records_a_warning_issued_event(self):
        (result, error), cursor = self._run(
            result="Orange", notice_level=1, warning_level=0,
            admin_user_id=42)
        self.assertIsNone(error)
        events = self._events(cursor)
        self.assertEqual(len(events), 1)
        params = events[0][1]
        self.assertEqual(params[0], "business")
        self.assertEqual(params[1], "BIZ-1")
        self.assertEqual(params[2], "warning_issued")
        self.assertEqual(params[3], 42)
        self.assertEqual(params[5], 0)   # previousLevel
        self.assertEqual(params[6], 1)   # newLevel

    def test_non_orange_non_black_after_warning_clears_and_records_event(self):
        for result in ("Red", "Yellow", "Green", "Purple"):
            with self.subTest(result=result):
                (_, error), cursor = self._run(
                    result=result, warning_level=2, admin_user_id=42)
                self.assertIsNone(error)
                sql, params = self._registry_update(cursor)
                self.assertIn("warningLevel = 0", sql)
                self.assertIn("warningBaseColor = NULL", sql)
                self.assertIn(
                    "warningClearedAt = VALUES(warningClearedAt)", sql)
                self.assertIn(
                    "warningClearedBy = VALUES(warningClearedBy)", sql)
                self.assertIn(42, params)
                events = self._events(cursor)
                self.assertEqual(len(events), 1)
                self.assertEqual(events[0][1][2], "warning_cleared")
                self.assertEqual(events[0][1][3], 42)
                self.assertEqual(events[0][1][5], 2)
                self.assertEqual(events[0][1][6], 0)
                self.assertEqual(
                    events[0][1][4],
                    f"Cleared by verified {result} inspection",
                )

    def test_every_registered_verify_stamps_the_last_result(self):
        for result, level, current in (("Red", 0, 0), ("Yellow", 0, 0),
                                       ("Green", 0, 0), ("Orange", 2, 1),
                                       ("Black", 4, 0)):
            with self.subTest(result=result):
                (_, error), cursor = self._run(
                    result=result, notice_level=level, warning_level=current)
                self.assertIsNone(error)
                sql, params = self._registry_update(cursor)
                self.assertIn(
                    "lastInspectionResult = VALUES(lastInspectionResult)", sql)
                self.assertIn("lastInspectedAt = NOW()", sql)
                self.assertIn(result, params)


# ── Black ────────────────────────────────────────────────────────────────────


class BlackLockWriteTests(LadderVerifyHarness):

    def test_black_result_locks_the_row(self):
        (result, error), cursor = self._run(
            result="Black", notice_level=4, black_locked=0, admin_user_id=7)
        self.assertIsNone(error)
        sql, params = self._registry_update(cursor)
        self.assertIn("blackLocked = 1", sql)
        self.assertIn("blackLockedAt = NOW()", sql)
        self.assertIn("blackLockedBy = VALUES(blackLockedBy)", sql)
        self.assertIn(7, params)
        self.assertNotIn("applicationStatus", sql)
        self.assertTrue(result["registryUpdated"])

    def test_black_does_not_need_a_notice_level_of_four(self):
        """A Black result locks even if the phone sent level 0."""
        (result, error), cursor = self._run(
            result="Black", notice_level=0, black_locked=0)
        self.assertIsNone(error)
        self.assertIn("blackLocked = 1", self._registry_update(cursor)[0])

    def test_black_records_a_black_locked_event(self):
        (result, error), cursor = self._run(
            result="Black", notice_level=4, black_locked=0, admin_user_id=9)
        self.assertIsNone(error)
        events = self._events(cursor)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0][1][2], "black_locked")
        self.assertEqual(events[0][1][3], 9)
        self.assertEqual(events[0][1][7], 0)   # previousBlack
        self.assertEqual(events[0][1][8], 1)   # newBlack


# ── the plain statuses ───────────────────────────────────────────────────────


class StatusWriteTests(LadderVerifyHarness):

    def test_red_yellow_green_map_to_the_right_status(self):
        for result, expected in (("Red", "Expired"), ("Yellow", "Pending"),
                                 ("Green", "Active")):
            with self.subTest(result=result):
                (out, error), cursor = self._run(result=result)
                self.assertIsNone(error)
                updates = self._statements(cursor, "UPDATE official_registry")
                self.assertTrue(updates)
                self.assertIn("applicationStatus = %s", updates[0][0])
                self.assertIn(expected, updates[0][1])
                self.assertTrue(out["registryUpdated"])

    def test_purple_still_closes(self):
        (result, error), cursor = self._run(result="Purple")
        self.assertIsNone(error)
        closed = [s for s in self._statements(cursor, "UPDATE official_registry")
                  if "'Closed'" in s[0]]
        self.assertEqual(len(closed), 1)
        self.assertTrue(result["registryClosed"])

    def test_an_unregistered_pin_writes_only_to_the_pin(self):
        (result, error), cursor = self._run(
            result="Green", pin_business_id=None, registry_business_id=None)
        self.assertIsNone(error)
        self.assertEqual(self._statements(
            cursor, "UPDATE official_registry"), [])
        self.assertEqual(self._events(cursor), [])
        self.assertEqual(self._pin_update(cursor)[1], ("Green", 0, 22))

    def test_an_unregistered_orange_pin_still_verifies(self):
        """No registry row means no ladder, so there is no level to check."""
        (result, error), cursor = self._run(
            result="Orange", notice_level=1,
            pin_business_id=None, registry_business_id=None)
        self.assertIsNone(error)
        self.assertEqual(result["newFlagColor"], "Orange")
        self.assertEqual(self._statements(
            cursor, "UPDATE official_registry"), [])

    def test_a_row_that_cannot_be_updated_warns_but_does_not_fail(self):
        """The warn-don't-fail contract, same as the Purple fix."""
        (result, error), cursor = self._run(
            result="Green", registry_rowcount=0)
        self.assertIsNone(error)
        self.assertFalse(result["registryUpdated"])
        self.assertIn("could not be updated", result["registryWarning"])


# ── fail closed when the ladder is not there ─────────────────────────────────


class UnmigratedDatabaseTests(LadderVerifyHarness):

    def test_orange_and_black_are_refused_without_the_ladder_columns(self):
        for result, level in (("Orange", 1), ("Black", 4)):
            with self.subTest(result=result):
                (out, error), cursor = self._run(
                    result=result, notice_level=level, ladder=False)
                self.assertIsNone(out)
                self.assertIsInstance(error, InspectionVerificationConflict)
                self.assertIn("migration", str(error))

    def test_the_refusal_writes_nothing(self):
        (_, error), cursor = self._run(
            result="Orange", notice_level=1, ladder=False)
        self.assertIsInstance(error, InspectionVerificationConflict)
        self.assertEqual(self._statements(
            cursor, "UPDATE inspection_reports"), [])
        self.assertEqual(self._statements(
            cursor, "UPDATE geospatial_logs"), [])

    def test_the_other_results_still_verify(self):
        for result in ("Red", "Yellow", "Green", "Purple"):
            with self.subTest(result=result):
                (out, error), _ = self._run(result=result, ladder=False)
                self.assertIsNone(error)
                self.assertEqual(out["newFlagColor"], result)

    def test_an_unregistered_orange_pin_is_still_refused(self):
        """The lock has nowhere to go even for a pin with no registry row."""
        (out, error), _ = self._run(
            result="Orange", notice_level=1, ladder=False,
            pin_business_id=None, registry_business_id=None)
        self.assertIsNone(out)
        self.assertIsInstance(error, InspectionVerificationConflict)


class VerificationConflictSurfacingTests(unittest.TestCase):
    """The route must answer 409, not 400 or 500."""

    def _call_verify(self, outcome):
        from flask import Flask
        from api.inspections import routes as inspections_routes

        with (
            patch.object(inspections_routes, "verify_inspection",
                         return_value=outcome),
            patch.object(inspections_routes,
                         "get_jwt_identity", return_value=2),
        ):
            app = Flask(__name__)
            with app.test_request_context(
                    "/api/inspections/4/verify", method="POST", json={}):
                return inspections_routes.verify.__wrapped__(4)

    def test_route_maps_the_conflict_to_409(self):
        response = self._call_verify((None, InspectionVerificationConflict(
            "This business is at warning level 1, so the next Orange must be "
            "level 2. This report carries level 3.")))
        self.assertEqual(response[1], 409)
        body = response[0].get_json()
        self.assertEqual(body["code"], "inspection_verification_conflict")
        self.assertIn("warning level 1", body["error"])

    def test_a_plain_error_is_still_400(self):
        response = self._call_verify(
            (None, "Report has no inspection result"))
        self.assertEqual(response[1], 400)


if __name__ == "__main__":
    unittest.main()
