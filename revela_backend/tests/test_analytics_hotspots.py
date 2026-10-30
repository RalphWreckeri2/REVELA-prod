import unittest
from datetime import date
from unittest.mock import Mock, patch

from shapely.geometry import box

from api.analytics import hotspots
from api.analytics.hotspots import (
    HOTSPOT_DEFAULT_EPS_M,
    HOTSPOT_DEFAULT_FLAGS,
    HOTSPOT_DEFAULT_MIN_SAMPLES,
    HOTSPOT_POPULATION_OBJECTIVE,
    HOTSPOT_POPULATION_UNREGISTERED,
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
from api.utils.barangay_mapping import (
    load_adm4_barangay_mapping,
    map_adm4_barangay_ids,
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
            "flags": list(HOTSPOT_DEFAULT_FLAGS),
            "source": "default",
            "sources": {"eps_m": "default", "min_samples": "default", "flags": "default"},
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
            "flags": list(HOTSPOT_DEFAULT_FLAGS),
            "source": "setting",
            "sources": {"eps_m": "setting", "min_samples": "setting", "flags": "default"},
        })
        self.assertEqual(fallbacks, {})

    def test_invalid_settings_fall_back_and_are_reported(self):
        parameters, fallbacks = resolve_hotspot_parameters({
            "hotspots.eps_m": "201",
            "hotspots.min_samples": '"2.5"',
        })
        self.assertEqual(parameters["eps_m"], 50)
        self.assertEqual(parameters["min_samples"], 3)
        self.assertEqual(parameters["source"], "default")
        self.assertEqual(parameters["sources"]["eps_m"], "default")
        self.assertEqual(parameters["sources"]["min_samples"], "default")
        self.assertEqual(set(fallbacks), {"eps_m", "min_samples"})

    def test_flag_setting_and_mixed_parameter_sources_are_reported(self):
        parameters, fallbacks = resolve_hotspot_parameters({
            "hotspots.eps_m": "75",
            "hotspots.flags": '["Red"]',
        })
        self.assertEqual(fallbacks, {})
        self.assertEqual(parameters["flags"], ["Red"])
        self.assertEqual(parameters["source"], "setting")
        self.assertEqual(parameters["sources"], {
            "eps_m": "setting",
            "min_samples": "default",
            "flags": "setting",
        })

    def test_invalid_flags_use_the_default_and_report_fallback(self):
        parameters, fallbacks = resolve_hotspot_parameters({
            "hotspots.flags": '["Green"]',
        })
        self.assertEqual(parameters["flags"], ["Red", "Black"])
        self.assertEqual(parameters["sources"]["flags"], "default")
        self.assertEqual(fallbacks, {"flags": "Invalid flag list; using default Red and Black."})

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
    def test_objective_sql_uses_configured_effective_flags_and_date_range(self):
        sql, params = build_hotspot_population_sql(
            "effective_color(g)",
            "EXISTS (SELECT 1 FROM official_registry r WHERE r.businessID = g.businessID)",
            date(2026, 10, 23),
            date(2026, 10, 29),
        )
        self.assertIn("(effective_color(g)) IN (%s, %s)", sql)
        self.assertIn("g.detectedDate >= %s", sql)
        self.assertIn("DATE_ADD(%s, INTERVAL 1 DAY)", sql)
        self.assertNotIn("'registry_linked'", sql)
        self.assertIn("missing_coordinates", sql)
        self.assertNotIn("COALESCE(g.source, 'unknown') <> 'detection'", sql)
        self.assertNotIn("g.businessID IS NOT NULL", sql)
        self.assertIn("g.latitude IS NULL OR g.longitude IS NULL", sql)
        self.assertEqual(params, [
            "Red",
            "Black",
            date(2026, 10, 23),
            date(2026, 10, 29),
        ])

    def test_unregistered_candidate_sql_uses_red_subset_and_exclusions(self):
        sql, params = build_hotspot_population_sql(
            "effective_color(g)",
            "registry_linked(g)",
            None,
            None,
            population=HOTSPOT_POPULATION_UNREGISTERED,
            flags=["Red"],
        )
        self.assertIn("(effective_color(g)) IN (%s)", sql)
        self.assertIn("COALESCE(g.source, 'unknown') <> 'detection'", sql)
        self.assertIn("WHEN registry_linked(g)", sql)
        self.assertIn("g.businessID IS NOT NULL", sql)
        self.assertEqual(params, ["Red"])

    def test_export_projection_omits_sensitive_columns_and_exposes_audit_fields(self):
        sql, params = build_hotspot_population_sql(
            "effective_color(g)",
            "registry_linked(g)",
            None,
            None,
            include_sensitive_fields=False,
            include_legacy_evidence=True,
        )
        select_clause = sql.split("FROM geospatial_logs", 1)[0]
        self.assertNotIn("g.detectedName", select_clause)
        self.assertNotIn("g.businessID,", select_clause)
        self.assertIn("AS registry_linked", select_clause)
        self.assertIn("AS legacy_evidence_eligible", select_clause)
        self.assertEqual(params, ["Red", "Black"])

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
            "Red",
            "Black",
            date(2026, 10, 23),
            date(2026, 10, 29),
            7,
        ])

    def test_population_counts_are_mutually_exclusive_and_count_flags_and_sources(self):
        rows = [
            {"disposition": "eligible", "flagColor": "Red", "source": "detection"},
            {"disposition": "not_detection", "flagColor": "Red", "source": "manual"},
            {"disposition": "registry_linked", "flagColor": "Red", "source": "detection"},
            {"disposition": "missing_coordinates", "flagColor": "Black", "source": "registry"},
        ]
        counts = count_hotspot_dispositions(
            rows,
            population=HOTSPOT_POPULATION_UNREGISTERED,
            flags=["Red", "Black"],
        )
        self.assertEqual(
            counts["considered_records"],
            counts["eligible_points"] + sum(counts["excluded"].values()),
        )
        self.assertEqual(counts["eligible_points"], 1)
        self.assertEqual(counts["counts_by_flag"], {"Red": 3, "Black": 1})
        self.assertEqual(counts["counts_by_source"], {
            "detection": 2,
            "manual": 1,
            "registry": 1,
        })
        self.assertEqual(counts["excluded_by_reason"], counts["excluded"])


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

    def test_polygon_boundary_and_outside_points_are_not_attributed(self):
        self.assertIsNone(attribute_hotspot_point(0.5, 1, self.polygons))
        self.assertIsNone(attribute_hotspot_point(3, 3, self.polygons))
        overlapping_polygons = [
            {"barangay_id": 1, "geometry": box(0, 0, 1.5, 1)},
            {"barangay_id": 2, "geometry": box(0.5, 0, 2, 1)},
        ]
        with self.assertRaisesRegex(ValueError, "matches multiple"):
            attribute_hotspot_point(0.5, 1, overlapping_polygons)

    def test_shared_mapping_covers_all_features_and_matches_live_ids(self):
        mapping = load_adm4_barangay_mapping()
        feature_names = [
            feature["properties"]["ADM4_EN"]
            for feature in hotspots._read_barangay_geojson()["features"]
        ]
        live_rows = [
            {"barangayID": barangay_id, "barangayName": f"Barangay {barangay_id}"}
            for barangay_id in range(1, 17)
        ]
        ids_by_name, _ = map_adm4_barangay_ids(feature_names, live_rows)

        self.assertEqual(len(mapping), 16)
        self.assertEqual(set(ids_by_name.values()), set(range(1, 17)))
        self.assertEqual(ids_by_name["Loob"], 9)
        self.assertEqual(ids_by_name["Kinalaglagan"], 11)
        with self.assertRaisesRegex(ValueError, "No barangay ID mapping"):
            map_adm4_barangay_ids(["Unknown Feature"], live_rows)

    def test_dbscan_results_are_invariant_to_input_row_order(self):
        rows = [
            {"logID": 13, "latitude": 10.00054, "longitude": 121.0, "disposition": "eligible"},
            {"logID": 11, "latitude": 10.0, "longitude": 121.0, "disposition": "eligible"},
            {"logID": 12, "latitude": 10.00027, "longitude": 121.0, "disposition": "eligible"},
        ]
        parameters, _ = resolve_hotspot_parameters({})
        polygons = [{
            "barangay_id": 1,
            "barangay_name": "Test Barangay",
            "geometry": box(120.9, 9.9, 121.1, 10.1),
        }]
        forward, _ = cluster_hotspot_rows(rows, parameters, polygons)
        reverse, _ = cluster_hotspot_rows(list(reversed(rows)), parameters, polygons)
        self.assertEqual(forward, reverse)
        self.assertEqual(forward[0]["log_ids"], [11, 12, 13])

    def test_previously_unassigned_detection_members_map_to_their_polygons(self):
        barangay_rows = [
            {"barangayID": barangay_id, "barangayName": f"Barangay {barangay_id}"}
            for barangay_id in range(1, 17)
        ]
        polygons = hotspots.load_barangay_polygons(barangay_rows)
        live_coordinates = {
            186: (13.96039790, 121.11429950),
            189: (13.96020410, 121.11466200),
            317: (13.97716950, 121.10996680),
            325: (13.97253270, 121.11046260),
            328: (13.97291230, 121.11015880),
            331: (13.96912700, 121.10945700),
            332: (13.96912700, 121.10945700),
            334: (13.96912700, 121.10945700),
            335: (13.97278210, 121.11012490),
            350: (13.97709150, 121.10995100),
            351: (13.97711660, 121.10993520),
            352: (13.97710060, 121.10963750),
        }
        expected_ids = {
            186: 16, 189: 16, 317: 7, 325: 16, 328: 16,
            331: 15, 332: 15, 334: 15, 335: 16,
            350: 7, 351: 7, 352: 7,
        }
        self.assertEqual(set(expected_ids), set(live_coordinates))
        for log_id, (latitude, longitude) in live_coordinates.items():
            attributed = attribute_hotspot_point(latitude, longitude, polygons)
            self.assertEqual(attributed["barangay_id"], expected_ids[log_id], log_id)

    def test_cluster_summaries_attribute_every_cluster_member(self):
        rows = [
            {"logID": 1, "latitude": 0.5, "longitude": 0.99990, "disposition": "eligible"},
            {"logID": 2, "latitude": 0.50001, "longitude": 0.99990, "disposition": "eligible"},
            {"logID": 3, "latitude": 0.50002, "longitude": 0.99990, "disposition": "eligible"},
            {"logID": 4, "latitude": 0.50001, "longitude": 0.99990, "disposition": "eligible"},
            {"logID": 5, "latitude": 0.51, "longitude": 1.5, "disposition": "eligible"},
        ]
        clusters, totals = cluster_hotspot_rows(
            rows,
            {"eps_m": 20, "min_samples": 3, "metric": "haversine"},
            self.polygons,
        )
        self.assertEqual(len(clusters), 1)
        self.assertEqual(clusters[0]["size"], 4)
        self.assertEqual(clusters[0]["uncertain_count"], 0)
        self.assertEqual(
            {row["barangay_id"]: row["count"] for row in clusters[0]["per_barangay"]},
            {1: 4},
        )
        self.assertEqual(totals, {
            "clustered_points": 4,
            "noise_points": 1,
            "uncertain_points": 0,
            "outside_boundary_count": 0,
        })

    def test_outside_pin_is_counted_logged_and_excluded_from_barangay_attribution(self):
        rows = [
            {"logID": 1, "latitude": 0.5, "longitude": 0.99990, "disposition": "eligible"},
            {"logID": 2, "latitude": 0.50001, "longitude": 0.99990, "disposition": "eligible"},
            {"logID": 3, "latitude": 0.50002, "longitude": 0.99990, "disposition": "eligible"},
            {"logID": 91, "latitude": 0.5, "longitude": 3, "disposition": "eligible"},
        ]
        with self.assertLogs("api.analytics.hotspots", level="WARNING") as captured:
            clusters, totals = cluster_hotspot_rows(
                rows,
                {"eps_m": 20, "min_samples": 3, "metric": "haversine"},
                self.polygons,
            )

        self.assertEqual(len(clusters), 1)
        self.assertEqual(clusters[0]["size"], 3)
        self.assertEqual(clusters[0]["per_barangay"][0]["count"], 3)
        self.assertEqual(totals["outside_boundary_count"], 1)
        self.assertTrue(any("logID=91" in message for message in captured.output))

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
        polygons = [{
            "barangay_id": 1,
            "barangay_name": "Test Barangay",
            "geometry": box(120.9, 9.9, 121.1, 10.1),
        }]
        clusters, totals = cluster_hotspot_rows(rows, parameters, polygons)
        memberships, primary_cluster_id = hotspot_cluster_memberships(rows, clusters)

        self.assertEqual(parameters["eps_m"], 50)
        self.assertEqual(parameters["min_samples"], 3)
        self.assertEqual([cluster["size"] for cluster in clusters], [3])
        self.assertEqual(clusters[0]["log_ids"], [11, 12, 13])
        self.assertEqual(memberships, {11: 0, 12: 0, 13: 0, 15: -1})
        self.assertEqual(primary_cluster_id, 0)
        self.assertEqual(totals["noise_points"], 1)


class MapHotspotEndpointContractTests(unittest.TestCase):
    def test_endpoint_returns_outside_boundary_count_without_failing(self):
        from flask import Flask
        from api.analytics import routes as analytics_routes

        cursor = Mock()
        fake_mysql = Mock()
        fake_mysql.connection.cursor.return_value = cursor
        cursor.fetchall.side_effect = [
            [],
            [{
                "logID": 91,
                "latitude": 3,
                "longitude": 3,
                "disposition": "eligible",
            }],
            [{"barangayID": 1, "barangayName": "Barangay One"}],
        ]
        cursor.fetchone.return_value = None
        polygons = [{
            "barangay_id": 1,
            "barangay_name": "Barangay One",
            "geometry": box(0, 0, 1, 1),
        }]

        with patch.object(analytics_routes, "mysql", fake_mysql), \
                patch.object(analytics_routes, "ladder_columns_available", return_value=False), \
                patch.object(analytics_routes, "_effective_flag_color_sql", return_value="effective_color(g)"), \
                patch.object(analytics_routes, "load_barangay_polygons", return_value=polygons):
            with patch.object(analytics_routes, "get_cached_hotspots", return_value=None):
                app = Flask(__name__)
                with app.test_request_context("/api/analytics/hotspots?date_preset=all"):
                    response, status = analytics_routes.get_analytics_hotspots.__wrapped__()

        self.assertEqual(status, 200)
        self.assertEqual(response.get_json()["totals"]["outside_boundary_count"], 1)
        self.assertTrue(cursor.close.called)

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
        self.assertIn("(effective_color(g)) IN (%s, %s)", population_sql)
        self.assertNotIn("THEN 'not_detection'", population_sql)
        self.assertNotIn("THEN 'business_id_present'", population_sql)
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
