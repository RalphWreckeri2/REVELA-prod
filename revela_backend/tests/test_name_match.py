from api.utils.name_match import name_match, parse_name
from api.flags.service import _match_poi_to_registry, _name_similarity
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..")))


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
        score = _name_similarity(
            "Mercedes Hardware", "Mercedes Hardware & Construction Supply")
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

    def test_accents_are_normalized_without_splitting_words(self):
        tokens, _ = parse_name("Jardín del Edén Event Venue")
        self.assertEqual(tokens, ["jardin", "eden"])

    def test_parse_name_cache_does_not_share_mutable_results(self):
        tokens, groups = parse_name("Silva Pharmacy")
        tokens.append("contaminated")
        groups.add("lodging")

        next_tokens, next_groups = parse_name("Silva Pharmacy")

        self.assertEqual(next_tokens, ["silva"])
        self.assertEqual(next_groups, {"pharmacy"})

    def test_eden_store_and_jardin_del_eden_are_category_conflict(self):
        score, decision = name_match(
            "Eden Store",
            "Jardín del Eden",
            reg_line="Supermarket",
            poi_types=("event_venue",),
        )
        self.assertEqual(decision, "category_conflict")
        self.assertLessEqual(score, 0.45)

        registry = [{
            "businessID": "BIZ-EDEN",
            "businessName": "Eden Store",
            "businessLine": "Supermarket",
            "businessType": "Supermarket",
            "businessAddress": "Poblacion, Mataasnakahoy",
            "barangayID": 1,
            "latitude": 13.9667,
            "longitude": 121.1167,
        }]
        matched, _, _, status = _match_poi_to_registry(
            "Jardín del Eden",
            13.96671,
            121.11671,
            registry,
            poi_barangay_id=1,
            poi_types=("event_venue",),
            poi_address="Poblacion, Mataasnakahoy",
        )
        self.assertIsNone(matched)
        self.assertEqual(status, "no_match")

    def test_single_shared_token_without_category_agreement_is_weak(self):
        score, decision = name_match("Eden Store", "Jardín del Eden")
        self.assertEqual(decision, "weak_name")
        self.assertLessEqual(score, 0.45)

    def test_single_brand_token_can_match_with_category_agreement(self):
        score, decision = name_match(
            "Eden Supermarket",
            "Eden Store",
            reg_line="Supermarket",
            poi_types=("supermarket",),
        )
        self.assertEqual(decision, "ok")
        self.assertGreaterEqual(score, 0.80)

    def test_address_similarity_is_supporting_evidence(self):
        from api.utils.name_match import address_similarity

        self.assertGreaterEqual(
            address_similarity(
                "Poblacion, Main Street, Mataasnakahoy",
                "Main St., Poblacion, Mataasnakahoy, Batangas",
            ),
            0.75,
        )


if __name__ == "__main__":
    unittest.main()
