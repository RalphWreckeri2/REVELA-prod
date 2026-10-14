"""Offline tests for the temporary Nearby Search (New) harness."""

import json
from pathlib import Path
import unittest

from shapely.geometry import shape

from api.utils.nearby_barangay_pilot import (
    PILOT_ENABLED_ENV,
    PILOT_MAX_REQUESTS_ENV,
    load_pilot_config,
)
from nearby_new_offline_harness import (
    CannedHttpResponse,
    CannedNearbyHttp,
    GEOJSON_PATH,
    load_authoritative_scope,
    run_offline_nearby_new_harness,
)


def first_barangay():
    collection = json.loads(GEOJSON_PATH.read_text(encoding="utf-8"))
    feature = collection["features"][0]
    representative = shape(feature["geometry"]).representative_point()
    return feature, {
        "barangay_id": 801,
        "barangay_name": feature["properties"]["ADM4_EN"],
    }, representative


def config(limit="5", enabled="1"):
    return load_pilot_config({
        PILOT_ENABLED_ENV: enabled,
        PILOT_MAX_REQUESTS_ENV: limit,
    })


def canned_response(status=200, places=None):
    return CannedHttpResponse(
        status_code=status,
        body={"places": list(places or [])},
    )


class TemporaryNearbyNewOfflineHarnessTests(unittest.TestCase):

    def setUp(self):
        self.feature, self.catalog_row, self.point = first_barangay()
        self.catalog = [self.catalog_row]
        self.request = {
            "request_id": "synthetic-request-1",
            "latitude": self.point.y,
            "longitude": self.point.x,
            "attempt_kinds": ["initial"],
        }

    def run_harness(self, *, responses, **overrides):
        arguments = {
            "config": config(),
            "persisted_authorized": True,
            "live_confirmation": True,
            "selected_barangay_id": self.catalog_row["barangay_id"],
            "barangay_catalog": self.catalog,
            "requested_budget": 5,
            "scan_requests": [self.request],
            "canned_http": CannedNearbyHttp(responses),
        }
        arguments.update(overrides)
        return run_offline_nearby_new_harness(**arguments)

    def test_authorized_run_loads_real_polygon_and_filters_canned_places(self):
        scope = load_authoritative_scope(
            self.catalog_row["barangay_id"],
            self.catalog,
        )
        self.assertEqual(scope.barangay_id, self.catalog_row["barangay_id"])

        result = self.run_harness(responses={
            self.request["request_id"]: [canned_response(places=[
                {
                    "id": "place-in",
                    "displayName": {"text": "Synthetic in-scope shop"},
                    "location": {
                        "latitude": self.point.y,
                        "longitude": self.point.x,
                    },
                },
                {
                    "id": "place-out",
                    "location": {"latitude": 0, "longitude": 0},
                },
            ])],
        })

        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["budget"]["attempts_reserved"], 1)
        self.assertEqual(result["mock_http_call_count"], 1)
        self.assertEqual(result["database_writes"], 0)
        decisions = {item["place_id"]: item for item in result["places"]}
        self.assertTrue(decisions["place-in"]["permitted_operations"])
        self.assertEqual(
            decisions["place-out"]["rejection_reason"],
            "place_outside_barangay_scope",
        )

    def test_invalid_or_ambiguous_barangay_mapping_fails_closed(self):
        duplicate_id_catalog = [self.catalog_row, dict(self.catalog_row)]
        mock = CannedNearbyHttp({
            self.request["request_id"]: [canned_response()],
        })
        result = run_offline_nearby_new_harness(
            config=config(),
            persisted_authorized=True,
            live_confirmation=True,
            selected_barangay_id=self.catalog_row["barangay_id"],
            barangay_catalog=duplicate_id_catalog,
            requested_budget=1,
            scan_requests=[self.request],
            canned_http=mock,
        )
        self.assertEqual(result["status"], "denied")
        self.assertEqual(result["mock_http_call_count"], 0)

        missing = run_offline_nearby_new_harness(
            config=config(),
            persisted_authorized=True,
            live_confirmation=True,
            selected_barangay_id=999999,
            barangay_catalog=self.catalog,
            requested_budget=1,
            scan_requests=[self.request],
            canned_http=mock,
        )
        self.assertEqual(missing["status"], "denied")
        self.assertEqual(missing["mock_http_call_count"], 0)

    def test_out_of_scope_registry_and_flag_conflicts_are_rejected(self):
        result = self.run_harness(
            responses={
                self.request["request_id"]: [canned_response(places=[
                    {
                        "id": "cross-registry",
                        "location": {
                            "latitude": self.point.y,
                            "longitude": self.point.x,
                        },
                    },
                    {
                        "id": "cross-flag",
                        "location": {
                            "latitude": self.point.y,
                            "longitude": self.point.x,
                        },
                    },
                    {
                        "id": "outside",
                        "location": {"latitude": 0, "longitude": 0},
                    },
                ])],
            },
            registry_records=[{
                "place_id": "cross-registry",
                "barangay_id": 900,
            }],
            existing_flags=[{
                "place_id": "cross-flag",
                "barangay_id": 900,
            }],
        )
        reasons = {
            item["place_id"]: item["rejection_reason"]
            for item in result["places"]
        }
        self.assertEqual(
            reasons["cross-registry"],
            "registry_candidate_outside_barangay_scope",
        )
        self.assertEqual(
            reasons["cross-flag"],
            "existing_flag_outside_barangay_scope",
        )
        self.assertEqual(reasons["outside"], "place_outside_barangay_scope")
        self.assertEqual(result["budget"]["attempts_reserved"], 1)

    def test_budget_exhaustion_stops_mock_http_and_caps_total_attempts(self):
        requests = [
            dict(self.request),
            {
                **self.request,
                "request_id": "synthetic-request-2",
                "attempt_kinds": ["initial"],
            },
        ]
        mock = CannedNearbyHttp({
            request["request_id"]: [canned_response(places=[])]
            for request in requests
        })
        result = self.run_harness(
            responses={
                request["request_id"]: [canned_response(places=[])]
                for request in requests
            },
            config=config(limit="1"),
            requested_budget=1,
            scan_requests=requests,
            canned_http=mock,
        )
        self.assertEqual(result["status"], "budget_exhausted")
        self.assertEqual(result["budget"]["attempts_reserved"], 1)
        self.assertEqual(result["mock_http_call_count"], 1)
        self.assertEqual(len(mock.calls), 1)

    def test_mocked_http_failure_consumes_attempt_and_retry_can_succeed(self):
        inside = {
            "id": "retry-place",
            "location": {
                "latitude": self.point.y,
                "longitude": self.point.x,
            },
        }
        self.request["attempt_kinds"] = ["initial", "retry"]
        result = self.run_harness(
            responses={
                self.request["request_id"]: [
                    canned_response(status=503),
                    canned_response(places=[inside]),
                ],
            },
            requested_budget=2,
        )
        self.assertEqual(result["status"], "completed_with_attempt_failures")
        self.assertEqual(result["budget"]["attempts_reserved"], 2)
        self.assertEqual(result["budget"]["remaining"], 0)
        self.assertEqual(result["mock_http_call_count"], 2)
        self.assertEqual(
            [attempt["outcome"] for attempt in result["attempts"]],
            ["failed", "success"],
        )
        self.assertTrue(result["places"][0]["permitted_operations"])

    def test_unauthorized_and_out_of_scope_scan_requests_never_call_http(self):
        unauthorized = self.run_harness(
            responses={
                self.request["request_id"]: [canned_response()],
            },
            persisted_authorized=False,
        )
        self.assertEqual(unauthorized["status"], "denied")
        self.assertEqual(unauthorized["mock_http_call_count"], 0)

        outside_request = {
            **self.request,
            "latitude": 0,
            "longitude": 0,
        }
        outside = self.run_harness(
            responses={
                outside_request["request_id"]: [canned_response()],
            },
            scan_requests=[outside_request],
        )
        self.assertEqual(outside["status"], "denied")
        self.assertEqual(outside["mock_http_call_count"], 0)

    def test_duplicate_places_across_mocked_responses_are_not_reprocessed(self):
        place = {
            "id": "duplicate",
            "location": {
                "latitude": self.point.y,
                "longitude": self.point.x,
            },
        }
        requests = [
            dict(self.request),
            {
                **self.request,
                "request_id": "synthetic-request-2",
            },
        ]
        result = self.run_harness(
            responses={
                request["request_id"]: [canned_response(places=[place])]
                for request in requests
            },
            scan_requests=requests,
            requested_budget=2,
        )
        self.assertEqual(len(result["places"]), 2)
        self.assertIsNone(result["places"][0]["rejection_reason"])
        self.assertEqual(
            result["places"][1]["rejection_reason"],
            "duplicate_place_in_run",
        )
        self.assertEqual(result["database_writes"], 0)


if __name__ == "__main__":
    unittest.main()
