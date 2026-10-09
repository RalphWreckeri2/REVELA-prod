from api.registry.places_resolver import (
    compute_resolve_key,
    compute_places_refresh_key,
    _is_within_municipal_bounds,
    _places_request,
    _text_search,
    reset_run_state,
    resolve_location,
    decide_review,
)
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..")))


class PlacesResolverHardeningTests(unittest.TestCase):

    def setUp(self):
        from api.registry import places_resolver

        reset_run_state()
        places_resolver._last_places_request_at = 0

    @patch("api.registry.places_resolver.time.sleep")
    def test_resource_exhausted_429_stops_without_retry(self, mock_sleep):
        from api.registry import places_resolver

        reset_run_state()
        places_resolver._last_places_request_at = 0
        response = MagicMock()
        response.status_code = 429
        response.text = '{"error":{"status":"RESOURCE_EXHAUSTED"}}'
        request = MagicMock(return_value=response)
        reserve = MagicMock(return_value=True)

        result = _places_request("TextSearch", request, reserve)

        self.assertIsNone(result)
        request.assert_called_once()
        reserve.assert_called_once()
        self.assertEqual(places_resolver._api_state.outcome, "skipped_quota")
        mock_sleep.assert_not_called()

    @patch("api.registry.places_resolver.random.uniform", return_value=1.0)
    @patch("api.registry.places_resolver.time.sleep")
    def test_per_minute_429_retries_three_times_and_counts_each_attempt(
        self, mock_sleep, _mock_uniform
    ):
        from api.registry import places_resolver

        reset_run_state()
        places_resolver._last_places_request_at = 0
        limited = MagicMock()
        limited.status_code = 429
        limited.text = '{"error":{"status":"RESOURCE_EXHAUSTED","quotaId":"RequestsPerMinute"}}'
        success = MagicMock()
        success.status_code = 200
        success.json.return_value = {"places": []}
        request = MagicMock(side_effect=[limited, limited, limited, success])
        reserve = MagicMock(return_value=True)

        result = _places_request("TextSearch", request, reserve)

        self.assertEqual(result, {"places": []})
        self.assertEqual(request.call_count, 4)
        self.assertEqual(reserve.call_count, 4)
        self.assertIsNone(places_resolver._api_state.outcome)
        self.assertGreaterEqual(mock_sleep.call_count, 3)

    @patch("api.registry.places_resolver.random.uniform", return_value=1.0)
    @patch("api.registry.places_resolver.time.sleep")
    def test_per_minute_429_exhaustion_is_api_error_not_daily_quota(
        self, _mock_sleep, _mock_uniform
    ):
        from api.registry import places_resolver

        reset_run_state()
        places_resolver._last_places_request_at = 0
        response = MagicMock()
        response.status_code = 429
        response.text = '{"error":{"status":"RESOURCE_EXHAUSTED","quotaId":"RequestsPerMinute"}}'
        request = MagicMock(return_value=response)
        reserve = MagicMock(return_value=True)

        result = _places_request("TextSearch", request, reserve)

        self.assertIsNone(result)
        self.assertEqual(request.call_count, 4)
        self.assertEqual(reserve.call_count, 4)
        self.assertEqual(places_resolver._api_state.outcome, "api_error")
        self.assertFalse(places_resolver._api_state.quota_halted)

    @patch.dict(os.environ, {"GOOGLE_MAPS_API_KEY": "dummy_test_key"})
    @patch("api.registry.places_resolver.time.sleep")
    @patch("api.registry.places_resolver.reserve_call", return_value=True)
    @patch("api.registry.places_resolver.mysql")
    def test_quota_429_is_not_a_no_match_or_geocode_fallback(
        self, mock_mysql, _mock_reserve, _mock_sleep
    ):
        mock_cursor = MagicMock()
        mock_mysql.connection.cursor.return_value = mock_cursor
        mock_cursor.fetchone.return_value = None
        mock_cursor.fetchall.return_value = []

        response = MagicMock()
        response.status_code = 429
        response.text = '{"error":{"status":"RESOURCE_EXHAUSTED"}}'
        post = MagicMock(return_value=response)
        geocode_reservation = MagicMock(return_value=True)

        lat, lng, meta = resolve_location(
            "No Match Store", "Poblacion", "Barangay I",
            business_id="BIZ-429", barangay_id=1, _post=post,
            reserve_geocode=geocode_reservation,
        )

        self.assertIsNone(lat)
        self.assertIsNone(lng)
        self.assertEqual(meta["reason"], "skipped_quota")
        post.assert_called_once()
        geocode_reservation.assert_not_called()

    @patch.dict(os.environ, {"GOOGLE_MAPS_API_KEY": "dummy_test_key"})
    def test_daily_quota_halt_persists_across_resolver_calls(self):
        from api.registry import places_resolver

        reset_run_state()
        places_resolver._api_state.quota_halted = True
        post = MagicMock()

        lat, lng, meta = resolve_location(
            "Next Store", "Poblacion", "Barangay I", _post=post
        )

        self.assertIsNone(lat)
        self.assertIsNone(lng)
        self.assertEqual(meta["reason"], "skipped_quota")
        post.assert_not_called()
        reset_run_state()

    @patch("api.registry.places_resolver.mysql")
    def test_monthly_quota_reservation_has_distinct_status(self, mock_mysql):
        from api.registry import places_resolver

        reset_run_state()
        places_resolver._table_ready = True
        cursor = MagicMock()
        cursor.rowcount = 0
        mock_mysql.connection.cursor.return_value = cursor

        self.assertFalse(places_resolver.reserve_call("imp_ts", 2500, 500))
        self.assertEqual(
            places_resolver._api_state.quota_reason, "monthly_quota_exceeded"
        )
        reset_run_state()

    @patch.dict(os.environ, {"GOOGLE_MAPS_API_KEY": "dummy_test_key"})
    @patch("api.registry.places_resolver.reserve_call", return_value=False)
    @patch("api.registry.places_resolver._places_request")
    @patch("api.registry.places_resolver.mysql")
    def test_place_details_reservation_uses_daily_and_monthly_caps(
        self, mock_mysql, mock_places_request, mock_reserve
    ):
        from api.registry import places_resolver

        reset_run_state()
        cursor = MagicMock()
        cursor.fetchall.return_value = [{
            "businessID": 1,
            "barangayID": 1,
            "businessName": "Test Business",
            "latitude": 13.96,
            "longitude": 121.11,
            "placeID": "place-id",
        }]
        mock_mysql.connection.cursor.return_value = cursor
        mock_places_request.side_effect = (
            lambda _label, _request, reserve: (reserve(), None)[1]
        )

        places_resolver.refresh_expired_coords(limit=1)

        mock_reserve.assert_called_once_with(
            "imp_pd", places_resolver.PD_MONTHLY_CAP, places_resolver.PD_DAILY_CAP
        )
        cursor.close.assert_called_once()
        reset_run_state()

    def test_compute_resolve_key_deterministic(self):
        """compute_resolve_key must return a 40-char SHA-1 hex digest normalized across case and spacing."""
        key1 = compute_resolve_key("Silva's Pharmacy", "  Poblacion  ", 1)
        key2 = compute_resolve_key("silva's pharmacy", "poblacion", "1")
        self.assertEqual(len(key1), 40)
        self.assertEqual(key1, key2)

        key3 = compute_resolve_key("Silva's Pharmacy", "Barangay II", 2)
        self.assertNotEqual(key1, key3)

    @patch.dict(os.environ, {"GOOGLE_MAPS_API_KEY": "dummy_test_key"})
    def test_text_search_field_mask_excludes_enterprise(self):
        """Text Search must request only Pro-tier fields and exclude all Enterprise tier fields."""
        reset_run_state()
        from api.registry import places_resolver
        places_resolver._last_places_request_at = 0
        mock_post = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"places": []}
        mock_post.return_value = mock_resp

        _text_search("Silva Pharmacy", "Poblacion",
                     "Barangay I", post=mock_post)

        self.assertTrue(mock_post.called)
        headers = mock_post.call_args[1].get("headers", {})
        mask = headers.get("X-Goog-FieldMask", "")

        # Verify allowed pro fields
        self.assertIn("places.id", mask)
        self.assertIn("places.displayName", mask)
        self.assertIn("places.location", mask)
        self.assertIn("places.primaryType", mask)
        self.assertIn("places.types", mask)

        # Strictly verify Enterprise tier fields are NOT present
        enterprise_fields = [
            "rating",
            "userRatingCount",
            "regularOpeningHours",
            "websiteUri",
            "reviews",
            "photos",
        ]
        for ef in enterprise_fields:
            self.assertNotIn(ef, mask)

    def test_municipal_bounds_screening(self):
        """Screening must accept Mataasnakahoy coordinates and reject out-of-town POIs."""
        # Inside Mataasnakahoy center & Poblacion
        self.assertTrue(_is_within_municipal_bounds(13.9667, 121.1167))
        self.assertTrue(_is_within_municipal_bounds(13.9610, 121.1110))

        # Outside: Calaca (~35km away)
        self.assertFalse(_is_within_municipal_bounds(13.9300, 120.8100))

        # Outside: Manila (~75km away)
        self.assertFalse(_is_within_municipal_bounds(14.5995, 120.9842))

        # Edge cases: None or invalid
        self.assertFalse(_is_within_municipal_bounds(None, None))
        self.assertFalse(_is_within_municipal_bounds("invalid", "coords"))

    @patch.dict(os.environ, {"GOOGLE_MAPS_API_KEY": "dummy_test_key"})
    @patch("api.registry.places_resolver.mysql")
    def test_resolve_key_cache_consumes_zero_api_calls(self, mock_mysql):
        """When resolveKey in DB matches computed hash, resolver must return cached coordinates without calling API."""
        curr_key = compute_resolve_key("Silva Pharmacy", "Poblacion", 1)

        mock_cursor = MagicMock()
        mock_mysql.connection.cursor.return_value = mock_cursor
        mock_cursor.fetchone.return_value = {
            "resolveKey": curr_key,
            "latitude": 13.9620,
            "longitude": 121.1120,
            "coordSource": "places",
            "placeID": "place_cached_123",
            "placeIDKind": "poi",
            "matchScore": 0.95,
            "matchStatus": "auto"
        }

        mock_post = MagicMock()
        lat, lng, meta = resolve_location(
            "Silva Pharmacy", "Poblacion", "Barangay I",
            business_id="BIZ-CACHE-01", barangay_id=1,
            _post=mock_post
        )

        # HTTP request must NEVER be made
        mock_post.assert_not_called()
        self.assertEqual(lat, 13.9620)
        self.assertEqual(lng, 121.1120)
        self.assertEqual(meta["match_type"], "cached_resolve_key")
        self.assertEqual(meta["place_id"], "place_cached_123")

    @patch.dict(os.environ, {"GOOGLE_MAPS_API_KEY": "dummy_test_key"})
    @patch("api.registry.places_resolver.reserve_call", return_value=True)
    @patch("api.registry.places_resolver.mysql")
    def test_places_refresh_rechecks_cached_geocode_without_geocode_fallback(
        self, mock_mysql, mock_reserve
    ):
        """A prior geocode key must not suppress a Places lookup during pin refresh."""
        mock_cursor = MagicMock()
        mock_mysql.connection.cursor.return_value = mock_cursor
        mock_cursor.fetchone.return_value = {
            "resolveKey": compute_resolve_key("Silva Pharmacy", "Poblacion", 1),
            "latitude": 13.9620,
            "longitude": 121.1120,
            "coordSource": "geocode",
            "placeID": None,
            "placeIDKind": "address",
            "matchScore": None,
            "matchStatus": "auto",
            "lineOfBusiness": "Pharmacy",
        }
        mock_cursor.fetchall.return_value = []

        mock_post = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "places": [{
                "id": "place_silva_pharmacy",
                "displayName": {"text": "Silva Pharmacy"},
                "location": {"latitude": 13.9667, "longitude": 121.1167},
                "types": ["pharmacy"],
            }]
        }
        mock_post.return_value = mock_resp
        mock_geocode_reservation = MagicMock(return_value=True)

        lat, lng, meta = resolve_location(
            "Silva Pharmacy", "Poblacion", "Barangay I",
            business_id="BIZ-GEOCODE-01", barangay_id=1,
            line_of_business="Pharmacy", refresh_geocode=True,
            reserve_geocode=mock_geocode_reservation, _post=mock_post,
        )

        self.assertEqual((lat, lng), (13.9667, 121.1167))
        self.assertEqual(meta["coord_source"], "places")
        self.assertEqual(meta["resolve_key"], compute_places_refresh_key(
            "Silva Pharmacy", "Poblacion", 1
        ))
        mock_post.assert_called_once()
        mock_geocode_reservation.assert_not_called()
        mock_reserve.assert_called_once()

    @patch.dict(os.environ, {"GOOGLE_MAPS_API_KEY": "dummy_test_key"})
    @patch("api.registry.places_resolver.reserve_call")
    @patch("api.registry.places_resolver.mysql")
    def test_quota_guard_fails_closed(self, mock_mysql, mock_reserve):
        """When quota is exhausted, resolver must fail closed without making HTTP calls."""
        mock_cursor = MagicMock()
        mock_mysql.connection.cursor.return_value = mock_cursor
        mock_cursor.fetchone.return_value = None  # No cache hit
        mock_cursor.fetchall.return_value = []   # No rejected places

        mock_reserve.return_value = False  # Quota exhausted
        mock_post = MagicMock()

        lat, lng, meta = resolve_location(
            "New Store", "Poblacion", "Barangay I",
            business_id="BIZ-NEW-01", barangay_id=1,
            _post=mock_post
        )

        mock_post.assert_not_called()
        self.assertIsNone(lat)
        self.assertIsNone(lng)

    @patch.dict(os.environ, {"GOOGLE_MAPS_API_KEY": "dummy_test_key"})
    @patch("api.registry.places_resolver.reserve_call")
    @patch("api.registry.places_resolver.mysql")
    def test_rejected_place_candidate_discarded(self, mock_mysql, mock_reserve):
        """Candidate present in registry_rejected_places must be discarded and flagged for review."""
        mock_cursor = MagicMock()
        mock_mysql.connection.cursor.return_value = mock_cursor
        mock_cursor.fetchone.return_value = None  # No resolveKey cache hit
        # registry_rejected_places returns bad_place_xyz for this business
        mock_cursor.fetchall.return_value = [{"placeID": "bad_place_xyz"}]

        mock_reserve.return_value = True

        mock_post = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "places": [
                {
                    "id": "bad_place_xyz",
                    "displayName": {"text": "Silva Pharmacy"},
                    "location": {"latitude": 13.9620, "longitude": 121.1120},
                    "types": ["pharmacy"]
                }
            ]
        }
        mock_post.return_value = mock_resp

        lat, lng, meta = resolve_location(
            "Silva Pharmacy", "Poblacion", "Barangay I",
            business_id="BIZ-REJ-01", barangay_id=1,
            _post=mock_post
        )

        # The candidate was rejected, so coordinates must not be snapped
        self.assertIsNone(lat)
        self.assertIsNone(lng)
        self.assertEqual(meta["match_status"], "review")
        self.assertEqual(meta["match_type"], "rejected_place_discarded")

    @patch("api.registry.places_resolver.mysql")
    def test_decide_review_rejection_records_into_rejected_places(self, mock_mysql):
        """When an admin rejects a review candidate, the placeID must be inserted into registry_rejected_places."""
        mock_cursor = MagicMock()
        mock_mysql.connection.cursor.return_value = mock_cursor
        mock_cursor.fetchone.return_value = {
            "barangayID": 1,
            "businessName": "Silva Pharmacy",
            "latitude": 13.9620,
            "longitude": 121.1120,
            "placeID": "bad_place_abc"
        }

        ok, err = decide_review("BIZ-REV-01", approve=False)
        self.assertTrue(ok, err)
        self.assertIsNone(err)

        insert_calls = [
            c for c in mock_cursor.execute.call_args_list
            if "INSERT IGNORE INTO registry_rejected_places" in c[0][0]
        ]
        self.assertEqual(len(insert_calls), 1)
        sql, params = insert_calls[0][0][0], insert_calls[0][0][1]
        self.assertEqual(params, ("BIZ-REV-01", "bad_place_abc"))


if __name__ == "__main__":
    unittest.main()
