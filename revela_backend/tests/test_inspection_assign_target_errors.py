"""Regression tests: assign_inspection returns meaningful HTTP statuses.

Two rejections were plain strings and therefore landed on the 500 branch:
"Flag #N not found" (should be 404) and "Inspector userID N not found"
(should be 400). Both are now typed and mapped with isinstance, so the status
cannot drift from the message.
"""
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..")))

from flask import Flask

from api.inspections import routes as inspections_routes
from api.inspections import service as inspection_service


class AssignTargetErrorsTests(unittest.TestCase):
    """Service level: the typed errors are actually produced."""

    def _assign(self, *, pin_exists, inspector_exists):
        cursor = MagicMock()
        cursor.lastrowid = 31

        def fetchone():
            call = cursor.execute.call_args
            sql = " ".join(call.args[0].split()) if call else ""
            if "FROM geospatial_logs g" in sql:
                if pin_exists:
                    return {"logID": 22, "flagColor": "Red",
                            "effectiveFlagColor": "Red"}
                return None
            if "FROM users" in sql:
                if inspector_exists:
                    return {"userID": 9, "fullName": "Ana",
                            "userRole": "Inspector"}
                return None
            return None

        cursor.fetchone.side_effect = fetchone
        with (
            patch.object(inspection_service, "mysql") as mock_mysql,
            patch.object(inspection_service, "_ensure_gps_columns"),
            patch.object(inspection_service,
                         "get_latest_inspection_cycle_id", return_value=None),
            patch.object(inspection_service, "log_inspection_event"),
            patch("api.notifications.hub.publish_to_admins"),
        ):
            mock_mysql.connection.cursor.return_value = cursor
            return inspection_service.assign_inspection(22, 9, None, 2)

    def test_missing_pin_is_not_found(self):
        result, error = self._assign(pin_exists=False, inspector_exists=True)
        self.assertIsNone(result)
        self.assertIsInstance(error,
                              inspection_service.InspectionTargetNotFound)
        self.assertIn("Flag #22 not found", str(error))

    def test_missing_inspector_is_invalid(self):
        result, error = self._assign(pin_exists=True, inspector_exists=False)
        self.assertIsNone(result)
        self.assertIsInstance(error,
                              inspection_service.InspectionTargetInvalid)
        self.assertIn("userID 9 not found", str(error))

    def test_pin_is_checked_before_the_inspector(self):
        # A bad inspector on a bad pin reports the pin, which is the 404 case.
        _, error = self._assign(pin_exists=False, inspector_exists=False)
        self.assertIsInstance(error,
                              inspection_service.InspectionTargetNotFound)


class AssignRouteStatusTests(unittest.TestCase):

    def setUp(self):
        self.app = Flask(__name__)
        self.view = inspections_routes.assign.__wrapped__

    def _status(self, service_result):
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
        _, status = self._status(
            (None, inspection_service.InspectionAssignmentConflict("nope")))
        self.assertEqual(status, 409)

    def test_missing_pin_is_404(self):
        body, status = self._status(
            (None, inspection_service.InspectionTargetNotFound(
                "Flag #22 not found")))
        self.assertEqual(status, 404)
        self.assertIn("inspection_target_not_found",
                      body.get_data(as_text=True))

    def test_missing_inspector_is_400(self):
        body, status = self._status(
            (None, inspection_service.InspectionTargetInvalid(
                "Inspector userID 9 not found")))
        self.assertEqual(status, 400)
        self.assertIn("inspection_target_invalid",
                      body.get_data(as_text=True))

    def test_genuine_failure_is_still_500(self):
        _, status = self._status((None, "database exploded"))
        self.assertEqual(status, 500)

    def test_route_does_not_match_on_message_text(self):
        import inspect
        source = inspect.getsource(inspections_routes.assign)
        # No comparison of the error value against any literal wording.
        for pattern in ("error ==", "error !=", "error in", '"Flag #',
                        '"Inspector userID'):
            self.assertNotIn(pattern, source)
        self.assertIn("isinstance", source)


if __name__ == "__main__":
    unittest.main()