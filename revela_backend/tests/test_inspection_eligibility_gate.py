"""Regression tests: server-side inspection eligibility.

assign_inspection previously accepted any pin. Eligibility is now decided on
the effective colour - the same _effective_flag_color_sql expression the Map
renders - so a stale pin cannot make an ineligible business look eligible.

These tests do not mock the colour logic. As with the analytics filter test,
SQLite cannot bind a correlated reference inside a subquery ORDER BY, so only
the registry-status lookup is substituted, with the value the row resolves to.
Every CASE arm, its precedence and the ELSE <stored colour> fallback are the
shipped expression.
"""
from api.registry.colors import _effective_flag_color_sql
from api.inspections import service as inspection_service
from api.inspections import routes as inspections_routes
from flask import Flask
import os
import re
import sqlite3
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..")))


_STATUS_LOOKUP = re.compile(
    r"\(\s*SELECT\s+r_chk\.applicationStatus.*?LIMIT\s+1\s*\)", re.DOTALL)
_LOCK_LOOKUP = re.compile(
    r"\(\s*SELECT\s+r_chk\.blackLocked.*?LIMIT\s+1\s*\)", re.DOTALL)
_WARNING_LOOKUP = re.compile(
    r"\(\s*SELECT\s+r_chk\.warningLevel.*?LIMIT\s+1\s*\)", re.DOTALL)

INSPECTOR = {"userID": 9, "fullName": "Inspector", "userRole": "Inspector"}


def _sqlite_registry_status(status):
    """Run the real expression for one row, standing in for the registry."""
    expression = _effective_flag_color_sql("g")
    substituted = _STATUS_LOOKUP.sub(
        lambda m: "NULL" if status is None else "'%s'" % status, expression)
    substituted = _LOCK_LOOKUP.sub("0", substituted)
    substituted = _WARNING_LOOKUP.sub("0", substituted)
    # Assert the substitution covered every correlated lookup, not how many
    # there were. The old "expected 5" check counted textual occurrences - one
    # per CASE arm - so a new arm broke this test with no behaviour change.
    if "SELECT r_chk." in substituted:
        raise AssertionError(
            "a correlated registry lookup was not substituted; the shared "
            "builder grew a lookup this helper does not cover:\n%s" % substituted)
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
            (22, "BIZ-1", None, 7, "ACME STORE", ""))
        row = con.execute(
            f"SELECT ({substituted}) FROM geospatial_logs g").fetchone()
        return row[0]
    finally:
        con.close()


class _AssignBase(unittest.TestCase):

    def _assign(self, stored_color, registry_status, *, business_id="BIZ-1",
                place_id=None, open_status=None, expected_barangay_id=None):
        effective = _sqlite_registry_status(registry_status)
        cursor = MagicMock()
        cursor.lastrowid = 31

        def fetchone():
            call = cursor.execute.call_args
            sql = call.args[0] if call else ""
            if "FROM geospatial_logs g" in sql and "WHERE g.logID = %s" in sql:
                return {"logID": 22, "flagColor": stored_color,
                        "effectiveFlagColor": effective}
            if "FROM users" in sql:
                return dict(INSPECTOR)
            if "FROM inspection_reports" in sql:
                if open_status:
                    return {"reportID": 7,
                            "verificationStatus": open_status}
                return None
            return None

        cursor.fetchone.side_effect = fetchone
        self.last_cursor = cursor
        with (
            patch.object(inspection_service, "mysql") as mock_mysql,
            patch.object(inspection_service, "_ensure_gps_columns"),
            patch.object(inspection_service,
                         "get_latest_inspection_cycle_id", return_value=None),
            patch.object(inspection_service, "log_inspection_event"),
            patch("api.notifications.hub.publish_to_admins"),
        ):
            mock_mysql.connection.cursor.return_value = cursor
            return inspection_service.assign_inspection(
                log_id=22, inspector_user_id=9, deadline=None, assigned_by=2,
                expected_barangay_id=expected_barangay_id)


class EligibilityGateTests(_AssignBase):

    def test_green_pin_is_blocked(self):
        result, error = self._assign("Green", "Active")
        self.assertIsNone(result)
        self.assertIsInstance(error,
                              inspection_service.InspectionAssignmentConflict)
        self.assertIn("Green (registered)", str(error))

    def test_black_pin_is_blocked(self):
        result, error = self._assign("Black", "Revoked")
        self.assertIsNone(result)
        self.assertIsInstance(error,
                              inspection_service.InspectionAssignmentConflict)
        self.assertIn("Black", str(error))

    def test_expected_barangay_is_enforced_in_target_lookup(self):
        self._assign("Red", "Active", expected_barangay_id=7)
        target_query = next(
            call for call in self.last_cursor.execute.call_args_list
            if "FROM geospatial_logs g" in call.args[0]
            and "WHERE g.logID = %s" in call.args[0]
        )
        self.assertIn("AND g.barangayID = %s", target_query.args[0])
        self.assertEqual(target_query.args[1], (22, 7))

    def test_allowed_colours_are_assignable(self):
        for colour, status in (("Red", "Expired"), ("Yellow", "Pending"),
                               ("Orange", "Expired"), ("Purple", "Closed")):
            with self.subTest(colour=colour):
                result, error = self._assign(colour, status)
                self.assertIsNone(error)
                self.assertEqual(result["status"], "Assigned")

    def test_stale_red_pin_with_active_registry_is_blocked(self):
        # Pin says Red, registry says Active, so the Map shows Green.
        result, error = self._assign("Red", "Active")
        self.assertIsNone(result)
        self.assertIsInstance(error,
                              inspection_service.InspectionAssignmentConflict)
        self.assertIn("Green (registered)", str(error))

    def test_stale_green_pin_with_expired_registry_is_allowed(self):
        # Pin says Green, registry says Expired, so the Map shows Red.
        result, error = self._assign("Green", "Expired")
        self.assertIsNone(error)
        self.assertEqual(result["status"], "Assigned")

    def test_unregistered_pin_uses_its_own_colour(self):
        result, error = self._assign("Red", None, business_id=None,
                                     place_id="PLACE-1")
        self.assertIsNone(error)
        self.assertEqual(result["status"], "Assigned")

    def test_unregistered_black_pin_is_blocked(self):
        result, error = self._assign("Black", None, business_id=None,
                                     place_id="PLACE-1")
        self.assertIsNone(result)
        self.assertIsInstance(error,
                              inspection_service.InspectionAssignmentConflict)

    def test_unknown_colour_is_blocked(self):
        result, error = self._assign("Magenta", None, business_id=None,
                                     place_id="PLACE-1")
        self.assertIsNone(result)
        self.assertIsInstance(error,
                              inspection_service.InspectionAssignmentConflict)

    def test_existing_open_assignment_is_a_conflict(self):
        result, error = self._assign("Red", "Expired", open_status="Assigned")
        self.assertIsNone(result)
        self.assertIsInstance(error,
                              inspection_service.InspectionAssignmentConflict)
        self.assertIn("already undergoing inspection", str(error))


class EligibilityUsesSharedExpressionTests(unittest.TestCase):

    def test_assign_query_embeds_the_shared_expression(self):
        cursor = MagicMock()
        cursor.fetchone.return_value = {
            "logID": 22, "flagColor": "Red", "effectiveFlagColor": "Red"}
        with (
            patch.object(inspection_service, "mysql") as mock_mysql,
            patch.object(inspection_service, "_ensure_gps_columns"),
            patch.object(inspection_service,
                         "get_latest_inspection_cycle_id", return_value=None),
            patch.object(inspection_service, "log_inspection_event"),
            patch("api.notifications.hub.publish_to_admins"),
        ):
            mock_mysql.connection.cursor.return_value = cursor
            inspection_service.assign_inspection(22, 9, None, 2)
        sqls = [c.args[0] for c in cursor.execute.call_args_list]
        self.assertTrue(any(_effective_flag_color_sql("g") in s for s in sqls),
                        "assign_inspection must reuse the shared expression")


class AssignRouteStatusCodeTests(unittest.TestCase):
    """Route-level: blocked assignment is 409, genuine failure is 500."""

    def setUp(self):
        # A bare app is enough: the view only needs a request context.
        self.app = Flask(__name__)
        self.view = inspections_routes.assign.__wrapped__

    def _call(self, service_result):
        with patch.object(inspections_routes, "assign_inspection",
                          return_value=service_result), \
            patch.object(inspections_routes, "get_jwt_identity",
                         return_value=2):
            with self.app.test_request_context(
                    "/inspections/assign", method="POST",
                    json={"logID": 22, "userID": 9}):
                body, status = self.view()
        return body, status

    def test_ineligible_is_409(self):
        _, status = self._call(
            (None, inspection_service.InspectionAssignmentConflict(
                "Green (registered) businesses cannot be inspected")))
        self.assertEqual(status, 409)

    def test_double_booked_is_409(self):
        _, status = self._call(
            (None, inspection_service.InspectionAssignmentConflict(
                "This business is already undergoing inspection")))
        self.assertEqual(status, 409)

    def test_other_error_stays_500(self):
        _, status = self._call((None, "database exploded"))
        self.assertEqual(status, 500)

    def test_error_body_carries_code_and_message(self):
        body, _ = self._call(
            (None, inspection_service.InspectionAssignmentConflict("nope")))
        text = body.get_data(as_text=True)
        self.assertIn("inspection_assignment_conflict", text)
        self.assertIn("nope", text)


class BatchAssignRouteTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.view = inspections_routes.assign_batch.__wrapped__

    def test_selected_ids_are_assigned_with_barangay_scope(self):
        assigned_result = {
            "reportID": 31, "logID": 22, "inspectorID": 9,
            "status": "Assigned",
        }
        with (
            patch.object(inspections_routes, "assign_inspection",
                         return_value=(assigned_result, None)) as assign_mock,
            patch.object(inspections_routes,
                         "get_jwt_identity", return_value=2),
            patch.object(inspections_routes, "notify_inspection_assigned"),
        ):
            with self.app.test_request_context(
                "/inspections/assign-batch", method="POST",
                json={"barangayID": 7, "userID": 9, "logIDs": [22]},
            ):
                body, status = self.view()
        self.assertEqual(status, 200)
        self.assertEqual(body.get_json()["assignedCount"], 1)
        self.assertEqual(body.get_json()["skippedCount"], 0)
        self.assertEqual(
            assign_mock.call_args.kwargs["expected_barangay_id"], 7)

    def test_empty_selection_is_rejected(self):
        with patch.object(inspections_routes, "get_jwt_identity", return_value=2):
            with self.app.test_request_context(
                "/inspections/assign-batch", method="POST",
                json={"barangayID": 7, "userID": 9, "logIDs": []},
            ):
                body, status = self.view()
        self.assertEqual(status, 400)
        self.assertIn("logIDs", body.get_json()["error"])

    def test_fractional_log_id_is_rejected_without_assignment(self):
        with (
            patch.object(inspections_routes,
                         "get_jwt_identity", return_value=2),
            patch.object(inspections_routes, "assign_inspection") as assign_mock,
        ):
            with self.app.test_request_context(
                "/inspections/assign-batch", method="POST",
                json={"barangayID": 7, "userID": 9, "logIDs": [22.5]},
            ):
                body, status = self.view()
        self.assertEqual(status, 400)
        self.assertIn("logIDs", body.get_json()["error"])
        assign_mock.assert_not_called()


if __name__ == "__main__":
    unittest.main()
