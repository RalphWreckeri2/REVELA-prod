"""Temporary in-memory harness for offline Nearby Search (New) simulations."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Any

from api.utils.nearby_barangay_pilot import NearbyBarangayPilotConfig
from api.utils.nearby_barangay_policy import (
    decide_barangay_scope_operations,
)
from api.utils.nearby_barangay_scope import (
    BarangayScope,
    validate_barangay_scope,
)
from api.utils.nearby_barangay_simulation import (
    simulate_offline_barangay_pilot,
)


GEOJSON_PATH = (
    Path(__file__).resolve().parents[1]
    / "api"
    / "utils"
    / "mataasnakahoy.json"
)


class OfflineHarnessError(ValueError):
    """Raised when a test fixture cannot be mapped safely to pilot scope."""


@dataclass(frozen=True)
class CannedHttpResponse:
    status_code: int
    body: Mapping[str, Any]


class CannedNearbyHttp:
    """In-memory HTTP stand-in; contains no network client or URL handling."""

    def __init__(
        self,
        responses_by_request: Mapping[str, Sequence[CannedHttpResponse]],
    ):
        if not isinstance(responses_by_request, Mapping):
            raise ValueError("Canned HTTP responses must be a mapping.")
        self._responses = {}
        for request_id, responses in responses_by_request.items():
            if (
                not isinstance(request_id, str)
                or not request_id.strip()
                or not isinstance(responses, Sequence)
                or isinstance(responses, (str, bytes))
                or not responses
                or any(not isinstance(item, CannedHttpResponse)
                       for item in responses)
                or any(
                    isinstance(item.status_code, bool)
                    or not isinstance(item.status_code, int)
                    or not 100 <= item.status_code <= 599
                    or not isinstance(item.body, Mapping)
                    for item in responses
                )
            ):
                raise ValueError("Malformed canned HTTP response fixture.")
            self._responses[request_id] = tuple(responses)
        self._attempts: dict[str, int] = {}
        self.calls: list[dict[str, Any]] = []

    @property
    def request_ids(self) -> frozenset[str]:
        return frozenset(self._responses)

    def request(self, request_id: str, attempt_kind: str) -> CannedHttpResponse:
        """Return the next scripted response without performing network I/O."""
        responses = self._responses.get(request_id)
        if responses is None:
            raise OfflineHarnessError("No canned response for request.")
        index = self._attempts.get(request_id, 0)
        if index >= len(responses):
            raise OfflineHarnessError("Canned response sequence exhausted.")
        self._attempts[request_id] = index + 1
        self.calls.append({
            "request_id": request_id,
            "attempt_kind": attempt_kind,
            "response_index": index,
        })
        return responses[index]


def load_authoritative_scope(
    selected_barangay_id: Any,
    barangay_catalog: Any,
    *,
    geojson_path: Path = GEOJSON_PATH,
) -> BarangayScope:
    """Resolve one in-memory numeric barangay row to exactly one GeoJSON feature."""
    if (
        isinstance(selected_barangay_id, bool)
        or not isinstance(selected_barangay_id, int)
        or selected_barangay_id <= 0
    ):
        raise OfflineHarnessError("A positive integer barangay ID is required.")
    if not _sequence_of_mappings(barangay_catalog):
        raise OfflineHarnessError("Barangay catalog must be a record sequence.")

    matching_rows = [
        row for row in barangay_catalog
        if (
            isinstance(row.get("barangay_id"), int)
            and not isinstance(row.get("barangay_id"), bool)
            and row.get("barangay_id") == selected_barangay_id
        )
    ]
    if len(matching_rows) != 1:
        raise OfflineHarnessError(
            "Selected barangay ID must map to exactly one catalog row."
        )
    barangay_name = matching_rows[0].get("barangay_name")
    if not isinstance(barangay_name, str) or not barangay_name.strip():
        raise OfflineHarnessError("Selected barangay name is missing.")

    try:
        collection = json.loads(Path(geojson_path).read_text(encoding="utf-8"))
    except (OSError, TypeError, UnicodeError, json.JSONDecodeError) as exc:
        raise OfflineHarnessError(
            "Authoritative barangay GeoJSON could not be loaded."
        ) from exc
    if (
        not isinstance(collection, Mapping)
        or collection.get("type") != "FeatureCollection"
        or not isinstance(collection.get("features"), list)
    ):
        raise OfflineHarnessError("Authoritative GeoJSON is malformed.")

    normalized_name = _normalize_name(barangay_name)
    matches = []
    for feature in collection["features"]:
        if not isinstance(feature, Mapping):
            continue
        properties = feature.get("properties")
        geometry = feature.get("geometry")
        if not isinstance(properties, Mapping):
            continue
        if (
            properties.get("ADM3_EN") == "Mataasnakahoy"
            and _normalize_name(properties.get("ADM4_EN")) == normalized_name
        ):
            matches.append((properties, geometry))
    if len(matches) != 1:
        raise OfflineHarnessError(
            "Selected barangay name must map to exactly one GeoJSON feature."
        )

    properties, geometry = matches[0]
    pcode = properties.get("ADM4_PCODE")
    if (
        not isinstance(pcode, str)
        or not pcode.strip()
        or sum(
            1 for feature in collection["features"]
            if isinstance(feature, Mapping)
            and isinstance(feature.get("properties"), Mapping)
            and feature["properties"].get("ADM4_PCODE") == pcode
        ) != 1
    ):
        raise OfflineHarnessError(
            "Selected authoritative barangay feature has an ambiguous code."
        )

    try:
        return validate_barangay_scope(selected_barangay_id, geometry)
    except ValueError as exc:
        raise OfflineHarnessError(
            "Selected authoritative barangay geometry is invalid."
        ) from exc


def run_offline_nearby_new_harness(
    *,
    config: NearbyBarangayPilotConfig,
    persisted_authorized: bool,
    live_confirmation: bool,
    selected_barangay_id: Any,
    barangay_catalog: Any,
    requested_budget: Any,
    scan_requests: Any,
    canned_http: CannedNearbyHttp,
    registry_records: Any = (),
    existing_flags: Any = (),
) -> dict[str, Any]:
    """Run only canned Nearby Search responses through the existing helpers."""
    if not isinstance(canned_http, CannedNearbyHttp):
        return _denied("only CannedNearbyHttp is permitted")
    try:
        scope = load_authoritative_scope(
            selected_barangay_id,
            barangay_catalog,
        )
    except OfflineHarnessError as exc:
        return _denied(str(exc))
    if not _sequence_of_mappings(scan_requests):
        return _denied("scan requests must be a record sequence")
    if not _sequence_of_mappings(registry_records) or not _sequence_of_mappings(
        existing_flags
    ):
        return _denied("registry and flag fixtures must be record sequences")

    request_records = list(scan_requests)
    if not request_records:
        return _denied("at least one in-scope scan request is required")
    for request in request_records:
        if (
            not isinstance(request.get("request_id"), str)
            or not request["request_id"].strip()
            or not scope.contains_scan_point(
                request.get("latitude"),
                request.get("longitude"),
            )
        ):
            return _denied("missing, malformed, or out-of-scope scan request")
    if len({request["request_id"] for request in request_records}) != len(
        request_records
    ):
        return _denied("scan request IDs must be unique")
    if canned_http.request_ids != frozenset(
        request["request_id"] for request in request_records
    ):
        return _denied("canned HTTP fixtures must match scan request IDs")
    response_decisions: list[dict[str, Any]] = []
    seen_places: set[str] = set()

    def mock_http_attempt(request, kind, _reservation):
        response = canned_http.request(
            request["place_id"],
            kind.value,
        )
        if response.status_code < 200 or response.status_code >= 300:
            return False
        if not isinstance(response.body, Mapping):
            response_decisions.append({
                "request_id": request["place_id"],
                "rejection_reason": "malformed_nearby_response",
            })
            return False
        places = response.body.get("places")
        if not isinstance(places, list):
            response_decisions.append({
                "request_id": request["place_id"],
                "rejection_reason": "malformed_nearby_response",
            })
            return False
        for place in places:
            _record_place_decision(
                place=place,
                request_id=request["place_id"],
                scope=scope,
                registry_records=registry_records,
                existing_flags=existing_flags,
                seen_places=seen_places,
                decisions=response_decisions,
            )
        return True

    simulation = simulate_offline_barangay_pilot(
        config=config,
        persisted_authorized=persisted_authorized,
        live_confirmation=live_confirmation,
        barangay_id=selected_barangay_id,
        authoritative_polygon=scope.polygon,
        requested_budget=requested_budget,
        candidate_places=[
            {
                "place_id": request["request_id"],
                "latitude": request["latitude"],
                "longitude": request["longitude"],
                "attempt_kinds": request.get("attempt_kinds", ["initial"]),
            }
            for request in request_records
        ],
        registry_records=[],
        existing_flags=[],
        attempt_callback=mock_http_attempt,
    )
    # The simulator's decisions concern synthetic scan requests, not returned
    # businesses. Expose only returned-Place decisions to avoid implying writes.
    return {
        "status": simulation["status"],
        "authorization_error": simulation["authorization_error"],
        "scope_error": simulation["scope_error"],
        "places": response_decisions,
        "attempts": simulation["attempts"],
        "budget": simulation["budget"],
        "mock_http_call_count": len(canned_http.calls),
        "database_writes": 0,
    }


def _record_place_decision(
    *,
    place: Any,
    request_id: str,
    scope: BarangayScope,
    registry_records: Sequence[Mapping[str, Any]],
    existing_flags: Sequence[Mapping[str, Any]],
    seen_places: set[str],
    decisions: list[dict[str, Any]],
) -> None:
    if not isinstance(place, Mapping):
        decisions.append({
            "request_id": request_id,
            "rejection_reason": "malformed_place",
        })
        return
    place_id = place.get("id")
    location = place.get("location")
    if (
        not isinstance(place_id, str)
        or not place_id.strip()
        or not isinstance(location, Mapping)
    ):
        decisions.append({
            "request_id": request_id,
            "rejection_reason": "malformed_place",
        })
        return
    if place_id in seen_places:
        decisions.append({
            "request_id": request_id,
            "place_id": place_id,
            "rejection_reason": "duplicate_place_in_run",
        })
        return
    seen_places.add(place_id)

    matching_registry = [
        record for record in registry_records
        if record.get("place_id") == place_id
    ]
    matching_flags = [
        record for record in existing_flags
        if record.get("place_id") == place_id
    ]
    if len(matching_registry) > 1 or len(matching_flags) > 1:
        decisions.append({
            "request_id": request_id,
            "place_id": place_id,
            "rejection_reason": (
                "ambiguous_registry_candidates"
                if len(matching_registry) > 1
                else "ambiguous_existing_flags"
            ),
        })
        return
    registry = matching_registry[0] if matching_registry else None
    flag = matching_flags[0] if matching_flags else None
    decision = decide_barangay_scope_operations(
        selected_barangay_id=scope.barangay_id,
        validated_scope=scope,
        candidate_place_id=place_id,
        latitude=location.get("latitude"),
        longitude=location.get("longitude"),
        registry_candidate_barangay_id=(
            registry.get("barangay_id") if registry is not None else None
        ),
        existing_flag_barangay_id=(
            flag.get("barangay_id") if flag is not None else None
        ),
        registry_candidate_present=registry is not None,
        existing_flag_present=flag is not None,
    )
    decisions.append({
        "request_id": request_id,
        "place_id": place_id,
        "permitted_operations": sorted(
            operation.value for operation in decision.allowed_operations
        ),
        "rejection_reason": decision.rejection_reason,
    })


def _sequence_of_mappings(value: Any) -> bool:
    return (
        isinstance(value, Sequence)
        and not isinstance(value, (str, bytes))
        and all(isinstance(item, Mapping) for item in value)
    )


def _normalize_name(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return re.sub(r"[^a-z0-9]", "", value.casefold())


def _denied(reason: str) -> dict[str, Any]:
    return {
        "status": "denied",
        "authorization_error": reason,
        "scope_error": reason,
        "places": [],
        "attempts": [],
        "budget": {
            "authorized_budget": 0,
            "attempts_reserved": 0,
            "remaining": 0,
        },
        "mock_http_call_count": 0,
        "database_writes": 0,
    }
