"""Shared DBSCAN population, parameter, and aggregation helpers."""

import json
import logging
import math
import threading
import time
from copy import deepcopy
from datetime import date, datetime, timedelta
from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
from shapely.geometry import Point, shape
from sklearn.cluster import DBSCAN

from api.utils.barangay_mapping import map_adm4_barangay_ids


HOTSPOT_EPS_SETTING = "hotspots.eps_m"
HOTSPOT_MIN_SAMPLES_SETTING = "hotspots.min_samples"
HOTSPOT_DEFAULT_EPS_M = 50
HOTSPOT_DEFAULT_MIN_SAMPLES = 3
HOTSPOT_EARTH_RADIUS_M = 6_371_008.8
HOTSPOT_CACHE_TTL_SECONDS = 60

_hotspot_cache = {}
_hotspot_cache_lock = threading.Lock()
_logger = logging.getLogger(__name__)

_BARANGAY_GEOJSON_PATH = (
    Path(__file__).resolve().parents[1] / "utils" / "mataasnakahoy.json"
)


def _setting_value(raw_value):
    if isinstance(raw_value, str):
        try:
            return json.loads(raw_value)
        except (TypeError, ValueError):
            return raw_value
    return raw_value


def resolve_hotspot_parameters(settings):
    """Validate persisted settings and return safe values plus fallback notes."""
    settings = settings or {}
    fallbacks = {}

    raw_eps = _setting_value(settings.get(HOTSPOT_EPS_SETTING, HOTSPOT_DEFAULT_EPS_M))
    try:
        eps_m = float(raw_eps)
        if isinstance(raw_eps, bool) or not math.isfinite(eps_m) or not 10 <= eps_m <= 200:
            raise ValueError
    except (TypeError, ValueError, OverflowError):
        eps_m = HOTSPOT_DEFAULT_EPS_M
        fallbacks["eps_m"] = "Invalid or out of range; using default 50 m."

    raw_min_samples = _setting_value(
        settings.get(HOTSPOT_MIN_SAMPLES_SETTING, HOTSPOT_DEFAULT_MIN_SAMPLES)
    )
    try:
        min_samples = int(raw_min_samples)
        if (
            isinstance(raw_min_samples, bool)
            or float(raw_min_samples) != min_samples
            or not 2 <= min_samples <= 10
        ):
            raise ValueError
    except (TypeError, ValueError, OverflowError):
        min_samples = HOTSPOT_DEFAULT_MIN_SAMPLES
        fallbacks["min_samples"] = "Invalid or out of range; using default 3."

    return {
        "eps_m": eps_m,
        "min_samples": min_samples,
        "metric": "haversine",
    }, fallbacks


def read_hotspot_settings(cursor):
    cursor.execute(
        "SELECT settingKey, settingValue FROM revela_app_settings "
        "WHERE settingKey IN (%s, %s)",
        (HOTSPOT_EPS_SETTING, HOTSPOT_MIN_SAMPLES_SETTING),
    )
    return {
        row["settingKey"]: row["settingValue"]
        for row in (cursor.fetchall() or [])
    }


def hotspot_date_window(date_preset, today=None):
    """Resolve the Overview date preset using Mataasnakahoy local calendar days."""
    if date_preset not in {"all", "year", "30days", "7days"}:
        raise ValueError("date_preset must be all, year, 30days, or 7days.")
    if date_preset == "all":
        return None, None

    local_today = today or datetime.now(ZoneInfo("Asia/Manila")).date()
    if date_preset == "year":
        start = date(local_today.year, 1, 1)
    elif date_preset == "30days":
        start = local_today - timedelta(days=29)
    else:
        start = local_today - timedelta(days=6)
    return start, local_today


def build_hotspot_population_sql(
    effective_flag_sql,
    registry_link_sql,
    start,
    end,
    *,
    extra_where_sql="",
    extra_params=(),
):
    """Build exclusive disposition rows for all effective-Red pins in scope."""
    date_sql = ""
    params = []
    if start is not None and end is not None:
        date_sql = " AND g.detectedDate >= %s AND g.detectedDate < DATE_ADD(%s, INTERVAL 1 DAY)"
        params.extend((start, end))
    params.extend(extra_params)
    extra_where = f" {extra_where_sql}" if extra_where_sql else ""

    sql = f"""
        SELECT g.logID, g.detectedName, g.detectedDate,
               ({effective_flag_sql}) AS flagColor,
               g.latitude, g.longitude, g.barangayID,
               COALESCE(b.barangayName, 'Unknown Area') AS barangayName,
               g.source, g.businessID,
               CASE
                 WHEN COALESCE(g.source, 'unknown') <> 'detection'
                   THEN 'not_detection'
                 WHEN {registry_link_sql}
                   THEN 'registry_linked'
                 WHEN g.businessID IS NOT NULL
                   THEN 'business_id_present'
                 WHEN g.latitude IS NULL OR g.longitude IS NULL
                   THEN 'missing_coordinates'
                 ELSE 'eligible'
               END AS disposition
        FROM geospatial_logs g
        LEFT JOIN barangays b ON b.barangayID = g.barangayID
        WHERE ({effective_flag_sql}) = 'Red' {date_sql}{extra_where}
        ORDER BY g.logID
    """
    return sql, params


@lru_cache(maxsize=1)
def _read_barangay_geojson():
    with _BARANGAY_GEOJSON_PATH.open("r", encoding="utf-8") as geojson_file:
        return json.load(geojson_file)


def load_barangay_polygons(barangay_rows):
    """Return canonical GeoJSON polygons paired with database IDs and labels."""
    features = _read_barangay_geojson().get("features", [])
    feature_names = [
        feature.get("properties", {}).get("ADM4_EN")
        for feature in features
        if feature.get("properties", {}).get("ADM4_EN") and feature.get("geometry")
    ]
    ids_by_geojson_name, names_by_id = map_adm4_barangay_ids(
        feature_names,
        barangay_rows,
    )
    polygons = []
    for feature in features:
        name = feature.get("properties", {}).get("ADM4_EN")
        if not name or not feature.get("geometry"):
            continue
        if name not in ids_by_geojson_name:
            raise ValueError(f"Barangay polygon feature {name!r} has no ADM4_EN mapping.")
        barangay_id = ids_by_geojson_name[name]
        polygons.append({
            "barangay_id": barangay_id,
            "barangay_name": names_by_id[barangay_id],
            "geometry": shape(feature["geometry"]),
        })
    return polygons


def attribute_hotspot_point(latitude, longitude, polygons):
    """Return its barangay, None if outside every polygon, or raise if ambiguous."""
    point = Point(float(longitude), float(latitude))
    matches = [
        polygon for polygon in polygons
        if polygon["geometry"].contains(point)
    ]
    if not matches:
        return None
    if len(matches) > 1:
        barangay_ids = sorted(polygon["barangay_id"] for polygon in matches)
        raise ValueError(
            f"Hotspot point ({latitude}, {longitude}) matches multiple "
            f"barangay polygons: {barangay_ids}."
        )
    return matches[0]


def _distance_m(first, second):
    lat1, lng1 = math.radians(first[0]), math.radians(first[1])
    lat2, lng2 = math.radians(second[0]), math.radians(second[1])
    delta_lat = lat2 - lat1
    delta_lng = lng2 - lng1
    haversine = (
        math.sin(delta_lat / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin(delta_lng / 2) ** 2
    )
    return 2 * HOTSPOT_EARTH_RADIUS_M * math.asin(math.sqrt(haversine))


def cluster_hotspot_rows(rows, parameters, polygons):
    """Cluster eligible rows and summarize point-in-polygon memberships."""
    eligible = [
        row for row in rows
        if row.get("disposition") == "eligible"
        and row.get("latitude") is not None
        and row.get("longitude") is not None
    ]
    if not eligible:
        return [], {
            "clustered_points": 0,
            "noise_points": 0,
            "uncertain_points": 0,
            "outside_boundary_count": 0,
        }

    attributions_by_row_id = {}
    outside_boundary_count = 0
    for row in eligible:
        attributed = attribute_hotspot_point(
            row["latitude"], row["longitude"], polygons
        )
        attributions_by_row_id[id(row)] = attributed
        if attributed is None:
            outside_boundary_count += 1
            _logger.warning(
                "Hotspot detection logID=%s is outside the municipal boundary.",
                row.get("logID"),
            )

    coordinates = np.radians(np.array([
        [float(row["latitude"]), float(row["longitude"])]
        for row in eligible
    ]))
    epsilon_radians = parameters["eps_m"] / HOTSPOT_EARTH_RADIUS_M
    labels = DBSCAN(
        eps=epsilon_radians,
        min_samples=parameters["min_samples"],
        algorithm="ball_tree",
        metric=parameters["metric"],
    ).fit_predict(coordinates)

    groups = {}
    noise_points = 0
    for index, label in enumerate(labels):
        if int(label) == -1:
            noise_points += 1
            continue
        groups.setdefault(int(label), []).append(eligible[index])

    clusters = []
    uncertain_points = 0
    for cluster_id, members in sorted(
        groups.items(), key=lambda item: (-len(item[1]), item[0])
    ):
        centroid = (
            sum(float(row["latitude"]) for row in members) / len(members),
            sum(float(row["longitude"]) for row in members) / len(members),
        )
        radius_m = max(
            _distance_m(
                centroid,
                (float(row["latitude"]), float(row["longitude"])),
            )
            for row in members
        )
        barangay_counts = {}
        cluster_uncertain = 0
        for row in members:
            attributed = attributions_by_row_id[id(row)]
            if attributed is None:
                cluster_uncertain += 1
                continue
            key = attributed["barangay_id"]
            if key not in barangay_counts:
                barangay_counts[key] = {
                    "barangay_id": key,
                    "barangay_name": attributed["barangay_name"],
                    "count": 0,
                }
            barangay_counts[key]["count"] += 1

        uncertain_points += cluster_uncertain
        clusters.append({
            "cluster_id": cluster_id,
            "centroid": {"lat": centroid[0], "lng": centroid[1]},
            "radius_m": round(radius_m, 1),
            "size": len(members),
            "log_ids": [int(row["logID"]) for row in members],
            "per_barangay": sorted(
                barangay_counts.values(),
                key=lambda item: (item["barangay_name"] or "", item["barangay_id"]),
            ),
            "uncertain_count": cluster_uncertain,
        })

    return clusters, {
        "clustered_points": sum(len(members) for members in groups.values()),
        "noise_points": noise_points,
        "uncertain_points": uncertain_points,
        "outside_boundary_count": outside_boundary_count,
    }


def hotspot_cluster_memberships(rows, clusters):
    """Map eligible point IDs to DBSCAN labels, retaining -1 for noise."""
    memberships = {
        int(row["logID"]): -1
        for row in rows
        if row.get("disposition") == "eligible"
        and row.get("latitude") is not None
        and row.get("longitude") is not None
    }
    for cluster in clusters:
        for log_id in cluster["log_ids"]:
            memberships[log_id] = cluster["cluster_id"]
    primary_cluster_id = clusters[0]["cluster_id"] if clusters else -1
    return memberships, primary_cluster_id


def serialize_map_hotspot_clusters(clusters, parameters):
    """Preserve the map endpoint's legacy shape using canonical cluster data."""
    return [
        {
            "clusterID": cluster["cluster_id"],
            "centroidLat": round(cluster["centroid"]["lat"], 7),
            "centroidLng": round(cluster["centroid"]["lng"], 7),
            "size": cluster["size"],
            "radius_m": cluster["radius_m"],
            "logIDs": cluster["log_ids"],
            "eps_m": parameters["eps_m"],
            "min_samples": parameters["min_samples"],
        }
        for cluster in clusters
    ]


def count_hotspot_dispositions(rows):
    counts = {
        "considered_red_pins": len(rows),
        "eligible_points": 0,
        "excluded": {
            "not_detection": 0,
            "registry_linked": 0,
            "business_id_present": 0,
            "missing_coordinates": 0,
        },
    }
    for row in rows:
        disposition = row.get("disposition")
        if disposition == "eligible":
            counts["eligible_points"] += 1
        elif disposition in counts["excluded"]:
            counts["excluded"][disposition] += 1
    return counts


def get_cached_hotspots(key):
    now = time.monotonic()
    with _hotspot_cache_lock:
        entry = _hotspot_cache.get(key)
        if entry and now - entry["created_at"] < HOTSPOT_CACHE_TTL_SECONDS:
            return deepcopy(entry["data"])
        if entry:
            del _hotspot_cache[key]
    return None


def cache_hotspots(key, data):
    with _hotspot_cache_lock:
        _hotspot_cache[key] = {
            "created_at": time.monotonic(),
            "data": deepcopy(data),
        }


def invalidate_hotspots_cache():
    with _hotspot_cache_lock:
        _hotspot_cache.clear()
