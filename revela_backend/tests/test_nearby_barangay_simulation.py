"""Offline integration tests composing the barangay pilot safety helpers."""

import unittest

from shapely.geometry import Polygon

from api.utils.nearby_barangay_pilot import (
    PILOT_ENABLED_ENV,
    PILOT_MAX_REQUESTS_ENV,
    load_pilot_config,
)
from api.utils.nearby_barangay_simulation import (
    simulate_offline_barangay_pilot,
)


def polygon():
    return Polygon([
        (121.0, 13.0),
        (121.01, 13.0),
        (121.01, 13.01),
        (121.0, 13.01),
        (121.0, 13.0),
    ])


def config(limit="5", enabled="1"):
    return load_pilot_config({
        PILOT_ENABLED_ENV: enabled,
        PILOT_MAX_REQUESTS_ENV: limit,
    })


def candidate(place_id, lat=13.005, lng=121.005, kinds=None):
    return {
        "place_id": place_id,
        "latitude": lat,
        "longitude": lng,
        "attempt_kinds": kinds or ["initial"],
    }


def simulate(callback, **overrides):
    arguments = {
        "config": config(),
        "persisted_authorized": True,
        "live_confirmation": True,
        "barangay_id": 7,
        "authoritative_polygon": polygon(),
        "requested_budget": 5,
        "candidate_places": [candidate("place-a")],
        "registry_records": [],
        "existing_flags": [],
        "attempt_callback": callback,
    }
    arguments.update(overrides)
    return simulate_offline_barangay_pilot(**arguments)


class NearbyBarangaySimulationTests(unittest.TestCase):

    def test_all_four_helpers_compose_for_safe_same_barangay_match(self):
        callback_arguments = []

        def in_memory_attempt(place, kind, reservation):
            callback_arguments.append(
                (place["place_id"], kind.value, reservation.attempt_number)
            )
            return True

        result = simulate(
            in_memory_attempt,
            candidate_places=[candidate(
                "place-a",
                kinds=["initial", "retry", "adaptive"],
            )],
            registry_records=[{
                "place_id": "place-a",
                "barangay_id": 7,
            }],
            existing_flags=[{
                "place_id": "place-a",
                "barangay_id": 7,
            }],
            requested_budget=3,
        )

        self.assertEqual(result["status"], "completed")
        self.assertEqual(callback_arguments, [
            ("place-a", "initial", 1),
            ("place-a", "retry", 2),
            ("place-a", "adaptive", 3),
        ])
        self.assertEqual(
            result["permitted_operations"][0]["permitted_operations"],
            ["flag_delete", "flag_update", "registry_match"],
        )
        self.assertEqual(result["rejected_operations"], [])
        self.assertEqual(result["budget"], {
            "authorized_budget": 3,
            "attempts_reserved": 3,
            "remaining": 0,
        })

    def test_unauthorized_run_is_rejected_before_any_callback(self):
        callback_arguments = []
        result = simulate(
            lambda *args: callback_arguments.append(args),
            persisted_authorized=False,
        )

        self.assertEqual(result["status"], "denied")
        self.assertIsNotNone(result["authorization_error"])
        self.assertEqual(callback_arguments, [])
        self.assertEqual(result["budget"]["attempts_reserved"], 0)

    def test_out_of_polygon_place_is_rejected_without_request(self):
        callback_arguments = []
        result = simulate(
            lambda *args: callback_arguments.append(args),
            candidate_places=[candidate(
                "outside",
                lat=13.02,
                lng=121.005,
            )],
        )

        self.assertEqual(result["status"], "completed_with_rejections")
        self.assertEqual(len(result["rejected_operations"]), 1)
        self.assertEqual(
            result["rejected_operations"][0]["rejection_reason"],
            "place_outside_barangay_scope",
        )
        self.assertEqual(callback_arguments, [])
        self.assertEqual(result["budget"]["attempts_reserved"], 0)

    def test_cross_barangay_registry_and_flag_rows_are_rejected(self):
        result = simulate(
            lambda *args: True,
            candidate_places=[
                candidate("cross-registry"),
                candidate("cross-flag"),
            ],
            registry_records=[{
                "place_id": "cross-registry",
                "barangay_id": 8,
            }],
            existing_flags=[{
                "place_id": "cross-flag",
                "barangay_id": 8,
            }],
        )

        self.assertEqual(result["status"], "completed_with_rejections")
        reasons = {
            item["place_id"]: item["rejection_reason"]
            for item in result["rejected_operations"]
        }
        self.assertEqual(
            reasons["cross-registry"],
            "registry_candidate_outside_barangay_scope",
        )
        self.assertEqual(
            reasons["cross-flag"],
            "existing_flag_outside_barangay_scope",
        )
        self.assertEqual(result["attempts"], [])
        self.assertEqual(result["budget"]["attempts_reserved"], 0)

    def test_missing_assignment_and_ambiguous_records_fail_closed(self):
        result = simulate(
            lambda *args: self.fail("rejected records must not call callback"),
            candidate_places=[
                candidate("missing-assignment"),
                candidate("ambiguous"),
            ],
            registry_records=[
                {
                    "place_id": "missing-assignment",
                    "barangay_id": None,
                },
                {
                    "place_id": "ambiguous",
                    "barangay_id": 7,
                },
                {
                    "place_id": "ambiguous",
                    "barangay_id": 7,
                },
            ],
        )

        reasons = {
            item["place_id"]: item["rejection_reason"]
            for item in result["rejected_operations"]
        }
        self.assertEqual(
            reasons["missing-assignment"],
            "missing_or_invalid_registry_barangay_assignment",
        )
        self.assertEqual(reasons["ambiguous"], "ambiguous_registry_candidates")
        self.assertEqual(result["budget"]["attempts_reserved"], 0)

    def test_attempt_failures_consume_budget_and_exhaustion_stops_callbacks(self):
        callback_attempts = []

        def failed_attempt(place, kind, reservation):
            callback_attempts.append(
                (place["place_id"], kind.value, reservation.attempt_number)
            )
            return False

        result = simulate(
            failed_attempt,
            requested_budget=2,
            candidate_places=[
                candidate("first", kinds=["initial", "retry"]),
                candidate("second", kinds=["initial"]),
            ],
        )

        self.assertEqual(result["status"], "budget_exhausted")
        self.assertEqual(callback_attempts, [
            ("first", "initial", 1),
            ("first", "retry", 2),
        ])
        self.assertEqual(result["attempts"][-1], {
            "candidate_index": 1,
            "kind": "initial",
            "outcome": "not_attempted_budget_exhausted",
        })
        self.assertEqual(result["budget"], {
            "authorized_budget": 2,
            "attempts_reserved": 2,
            "remaining": 0,
        })

    def test_attempt_failure_is_reported_without_refunding_budget(self):
        result = simulate(
            lambda *_args: False,
            requested_budget=2,
            candidate_places=[candidate(
                "failed-once",
                kinds=["initial"],
            )],
        )

        self.assertEqual(result["status"], "completed_with_attempt_failures")
        self.assertEqual(result["attempts"][0]["outcome"], "failed")
        self.assertEqual(result["budget"]["attempts_reserved"], 1)
        self.assertEqual(result["budget"]["remaining"], 1)

    def test_invalid_geometry_and_attempt_schedule_fail_closed(self):
        callback_attempts = []
        bad_geometry = simulate(
            lambda *args: callback_attempts.append(args),
            authoritative_polygon=None,
        )
        self.assertEqual(bad_geometry["status"], "denied")
        self.assertEqual(callback_attempts, [])

        bad_schedule = simulate(
            lambda *args: callback_attempts.append(args),
            candidate_places=[candidate("bad-schedule", kinds=["retry"])],
        )
        self.assertEqual(
            bad_schedule["rejected_operations"][0]["rejection_reason"],
            "attempt_schedule_must_begin_with_initial",
        )
        self.assertEqual(callback_attempts, [])


if __name__ == "__main__":
    unittest.main()
