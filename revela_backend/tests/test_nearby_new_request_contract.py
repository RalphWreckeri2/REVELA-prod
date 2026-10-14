"""Offline contract tests for the existing Nearby Search (New) helper."""

import os
import unittest
from unittest.mock import MagicMock, patch

from api.flags import service


FAKE_API_KEY = "offline-contract-test-key"
CAPS = {
    "quota.nearby_new.daily": 7,
    "quota.nearby_new.monthly": 31,
    "run_detection.max_seconds": 90,
    "run_detection.max_requests": 8,
}


class NearbyNewRequestContractTests(unittest.TestCase):

    def setUp(self):
        service._places_run_state.calls = {
            "new_nearby": 0,
            "new_nearby_initial": 0,
            "new_nearby_adaptive": 0,
        }
        service._places_run_state.query_kind = "initial"
        service._places_run_state.api_errors = 0
        service._places_run_state.started_at = None

    def _patch_request_boundary(
        self,
        *,
        responses=(),
        reservation=(True, None),
        daily=7,
        monthly=31,
        detector=False,
    ):
        response = MagicMock()
        if responses:
            post = patch(
                "api.flags.service.http.post",
                side_effect=list(responses),
            )
        else:
            post = patch("api.flags.service.http.post", return_value=response)
        overrides = {
            **CAPS,
            "quota.nearby_new.daily": daily,
            "quota.nearby_new.monthly": monthly,
        }
        return (
            patch.dict(os.environ, {
                "GOOGLE_MAPS_API_KEY": FAKE_API_KEY,
            }, clear=True),
            patch("api.flags.service.mysql", MagicMock()),
            patch("api.flags.service.reserve_usage_slot",
                  return_value=reservation),
            patch("api.flags.service.quota_settings.cap",
                  side_effect=overrides.__getitem__),
            post,
            patch("api.flags.service._detection_work_budget_reached",
                  return_value=detector),
            patch("api.flags.service.test_mode.is_enabled",
                  return_value=False),
            patch("api.flags.service.time.sleep"),
            patch("api.flags.service.random.uniform", return_value=1.0),
            patch("api.flags.service._nearby_last_request_at", 0),
        )

    def _run(self, patches, lat=13.9667, lng=121.1167, radius=850):
        with (
            patches[0],
            patches[1],
            patches[2] as reserve,
            patches[3],
            patches[4] as post,
            patches[5],
            patches[6],
            patches[7] as sleep,
            patches[8],
            patches[9],
        ):
            result = service._new_nearby_request(lat, lng, radius)
        return result, post, reserve, sleep

    def test_success_request_contract_endpoint_body_field_mask_and_parser(self):
        response = MagicMock(status_code=200, text="")
        response.json.return_value = {
            "places": [{
                "id": "places/offline-1",
                "displayName": {"text": "Synthetic Market"},
                "location": {"latitude": 13.97, "longitude": 121.12},
                "primaryType": "convenience_store",
                "businessStatus": "OPERATIONAL",
                "formattedAddress": "Synthetic address",
            }],
            "nextPageToken": "ignored-by-current-single-response-implementation",
        }
        with patch.object(service, "NEW_NEARBY_RESULT_LIMIT", 17), \
                patch.object(service, "NEW_NEARBY_EXCLUDED_TYPES",
                             ("school", "library")):
            result, post, reserve, _sleep = self._run(
                self._patch_request_boundary(responses=[response]),
                lat=13.97,
                lng=121.12,
                radius=640,
            )

        places, complete = result
        self.assertTrue(complete)
        self.assertEqual(places, [{
            "place_id": "places/offline-1",
            "name": "Synthetic Market",
            "geometry": {
                "location": {"lat": 13.97, "lng": 121.12},
            },
            "vicinity": "Synthetic address",
            "primaryType": "convenience_store",
            "types": ["convenience_store"],
            "business_status": "OPERATIONAL",
        }])
        post.assert_called_once()
        args, kwargs = post.call_args
        self.assertEqual(args, (service.NEW_NEARBY_URL,))
        self.assertEqual(
            service.NEW_NEARBY_URL,
            "https://places.googleapis.com/v1/places:searchNearby",
        )
        self.assertEqual(kwargs["headers"], {
            "Content-Type": "application/json",
            "X-Goog-Api-Key": FAKE_API_KEY,
            "X-Goog-FieldMask": service.NEW_NEARBY_FIELD_MASK,
        })
        self.assertEqual(kwargs["headers"]["X-Goog-FieldMask"], (
            "places.id,places.displayName,places.location,"
            "places.primaryType,places.businessStatus,places.formattedAddress"
        ))
        self.assertEqual(kwargs["json"], {
            "excludedTypes": ["school", "library"],
            "maxResultCount": 17,
            "locationRestriction": {
                "circle": {
                    "center": {"latitude": 13.97, "longitude": 121.12},
                    "radius": 640,
                },
            },
        })
        self.assertEqual(kwargs["timeout"], 10)
        self.assertNotIn("pageToken", kwargs["json"])
        reserve.assert_called_once()
        self.assertEqual(reserve.call_args.args[1:],
            (
            "new_nearby_month",
            "new_nearby_day",
            31,
            7,
            ))
        self.assertEqual(service._places_run_state.calls["new_nearby"], 1)

    def test_zero_results_are_a_complete_empty_response_without_pagination(self):
        response = MagicMock(status_code=200, text="")
        response.json.return_value = {"places": []}

        result, post, reserve, _sleep = self._run(
            self._patch_request_boundary(responses=[response])
        )

        self.assertEqual(result, ([], True))
        post.assert_called_once()
        reserve.assert_called_once()

    def test_malformed_json_is_incomplete_and_reported_as_api_error(self):
        response = MagicMock(status_code=200, text="not-json")
        response.json.side_effect = ValueError("malformed JSON")

        result, post, reserve, _sleep = self._run(
            self._patch_request_boundary(responses=[response])
        )

        self.assertEqual(result, ([], False))
        post.assert_called_once()
        reserve.assert_called_once()
        self.assertEqual(service._places_run_state.api_errors, 1)

    def test_http_503_is_not_retried_and_attempt_consumes_reservation(self):
        response = MagicMock(status_code=503, text="simulated unavailable")

        result, post, reserve, _sleep = self._run(
            self._patch_request_boundary(responses=[response])
        )

        self.assertEqual(result, ([], False))
        post.assert_called_once()
        reserve.assert_called_once()
        self.assertEqual(service._places_run_state.calls["new_nearby"], 1)
        self.assertEqual(service._places_run_state.api_errors, 1)

    def test_per_minute_429_retries_and_reserves_each_http_attempt(self):
        throttled = MagicMock(
            status_code=429,
            text='{"error":{"status":"RESOURCE_EXHAUSTED",'
                 '"quotaId":"RequestsPerMinute"}}',
        )
        success = MagicMock(status_code=200, text="")
        success.json.return_value = {"places": []}

        result, post, reserve, sleep = self._run(
            self._patch_request_boundary(responses=[throttled, success])
        )

        self.assertEqual(result, ([], True))
        self.assertEqual(post.call_count, 2)
        self.assertEqual(reserve.call_count, 2)
        self.assertEqual(
            [item.args[1:3] for item in reserve.call_args_list],
            [
                ("new_nearby_month", "new_nearby_day"),
                ("new_nearby_month", "new_nearby_day"),
            ],
        )
        self.assertEqual(service._places_run_state.calls["new_nearby"], 2)
        self.assertEqual(sleep.call_count, 2)

    def test_google_daily_quota_429_raises_without_retry(self):
        exhausted = MagicMock(
            status_code=429,
            text='{"error":{"status":"RESOURCE_EXHAUSTED",'
                 '"message":"daily quota exceeded"}}',
        )

        with self.assertRaises(service.PlacesBudgetExceeded) as raised:
            self._run(self._patch_request_boundary(responses=[exhausted]))

        self.assertEqual(raised.exception.reason, "daily_quota_exceeded")
        # One HTTP attempt only; Google's returned quota error is terminal.
        self.assertEqual(service._places_run_state.calls["new_nearby"], 1)

    def test_local_daily_and_monthly_quota_denials_prevent_http(self):
        for reason in ("daily_quota_exceeded", "monthly_quota_exceeded"):
            with self.subTest(reason=reason):
                post = MagicMock()
                reserve = MagicMock(return_value=(False, reason))
                with (
                    patch.dict(os.environ, {
                        "GOOGLE_MAPS_API_KEY": FAKE_API_KEY,
                    }, clear=True),
                    patch("api.flags.service.mysql", MagicMock()),
                    patch("api.flags.service.reserve_usage_slot", reserve),
                    patch("api.flags.service.quota_settings.cap",
                          side_effect=CAPS.__getitem__),
                    patch("api.flags.service.http.post", post),
                    patch("api.flags.service._detection_work_budget_reached",
                          return_value=False),
                    patch("api.flags.service.test_mode.is_enabled",
                          return_value=False),
                    patch("api.flags.service._nearby_last_request_at", 0),
                ):
                    with self.assertRaises(
                        service.PlacesBudgetExceeded
                    ) as raised:
                        service._new_nearby_request(
                            13.9667, 121.1167, 850
                        )
                self.assertEqual(raised.exception.reason, reason)
                reserve.assert_called_once()
                post.assert_not_called()
                self.assertEqual(service._places_run_state.calls["new_nearby"], 0)

    def test_zero_new_nearby_daily_or_monthly_caps_block_reservation_and_http(self):
        for daily, monthly in ((0, 31), (7, 0)):
            with self.subTest(daily=daily, monthly=monthly):
                post = MagicMock()
                reserve = MagicMock()
                overrides = {
                    **CAPS,
                    "quota.nearby_new.daily": daily,
                    "quota.nearby_new.monthly": monthly,
                }
                with (
                    patch.dict(os.environ, {
                        "GOOGLE_MAPS_API_KEY": FAKE_API_KEY,
                    }, clear=True),
                    patch("api.flags.service.mysql", MagicMock()),
                    patch("api.flags.service.reserve_usage_slot", reserve),
                    patch("api.flags.service.quota_settings.cap",
                          side_effect=overrides.__getitem__),
                    patch("api.flags.service.http.post", post),
                    patch("api.flags.service.test_mode.is_enabled",
                          return_value=False),
                ):
                    with self.assertRaises(service.PlacesBudgetExceeded):
                        service._new_nearby_request(
                            13.9667, 121.1167, 850
                        )

                reserve.assert_not_called()
                post.assert_not_called()

    def test_detection_request_budget_stops_retry_before_second_reservation(self):
        throttled = MagicMock(
            status_code=429,
            text="RESOURCE_EXHAUSTED per minute",
        )
        post = MagicMock(return_value=throttled)
        reserve = MagicMock(return_value=(True, None))
        service._places_run_state.started_at = 99
        caps = {
            **CAPS,
            "run_detection.max_requests": 1,
        }
        with (
            patch.dict(os.environ, {
                "GOOGLE_MAPS_API_KEY": FAKE_API_KEY,
            }, clear=True),
            patch("api.flags.service.mysql", MagicMock()),
            patch("api.flags.service.reserve_usage_slot", reserve),
            patch("api.flags.service.quota_settings.cap",
                  side_effect=caps.__getitem__),
            patch("api.flags.service.http.post", post),
            patch("api.flags.service.test_mode.is_enabled", return_value=False),
            patch("api.flags.service.time.sleep"),
            patch("api.flags.service.time.monotonic", return_value=100),
            patch("api.flags.service.random.uniform", return_value=1.0),
            patch("api.flags.service._nearby_last_request_at", 0),
        ):
            places, complete = service._new_nearby_request(
                13.9667, 121.1167, 850
            )

        self.assertEqual((places, complete), ([], False))
        post.assert_called_once()
        reserve.assert_called_once()
        self.assertEqual(service._places_run_state.calls["new_nearby"], 1)


if __name__ == "__main__":
    unittest.main()
