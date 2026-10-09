import os
import sys
import unittest
from io import BytesIO
from unittest.mock import MagicMock, patch

import pandas as pd

sys.path.insert(0, os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..")))

from api.registry import service


class RegistryImportHardeningTests(unittest.TestCase):

    def test_coordinate_pair_requires_finite_in_range_values(self):
        self.assertEqual(service._parse_coordinate_pair("13.96", "121.11"), (13.96, 121.11))
        self.assertIsNone(service._parse_coordinate_pair("91", "121.11"))
        self.assertIsNone(service._parse_coordinate_pair("13.96", "inf"))
        self.assertIsNone(service._parse_coordinate_pair("13.96", None))

    def test_transient_resolver_failures_do_not_become_cache_keys(self):
        for meta in (
            {"reason": "api_error"},
            {"reason": "skipped_quota", "budget_exhausted": True},
            {"reason": "monthly_quota_exceeded"},
        ):
            with self.subTest(meta=meta):
                self.assertIsNone(service._resolution_key_for_cache("new-key", meta))
        self.assertEqual(
            service._resolution_key_for_cache("new-key", {"reason": "no_text_results"}),
            "new-key",
        )

    def test_import_preserves_authoritative_manual_and_csv_coordinates(self):
        self.assertTrue(service._preserve_import_coordinates("manual", "auto", True))
        self.assertTrue(service._preserve_import_coordinates("places", "approved", True))
        self.assertTrue(service._preserve_import_coordinates("csv", "auto", False))
        self.assertFalse(service._preserve_import_coordinates("csv", "auto", True))
        self.assertFalse(service._preserve_import_coordinates("geocode", "auto", False))

    def test_legacy_geocode_http_error_is_not_reported_as_no_match(self):
        response = MagicMock(status_code=503, text="upstream unavailable")
        service._geocode_state.outcome = None
        with (
            patch.dict(os.environ, {"GOOGLE_MAPS_API_KEY": "test-key"}),
            patch.object(service, "_reserve_geocode_call", return_value=True),
            patch.object(service.http, "get", return_value=response),
        ):
            self.assertEqual(service._geocode("Main Street", "Barangay I"), (None, None))

        self.assertEqual(service._geocode_state.outcome, "api_error")
        response.json.assert_not_called()

    def test_legacy_name_only_geocode_has_geocode_provenance_and_one_request(self):
        service._geocode_state.outcome = None
        with (
            patch.object(service.places_resolver, "enabled", return_value=False),
            patch.object(service.places_resolver, "compute_resolve_key", return_value="resolve-key"),
            patch.object(service, "_geocode", return_value=(13.96, 121.11)) as geocode,
        ):
            result = service._resolve_location(
                "Silva Pharmacy", "", "Barangay I", barangay_id=1
            )

        self.assertEqual(result[:2], (13.96, 121.11))
        self.assertEqual(result[2]["coord_source"], "geocode")
        self.assertEqual(result[2]["place_id_kind"], "address")
        geocode.assert_called_once_with("Silva Pharmacy", "Barangay I")

    def test_sync_preserves_existing_pin_and_retryability_on_api_failure(self):
        existing = {
            "businessID": "BIZ-1",
            "latitude": 13.96,
            "longitude": 121.11,
            "coordSource": "geocode",
            "matchStatus": "auto",
            "resolveKey": "old-key",
        }
        cursor = MagicMock()
        cursor.fetchone.return_value = existing
        cursor.rowcount = 1
        mysql = MagicMock()
        mysql.connection.cursor.return_value = cursor

        frame = pd.DataFrame([{
            "Business ID": "BIZ-1",
            "businessName": "Updated Pharmacy",
            "businessAddress": "New Main Street",
            "barangay": "Barangay I",
            "lineOfBusiness": "Pharmacy",
            "applicationStatus": "Active",
        }])
        usage = {
            "text_search": {"day": 3, "month": 10},
            "details": {"day": 0, "month": 0},
            "geocoding": {"day": 1, "month": 4},
        }
        with (
            patch.object(service, "mysql", mysql),
            patch.object(service.pd, "read_csv", return_value=frame),
            patch.object(service, "_load_barangay_lookup", return_value={"Barangay I": 1}),
            patch.object(service, "_resolve_barangay_id", return_value=1),
            patch.object(service, "is_cancelled", return_value=False),
            patch.object(service.places_resolver, "reset_run_state"),
            patch.object(service.places_resolver, "compute_resolve_key", return_value="new-key"),
            patch.object(
                service,
                "_resolve_location",
                return_value=(None, None, {"reason": "api_error", "api_error": "HTTP 503"}),
            ) as resolve_location,
            patch.object(service.places_resolver, "record_coord_meta") as record_coord_meta,
            patch.object(service.places_resolver, "get_places_call_usage", return_value=usage),
            patch.object(service.places_resolver, "_update_pin") as update_pin,
            patch.object(service, "_sync_flag_color") as sync_flag,
            patch.object(service, "insert_green_flag") as insert_flag,
            patch("api.notifications.hub.publish_to_admins"),
        ):
            summary, error = service.sync_registry(BytesIO(b"csv"), ".csv")

        self.assertIsNone(error)
        self.assertEqual(summary["api_error"], 1)
        self.assertEqual(summary["skipped_quota"], 0)
        resolve_location.assert_called_once()
        record_coord_meta.assert_not_called()
        update_pin.assert_not_called()
        sync_flag.assert_not_called()
        insert_flag.assert_not_called()

        update_call = next(
            call for call in cursor.execute.call_args_list
            if "UPDATE official_registry SET" in call.args[0]
        )
        self.assertIn("resolveKey = COALESCE(%s, resolveKey)", update_call.args[0])
        self.assertEqual(update_call.args[1][5:7], (13.96, 121.11))
        self.assertIsNone(update_call.args[1][11])

    def test_sync_moves_existing_pin_when_changed_business_data_resolves(self):
        existing = {
            "businessID": "BIZ-1",
            "latitude": 13.96,
            "longitude": 121.11,
            "coordSource": "geocode",
            "matchStatus": "auto",
            "resolveKey": "old-key",
        }
        cursor = MagicMock()
        cursor.fetchone.return_value = existing
        cursor.rowcount = 1
        mysql = MagicMock()
        mysql.connection.cursor.return_value = cursor
        frame = pd.DataFrame([{
            "Business ID": "BIZ-1",
            "businessName": "Updated Pharmacy",
            "businessAddress": "New Main Street",
            "barangay": "Barangay I",
            "lineOfBusiness": "Pharmacy",
            "applicationStatus": "Active",
        }])
        usage = {
            "text_search": {"day": 4, "month": 11},
            "details": {"day": 0, "month": 0},
            "geocoding": {"day": 1, "month": 4},
        }
        with (
            patch.object(service, "mysql", mysql),
            patch.object(service.pd, "read_csv", return_value=frame),
            patch.object(service, "_load_barangay_lookup", return_value={"Barangay I": 1}),
            patch.object(service, "_resolve_barangay_id", return_value=1),
            patch.object(service, "is_cancelled", return_value=False),
            patch.object(service.places_resolver, "reset_run_state"),
            patch.object(service.places_resolver, "compute_resolve_key", return_value="new-key"),
            patch.object(
                service,
                "_resolve_location",
                return_value=(
                    13.9667, 121.1167,
                    {
                        "coord_source": "places",
                        "place_id": "new-place",
                        "place_id_kind": "poi",
                        "score": 0.92,
                        "match_status": "auto",
                        "resolve_key": "new-key",
                    },
                ),
            ),
            patch.object(service.places_resolver, "record_coord_meta"),
            patch.object(service.places_resolver, "_update_pin") as update_pin,
            patch.object(service.places_resolver, "get_places_call_usage", return_value=usage),
            patch.object(service, "_sync_flag_color"),
            patch("api.notifications.hub.publish_to_admins"),
        ):
            summary, error = service.sync_registry(BytesIO(b"csv"), ".csv")

        self.assertIsNone(error)
        self.assertEqual(summary["resolved"], 1)
        update_pin.assert_called_once_with(
            cursor, 1, "UPDATED PHARMACY", 13.96, 121.11,
            13.9667, 121.1167, business_id="BIZ-1",
        )


if __name__ == "__main__":
    unittest.main()
