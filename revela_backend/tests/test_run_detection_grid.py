import contextlib
import json
import math
import statistics
import time
import unittest
from unittest.mock import MagicMock, patch

from shapely.affinity import scale
from api.flags import service
from api.utils import quota_settings
from shapely.geometry import Point
from shapely.ops import unary_union


@contextlib.contextmanager
def quota_overrides(**values):
    """
    Point `quota_settings.cap` at in-memory values for one test.

    Run Detection resolves its caps from `quota_settings` (env baseline plus
    persisted admin overrides) rather than from module-level constants, so a
    test that wants a non-default cap has to override the resolver. Keys left
    unset fall through to the real implementation, which degrades to the env
    baseline when no database is reachable.
    """
    original = quota_settings.cap

    def fake_cap(key):
        return values.get(key, original(key))

    with patch.object(quota_settings, "cap", side_effect=fake_cap):
        yield


def nearby_new_enabled(daily=75, monthly=2500):
    """Context manager enabling Nearby Search (New) with test-sized caps."""
    return quota_overrides(
        **{
            "quota.nearby_new.daily": daily,
            "quota.nearby_new.monthly": monthly,
        }
    )


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
        service._places_run_state.started_at = None
        service._places_run_state.work_budget_exhausted = False
        service._places_run_state.work_budget_reason = None

    @patch("api.flags.service._fetch_point_results_once")
    def test_saturated_nearby_search_refines_dense_area(self, fetch_once):
        fetch_once.side_effect = [
            ([{"place_id": f"root-{i}"} for i in range(60)], True),
            ([{"place_id": "child-1"}], True),
            ([{"place_id": "child-2"}], True),
            ([{"place_id": "child-3"}], True),
            ([{"place_id": "child-4"}], True),
        ]

        results, complete = service._fetch_point_results(
            13.9667, 121.1167, 850)

        self.assertTrue(complete)
        self.assertEqual(len(results), 64)
        self.assertEqual(fetch_once.call_count, 5)
        self.assertAlmostEqual(
            fetch_once.call_args_list[1].args[2], 850 * 0.72)

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
        shared = next(
            place for place in results if place["place_id"] == "shared")
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

    def test_reduced_grid_circles_cover_buffered_municipality(self):
        """
        Guards the 850 m search-circle coverage of the whole municipality.

        The `len(points)` assertion pins the current spacing to the current
        boundary polygon. It is deliberately coupled to mataasnakahoy.json:
        coverage is non-monotonic in the grid step, so if this fails after a
        boundary edit, re-measure coverage at several candidate steps rather
        than relaxing the expected count.
        """
        points = service._grid_points()
        longitude_scale = 111_320.0 * math.cos(math.radians(13.98))
        projected_boundary = scale(
            service._MUNICIPALITY_WITH_TOLERANCE,
            xfact=longitude_scale,
            yfact=111_320.0,
            origin=(0, 0),
        )
        search_circles = [
            Point(longitude * longitude_scale, latitude * 111_320.0).buffer(
                service.DETECTION_RADIUS_M + 2,
                quad_segs=32,
            )
            for latitude, longitude in points
        ]
        uncovered_area = projected_boundary.difference(
            unary_union(search_circles)
        )

        self.assertEqual(len(points), 70)
        self.assertTrue(uncovered_area.is_empty)

    def test_quick_discovery_points_are_limited_and_cover_barangay_centres(self):
        barangays = [
            {"barangayID": 1, "barangayName": "Barangay I"},
            {"barangayID": 2, "barangayName": "Barangay II"},
            {"barangayID": 3, "barangayName": "Barangay III"},
            {"barangayID": 4, "barangayName": "Barangay IV"},
            {"barangayID": 5, "barangayName": "Barangay V"},
            {"barangayID": 6, "barangayName": "Barangay VI"},
            {"barangayID": 7, "barangayName": "Barangay VII"},
            {"barangayID": 8, "barangayName": "Barangay VIII"},
            {"barangayID": 9, "barangayName": "Barangay IX"},
            {"barangayID": 10, "barangayName": "Barangay X"},
            {"barangayID": 11, "barangayName": "Barangay XI"},
            {"barangayID": 12, "barangayName": "Barangay XII"},
            {"barangayID": 13, "barangayName": "Barangay XIII"},
            {"barangayID": 14, "barangayName": "Barangay XIV"},
            {"barangayID": 15, "barangayName": "Barangay XV"},
            {"barangayID": 16, "barangayName": "Barangay XVI"},
        ]

        points = service._quick_discovery_points(barangays)

        self.assertLessEqual(len(points), 24)
        self.assertGreater(len(points), 0)
        self.assertTrue(all(service._within_municipality(lat, lng)
                        for lat, lng in points))
        self.assertTrue(any(abs(lat - 13.9667) < 0.05 and abs(lng -
                        121.1167) < 0.05 for lat, lng in points))

    def test_quick_discovery_respects_test_mode_point_limit(self):
        barangays = [
            {"barangayID": index, "barangayName": f"Barangay {index}"}
            for index in range(1, 17)
        ]
        config = {
            "test_mode.enabled": True,
            "test_mode.max_grid_points": 3,
        }
        with patch.object(service.test_mode, "get_config", return_value=config):
            points = service._detection_points_for_mode("quick", barangays)

        self.assertEqual(len(points), 3)

    def test_grid_step_env_tuning_is_guarded(self):
        # A non-positive step would never terminate the lattice walk.
        with patch.dict("os.environ",
                        {"DETECTION_GRID_STEP_DEGREES": "0"}):
            self.assertEqual(service._env_positive_float(
                "DETECTION_GRID_STEP_DEGREES", 0.009, 0.001), 0.001)
        with patch.dict("os.environ",
                        {"DETECTION_GRID_STEP_DEGREES": "-0.5"}):
            self.assertEqual(service._env_positive_float(
                "DETECTION_GRID_STEP_DEGREES", 0.009, 0.001), 0.001)

        # Garbage must fall back rather than allowing a bad value to propagate.
        with patch.dict("os.environ",
                        {"DETECTION_GRID_STEP_DEGREES": "wider"}):
            self.assertEqual(service._env_positive_float(
                "DETECTION_GRID_STEP_DEGREES", 0.009, 0.001), 0.009)

        # A valid override is honoured.
        with patch.dict("os.environ",
                        {"DETECTION_GRID_STEP_DEGREES": "0.0075"}):
            self.assertEqual(service._env_positive_float(
                "DETECTION_GRID_STEP_DEGREES", 0.009, 0.001), 0.0075)

        self.assertEqual(service.DETECTION_GRID_STEP_DEGREES, 0.009)

    def test_wider_grid_steps_are_not_assumed_to_stay_covered(self):
        """
        Documents that coverage is non-monotonic: 0.0105 opens a hole that the
        smaller 0.0100 step does not. Guards against someone "optimizing" the
        step upward from the trend line alone.
        """
        def worst_boundary_gap(step):
            min_lat, max_lat = 13.9450, 14.0125
            min_lng, max_lng = 121.0120, 121.1260
            buffer_degrees = (
                service.DETECTION_RADIUS_M / 111_320.0
            ) * 1.1
            search_area = service._MUNICIPALITY_BOUNDARY.buffer(
                buffer_degrees
            )
            centres, lat = [], min_lat
            while lat <= max_lat + 1e-12:
                lng = min_lng
                while lng <= max_lng + 1e-12:
                    if search_area.contains(Point(lng, lat)):
                        centres.append((lat, lng))
                    lng += step
                lat += step

            longitude_scale = 111_320.0 * math.cos(math.radians(13.98))
            boundary = scale(
                service._MUNICIPALITY_BOUNDARY,
                xfact=longitude_scale,
                yfact=111_320.0,
                origin=(0, 0),
            )
            vertices = list(boundary.exterior.coords) + [
                coord
                for ring in boundary.interiors
                for coord in ring.coords
            ]
            return max(
                min(
                    math.hypot(
                        x - centre_lng * longitude_scale,
                        y - centre_lat * 111_320.0,
                    )
                    for centre_lat, centre_lng in centres
                )
                for x, y in vertices
            )

        gap_0010 = worst_boundary_gap(0.0100)
        gap_00105 = worst_boundary_gap(0.0105)

        self.assertLess(gap_0010, service.DETECTION_RADIUS_M)
        self.assertGreater(gap_00105, service.DETECTION_RADIUS_M)

    def test_municipality_predicate_uses_cached_tolerance_geometry(self):
        with patch.object(service, "_MUNICIPALITY_WITH_TOLERANCE") as prepared, \
                patch.object(service, "_MUNICIPALITY_BOUNDARY") as boundary:
            prepared.contains.return_value = True

            self.assertTrue(service._within_municipality(13.9667, 121.1167))

        boundary.buffer.assert_not_called()

    def test_barangay_lookup_uses_preloaded_rows_without_database_reads(self):
        polygon = MagicMock()
        polygon.contains.return_value = True
        barangay_rows = [{"barangayID": 7, "barangayName": "Barangay I"}]

        with patch.object(
            service, "_BARANGAY_POLYGONS", {"District I (Pob.)": polygon}
        ), patch.object(service, "mysql") as mysql:
            barangay_id = service._get_barangay_id_by_coords(
                13.9667, 121.1167, barangay_rows, []
            )

        self.assertEqual(barangay_id, 7)
        mysql.connection.cursor.assert_not_called()

    def test_existing_flags_are_loaded_in_one_batch_query(self):
        cursor = MagicMock()
        cursor.fetchall.return_value = [
            {"logID": 11, "placeID": "place-a", "flagColor": "Red"},
            {"logID": 12, "placeID": "place-b", "flagColor": "Green"},
        ]
        with patch.object(service, "mysql") as mysql:
            mysql.connection.cursor.return_value = cursor

            existing = service._load_existing_flags(
                ["place-a", "place-b", "place-a"]
            )

        self.assertEqual(existing["place-a"]["logID"], 11)
        self.assertEqual(existing["place-b"]["flagColor"], "Green")
        cursor.execute.assert_called_once()
        self.assertEqual(
            cursor.execute.call_args.args[1], ("place-a", "place-b"))

    def test_red_flag_insert_can_defer_commit_for_batch_transaction(self):
        cursor = MagicMock()
        cursor.lastrowid = 42
        with patch.object(service, "mysql") as mysql:
            mysql.connection.cursor.return_value = cursor

            flag_id = service._insert_red_flag(
                "place-a", "Example Shop", 13.9667, 121.1167, 1,
                commit=False,
            )

        self.assertEqual(flag_id, 42)
        mysql.connection.commit.assert_not_called()

    def test_run_detection_rejects_a_concurrent_scan(self):
        with service._run_detection_lock, patch.object(
            service, "_run_detection_cycle"
        ) as run_cycle:
            result, error = service.run_detection(mode="full")

        self.assertIsNone(result)
        self.assertEqual(error, "A detection scan is already in progress.")
        run_cycle.assert_not_called()

    def test_adaptive_centers_cover_radius_with_smaller_search_circles(self):
        center_lat, center_lng, root_radius = 13.9667, 121.1167, 850
        centers = service._adaptive_nearby_centers(
            center_lat, center_lng, root_radius)

        self.assertEqual(len(centers), 4)
        child_radius = root_radius * service.ADAPTIVE_QUERY_RADIUS_RATIO
        for _lat, _lng, radius in centers:
            self.assertAlmostEqual(radius, child_radius)

        lng_scale = math.cos(math.radians(center_lat))
        edge_points = [
            (
                center_lat + math.sin(angle) * root_radius / 111_320.0,
                center_lng + math.cos(angle) * root_radius /
                (111_320.0 * lng_scale),
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

    @patch("api.flags.service._fetch_point_results_once")
    def test_saturated_edge_cell_skips_children_outside_municipality(self, fetch_once):
        root = (13.9450, 121.1020, service.DETECTION_RADIUS_M)
        children = service._adaptive_nearby_centers(*root)
        intersecting_children = [
            child for child in children
            if service._nearby_circle_intersects_municipality(*child)
        ]
        fetch_once.side_effect = [
            ([{"place_id": f"root-{index}"} for index in range(60)], True),
            *[([], True) for _ in intersecting_children],
        ]

        results, complete = service._fetch_point_results(*root)

        self.assertEqual(len(intersecting_children), 2)
        self.assertTrue(complete)
        self.assertEqual(len(results), 60)
        self.assertEqual(fetch_once.call_count, 1 + len(intersecting_children))
        self.assertTrue(all(
            service._nearby_circle_intersects_municipality(*call.args)
            for call in fetch_once.call_args_list[1:]
        ))

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
                "formattedAddress": "Barangay I, Mataasnakahoy, Batangas",
            }]
        }
        post.return_value = response

        with patch.dict("os.environ", {"GOOGLE_MAPS_API_KEY": "server-key"}), \
                patch.object(service, "RUN_DETECTION_NEARBY_API", "new"), \
                nearby_new_enabled(75, 2500), \
                patch.object(service, "_nearby_last_request_at", 0):
            results, complete = service._fetch_point_results_once(
                13.9667, 121.1167, 850
            )

        self.assertTrue(complete)
        self.assertEqual(results[0]["place_id"], "places/test-id")
        self.assertEqual(results[0]["name"], "Test Store")
        self.assertEqual(results[0]["business_status"], "CLOSED_PERMANENTLY")
        self.assertEqual(
            results[0]["vicinity"],
            "Barangay I, Mataasnakahoy, Batangas",
        )
        self.assertIn("places.formattedAddress", service.NEW_NEARBY_FIELD_MASK)
        self.assertFalse(service._is_non_business_place(results[0]))
        args, kwargs = post.call_args
        self.assertEqual(args[0], service.NEW_NEARBY_URL)
        self.assertEqual(kwargs["headers"]["X-Goog-Api-Key"], "server-key")
        self.assertEqual(
            kwargs["headers"]["X-Goog-FieldMask"],
            service.NEW_NEARBY_FIELD_MASK,
        )
        self.assertEqual(kwargs["json"]["maxResultCount"], 20)
        self.assertEqual(
            kwargs["json"]["locationRestriction"]["circle"]["radius"], 850)
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
                nearby_new_enabled(75, 2500), \
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
                nearby_new_enabled(75, 2500), \
                patch.object(service, "_nearby_last_request_at", 0):
            results, complete = service._fetch_point_results_once(
                13.9667, 121.1167, 850
            )

        self.assertEqual(results, [])
        self.assertTrue(complete)
        self.assertEqual(post.call_count, 2)
        self.assertEqual(reserve.call_count, 2)
        self.assertEqual(service._places_run_state.calls["new_nearby"], 2)
        self.assertEqual(
            service._places_run_state.calls["new_nearby_initial"], 2)
        self.assertEqual(
            service._places_run_state.calls["new_nearby_adaptive"], 0)
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
                nearby_new_enabled(75, 2500):
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

    @patch("api.flags.service._fetch_point_results_once")
    def test_adaptive_search_stops_at_run_request_budget(self, fetch_once):
        def saturated_result(*_args):
            service._places_run_state.calls["new_nearby"] += 1
            return ([{"place_id": f"place-{i}"} for i in range(20)], True)

        fetch_once.side_effect = saturated_result
        service._places_run_state.started_at = service.time.monotonic()

        with patch.object(service, "RUN_DETECTION_NEARBY_API", "new"), \
                quota_overrides(**{"run_detection.max_requests": 1}):
            results, complete = service._fetch_point_results(
                13.9667, 121.1167, 850
            )

        self.assertFalse(complete)
        self.assertEqual(len(results), 20)
        fetch_once.assert_called_once()
        self.assertTrue(service._places_run_state.work_budget_exhausted)
        self.assertEqual(
            service._places_run_state.work_budget_reason, "request_limit"
        )

    def test_work_budget_reports_elapsed_time_limit(self):
        service._places_run_state.started_at = 10.0

        with patch.object(service.time, "monotonic", return_value=100.0), \
                patch.object(service, "RUN_DETECTION_MAX_SECONDS", 90):
            self.assertTrue(service._detection_work_budget_reached())

        self.assertEqual(
            service._places_run_state.work_budget_reason, "time_limit"
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

    @patch("api.flags.service._reserve_places_call")
    @patch("api.flags.service.http.get")
    def test_legacy_nearby_is_gated_by_the_shared_rate_limiter(
        self, http_get, reserve
    ):
        """
        Pacing now lives in the shared GCRA limiter, not in a local sleep, so
        that every thread in the process is paced by one object. The limiter's
        own maths is covered in tests/test_places_rate_limit.py.
        """
        response = MagicMock()
        response.json.return_value = {"status": "ZERO_RESULTS", "results": []}
        http_get.return_value = response

        with patch.object(service, "LEGACY_NEARBY_LIMITER") as limiter:
            limiter.acquire.return_value = 1.25
            result = service._places_get(
                "nearby", "https://places.test", timeout=10
            )

        self.assertIs(result, response)
        limiter.acquire.assert_called_once()
        reserve.assert_called_once_with("nearby")

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

    def test_fully_attempted_saturated_grid_is_terminal_with_gaps(self):
        state = {
            "total_points": 3,
            "skipped_points": 1,
            "done_keys": ["completed"],
            "incomplete_points": 1,
            "api_error_stop": False,
            "work_budget_stop": False,
        }

        self.assertTrue(service._grid_scan_has_terminal_gaps(state))
        state["work_budget_stop"] = True
        self.assertFalse(service._grid_scan_has_terminal_gaps(state))

    def test_elapsed_metrics_separate_end_to_end_from_scan_slice(self):
        service._places_run_state.started_at = service.time.monotonic() - 5
        metrics = service._detection_elapsed_metrics(
            service.time.monotonic() - 40
        )

        self.assertGreaterEqual(metrics["elapsed_seconds"], 40)
        self.assertGreaterEqual(metrics["scan_elapsed_seconds"], 5)
        self.assertLess(metrics["scan_elapsed_seconds"],
                        metrics["elapsed_seconds"])

    def test_elapsed_metrics_report_zero_slice_before_grid_traversal(self):
        service._places_run_state.started_at = None
        metrics = service._detection_elapsed_metrics(
            service.time.monotonic() - 12
        )

        self.assertEqual(metrics["scan_elapsed_seconds"], 0.0)
        self.assertGreaterEqual(metrics["elapsed_seconds"], 12)

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

    def test_fixture_benchmark_compares_quick_and_full_without_live_requests(self):
        registry = [{
            "businessID": "BIZ-SILVA",
            "businessName": "Silva Pharmacy",
            "businessLine": "Pharmacy",
            "businessType": "Pharmacy",
            "businessAddress": "Poblacion, Mataasnakahoy",
            "applicationStatus": "Active",
            "placeID": "registry-place-id",
            "barangayID": 1,
            "latitude": 13.9667,
            "longitude": 121.1167,
        }]
        registry.extend({
            "businessID": f"DECOY-{index}",
            "businessName": f"UnrelatedBrand{index}",
            "businessLine": "Retail",
            "applicationStatus": "Active",
            "placeID": f"registry-decoy-{index}",
            "barangayID": 1,
            "latitude": 13.9667,
            "longitude": 121.1167,
        } for index in range(100))

        cursor = MagicMock()
        cursor.fetchall.return_value = []
        cursor.lastrowid = 900

        def fetchone():
            query = cursor.execute.call_args.args[0]
            if "COUNT(*) AS total FROM official_registry" in query:
                return {"total": len(registry)}
            if "SELECT coordSource, matchStatus, latitude, longitude" in query:
                return {
                    "coordSource": "manual",
                    "matchStatus": "approved",
                    "latitude": 13.9667,
                    "longitude": 121.1167,
                }
            return None

        cursor.fetchone.side_effect = fetchone
        database = MagicMock()
        database.connection.cursor.return_value = cursor
        results = []

        def run_mode(mode):
            service._places_run_state.quick_scan_history = {}
            config = {
                "test_mode.enabled": False,
                "test_mode.max_grid_points": 6,
            }
            with patch.object(
                service.test_mode, "get_config", return_value=config
            ), patch.object(
                service.quota_settings, "cap", return_value=0.009
            ):
                points = service._detection_points_for_mode(mode)
            point_indexes = {
                (round(lat, 5), round(lng, 5)): index
                for index, (lat, lng) in enumerate(points)
            }

            def fetch_fixture(lat, lng, _radius, _mode):
                index = point_indexes[(round(lat, 5), round(lng, 5))]
                is_registered = index % 5 == 0
                place_name = (
                    "Silva Pharmacy" if is_registered
                    else f"UnmatchedFixtureBusiness{index}"
                )
                places = [
                    {
                        "place_id": "fixture-library-shared",
                        "name": "Public Library",
                        "geometry": {"location": {
                            "lat": 13.9667, "lng": 121.1167,
                        }},
                        "types": ["library"],
                    },
                    {
                        "place_id": f"fixture-{mode}-{index}",
                        "name": place_name,
                        "geometry": {"location": {
                            "lat": 13.9667, "lng": 121.1167,
                        }},
                        "types": ["pharmacy"] if is_registered else ["store"],
                        "vicinity": "Poblacion, Mataasnakahoy",
                        "business_status": "OPERATIONAL",
                    },
                ]
                service._places_run_state.calls[
                    "legacy_nearby_fixture"
                ] = service._places_run_state.calls.get(
                    "legacy_nearby_fixture", 0
                ) + 1
                service._places_run_state.results_received += len(places)
                return places, True

            quota_info = {
                "is_limit_reached": False,
                "monthly_limit": 10,
                "registry_count": len(registry),
            }
            with contextlib.ExitStack() as patches:
                patches.enter_context(patch.object(service, "mysql", database))
                patches.enter_context(patch.object(
                    service, "get_detection_quota_info", return_value=quota_info
                ))
                patches.enter_context(patch.object(
                    service, "_ensure_place_types_column"))
                patches.enter_context(patch.object(
                    service, "_load_registry", return_value=registry
                ))
                patches.enter_context(patch.object(
                    service, "reconcile_existing_flags"))
                patches.enter_context(patch.object(
                    service, "create_detection_run", return_value=1
                ))
                patches.enter_context(patch.object(
                    service, "update_detection_run_status"))
                patches.enter_context(patch.object(
                    service, "_completed_points_this_cycle", return_value=set()
                ))
                patches.enter_context(patch.object(
                    service, "_mark_point_done"))
                patches.enter_context(patch.object(
                    service, "_get_barangay_id_by_coords", return_value=1
                ))
                patches.enter_context(patch.object(
                    service, "_detection_work_budget_reached", return_value=False
                ))
                patches.enter_context(patch.object(
                    service, "_detection_radius_m", return_value=850
                ))
                patches.enter_context(patch.object(
                    service, "_log_detection_summary", return_value={}
                ))
                patches.enter_context(patch.object(
                    service, "set_cancel"
                ))
                patches.enter_context(patch.object(
                    service, "is_cancelled", return_value=False
                ))
                patches.enter_context(patch.object(
                    service.hub, "publish_to_admins"
                ))
                patches.enter_context(patch.object(
                    service.test_mode, "get_config", return_value=config
                ))
                patches.enter_context(patch.object(
                    service.quota_settings, "cap", return_value=0.009
                ))
                patches.enter_context(patch.object(
                    service, "_fetch_point_results_for_mode",
                    side_effect=fetch_fixture,
                ))
                started = time.perf_counter()
                result, error = service.run_detection(mode=mode)
                elapsed_ms = (time.perf_counter() - started) * 1000

            self.assertIsNone(error)
            summary = result["run_summary"]
            results.append({
                "mode": summary["detection_mode"],
                "simulated_end_to_end_ms": round(elapsed_ms, 3),
                "scan_elapsed_seconds": summary["scan_elapsed_seconds"],
                "google_requests_consumed": summary["api_requests_consumed"],
                "fixture_queries_replayed": summary[
                    "fixture_requests_replayed"
                ],
                "unique_in_bound_pois": summary["unique_in_bound_pois"],
                "actionable_candidates_per_query": summary[
                    "actionable_candidates_per_nearby_query"
                ],
                "registry_match_time_seconds": summary[
                    "registry_match_time_seconds"
                ],
                "registry_candidate_reduction_percent": summary[
                    "registry_candidate_reduction_percent"
                ],
                "poi_processing_db_queries": summary[
                    "poi_processing_db_queries"
                ],
                "poi_processing_db_commits": summary[
                    "poi_processing_db_commits"
                ],
                "new_flags": result["new_flags"],
            })

        for mode in ("quick", "full"):
            for _ in range(3):
                run_mode(mode)

        benchmarks = []
        for offset, mode in ((0, "quick"), (3, "full")):
            samples = results[offset:offset + 3]
            benchmark = dict(samples[0])
            benchmark["simulated_end_to_end_ms_median"] = round(
                statistics.median(
                    sample["simulated_end_to_end_ms"] for sample in samples
                ),
                3,
            )
            benchmark["timing_samples_ms"] = [
                sample["simulated_end_to_end_ms"] for sample in samples
            ]
            benchmarks.append(benchmark)

        self.assertEqual(benchmarks[0]["google_requests_consumed"], 0)
        self.assertEqual(benchmarks[1]["google_requests_consumed"], 0)
        self.assertLess(
            benchmarks[0]["fixture_queries_replayed"],
            benchmarks[1]["fixture_queries_replayed"],
        )
        self.assertLess(
            benchmarks[0]["unique_in_bound_pois"],
            benchmarks[1]["unique_in_bound_pois"],
        )
        self.assertGreater(
            benchmarks[1]["registry_candidate_reduction_percent"], 0
        )
        print("FIXTURE_MODE_BENCHMARK=" +
              json.dumps(benchmarks, sort_keys=True))


if __name__ == "__main__":
    unittest.main()
