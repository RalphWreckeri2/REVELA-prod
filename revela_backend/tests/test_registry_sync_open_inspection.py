"""Regression tests: sync_registry must skip rows with an open inspection.

An inspection is "open" while verificationStatus <> 'Verified'. These tests
drive the real sync_registry and the real _sync_flag_color against a mock-DB
cursor: _sync_flag_color is deliberately NOT patched, which is how the missing
business_id argument in update_business went unnoticed for so long.

The fake cursor evaluates the open-inspection predicate in Python from a
(pin, inspection) fixture, so the tests exercise the SQL's own "<> 'Verified'"
rule rather than a hardcoded set of statuses.
"""
from api.registry import service
import os
import sys
import unittest
from io import BytesIO
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..")))


CSV_HEADER = ("Business ID,businessName,barangay,businessAddress,"
              "applicationStatus\n")


def _csv(rows):
    return BytesIO((CSV_HEADER + "".join(rows)).encode("utf-8"))


class _Fixture:
    """Pins and inspections backing the fake open-inspection query."""

    def __init__(self, pins=None, inspections=None, existing=None,
                 warning_state=None):
        self.pins = pins or []
        self.inspections = inspections or []
        self.existing = existing
        self.warning_state = warning_state

    def _open_for(self, pin):
        return any(
            ir["targetID"] == pin["logID"]
            and ir["targetType"] == "geospatial_log"
            and ir["verificationStatus"] != "Verified"
            for ir in self.inspections
        )

    def open_business_ids(self):
        return {p["businessID"] for p in self.pins
                if p.get("businessID") and self._open_for(p)}

    def open_name_brgy(self):
        return {(p["detectedName"], p["barangayID"]) for p in self.pins
                if not p.get("businessID") and self._open_for(p)}


def _cursor(fixture):
    cursor = MagicMock()
    cursor.rowcount = 1
    calls = {"registry": 0}

    def last():
        return cursor.execute.call_args.args[0] if cursor.execute.call_args else ""

    def fetchall():
        sql = last()
        if "SELECT DISTINCT g.businessID" in sql:
            return [{"businessID": b} for b in fixture.open_business_ids()]
        if "SELECT DISTINCT g.detectedName" in sql:
            return [{"detectedName": n, "barangayID": b}
                    for n, b in fixture.open_name_brgy()]
        return []

    def fetchone():
        sql = last()
        if sql.lstrip().startswith("SELECT warningLevel, blackLocked"):
            return fixture.warning_state
        if "FROM official_registry" in sql and "WHERE businessID = %s" in sql:
            calls["registry"] += 1
            return fixture.existing
        if "SELECT g.logID" in sql:
            for pin in fixture.pins:
                return pin
            return None
        return None

    cursor.fetchall.side_effect = fetchall
    cursor.fetchone.side_effect = fetchone
    return cursor


_EXISTING = {
    "businessID": "BIZ-1",
    "businessName": "ACME STORE",
    "barangayID": 1,
    "businessType": "SOLE PROPRIETORSHIP",
    "lineOfBusiness": "PHARMACY",
    "businessAddress": "OLD MAIN STREET",
    "applicationStatus": "Active",
    "lastRenewalDate": "2026-01-01 00:00:00",
    "businessSize": "SMALL",
    "registrationType": "NEW",
    "latitude": 13.96,
    "longitude": 121.11,
    "coordSource": "csv",
    "placeID": None,
    "placeIDKind": None,
    "matchScore": None,
    "matchStatus": None,
    "resolveKey": "old-key",
}

_PIN = {
    "logID": 42, "businessID": "BIZ-1", "detectedName": "ACME STORE",
    "barangayID": 1, "flagColor": "Green",
    "latitude": 13.96, "longitude": 121.11, "has_verified_orange": 0,
}


class SyncOpenInspectionTests(unittest.TestCase):

    def _run(self, fixture, csv_rows):
        cursor = _cursor(fixture)
        mysql = MagicMock()
        mysql.connection.cursor.return_value = cursor
        usage = {"text_search": {"day": 0, "month": 0},
                 "details": {"day": 0, "month": 0},
                 "geocoding": {"day": 0, "month": 0}}
        with (
            patch.object(service, "mysql", mysql),
            patch.object(service, "_load_barangay_lookup",
                         return_value={"barangay i": 1}),
            patch.object(service, "_resolve_barangay_id", return_value=1),
            patch.object(service, "is_cancelled", return_value=False),
            patch.object(service.places_resolver, "reset_run_state"),
            patch.object(service.places_resolver, "compute_resolve_key",
                         return_value="new-key"),
            patch.object(service.places_resolver, "record_coord_meta"),
            patch.object(service.places_resolver, "_update_pin"),
            patch.object(service.places_resolver,
                         "get_places_call_usage", return_value=usage),
            patch.object(service, "_resolve_location",
                         return_value=(13.97, 121.12,
                                       {"coord_source": "csv",
                                        "resolve_key": "new-key"})),
            patch.object(service, "insert_green_flag"),
            patch("api.notifications.hub.publish_to_admins"),
        ):
            summary, error = service.sync_registry(
                _csv(csv_rows), ".csv")
        self.assertIsNone(error)
        return summary, cursor

    @staticmethod
    def _sqls(cursor, needle):
        return [c.args[0] for c in cursor.execute.call_args_list
                if needle in c.args[0]]

    # -- the required cases --------------------------------------------------

    def test_assigned_inspection_freezes_the_row(self):
        fixture = _Fixture(
            pins=[_PIN],
            inspections=[{"targetID": 42, "targetType": "geospatial_log",
                          "verificationStatus": "Assigned"}],
            existing=dict(_EXISTING))
        summary, cursor = self._run(
            fixture, ["BIZ-1,Acme Store,Barangay I,New Main Street,Expired\n"])

        self.assertEqual(summary["skipped_open_inspection"], 1)
        self.assertEqual(summary["skipped"], 1)
        self.assertEqual(summary["updated"], 0)
        self.assertEqual(self._sqls(cursor, "UPDATE official_registry"), [])
        self.assertEqual(
            self._sqls(cursor, "SET flagColor = %s"), [],
            "the pin must not be recoloured")

    def test_submitted_inspection_freezes_the_row(self):
        fixture = _Fixture(
            pins=[_PIN],
            inspections=[{"targetID": 42, "targetType": "geospatial_log",
                          "verificationStatus": "Submitted"}],
            existing=dict(_EXISTING))
        summary, cursor = self._run(
            fixture, ["BIZ-1,Acme Store,Barangay I,New Main Street,Expired\n"])

        self.assertEqual(summary["skipped_open_inspection"], 1)
        self.assertEqual(summary["updated"], 0)
        self.assertEqual(self._sqls(cursor, "UPDATE official_registry"), [])
        self.assertEqual(self._sqls(cursor, "SET flagColor = %s"), [])

    def test_verified_inspection_does_not_freeze_the_row(self):
        fixture = _Fixture(
            pins=[_PIN],
            inspections=[{"targetID": 42, "targetType": "geospatial_log",
                          "verificationStatus": "Verified"}],
            existing=dict(_EXISTING))
        summary, cursor = self._run(
            fixture, ["BIZ-1,Acme Store,Barangay I,New Main Street,Expired\n"])

        self.assertEqual(summary["skipped_open_inspection"], 0)
        self.assertEqual(summary["updated"], 1)
        self.assertTrue(self._sqls(cursor, "UPDATE official_registry"))
        self.assertTrue(self._sqls(cursor, "SET flagColor = %s"))

    def test_active_import_clears_warning_and_recolors_pin(self):
        existing = dict(_EXISTING, applicationStatus="Expired")
        fixture = _Fixture(
            pins=[dict(_PIN, flagColor="Orange")],
            inspections=[{"targetID": 42, "targetType": "geospatial_log",
                          "verificationStatus": "Verified",
                          "inspectionResult": "Orange"}],
            existing=existing,
            warning_state={"warningLevel": 2, "blackLocked": 0},
        )
        cursor = _cursor(fixture)
        mysql = MagicMock()
        mysql.connection.cursor.return_value = cursor
        usage = {"text_search": {"day": 0, "month": 0},
                 "details": {"day": 0, "month": 0},
                 "geocoding": {"day": 0, "month": 0}}
        with (
            patch.object(service, "mysql", mysql),
            patch.object(service, "_load_barangay_lookup",
                         return_value={"barangay i": 1}),
            patch.object(service, "_resolve_barangay_id", return_value=1),
            patch.object(service, "is_cancelled", return_value=False),
            patch.object(service, "ladder_columns_available",
                         return_value=True),
            patch.object(service.places_resolver, "reset_run_state"),
            patch.object(service.places_resolver, "compute_resolve_key",
                         return_value="new-key"),
            patch.object(service.places_resolver, "record_coord_meta"),
            patch.object(service.places_resolver, "_update_pin"),
            patch.object(service.places_resolver,
                         "get_places_call_usage", return_value=usage),
            patch.object(service, "_resolve_location",
                         return_value=(13.97, 121.12,
                                       {"coord_source": "csv",
                                        "resolve_key": "new-key"})),
            patch.object(service, "insert_green_flag"),
            patch("api.notifications.hub.publish_to_admins"),
        ):
            summary, error = service.sync_registry(
                _csv(["BIZ-1,Acme Store,Barangay I,New Main Street,Active\n"]),
                ".csv")

        self.assertIsNone(error)
        self.assertEqual(summary["cleared_warnings"], 1)
        warning_updates = [
            call for call in cursor.execute.call_args_list
            if "UPDATE enforcement_state" in call.args[0]
        ]
        self.assertEqual(len(warning_updates), 1)
        self.assertIn("warningLevel = 0", warning_updates[0].args[0])
        event_inserts = [
            call for call in cursor.execute.call_args_list
            if "INSERT INTO enforcement_events" in call.args[0]
        ]
        self.assertEqual(len(event_inserts), 1)
        self.assertEqual(event_inserts[0].args[1][2], "warning_cleared")
        pin_updates = [
            call for call in cursor.execute.call_args_list
            if "SET flagColor = %s" in call.args[0]
        ]
        self.assertEqual(len(pin_updates), 1)
        self.assertEqual(pin_updates[0].args[1][0], "Green")
        self.assertEqual(len(fixture.inspections), 1)

    def test_unlinked_pin_is_frozen_by_name_and_barangay(self):
        unlinked_pin = {
            "logID": 43, "businessID": None, "detectedName": "ACME STORE",
            "barangayID": 1, "flagColor": "Green",
            "latitude": 13.96, "longitude": 121.11, "has_verified_orange": 0,
        }
        fixture = _Fixture(
            pins=[unlinked_pin],
            inspections=[{"targetID": 43, "targetType": "geospatial_log",
                          "verificationStatus": "Assigned"}],
            existing=dict(_EXISTING))
        summary, cursor = self._run(
            fixture, ["BIZ-1,Acme Store,Barangay I,New Main Street,Expired\n"])

        self.assertEqual(summary["skipped_open_inspection"], 1)
        self.assertEqual(summary["updated"], 0)
        self.assertEqual(self._sqls(cursor, "UPDATE official_registry"), [])

    def test_row_without_inspection_is_synced(self):
        fixture = _Fixture(pins=[_PIN], inspections=[],
                           existing=dict(_EXISTING))
        summary, cursor = self._run(
            fixture, ["BIZ-1,Acme Store,Barangay I,New Main Street,Expired\n"])

        self.assertEqual(summary["skipped_open_inspection"], 0)
        self.assertEqual(summary["updated"], 1)
        self.assertTrue(self._sqls(cursor, "UPDATE official_registry"))

    def test_new_row_is_still_inserted(self):
        fixture = _Fixture(pins=[], inspections=[], existing=None)
        summary, cursor = self._run(
            fixture, ["BIZ-NEW,New Shop,Barangay I,Other Street,Active\n"])

        self.assertEqual(summary["inserted"], 1)
        self.assertEqual(summary["skipped_open_inspection"], 0)
        self.assertTrue(self._sqls(cursor, "INSERT INTO official_registry"))

    # -- the predicate itself ------------------------------------------------

    def test_lookup_uses_not_verified_not_a_status_list(self):
        fixture = _Fixture(pins=[], inspections=[], existing=None)
        _, cursor = self._run(
            fixture, ["BIZ-NEW,New Shop,Barangay I,S,Active\n"])
        lookups = self._sqls(cursor, "SELECT DISTINCT g.businessID")
        self.assertEqual(len(lookups), 1)
        sql = lookups[0]
        self.assertIn("ir.verificationStatus IS NULL", sql)
        self.assertIn("ir.verificationStatus <> 'Verified'", sql)
        self.assertIn("ir.targetType = 'geospatial_log'", sql)
        self.assertIn("g.businessID IS NOT NULL", sql)
        for status in ("'Assigned'", "'Reassigned'", "'In Progress'",
                       "'Submitted'"):
            self.assertNotIn(f"IN ({status}", sql)

    def test_lookups_are_batched_once_before_the_loop(self):
        fixture = _Fixture(pins=[_PIN], inspections=[],
                           existing=dict(_EXISTING))
        _, cursor = self._run(
            fixture,
            ["BIZ-1,Acme Store,Barangay I,New Main Street,Expired\n",
             "BIZ-1,Acme Store,Barangay I,New Main Street,Active\n"])
        self.assertEqual(
            len(self._sqls(cursor, "SELECT DISTINCT g.businessID")), 1,
            "the open-inspection lookup must run once per batch, not per row")

    def test_skip_happens_before_geocoding(self):
        fixture = _Fixture(
            pins=[_PIN],
            inspections=[{"targetID": 42, "targetType": "geospatial_log",
                          "verificationStatus": "Assigned"}],
            existing=dict(_EXISTING))
        with (
            patch.object(service, "mysql") as mock_mysql,
            patch.object(service, "_load_barangay_lookup",
                         return_value={"barangay i": 1}),
            patch.object(service, "_resolve_barangay_id", return_value=1),
            patch.object(service, "is_cancelled", return_value=False),
            patch.object(service.places_resolver, "reset_run_state"),
            patch.object(service.places_resolver, "compute_resolve_key",
                         return_value="k"),
            patch.object(service.places_resolver, "record_coord_meta"),
            patch.object(service.places_resolver, "_update_pin"),
            patch.object(service.places_resolver, "get_places_call_usage",
                         return_value={"text_search": {"day": 0, "month": 0},
                                       "details": {"day": 0, "month": 0},
                                       "geocoding": {"day": 0, "month": 0}}),
            patch.object(service, "_resolve_location") as resolve_location,
            patch.object(service, "insert_green_flag"),
            patch("api.notifications.hub.publish_to_admins"),
        ):
            mock_mysql.connection.cursor.return_value = _cursor(fixture)
            service.sync_registry(
                _csv(["BIZ-1,Acme Store,Barangay I,New Main St,Expired\n"]),
                ".csv")
        resolve_location.assert_not_called()

    def test_null_status_inspection_protects_its_row(self):
        """A row with no verificationStatus is still 'not verified'."""
        fixture = _Fixture(
            pins=[_PIN],
            inspections=[{"targetID": 42, "targetType": "geospatial_log",
                          "verificationStatus": None}],
            existing=dict(_EXISTING))
        summary, cursor = self._run(
            fixture, ["BIZ-1,Acme Store,Barangay I,New Main Street,Expired\n"])

        self.assertEqual(summary["skipped_open_inspection"], 1)
        self.assertEqual(summary["updated"], 0)
        self.assertEqual(self._sqls(cursor, "UPDATE official_registry"), [])
        self.assertEqual(self._sqls(cursor, "SET flagColor = %s"), [])

    def test_lookup_failure_aborts_sync_without_writing_anything(self):
        """Fail closed: an unusable guard must not fall back to syncing."""
        fixture = _Fixture(pins=[_PIN], inspections=[],
                           existing=dict(_EXISTING))
        cursor = _cursor(fixture)
        healthy_fetchall = cursor.fetchall.side_effect

        def exploding_fetchall():
            sql = cursor.execute.call_args.args[0] if cursor.execute.call_args else ""
            if "SELECT DISTINCT g.businessID" in sql:
                raise RuntimeError("connection lost")
            return healthy_fetchall()

        cursor.fetchall.side_effect = exploding_fetchall
        mysql = MagicMock()
        mysql.connection.cursor.return_value = cursor
        usage = {"text_search": {"day": 0, "month": 0},
                 "details": {"day": 0, "month": 0},
                 "geocoding": {"day": 0, "month": 0}}
        with (
            patch.object(service, "mysql", mysql),
            patch.object(service, "_load_barangay_lookup",
                         return_value={"barangay i": 1}),
            patch.object(service, "_resolve_barangay_id", return_value=1),
            patch.object(service, "is_cancelled", return_value=False),
            patch.object(service.places_resolver, "reset_run_state"),
            patch.object(service.places_resolver, "compute_resolve_key",
                         return_value="k"),
            patch.object(service.places_resolver, "record_coord_meta"),
            patch.object(service.places_resolver, "_update_pin"),
            patch.object(service.places_resolver, "get_places_call_usage",
                         return_value=usage),
            patch.object(service, "_resolve_location"),
            patch.object(service, "insert_green_flag"),
            patch("api.notifications.hub.publish_to_admins"),
        ):
            # sync_registry now re-raises the typed lookup error instead of
            # stringifying it, so the route can answer 409 without matching
            # message text. The fail-closed contract is unchanged: nothing is
            # written and the call does not continue.
            with self.assertRaises(service.OpenInspectionLookupError) as caught:
                service.sync_registry(
                    _csv(["BIZ-1,Acme Store,Barangay I,New Main Street,Expired\n"]),
                    ".csv")

        error = str(caught.exception)
        self.assertIn("Could not check open inspections", error)
        self.assertIn("nothing was changed", error)
        # Nothing may be written, for any row, new or existing.
        self.assertEqual(self._sqls(cursor, "UPDATE official_registry"), [])
        self.assertEqual(self._sqls(
            cursor, "INSERT INTO official_registry"), [])
        self.assertEqual(self._sqls(cursor, "SET flagColor = %s"), [])
        mysql.connection.commit.assert_not_called()


if __name__ == "__main__":
    unittest.main()
