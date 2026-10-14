import unittest
from unittest.mock import Mock, patch

import requests

from api.registry import service


def response(status="OK", results=None):
    result = Mock()
    result.status_code = 200
    result.json.return_value = {"status": status, "results": results or []}
    return result


class YellowFlagAddressSearchTests(unittest.TestCase):
    def setUp(self):
        environ = patch.dict("os.environ", {"GOOGLE_MAPS_API_KEY": "offline-test-key"})
        environ.start()
        self.addCleanup(environ.stop)
        key = patch.object(service, "GOOGLE_MAPS_API_KEY", "offline-test-key")
        key.start()
        self.addCleanup(key.stop)
        self.get = Mock(return_value=response("ZERO_RESULTS"))
        self.reserve = Mock(return_value=True)

    def search(self, address="Main Street", barangay="Barangay II"):
        return service.search_address_candidates(
            address, barangay, get=self.get, reserve=self.reserve,
        )

    def reverse(self, lat=13.96, lng=121.11):
        return service.reverse_geocode_coordinates(
            lat, lng, get=self.get, reserve=self.reserve,
        )

    def test_address_search_returns_client_candidate_contract(self):
        self.get.return_value = response(results=[{
            "formatted_address": "12 Main Street, Barangay II, Philippines",
            "place_id": "place-1", "geometry": {"location": {"lat": 13.96, "lng": 121.11}},
        }])
        matches, error = self.search("12 Main Street")
        self.assertIsNone(error)
        self.assertEqual(matches, [{
            "formattedAddress": "12 Main Street, Barangay II, Philippines",
            "latitude": 13.96, "longitude": 121.11, "placeId": "place-1",
        }])
        params = self.get.call_args.kwargs["params"]
        self.assertEqual(params["address"], "12 Main Street, Barangay II, Mataasnakahoy, Batangas, Philippines")
        self.assertEqual(params["components"], "country:PH")
        self.assertEqual(params["region"], "ph")
        self.reserve.assert_called_once()

    def test_search_without_barangay_still_scopes_to_municipality(self):
        self.search("115 Templo Avenue", None)
        self.assertEqual(self.get.call_args.kwargs["params"]["address"],
                         "115 Templo Avenue, Mataasnakahoy, Batangas, Philippines")

    def test_no_results_never_fabricates_coordinates_or_address(self):
        self.assertEqual(self.search(), ([], None))
        self.assertEqual(self.reverse(), (None, None))

    def test_unavailable_quota_calls_neither_provider(self):
        self.reserve.return_value = False
        self.assertEqual(self.search(), (None, "quota_exceeded"))
        self.assertEqual(self.reverse(), (None, "quota_exceeded"))
        self.get.assert_not_called()

    def test_missing_key_does_not_reserve_or_call_provider(self):
        with patch.dict("os.environ", {"GOOGLE_MAPS_API_KEY": ""}), \
                patch.object(service, "GOOGLE_MAPS_API_KEY", ""):
            self.assertEqual(self.search(), (None, "not_configured"))
            self.assertEqual(self.reverse(), (None, "not_configured"))
        self.reserve.assert_not_called()
        self.get.assert_not_called()

    def test_invalid_coordinates_fail_before_quota_or_provider(self):
        for lat, lng in ((True, 121), ("13.96", 121), (91, 121), (14, 181),
                         (float("nan"), 121), (14, float("inf")), (10 ** 10000, 121)):
            self.assertEqual(self.reverse(lat, lng), (None, "invalid_request"))
        self.reserve.assert_not_called()
        self.get.assert_not_called()

    def test_reverse_geocoding_returns_selected_formatted_address(self):
        self.get.return_value = response(results=[{
            "formatted_address": "115 Templo Avenue, Barangay II, Philippines",
        }])
        self.assertEqual(self.reverse(), ("115 Templo Avenue, Barangay II, Philippines", None))
        self.assertEqual(self.get.call_args.kwargs["params"]["latlng"], "13.960000,121.110000")

    def test_provider_quota_errors_are_preserved(self):
        for status in ("OVER_DAILY_LIMIT", "OVER_QUERY_LIMIT"):
            self.get.return_value = response(status)
            self.assertEqual(self.search(), (None, "quota_exceeded"))
            self.assertEqual(self.reverse(), (None, "quota_exceeded"))

    def test_network_errors_are_classified_without_logging_exception_secrets(self):
        self.get.side_effect = requests.RequestException("key=do-not-log-this-test-marker")
        with patch("builtins.print") as log:
            self.assertEqual(self.search(), (None, "network_error"))
            self.assertEqual(self.reverse(), (None, "network_error"))
        self.assertNotIn("do-not-log-this-test-marker", str(log.call_args_list))

    def test_http_and_malformed_provider_responses_are_errors(self):
        self.get.return_value.status_code = 403
        self.assertEqual(self.search(), (None, "provider_error"))
        self.assertEqual(self.reverse(), (None, "provider_error"))
        self.get.return_value.status_code = 200
        for data in ([], {"status": "REQUEST_DENIED"}, {"status": "OK", "results": {}}):
            self.get.return_value.json.return_value = data
            self.assertEqual(self.search(), (None, "provider_error"))
            self.assertEqual(self.reverse(), (None, "provider_error"))
        self.get.return_value.json.side_effect = ValueError("not JSON")
        self.assertEqual(self.search(), (None, "provider_error"))
        self.assertEqual(self.reverse(), (None, "provider_error"))

    def test_search_filters_invalid_candidates_and_caps_results_at_five(self):
        valid = {"formatted_address": "Main Street", "place_id": "place-1",
                 "geometry": {"location": {"lat": 13.96, "lng": 121.11}}}
        self.get.return_value = response(results=[
            None, {"geometry": []}, {"geometry": {"location": {"lat": "NaN", "lng": 121}}},
            {"geometry": {"location": {"lat": 10 ** 10000, "lng": 121}}},
            *[valid] * 8,
        ])
        matches, error = self.search()
        self.assertIsNone(error)
        self.assertEqual(len(matches), 5)

    def test_empty_address_fails_before_reservation(self):
        self.assertEqual(self.search(" "), (None, "invalid_request"))
        self.reserve.assert_not_called()
        self.get.assert_not_called()
