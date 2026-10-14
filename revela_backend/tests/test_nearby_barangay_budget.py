"""Offline tests for the isolated barangay pilot request budget."""

from concurrent.futures import ThreadPoolExecutor
import unittest

from api.utils.nearby_barangay_budget import (
    NearbyBarangayRequestBudget,
    RequestAttemptKind,
    RequestBudgetExhausted,
)
from api.utils.nearby_barangay_pilot import PILOT_HARD_MAX_REQUESTS


class NearbyBarangayRequestBudgetTests(unittest.TestCase):

    def test_budget_of_one_reserves_one_attempt_then_exhausts(self):
        budget = NearbyBarangayRequestBudget(1, authorized=True)
        reservation = budget.reserve_attempt(RequestAttemptKind.INITIAL)

        self.assertEqual(reservation.attempt_number, 1)
        self.assertEqual(budget.attempts_reserved, 1)
        self.assertEqual(budget.remaining, 0)
        with self.assertRaises(RequestBudgetExhausted):
            budget.reserve_attempt(RequestAttemptKind.RETRY)

    def test_budget_of_five_allows_exactly_five_attempts(self):
        budget = NearbyBarangayRequestBudget(
            PILOT_HARD_MAX_REQUESTS, authorized=True
        )
        reservations = [
            budget.reserve_attempt(RequestAttemptKind.INITIAL)
            for _ in range(PILOT_HARD_MAX_REQUESTS)
        ]

        self.assertEqual(
            [reservation.attempt_number for reservation in reservations],
            [1, 2, 3, 4, 5],
        )
        self.assertEqual(budget.snapshot().attempts_reserved, 5)
        self.assertEqual(budget.snapshot().remaining, 0)

    def test_initial_retries_and_adaptive_requests_count_equally(self):
        budget = NearbyBarangayRequestBudget(4, authorized=True)
        kinds = (
            RequestAttemptKind.INITIAL,
            RequestAttemptKind.RETRY,
            RequestAttemptKind.RETRY,
            RequestAttemptKind.ADAPTIVE,
        )

        reservations = [budget.reserve_attempt(kind) for kind in kinds]

        self.assertEqual(
            [reservation.kind for reservation in reservations],
            list(kinds),
        )
        self.assertEqual(budget.attempts_reserved, 4)
        self.assertEqual(budget.remaining, 0)

    def test_failed_attempt_has_no_refund_path(self):
        budget = NearbyBarangayRequestBudget(1, authorized=True)
        budget.reserve_attempt(RequestAttemptKind.INITIAL)

        with self.assertRaises(RequestBudgetExhausted):
            budget.reserve_attempt(RequestAttemptKind.RETRY)

        self.assertEqual(budget.attempts_reserved, 1)
        self.assertEqual(budget.remaining, 0)
        self.assertFalse(hasattr(budget, "refund"))

    def test_invalid_or_unauthorized_budgets_are_rejected(self):
        for invalid_budget in (
            None, 0, -1, 6, True, 1.0, "1",
        ):
            with self.subTest(budget=invalid_budget):
                with self.assertRaises(ValueError):
                    NearbyBarangayRequestBudget(
                        invalid_budget, authorized=True
                    )
        with self.assertRaises(PermissionError):
            NearbyBarangayRequestBudget(1, authorized=False)
        with self.assertRaises(PermissionError):
            NearbyBarangayRequestBudget(1, authorized=None)

    def test_invalid_attempt_kind_does_not_reserve_a_slot(self):
        budget = NearbyBarangayRequestBudget(2, authorized=True)

        with self.assertRaises(ValueError):
            budget.reserve_attempt("retry")

        self.assertEqual(budget.attempts_reserved, 0)
        self.assertEqual(budget.remaining, 2)

    def test_concurrent_reservations_never_exceed_authorized_budget(self):
        budget = NearbyBarangayRequestBudget(5, authorized=True)

        def reserve_one(_):
            try:
                budget.reserve_attempt(RequestAttemptKind.ADAPTIVE)
                return True
            except RequestBudgetExhausted:
                return False

        with ThreadPoolExecutor(max_workers=20) as executor:
            outcomes = list(executor.map(reserve_one, range(100)))

        self.assertEqual(sum(outcomes), 5)
        self.assertEqual(budget.attempts_reserved, 5)
        self.assertEqual(budget.remaining, 0)


if __name__ == "__main__":
    unittest.main()
