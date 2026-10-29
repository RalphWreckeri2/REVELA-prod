"""Regression tests for municipal WLC priority and feasible staffing."""
import itertools
import unittest
from copy import deepcopy

from api.analytics.dispatch import generate_recommendations, _urgency_label, _score_breakdown
from api.analytics.scoring import calculate_rankings, select_rankings, haversine_km
from api.analytics.service import DEFAULT_CONFIG


def row(bid, red=0, yellow=0, black=0, **extra):
    return {"barangayID": bid, "barangayName": f"Barangay {bid}",
            "red_count": red, "yellow_count": yellow, "black_count": black,
            "avg_lat": DEFAULT_CONFIG["bplo_lat"], "avg_lng": DEFAULT_CONFIG["bplo_lng"],
            "total_registered": 0, "registry_flagged_count": 0, **extra}


class PrescriptiveScoringTests(unittest.TestCase):
    def setUp(self):
        self.config = deepcopy(DEFAULT_CONFIG)

    def test_risk_uses_maximum_weighted_burden_not_premature_clipping(self):
        rankings, model = calculate_rankings([row(1, red=100), row(2, red=34),
                                             row(3, yellow=50), row(4, black=25)], self.config)
        by_id = {r["barangayID"]: r for r in rankings}
        self.assertEqual(model["reference_max_burden"], 300)
        self.assertEqual(by_id[1]["risk_score"], 100)
        self.assertEqual(by_id[2]["risk_score"], 34)
        self.assertEqual(by_id[3]["risk_score"], 33.3)
        self.assertEqual(by_id[4]["risk_score"], 33.3)
        self.assertGreater(by_id[1]["ops_score"], by_id[2]["ops_score"])

    def test_black_red_yellow_severity_order_at_equal_volume_and_distance(self):
        rankings, _ = calculate_rankings([row(1, yellow=5), row(2, red=5), row(3, black=5)], self.config)
        self.assertEqual([r["barangayID"] for r in rankings], [3, 2, 1])

    def test_no_flags_never_receive_priority_from_proximity_or_sector(self):
        self.config.update(w1_risk=30, w2_sector=50, w3_distance=20,
                           sectors={"Barangay 1": 100, "Barangay 2": 10})
        rankings, _ = calculate_rankings([row(1), row(2, red=1)], self.config)
        self.assertEqual(rankings[-1]["ops_score"], 0)
        self.assertFalse(rankings[-1]["inspection_required"])
        self.assertEqual(rankings[-1]["priority_label"], "NO ACTIVE FLAGS")
        self.assertEqual(len(generate_recommendations(rankings, 6, {"w1": .3, "w2": .5, "w3": .2})), 1)

    def test_empty_and_all_clear_datasets(self):
        self.assertEqual(calculate_rankings([], self.config)[0], [])
        rankings, model = calculate_rankings([row(1), row(2)], self.config)
        self.assertEqual(model["reference_max_burden"], 0)
        self.assertTrue(all(r["risk_score"] == r["ops_score"] == 0 for r in rankings))
        self.assertEqual(generate_recommendations(rankings, 6, model["weights"]), [])

    def test_interview_weights_are_never_redistributed_for_sector_input_coverage(self):
        for sectors in ({}, {"Barangay 1": 80}, {"Barangay 1": 50, "Barangay 2": 50},
                        {"Barangay 1": 0, "Barangay 2": 100}):
            with self.subTest(sectors=sectors):
                self.config["sectors"] = sectors
                rankings, model = calculate_rankings([row(1, red=2), row(2, red=1)], self.config)
                self.assertTrue(model["sector_enabled"])
                self.assertEqual(model["weights"], {"w1": .68, "w2": .07, "w3": .25})
                self.assertEqual(model["sector_fallback_count"], 2 - len(sectors))
                for ranked in rankings:
                    expected_sector = sectors.get(ranked["barangayName"], 50)
                    self.assertEqual(ranked["sector_score"], expected_sector)
                    self.assertEqual(ranked["ops_score"], round(.68 * ranked["risk_score"] + .07 * expected_sector + .25 * ranked["proximity_score"], 1))

    def test_actual_ops_uses_interview_weights_and_original_neutral_sector_score(self):
        rankings, model = calculate_rankings([row(1, red=100), row(2, red=34, avg_lat=None)], self.config)
        by_id = {ranked["barangayID"]: ranked for ranked in rankings}
        self.assertEqual(model["weights"], {"w1": .68, "w2": .07, "w3": .25})
        self.assertEqual(by_id[1]["ops_score"], 96.5)  # 68 + 3.5 + 25
        self.assertEqual(by_id[2]["ops_score"], 39.1)  # 23.12 + 3.5 + 12.5
        self.assertEqual(by_id[1]["sector_score_source"], "neutral_fallback")

    def test_mapped_sector_mix_is_entity_weighted_and_unclassified_entities_use_50(self):
        rows, model = calculate_rankings([
            row(1, red=1, sector_category_counts={"Manufacturing": 2, "Retail": 1, None: 1}),
        ], self.config)
        ranked = rows[0]
        self.assertEqual(ranked["sector_entity_count"], 4)
        self.assertEqual(ranked["sector_known_entity_count"], 3)
        self.assertEqual(ranked["sector_fallback_entity_count"], 1)
        self.assertEqual(ranked["sector_score"], 77.5)
        self.assertEqual(ranked["sector_score_source"], "psic_weighted")
        self.assertEqual(ranked["ops_score"], 98.4)
        self.assertEqual(model["sector_policy"]["fallback_score"], 50)
        self.assertEqual(model["sector_entity_count"], 4)
        self.assertEqual(model["sector_fallback_entity_count"], 1)

    def test_explicit_barangay_sector_override_precedes_mapped_category_average(self):
        self.config["sectors"] = {"Barangay 1": 12}
        rankings, _ = calculate_rankings([
            row(1, red=1, sector_category_counts={"Manufacturing": 2}),
        ], self.config)
        self.assertEqual(rankings[0]["sector_score"], 12)
        self.assertEqual(rankings[0]["sector_score_source"], "configured")

    def test_custom_saved_weights_are_also_applied_without_redistribution(self):
        self.config.update(w1_risk=30, w2_sector=40, w3_distance=30)
        rankings, model = calculate_rankings([row(1, red=1)], self.config)
        self.assertEqual(model["weights"], {"w1": .3, "w2": .4, "w3": .3})
        self.assertEqual(rankings[0]["ops_score"], 80)  # 30 + 20 + 30

    def test_explicit_zero_and_sector_only_weights_are_not_overridden(self):
        for weights, expected in (((100, 0, 0), 100), ((0, 100, 0), 50), ((0, 0, 100), 100)):
            with self.subTest(weights=weights):
                self.config.update(zip(("w1_risk", "w2_sector", "w3_distance"), weights))
                rankings, model = calculate_rankings([row(1, red=1)], self.config)
                self.assertEqual(list(model["weights"].values()), [value / 100 for value in weights])
                self.assertEqual(rankings[0]["ops_score"], expected)

    def test_complete_varying_sector_inputs_are_explicit_opt_in(self):
        self.config.update(w1_risk=60, w2_sector=20, w3_distance=20,
                           sectors={"Barangay 1": 80, "Barangay 2": 20})
        rankings, model = calculate_rankings([row(1, red=1), row(2, red=1)], self.config)
        self.assertTrue(model["sector_enabled"])
        self.assertEqual(rankings[0]["ops_score"], 96)
        self.assertEqual(rankings[1]["ops_score"], 84)

    def test_missing_or_invalid_locations_use_disclosed_neutral_proximity(self):
        for latitude, longitude in ((None, 121), (13, None), (91, 121), (13, 181), (float("nan"), 121), ("invalid", 121)):
            with self.subTest(latitude=latitude, longitude=longitude):
                rankings, _ = calculate_rankings([row(1, red=1, avg_lat=latitude, avg_lng=longitude)], self.config)
                self.assertTrue(rankings[0]["location_missing"])
                self.assertIsNone(rankings[0]["distance_km"])
                self.assertEqual(rankings[0]["proximity_score"], 50)
        rankings, _ = calculate_rankings([row(1, red=1, avg_lat=0, avg_lng=0)], self.config)
        self.assertFalse(rankings[0]["location_missing"], "Zero coordinates are valid numbers, not missing values")

    def test_haversine_and_nearer_locations_increase_priority_for_equal_burden(self):
        self.assertEqual(haversine_km(0, 0, 0, 0), 0)
        self.assertAlmostEqual(haversine_km(0, 0, 0, 1), 111.195, places=3)
        rankings, _ = calculate_rankings([row(1, red=1, avg_lat=14.2), row(2, red=1)], self.config)
        self.assertEqual(rankings[0]["barangayID"], 2)

    def test_registry_rate_is_separate_from_flag_record_volume_and_unknown_is_na(self):
        rankings, _ = calculate_rankings([row(1, red=20, total_registered=10, registry_flagged_count=2), row(2, red=5)], self.config)
        self.assertEqual(rankings[0]["registry_active_flag_rate"], 20)
        self.assertIsNone(rankings[1]["registry_active_flag_rate"])
        self.assertNotIn("non_compliance_rate", rankings[0])

    def test_ties_are_deterministic_and_display_filters_preserve_global_ranks(self):
        inputs = [row(3, red=1, barangayName="Zulu"), row(2, red=1, barangayName="Alpha"),
                  row(1, red=1, barangayName="Alpha")]
        rankings, _ = calculate_rankings(inputs, self.config)
        reversed_rankings, _ = calculate_rankings(reversed(inputs), self.config)
        self.assertEqual(rankings, reversed_rankings)
        self.assertEqual([r["barangayID"] for r in rankings], [1, 2, 3])
        filtered = select_rankings(rankings, {"barangay_ids": [3], "flag_color": "Green", "application_status": "Active"})
        self.assertEqual(filtered, [rankings[2]])
        self.assertEqual(filtered[0]["rank"], 3)


class DispatchAllocationTests(unittest.TestCase):
    def plans(self, available, inputs=None):
        rankings, model = calculate_rankings(inputs or [row(1, red=30), row(2, red=20), row(3, red=10)], deepcopy(DEFAULT_CONFIG))
        return generate_recommendations(rankings, available, model["weights"])

    def test_shortages_defer_lowest_wlc_priorities_without_negative_staffing(self):
        for available, expected in ((0, [0, 0, 0]), (1, [1, 0, 0]), (2, [1, 1, 0]), (6, [3, 2, 1]), (10, [3, 2, 1])):
            with self.subTest(available=available):
                plans = self.plans(available)
                self.assertEqual([p["inspectors"] for p in plans], expected)
                for plan in plans:
                    if not plan["inspectors"]:
                        self.assertEqual(plan["allocation_status"], "deferred")
                        self.assertNotIn("Deploy 0", plan["recommendation"])
                        self.assertNotIn("Schedule inspections within", " ".join(plan["actionSteps"]))

    def test_allocation_conserves_pool_for_small_and_uneven_workloads(self):
        for counts in itertools.product((1, 2, 100), repeat=3):
            inputs = [row(index, red=count) for index, count in enumerate(counts, 1)]
            for available in range(9):
                with self.subTest(counts=counts, available=available):
                    plans = self.plans(available, inputs)
                    allocations = [p["inspectors"] for p in plans]
                    eligible_businesses = sum(p["dispatchable_business_count"] for p in plans)
                    self.assertEqual(sum(allocations), min(available, 6, eligible_businesses))
                    self.assertTrue(all(isinstance(n, int) and n >= 0 for n in allocations))
                    self.assertEqual(sum(n > 0 for n in allocations), min(available, 3, eligible_businesses))
                    self.assertTrue(all(n <= p["dispatchable_business_count"]
                                        for n, p in zip(allocations, plans)))

    def test_one_destination_and_negative_available_pool(self):
        one = self.plans(6, [row(1, red=1)])[0]
        self.assertEqual(one["inspectors"], 1)
        self.assertEqual(one["allocation_status"], "ready")
        self.assertEqual(self.plans(-1, [row(1, red=1)])[0]["inspectors"], 0)

    def test_capacity_routes_excess_staff_to_other_destinations_or_leaves_it_unallocated(self):
        inputs = [row(1, red=10, dispatchable_business_count=1),
                  row(2, red=8, dispatchable_business_count=3),
                  row(3, red=5, dispatchable_business_count=2)]
        plans = self.plans(6, inputs)
        self.assertEqual([plan["inspectors"] for plan in plans], [1, 3, 2])
        self.assertEqual(sum(plan["inspectors"] for plan in plans), 6)
        only_two_businesses = self.plans(
            6, [row(1, red=1, dispatchable_business_count=1),
                row(2, red=1, dispatchable_business_count=1)])
        self.assertEqual([plan["inspectors"] for plan in only_two_businesses], [1, 1])

    def test_black_only_and_already_assigned_destinations_do_not_take_top_three_slots(self):
        plans = self.plans(6, [row(1, black=100), row(2, red=90, dispatchable_red_count=0),
                              row(3, red=3), row(4, red=2), row(5, red=1)])
        self.assertEqual([p["barangayID"] for p in plans], [3, 4, 5])
        self.assertEqual(sum(p["inspectors"] for p in plans), 6)

    def test_black_context_does_not_inflate_the_dispatchable_workload_split(self):
        plans = self.plans(6, [row(1, red=1, black=100), row(2, red=100), row(3, red=1)])
        self.assertEqual([p["inspectors"] for p in plans], [1, 4, 1])

    def test_legacy_rank_payload_also_excludes_black_from_staffing_workload(self):
        rankings, model = calculate_rankings([row(1, red=1, black=100), row(2, red=100), row(3, red=1)], deepcopy(DEFAULT_CONFIG))
        legacy = [{key: value for key, value in r.items() if not key.startswith("dispatchable_")} for r in rankings]
        plans = generate_recommendations(legacy, 6, model["weights"])
        self.assertEqual([p["inspectors"] for p in plans], [1, 4, 1])

    def test_table_and_recommendation_bands_share_the_same_thresholds(self):
        for score, expected in ((0, "MONITOR"), (29.9, "MONITOR"), (30, "STANDARD"),
                                (59.9, "STANDARD"), (60, "HIGH PRIORITY"), (100, "HIGH PRIORITY")):
            self.assertEqual(_urgency_label(score), expected)
        for plan in self.plans(6):
            expected = "High" if plan["ops_score"] >= 60 else "Medium" if plan["ops_score"] >= 30 else "Low"
            self.assertEqual(plan["risk_level"], expected)
            self.assertAlmostEqual(sum(component["contribution"] for component in plan["scoreBreakdown"].values()), plan["ops_score"], delta=.2)

    def test_breakdown_fallback_matches_the_interview_preset(self):
        breakdown = _score_breakdown({"risk_score": 100, "proximity_score": 50}, {})
        self.assertEqual([part["weight"] for part in breakdown.values()], [68, 7, 25])
        self.assertEqual(breakdown["sector"]["raw"], 50)
        self.assertEqual(breakdown["sector"]["contribution"], 3.5)


if __name__ == "__main__":
    unittest.main()
