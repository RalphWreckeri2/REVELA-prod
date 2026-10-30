#!/usr/bin/env python3
"""Generate shared projected barangay centroids and interior label points."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

from pyproj import Transformer
from shapely.geometry import Point, shape
from shapely.ops import transform, unary_union


ROOT = Path(__file__).resolve().parents[1]
BACKEND_UTILS = ROOT / "revela_backend" / "api" / "utils"
CANONICAL_GEOJSON = BACKEND_UTILS / "mataasnakahoy_mpdo_compatible.json"
SHARED_MAPPING = BACKEND_UTILS / "adm4_en_barangay_ids.json"
LEGACY_POINTS = ROOT / "scripts" / "legacy_barangay_centroids.json"
OUTPUT = BACKEND_UTILS / "barangay_points.json"
SOURCE_CRS = "EPSG:4326"
PROJECTED_CRS = "EPSG:32651"
EDGE_WARNING_METERS = 100


def _read_inputs():
    geojson_bytes = CANONICAL_GEOJSON.read_bytes()
    geojson = json.loads(geojson_bytes)
    mapping = json.loads(SHARED_MAPPING.read_text(encoding="utf-8"))
    legacy_points = json.loads(LEGACY_POINTS.read_text(encoding="utf-8"))
    features = geojson.get("features")
    if not isinstance(features, list) or not features:
        raise ValueError(f"{CANONICAL_GEOJSON} has no features.")
    if len(features) != 16 or len(mapping) != 16:
        raise ValueError("Expected exactly 16 GeoJSON features and ADM4 mappings.")
    return geojson_bytes, features, mapping, legacy_points


def _projected_feature(feature, forward):
    name = feature.get("properties", {}).get("ADM4_EN")
    if not name:
        raise ValueError("GeoJSON feature is missing properties.ADM4_EN.")
    geometry = shape(feature.get("geometry"))
    if geometry.geom_type not in {"Polygon", "MultiPolygon"} or geometry.is_empty:
        raise ValueError(f"{name}: expected a non-empty Polygon or MultiPolygon.")
    if not geometry.is_valid:
        raise ValueError(f"{name}: GeoJSON polygon is invalid.")
    projected = transform(forward, geometry)
    if projected.is_empty or projected.area <= 0:
        raise ValueError(f"{name}: projected polygon has no area.")
    return name, projected


def generate_points():
    geojson_bytes, features, mapping, legacy_points = _read_inputs()
    forward = Transformer.from_crs(
        SOURCE_CRS, PROJECTED_CRS, always_xy=True,
    ).transform
    reverse = Transformer.from_crs(
        PROJECTED_CRS, SOURCE_CRS, always_xy=True,
    ).transform

    projected_features = {}
    seen_names = set()
    for feature in features:
        name, polygon = _projected_feature(feature, forward)
        if name in seen_names:
            raise ValueError(f"Duplicate ADM4_EN feature name: {name}")
        if name not in mapping:
            raise ValueError(f"No barangay ID mapping for ADM4_EN={name!r}.")
        seen_names.add(name)
        projected_features[name] = polygon

    missing_features = sorted(set(mapping) - seen_names)
    if missing_features:
        raise ValueError(
            "Mapped feature(s) are missing from GeoJSON: "
            + ", ".join(missing_features)
        )
    ids = list(mapping.values())
    if len(set(ids)) != 16 or set(ids) != set(range(1, 17)):
        raise ValueError("ADM4 mapping must contain each barangay ID 1 through 16 once.")

    records = []
    polygons = []
    for name, barangay_id in sorted(mapping.items(), key=lambda item: item[1]):
        polygon = projected_features[name]
        polygons.append(polygon)
        centroid = polygon.centroid
        representative = polygon.representative_point()
        if not polygon.contains(representative):
            raise ValueError(
                f"{name} (barangayID {barangay_id}): representative point "
                "is outside the polygon."
            )
        centroid_wgs84 = transform(reverse, centroid)
        representative_wgs84 = transform(reverse, representative)
        representative_clearance_m = representative.distance(polygon.boundary)
        records.append({
            "barangayID": barangay_id,
            "name": name,
            "centroid": {
                "lat": centroid_wgs84.y,
                "lng": centroid_wgs84.x,
            },
            "centroidInsidePolygon": polygon.covers(centroid),
            "representativePoint": {
                "lat": representative_wgs84.y,
                "lng": representative_wgs84.x,
            },
            "representativeClearanceM": representative_clearance_m,
            "polygonAreaM2": polygon.area,
        })

    municipality_centroid = unary_union(polygons).centroid
    municipality_centroid_wgs84 = transform(reverse, municipality_centroid)
    payload = {
        "sourceGeoJsonSha256": hashlib.sha256(geojson_bytes).hexdigest(),
        "generatedAtUtc": datetime.now(timezone.utc).isoformat(
            timespec="seconds",
        ).replace("+00:00", "Z"),
        "sourceCrs": SOURCE_CRS,
        "projectedCrs": PROJECTED_CRS,
        "municipalityCentroid": {
            "lat": municipality_centroid_wgs84.y,
            "lng": municipality_centroid_wgs84.x,
        },
        "barangays": records,
    }
    return payload, projected_features, legacy_points, forward


def _edge_label(distance_meters):
    marker = "NEAR EDGE (<100m)" if distance_meters < EDGE_WARNING_METERS else ""
    return f"{distance_meters:8.1f}m {marker}".rstrip()


def print_dry_run(payload, projected_features, legacy_points, forward):
    print(f"GeoJSON SHA-256: {payload['sourceGeoJsonSha256']}")
    print(
        "Distances are projected metres. Area centroid is the polygon's "
        "area-weighted centroid; label/approximate point is representative_point()."
    )
    print(
        "ID  Barangay             old lat,lng          old edge/inside"
        "              area centroid (lat,lng) / edge / inside"
        "       representative point (lat,lng) / edge / inside"
        "       old-to-area-centroid / old-to-representative"
    )
    for record in payload["barangays"]:
        barangay_id = record["barangayID"]
        polygon = projected_features[record["name"]]
        old = legacy_points.get(str(barangay_id))
        if not old:
            raise ValueError(
                f"Legacy point missing for barangayID {barangay_id}."
            )
        old_projected = transform(
            forward, Point(old["lng"], old["lat"]),
        )
        centroid = transform(
            forward,
            Point(record["centroid"]["lng"], record["centroid"]["lat"]),
        )
        representative = transform(
            forward,
            Point(
                record["representativePoint"]["lng"],
                record["representativePoint"]["lat"],
            ),
        )
        old_edge = old_projected.distance(polygon.boundary)
        centroid_edge = centroid.distance(polygon.boundary)
        representative_edge = representative.distance(polygon.boundary)
        old_inside = polygon.covers(old_projected)
        centroid_inside = polygon.covers(centroid)
        representative_inside = polygon.contains(representative)
        if not representative_inside:
            raise ValueError(
                f"{record['name']}: generated representative point is outside."
            )
        old_to_new = old_projected.distance(representative)
        old_to_centroid = old_projected.distance(centroid)
        print(
            f"{barangay_id:2}  {record['name']:<20} "
            f"{old['lat']:.6f},{old['lng']:.6f}  "
            f"{_edge_label(old_edge)} / {'yes' if old_inside else 'no':<3}  "
            f"{record['centroid']['lat']:.6f},{record['centroid']['lng']:.6f}  "
            f"{_edge_label(centroid_edge)} / {'yes' if centroid_inside else 'no':<3}  "
            f"{record['representativePoint']['lat']:.6f},"
            f"{record['representativePoint']['lng']:.6f}  "
            f"{_edge_label(representative_edge)} / yes   "
            f"{old_to_centroid:.1f}m / {old_to_new:.1f}m"
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print point comparisons and validations without writing JSON.",
    )
    args = parser.parse_args()
    payload, polygons, legacy_points, forward = generate_points()
    if args.dry_run:
        print_dry_run(payload, polygons, legacy_points, forward)
        return
    OUTPUT.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {len(payload['barangays'])} points to {OUTPUT}")
    print(f"GeoJSON SHA-256: {payload['sourceGeoJsonSha256']}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"Barangay point generation failed: {exc}", file=sys.stderr)
        raise
