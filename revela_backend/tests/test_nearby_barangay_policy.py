"""Offline registry/flag authorization tests for the barangay pilot."""

import unittest

from shapely.geometry import Polygon

from api.utils.nearby_barangay_policy import (
    ScopeOperation,
    decide_barangay_scope_operations,
)
from api.utils.nearby_barangay_scope import validate_barangay_scope


def make_scope(barangay_id=7):
    polygon = Polygon([
        (121.0, 13.0),
        (121.01, 13.0),
        (121.01, 13.01),
        (121.0, 13.01),
        (121.0, 13.0),
    ])
    return validate_barangay_scope(barangay_id, polygon)


def decide(**overrides):
    args = {
        "selected_barangay_id": 7,
        "validated_scope": make_scope(),
        "candidate_place_id": "place-123",
        "latitude": 13.005,
        "longitude": 121.005,
    }
    args.update(overrides)
    return decide_barangay_scope_operations(**args)


class NearbyBarangayPolicyTests(unittest.TestCase):

    def test_same_barangay_registry_match_and_existing_flag_are_permitted(self):
        decision = decide(
            registry_candidate_barangay_id=7,
            existing_flag_barangay_id=7,
            registry_candidate_present=True,
            existing_flag_present=True,
        )

        self.assertTrue(decision.permitted)
        self.assertIsNone(decision.rejection_reason)
        self.assertEqual(
            decision.allowed_operations,
            frozenset({
                ScopeOperation.REGISTRY_MATCH,
                ScopeOperation.FLAG_UPDATE,
                ScopeOperation.FLAG_DELETE,
            }),
        )

    def test_registry_candidate_in_a_different_barangay_is_rejected(self):
        decision = decide(
            registry_candidate_barangay_id=8,
            registry_candidate_present=True,
        )

        self.assertFalse(decision.permitted)
        self.assertEqual(
            decision.rejection_reason,
            "registry_candidate_outside_barangay_scope",
        )

    def test_same_place_id_does_not_authorize_cross_barangay_flag(self):
        decision = decide(
            candidate_place_id="same-place-id",
            existing_flag_barangay_id=8,
            existing_flag_present=True,
        )

        self.assertFalse(decision.permitted)
        self.assertEqual(
            decision.rejection_reason,
            "existing_flag_outside_barangay_scope",
        )
        self.assertNotIn(
            ScopeOperation.FLAG_UPDATE, decision.allowed_operations
        )
        self.assertNotIn(
            ScopeOperation.FLAG_DELETE, decision.allowed_operations
        )

    def test_missing_or_invalid_applicable_assignments_fail_closed(self):
        cases = (
            {
                "registry_candidate_present": True,
                "registry_candidate_barangay_id": None,
            },
            {
                "registry_candidate_present": True,
                "registry_candidate_barangay_id": 0,
            },
            {
                "registry_candidate_present": True,
                "registry_candidate_barangay_id": True,
            },
            {
                "existing_flag_present": True,
                "existing_flag_barangay_id": None,
            },
            {
                "existing_flag_present": True,
                "existing_flag_barangay_id": "7",
            },
            {
                "existing_flag_present": True,
                "existing_flag_barangay_id": False,
            },
            {
                "registry_candidate_barangay_id": 7,
                "registry_candidate_present": False,
            },
            {
                "existing_flag_barangay_id": 7,
                "existing_flag_present": False,
            },
        )
        for values in cases:
            with self.subTest(values=values):
                self.assertFalse(decide(**values).permitted)

    def test_place_outside_polygon_is_rejected_before_operations(self):
        decision = decide(latitude=13.02, longitude=121.005)

        self.assertFalse(decision.permitted)
        self.assertEqual(
            decision.rejection_reason,
            "place_outside_barangay_scope",
        )

    def test_missing_or_invalid_scope_is_rejected(self):
        self.assertFalse(decide(validated_scope=None).permitted)
        self.assertFalse(
            decide(
                validated_scope=make_scope(8),
                selected_barangay_id=7,
            ).permitted
        )
        self.assertFalse(decide(selected_barangay_id=True).permitted)

    def test_unregistered_place_allows_only_scoped_flag_insert(self):
        decision = decide()

        self.assertTrue(decision.permitted)
        self.assertEqual(
            decision.allowed_operations,
            frozenset({ScopeOperation.FLAG_INSERT}),
        )
        self.assertNotIn(
            ScopeOperation.FLAG_UPDATE, decision.allowed_operations
        )
        self.assertNotIn(
            ScopeOperation.FLAG_DELETE, decision.allowed_operations
        )


if __name__ == "__main__":
    unittest.main()
