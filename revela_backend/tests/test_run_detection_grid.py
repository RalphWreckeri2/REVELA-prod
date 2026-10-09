import math
import unittest
from unittest.mock import MagicMock, patch

from api.flags import service


class RunDetectionGridTests(unittest.TestCase):

    def setUp(self):
        service._places_run_state.calls = {
            "legacy_nearby": 0,
            "legacy_nearby_initial": 0,
            "legacy_nearby_adaptive": 0,
            "new_nearby": 0,
            "new_nearby_initial": 0,
            "new_nearby_adaptive": 0,
        }
        service._places_run_state.results_received = 0
        service._places_run_state.duplicate_results = 0
        service._places_run_state.query_kind = "initial"

    @patch("api.flags.service._fetch_point_results_once")
    def test_saturated_nearby_search_refines_dense_area(self, fetch_once):
        fetch_once.side_effect = [
            ([{"place_id": f"root-{i}"} for i in range(60)], True),
            ([{"place_id": "child-1"}], True),
            ([{"place_id": "child-2"}], True),
            ([{"place_id": "child-3"}], True),
            ([{"place_id": "child-4"}], True),
        ]

        results, complete = service._fetch_point_results(13.9667, 121.1167, 850)

        self.assertTrue(complete)
        self.assertEqual(len(results), 64)
        self.assertEqual(fetch_once.call_count, 5)
        self.assertAlmostEqual(fetch_once.call_args_list[1].args[2], 850 * 0.72)

    @patch("api.flags.service._fetch_point_results_once")
    def test_parent_child_duplicates_keep_first_location_and_fill_missing_metadata(
        self, fetch_once
    ):
        root = [
            {
                "place_id": "shared",
                "name": "Known Business",
                "geometry": {"location": {"lat": 13.9667, "lng": 121.1167}},
            }
        ] + [{"place_id": f"root-{i}"} for i in range(19)]
        child_duplicate = {
            "place_id": "shared",
            "name": "New Business Name",
            "geometry": {"location": {"lat": 13.967, "lng": 121.117}},
            "primaryType": "pharmacy",
            "types": ["pharmacy"],
            "business_status": "OPERATIONAL",
        }
        fetch_once.side_effect = [
            (root, True),
            ([child_duplicate], True),
            ([], True),
            ([], True),
            ([], True),
        ]

        with patch.object(service, "RUN_DETECTION_NEARBY_API", "new"):
            results, complete = service._fetch_point_results(
                13.9667, 121.1167, 850
            )

        self.assertTrue(complete)
        self.assertEqual(len(results), 20)
        shared = next(place for place in results if place["place_id"] == "shared")
        self.assertEqual(shared["name"], "Known Business")
        self.assertEqual(
            shared["geometry"]["location"],
            {"lat": 13.9667, "lng": 121.1167},
        )
        self.assertEqual(shared["primaryType"], "pharmacy")
        self.assertEqual(shared["business_status"], "OPERATIONAL")
        self.assertEqual(service._places_run_state.duplicate_results, 1)
        self.assertEqual(service._places_run_state.results_received, 21)

    def test_grid_includes_centers_outside_boundary_for_edge_coverage(self):
        with patch.object(service, "_MUNICIPALITY_BOUNDARY") as boundary:
            boundary.buffer.return_value.contains.return_value = True

            service._grid_points()

        expected_buffer = (service.DETECTION_RADIUS_M / 111_320.0) * 1.1
        boundary.buffer.assert_called_once_with(expected_buffer)

    def test_adaptive_centers_cover_radius_with_smaller_search_circles(self):
        center_lat, center_lng, root_radius = 13.9667, 121.1167, 850
        centers = service._adaptive_nearby_centers(center_lat, center_lng, root_radius)

        self.assertEqual(len(centers), 4)
        child_radius = root_radius * service.ADAPTIVE_QUERY_RADIUS_RATIO
        for _lat, _lng, radius in centers:
            self.assertAlmostEqual(radius, child_radius)

        lng_scale = math.cos(math.radians(center_lat))
        edge_points = [
            (
                center_lat + math.sin(angle) * root_radius / 111_320.0,
                center_lng + math.cos(angle) * root_radius / (111_320.0 * lng_scale),
            )
            for angle in (0, math.pi / 4, math.pi / 2, 3 * math.pi / 4,
                          math.pi, 5 * math.pi / 4, 3 * math.pi / 2,
                          7 * math.pi / 4)
        ]
        for edge_lat, edge_lng in edge_points:
            nearest = min(
                math.hypot(
                    (edge_lat - lat) * 111_320.0,
                    (edge_lng - lng) * 111_320.0 * lng_scale,
                )
                for lat, lng, _radius in centers
            )
            self.assertLessEqual(nearest, child_radius)

    @patch("api.flags.service.mysql")
    @patch("api.flags.service.reserve_usage_slot", return_value=(True, None))
    @patch("api.flags.service.http.post")
    def test_new_nearby_request_uses_pro_field_mask_and_normalizes_results(
        self, post, reserve, _mysql
    ):
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {
            "places": [{
                "id": "places/test-id",
                "displayName": {"text": "Test Store"},
                "location": {"latitude": 13.9667, "longitude": 121.1167},
                "primaryType": "convenience_store",
                "businessStatus": "CLOSED_PERMANENTLY",
            }]
        }
        post.return_value = response

        with patch.dict("os.environ", {"GOOGLE_MAPS_API_KEY": "server-key"}), \
                patch.object(service, "RUN_DETECTION_NEARBY_API", "new"), \
                patch.object(service, "NEW_NEARBY_DAILY_CAP", 75), \
                patch.object(service, "NEW_NEARBY_MONTHLY_CAP", 2500), \
                patch.object(service, "_nearby_last_request_at", 0):
            results, complete = service._fetch_point_results_once(
                13.9667, 121.1167, 850
            )

        self.assertTrue(complete)
        self.assertEqual(results[0]["place_id"], "places/test-id")
        self.assertEqual(results[0]["name"], "Test Store")
        self.assertEqual(results[0]["business_status"], "CLOSED_PERMANENTLY")
        self.assertFalse(service._is_non_business_place(results[0]))
        args, kwargs = post.call_args
        self.assertEqual(args[0], service.NEW_NEARBY_URL)
        self.assertEqual(kwargs["headers"]["X-Goog-Api-Key"], "server-key")
        self.assertEqual(
            kwargs["headers"]["X-Goog-FieldMask"],
            service.NEW_NEARBY_FIELD_MASK,
        )
        self.assertEqual(kwargs["json"]["maxResultCount"], 20)
        self.assertEqual(kwargs["json"]["locationRestriction"]["circle"]["radius"], 850)
        self.assertEqual(
            kwargs["json"],
            {
                "excludedTypes": list(service.NEW_NEARBY_EXCLUDED_TYPES),
                "maxResultCount": 20,
                "locationRestriction": {
                    "circle": {
                        "center": {"latitude": 13.9667, "longitude": 121.1167},
                        "radius": 850,
                    }
                },
            },
        )
        self.assertEqual(
            service.NEW_NEARBY_EXCLUDED_TYPES,
            (
                "place_of_worship", "school", "primary_school", "secondary_school",
                "university", "local_government_office", "city_hall", "courthouse",
                "fire_station", "police_station", "post_office", "library", "cemetery",
                "park", "transit_station", "bus_station", "subway_station",
                "train_station", "light_rail_station",
            ),
        )
        for field in ("includedTypes", "rankPreference", "languageCode"):
            self.assertNotIn(field, kwargs["json"])
        reserve.assert_called_once_with(
            service.mysql.connection,
            "new_nearby_month",
            "new_nearby_day",
            2500,
            75,
        )

    def test_local_exclusion_does_not_hide_common_business_categories(self):
        business_types = (
            "restaurant", "convenience_store", "pharmacy", "beauty_salon",
            "hardware_store", "auto_repair",
        )
        for business_type in business_types:
            with self.subTest(business_type=business_type):
                self.assertFalse(service._is_non_business_place({
                    "name": f"Local {business_type.replace('_', ' ')}",
                    "primaryType": business_type,
                }))

    def test_local_exclusion_still_filters_public_facilities_by_name_and_type(self):
        self.assertTrue(service._is_non_business_place({
            "name": "Barangay Hall",
            "primaryType": "local_government_office",
        }))
        self.assertTrue(service._is_non_business_place({
            "name": "Mataasnakahoy Elementary School",
            "primaryType": "school",
        }))

    @patch("api.flags.service.mysql")
    @patch("api.flags.service.reserve_usage_slot", return_value=(True, None))
    @patch("api.flags.service.http.post")
    def test_new_nearby_resource_exhausted_stops_without_retry(
        self, post, _reserve, _mysql
    ):
        response = MagicMock()
        response.status_code = 429
        response.text = '{"error":{"status":"RESOURCE_EXHAUSTED"}}'
        post.return_value = response

        with patch.dict("os.environ", {"GOOGLE_MAPS_API_KEY": "server-key"}), \
                patch.object(service, "RUN_DETECTION_NEARBY_API", "new"), \
                patch.object(service, "NEW_NEARBY_DAILY_CAP", 75), \
                patch.object(service, "NEW_NEARBY_MONTHLY_CAP", 2500), \
                patch.object(service, "_nearby_last_request_at", 0):
            with self.assertRaises(service.PlacesBudgetExceeded) as raised:
                service._fetch_point_results_once(13.9667, 121.1167, 850)

        post.assert_called_once()
        self.assertEqual(raised.exception.reason, "daily_quota_exceeded")

    @patch("api.flags.service.time.sleep")
    @patch("api.flags.service.random.uniform", return_value=1.0)
    @patch("api.flags.service.mysql")
    @patch("api.flags.service.reserve_usage_slot", return_value=(True, None))
    @patch("api.flags.service.http.post")
    def test_new_nearby_per_minute_429_retries_and_reserves_each_attempt(
        self, post, reserve, _mysql, _uniform, sleep
    ):
        limited = MagicMock()
        limited.status_code = 429
        limited.text = '{"error":{"status":"RESOURCE_EXHAUSTED","quotaId":"RequestsPerMinute"}}'
        success = MagicMock()
        success.status_code = 200
        success.json.return_value = {"places": []}
        post.side_effect = [limited, success]

        with patch.dict("os.environ", {"GOOGLE_MAPS_API_KEY": "server-key"}), \
                patch.object(service, "RUN_DETECTION_NEARBY_API", "new"), \
                patch.object(service, "NEW_NEARBY_DAILY_CAP", 75), \
                patch.object(service, "NEW_NEARBY_MONTHLY_CAP", 2500), \
                patch.object(service, "_nearby_last_request_at", 0):
            results, complete = service._fetch_point_results_once(
                13.9667, 121.1167, 850
            )

        self.assertEqual(results, [])
        self.assertTrue(complete)
        self.assertEqual(post.call_count, 2)
        self.assertEqual(reserve.call_count, 2)
        self.assertEqual(service._places_run_state.calls["new_nearby"], 2)
        self.assertEqual(service._places_run_state.calls["new_nearby_initial"], 2)
        self.assertEqual(service._places_run_state.calls["new_nearby_adaptive"], 0)
        self.assertEqual(sleep.call_args_list[0].args, (2.0,))
        self.assertEqual(len(sleep.call_args_list), 2)

    @patch("api.flags.service.reserve_usage_slot", return_value=(False, "daily_quota_exceeded"))
    @patch("api.flags.service.mysql")
    @patch("api.flags.service.http.post")
    def test_new_nearby_cap_denial_does_not_send_request(
        self, post, _mysql, _reserve
    ):
        with patch.dict("os.environ", {"GOOGLE_MAPS_API_KEY": "server-key"}), \
                patch.object(service, "RUN_DETECTION_NEARBY_API", "new"), \
                patch.object(service, "NEW_NEARBY_DAILY_CAP", 75), \
                patch.object(service, "NEW_NEARBY_MONTHLY_CAP", 2500):
            with self.assertRaises(service.PlacesBudgetExceeded):
                service._fetch_point_results_once(13.9667, 121.1167, 850)

        post.assert_not_called()

    @patch("api.flags.service._fetch_point_results_once")
    def test_new_nearby_twenty_result_saturation_refines_children(self, fetch_once):
        fetch_once.side_effect = [
            ([{"place_id": f"root-{i}"} for i in range(20)], True),
            ([{"place_id": "child-1"}], True),
            ([{"place_id": "child-2"}], True),
            ([{"place_id": "child-3"}], True),
            ([{"place_id": "child-4"}], True),
        ]

        with patch.object(service, "RUN_DETECTION_NEARBY_API", "new"):
            results, complete = service._fetch_point_results(
                13.9667, 121.1167, 850
            )

        self.assertTrue(complete)
        self.assertEqual(len(results), 24)
        self.assertEqual(fetch_once.call_count, 5)

    @patch("api.flags.service._fetch_point_results_once")
    def test_new_nearby_adaptive_requests_never_exceed_root_and_child_budget(
        self, fetch_once
    ):
        fetch_once.return_value = ([{"place_id": "saturated"}] * 20, True)

        with patch.object(service, "RUN_DETECTION_NEARBY_API", "new"):
            results, complete = service._fetch_point_results(
                13.9667, 121.1167, 850
            )

        self.assertFalse(complete)
        self.assertEqual(len(results), 1)
        self.assertEqual(
            fetch_once.call_count,
            1 + service.MAX_ADAPTIVE_QUERIES_PER_POINT,
        )

    @patch("api.flags.service._fetch_legacy_point_results_once")
    def test_legacy_mode_remains_the_default_fallback(self, fetch_legacy):
        fetch_legacy.return_value = ([{"place_id": "legacy"}], True)

        with patch.object(service, "RUN_DETECTION_NEARBY_API", "legacy"):
            results, complete = service._fetch_point_results_once(
                13.9667, 121.1167, 850
            )

        self.assertTrue(complete)
        self.assertEqual(results, [{"place_id": "legacy"}])
        fetch_legacy.assert_called_once_with(13.9667, 121.1167, 850)

    @patch("api.flags.service._mark_point_done")
    @patch("api.flags.service._completed_points_this_cycle", return_value=set())
    @patch("api.flags.service._fetch_point_results_once")
    def test_still_saturated_grid_point_is_incomplete_and_not_checkpointed(
        self, fetch_once, _completed, mark_done
    ):
        fetch_once.return_value = ([{}] * service.NEARBY_RESULT_LIMIT, True)
        state = {
            "done_keys": [],
            "total_points": 0,
            "skipped_points": 0,
            "outside": 0,
            "incomplete_points": 0,
        }

        with patch.object(service, "_grid_points", return_value=[(13.9667, 121.1167)]):
            service._scan_grid(lambda _places: None, None, state)

        self.assertEqual(state["incomplete_points"], 1)
        mark_done.assert_not_called()

    @patch("api.flags.service._mark_point_done")
    @patch("api.flags.service._completed_points_this_cycle", return_value=set())
    @patch("api.flags.service._fetch_point_results")
    def test_api_error_stops_remaining_cells_and_leaves_failed_cell_uncheckpointed(
        self, fetch_point, _completed, mark_done
    ):
        def fail_first_cell(*_args):
            service._record_nearby_api_error()
            return [], False

        fetch_point.side_effect = fail_first_cell
        state = {
            "done_keys": [],
            "total_points": 0,
            "skipped_points": 0,
            "outside": 0,
            "incomplete_points": 0,
        }
        points = [(13.9667, 121.1167), (13.9742, 121.1167)]

        with patch.object(service, "_grid_points", return_value=points):
            service._scan_grid(lambda _places: None, None, state)

        self.assertEqual(fetch_point.call_count, 1)
        self.assertEqual(state["incomplete_points"], 1)
        self.assertTrue(state["api_error_stop"])
        mark_done.assert_not_called()

    @patch("api.flags.service._mark_point_done")
    @patch("api.flags.service._completed_points_this_cycle", return_value=set())
    @patch("api.flags.service._fetch_point_results")
    def test_quota_denial_propagates_and_does_not_checkpoint_cell(
        self, fetch_point, _completed, mark_done
    ):
        fetch_point.side_effect = service.PlacesBudgetExceeded(
            "Nearby Search (New) daily quota exceeded.",
            reason="daily_quota_exceeded",
        )
        state = {
            "done_keys": [],
            "total_points": 0,
            "skipped_points": 0,
            "outside": 0,
            "incomplete_points": 0,
        }

        with patch.object(service, "_grid_points", return_value=[(13.9667, 121.1167)]):
            with self.assertRaises(service.PlacesBudgetExceeded):
                service._scan_grid(lambda _places: None, None, state)

        mark_done.assert_not_called()


if __name__ == "__main__":
    unittest.main()
