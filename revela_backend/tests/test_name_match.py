import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from api.flags.service import _name_similarity
from api.utils.name_match import name_match, parse_name


class NameMatchRegressionTests(unittest.TestCase):
    """
    Phase 0 & Phase 1 Test Suite:
    Validates category-aware name normalization, token overlap, and boundary rules.
    """

    def test_tc01_same_surname_conflicting_category_no_match(self):
        """
        'Silva's Pharmacy' vs 'Silva's Apartment'
        Category conflict (Pharmacy vs Lodging) capped at <= 0.45 (No Match).
        """
        score = _name_similarity("Silva's Pharmacy", "Silva's Apartment")
        self.assertLessEqual(
            score, 0.45,
            f"Expected score <= 0.45 for category conflict (Pharmacy vs Apartment), but got {score:.2f}"
        )

    def test_tc02_different_categories_same_first_name_no_match(self):
        """
        'Jose Store' vs 'Jose Bakery'
        Generic retail vs specialized bakery capped at <= 0.50 (No Match).
        """
        score = _name_similarity("Jose Store", "Jose Bakery")
        self.assertLessEqual(
            score, 0.50,
            f"Expected score <= 0.50 for generic retail vs bakery, but got {score:.2f}"
        )

    def test_tc03_substring_containment_trap_no_match(self):
        """
        'Ana's' vs 'Banana Store'
        Prevent false-positive substring containment ('ana' in 'banana').
        """
        score = _name_similarity("Ana's", "Banana Store")
        self.assertLessEqual(
            score, 0.35,
            f"Expected score <= 0.35 for Ana's vs Banana Store, but got {score:.2f}"
        )

    def test_tc04_valid_category_synonym_matches(self):
        """
        'Silva's Pharmacy' vs 'Silva Drugstore'
        Valid commercial synonym expansion (Pharmacy <-> Drugstore).
        Expected: Score >= 0.80 (Auto-Snap candidate tier).
        """
        score = _name_similarity("Silva's Pharmacy", "Silva Drugstore")
        self.assertGreaterEqual(
            score, 0.80,
            f"Expected score >= 0.80 for Pharmacy vs Drugstore, but got {score:.2f}"
        )

    def test_tc05_trade_name_expansion_matches(self):
        """
        'Mercedes Hardware' vs 'Mercedes Hardware & Construction Supply'
        Valid elaboration within the same commercial category.
        Expected: Score >= 0.80 (Auto-Snap candidate tier).
        """
        score = _name_similarity("Mercedes Hardware", "Mercedes Hardware & Construction Supply")
        self.assertGreaterEqual(
            score, 0.80,
            f"Expected score >= 0.80 for Hardware trade name expansion, but got {score:.2f}"
        )

    def test_tc06_specific_vs_generic_routes_to_review(self):
        """
        'Silva's Pharmacy' vs 'Silva Store'
        Ambiguous case: specific pharmacy vs general store.
        Expected: Score between 0.55 and 0.75 (Review range, never auto-snap).
        """
        score = _name_similarity("Silva's Pharmacy", "Silva Store")
        self.assertGreaterEqual(
            score, 0.55,
            f"Expected score >= 0.55 for review candidate, got {score:.2f}"
        )
        self.assertLess(
            score, 0.75,
            f"Expected score < 0.75 to prevent premature auto-snap, got {score:.2f}"
        )

    def test_tc07_category_extracted_from_line_of_business_and_poi_types(self):
        """
        'Generika Branch' + lineOfBusiness='Retail Selling of Pharmaceutical Drugs'
        vs 'Generika' + types=('pharmacy', 'health')
        Should detect matching category and boost score.
        """
        score, decision = name_match(
            "Generika Branch",
            "Generika",
            reg_line="Retail Selling of Pharmaceutical Drugs",
            poi_types=("pharmacy", "health")
        )
        self.assertEqual(decision, "ok")
        self.assertGreaterEqual(score, 0.80)

    def test_tc08_lone_surname_different_category_capped_low(self):
        """
        'Tan Medical Clinic' vs 'Tan Bakeshop'
        Different specialties sharing only a single surname.
        Score must be capped at <= 0.45 (No Match).
        """
        score, decision = name_match("Tan Medical Clinic", "Tan Bakeshop")
        self.assertEqual(decision, "category_conflict")
        self.assertLessEqual(score, 0.45)

    def test_tc09_initials_gap_does_not_auto_snap(self):
        """
        'J&M Trading' vs 'JM Enterprises'
        Initials mismatch correctly falls below auto-snap threshold.
        """
        score, _ = name_match("J&M Trading", "JM Enterprises")
        self.assertLess(score, 0.80)

    def test_tc10_empty_and_none_handled_gracefully(self):
        """Ensure empty strings or None inputs return 0.0 without exceptions."""
        score1, _ = name_match("", "")
        score2, _ = name_match(None, "Silva Store")
        score3, _ = name_match("Jose Store", None)
        self.assertEqual(score1, 0.0)
        self.assertEqual(score2, 0.0)
        self.assertEqual(score3, 0.0)


if __name__ == "__main__":
    unittest.main()
