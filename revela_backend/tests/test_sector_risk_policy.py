"""Validation and bounds checks for editable PSIC sector-risk policy."""

import json
import unittest
from pathlib import Path

from api.analytics.sector_risk import (
    SECTOR_CATEGORIES,
    load_sector_risk_policy,
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
        display_defaults_path = Path(__file__).parents[1] / "api" / "analytics" / "display_sector_defaults.json"
        with display_defaults_path.open(encoding="utf-8") as defaults_file:
            display_labels = {entry[1] for entry in json.load(defaults_file).values()}
        self.assertEqual(display_labels, set(SECTOR_CATEGORIES))

    def test_policy_rejects_missing_extra_and_out_of_bounds_scores(self):
        original = load_sector_risk_policy()
        for invalid in (
            {**original, "categories": {**original["categories"], "Retail": 101}},
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


if __name__ == "__main__":
    unittest.main()
