"""Regression tests: unrecognised permit statuses are rejected, not defaulted.

_normalise_status used to return "Pending" for anything it did not recognise,
so "Orange", "Black", a typo, or a blank cell all became a Yellow pin. Statuses
are now validated: an unrecognised or empty value rejects the row.

These tests drive the real upload_registry, sync_registry and update_business
against a mock-DB cursor. Neither _normalise_status nor _sync_flag_color is
patched.
"""
import os
import sys
import unittest
from io import BytesIO
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..")))

from api.registry import service

CSV_HEADER = ("Business ID,businessName,barangay,businessAddress,"
              "applicationStatus\n")

REJECTED = ["Orange", "Black", "Suspended", "Banana", ""]
USAGE = {"text_search": {"day": 0, "month": 0},
         "details": {"day": 0, "month": 0},
         "geocoding": {"day": 0, "month": 0}}


def _csv(rows):
    return BytesIO((CSV_HEADER + "".join(rows)).encode("utf-8"))


def _row(biz_id, name, status):
    return f"{biz_id},{name},Barangay I,Main Street,{status}\n"


class StatusValidationBase(unittest.TestCase):

    def _cursor(self, existing=None):
        cursor = MagicMock()
        cursor.rowcount = 1
        cursor.fetchall.return_value = []
        cursor.fetchone.side_effect = (
            lambda *a, **k: existing if _is_registry_lookup() else None)

        def _is_registry_lookup():
            call = cursor.execute.call_args
            return bool(call) and "FROM official_registry" in call.args[0]

        return cursor

    def _patches(self, cursor, existing=None):
        mysql = MagicMock()
        mysql.connection.cursor.return_value = cursor
        return (
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
                         return_value=USAGE),
            patch.object(service, "_resolve_location",
                         return_value=(13.97, 121.12,
                                       {"coord_source": "csv",
                                        "resolve_key": "k"})),
            patch.object(service, "insert_green_flag"),
            patch("api.notifications.hub.publish_to_admins"),
        )

    def _run_sync(self, rows):
        cursor = self._cursor()
        patches = self._patches(cursor)
        with patches[0], patches[1], patches[2], patches[3], patches[4], \
                patches[5], patches[6], patches[7], patches[8], patches[9], \
                patches[10]:
            summary, error = service.sync_registry(_csv(rows), ".csv")
        self.assertIsNone(error)
        return summary, cursor

    def _run_upload(self, rows):
        cursor = self._cursor()
        patches = self._patches(cursor)
        with patches[0], patches[1], patches[2], patches[3], patches[4], \
                patches[5], patches[6], patches[7], patches[8], patches[9], \
                patches[10], \
                patch("api.registry.reverify._ensure_history_table"):
            summary, error = service.upload_registry(_csv(rows), ".csv")
        self.assertIsNone(error)
        return summary, cursor

    def _sqls(self, cursor, needle):
        return [c.args[0] for c in cursor.execute.call_args_list
                if needle in c.args[0]]


class RejectedStatusInImportsTests(StatusValidationBase):

    def test_sync_rejects_each_bad_value(self):
        for value in REJECTED:
            with self.subTest(status=value):
                summary, cursor = self._run_sync(
                    [_row("BIZ-1", "Acme", value)])
                self.assertEqual(summary["inserted"], 0)
                self.assertEqual(summary["invalid_status_rows"], 1)
                self.assertEqual(summary["invalid_status_values"],
                                 {value: 1})
                self.assertEqual(
                    self._sqls(cursor, "INSERT INTO official_registry"), [])

    def test_upload_rejects_each_bad_value(self):
        for value in REJECTED:
            with self.subTest(status=value):
                summary, cursor = self._run_upload(
                    [_row("BIZ-1", "Acme", value)])
                self.assertEqual(summary["inserted"], 0)
                self.assertEqual(summary["invalid_status_rows"], 1)
                self.assertEqual(summary["invalid_status_values"],
                                 {value: 1})
                self.assertEqual(
                    self._sqls(cursor, "INSERT IGNORE INTO official_registry"),
                    [])

    def test_rejection_is_reported_in_errors(self):
        summary, _ = self._run_sync([_row("BIZ-1", "Acme", "Orange")])
        self.assertTrue(
            any("unrecognised permit status 'Orange'" in e
                for e in summary["errors"]))

    def test_one_bad_row_does_not_stop_the_good_rows(self):
        summary, cursor = self._run_sync([
            _row("BIZ-BAD1", "Bad One", "Orange"),
            _row("BIZ-GOOD", "Good One", "Active"),
            _row("BIZ-BAD2", "Bad Two", "Black"),
            _row("BIZ-GOOD2", "Good Two", "Expired"),
        ])
        self.assertEqual(summary["inserted"], 2)
        self.assertEqual(summary["invalid_status_rows"], 2)
        self.assertEqual(summary["invalid_status_values"],
                         {"Orange": 1, "Black": 1})
        inserts = self._sqls(cursor, "INSERT INTO official_registry")
        self.assertEqual(len(inserts), 2)

    def test_invalid_status_values_counts_are_not_truncated(self):
        # errors is capped at 20; the histogram must not be.
        rows = [_row(f"BIZ-{i}", f"S{i}", "Orange") for i in range(25)]
        summary, _ = self._run_sync(rows)
        self.assertEqual(summary["invalid_status_rows"], 25)
        self.assertEqual(summary["invalid_status_values"], {"Orange": 25})
        self.assertLessEqual(len(summary["errors"]), 20)

    def test_bad_row_costs_no_geocode_quota(self):
        with (
            patch.object(service, "mysql") as mock_mysql,
            patch.object(service, "_load_barangay_lookup",
                         return_value={"barangay i": 1}),
            patch.object(service, "_resolve_barangay_id", return_value=1),
            patch.object(service, "is_cancelled", return_value=False),
            patch.object(service.places_resolver, "reset_run_state"),
            patch.object(service.places_resolver, "compute_resolve_key",
                         return_value="k"),
            patch.object(service.places_resolver, "get_places_call_usage",
                         return_value=USAGE),
            patch.object(service, "_resolve_location") as resolve_location,
            patch.object(service, "insert_green_flag"),
            patch("api.notifications.hub.publish_to_admins"),
        ):
            mock_mysql.connection.cursor.return_value = self._cursor()
            service.sync_registry(_csv([_row("BIZ-1", "Acme", "Orange")]), ".csv")
        resolve_location.assert_not_called()


class ValidStatusStillWorksTests(StatusValidationBase):

    VALID = ["Active", "Expired", "Revoked", "Pending", "Closed"]
    ALIASES = {"blacklisted": "Revoked", "cancelled": "Revoked",
               "lapsed": "Expired", "for issuance": "Pending",
               "issued": "Active", "license issued": "Active"}

    def test_every_valid_status_imports(self):
        for value in self.VALID:
            with self.subTest(status=value):
                summary, _ = self._run_sync([_row("BIZ-1", "Acme", value)])
                self.assertEqual(summary["inserted"], 1)
                self.assertEqual(summary["invalid_status_rows"], 0)
                self.assertEqual(summary["invalid_status_values"], {})

    def test_every_existing_alias_still_maps(self):
        for raw, expected in self.ALIASES.items():
            with self.subTest(alias=raw):
                self.assertEqual(service._normalise_status(raw),
                                 (expected, None))
                summary, _ = self._run_sync([_row("BIZ-1", "Acme", raw)])
                self.assertEqual(summary["invalid_status_rows"], 0)

    def test_alias_is_stored_canonically(self):
        summary, cursor = self._run_sync([_row("BIZ-1", "Acme", "blacklisted")])
        self.assertEqual(summary["inserted"], 1)
        insert = next(c for c in cursor.execute.call_args_list
                      if "INSERT INTO official_registry" in c.args[0])
        self.assertEqual(insert.args[1][8], "Revoked")


class ManualEditRejectsBadStatusTests(unittest.TestCase):

    EXISTING = {"businessID": "BIZ-1", "businessName": "ACME STORE",
                "barangayID": 1}

    def _update(self, payload):
        cursor = MagicMock()
        cursor.rowcount = 1

        def fetchone():
            call = cursor.execute.call_args
            sql = call.args[0] if call else ""
            if "FROM official_registry" in sql:
                return dict(self.EXISTING)
            return {"logID": 42, "flagColor": "Green",
                    "latitude": 13.96, "longitude": 121.11,
                    "has_verified_orange": 0}

        cursor.fetchone.side_effect = fetchone
        mysql = MagicMock()
        mysql.connection.cursor.return_value = cursor
        with (
            patch.object(service, "mysql", mysql),
            patch("api.notifications.hub.publish_to_admins"),
        ):
            return service.update_business("BIZ-1", payload), cursor, mysql

    def test_manual_edit_rejects_each_bad_value(self):
        for value in REJECTED:
            with self.subTest(status=value):
                (ok, error), cursor, mysql = self._update(
                    {"applicationStatus": value})
                self.assertFalse(ok)
                self.assertIn("permit status", error)
                self.assertEqual(
                    [c.args[0] for c in cursor.execute.call_args_list
                     if "UPDATE official_registry" in c.args[0]], [],
                    "nothing may be written on a rejected status")
                mysql.connection.commit.assert_not_called()

    def test_manual_edit_accepts_valid_status(self):
        (ok, error), cursor, _ = self._update(
            {"applicationStatus": "Expired"})
        self.assertTrue(ok)
        self.assertIsNone(error)
        self.assertTrue([c for c in cursor.execute.call_args_list
                         if "UPDATE official_registry" in c.args[0]])

    def test_manual_edit_rejects_empty_status(self):
        (ok, error), _, _ = self._update({"applicationStatus": ""})
        self.assertFalse(ok)
        self.assertIn("missing permit status", error)

    def test_manual_edit_without_status_is_unaffected(self):
        (ok, error), _, _ = self._update({"businessName": "Acme Store"})
        self.assertTrue(ok)
        self.assertIsNone(error)


if __name__ == "__main__":
    unittest.main()