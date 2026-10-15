"""Regression tests: the Purple -> Closed registry write.

verify_inspection matched official_registry by LOWER(businessName) =
LOWER(detectedName) AND barangayID, ignored the pin's businessID, and never
checked how many rows the UPDATE affected. A zero-row update still returned
"Verified", so an admin could believe a permit had been closed when nothing
had changed - and with two same-named businesses in one barangay, the wrong
one could be closed.
"""
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..")))

from api.inspections import service as inspection_service

SUBMITTED = "Submitted"


class PurpleRegistryWriteTests(unittest.TestCase):
    """Drives verify_inspection with a fake cursor that understands SQL."""

    def _verify(self, *, pin_business_id, registry_match_business_id=None,
                result="Purple", pin_name="ACME STORE", pin_barangay=7,
                geospatial_exists=True):
        """rowcount of the registry UPDATE is decided by registry_match_business_id."""
        cursor = MagicMock()
        cursor.lastrowid = 1
        state = {"closed_rowcount": 0}

        def execute(sql, params=()):
            normalised = " ".join(sql.split())
            if "UPDATE official_registry" in normalised and "'Closed'" in normalised:
                if "WHERE businessID = %s" in normalised:
                    state["closed_rowcount"] = (
                        1 if registry_match_business_id == params[0] else 0)
                else:
                    # name + barangay fallback
                    state["closed_rowcount"] = 1 if registry_match_business_id else 0
                cursor.rowcount = state["closed_rowcount"]
                return
            cursor.rowcount = 1

        def fetchone():
            call = cursor.execute.call_args
            sql = " ".join(call.args[0].split()) if call else ""
            if "FROM inspection_reports ir" in sql:
                return {
                    "reportID": 4, "targetID": 22, "userID": 9,
                    "inspectionResult": result, "noticeLevel": 1,
                    "verificationStatus": SUBMITTED,
                    "verifiedLatitude": None, "verifiedLongitude": None,
                    "verifiedAccuracy": None, "nearestLandmark": None,
                    "detectedName": pin_name, "barangayID": pin_barangay,
                    "businessID": pin_business_id,
                }
            if "SELECT flagColor FROM geospatial_logs" in sql:
                return {"flagColor": "Red"}
            if "SELECT detectedName, barangayID FROM geospatial_logs" in sql:
                if geospatial_exists:
                    return {"detectedName": pin_name, "barangayID": pin_barangay}
                return None
            return None

        cursor.execute.side_effect = execute
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
            result, error = inspection_service.verify_inspection(
                4, verified_by_user_id=2)
        self.assertIsNone(error)
        return result, cursor

    @staticmethod
    def _closed_update(cursor):
        for call in cursor.execute.call_args_list:
            if "UPDATE official_registry" in call.args[0]:
                return " ".join(call.args[0].split()), call.args[1]
        return None, None

    # -- the required cases --------------------------------------------------

    def test_purple_on_linked_pin_closes_the_right_registry_row(self):
        result, cursor = self._verify(pin_business_id="BIZ-7",
                                      registry_match_business_id="BIZ-7")
        sql, params = self._closed_update(cursor)
        self.assertIn("WHERE businessID = %s", sql)
        self.assertEqual(params, ("BIZ-7",))
        self.assertTrue(result["registryClosed"])
        self.assertIsNone(result["registryWarning"])

    def test_same_name_two_branches_only_the_linked_one_changes(self):
        # "7-Eleven" exists as BIZ-711-BR1 and BIZ-711-BR2 in barangay 7.
        # The pin is linked to BR2, so only BR2 may be closed.
        result, cursor = self._verify(pin_business_id="BIZ-711-BR2",
                                      registry_match_business_id="BIZ-711-BR2",
                                      pin_name="7-Eleven")
        sql, params = self._closed_update(cursor)
        self.assertIn("WHERE businessID = %s", sql)
        self.assertNotIn("LOWER(businessName)", sql)
        self.assertEqual(params, ("BIZ-711-BR2",))
        self.assertTrue(result["registryClosed"])

    def test_linked_pin_with_no_registry_row_warns(self):
        result, cursor = self._verify(pin_business_id="BIZ-GHOST",
                                      registry_match_business_id=None)
        self.assertFalse(result["registryClosed"])
        self.assertIsNotNone(result["registryWarning"])
        self.assertIn("BIZ-GHOST", result["registryWarning"])
        self.assertEqual(result["status"], "Verified")

    def test_unregistered_pin_falls_back_to_name_and_barangay(self):
        result, cursor = self._verify(pin_business_id=None,
                                      registry_match_business_id="BIZ-NAME")
        sql, params = self._closed_update(cursor)
        self.assertIn("LOWER(businessName) = LOWER(%s)", sql)
        self.assertEqual(params, ("ACME STORE", 7))
        self.assertTrue(result["registryClosed"])
        self.assertIsNone(result["registryWarning"])

    def test_unregistered_pin_with_no_registry_row_is_not_an_error(self):
        result, cursor = self._verify(pin_business_id=None,
                                      registry_match_business_id=None,
                                      geospatial_exists=False)
        self.assertEqual(result["status"], "Verified")
        self.assertEqual(result["newFlagColor"], "Purple")
        self.assertFalse(result["registryClosed"])
        self.assertIsNone(result["registryWarning"])

    # -- other colours are untouched ----------------------------------------

    def test_other_results_never_write_the_registry(self):
        for colour in ("Green", "Red", "Yellow", "Orange", "Black"):
            with self.subTest(result=colour):
                result, cursor = self._verify(pin_business_id="BIZ-7",
                                              registry_match_business_id="BIZ-7",
                                              result=colour)
                sql, _ = self._closed_update(cursor)
                self.assertIsNone(sql, f"{colour} must not touch the registry")
                self.assertFalse(result["registryClosed"])
                self.assertIsNone(result["registryWarning"])

    def test_pin_colour_is_still_updated_for_purple(self):
        result, cursor = self._verify(pin_business_id="BIZ-7",
                                      registry_match_business_id="BIZ-7")
        pin_updates = [c for c in cursor.execute.call_args_list
                       if "UPDATE geospatial_logs" in c.args[0]]
        self.assertEqual(len(pin_updates), 1)
        self.assertEqual(pin_updates[0].args[1][0], "Purple")

    def test_report_query_selects_the_pin_business_id(self):
        _, cursor = self._verify(pin_business_id="BIZ-7",
                                 registry_match_business_id="BIZ-7")
        selects = [c.args[0] for c in cursor.execute.call_args_list
                   if "FROM inspection_reports ir" in c.args[0]]
        self.assertEqual(len(selects), 1)
        self.assertIn("g.businessID", selects[0])


if __name__ == "__main__":
    unittest.main()