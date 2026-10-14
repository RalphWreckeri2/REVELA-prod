"""Fail-closed configuration and authorization checks for the future pilot."""

from dataclasses import dataclass
import os
from typing import Mapping


PILOT_ENABLED_ENV = "NEARBY_BARANGAY_PILOT_ENABLED"
PILOT_MAX_REQUESTS_ENV = "NEARBY_BARANGAY_PILOT_MAX_REQUESTS"
PILOT_HARD_MAX_REQUESTS = 5


@dataclass(frozen=True)
class NearbyBarangayPilotConfig:
    enabled: bool
    max_requests: int | None
    configuration_error: str | None = None


def load_pilot_config(
    environ: Mapping[str, object] | None = None,
) -> NearbyBarangayPilotConfig:
    """Load the explicit pilot gate and strict per-run attempt limit."""
    environ = os.environ if environ is None else environ
    gate_value = environ.get(PILOT_ENABLED_ENV)
    if gate_value != "1":
        error = (
            f"{PILOT_ENABLED_ENV} must be exactly '0' or '1'."
            if gate_value not in (None, "0")
            else None
        )
        return NearbyBarangayPilotConfig(
            enabled=False,
            max_requests=None,
            configuration_error=error,
        )

    raw_limit = environ.get(PILOT_MAX_REQUESTS_ENV)
    if (
        not isinstance(raw_limit, str)
        or not raw_limit.isascii()
        or not raw_limit.isdigit()
    ):
        return NearbyBarangayPilotConfig(
            enabled=False,
            max_requests=None,
            configuration_error=(
                f"{PILOT_MAX_REQUESTS_ENV} must be an integer between 1 "
                f"and {PILOT_HARD_MAX_REQUESTS}."
            ),
        )

    request_limit = int(raw_limit)
    if not 1 <= request_limit <= PILOT_HARD_MAX_REQUESTS:
        return NearbyBarangayPilotConfig(
            enabled=False,
            max_requests=None,
            configuration_error=(
                f"{PILOT_MAX_REQUESTS_ENV} must be an integer between 1 "
                f"and {PILOT_HARD_MAX_REQUESTS}."
            ),
        )

    return NearbyBarangayPilotConfig(
        enabled=True,
        max_requests=request_limit,
    )


def validate_pilot_authorization(
    config: NearbyBarangayPilotConfig,
    persisted_authorized: bool,
    live_confirmation: bool,
    barangay_id: int,
    requested_budget: int,
) -> tuple[bool, str | None]:
    """Purely validate every explicit gate required for a future live pilot."""
    if (
        not isinstance(config, NearbyBarangayPilotConfig)
        or config.enabled is not True
        or isinstance(config.max_requests, bool)
        or not isinstance(config.max_requests, int)
        or not 1 <= config.max_requests <= PILOT_HARD_MAX_REQUESTS
    ):
        error = (
            config.configuration_error
            if isinstance(config, NearbyBarangayPilotConfig)
            else None
        )
        return False, error or "Pilot environment gate is disabled."
    if persisted_authorized is not True:
        return False, "Persisted pilot authorization is not enabled."
    if live_confirmation is not True:
        return False, "Explicit live-run confirmation is required."
    if (
        isinstance(barangay_id, bool)
        or not isinstance(barangay_id, int)
        or barangay_id <= 0
    ):
        return False, "A positive integer barangay ID is required."
    if (
        isinstance(requested_budget, bool)
        or not isinstance(requested_budget, int)
        or requested_budget <= 0
        or requested_budget > PILOT_HARD_MAX_REQUESTS
        or requested_budget > config.max_requests
    ):
        return False, (
            "Requested budget must be positive and no greater than the "
            "configured and hard pilot limits."
        )
    return True, None
