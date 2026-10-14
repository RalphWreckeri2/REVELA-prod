"""Pure registry and flag scope decisions for a future barangay pilot."""

from dataclasses import dataclass
from enum import Enum
from typing import Any

from api.utils.nearby_barangay_scope import (
    BarangayScope,
    validate_barangay_scope,
)


class ScopeOperation(str, Enum):
    REGISTRY_MATCH = "registry_match"
    FLAG_INSERT = "flag_insert"
    FLAG_UPDATE = "flag_update"
    FLAG_DELETE = "flag_delete"


@dataclass(frozen=True)
class BarangayScopeDecision:
    allowed_operations: frozenset[ScopeOperation]
    rejection_reason: str | None = None

    @property
    def permitted(self) -> bool:
        return bool(self.allowed_operations)


def decide_barangay_scope_operations(
    selected_barangay_id: Any,
    validated_scope: Any,
    candidate_place_id: Any,
    latitude: Any,
    longitude: Any,
    registry_candidate_barangay_id: Any = None,
    existing_flag_barangay_id: Any = None,
    *,
    registry_candidate_present: bool = False,
    existing_flag_present: bool = False,
) -> BarangayScopeDecision:
    """Authorize only operations whose records and coordinates share the scope.

    Presence flags distinguish "no applicable row" from an applicable registry
    or flag row whose barangay assignment is missing. Place ID is validated as
    an identifier but never suffices to authorize an operation.
    """
    if not _positive_integer(selected_barangay_id):
        return _reject("invalid_selected_barangay_id")
    if not isinstance(validated_scope, BarangayScope):
        return _reject("missing_or_ambiguous_authoritative_scope")
    if not _positive_integer(validated_scope.barangay_id):
        return _reject("missing_or_ambiguous_authoritative_scope")
    try:
        scope = validate_barangay_scope(
            selected_barangay_id,
            validated_scope.polygon,
        )
    except Exception:
        return _reject("missing_or_ambiguous_authoritative_scope")
    if scope.barangay_id != validated_scope.barangay_id:
        return _reject("scope_barangay_mismatch")

    if not isinstance(candidate_place_id, str) or not candidate_place_id.strip():
        return _reject("missing_or_invalid_place_id")
    if not scope.contains_place_coordinate(latitude, longitude):
        return _reject("place_outside_barangay_scope")

    if not isinstance(registry_candidate_present, bool):
        return _reject("ambiguous_registry_candidate_presence")
    if not isinstance(existing_flag_present, bool):
        return _reject("ambiguous_existing_flag_presence")

    if registry_candidate_present:
        if not _positive_integer(registry_candidate_barangay_id):
            return _reject("missing_or_invalid_registry_barangay_assignment")
        if registry_candidate_barangay_id != selected_barangay_id:
            return _reject("registry_candidate_outside_barangay_scope")
    elif registry_candidate_barangay_id is not None:
        return _reject("ambiguous_registry_candidate_assignment")

    if existing_flag_present:
        if not _positive_integer(existing_flag_barangay_id):
            return _reject("missing_or_invalid_flag_barangay_assignment")
        if existing_flag_barangay_id != selected_barangay_id:
            return _reject("existing_flag_outside_barangay_scope")
    elif existing_flag_barangay_id is not None:
        return _reject("ambiguous_existing_flag_assignment")

    operations = set()
    if registry_candidate_present:
        operations.add(ScopeOperation.REGISTRY_MATCH)
    if existing_flag_present:
        operations.update((
            ScopeOperation.FLAG_UPDATE,
            ScopeOperation.FLAG_DELETE,
        ))
    else:
        operations.add(ScopeOperation.FLAG_INSERT)

    return BarangayScopeDecision(frozenset(operations))


def _positive_integer(value: Any) -> bool:
    return (
        isinstance(value, int)
        and not isinstance(value, bool)
        and value > 0
    )


def _reject(reason: str) -> BarangayScopeDecision:
    return BarangayScopeDecision(frozenset(), reason)
