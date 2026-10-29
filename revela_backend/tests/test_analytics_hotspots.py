import unittest
from datetime import date
from unittest.mock import Mock, patch

from shapely.geometry import box

from api.analytics.hotspots import (
    HOTSPOT_DEFAULT_EPS_M,
    HOTSPOT_DEFAULT_MIN_SAMPLES,
    attribute_hotspot_point,
    build_hotspot_population_sql,
    cluster_hotspot_rows,
    cache_hotspots,
    count_hotspot_dispositions,
    get_cached_hotspots,
    hotspot_cluster_memberships,
    hotspot_date_window,
    invalidate_hotspots_cache,
    resolve_hotspot_parameters,
    serialize_map_hotspot_clusters,
)


class HotspotParameterTests(unittest.TestCase):
    def setUp(self):
        invalidate_hotspots_cache()

    def test_defaults_and_valid_settings(self):
        parameters, fallbacks = resolve_hotspot_parameters({})
        self.assertEqual(parameters, {
            "eps_m": HOTSPOT_DEFAULT_EPS_M,
            "min_samples": HOTSPOT_DEFAULT_MIN_SAMPLES,
            "metric": "haversine",
        })
        self.assertEqual(fallbacks, {})

        parameters, fallbacks = resolve_hotspot_parameters({
            "hotspots.eps_m": "75",
            "hotspots.min_samples": '"5"',
        })
        self.assertEqual(parameters, {
            "eps_m": 75.0,
            "min_samples": 5,
            "metric": "haversine",
        })
        self.assertEqual(fallbacks, {})

    def test_invalid_settings_fall_back_and_are_reported(self):
        parameters, fallbacks = resolve_hotspot_parameters({
            "hotspots.eps_m": "201",
            "hotspots.min_samples": '"2.5"',
        })
        self.assertEqual(parameters["eps_m"], 50)
        self.assertEqual(parameters["min_samples"], 3)
        self.assertEqual(set(fallbacks), {"eps_m", "min_samples"})

    def test_overview_date_presets_use_inclusive_calendar_days(self):
        today = date(2026, 10, 29)
        self.assertEqual(hotspot_date_window("all", today), (None, None))
        self.assertEqual(
            hotspot_date_window("year", today),
            (date(2026, 1, 1), today),
        )
        self.assertEqual(
            hotspot_date_window("30days", today),
            (date(2026, 9, 30), today),
        )
        self.assertEqual(
            hotspot_date_window("7days", today),
            (date(2026, 10, 23), today),
        )
        with self.assertRaises(ValueError):
            hotspot_date_window("quarter", today)

    def test_hotspot_cache_returns_copies_and_can_be_invalidated(self):
        key = ("all", None, 50, 3)
        payload = {"clusters": [{"cluster_id": 1}]}
        cache_hotspots(key, payload)

        cached = get_cached_hotspots(key)
        self.assertEqual(cached, payload)
        cached["clusters"].clear()
        self.assertEqual(get_cached_hotspots(key), payload)

        invalidate_hotspots_cache()
        self.assertIsNone(get_cached_hotspots(key))


class HotspotPopulationTests(unittest.TestCase):
    def test_population_sql_uses_effective_red_color_and_date_range(self):
        sql, params = build_hotspot_population_sql(
            "effective_color(g)",
            "EXISTS (SELECT 1 FROM official_registry r WHERE r.businessID = g.businessID)",
            date(2026, 10, 23),
            date(2026, 10, 29),
        )
        self.assertIn("(effective_color(g)) = 'Red'", sql)
        self.assertIn("g.detectedDate >= %s", sql)
        self.assertIn("DATE_ADD(%s, INTERVAL 1 DAY)", sql)
        self.assertIn("registry_linked", sql)
        self.assertIn("missing_coordinates", sql)
        self.assertIn("COALESCE(g.source, 'unknown') <> 'detection'", sql)
        self.assertIn("g.businessID IS NOT NULL", sql)
        self.assertIn("g.latitude IS NULL OR g.longitude IS NULL", sql)
        self.assertEqual(params, [
            date(2026, 10, 23),
            date(2026, 10, 29),
        ])

    def test_population_sql_appends_shared_page_scope_after_date_parameters(self):
        sql, params = build_hotspot_population_sql(
            "effective_color(g)",
            "registry_linked(g)",
            date(2026, 10, 23),
            date(2026, 10, 29),
            extra_where_sql=" AND g.barangayID = %s",
            extra_params=(7,),
        )
        self.assertIn("AND g.barangayID = %s", sql)
        self.assertEqual(params, [
            date(2026, 10, 23),
            date(2026, 10, 29),
            7,
        ])

    def test_population_exclusions_are_mutually_exclusive_and_account_for_red_rows(self):
        rows = [
            {"disposition": "eligible"},
            {"disposition": "not_detection"},
            {"disposition": "registry_linked"},
            {"disposition": "missing_coordinates"},
        ]
        counts = count_hotspot_dispositions(rows)
        self.assertEqual(
            counts["considered_red_pins"],
            counts["eligible_points"] + sum(counts["excluded"].values()),
        )
        self.assertEqual(counts["eligible_points"], 1)


class HotspotAttributionTests(unittest.TestCase):
    def setUp(self):
        self.polygons = [
            {
                "barangay_id": 1,
                "barangay_name": "Barangay One",
                "geometry": box(0, 0, 1, 1),
            },
            {
                "barangay_id": 2,
                "barangay_name": "Barangay Two",
                "geometry": box(1, 0, 2, 1),
            },
        ]

    def test_point_inside_exactly_one_polygon_is_attributed(self):
        point = attribute_hotspot_point(0.5, 0.5, self.polygons)
        self.assertEqual(point["barangay_id"], 1)

    def test_boundary_and_outside_points_are_uncertain(self):
        self.assertIsNone(attribute_hotspot_point(0.5, 1, self.polygons))
        self.assertIsNone(attribute_hotspot_point(3, 3, self.polygons))

    def test_cluster_summaries_keep_uncertain_members_out_of_barangay_counts(self):
        rows = [
            {"logID": 1, "latitude": 0.5, "longitude": 0.99990, "disposition": "eligible"},
            {"logID": 2, "latitude": 0.50001, "longitude": 0.99990, "disposition": "eligible"},
            {"logID": 3, "latitude": 0.50002, "longitude": 0.99990, "disposition": "eligible"},
            {"logID": 4, "latitude": 0.50001, "longitude": 1, "disposition": "eligible"},
            {"logID": 5, "latitude": 0.51, "longitude": 1.5, "disposition": "eligible"},
        ]
        clusters, totals = cluster_hotspot_rows(
            rows,
            {"eps_m": 20, "min_samples": 3, "metric": "haversine"},
            self.polygons,
        )
        self.assertEqual(len(clusters), 1)
        self.assertEqual(clusters[0]["size"], 4)
        self.assertEqual(clusters[0]["uncertain_count"], 1)
        self.assertEqual(
            {row["barangay_id"]: row["count"] for row in clusters[0]["per_barangay"]},
            {1: 3},
        )
        self.assertEqual(totals, {
            "clustered_points": 4,
            "noise_points": 1,
            "uncertain_points": 1,
        })

    def test_canonical_50m_contract_clusters_detection_pins_and_preserves_noise(self):
        rows = [
            {
                "logID": 11,
                "latitude": 10.0,
                "longitude": 121.0,
                "disposition": "eligible",
            },
            {
                "logID": 12,
                "latitude": 10.00027,
                "longitude": 121.0,
                "disposition": "eligible",
            },
            {
                "logID": 13,
                "latitude": 10.00054,
                "longitude": 121.0,
                "disposition": "eligible",
            },
            {
                "logID": 14,
                "latitude": 10.00028,
                "longitude": 121.0,
                "disposition": "not_detection",
            },
            {
                "logID": 15,
                "latitude": 10.01,
                "longitude": 121.0,
                "disposition": "eligible",
            },
        ]
        parameters, _ = resolve_hotspot_parameters({})
        clusters, totals = cluster_hotspot_rows(rows, parameters, self.polygons)
        memberships, primary_cluster_id = hotspot_cluster_memberships(rows, clusters)

        self.assertEqual(parameters["eps_m"], 50)
        self.assertEqual(parameters["min_samples"], 3)
        self.assertEqual([cluster["size"] for cluster in clusters], [3])
        self.assertEqual(clusters[0]["log_ids"], [11, 12, 13])
        self.assertEqual(memberships, {11: 0, 12: 0, 13: 0, 15: -1})
        self.assertEqual(primary_cluster_id, 0)
        self.assertEqual(totals["noise_points"], 1)


class MapHotspotEndpointContractTests(unittest.TestCase):
    def test_map_endpoint_uses_shared_population_parameters_and_clusterer(self):
        from api.flags import service

        cursor = Mock()
        fake_mysql = Mock()
        fake_mysql.connection.cursor.return_value = cursor
        cursor.fetchall.side_effect = [
            [],
            [
                {"logID": 21, "latitude": 10.0, "longitude": 121.0,
                 "disposition": "eligible"},
                {"logID": 22, "latitude": 10.00027, "longitude": 121.0,
                 "disposition": "eligible"},
                {"logID": 23, "latitude": 10.00054, "longitude": 121.0,
                 "disposition": "eligible"},
                {"logID": 24, "latitude": 10.00028, "longitude": 121.0,
                 "disposition": "business_id_present"},
            ],
            [{"barangayID": 1, "barangayName": "Barangay One"}],
        ]
        polygons = [{
            "barangay_id": 1,
            "barangay_name": "Barangay One",
            "geometry": box(120, 9, 122, 11),
        }]

        with patch("api.flags.service.mysql", fake_mysql), \
                patch("api.flags.service.ladder_columns_available", return_value=False), \
                patch("api.flags.service._effective_flag_color_sql", return_value="effective_color(g)"), \
                patch("api.flags.service.load_barangay_polygons", return_value=polygons):
            clusters, error = service.get_red_flag_clusters()

        self.assertIsNone(error)
        self.assertEqual(len(clusters), 1)
        self.assertEqual(clusters[0]["size"], 3)
        self.assertEqual(clusters[0]["logIDs"], [21, 22, 23])
        self.assertEqual(clusters[0]["eps_m"], 50)
        self.assertEqual(clusters[0]["min_samples"], 3)
        population_sql = cursor.execute.call_args_list[1].args[0]
        self.assertIn("(effective_color(g)) = 'Red'", population_sql)
        self.assertIn("COALESCE(g.source, 'unknown') <> 'detection'", population_sql)
        self.assertIn("g.businessID IS NOT NULL", population_sql)
        self.assertTrue(cursor.close.called)

    def test_map_endpoint_adapter_keeps_legacy_fields_and_shared_parameters(self):
        clusters = [{
            "cluster_id": 4,
            "centroid": {"lat": 10.5, "lng": 121.2},
            "radius_m": 31.7,
            "size": 3,
            "log_ids": [4, 8, 12],
        }]
        self.assertEqual(serialize_map_hotspot_clusters(clusters, {
            "eps_m": 50,
            "min_samples": 3,
        }), [{
            "clusterID": 4,
            "centroidLat": 10.5,
            "centroidLng": 121.2,
            "radius_m": 31.7,
            "size": 3,
            "logIDs": [4, 8, 12],
            "eps_m": 50,
            "min_samples": 3,
        }])


if __name__ == "__main__":
    unittest.main()
