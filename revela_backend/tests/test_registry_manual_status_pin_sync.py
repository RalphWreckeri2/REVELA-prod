"""Regression tests for update_business -> map pin colour propagation.

These deliberately drive the real _sync_flag_color instead of mocking it.
The existing sync tests patch api.registry.service._sync_flag_color, which is
precisely why the missing business_id argument went unnoticed.
"""
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..")))

from api.registry import service


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
        #      OR (g.businessID IS NULL AND g.barangayID = %s AND g.detectedName = %s)
        # A NULL business_id therefore matches nothing, and the pin is only
        # found through the name+barangay branch when businessID IS NULL.
        def fetchone():
            last_sql, last_params = cursor.execute.call_args.args
            if "FROM official_registry" in last_sql:
                return registry_row
            if "SELECT g.logID" in last_sql:
                wanted_id, brgy, name = last_params[0], last_params[1], last_params[2]
                if wanted_id:
                    return pin
                if name == registry_row["businessName"] and brgy == registry_row["barangayID"]:
                    # name+barangay branch, but only for unlinked pins
                    return None
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
        self.assertEqual(pin_lookups[0].args[1][3], "BIZ-1")

        pin_updates = [
            call for call in cursor.execute.call_args_list
            if "UPDATE geospatial_logs" in call.args[0]
            and "flagColor" in call.args[0]
        ]
        self.assertEqual(len(pin_updates), 1,
                         "the linked pin should be recoloured exactly once")
        self.assertEqual(pin_updates[0].args[1][0], "Red")

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
        self.assertEqual(params[1], 7, "barangay of the edited row is used")
        self.assertEqual(params[2], "ACME STORE")
        self.assertEqual(params[3], "BIZ-1",
                         "ORDER BY must prefer the exact businessID match")

    @patch("api.registry.service.mysql")
    def test_missing_business_is_reported_without_touching_a_pin(self, mock_mysql):
        cursor = MagicMock()
        mock_mysql.connection.cursor.return_value = cursor
        cursor.fetchone.return_value = None

        ok, error = service.update_business(
            "NOPE", {"applicationStatus": "Expired"})

        self.assertFalse(ok)
        self.assertEqual(error, "Business not found")
        self.assertFalse([
            call for call in cursor.execute.call_args_list
            if "UPDATE geospatial_logs" in call.args[0]
        ])


if __name__ == "__main__":
    unittest.main()