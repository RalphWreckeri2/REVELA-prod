"""Pure polygon-based scope validation for a future barangay pilot."""

from dataclasses import dataclass
import math
from typing import Any

from shapely.geometry import MultiPolygon, Polygon, Point, shape
from shapely.geometry.base import BaseGeometry


@dataclass(frozen=True)
class BarangayScope:
    """A validated barangay identifier and authoritative polygon boundary."""

    barangay_id: int
    polygon: Polygon | MultiPolygon

    def contains_coordinate(self, latitude: Any, longitude: Any) -> bool:
        """Return whether a strict WGS84 coordinate is covered by this scope."""
        coordinate = _coordinate(latitude, longitude)
        if coordinate is None:
            return False
        lat, lng = coordinate
        try:
            return self.polygon.covers(Point(lng, lat))
        except Exception:
            return False

    def contains_scan_point(self, latitude: Any, longitude: Any) -> bool:
        """Validate a proposed scan point against the selected barangay."""
        return self.contains_coordinate(latitude, longitude)

    def contains_place_coordinate(
        self, latitude: Any, longitude: Any
    ) -> bool:
        """Validate a returned Place coordinate against the selected barangay."""
        return self.contains_coordinate(latitude, longitude)


def validate_barangay_scope(
    selected_barangay_id: Any,
    authoritative_geometry: Any,
) -> BarangayScope:
    """Build a scope only from one valid Polygon or MultiPolygon geometry.

    Accepts a Shapely polygon or a GeoJSON geometry mapping. Feature collections,
    geometry collections, and other potentially ambiguous inputs are rejected.
    """
    if (
        isinstance(selected_barangay_id, bool)
        or not isinstance(selected_barangay_id, int)
        or selected_barangay_id <= 0
    ):
        raise ValueError("A positive integer barangay ID is required.")

    if authoritative_geometry is None:
        raise ValueError("Authoritative barangay geometry is required.")

    try:
        polygon = (
            authoritative_geometry
            if isinstance(authoritative_geometry, BaseGeometry)
            else shape(authoritative_geometry)
        )
    except Exception as exc:
        raise ValueError("Authoritative barangay geometry is malformed.") from exc

    if not isinstance(polygon, (Polygon, MultiPolygon)):
        raise ValueError(
            "Barangay geometry must be exactly one Polygon or MultiPolygon."
        )
    if polygon.is_empty or not polygon.is_valid or polygon.area <= 0:
        raise ValueError("Authoritative barangay geometry is empty or invalid.")

    min_x, min_y, max_x, max_y = polygon.bounds
    if (
        not all(math.isfinite(value) for value in polygon.bounds)
        or min_x < -180
        or max_x > 180
        or min_y < -90
        or max_y > 90
    ):
        raise ValueError(
            "Authoritative barangay geometry is outside valid WGS84 bounds."
        )

    return BarangayScope(
        barangay_id=selected_barangay_id,
        polygon=polygon,
    )


def _coordinate(latitude: Any, longitude: Any) -> tuple[float, float] | None:
    if (
        isinstance(latitude, bool)
        or isinstance(longitude, bool)
        or not isinstance(latitude, (int, float))
        or not isinstance(longitude, (int, float))
    ):
        return None
    try:
        lat, lng = float(latitude), float(longitude)
    except (OverflowError, TypeError, ValueError):
        return None
    if (
        not math.isfinite(lat)
        or not math.isfinite(lng)
        or not -90 <= lat <= 90
        or not -180 <= lng <= 180
    ):
        return None
    return lat, lng
