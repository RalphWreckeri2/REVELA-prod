import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from api.utils.matching_evaluation import evaluate_labeled_cases


def make_case(case_id, expected_id, poi_name, candidate_name, candidate_id):
    return {
        "case_id": case_id,
        "reviewed_by": "reviewer-1",
        "reviewed_at": "2026-10-11",
        "label_source": "BPLO record and field confirmation",
        "expected_business_id": expected_id,
        "poi": {
            "name": poi_name,
            "latitude": 13.96671,
            "longitude": 121.11671,
            "barangay_id": 1,
            "types": ["bakery"],
            "address": "Main Street",
        },
        "registry_candidates": [{
            "businessID": candidate_id,
            "businessName": candidate_name,
            "businessLine": "Bakery",
            "businessType": "Retail",
            "businessAddress": "Main Street",
            "barangayID": 1,
            "latitude": 13.9667,
            "longitude": 121.1167,
        }],
    }


class MatchingEvaluationTests(unittest.TestCase):
    def test_metrics_report_false_matches_and_missed_matches(self):
        cases = [
            make_case("correct", "BIZ-1", "Luna Bakery", "Luna Bakery", "BIZ-1"),
            make_case("false", None, "Luna Bakery", "Luna Bakery", "BIZ-2"),
            make_case("missed", "BIZ-3", "Different Bakery", "Luna Bakery", "BIZ-3"),
        ]

        report = evaluate_labeled_cases(cases)

        self.assertEqual(report["auto_match_true_positives"], 1)
        self.assertEqual(report["auto_match_false_positives"], 1)
        self.assertEqual(report["auto_match_false_negatives"], 1)
        self.assertEqual(report["precision"], 0.5)
        self.assertEqual(report["recall"], 0.5)
        self.assertEqual(report["f1_score"], 0.5)
        self.assertEqual([case["case_id"] for case in report["false_matches"]], ["false"])
        self.assertEqual([case["case_id"] for case in report["missed_matches"]], ["missed"])

    def test_review_only_candidate_is_reported_not_counted_as_auto_match(self):
        case = make_case(
            "review", "BIZ-1", "Luna Store", "Luna Bakery", "BIZ-1"
        )
        case["poi"]["types"] = ["store"]

        with patch(
            "api.utils.matching_evaluation._match_poi_to_registry",
            return_value=(case["registry_candidates"][0], 10, 0.6, "review"),
        ):
            report = evaluate_labeled_cases([case])

        self.assertEqual(report["review_cases"], 1)
        self.assertEqual(report["auto_match_false_negatives"], 1)
        self.assertIsNone(report["precision"])
        self.assertEqual(report["recall"], 0.0)
        self.assertIsNone(report["f1_score"])

    def test_wrong_auto_selected_id_is_both_false_and_missed_match(self):
        case = make_case(
            "wrong-id", "EXPECTED", "Luna Bakery", "Luna Bakery", "WRONG"
        )

        report = evaluate_labeled_cases([case])

        self.assertEqual(report["auto_match_false_positives"], 1)
        self.assertEqual(report["auto_match_false_negatives"], 1)
        self.assertEqual(report["false_matches"][0]["predicted_business_id"], "WRONG")
        self.assertEqual(report["missed_matches"][0]["expected_business_id"], "EXPECTED")

    def test_human_label_provenance_and_explicit_expected_id_are_required(self):
        case = make_case("missing-label", "BIZ-1", "Luna Bakery", "Luna Bakery", "BIZ-1")
        del case["expected_business_id"]

        with self.assertRaisesRegex(ValueError, "expected_business_id"):
            evaluate_labeled_cases([case])

        case = make_case("missing-reviewer", "BIZ-1", "Luna Bakery", "Luna Bakery", "BIZ-1")
        case["reviewed_by"] = ""
        with self.assertRaisesRegex(ValueError, "reviewed_by"):
            evaluate_labeled_cases([case])

        case = make_case("invalid-date", "BIZ-1", "Luna Bakery", "Luna Bakery", "BIZ-1")
        case["reviewed_at"] = "20261011"
        with self.assertRaisesRegex(ValueError, "YYYY-MM-DD"):
            evaluate_labeled_cases([case])

    def test_duplicate_case_ids_are_rejected(self):
        case = make_case("duplicate", None, "Unknown Shop", "Luna Bakery", "BIZ-1")
        with self.assertRaisesRegex(ValueError, "unique"):
            evaluate_labeled_cases([case, case])


if __name__ == "__main__":
    unittest.main()
