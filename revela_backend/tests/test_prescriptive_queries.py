"""Exercise the real municipal SQL with in-memory data, never production DB."""
import os
import sys
import unittest
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import patch

from flask import Flask

sys.path.insert(0, os.path.dirname(__file__))
from registry_sqlite import RegistryDB
from api.analytics import routes
from api.analytics.service import DEFAULT_CONFIG
from api.registry.colors import _effective_flag_color_sql


class PrescriptiveQueryTests(unittest.TestCase):
    def setUp(self):
        self.db = RegistryDB()
        self.addCleanup(self.db.close)
        self.config = deepcopy(DEFAULT_CONFIG)
        self.color = _effective_flag_color_sql("g", ladder=True)
        self.db.db.executescript("""
            INSERT INTO barangays VALUES (2, 'Barangay II'), (3, 'Barangay III');
            INSERT INTO users VALUES (10, 'Free inspector', 'Inspector', 1), (11, 'Inactive inspector', 'Inspector', 0);
            INSERT INTO official_registry (businessID, businessName, barangayID, applicationStatus, placeID) VALUES
                ('B1', 'Expired shop', 1, 'Expired', 'P1'),
                ('B2', 'Active shop', 1, 'Active', 'P2'),
                ('B3', 'Warned shop', 1, 'Expired', 'P3'),
                ('B4', 'Closed shop', 1, 'Closed', 'P4'),
                ('B5', 'Pending shop', 2, 'Pending', 'P5'),
                ('B6', 'Revoked shop', 2, 'Revoked', 'P6');
            UPDATE official_registry SET lineOfBusiness = 'Make stuff' WHERE businessID = 'B1';
            INSERT INTO registry_sector_map
                (normalized_line_of_business, display_sector_key, display_sector_label, match_status)
            VALUES
                ('makestuff', 'manufacturing', 'Manufacturing', 'matched'),
                ('shopretail', 'retail', 'Retail', 'matched');
            UPDATE official_registry SET lineOfBusiness = 'Shop retail' WHERE businessID = 'B2';
            INSERT INTO enforcement_state (subjectType, subjectID, warningLevel) VALUES ('business', 'B3', 1);
            INSERT INTO geospatial_logs (logID, businessID, barangayID, detectedName, flagColor, latitude, longitude, placeID) VALUES
                (1, 'B1', 1, 'Expired shop', 'Green', 13.96, 121.11, 'P1'),
                (2, 'B1', 1, 'Duplicate record', 'Green', 13.96, 121.11, 'P1'),
                (3, 'B2', 1, 'Active shop', 'Red', 80, 170, 'P2'),
                (4, 'B3', 1, 'Warned shop', 'Red', 80, 170, 'P3'),
                (5, 'B4', 1, 'Closed shop', 'Red', 80, 170, 'P4'),
                (6, NULL, 1, 'Unknown shop', 'Red', 13.96, 121.11, 'PX'),
                (7, NULL, 1, 'Unknown no coordinates', 'Red', 20, NULL, 'PN'),
                (8, 'B5', 2, 'Pending shop', 'Green', 14, 121.12, 'P5'),
                (9, 'B6', 2, 'Revoked shop', 'Green', 14, 121.12, 'P6'),
                (10, NULL, 1, 'Different Places label', 'Red', 13.96, 121.11, 'P1');
        """)
        self.db.commit()

    def section(self, filters=None, split=False):
        with patch.object(routes, "_rankings_split_enabled", return_value=split):
            return routes._build_prescriptive_section(self.db.cursor(), self.color, True, self.config, filters or {})

    def test_only_active_flags_with_paired_valid_coordinates_define_proximity(self):
        for split in (False, True):
            builder = routes._barangay_rankings_sql_split if split else routes._barangay_rankings_sql
            sql, params = builder(self.color, "", [], "", [], "", [])
            cur = self.db.cursor()
            cur.execute(sql, params)
            rows = {row["barangayID"]: row for row in cur.fetchall()}
            self.assertAlmostEqual(rows[1]["avg_lat"], 13.96)
            self.assertAlmostEqual(rows[1]["avg_lng"], 121.11)
            self.assertEqual(rows[1]["red_count"], 5)
            self.assertEqual(rows[1]["unregistered_candidate_count"], 2)
            self.assertIsNone(rows[3]["avg_lat"])

    def test_registry_rate_deduplicates_businesses_and_respects_enforcement_color(self):
        section = self.section()
        rows = {row["barangayID"]: row for row in section["rankings"]}
        self.assertEqual(rows[1]["flagged_count"], 5, "WLC inputs explicitly count geo records")
        self.assertEqual(rows[1]["total_registered"], 4)
        self.assertEqual(rows[1]["registry_flagged_count"], 1, "Orange/Green/Purple must not enter the active-flag numerator")
        self.assertEqual(rows[1]["registry_active_flag_rate"], 25)
        self.assertEqual(rows[1]["unregistered_candidate_count"], 2, "A placeID match is a registry match even when businessID is null")
        self.assertEqual(rows[2]["registry_active_flag_rate"], 100)
        self.assertIsNone(rows[3]["registry_active_flag_rate"])

    def test_sector_risk_uses_distinct_active_flag_entities_and_neutral_fallback(self):
        rows = {row["barangayID"]: row for row in self.section()["rankings"]}
        first = rows[1]
        self.assertEqual(first["sector_entity_count"], 3)
        self.assertEqual(first["sector_known_entity_count"], 1)
        self.assertEqual(first["sector_fallback_entity_count"], 2)
        self.assertAlmostEqual(first["sector_score"], 190 / 3)
        self.assertEqual(first["sector_score_source"], "psic_weighted")
        self.assertEqual(rows[2]["sector_score_source"], "neutral_fallback")

    def test_sector_risk_deduplicates_unregistered_entities_by_place_id(self):
        self.db.db.execute("""
            INSERT INTO geospatial_logs
                (logID, businessID, barangayID, detectedName, flagColor, latitude, longitude, placeID)
            VALUES (11, NULL, 1, 'Second pin for same unknown place', 'Red', 13.96, 121.11, 'PX')
        """)
        self.db.commit()
        first = next(row for row in self.section()["rankings"] if row["barangayID"] == 1)
        self.assertEqual(first["sector_entity_count"], 3)
        self.assertEqual(first["sector_fallback_entity_count"], 2)

    def test_dispatch_capacity_deduplicates_registry_and_place_matched_businesses(self):
        before = next(row for row in self.section()["rankings"] if row["barangayID"] == 1)
        self.db.db.executemany("""
            INSERT INTO geospatial_logs
                (logID, businessID, barangayID, detectedName, flagColor, latitude, longitude, placeID)
            VALUES (?, ?, 1, ?, 'Red', 13.96, 121.11, ?)
        """, [
            (11, None, "Duplicate unregistered pin", "PX"),
            (12, "B1", "Duplicate registered pin", "P1"),
        ])
        self.db.commit()

        after = next(row for row in self.section()["rankings"] if row["barangayID"] == 1)
        self.assertEqual(after["dispatchable_count"], before["dispatchable_count"] + 2)
        self.assertEqual(after["dispatchable_business_count"],
                         before["dispatchable_business_count"])

    def test_dashboard_filters_preserve_scores_ranks_and_municipal_allocations(self):
        full = self.section()
        filters = {"barangay_ids": [2], "application_status": "Active", "flag_color": "Green",
                   "detected_from": "2099-01-01", "line_of_business": "Not a real sector"}
        subset = self.section(filters)
        expected = [r for r in full["rankings"] if r["barangayID"] == 2]
        self.assertEqual(subset["rankings"], expected)
        self.assertEqual(subset["dispatch_recommendations"],
                         [r for r in full["dispatch_recommendations"] if r["barangayID"] == 2])
        self.assertEqual(subset["rankings"][0]["rank"], 2)
        self.assertEqual(subset["dispatch_recommendations"][0]["inspectors"], 1)
        self.assertIn("flag_color", subset["model"]["ignored_filters"])
        self.assertNotIn("barangay_ids", subset["model"]["ignored_filters"])

    def test_split_and_shipped_paths_produce_the_same_complete_prescription(self):
        full, split = self.section(), self.section(split=True)
        for key in ("rankings", "dispatch_recommendations", "workforce", "model"):
            self.assertEqual(full[key], split[key], key)

    def test_registry_context_is_aggregated_without_fanning_out_model_records(self):
        self.section()
        source = next(sql for sql, _ in self.db.calls if "unregistered_candidate_count" in sql)
        self.assertIn("LEFT JOIN official_registry o ON o.barangayID = b.barangayID AND 1=0", source)
        self.assertTrue(any("registry_flagged_count" in sql for sql, _ in self.db.calls))

    def test_busy_and_inactive_inspectors_are_not_allocated(self):
        self.db.db.executescript("""
            INSERT INTO inspection_reports (userID, targetID, verificationStatus) VALUES
                (9, 1, 'Assigned'), (9, 2, 'Reassigned'), (11, 3, 'Assigned');
        """)
        section = self.section()
        self.assertEqual(section["workforce"]["active_inspectors"], 2)
        self.assertEqual(section["workforce"]["available_inspectors"], 1)
        self.assertEqual([r["inspectors"] for r in section["dispatch_recommendations"]], [1, 0])
        self.db.db.execute("UPDATE inspection_reports SET verificationStatus = 'Submitted'")
        self.assertEqual(self.section()["workforce"]["available_inspectors"], 2)

    def test_zero_active_inspectors_does_not_fabricate_a_six_person_pool(self):
        self.db.db.execute("UPDATE users SET isActive = 0")
        section = self.section()
        self.assertEqual(section["workforce"]["available_inspectors"], 0)
        self.assertEqual(section["workforce"]["allocation_capacity"], 0)
        self.assertEqual(section["workforce"]["unallocated_inspectors"], 0)
        self.assertTrue(all(r["inspectors"] == 0 and r["allocation_status"] == "deferred"
                            for r in section["dispatch_recommendations"]))

    def test_excess_available_inspectors_are_reported_as_unallocated(self):
        self.db.db.executemany(
            "INSERT INTO users (userID, fullName, userRole, isActive) VALUES (?, ?, 'Inspector', 1)",
            [(user_id, f"Inspector {user_id}") for user_id in range(12, 16)],
        )
        ranked = {
            "barangayID": 1, "barangayName": "Barangay I", "rank": 1,
            "ops_score": 80, "risk_score": 80, "sector_score": 50,
            "proximity_score": 50, "distance_score": 50, "flagged_count": 2,
            "red_count": 2, "yellow_count": 0, "black_count": 0,
            "dispatchable_count": 2, "dispatchable_business_count": 1,
            "dispatchable_red_count": 2, "dispatchable_yellow_count": 0,
            "dispatchable_burden": 6,
        }
        model = {"weights": {"w1": .68, "w2": .07, "w3": .25}}
        with patch.object(routes, "_load_prescriptive_rankings", return_value=([ranked], model)):
            section = self.section()
        self.assertEqual(section["workforce"]["available_inspectors"], 6)
        self.assertEqual(section["workforce"]["allocated_inspectors"], 1)
        self.assertEqual(section["workforce"]["unallocated_inspectors"], 5)

    def test_black_only_barangays_remain_risk_context_but_receive_no_field_plan(self):
        self.db.db.executescript("""
            INSERT INTO barangays VALUES (4, 'Black-only area');
            INSERT INTO geospatial_logs (barangayID, detectedName, flagColor, placeID, latitude, longitude)
            VALUES (4, 'Black-only record', 'Black', 'PB', 13.96, 121.11);
        """)
        section = self.section()
        black = next(r for r in section["rankings"] if r["barangayID"] == 4)
        self.assertGreater(black["risk_score"], 0)
        self.assertEqual(black["dispatchable_count"], 0)
        self.assertFalse(black["inspection_required"])
        self.assertNotIn(4, [r["barangayID"] for r in section["dispatch_recommendations"]])

    def test_fully_assigned_barangay_is_not_given_duplicate_field_deployments(self):
        self.db.db.executescript("""
            INSERT INTO inspection_reports (userID, targetID, verificationStatus) VALUES
                (9, 1, 'Assigned'), (9, 2, 'Assigned'), (9, 6, 'Reassigned'),
                (9, 7, 'In Progress'), (9, 10, 'Assigned');
        """)
        section = self.section()
        assigned = next(r for r in section["rankings"] if r["barangayID"] == 1)
        self.assertEqual(assigned["flagged_count"], 5)
        self.assertEqual(assigned["dispatchable_count"], 0)
        self.assertFalse(assigned["inspection_required"])
        self.assertEqual([r["barangayID"] for r in section["dispatch_recommendations"]], [2])
        self.assertEqual(section["dispatch_recommendations"][0]["dispatchable_count"], 1,
                         "Only Yellow, not the locked Black record, can receive a new inspection")

    def test_dispatchable_location_mean_excludes_black_and_ongoing_records(self):
        self.db.db.executescript("""
            UPDATE geospatial_logs SET latitude = 80, longitude = 170 WHERE logID = 9;
            UPDATE geospatial_logs SET latitude = 75, longitude = 160 WHERE logID = 2;
            INSERT INTO inspection_reports (userID, targetID, verificationStatus) VALUES (9, 2, 'Assigned');
        """)
        for split in (False, True):
            builder = routes._barangay_rankings_sql_split if split else routes._barangay_rankings_sql
            sql, params = builder(self.color, "", [], "", [], "", [])
            cur = self.db.cursor()
            cur.execute(sql, params)
            rows = {row["barangayID"]: row for row in cur.fetchall()}
            self.assertAlmostEqual(rows[1]["avg_lat"], 13.96)
            self.assertAlmostEqual(rows[2]["avg_lat"], 14)

    def test_map_endpoint_returns_the_same_scores_as_analytics(self):
        expected = self.section()["rankings"]
        app = Flask(__name__)
        with app.test_request_context("/api/analytics/ops-rankings"), \
                patch.object(routes, "mysql", SimpleNamespace(connection=self.db)), \
                patch.object(routes, "ladder_columns_available", return_value=True), \
                patch.object(routes, "get_wlc_config", return_value=self.config), \
                patch.object(routes, "_rankings_split_enabled", return_value=False):
            response, status = routes.get_ops_rankings_only.__wrapped__()
        self.assertEqual(status, 200)
        self.assertEqual(response.get_json()["data"], expected)
        self.assertEqual(response.get_json()["model"]["version"], "wlc-v3")

    def test_invalid_policy_payloads_return_400_not_500(self):
        app = Flask(__name__)
        for payload in ([1], "not an object", {"w1_risk": -1}):
            with self.subTest(payload=payload), \
                    app.test_request_context("/api/analytics/wlc-config", method="PUT", json=payload), \
                    patch.object(routes, "update_wlc_config", side_effect=ValueError("Invalid WLC policy")):
                response, status = routes.update_config.__wrapped__()
                self.assertEqual(status, 400)
                self.assertIn("error", response.get_json())

    def test_sector_policy_routes_validate_update_and_reset(self):
        app = Flask(__name__)
        payload = {
            "categories": {"Retail": 96},
            "fallback_score": 45,
        }
        updated = {
            "version": "psic-sector-risk-v1",
            "categories": {"Retail": 96},
            "fallback_score": 45,
        }
        with app.test_request_context("/api/analytics/sector-policy", method="PUT", json=payload), \
                patch.object(routes, "update_sector_risk_policy", return_value=updated):
            response, status = routes.update_sector_policy.__wrapped__()
        self.assertEqual(status, 200)
        self.assertEqual(response.get_json()["data"], updated)

        with app.test_request_context(
            "/api/analytics/sector-policy", method="PUT", json={"categories": {}, "fallback_score": 50}
        ), patch.object(routes, "update_sector_risk_policy", side_effect=ValueError("Invalid sector policy")):
            response, status = routes.update_sector_policy.__wrapped__()
        self.assertEqual(status, 400)
        self.assertEqual(response.get_json()["error"], "Invalid sector policy")

        with app.test_request_context("/api/analytics/sector-policy/reset", method="POST"), \
                patch.object(routes, "reset_sector_risk_policy", return_value=updated):
            response, status = routes.reset_sector_policy.__wrapped__()
        self.assertEqual(status, 200)
        self.assertEqual(response.get_json()["data"], updated)


if __name__ == "__main__":
    unittest.main()
