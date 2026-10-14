"""Thread-safe per-run request budget for a future barangay pilot."""

from dataclasses import dataclass
from enum import Enum
import threading
from typing import Any

from api.utils.nearby_barangay_pilot import PILOT_HARD_MAX_REQUESTS


class RequestAttemptKind(str, Enum):
    INITIAL = "initial"
    RETRY = "retry"
    ADAPTIVE = "adaptive"


class RequestBudgetExhausted(RuntimeError):
    """Raised when no additional pilot request attempt can be reserved."""


@dataclass(frozen=True)
class RequestReservation:
    attempt_number: int
    kind: RequestAttemptKind


@dataclass(frozen=True)
class RequestBudgetSnapshot:
    authorized_budget: int
    attempts_reserved: int
    remaining: int


class NearbyBarangayRequestBudget:
    """Reserve every initial, retry, and adaptive attempt before it is sent."""

    def __init__(self, authorized_budget: Any, *, authorized: bool):
        if authorized is not True:
            raise PermissionError("An authorized pilot request budget is required.")
        if (
            isinstance(authorized_budget, bool)
            or not isinstance(authorized_budget, int)
            or not 1 <= authorized_budget <= PILOT_HARD_MAX_REQUESTS
        ):
            raise ValueError(
                "Authorized request budget must be an integer between 1 "
                f"and {PILOT_HARD_MAX_REQUESTS}."
            )

        self._authorized_budget = authorized_budget
        self._attempts_reserved = 0
        self._lock = threading.Lock()

    def reserve_attempt(self, kind: RequestAttemptKind) -> RequestReservation:
        """Atomically consume one slot or raise before an HTTP attempt."""
        if not isinstance(kind, RequestAttemptKind):
            raise ValueError("Request attempt kind must be a RequestAttemptKind.")

        with self._lock:
            if self._attempts_reserved >= self._authorized_budget:
                raise RequestBudgetExhausted(
                    "The authorized pilot request budget is exhausted."
                )
            self._attempts_reserved += 1
            return RequestReservation(
                attempt_number=self._attempts_reserved,
                kind=kind,
            )

    @property
    def attempts_reserved(self) -> int:
        with self._lock:
            return self._attempts_reserved

    @property
    def remaining(self) -> int:
        with self._lock:
            return self._authorized_budget - self._attempts_reserved

    def snapshot(self) -> RequestBudgetSnapshot:
        with self._lock:
            return RequestBudgetSnapshot(
                authorized_budget=self._authorized_budget,
                attempts_reserved=self._attempts_reserved,
                remaining=self._authorized_budget - self._attempts_reserved,
            )
