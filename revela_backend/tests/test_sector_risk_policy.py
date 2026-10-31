"""Validation and bounds checks for editable PSIC sector-risk policy."""

import json
import tempfile
import unittest
from pathlib import Path

from api.analytics.sector_risk import (
    DEFAULT_SECTOR_RISK_POLICY,
    SECTOR_CATEGORIES,
    load_sector_risk_policy,
    reset_sector_risk_policy,
    update_sector_risk_policy,
    validate_sector_risk_policy,
    weighted_sector_score,
)


class SectorRiskPolicyTests(unittest.TestCase):
    def test_default_policy_has_exact_ui_categories_and_requested_scores(self):
        policy = load_sector_risk_policy()
        self.assertEqual(set(policy["categories"]), set(SECTOR_CATEGORIES))
        self.assertEqual(policy["categories"], {
            "Manufacturing": 90,
            "Construction and utilities": 85,
            "Wholesale and vehicles": 80,
            "Retail": 80,
            "Food and drink": 75,
            "Hospitality, arts and recreation": 75,
            "Transport and storage": 70,
            "Real estate": 60,
            "Finance and professional": 50,
            "Information and communication": 50,
            "Education, health and other services": 40,
            "Agriculture and mining": 30,
        })
        self.assertEqual(policy["fallback_score"], 50)
        self.assertEqual(policy, DEFAULT_SECTOR_RISK_POLICY)
        display_defaults_path = Path(__file__).parents[1] / "api" / "analytics" / "display_sector_defaults.json"
        with display_defaults_path.open(encoding="utf-8") as defaults_file:
            display_labels = {entry[1] for entry in json.load(defaults_file).values()}
        self.assertEqual(display_labels, set(SECTOR_CATEGORIES))

    def test_policy_rejects_missing_extra_and_out_of_bounds_scores(self):
        original = load_sector_risk_policy()
        for invalid in (
            {**original, "categories": {**original["categories"], "Retail": 101}},
            {**original, "categories": {**original["categories"], "Retail": 10 ** 10000}},
            {**original, "categories": {**original["categories"], "Retail": 10.5}},
            {**original, "categories": {key: value for key, value in original["categories"].items()
                                       if key != "Retail"}},
            {**original, "categories": {**original["categories"], "Other": 40}},
            {**original, "fallback_score": -1},
            {**original, "fallback_score": float("nan")},
            {**original, "categories": {**original["categories"], "Retail": True}},
        ):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    validate_sector_risk_policy(invalid)

    def test_sector_average_uses_fallback_for_unmapped_labels_and_empty_cohort(self):
        policy = load_sector_risk_policy()
        score, total, known, fallback = weighted_sector_score(
            {"Manufacturing": 2, "Unmapped sector": 2}, policy)
        self.assertEqual((score, total, known, fallback), (70, 4, 2, 2))
        self.assertEqual(weighted_sector_score({}, policy), (50, 0, 0, 0))

    def test_sector_counts_must_be_nonnegative_integers(self):
        policy = load_sector_risk_policy()
        for counts in ({"Retail": -1}, {"Retail": 1.5}, {"Retail": True}):
            with self.subTest(counts=counts):
                with self.assertRaises(ValueError):
                    weighted_sector_score(counts, policy)

    def test_policy_update_persists_complete_valid_scores_and_reset_restores_defaults(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sector-risk.json"
            changed = {
                "fallback_score": 50,
                "categories": {**DEFAULT_SECTOR_RISK_POLICY["categories"], "Retail": 96},
            }
            updated = update_sector_risk_policy(changed, path=path)
            self.assertEqual(load_sector_risk_policy(path), updated)
            self.assertEqual(updated["categories"]["Retail"], 96)
            self.assertEqual(updated["fallback_score"], 50)

            reset = reset_sector_risk_policy(path=path)
            self.assertEqual(reset, DEFAULT_SECTOR_RISK_POLICY)
            self.assertEqual(load_sector_risk_policy(path), DEFAULT_SECTOR_RISK_POLICY)

    def test_editable_category_payload_rejects_unknown_fields_and_non_integer_values(self):
        from api.analytics.sector_risk import validate_sector_risk_categories

        valid = {"categories": dict(DEFAULT_SECTOR_RISK_POLICY["categories"])}
        self.assertEqual(validate_sector_risk_categories(valid), valid["categories"])
        for invalid in (
            {**valid, "fallback_score": 49},
            {"categories": {**valid["categories"], "Unknown sector": 20}},
            {"categories": {**valid["categories"], "Retail": 10.5}},
            {"categories": {**valid["categories"], "Retail": True}},
        ):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    validate_sector_risk_categories(invalid)

    def test_invalid_update_does_not_replace_existing_policy(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sector-risk.json"
            before = load_sector_risk_policy()
            path.write_text(json.dumps(before), encoding="utf-8")
            invalid = {
                "fallback_score": 50,
                "categories": {**before["categories"], "Retail": float("inf")},
            }
            with self.assertRaises(ValueError):
                update_sector_risk_policy(invalid, path=path)
            self.assertEqual(load_sector_risk_policy(path), before)


if __name__ == "__main__":
    unittest.main()
