"""Regression tests for update_business -> map pin colour propagation.

These deliberately drive the real _sync_flag_color instead of mocking it.
The existing sync tests patch api.registry.service._sync_flag_color, which is
precisely why the missing business_id argument went unnoticed.
"""
from api.registry import service
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..")))


class UpdateBusinessPinColourTests(unittest.TestCase):
    """update_business must recolour the pin linked by businessID."""

    def _cursor_with_registry_and_pin(self, mock_mysql, pin_colour="Green"):
        cursor = MagicMock()
        mock_mysql.connection.cursor.return_value = cursor

        registry_row = {
            "businessID": "BIZ-1",
            "businessName": "ACME STORE",
            "barangayID": 7,
        }
        pin = {
            "logID": 42,
            "flagColor": pin_colour,
            "latitude": 13.9,
            "longitude": 121.1,
            "has_verified_orange": 0,
        }

        # Model the SQL semantics of the _sync_flag_color lookup instead of
        # blindly returning a row:
        #   WHERE (g.businessID IS NOT NULL AND g.businessID = %s)
        # A NULL business_id matches nothing: name-only adoption is forbidden.
        def fetchone():
            last_sql, last_params = cursor.execute.call_args.args
            if "FROM official_registry" in last_sql:
                return registry_row
            if "SELECT g.logID" in last_sql:
                wanted_id = last_params[0]
                if wanted_id:
                    return pin
                return None
            return None

        cursor.fetchone.side_effect = fetchone
        return cursor

    @patch("api.registry.service.mysql")
    def test_active_to_expired_recolours_linked_pin_red(self, mock_mysql):
        """Editing permit status Active -> Expired must set the pin to Red."""
        cursor = self._cursor_with_registry_and_pin(mock_mysql)

        ok, error = service.update_business(
            "BIZ-1", {"applicationStatus": "Expired"})

        self.assertIsNone(error)
        self.assertTrue(ok)

        pin_lookups = [
            call for call in cursor.execute.call_args_list
            if "SELECT g.logID" in call.args[0]
        ]
        self.assertEqual(len(pin_lookups), 1,
                         "_sync_flag_color should look the pin up exactly once")

        # The lookup must be keyed on businessID. Pins created from the registry
        # already carry businessID, so the name+barangay fallback branch
        # ("g.businessID IS NULL AND ...") can never match them.
        self.assertEqual(pin_lookups[0].args[1][0], "BIZ-1")
        self.assertEqual(pin_lookups[0].args[1][1], "BIZ-1")

        pin_updates = [
            call for call in cursor.execute.call_args_list
            if "UPDATE geospatial_logs" in call.args[0]
            and "flagColor" in call.args[0]
        ]
        self.assertEqual(len(pin_updates), 1,
                         "the linked pin should be recoloured exactly once")
        self.assertEqual(pin_updates[0].args[1][0], "Red")
        self.assertEqual(pin_updates[0].args[1][4], "ACME STORE")

    @patch("api.registry.service.mysql")
    def test_registry_name_edit_updates_pin_by_business_id(self, mock_mysql):
        cursor = self._cursor_with_registry_and_pin(mock_mysql)

        ok, error = service.update_business(
            "BIZ-1", {"businessName": "New Business Name"})

        self.assertIsNone(error)
        self.assertTrue(ok)
        pin_updates = [
            call for call in cursor.execute.call_args_list
            if "UPDATE geospatial_logs" in call.args[0]
        ]
        self.assertEqual(len(pin_updates), 1)
        sql, params = pin_updates[0].args
        self.assertIn("WHERE businessID = %s", sql)
        self.assertEqual(params, (
            "NEW BUSINESS NAME", "BIZ-1", "ACME STORE", 7))

    @patch("api.registry.service.mysql")
    def test_open_inspection_blocks_manual_registry_edits(self, mock_mysql):
        cursor = self._cursor_with_registry_and_pin(mock_mysql)
        open_inspection = {
            "reportID": 23,
            "verificationStatus": "Submitted",
        }
        original_fetchone = cursor.fetchone.side_effect

        def fetchone():
            sql = cursor.execute.call_args.args[0]
            if "FROM inspection_reports ir" in sql:
                return open_inspection
            return original_fetchone()

        cursor.fetchone.side_effect = fetchone

        ok, error = service.update_business(
            "BIZ-1", {"businessName": "New Business Name"})

        self.assertFalse(ok)
        self.assertIsInstance(error, service.RegistryInspectionInProgress)
        self.assertIn("report #23", str(error))
        self.assertFalse(any(
            "UPDATE official_registry" in call.args[0]
            or "UPDATE geospatial_logs" in call.args[0]
            for call in cursor.execute.call_args_list
        ))
        mock_mysql.connection.commit.assert_not_called()

    @patch("api.registry.service.mysql")
    def test_revoked_recolours_linked_pin_black(self, mock_mysql):
        cursor = self._cursor_with_registry_and_pin(mock_mysql)

        ok, error = service.update_business(
            "BIZ-1", {"applicationStatus": "Revoked"})

        self.assertIsNone(error)
        self.assertTrue(ok)

        pin_updates = [
            call for call in cursor.execute.call_args_list
            if "UPDATE geospatial_logs" in call.args[0]
            and "flagColor" in call.args[0]
        ]
        self.assertEqual(len(pin_updates), 1)
        self.assertEqual(pin_updates[0].args[1][0], "Black")

    @patch("api.registry.service.mysql")
    def test_reactivation_recolours_linked_pin_green(self, mock_mysql):
        cursor = self._cursor_with_registry_and_pin(
            mock_mysql, pin_colour="Red")

        ok, error = service.update_business(
            "BIZ-1", {"applicationStatus": "Active"})

        self.assertIsNone(error)
        self.assertTrue(ok)

        pin_updates = [
            call for call in cursor.execute.call_args_list
            if "UPDATE geospatial_logs" in call.args[0]
            and "flagColor" in call.args[0]
        ]
        self.assertEqual(len(pin_updates), 1)
        self.assertEqual(pin_updates[0].args[1][0], "Green")

    @patch("api.registry.service.mysql")
    def test_business_id_used_is_the_edited_row_not_a_name_match(self, mock_mysql):
        """A same-name business in another barangay must not be recoloured."""
        cursor = self._cursor_with_registry_and_pin(mock_mysql)

        service.update_business(
            "BIZ-1", {"applicationStatus": "Expired"})

        pin_lookups = [
            call for call in cursor.execute.call_args_list
            if "SELECT g.logID" in call.args[0]
        ]
        params = pin_lookups[0].args[1]
        self.assertEqual(params[0], "BIZ-1", "only the explicit ID identifies the edited row")
        self.assertEqual(params[1], "BIZ-1",
                         "ORDER BY must prefer the exact businessID match")

    @patch("api.registry.service.mysql")
    def test_missing_business_is_reported_without_touching_a_pin(self, mock_mysql):
        cursor = MagicMock()
        mock_mysql.connection.cursor.return_value = cursor
        cursor.fetchone.return_value = None

        ok, error = service.update_business(
            "NOPE", {"applicationStatus": "Expired"})

        self.assertFalse(ok)
        self.assertIsInstance(error, service.RegistryNotFoundError)
        self.assertEqual(str(error), "Business not found")
        self.assertFalse([
            call for call in cursor.execute.call_args_list
            if "UPDATE geospatial_logs" in call.args[0]
        ])


if __name__ == "__main__":
    unittest.main()
