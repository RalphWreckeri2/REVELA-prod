"""In-memory composition of the offline barangay-pilot safety helpers."""

from collections.abc import Callable, Mapping, Sequence
from typing import Any

from api.utils.nearby_barangay_budget import (
    NearbyBarangayRequestBudget,
    RequestAttemptKind,
    RequestBudgetExhausted,
)
from api.utils.nearby_barangay_pilot import (
    NearbyBarangayPilotConfig,
    validate_pilot_authorization,
)
from api.utils.nearby_barangay_policy import (
    BarangayScopeDecision,
    decide_barangay_scope_operations,
)
from api.utils.nearby_barangay_scope import validate_barangay_scope


def simulate_offline_barangay_pilot(
    *,
    config: NearbyBarangayPilotConfig,
    persisted_authorized: bool,
    live_confirmation: bool,
    barangay_id: Any,
    authoritative_polygon: Any,
    requested_budget: Any,
    candidate_places: Any,
    registry_records: Any,
    existing_flags: Any,
    attempt_callback: Callable[
        [Mapping[str, Any], RequestAttemptKind, Any], Any
    ],
) -> dict[str, Any]:
    """Simulate scoped decisions and request attempts without persistence/HTTP.

    `attempt_callback` is an injected test double and is called only after
    authorization, geometry validation, candidate validation, and budget
    reservation. It must be an in-memory callback; it is never imported here.
    No callback result can trigger a real flag operation.
    """
    authorized, authorization_error = validate_pilot_authorization(
        config,
        persisted_authorized,
        live_confirmation,
        barangay_id,
        requested_budget,
    )
    if not authorized:
        return _summary(
            status="denied",
            authorization_error=authorization_error,
            scope_error=None,
            decisions=[],
            attempts=[],
            budget=None,
        )

    try:
        scope = validate_barangay_scope(
            barangay_id,
            authoritative_polygon,
        )
    except Exception as exc:
        return _summary(
            status="denied",
            authorization_error=None,
            scope_error=type(exc).__name__,
            decisions=[],
            attempts=[],
            budget=None,
        )

    if not callable(attempt_callback):
        return _summary(
            status="denied",
            authorization_error=None,
            scope_error="invalid_attempt_callback",
            decisions=[],
            attempts=[],
            budget=None,
        )

    if not isinstance(candidate_places, Sequence) or isinstance(
        candidate_places, (str, bytes)
    ):
        return _summary(
            status="denied",
            authorization_error=None,
            scope_error="candidate_places_must_be_a_sequence",
            decisions=[],
            attempts=[],
            budget=None,
        )

    if not _record_sequence(registry_records) or not _record_sequence(
        existing_flags
    ):
        return _summary(
            status="denied",
            authorization_error=None,
            scope_error="registry_records_and_existing_flags_must_be_sequences",
            decisions=[],
            attempts=[],
            budget=None,
        )

    candidates = list(candidate_places)
    registries = list(registry_records)
    flags = list(existing_flags)
    if any(not isinstance(item, Mapping) for item in candidates):
        return _summary(
            status="denied",
            authorization_error=None,
            scope_error="malformed_candidate_place",
            decisions=[],
            attempts=[],
            budget=None,
        )
    if any(not isinstance(item, Mapping) for item in (*registries, *flags)):
        return _summary(
            status="denied",
            authorization_error=None,
            scope_error="malformed_registry_or_flag_record",
            decisions=[],
            attempts=[],
            budget=None,
        )

    prepared = []
    for index, place in enumerate(candidates):
        place_id = place.get("place_id")
        matching_registry = [
            item for item in registries
            if item.get("place_id") == place_id
        ]
        matching_flags = [
            item for item in flags
            if item.get("place_id") == place_id
        ]

        if len(matching_registry) > 1:
            decision = _rejected_decision("ambiguous_registry_candidates")
        elif len(matching_flags) > 1:
            decision = _rejected_decision("ambiguous_existing_flags")
        else:
            registry_record = matching_registry[0] if matching_registry else None
            flag_record = matching_flags[0] if matching_flags else None
            decision = decide_barangay_scope_operations(
                selected_barangay_id=barangay_id,
                validated_scope=scope,
                candidate_place_id=place_id,
                latitude=place.get("latitude"),
                longitude=place.get("longitude"),
                registry_candidate_barangay_id=(
                    registry_record.get("barangay_id")
                    if registry_record is not None else None
                ),
                existing_flag_barangay_id=(
                    flag_record.get("barangay_id")
                    if flag_record is not None else None
                ),
                registry_candidate_present=registry_record is not None,
                existing_flag_present=flag_record is not None,
            )

        attempt_kinds, schedule_error = _attempt_schedule(
            place.get("attempt_kinds")
        )
        if decision.permitted and schedule_error:
            decision = _rejected_decision(schedule_error)

        prepared.append({
            "candidate_index": index,
            "place_id": place_id,
            "decision": decision,
            "place": place,
            "attempt_kinds": attempt_kinds,
        })

    budget = NearbyBarangayRequestBudget(
        requested_budget,
        authorized=True,
    )
    attempt_records = []
    exhausted = False
    for item in prepared:
        decision = item["decision"]
        if not decision.permitted:
            continue
        for kind in item["attempt_kinds"]:
            try:
                reservation = budget.reserve_attempt(kind)
            except RequestBudgetExhausted:
                exhausted = True
                attempt_records.append({
                    "candidate_index": item["candidate_index"],
                    "kind": kind.value,
                    "outcome": "not_attempted_budget_exhausted",
                })
                break

            try:
                callback_result = attempt_callback(
                    item["place"], kind, reservation
                )
                outcome = (
                    "success" if callback_result is True
                    else "failed" if callback_result is False
                    else "rejected_invalid_callback_result"
                )
            except Exception as exc:
                outcome = f"failed:{type(exc).__name__}"
            attempt_records.append({
                "candidate_index": item["candidate_index"],
                "kind": kind.value,
                "attempt_number": reservation.attempt_number,
                "outcome": outcome,
            })
        if exhausted:
            break

    decisions = [
        {
            "candidate_index": item["candidate_index"],
            "place_id": item["place_id"],
            "permitted_operations": sorted(
                operation.value
                for operation in item["decision"].allowed_operations
            ),
            "rejection_reason": item["decision"].rejection_reason,
        }
        for item in prepared
    ]
    return _summary(
        status=(
            "budget_exhausted" if exhausted
            else "completed_with_rejections"
            if any(not item["decision"].permitted for item in prepared)
            else "completed_with_attempt_failures"
            if any(item["outcome"] != "success" for item in attempt_records)
            else "completed"
        ),
        authorization_error=None,
        scope_error=None,
        decisions=decisions,
        attempts=attempt_records,
        budget=budget.snapshot(),
    )


def _record_sequence(value: Any) -> bool:
    return isinstance(value, Sequence) and not isinstance(
        value, (str, bytes)
    )


def _attempt_schedule(
    value: Any,
) -> tuple[list[RequestAttemptKind], str | None]:
    if not _record_sequence(value) or not value:
        return [], "missing_attempt_schedule"
    kinds = []
    for raw_kind in value:
        try:
            kinds.append(RequestAttemptKind(raw_kind))
        except (TypeError, ValueError):
            return [], "invalid_attempt_schedule"
    if kinds[0] is not RequestAttemptKind.INITIAL:
        return [], "attempt_schedule_must_begin_with_initial"
    return kinds, None


def _rejected_decision(reason: str):
    return BarangayScopeDecision(frozenset(), reason)


def _summary(
    *,
    status: str,
    authorization_error: str | None,
    scope_error: str | None,
    decisions: list[dict[str, Any]],
    attempts: list[dict[str, Any]],
    budget: Any,
) -> dict[str, Any]:
    permitted = [
        decision for decision in decisions
        if decision["permitted_operations"]
    ]
    rejected = [
        decision for decision in decisions
        if decision["rejection_reason"] is not None
    ]
    if budget is None:
        budget_summary = {
            "authorized_budget": 0,
            "attempts_reserved": 0,
            "remaining": 0,
        }
    else:
        budget_summary = {
            "authorized_budget": budget.authorized_budget,
            "attempts_reserved": budget.attempts_reserved,
            "remaining": budget.remaining,
        }
    return {
        "status": status,
        "authorization_error": authorization_error,
        "scope_error": scope_error,
        "permitted_operations": permitted,
        "rejected_operations": rejected,
        "attempts": attempts,
        "budget": budget_summary,
    }
