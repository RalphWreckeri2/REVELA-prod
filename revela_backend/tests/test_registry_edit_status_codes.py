"""Regression tests: the registry edit route returns the right HTTP status.

update_business used to signal "not found" and "bad input" with plain message
strings, so the route had to compare error text to pick a status code. Both
are now typed (RegistryNotFoundError / RegistryValidationError) and the route
uses isinstance, so the status cannot drift from the wording.
"""
from api.registry import service as registry_service
from api.registry import routes as registry_routes
from flask import Flask
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..")))


EXISTING = {"businessID": "BIZ-1", "businessName": "ACME STORE",
            "barangayID": 1}


def _app():
    app = Flask(__name__)
    app.register_blueprint(registry_routes.registry_bp)
    return app


class RegistryEditStatusCodeTests(unittest.TestCase):
    """Route-level: assert the HTTP status, not the service internals."""

    def setUp(self):
        self.app = _app()
        # admin_required wraps the view; step past it so the test exercises the
        # status mapping rather than the JWT/session guard.
        self.view = registry_routes.edit_business.__wrapped__

    def _call(self, service_result):
        with patch.object(registry_routes, "update_business",
                          return_value=service_result):
            with self.app.test_request_context(
                    "/registry/BIZ-1", method="PUT",
                    json={"applicationStatus": "Expired"}):
                body, status = self.view("BIZ-1")
        return body, status

    def test_validation_error_is_400(self):
        _, status = self._call(
            (False, registry_service.RegistryValidationError(
                "unrecognised permit status 'Orange'")))
        self.assertEqual(status, 400)

    def test_not_found_is_404(self):
        _, status = self._call(
            (False, registry_service.RegistryNotFoundError(
                "Business not found")))
        self.assertEqual(status, 404)

    def test_open_inspection_conflict_is_409(self):
        _, status = self._call(
            (False, registry_service.RegistryInspectionInProgress(
                "Inspection is in progress")))
        self.assertEqual(status, 409)

    def test_untyped_failure_stays_500(self):
        _, status = self._call((False, "database exploded"))
        self.assertEqual(status, 500)

    def test_success_is_200(self):
        _, status = self._call((True, None))
        self.assertEqual(status, 200)

    def test_error_body_carries_the_message(self):
        body, _ = self._call(
            (False, registry_service.RegistryValidationError("bad status")))
        self.assertIn("bad status", body.get_data(as_text=True))


class RegistryEditErrorTypesTests(unittest.TestCase):
    """Service-level: the typed errors are actually produced."""

    def _update(self, existing, payload):
        cursor = MagicMock()
        cursor.rowcount = 1

        def fetchone():
            call = cursor.execute.call_args
            sql = call.args[0] if call else ""
            if "FROM official_registry" in sql:
                return existing
            return None

        cursor.fetchone.side_effect = fetchone
        mysql = MagicMock()
        mysql.connection.cursor.return_value = cursor
        with (
            patch.object(registry_service, "mysql", mysql),
            patch("api.notifications.hub.publish_to_admins"),
        ):
            return registry_service.update_business("BIZ-1", payload)

    def test_bad_status_returns_validation_error(self):
        ok, error = self._update(dict(EXISTING),
                                 {"applicationStatus": "Orange"})
        self.assertFalse(ok)
        self.assertIsInstance(error, registry_service.RegistryValidationError)
        self.assertIn("Orange", str(error))

    def test_missing_business_returns_not_found_error(self):
        ok, error = self._update(None, {"applicationStatus": "Expired"})
        self.assertFalse(ok)
        self.assertIsInstance(error, registry_service.RegistryNotFoundError)

    def test_route_does_not_match_on_message_text(self):
        """The route must not compare error strings to choose a status."""
        import inspect
        source = inspect.getsource(registry_routes.edit_business)
        self.assertNotIn('== "Business not found"', source)
        self.assertIn("isinstance", source)


if __name__ == "__main__":
    unittest.main()
