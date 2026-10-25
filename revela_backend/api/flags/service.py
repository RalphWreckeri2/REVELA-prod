from api.models.detection_runs import (
    get_monthly_detection_count,
    create_detection_run,
    update_detection_run_status,
    get_detection_quota_info,
)
import difflib
import hashlib
import math
import numpy as np
from sklearn.cluster import DBSCAN
import os
import random
import time
import threading
import traceback
import requests as http
import json
from geopy.distance import geodesic
from app import mysql
from api.registry.service import _flag_source_sql, _has_enforcement_columns
from api.flags.compliance import (
    decorate_compliance, origin_source_sql, registry_link_sql, verified_green_at_sql,
)
from api.models.geospatial import (
    SOURCE_DETECTION,
    geospatial_source_column_exists,
    SOURCE_MANUAL,
    SOURCE_REGISTRY,
    SOURCE_REGISTRY_DETECTED,
    with_source,
)
from api.registry.colors import (
    _effective_flag_color_sql, _registry_column_sql, ladder_columns_available,
    registry_row_color_sql, status_to_color,
)
from api.registry.locks import (
    BLACK_LOCKED, BlackLockedError, assert_not_black_locked,
    record_enforcement_event,
    assert_business_deletable, BlackBusinessDeletionForbidden, is_black_locked,
)
from shapely import prepare
from shapely.affinity import scale
from shapely.geometry import mapping, shape, Point
from shapely.ops import unary_union
from api.utils.cancellation import is_cancelled, set_cancel
from api.notifications import hub
from api.utils.name_match import address_similarity, name_match, parse_name
from api.utils.places_quota import (
    MANILA_DATE_SQL,
    read_daily_usage,
    read_usage,
    reserve_usage_slot,
)
from api.utils.quota_config import API_QUOTA_CONFIG
from api.utils.places_rate_limit import (
    CLOUD_LEGACY_NEARBY_PER_MINUTE,
    LEGACY_NEARBY_LIMITER,
)
from api.utils import quota_settings, test_mode
from api.utils.barangay_scope import validate_barangay_scope

GOOGLE_MAPS_API_KEY = os.getenv("GOOGLE_MAPS_API_KEY")
VIRTUAL_REGISTRY_LOG_ID_OFFSET = 2147483648


def _registry_business_id_for_virtual_log_id(cursor, log_id):
    """Resolve a virtual map ID to its registry business ID."""
    numeric_id = -int(log_id)
    if numeric_id <= VIRTUAL_REGISTRY_LOG_ID_OFFSET:
        cursor.execute(
            "SELECT businessID FROM official_registry WHERE businessID = %s",
            (str(numeric_id),),
        )
        row = cursor.fetchone()
        if row:
            return row.get("businessID")
        return None

    registry_ordinal = numeric_id - VIRTUAL_REGISTRY_LOG_ID_OFFSET
    cursor.execute("""
        SELECT businessID
        FROM (
            SELECT businessID,
                   ROW_NUMBER() OVER (ORDER BY businessID) AS registryOrdinal
            FROM official_registry
        ) registry_rows
        WHERE registryOrdinal = %s
    """, (registry_ordinal,))
    row = cursor.fetchone()
    return row.get("businessID") if row else None

# ── Places API cost guard ─────────────────────────────────────────────────────
# Hard daily ceilings, stored in MySQL so they survive restarts and multiple workers.
# Tune via env vars on Railway without redeploying code.
#


PLACES_MONTHLY_CAP = API_QUOTA_CONFIG.legacy_nearby.monthly
PLACES_DAILY_CAP = API_QUOTA_CONFIG.legacy_nearby.daily
PLACES_KINDS = ("nearby",)
NEW_NEARBY_DAILY_CAP = API_QUOTA_CONFIG.nearby_new.daily
NEW_NEARBY_MONTHLY_CAP = API_QUOTA_CONFIG.nearby_new.monthly
NEW_NEARBY_URL = "https://places.googleapis.com/v1/places:searchNearby"
NEW_NEARBY_FIELD_MASK = (
    "places.id,places.displayName,places.location,"
    "places.primaryType,places.businessStatus,places.formattedAddress"
)
NEW_NEARBY_EXCLUDED_TYPES = (
    "school", "primary_school", "secondary_school",
    "university", "local_government_office", "city_hall", "courthouse",
    "fire_station", "police", "post_office", "library", "cemetery",
    "park", "transit_station", "bus_station", "subway_station",
    "train_station", "light_rail_station",
)
RUN_DETECTION_MAX_SECONDS = API_QUOTA_CONFIG.run_detection_max_seconds
RUN_DETECTION_MAX_REQUESTS = API_QUOTA_CONFIG.run_detection_max_requests


def _env_positive_float(name, default, minimum):
    """
    Parse a tunable float env var, falling back to the default when unusable.

    A grid step drives `while lat <= max_lat: lat += step`, so a zero or
    negative value would never terminate. Garbage input must not raise at
    import time either, because this module is imported during app startup.
    """
    try:
        return max(minimum, float(os.getenv(name, default)))
    except (TypeError, ValueError):
        print(
            f"[Run Detection] Ignoring invalid {name}; using {default}.")
        return default


RUN_DETECTION_NEARBY_API = os.getenv(
    "RUN_DETECTION_NEARBY_API", API_QUOTA_CONFIG.run_detection_nearby_api
).strip().lower()
_nearby_request_lock = threading.Lock()
_run_detection_lock = threading.Lock()
_nearby_last_request_at = 0.0
_places_run_state = threading.local()


class PlacesBudgetExceeded(Exception):
    def __init__(self, message, reason="skipped_quota"):
        super().__init__(message)
        self.reason = reason


_budget_tables_ready = False


def _ensure_budget_tables():
    """Create the guard tables once per server process (not on every call)."""
    global _budget_tables_ready
    if _budget_tables_ready:
        return
    cur = mysql.connection.cursor()
    try:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS places_api_usage (
                usageDate    DATE        NOT NULL,
                kind         VARCHAR(20) NOT NULL,
                requestCount INT         NOT NULL DEFAULT 0,
                PRIMARY KEY (usageDate, kind)
            ) ENGINE=InnoDB
        """)

        # Checkpoints for a multi-day scan. Stores ONLY our own grid coordinates + a timestamp.
        # No Google content (names, addresses, ratings, coordinates of places) is stored here.
        cur.execute("""
            CREATE TABLE IF NOT EXISTS scan_point_log (
                pointKey    VARCHAR(64) NOT NULL PRIMARY KEY,
                completedAt DATETIME    NOT NULL
            ) ENGINE=InnoDB
        """)
        mysql.connection.commit()
        _budget_tables_ready = True      # only set after everything succeeded
    finally:
        cur.close()


# First day of the current month. NOTE: no '%' characters on purpose. MySQLdb runs
# `query % args` whenever args are passed, so a literal '%Y-%m' in a query would raise
# "ValueError: unsupported format character".
_MONTH_KEY = (
    f"DATE_SUB({MANILA_DATE_SQL}, "
    f"INTERVAL DAYOFMONTH({MANILA_DATE_SQL}) - 1 DAY)"
)


def _reserve_places_call(kind):
    """Reserve a legacy Nearby Search call, preserving its existing ledger rows."""
    _ensure_budget_tables()
    # Resolved per call, not from the import-time constant, so an admin quota
    # override in the settings panel takes effect without a redeploy.
    monthly_cap = quota_settings.cap("quota.legacy_nearby.monthly")
    daily_cap = quota_settings.cap("quota.legacy_nearby.daily")
    try:
        allowed, reason = reserve_usage_slot(
            mysql.connection, "month", "day", monthly_cap, daily_cap,
        )
    except Exception as exc:
        print(
            f"[Run Detection] legacy_nearby reservation failed closed: {exc}")
        raise PlacesBudgetExceeded(
            "Legacy Nearby Search usage ledger is unavailable; no request was sent."
        ) from exc
    if not allowed:
        raise PlacesBudgetExceeded(
            f"Legacy Nearby Search {reason.replace('_', ' ')} "
            f"(daily {daily_cap}, monthly {monthly_cap}).",
            reason=reason,
        )


def _places_get(kind, url, **kwargs):
    """Every Google Places HTTP call in this module must go through here."""
    # Test Mode: replay a stored fixture if we have one. A replay costs nothing
    # and is deliberately NOT reserved, because no Google request happens.
    # `remember_response` then stores any live result for the next replay.
    if test_mode.is_enabled():
        cached, _ = test_mode.resolve_request(
            kind, url, params=kwargs.get("params")
        )
        if cached is not None:
            calls = getattr(_places_run_state, "calls", None)
            if calls is not None:
                calls["legacy_nearby_fixture"] = calls.get(
                    "legacy_nearby_fixture", 0) + 1
            return cached

    global _nearby_last_request_at
    with _nearby_request_lock:
        # Single funnel for every Places API (Legacy) request in this module, so
        # this is the one place that has to be paced. The shared limiter (see
        # api/utils/places_rate_limit.py) keeps the send rate under Google's
        # 60 requests/minute Legacy quota and coordinates every thread in the
        # process, including overlapping detection runs. Per-request timing is
        # recorded only for diagnostics now.
        waited = LEGACY_NEARBY_LIMITER.acquire()
        if waited > 5:
            print(
                f"[Run Detection] legacy Nearby rate limiter held the request "
                f"for {waited:.1f}s (Cloud quota "
                f"{CLOUD_LEGACY_NEARBY_PER_MINUTE}/minute)."
            )
        _reserve_places_call(kind)
        calls = getattr(_places_run_state, "calls", None)
        if calls is not None:
            calls["legacy_nearby"] += 1
            query_kind = getattr(_places_run_state, "query_kind", "initial")
            calls[f"legacy_nearby_{query_kind}"] += 1
        try:
            response = http.get(url, **kwargs)
        finally:
            _nearby_last_request_at = time.monotonic()
    if test_mode.is_enabled() and getattr(response, "status_code", None) == 200:
        try:
            test_mode.remember_response(
                kind, url, kwargs.get("params"), None, response.json()
            )
        except ValueError:
            pass
    return response


def get_places_usage_today():
    _ensure_budget_tables()
    cur = mysql.connection.cursor()
    try:
        m_used = _places_usage_count(cur, "month")
        d_used = _places_usage_count(cur, "day", today=True)

        geo_daily_cap = quota_settings.cap("quota.geocoding.daily")
        geo_monthly_cap = quota_settings.cap("quota.geocoding.monthly")
        geocoding = read_usage(mysql.connection, "geo_month", "geo_day")
        geo_info = {
            "cap": geo_daily_cap,
            "remaining": max(0, geo_daily_cap - geocoding["day"]),
            "used": geocoding["day"],
            "monthly_cap": geo_monthly_cap,
            "monthly_remaining": max(0, geo_monthly_cap - geocoding["month"]),
            "used_month": geocoding["month"],
        }

        from api.registry.places_resolver import TEXT_SEARCH_WORKFLOW_LEDGER
        ts_daily_cap = quota_settings.cap("quota.text_search.daily")
        ts_monthly_cap = quota_settings.cap("quota.text_search.monthly")
        pd_daily_cap = quota_settings.cap("quota.place_details.daily")
        pd_monthly_cap = quota_settings.cap("quota.place_details.monthly")
        text_search = read_usage(
            mysql.connection, "imp_ts_month", "imp_ts_day")
        details = read_usage(mysql.connection, "imp_pd_month", "imp_pd_day")
        text_search_workflows = {}
        for scope, ledger_kind in TEXT_SEARCH_WORKFLOW_LEDGER.items():
            used = read_daily_usage(mysql.connection, ledger_kind)
            cap = quota_settings.cap(f"quota.text_search.workflow.{scope}")
            text_search_workflows[scope] = {
                "used_today": used,
                "daily_cap": cap,
                "daily_remaining": max(0, cap - used),
                "daily_quota_exceeded": used >= cap,
            }
        nearby_new = read_usage(
            mysql.connection, "new_nearby_month", "new_nearby_day"
        )
        legacy_nearby_daily_cap = quota_settings.cap(
            "quota.legacy_nearby.daily")
        legacy_nearby_monthly_cap = quota_settings.cap(
            "quota.legacy_nearby.monthly")
        nearby_new_daily_cap = quota_settings.cap("quota.nearby_new.daily")
        nearby_new_monthly_cap = quota_settings.cap("quota.nearby_new.monthly")
        nearby_legacy = {
            "enabled": True,
            "used_today": d_used,
            "daily_cap": legacy_nearby_daily_cap,
            "daily_remaining": max(0, legacy_nearby_daily_cap - d_used),
            "used_month": m_used,
            "monthly_cap": legacy_nearby_monthly_cap,
            "monthly_remaining": max(0, legacy_nearby_monthly_cap - m_used),
            "daily_quota_exceeded": d_used >= legacy_nearby_daily_cap,
            "monthly_quota_exceeded": m_used >= legacy_nearby_monthly_cap,
        }
        nearby_new_status = {
            "enabled": (
                nearby_new_daily_cap > 0 and nearby_new_monthly_cap > 0
            ),
            "used_today": nearby_new["day"],
            "daily_cap": nearby_new_daily_cap,
            "daily_remaining": max(0, nearby_new_daily_cap - nearby_new["day"]),
            "used_month": nearby_new["month"],
            "monthly_cap": nearby_new_monthly_cap,
            "monthly_remaining": max(
                0, nearby_new_monthly_cap - nearby_new["month"]
            ),
            "daily_quota_exceeded": (
                nearby_new_daily_cap > 0
                and nearby_new["day"] >= nearby_new_daily_cap
            ),
            "monthly_quota_exceeded": (
                nearby_new_monthly_cap > 0
                and nearby_new["month"] >= nearby_new_monthly_cap
            ),
        }
        active_nearby_usage = (
            nearby_new_status
            if _nearby_api_mode() == "new"
            else nearby_legacy
        )

        return {
            "month": {
                "used": m_used,
                "cap": legacy_nearby_monthly_cap,
                "remaining": max(0, legacy_nearby_monthly_cap - m_used),
            },
            "monthly": {
                "used": m_used,
                "cap": legacy_nearby_monthly_cap,
                "remaining": max(0, legacy_nearby_monthly_cap - m_used),
            },
            "today": {
                "used": d_used,
                "cap": legacy_nearby_daily_cap,
                "remaining": max(0, legacy_nearby_daily_cap - d_used),
            },
            "geocode": geo_info,
            "text_search_month": {
                "used": text_search["month"],
                "cap": ts_monthly_cap,
                "remaining": max(0, ts_monthly_cap - text_search["month"]),
                "monthly_quota_exceeded": text_search["month"] >= ts_monthly_cap,
            },
            "text_search_day": {
                "used": text_search["day"],
                "cap": ts_daily_cap,
                "remaining": max(0, ts_daily_cap - text_search["day"]),
                "daily_quota_exceeded": text_search["day"] >= ts_daily_cap,
            },
            "text_search_workflows": text_search_workflows,
            "monthly_quota_exceeded": text_search["month"] >= ts_monthly_cap,
            "place_details_day": {
                "used": details["day"],
                "cap": pd_daily_cap,
                "remaining": max(0, pd_daily_cap - details["day"]),
                "daily_quota_exceeded": details["day"] >= pd_daily_cap,
            },
            "place_details_month": {
                "used": details["month"],
                "cap": pd_monthly_cap,
                "remaining": max(0, pd_monthly_cap - details["month"]),
                "monthly_quota_exceeded": details["month"] >= pd_monthly_cap,
            },
            "nearby_search_mode": _nearby_api_mode(),
            "nearby_search_legacy": nearby_legacy,
            "nearby_search_new": nearby_new_status,
            "nearby_search_active": active_nearby_usage,
            "quota_source": "application",
            "quota_settings": {
                "text_search": {
                    "daily_cap": ts_daily_cap,
                    "monthly_cap": ts_monthly_cap,
                    "workflow_daily_caps": {
                        scope: quota_settings.cap(
                            f"quota.text_search.workflow.{scope}")
                        for scope in TEXT_SEARCH_WORKFLOW_LEDGER
                    },
                },
                "place_details": {
                    "daily_cap": pd_daily_cap,
                    "monthly_cap": pd_monthly_cap,
                },
                "geocoding": {
                    "daily_cap": geo_daily_cap,
                    "monthly_cap": geo_monthly_cap,
                },
                "nearby_search_legacy": {
                    "daily_cap": legacy_nearby_daily_cap,
                    "monthly_cap": legacy_nearby_monthly_cap,
                },
                "nearby_search_new": {
                    "daily_cap": nearby_new_daily_cap,
                    "monthly_cap": nearby_new_monthly_cap,
                },
                "run_detection_monthly_scan_limit": (
                    quota_settings.cap("run_detection.monthly_scan_limit")
                ),
                "quota_resets_enabled": (
                    API_QUOTA_CONFIG.allow_quota_resets
                ),
            },
        }
    finally:
        cur.close()


def _places_usage_count(cur, kind, today=False):
    if today:
        cur.execute(
            f"SELECT requestCount AS c FROM places_api_usage "
            f"WHERE usageDate = {MANILA_DATE_SQL} AND kind = %s",
            (kind,),
        )
    else:
        cur.execute(
            f"SELECT requestCount AS c FROM places_api_usage WHERE usageDate = {_MONTH_KEY} AND kind = %s",
            (kind,),
        )
    row = cur.fetchone()
    return int((row.get("c") if isinstance(row, dict) else row[0]) or 0) if row else 0


#: Detection-run statuses that mark a scan cycle as finished.
#:
#: `_completed_points_this_cycle` uses these as a watermark: only when a run
#: reaches one of them is the previous cycle's checkpoint list considered
#: settled. A run that stops on the work budget is recorded as "partial", which
#: is deliberately NOT in this list, so its completed grid points stay
#: checkpointed and the next scan resumes from where it stopped rather than
#: starting the grid over.
#:
#: This matters more than it looks: the Legacy Nearby rate limiter makes runs
#: stop on the work budget more often, so more runs end "partial".
RESUME_RESET_STATUSES = ("completed", "completed_with_gaps", "reset")


def _completed_points_this_cycle():
    """
    Grid points already finished since the last COMPLETED scan (so a scan interrupted by the
    daily budget resumes instead of restarting). Our own grid keys only.
    """
    statuses = ", ".join(f"'{s}'" for s in RESUME_RESET_STATUSES)
    cur = mysql.connection.cursor()
    try:
        cur.execute(f"""
            SELECT pointKey FROM scan_point_log
            WHERE completedAt > COALESCE(
                    (SELECT MAX(completedAt) FROM detection_runs
                      WHERE status IN ({statuses})),
                    '1970-01-01')
              AND completedAt > NOW() - INTERVAL 30 DAY
        """)
        return {(r["pointKey"] if isinstance(r, dict) else r[0]) for r in cur.fetchall()}
    finally:
        cur.close()


def _mark_point_done(point_key):
    cur = mysql.connection.cursor()
    try:
        cur.execute("""
            INSERT INTO scan_point_log (pointKey, completedAt) VALUES (%s, NOW())
            ON DUPLICATE KEY UPDATE completedAt = NOW()
        """, (point_key,))
        mysql.connection.commit()
    finally:
        cur.close()


def _unmark_points(point_keys):
    if not point_keys:
        return
    cur = mysql.connection.cursor()
    try:
        marks = ",".join(["%s"] * len(point_keys))
        cur.execute(
            f"DELETE FROM scan_point_log WHERE pointKey IN ({marks})", tuple(point_keys))
        mysql.connection.commit()
    finally:
        cur.close()


def _cleanup_cancelled_detection(inserted_flag_ids, point_keys):
    """Atomically remove this run's new Red flags and their checkpoints."""
    inserted_flag_ids = tuple(dict.fromkeys(inserted_flag_ids))
    point_keys = tuple(dict.fromkeys(point_keys))
    if not inserted_flag_ids and not point_keys:
        return

    cursor = mysql.connection.cursor()
    try:
        mysql.connection.begin()
        if inserted_flag_ids:
            placeholders = ", ".join(["%s"] * len(inserted_flag_ids))
            _detection_execute(
                cursor,
                "DELETE FROM geospatial_logs "
                f"WHERE logID IN ({placeholders})",
                inserted_flag_ids,
            )
        if point_keys:
            placeholders = ", ".join(["%s"] * len(point_keys))
            _detection_execute(
                cursor,
                "DELETE FROM scan_point_log "
                f"WHERE pointKey IN ({placeholders})",
                point_keys,
            )
        _detection_commit()
    except Exception:
        mysql.connection.rollback()
        raise
    finally:
        cursor.close()


# ── GeoJSON Loading ───────────────────────────────────────────────────────────
MATAASNAKAHOY_GEOJSON_PATH = os.path.join(
    os.path.dirname(__file__), '..', 'utils', 'mataasnakahoy.json')
_BARANGAY_POLYGONS = {}
_GEOJSON_BARANGAY_ALIASES = {
    "District I (Pob.)": "Barangay I",
    "District II (Pob.)": "Barangay II",
    "District III (Pob.)": "Barangay III",
    "District IV (Pob.)": "Barangay IV",
    "Barangay II-A (Pob.)": "Barangay II-A",
    "Lumang Lipa": "Barangay Lumanglipa",
}

if os.path.exists(MATAASNAKAHOY_GEOJSON_PATH):
    with open(MATAASNAKAHOY_GEOJSON_PATH, 'r', encoding='utf-8') as f:
        _geojson_data = json.load(f)
        for feature in _geojson_data.get('features', []):
            b_name = feature.get('properties', {}).get('ADM4_EN')
            if b_name:
                poly = shape(feature.get('geometry'))
                _BARANGAY_POLYGONS[b_name] = poly

# ── Municipality spatial config ───────────────────────────────────────────────
# Cross-referencing threshold: POI must be within this distance of a registry
# entry to be considered a match (Green). Otherwise it becomes a Red Flag.
THRESHOLD_M = 20

# ── STRICT BOUNDARY FILTER ───────────────────────────────────────────────────
# Hard bounding box for Mataasnakahoy, Batangas.
# Any POI returned by Google Places outside this box is immediately discarded
# before cross-referencing — this is what prevents businesses from other
# municipalities from appearing as false Red Flags.
#
# Derived from the same source as the barangay polygons: the geometric union of
# all 16 barangay features in MATAASNAKAHOY_GEOJSON_PATH. The previous literal was
# an independent OSM-derived outline that disagreed with the GADM barangay
# geometry on the east/northeast edge by up to 578 m while overshooting the
# western edge by 7.3 km, so six barangay polygons extended outside it and their
# submissions were rejected by fail-closed validation.
#
# Deriving instead of hardcoding makes municipal containment structural: every
# barangay is contained by construction and the two datasets can never drift
# apart again. Do not reintroduce a hand-maintained outline here.
_BOUNDARY_GEOJSON = mapping(
    unary_union(list(_BARANGAY_POLYGONS.values()))
)
_MUNICIPALITY_BOUNDARY = shape(_BOUNDARY_GEOJSON)
_MUNICIPALITY_WITH_TOLERANCE = _MUNICIPALITY_BOUNDARY.buffer(0.0005)
prepare(_MUNICIPALITY_WITH_TOLERANCE)
_METERS_PER_DEGREE_LAT = 111_320.0
_METERS_PER_DEGREE_LNG = _METERS_PER_DEGREE_LAT * math.cos(math.radians(13.98))
_MUNICIPALITY_WITH_TOLERANCE_METERS = scale(
    _MUNICIPALITY_WITH_TOLERANCE,
    xfact=_METERS_PER_DEGREE_LNG,
    yfact=_METERS_PER_DEGREE_LAT,
    origin=(0, 0),
)


def _within_municipality(lat: float, lng: float) -> bool:
    """Polygon test with tight 0.0005° (~55m) buffer for border road tolerance without spilling into Lipa/Balete."""
    if lat is None or lng is None:
        return False
    return _MUNICIPALITY_WITH_TOLERANCE.contains(Point(lng, lat))


def is_within_municipality_boundary(lat: float, lng: float) -> bool:
    """Check the unbuffered Mataasnakahoy boundary for imported coordinates."""
    if lat is None or lng is None:
        return False
    return _MUNICIPALITY_BOUNDARY.covers(Point(lng, lat))


def _normalize_business_name(name: str) -> str:
    tokens, _ = parse_name(name)
    return " ".join(tokens)


class _RegistryMatchIndex:
    """Find only registry names that can share a token with the POI name."""

    def __init__(self, registry):
        self.registry = registry
        self.entries_by_token = {}
        self.tokens_by_length = {}
        self.match_requests = 0
        self.candidate_rows_scored = 0
        for index, entry in enumerate(registry):
            tokens, _ = parse_name(entry.get("businessName", ""))
            for token in set(tokens):
                self.entries_by_token.setdefault(token, []).append(index)
                self.tokens_by_length.setdefault(len(token), set()).add(token)

    def candidates(self, poi_name):
        self.match_requests += 1
        poi_tokens, _ = parse_name(poi_name)
        candidate_indexes = set()
        for poi_token in set(poi_tokens):
            if len(poi_token) < 5:
                possible_tokens = (poi_token,)
            else:
                min_length = max(1, int(len(poi_token) * 0.7))
                max_length = int(len(poi_token) / 0.7) + 1
                possible_tokens = (
                    token
                    for length in range(min_length, max_length + 1)
                    for token in self.tokens_by_length.get(length, ())
                )
            for registry_token in possible_tokens:
                threshold = (
                    0.85 if min(len(registry_token), len(poi_token)) >= 5
                    else 1.0
                )
                if difflib.SequenceMatcher(
                    None, registry_token, poi_token
                ).ratio() >= threshold:
                    candidate_indexes.update(
                        self.entries_by_token.get(registry_token, ())
                    )
        candidates = [self.registry[index]
                      for index in sorted(candidate_indexes)]
        self.candidate_rows_scored += len(candidates)
        return candidates


def _name_similarity(
    name1: str,
    name2: str,
    reg_line: str = '',
    poi_types: tuple = (),
    reg_type: str = '',
) -> float:
    score, _ = name_match(
        name1, name2, reg_line=reg_line, poi_types=poi_types, reg_type=reg_type
    )
    return score


def _match_poi_to_registry(
    poi_name,
    poi_lat,
    poi_lng,
    registry,
    poi_barangay_id=None,
    poi_types=(),
    poi_address='',
    registry_index=None,
    place_id=None,
    rejected_place_pairs=None,
):
    """
    Tiered Decision Matrix for matching a candidate POI to official registry entries:
    - Auto: compatible category, score >= 0.80, and within 300 m; without coordinates,
      require same barangay plus strong address agreement.
    - Review: plausible score >= 0.55 with no hard category conflict, or competing candidates.
    - No Match: weak/single-token-only name, hard category conflict, or score < 0.55.
      Address or proximity alone never establishes identity.
    Returns (matched_entry, distance_meters, similarity_score, match_status)
    """
    best_match = None
    best_dist = float("inf")
    best_score = 0.0
    best_status = "no_match"
    candidate_scores = []

    entries = (
        registry_index.candidates(poi_name)
        if registry_index is not None else registry
    )
    for entry in entries:
        if _is_rejected_registry_place_pair(
            entry.get("businessID"), place_id, rejected_place_pairs
        ):
            continue
        sim, match_reason = name_match(
            entry.get("businessName", ""),
            poi_name,
            reg_line=entry.get("businessLine", ""),
            reg_type=entry.get("businessType", ""),
            poi_types=poi_types,
        )
        if match_reason in ("category_conflict", "weak_name", "no_shared_name"):
            continue
        # Strict cutoff: under 0.55 is rejected regardless of proximity
        if sim < 0.55:
            continue

        address_score = address_similarity(
            entry.get("businessAddress", ""), poi_address
        )
        reg_lat = entry.get("latitude")
        reg_lng = entry.get("longitude")
        reg_b_id = entry.get("barangayID")
        same_barangay = (reg_b_id is None) or (
            poi_barangay_id is None) or (reg_b_id == poi_barangay_id)

        dist = None
        if reg_lat is not None and reg_lng is not None:
            try:
                dist = geodesic((poi_lat, poi_lng),
                                (float(reg_lat), float(reg_lng))).meters
            except Exception:
                dist = None

        supported_score = min(
            1.0,
            sim + (0.05 if address_score >= 0.6 else 0.0),
        )
        candidate_scores.append((entry.get("businessID"), supported_score))
        if match_reason == "soft_category_conflict":
            status = "review"
        elif supported_score >= 0.80:
            if dist is not None:
                status = "auto" if dist <= 300.0 else "review"
            else:
                status = (
                    "auto"
                    if same_barangay and address_score >= 0.75
                    else "review"
                )
        else:
            status = "review"

        # Candidate selection priority:
        # 1. Prefer 'auto' over 'review'
        # 2. Prefer higher similarity score
        # 3. Prefer smaller geographical distance
        is_better = False
        if best_match is None:
            is_better = True
        elif status == "auto" and best_status != "auto":
            is_better = True
        elif status == best_status:
            if supported_score > best_score + 0.01:
                is_better = True
            elif abs(supported_score - best_score) <= 0.01:
                cur_dist = dist if dist is not None else float("inf")
                if cur_dist < best_dist:
                    is_better = True

        if is_better:
            best_match = entry
            best_dist = dist if dist is not None else 0.0
            best_score = supported_score
            best_status = status

    competing_match = any(
        business_id != best_match.get("businessID")
        and score >= best_score - 0.05
        for business_id, score in candidate_scores
    ) if best_match else False
    if competing_match and best_status == "auto":
        best_status = "review"

    return best_match, best_dist, best_score, best_status


def _is_rejected_registry_place_pair(business_id, place_id, rejected_pairs):
    if not business_id or not place_id or not rejected_pairs:
        return False
    return (str(business_id), str(place_id)) in rejected_pairs


def _registry_entry_for_place_id(place_id, registry_by_place_id, rejected_pairs):
    if not place_id:
        return None
    entries = registry_by_place_id.get(place_id, ())
    if not isinstance(entries, (list, tuple)):
        entries = (entries,)
    return next(
        (
            entry for entry in entries
            if not _is_rejected_registry_place_pair(
                entry.get("businessID"), place_id, rejected_pairs
            )
        ),
        None,
    )


def _load_rejected_place_pairs():
    cursor = mysql.connection.cursor()
    try:
        cursor.execute(
            "SELECT businessID, placeID FROM registry_rejected_places"
        )
        rows = cursor.fetchall()
        pairs = set()
        for row in rows:
            business_id = (
                row.get("businessID") if isinstance(row, dict) else row[0]
            )
            place_id = row.get("placeID") if isinstance(row, dict) else row[1]
            if business_id and place_id:
                pairs.add((str(business_id), str(place_id)))
        return pairs
    finally:
        cursor.close()


def _detection_status_color(application_status):
    status = (
        str(application_status).strip()
        if application_status is not None else ""
    ) or "Pending"
    return (
        "Green" if status == "Active" else
        "Red" if status == "Expired" else
        "Black" if status in ("Revoked", "Blacklisted") else
        "Purple" if status == "Closed" else "Yellow"
    )


_place_types_column_ready = False
_place_types_schema_lock = threading.Lock()


def _ensure_place_types_column():
    global _place_types_column_ready
    if _place_types_column_ready:
        return

    with _place_types_schema_lock:
        if _place_types_column_ready:
            return
        cursor = mysql.connection.cursor()
        try:
            cursor.execute(
                "SHOW COLUMNS FROM geospatial_logs LIKE 'placeTypes'")
            if not cursor.fetchone():
                cursor.execute(
                    "ALTER TABLE geospatial_logs ADD COLUMN placeTypes JSON NULL AFTER nearestLandmark"
                )
                mysql.connection.commit()
            _place_types_column_ready = True
        finally:
            cursor.close()


def _decode_place_types(value):
    if isinstance(value, (list, tuple, set)):
        return tuple(sorted(str(item) for item in value if item))
    if not value:
        return ()
    try:
        parsed = json.loads(value) if isinstance(value, str) else value
    except (TypeError, ValueError):
        return ()
    if not isinstance(parsed, (list, tuple, set)):
        return ()
    return tuple(sorted(str(item) for item in parsed if item))


def _match_registry_to_google(
    place_id,
    business_id,
    detected_name,
    target_color='Green',
    lat=None,
    lng=None,
    barangay_id=None,
    match_score=None,
    match_status=None,
    poi_types=(),
    poi_address=None,
    commit=True,
    operation_type=None,
    rejected_place_pairs=None,
):
    """
    Updates or inserts the geospatial log for an existing registry business 
    with its official Google Maps Place ID and dynamic status-based flag color.
    Also backfills discovered GPS coordinates into official_registry if unlocked.
    Cleans up any redundant unpositioned baseline logs for this business.
    """
    serialized_types = json.dumps(
        sorted(set(poi_types))) if poi_types else None
    cursor = mysql.connection.cursor()
    if operation_type == "reconciled":
        from api.registry.audit import ensure_registry_workflow_events
        ensure_registry_workflow_events()

    if match_status is None:
        if match_score is not None:
            match_status = "auto" if float(match_score) >= 0.80 else "review"
        else:
            match_status = "auto"

    # 1. Query current official_registry metadata before updating
    is_locked = False
    reg_lat = None
    reg_lng = None
    registry_place_id = None
    registry_match_status = None
    if business_id:
        from api.registry.inspection_link import confirmed_pin_column_available
        if confirmed_pin_column_available(cursor):
            _detection_execute(cursor, "SELECT confirmedLogID FROM official_registry WHERE businessID = %s FOR UPDATE", (business_id,))
            confirmed = cursor.fetchone()
            if confirmed and confirmed.get("confirmedLogID") is not None:
                # Detection must not replace the admin-confirmed pin, merge its
                # history into a generated marker, or change its original source.
                cursor.close()
                return
        _detection_execute(cursor, """
            SELECT coordSource, matchStatus, latitude, longitude, placeID
            FROM official_registry
            WHERE businessID = %s
        """, (business_id,))
        reg_row = cursor.fetchone()
        if reg_row:
            src = (reg_row.get("coordSource") or "").strip().lower()
            m_stat = (reg_row.get("matchStatus") or "").strip().lower()
            registry_match_status = m_stat
            registry_place_id = reg_row.get("placeID")
            if src == "manual" or m_stat == "approved":
                is_locked = True
                reg_lat = reg_row.get("latitude")
                reg_lng = reg_row.get("longitude")
            elif m_stat == "auto" and match_status == "review":
                # Guard: Do not downgrade an already confident auto match with a lower-confidence review candidate
                is_locked = True
                reg_lat = reg_row.get("latitude")
                reg_lng = reg_row.get("longitude")

    if _is_rejected_registry_place_pair(
        business_id, place_id, rejected_place_pairs
    ):
        cursor.close()
        return
    if (
        registry_match_status == "approved"
        and registry_place_id
        and registry_place_id != place_id
    ):
        cursor.close()
        return

    # 2. Backfill discovered GPS coordinates into official_registry IF NOT LOCKED
    if business_id and not is_locked:
        if lat and lng:
            stat_sql = "review" if match_status == "review" else "auto"
            _detection_execute(cursor, f"""
                UPDATE official_registry
                SET latitude = %s,
                    longitude = %s,
                    placeID = %s,
                    placeIDKind = 'poi',
                    coordSource = 'places',
                    coordFetchedAt = NOW(),
                    matchScore = %s,
                    matchStatus = '{stat_sql}'
                WHERE businessID = %s
            """, (
                lat,
                lng,
                place_id,
                round(float(match_score), 3) if match_score is not None else None,
                business_id
            ))

    # 3. Check all geospatial_logs matching businessID, placeID OR (businessID IS NULL AND detectedName + barangayID)
    _detection_execute(cursor, """
        SELECT g.logID, g.businessID, g.placeID, g.flagColor,
               g.latitude, g.longitude,
               EXISTS (
                   SELECT 1
                   FROM inspection_reports ir
                   WHERE ir.targetType = 'geospatial_log'
                     AND ir.targetID = g.logID
                     AND ir.verificationStatus = 'Verified'
                     AND ir.inspectionResult = 'Orange'
               ) AS has_verified_orange
        FROM geospatial_logs g
        WHERE (g.businessID IS NOT NULL AND g.businessID = %s)
           OR (g.placeID IS NOT NULL AND g.placeID = %s)
           OR (g.businessID IS NULL AND g.detectedName = %s AND g.barangayID = %s)
        ORDER BY (g.businessID = %s) DESC, (g.placeID = %s) DESC
    """, (business_id, place_id, detected_name, barangay_id, business_id, place_id))
    matched_logs = cursor.fetchall()
    matched_logs = [
        log for log in matched_logs
        if not _is_rejected_registry_place_pair(
            log.get("businessID"), log.get("placeID"), rejected_place_pairs
        )
    ]
    if (
        registry_match_status == "approved"
        and any(
            log.get("businessID") == business_id
            and log.get("placeID")
            and log.get("placeID") != place_id
            for log in matched_logs
        )
    ):
        cursor.close()
        return

    if matched_logs:
        # Keep primary log (prefer the one with matching businessID, then placeID)
        primary_log = None
        for log in matched_logs:
            if log.get("businessID") == business_id:
                primary_log = log
                break
        if not primary_log:
            for log in matched_logs:
                if log.get("placeID") == place_id:
                    primary_log = log
                    break
        if not primary_log:
            primary_log = matched_logs[0]

        if target_color == "Red" and any(
            log.get("has_verified_orange") for log in matched_logs
        ):
            target_color = "Orange"

        # If locked, DO NOT overwrite existing verified coordinates with Google's lat/lng!
        final_lat = (reg_lat if reg_lat is not None else primary_log.get(
            "latitude")) if is_locked else lat
        final_lng = (reg_lng if reg_lng is not None else primary_log.get(
            "longitude")) if is_locked else lng

        _detection_execute(cursor, """
                UPDATE geospatial_logs
                SET businessID = %s,
                    placeID = %s, flagColor = %s,
                    detectedName = %s,
                    latitude = %s,
                    longitude = %s,
                    nearestLandmark = COALESCE(%s, nearestLandmark),
                    placeTypes = COALESCE(%s, placeTypes),
                    barangayID = COALESCE(%s, barangayID)
                WHERE logID = %s
            """, (
            business_id, place_id, target_color, detected_name, final_lat, final_lng,
            poi_address, serialized_types, barangay_id, primary_log["logID"]
        ))

        # Remove redundant duplicate unpositioned logs, repointing inspections first
        for log in matched_logs:
            if log["logID"] != primary_log["logID"]:
                _detection_execute(cursor,
                                   "UPDATE inspection_reports SET targetID = %s WHERE targetID = %s",
                                   (primary_log["logID"], log["logID"])
                                   )
                try:
                    _detection_execute(cursor,
                                       "UPDATE inspection_lifecycle_events SET targetLogID = %s WHERE targetLogID = %s",
                                       (primary_log["logID"], log["logID"])
                                       )
                except Exception:
                    pass
                _detection_execute(cursor,
                                   "DELETE FROM geospatial_logs WHERE logID = %s", (log["logID"],))

    elif lat and lng and barangay_id:
        final_lat = reg_lat if (is_locked and reg_lat is not None) else lat
        final_lng = reg_lng if (is_locked and reg_lng is not None) else lng
        _columns, _values, _params = with_source(
            cursor,
            """(barangayID, businessID, reportID, detectedName, latitude, longitude,
                 flagColor, placeID, nearestLandmark, placeTypes)""",
            "(%s, %s, NULL, %s, %s, %s, %s, %s, %s, %s)",
            (barangay_id, business_id, detected_name, final_lat, final_lng,
             target_color, place_id, poi_address, serialized_types),
            # A registry business Google Places also found.
            SOURCE_REGISTRY_DETECTED,
        )
        _detection_execute(
            cursor,
            f"INSERT INTO geospatial_logs {_columns} VALUES {_values}",
            _params)

    if operation_type == "reconciled":
        from api.registry.audit import record_registry_workflow_event
        record_registry_workflow_event(
            cursor,
            business_id,
            "reconciled",
            result_status=match_status,
            place_id=place_id,
            latitude=lat,
            longitude=lng,
            match_score=match_score,
        )

    if commit:
        _detection_commit()
    cursor.close()


_last_reconcile_time = 0.0  # module-level throttle
_RECONCILE_INTERVAL_S = 300   # run at most once every 5 minutes
_reconcile_lock = threading.Lock()


def reconcile_existing_flags(force: bool = False, silent: bool = False):
    """
    Reconciles existing Red flags in geospatial_logs against official_registry.
    If a Red flag was erroneously created for a registered business, converts it
    to Green (or appropriate permit status color), updates official_registry GPS,
    and removes any duplicate unpositioned baseline logs.

    Throttled to run at most once every 5 minutes unless force=True.
    silent=True suppresses all SSE progress events (use when called from run_detection
    to avoid the reconcile overlay flashing mid-scan on the frontend).
    """
    global _last_reconcile_time
    now = time.time()
    if not force and (now - _last_reconcile_time) < _RECONCILE_INTERVAL_S:
        return 0   # too soon; skip

    # Prevent concurrent reconcile runs
    if not _reconcile_lock.acquire(blocking=False):
        print("[Reconcile] Already running. Skipping duplicate concurrent call.")
        return 0

    try:
        _last_reconcile_time = now

        _ensure_place_types_column()
        from api.registry.audit import ensure_registry_workflow_events
        ensure_registry_workflow_events()
        cursor = mysql.connection.cursor()
        cursor.execute("""
            SELECT g.logID, g.businessID, g.placeID, g.detectedName,
                   g.latitude, g.longitude, g.barangayID,
                   g.nearestLandmark, g.placeTypes,
                   EXISTS (
                       SELECT 1
                       FROM inspection_reports ir
                       WHERE ir.targetType = 'geospatial_log'
                         AND ir.targetID = g.logID
                         AND ir.verificationStatus = 'Verified'
                         AND ir.inspectionResult = 'Orange'
                   ) AS has_verified_orange
            FROM geospatial_logs g
            WHERE g.flagColor = 'Red'
              AND g.latitude IS NOT NULL AND g.longitude IS NOT NULL
        """)
        red_flags = cursor.fetchall()
        cursor.close()

        if not red_flags:
            if not silent:
                hub.publish_to_admins({"type": "reconcile_progress", "percentage": 100,
                                      "status": "No Red flags to reconcile.", "converted": 0, "total": 0, "stage": "completed"})
            return 0

        cursor = mysql.connection.cursor()
        cursor.execute("SELECT COUNT(*) AS total FROM official_registry")
        r_row = cursor.fetchone()
        cursor.close()
        reg_count = (r_row.get("total") if isinstance(
            r_row, dict) else r_row[0]) if r_row else 0
        if reg_count == 0:
            if not silent:
                hub.publish_to_admins({"type": "reconcile_progress", "percentage": 100,
                                      "status": "Official registry is empty. No records to reconcile against.", "converted": 0, "total": len(red_flags), "stage": "completed"})
            return 0

        registry = _load_registry()
        rejected_place_pairs = _load_rejected_place_pairs()
        registry_match_index = _RegistryMatchIndex(registry)
        converted_count = 0
        total = len(red_flags)

        if not silent:
            hub.publish_to_admins({"type": "reconcile_progress", "percentage": 0,
                                  "status": f"Checking {total} Red flag(s) against the registry...", "converted": 0, "total": total, "stage": "running"})

        for idx, flag in enumerate(red_flags):
            name = flag.get("detectedName") or ""
            lat = flag.get("latitude")
            lng = flag.get("longitude")
            b_id = flag.get("barangayID")
            place_id = flag.get("placeID")
            biz_id = flag.get("businessID")

            matched_by_id = None
            if biz_id:
                for entry in registry:
                    if (
                        entry.get("businessID") == biz_id
                        and not _is_rejected_registry_place_pair(
                            biz_id, place_id, rejected_place_pairs
                        )
                    ):
                        matched_by_id = entry
                        break

            matched_by_place = None
            if not matched_by_id and place_id:
                for entry in registry:
                    if (
                        entry.get("placeID") == place_id
                        and not _is_rejected_registry_place_pair(
                            entry.get("businessID"), place_id,
                            rejected_place_pairs,
                        )
                    ):
                        matched_by_place = entry
                        break

            if matched_by_id:
                matched = matched_by_id
                dist = 0.0
                score = 1.0
                status = "auto"
            elif matched_by_place:
                matched = matched_by_place
                dist = 0.0
                score = 1.0
                status = "auto"
            else:
                matched, dist, score, status = _match_poi_to_registry(
                    name,
                    lat,
                    lng,
                    registry,
                    poi_barangay_id=b_id,
                    poi_types=_decode_place_types(flag.get("placeTypes")),
                    poi_address=flag.get("nearestLandmark") or "",
                    place_id=place_id,
                    rejected_place_pairs=rejected_place_pairs,
                )

            if matched and status != "no_match":
                target_color = _detection_status_color(
                    matched.get("applicationStatus")
                )
                if status == 'review':
                    target_color = 'Yellow'
                elif (
                    matched.get("applicationStatus") == "Expired"
                    and flag.get("has_verified_orange")
                ):
                    target_color = "Orange"

                target_b_id = matched.get('barangayID') or b_id
                _match_registry_to_google(
                    place_id, matched['businessID'], matched['businessName'],
                    target_color=target_color, lat=lat, lng=lng, barangay_id=target_b_id,
                    match_score=score,
                    poi_types=_decode_place_types(flag.get("placeTypes")),
                    poi_address=flag.get("nearestLandmark"),
                    operation_type="reconciled",
                    rejected_place_pairs=rejected_place_pairs,
                )
                converted_count += 1

            if not silent and (idx % 5 == 0 or idx == total - 1):
                pct = min(99, int(((idx + 1) / max(total, 1)) * 100))
                hub.publish_to_admins({
                    "type": "reconcile_progress",
                    "percentage": pct,
                    "status": f"Checking '{name}'... ({idx + 1}/{total})",
                    "converted": converted_count,
                    "total": total,
                    "stage": "running"
                })

        if not silent:
            hub.publish_to_admins({
                "type": "reconcile_progress",
                "percentage": 100,
                "status": f"Done. Converted {converted_count} of {total} flag(s).",
                "converted": converted_count,
                "total": total,
                "stage": "completed"
            })
        return converted_count

    finally:
        _reconcile_lock.release()


# ── Google Places fetch & checkpointed grid scan ───────────────────────────────
DETECTION_RADIUS_M = 850
# Tunable via env so staging can probe spacing without a redeploy. Coverage is
# NOT monotonic in the step: the lattice is anchored to a fixed bounding-box
# origin while the municipality polygon is arbitrary, so a larger step can slide
# centers out of the inclusion buffer and OPEN a gap that a smaller step did not
# have. 0.0105 degrees leaves a hole; 0.0109 does not. Re-run
# test_reduced_grid_circles_cover_buffered_municipality for any new value
# instead of extrapolating.
DETECTION_GRID_STEP_DEGREES = _env_positive_float(
    "DETECTION_GRID_STEP_DEGREES", 0.009, 0.001
)
NEARBY_RESULT_LIMIT = 60
NEW_NEARBY_RESULT_LIMIT = 20
MAX_ADAPTIVE_DEPTH = 2
MAX_ADAPTIVE_QUERIES_PER_POINT = 12
ADAPTIVE_QUERY_RADIUS_RATIO = 0.72
ADAPTIVE_CENTER_OFFSET_RATIO = 0.5
RUN_DETECTION_MODES = ("quick", "full")


def _normalize_barangay_name(value):
    return "".join(ch for ch in (value or "").lower() if ch.isalnum())


def _quick_discovery_points(barangay_rows=None, max_points=24):
    """Lightweight discovery mode: a capped set of distributed municipal points.

    This is intentionally smaller than the exhaustive grid and avoids adaptive
    recursion. It remains inside Mataasnakahoy's valid barangay boundaries and
    rotates through less-frequently visited sectors across repeated quick scans.
    """
    if barangay_rows is None:
        try:
            cursor = mysql.connection.cursor()
            cursor.execute("SELECT barangayID, barangayName FROM barangays")
            barangay_rows = cursor.fetchall()
            cursor.close()
        except Exception:
            barangay_rows = []

    if not barangay_rows:
        barangay_rows = [
            {"barangayID": i, "barangayName": f"Barangay {letter}"}
            for i, letter in enumerate([
                "I", "II", "III", "IV", "V", "VI", "VII", "VIII",
                "IX", "X", "XI", "XII", "XIII", "XIV", "XV", "XVI",
            ], 1)
        ]

    candidates = []
    for idx, row in enumerate(barangay_rows):
        name = (row.get("barangayName") if isinstance(
            row, dict) else row[1]) or ""
        matched = None
        normalized_name = _normalize_barangay_name(name)
        for poly_name, poly in _BARANGAY_POLYGONS.items():
            if normalized_name and (
                normalized_name in _normalize_barangay_name(poly_name)
                or _normalize_barangay_name(poly_name) in normalized_name
            ):
                matched = poly.centroid
                break

        if matched is None:
            lat = 13.9667 + ((idx % 4) - 1.5) * 0.0035
            lng = 121.1167 + ((idx % 3) - 1) * 0.0038
            matched = Point(lng, lat)

        base_lat, base_lng = matched.y, matched.x
        offsets = [
            (0.0000, 0.0000),
            (0.0018, 0.0025),
            (-0.0015, -0.0024),
            (0.0022, -0.0012),
        ]
        for lat_offset, lng_offset in offsets:
            lat = base_lat + lat_offset
            lng = base_lng + lng_offset
            if _within_municipality(lat, lng):
                candidates.append((lat, lng))

    anchor_points = [
        (13.9490, 121.1040),
        (13.9498, 121.1188),
        (13.9595, 121.0900),
        (13.9595, 121.1248),
        (13.9705, 121.0925),
        (13.9746, 121.1240),
        (13.9832, 121.0998),
        (13.9860, 121.1185),
        (13.9988, 121.1090),
        (13.9667, 121.1167),
    ]
    for lat, lng in anchor_points:
        if _within_municipality(lat, lng):
            candidates.append((lat, lng))

    seen = set()
    distinct = []
    history = getattr(_places_run_state, "quick_scan_history", {})
    scored = []
    for lat, lng in candidates:
        key = (round(lat, 5), round(lng, 5))
        if key in seen:
            continue
        seen.add(key)
        score = history.get(key, 0) + abs(lat - 13.9667) + abs(lng - 121.1167)
        scored.append((score, lat, lng))

    point_limit = max(1, min(24, int(max_points)))
    for _, lat, lng in sorted(scored, key=lambda item: (item[0], item[1], item[2]))[:point_limit]:
        distinct.append((lat, lng))

    if not distinct:
        return [(13.9667, 121.1167)]

    return distinct


def _grid_points():
    """
    Include nearby outside centers so search circles cover the municipal boundary.

    The step comes from the effective setting rather than the import-time
    constant so an admin override applies without a redeploy. Test Mode narrows
    the scope to the first N centres, which is the "small geographic area"
    switch the admin panel exposes.
    """
    min_lat, max_lat = 13.9450, 14.0125
    min_lng, max_lng = 121.0120, 121.1260
    step = quota_settings.cap("run_detection.grid_step_degrees")
    test_config = test_mode.get_config() if test_mode.is_enabled() else None
    radius_m = DETECTION_RADIUS_M
    limit = None
    if test_config:
        step = test_config["test_mode.grid_step_degrees"]
        radius_m = test_config["test_mode.radius_m"]
        limit = test_config["test_mode.max_grid_points"]
    search_buffer_degrees = (radius_m / 111_320.0) * 1.1
    search_area = _MUNICIPALITY_BOUNDARY.buffer(search_buffer_degrees)
    points = []
    lat = min_lat
    while lat <= max_lat:
        lng = min_lng
        while lng <= max_lng:
            if search_area.contains(Point(lng, lat)):
                points.append((lat, lng))
                if limit and len(points) >= limit:
                    return points
            lng += step
        lat += step
    return points


def _checkpoint_configuration_fingerprint(detection_mode):
    test_config = test_mode.get_config() if test_mode.is_enabled() else {}
    test_mode_enabled = bool(test_config.get("test_mode.enabled", False))
    grid_step = (
        test_config["test_mode.grid_step_degrees"]
        if test_mode_enabled
        else quota_settings.cap("run_detection.grid_step_degrees")
    )
    relevant_test_settings = (
        {
            key: value
            for key, value in test_config.items()
            if key.startswith("test_mode.")
        }
        if test_mode_enabled else {}
    )
    material = {
        "version": 2,
        "detection_mode": detection_mode,
        "nearby_api": _nearby_api_mode(),
        "radius_m": _detection_radius_m(),
        "grid_step_degrees": grid_step,
        "test_mode": relevant_test_settings,
    }
    encoded = json.dumps(
        material, sort_keys=True, separators=(",", ":"), default=str
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:16]


def _checkpoint_point_key(lat, lng, fingerprint):
    return f"v2:{fingerprint}:{lat:.5f},{lng:.5f}"


def _detection_points_for_mode(mode, barangay_rows=None):
    if mode == "full":
        return _grid_points()
    test_config = test_mode.get_config()
    max_points = (
        test_config["test_mode.max_grid_points"]
        if test_config["test_mode.enabled"] else 24
    )
    return _quick_discovery_points(barangay_rows, max_points=max_points)


def _detection_radius_m():
    """Effective search radius; Test Mode may shrink it."""
    if test_mode.is_enabled():
        return test_mode.get_config()["test_mode.radius_m"]
    return DETECTION_RADIUS_M


def _nearby_api_mode():
    mode = RUN_DETECTION_NEARBY_API
    if mode not in ("legacy", "new"):
        raise RuntimeError(
            "RUN_DETECTION_NEARBY_API must be either 'legacy' or 'new'."
        )
    return mode


def _record_nearby_api_error():
    current = getattr(_places_run_state, "api_errors", 0)
    _places_run_state.api_errors = current + 1


def _detection_execute(cursor, query, params=None):
    if getattr(_places_run_state, "db_metrics_active", False):
        _places_run_state.db_queries += 1
    if params is None:
        return cursor.execute(query)
    return cursor.execute(query, params)


def _detection_commit():
    if getattr(_places_run_state, "db_metrics_active", False):
        _places_run_state.db_commits += 1
    mysql.connection.commit()


def _active_nearby_result_limit():
    return (
        NEW_NEARBY_RESULT_LIMIT
        if _nearby_api_mode() == "new"
        else NEARBY_RESULT_LIMIT
    )


def _detection_work_limits():
    """
    Effective work-slice limits for this check.

    Resolved per call so an admin override applies to the next slice without a
    redeploy. Test Mode tightens the request cap further. Fixture replays are
    not counted: they cost no Google request.
    """
    max_seconds = quota_settings.cap("run_detection.max_seconds")
    max_requests = quota_settings.cap("run_detection.max_requests")
    if test_mode.is_enabled():
        max_requests = min(
            max_requests, test_mode.get_config()["test_mode.max_requests"]
        )
    return max_seconds, max_requests


def _detection_work_budget_reached():
    started_at = getattr(_places_run_state, "started_at", None)
    if started_at is None:
        return False
    calls = getattr(_places_run_state, "calls", {})
    request_count = calls.get("legacy_nearby", 0) + calls.get("new_nearby", 0)
    elapsed_seconds = time.monotonic() - started_at
    max_seconds, max_requests = _detection_work_limits()
    time_limit_hit = elapsed_seconds >= max_seconds
    request_limit_hit = request_count >= max_requests
    if time_limit_hit or request_limit_hit:
        _places_run_state.work_budget_exhausted = True
        _places_run_state.work_budget_reason = (
            "time_limit" if time_limit_hit else "request_limit"
        )
    return time_limit_hit or request_limit_hit


def _detection_result_processing_stopped():
    """Stop local result processing for elapsed-time limits, not request caps."""
    if not _detection_work_budget_reached():
        return False
    return getattr(_places_run_state, "work_budget_reason", None) != "request_limit"


def _detection_elapsed_metrics(request_started_at):
    """
    Timing diagnostics for every terminal path.

    `elapsed_seconds` is end-to-end request time, so it includes the
    pre-scan reconciliation pass that is still synchronous. `scan_elapsed_seconds`
    covers only the grid traversal bounded by RUN_DETECTION_MAX_SECONDS.
    `scan_elapsed_seconds` is 0.0 when the run failed before grid traversal
    started, since the work-slice clock is not armed until then.
    """
    now = time.monotonic()
    scan_started_at = getattr(_places_run_state, "started_at", None)
    return {
        "elapsed_seconds": round(now - request_started_at, 1),
        "scan_elapsed_seconds": (
            0.0 if scan_started_at is None
            else round(now - scan_started_at, 1)
        ),
    }


def _detection_performance_metrics(counters, registry, registry_match_index):
    calls = getattr(_places_run_state, "calls", {})
    api_requests = (
        calls.get("legacy_nearby", 0) + calls.get("new_nearby", 0)
    )
    fixture_requests = (
        calls.get("legacy_nearby_fixture", 0)
        + calls.get("new_nearby_fixture", 0)
    )
    nearby_queries = api_requests + fixture_requests
    match_calls = registry_match_index.match_requests
    possible_registry_comparisons = match_calls * len(registry)
    candidate_rows = registry_match_index.candidate_rows_scored
    return {
        "api_requests_consumed": api_requests,
        "fixture_requests_replayed": fixture_requests,
        "nearby_queries_processed": nearby_queries,
        "unique_in_bound_pois": counters["unique_in_bound_pois"],
        "unique_pois_per_api_request": round(
            counters["unique_in_bound_pois"] / api_requests, 3
        ) if api_requests else 0.0,
        "unique_pois_per_nearby_query": round(
            counters["unique_in_bound_pois"] / nearby_queries, 3
        ) if nearby_queries else 0.0,
        "actionable_business_candidates": counters[
            "actionable_business_candidates"
        ],
        "actionable_candidates_per_api_request": round(
            counters["actionable_business_candidates"] / api_requests, 3
        ) if api_requests else 0.0,
        "actionable_candidates_per_nearby_query": round(
            counters["actionable_business_candidates"] / nearby_queries, 3
        ) if nearby_queries else 0.0,
        "new_flags_per_api_request": round(
            counters["new_flags"] / api_requests, 3
        ) if api_requests else 0.0,
        "registry_match_time_seconds": round(
            getattr(_places_run_state, "registry_match_time_seconds", 0.0), 4
        ),
        "registry_match_calls": match_calls,
        "registry_candidate_rows_scored": candidate_rows,
        "registry_full_scan_rows_avoided": max(
            0, possible_registry_comparisons - candidate_rows
        ),
        "registry_candidate_reduction_percent": round(
            100 * (possible_registry_comparisons - candidate_rows)
            / possible_registry_comparisons,
            1,
        ) if possible_registry_comparisons else 0.0,
        "poi_processing_db_queries": getattr(
            _places_run_state, "db_queries", 0
        ),
        "poi_processing_db_commits": getattr(
            _places_run_state, "db_commits", 0
        ),
        "poi_processing_db_metric_scope": (
            "POI lookups and writes during grid scanning; excludes startup and reconciliation"
        ),
    }


def _normalize_new_nearby_results(data):
    normalized = []
    for place in data.get("places", []) or []:
        location = place.get("location") or {}
        display_name = place.get("displayName") or {}
        primary_type = place.get("primaryType")
        normalized.append({
            "place_id": place.get("id"),
            "name": display_name.get("text") or "Unknown",
            "geometry": {
                "location": {
                    "lat": location.get("latitude"),
                    "lng": location.get("longitude"),
                }
            },
            "vicinity": place.get("formattedAddress"),
            "primaryType": primary_type,
            "types": [primary_type] if primary_type else [],
            "business_status": place.get("businessStatus"),
        })
    return normalized


def _new_nearby_request(lat, lng, radius_m):
    """Send one quota-reserved New Nearby request with bounded RPM retries."""
    global _nearby_last_request_at
    api_key = os.getenv("GOOGLE_MAPS_API_KEY") or os.getenv(
        "GOOGLE_PLACES_API_KEY")
    if not api_key:
        raise RuntimeError(
            "GOOGLE_MAPS_API_KEY or GOOGLE_PLACES_API_KEY must be configured "
            "on the backend."
        )
    if (quota_settings.cap("quota.nearby_new.daily") <= 0
            or quota_settings.cap("quota.nearby_new.monthly") <= 0):
        raise PlacesBudgetExceeded(
            "Nearby Search (New) is disabled until positive "
            "NEW_NEARBY_DAILY_CAP and NEW_NEARBY_MONTHLY_CAP limits are configured."
        )

    payload = {
        "excludedTypes": list(NEW_NEARBY_EXCLUDED_TYPES),
        "maxResultCount": NEW_NEARBY_RESULT_LIMIT,
        "locationRestriction": {
            "circle": {
                "center": {"latitude": lat, "longitude": lng},
                "radius": radius_m,
            }
        },
    }
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": api_key,
        "X-Goog-FieldMask": NEW_NEARBY_FIELD_MASK,
    }

    monthly_cap = quota_settings.cap("quota.nearby_new.monthly")
    daily_cap = quota_settings.cap("quota.nearby_new.daily")

    for attempt in range(4):
        if _detection_work_budget_reached():
            return [], False

        # Test Mode replay. Checked before the pacing sleep and the reservation
        # so a cached round costs no ledger entry and no rate-limit budget.
        if test_mode.is_enabled():
            cached, _ = test_mode.resolve_request(
                "nearby_new", NEW_NEARBY_URL, payload=payload
            )
            if cached is not None:
                calls = getattr(_places_run_state, "calls", None)
                if calls is not None:
                    calls["new_nearby_fixture"] = calls.get(
                        "new_nearby_fixture", 0) + 1
                return _normalize_new_nearby_results(cached.json()), True

        with _nearby_request_lock:
            elapsed = time.monotonic() - _nearby_last_request_at
            if _nearby_last_request_at and elapsed < 0.3:
                time.sleep(max(0.0, random.uniform(0.3, 0.5) - elapsed))
            try:
                allowed, reason = reserve_usage_slot(
                    mysql.connection,
                    "new_nearby_month",
                    "new_nearby_day",
                    monthly_cap,
                    daily_cap,
                )
            except Exception as exc:
                print(
                    f"[Run Detection] new_nearby reservation failed closed: {exc}")
                raise PlacesBudgetExceeded(
                    "Nearby Search (New) usage ledger is unavailable; no request was sent."
                ) from exc
            if not allowed:
                raise PlacesBudgetExceeded(
                    f"Nearby Search (New) {reason.replace('_', ' ')} "
                    f"(daily {daily_cap}, monthly {monthly_cap}).",
                    reason=reason,
                )
            calls = getattr(_places_run_state, "calls", None)
            if calls is not None:
                calls["new_nearby"] += 1
                query_kind = getattr(
                    _places_run_state, "query_kind", "initial")
                calls[f"new_nearby_{query_kind}"] += 1

            try:
                response = http.post(
                    NEW_NEARBY_URL, headers=headers, json=payload, timeout=10
                )
                _nearby_last_request_at = time.monotonic()
            except http.RequestException as exc:
                _record_nearby_api_error()
                print(
                    "[Run Detection] Nearby Search (New) network error "
                    f"({type(exc).__name__})"
                )
                return [], False

        if response.status_code == 429:
            body = getattr(response, "text", "") or ""
            print(
                f"[Run Detection] Nearby Search (New) HTTP 429 "
                f"attempt={attempt + 1} body={body[:2000]}"
            )
            lowered = body.lower()
            per_minute = any(marker in lowered for marker in (
                "requestsperminute", "requests_per_minute", "per minute",
                "per_minute", "rate limit", "rate_limit",
            ))
            daily_quota = any(marker in lowered for marker in (
                "resource_exhausted", "requestsperday", "per_day", "per day",
                "daily quota", "quota exceeded",
            ))
            if per_minute and attempt < 3:
                if _detection_work_budget_reached():
                    return [], False
                delay = (2 ** (attempt + 1)) * random.uniform(0.8, 1.2)
                print(
                    f"[Run Detection] New Nearby per-minute throttle; "
                    f"retry {attempt + 1}/3 after {delay:.2f}s"
                )
                time.sleep(delay)
                continue
            if daily_quota or not per_minute:
                raise PlacesBudgetExceeded(
                    "Nearby Search (New) quota exhausted by Google (HTTP 429); "
                    "stopping Places calls for this run.",
                    reason=(
                        "daily_quota_exceeded"
                        if daily_quota else "skipped_quota"
                    ),
                )
            _record_nearby_api_error()
            print("[Run Detection] New Nearby per-minute retries exhausted.")
            return [], False

        if response.status_code != 200:
            _record_nearby_api_error()
            body = getattr(response, "text", "") or ""
            print(
                f"[Run Detection] Nearby Search (New) HTTP "
                f"{response.status_code}: {body[:2000]}"
            )
            return [], False
        try:
            body = response.json()
        except (ValueError, TypeError) as exc:
            _record_nearby_api_error()
            print(
                f"[Run Detection] Nearby Search (New) invalid response: {exc}")
            return [], False
        if test_mode.is_enabled():
            test_mode.remember_response(
                "nearby_new", NEW_NEARBY_URL, None, payload, body
            )
        return _normalize_new_nearby_results(body), True
    return [], False


def _fetch_point_results_once(lat, lng, radius_m):
    if _nearby_api_mode() == "new":
        return _new_nearby_request(lat, lng, radius_m)
    return _fetch_legacy_point_results_once(lat, lng, radius_m)


def _fetch_legacy_point_results_once(lat, lng, radius_m):
    """
    Fetch all result pages for ONE grid point. Nothing is stored.
    Returns (results, complete). Raises PlacesBudgetExceeded when a limit is hit.
    """
    api_key = (
        os.getenv("GOOGLE_MAPS_API_KEY")
        or os.getenv("GOOGLE_PLACES_API_KEY")
    )
    if not api_key:
        raise RuntimeError(
            "GOOGLE_MAPS_API_KEY environment variable is not configured.")

    url = "https://maps.googleapis.com/maps/api/place/nearbysearch/json"
    params = {"location": f"{lat},{lng}", "radius": radius_m, "key": api_key}
    headers = {"User-Agent": "REVELA-Backend/1.0"}
    results, complete = [], True
    quick_mode = getattr(_places_run_state, "mode", "full") == "quick"

    while True:
        if _detection_work_budget_reached():
            return results, False
        try:
            resp = _places_get("nearby", url, params=params,
                               headers=headers, timeout=10)
            data = resp.json()
        except PlacesBudgetExceeded:
            raise
        except Exception as he:
            _record_nearby_api_error()
            print(
                f"[Run Detection] HTTP error querying point ({lat}, {lng}): "
                f"{type(he).__name__}"
            )
            return results, False

        status = data.get("status")
        err_msg = data.get("error_message") or ""
        if status == "OVER_QUERY_LIMIT":
            raise PlacesBudgetExceeded(
                f"Places API daily budget reached (Google returned {status}). Try again tomorrow.")
        if status == "REQUEST_DENIED":
            details = f": {err_msg}" if err_msg else ""
            raise RuntimeError(
                f"Google Maps Places API request was denied (REQUEST_DENIED){details}. "
                "This is not a daily quota limit. Please verify in Google Cloud Console that 'Places API' "
                "is enabled, billing is active, and the API key has no incompatible HTTP referrer restrictions."
            )
        if status not in ("OK", "ZERO_RESULTS"):
            _record_nearby_api_error()
            print(
                f"[Run Detection] Places API status: {status}, message: {err_msg}")
            return results, False

        results.extend(data.get("results", []))
        next_token = data.get("next_page_token")
        if not next_token or quick_mode:
            return results, complete
        time.sleep(2)
        params = {"pagetoken": next_token, "key": api_key}


def _adaptive_nearby_centers(lat, lng, radius_m):
    """Split a saturated search circle into four overlapping, smaller search circles."""
    lat_offset = radius_m * ADAPTIVE_CENTER_OFFSET_RATIO / 111_320.0
    lng_scale = max(0.01, math.cos(math.radians(lat)))
    lng_offset = radius_m * ADAPTIVE_CENTER_OFFSET_RATIO / \
        (111_320.0 * lng_scale)
    child_radius = radius_m * ADAPTIVE_QUERY_RADIUS_RATIO
    return [
        (lat + lat_sign * lat_offset, lng + lng_sign * lng_offset, child_radius)
        for lat_sign, lng_sign in ((-1, -1), (-1, 1), (1, -1), (1, 1))
    ]


def _nearby_circle_intersects_municipality(lat, lng, radius_m):
    center = Point(
        lng * _METERS_PER_DEGREE_LNG,
        lat * _METERS_PER_DEGREE_LAT,
    )
    return (
        _MUNICIPALITY_WITH_TOLERANCE_METERS.distance(center)
        <= radius_m + 10
    )


def _fetch_point_results(lat, lng, radius_m):
    """
    Fetch one grid cell and deduplicate overlapping parent/child results by place ID.
    Refinement is bounded; a still-saturated area is left uncheckpointed for a later scan.
    """
    query_budget = {"remaining": MAX_ADAPTIVE_QUERIES_PER_POINT}
    results, complete = _fetch_point_results_adaptive(
        lat, lng, radius_m, depth=0, query_budget=query_budget
    )
    return _deduplicate_nearby_results(results), complete


def _fetch_point_results_quick(lat, lng, radius_m):
    """Quick discovery: one lightweight request per search point without recursive refinement."""
    results, complete = _fetch_point_results_once(lat, lng, radius_m)
    return _deduplicate_nearby_results(results), complete


def _fetch_point_results_for_mode(lat, lng, radius_m, mode):
    if mode == "quick":
        return _fetch_point_results_quick(lat, lng, radius_m)
    return _fetch_point_results(lat, lng, radius_m)


def _fetch_point_results_adaptive(lat, lng, radius_m, depth, query_budget):
    if _detection_work_budget_reached():
        return [], False
    result_limit = _active_nearby_result_limit()
    previous_query_kind = getattr(_places_run_state, "query_kind", "initial")
    _places_run_state.query_kind = "adaptive" if depth else "initial"
    try:
        results, complete = _fetch_point_results_once(lat, lng, radius_m)
    finally:
        _places_run_state.query_kind = previous_query_kind
    _places_run_state.results_received = (
        getattr(_places_run_state, "results_received", 0) + len(results)
    )
    if not complete:
        return results, False
    if len(results) < result_limit:
        return results, True

    print(
        f"[Run Detection] Nearby Search saturated at {len(results)} results "
        f"(limit {result_limit}) "
        f"near ({lat:.5f}, {lng:.5f}); refining dense area"
    )
    if depth >= MAX_ADAPTIVE_DEPTH:
        return results, False

    refined = list(results)
    refined_complete = True
    for child_lat, child_lng, child_radius in _adaptive_nearby_centers(
        lat, lng, radius_m
    ):
        if not _nearby_circle_intersects_municipality(
            child_lat, child_lng, child_radius
        ):
            continue
        if query_budget["remaining"] <= 0 or _detection_work_budget_reached():
            refined_complete = False
            break
        query_budget["remaining"] -= 1
        child_results, child_complete = _fetch_point_results_adaptive(
            child_lat, child_lng, child_radius, depth + 1, query_budget
        )
        refined.extend(child_results)
        refined_complete = refined_complete and child_complete

    return refined, refined_complete


def _deduplicate_nearby_results(results):
    """Merge repeated Places records while retaining the first complete location."""
    unique = []
    places_by_id = {}
    duplicate_count = 0
    for place in results:
        place_id = place.get("place_id")
        if not place_id:
            unique.append(place)
            continue
        existing = places_by_id.get(place_id)
        if existing is None:
            places_by_id[place_id] = place
            unique.append(place)
            continue
        duplicate_count += 1
        _merge_nearby_place(existing, place)

    _places_run_state.duplicate_results = (
        getattr(_places_run_state, "duplicate_results", 0) + duplicate_count
    )
    return unique


def _merge_nearby_place(existing, duplicate):
    """Fill absent metadata from duplicate records without replacing a known location."""
    for key in ("name", "vicinity", "primaryType", "business_status"):
        current = existing.get(key)
        incoming = duplicate.get(key)
        if (current is None or current == "" or current == "Unknown") and incoming:
            existing[key] = incoming

    types = list(existing.get("types") or [])
    for place_type in duplicate.get("types") or []:
        if place_type not in types:
            types.append(place_type)
    if types:
        existing["types"] = types

    current_location = (
        (existing.get("geometry") or {}).get("location") or {}
    )
    duplicate_location = (
        (duplicate.get("geometry") or {}).get("location") or {}
    )
    if (
        (current_location.get("lat") is None or current_location.get("lng") is None)
        and duplicate_location.get("lat") is not None
        and duplicate_location.get("lng") is not None
    ):
        existing.setdefault("geometry", {})[
            "location"] = dict(duplicate_location)


def _scan_grid(process_places, progress_cb, state, detection_mode="full", points=None):
    """
    Walk the selected grid. For every point not finished in this scan cycle:
    fetch -> process_places(results inside the municipality) -> checkpoint.
    `state` is filled in as we go, so the caller still has it if PlacesBudgetExceeded is raised.
    """
    done_before = _completed_points_this_cycle()
    if points is None:
        points = _detection_points_for_mode(detection_mode)
    fingerprint = _checkpoint_configuration_fingerprint(detection_mode)
    state["total_points"] = len(points)
    state["detection_mode"] = detection_mode

    for idx, (lat, lng) in enumerate(points):
        if is_cancelled("run_detection"):
            break
        if _detection_work_budget_reached():
            state["work_budget_stop"] = True
            break
        key = _checkpoint_point_key(lat, lng, fingerprint)
        if key in done_before:
            state["skipped_points"] += 1
            continue

        if progress_cb:
            progress_cb(
                idx,
                len(points),
                lat,
                lng,
                mode=detection_mode,
            )

        errors_before_query = getattr(_places_run_state, "api_errors", 0)
        results, complete = _fetch_point_results_for_mode(
            lat, lng, _detection_radius_m(), detection_mode
        )
        api_error_during_query = (
            getattr(_places_run_state, "api_errors", 0) > errors_before_query
        )
        if detection_mode == "quick":
            history = getattr(_places_run_state, "quick_scan_history", {})
            history[(round(lat, 5), round(lng, 5))] = history.get(
                (round(lat, 5), round(lng, 5)), 0) + 1
            _places_run_state.quick_scan_history = history
        if not complete:
            state["incomplete_points"] += 1

        inside = []
        for p in results:
            loc = (p.get("geometry") or {}).get("location") or {}
            p_lat, p_lng = loc.get("lat"), loc.get("lng")
            if p_lat is None or p_lng is None:
                continue
            if _within_municipality(p_lat, p_lng):
                inside.append(p)
            else:
                state["outside"] += 1

        processing_complete = process_places(inside) is not False
        if not processing_complete:
            if complete:
                state["incomplete_points"] += 1
            state["work_budget_stop"] = True
            break
        if api_error_during_query:
            state["api_error_stop"] = True
            break
        if complete:
            _mark_point_done(key)
            state["done_keys"].append(key)
        if _detection_work_budget_reached():
            state["work_budget_stop"] = True
            break


def _grid_scan_has_terminal_gaps(state):
    attempted_points = (
        state["skipped_points"]
        + len(state["done_keys"])
        + state["incomplete_points"]
    )
    return (
        attempted_points >= state["total_points"]
        and state["incomplete_points"] > 0
        and not state.get("api_error_stop")
        and not state.get("work_budget_stop")
    )


# ── Registry loader ───────────────────────────────────────────────────────────

def _load_registry():
    """Load all official registry entries into memory for cross-referencing."""
    cursor = mysql.connection.cursor()
    cursor.execute("""
        SELECT r.businessID, r.barangayID, r.businessName, r.applicationStatus,
               r.businessType AS businessType,
               r.lineOfBusiness AS businessLine,
               r.businessAddress AS businessAddress,
               r.placeID, r.coordSource, r.matchStatus,
               COALESCE(r.latitude, g.latitude) AS latitude,
               COALESCE(r.longitude, g.longitude) AS longitude
        FROM official_registry r
        LEFT JOIN LATERAL (
            SELECT latitude, longitude
            FROM geospatial_logs
            WHERE flagColor = 'Green'
              AND latitude IS NOT NULL
              AND ((businessID IS NOT NULL AND businessID = r.businessID) OR (businessID IS NULL AND detectedName = r.businessName AND barangayID = r.barangayID))
            ORDER BY (businessID = r.businessID) DESC
            LIMIT 1
        ) g ON TRUE
    """)
    rows = cursor.fetchall()
    cursor.close()
    return rows


def _log_detection_summary(
    run_id, state, counters, stop_reason=None, elapsed=None
):
    calls = getattr(_places_run_state, "calls", {})
    state["api_errors"] = getattr(_places_run_state, "api_errors", 0)
    state["work_budget_reason"] = getattr(
        _places_run_state, "work_budget_reason", None
    )
    try:
        usage = get_places_usage_today()
    except Exception as exc:
        print(
            f"[Run Detection] run={run_id} Places usage summary unavailable "
            f"({type(exc).__name__})"
        )
        return None
    print(
        f"[Run Detection] run={run_id} mode={_nearby_api_mode()} "
        f"matched={counters['matched']} no_match={counters['no_match']} "
        f"new_flags={counters['new_flags']} api_error={state['api_errors']} "
        f"quota_stop={stop_reason or 'none'} "
        f"api_error_stop={state.get('api_error_stop', False)} "
        f"work_budget_stop={state.get('work_budget_stop', False)} "
        f"work_budget_reason={state['work_budget_reason'] or 'none'} "
        f"elapsed_seconds={(elapsed or {}).get('elapsed_seconds', 0)} "
        f"scan_elapsed_seconds={(elapsed or {}).get('scan_elapsed_seconds', 0)} "
        f"grid_completed={state['skipped_points'] + len(state['done_keys'])}/"
        f"{state['total_points']} grid_incomplete={state['incomplete_points']} "
        f"results={getattr(_places_run_state, 'results_received', 0)} "
        f"duplicates={getattr(_places_run_state, 'duplicate_results', 0) + counters.get('duplicates', 0)} "
        f"non_business={counters.get('non_business', 0)} "
        f"closed_results={counters.get('closed_results', 0)} "
        f"review={counters.get('review', 0)} "
        f"initial_requests="
        f"{calls.get('legacy_nearby_initial', 0) + calls.get('new_nearby_initial', 0)} "
        f"adaptive_requests="
        f"{calls.get('legacy_nearby_adaptive', 0) + calls.get('new_nearby_adaptive', 0)} "
        f"calls_this_run={calls} "
        f"legacy_nearby_day/month="
        f"{usage['nearby_search_legacy']['used_today']}/"
        f"{usage['nearby_search_legacy']['used_month']} "
        f"new_nearby_day/month="
        f"{usage['nearby_search_new']['used_today']}/"
        f"{usage['nearby_search_new']['used_month']} "
        f"text_search_day/month="
        f"{usage['text_search_day']['used']}/"
        f"{usage['text_search_month']['used']} "
        f"details_day/month="
        f"{usage['place_details_day']['used']}/"
        f"{usage['place_details_month']['used']} "
        f"geocode_day/month={usage['geocode']['used']}/"
        f"{usage['geocode']['used_month']}"
    )
    return usage


# ── 20-meter threshold check ──────────────────────────────────────────────────

def _find_nearest(poi_lat, poi_lng, registry):
    """
    For a given POI, find the nearest OFFICIAL_REGISTRY entry.
    Returns (nearest_row, distance_in_meters).
    """
    nearest = None
    nearest_dist = float("inf")

    for entry in registry:
        if not entry["latitude"] or not entry["longitude"]:
            continue
        dist = geodesic(
            (poi_lat, poi_lng),
            (float(entry["latitude"]), float(entry["longitude"]))
        ).meters

        if dist < nearest_dist:
            nearest_dist = dist
            nearest = entry

    return nearest, nearest_dist


# ── Barangay resolver ─────────────────────────────────────────────────────────

def _get_barangay_id_by_coords(
    lat, lng, barangay_rows=None, fallback_rows=None
):
    """
    Find which barangayID a POI belongs to by checking GeoJSON boundaries.
    Falls back to proximity to existing registry entries if not found in any polygon.
    """
    pt = Point(lng, lat)
    matched_geojson_name = None
    for name, poly in _BARANGAY_POLYGONS.items():
        if poly.contains(pt):
            matched_geojson_name = name
            break

    if not matched_geojson_name:
        for name, poly in _BARANGAY_POLYGONS.items():
            if poly.buffer(0.001).contains(pt):
                matched_geojson_name = name
                break

    if matched_geojson_name:
        if barangay_rows is None:
            cursor = mysql.connection.cursor()
            try:
                cursor.execute(
                    "SELECT barangayID, barangayName FROM barangays")
                barangay_rows = cursor.fetchall()
            finally:
                cursor.close()

        mapping = {
            "District I (Pob.)": "Barangay I",
            "District II (Pob.)": "Barangay II",
            "District III (Pob.)": "Barangay III",
            "District IV (Pob.)": "Barangay IV",
            "Barangay II-A (Pob.)": "Barangay II-A",
            "Lumang Lipa": "Barangay Lumanglipa"
        }

        for b in barangay_rows:
            b_name = b['barangayName']
            target_name = mapping.get(matched_geojson_name)

            if target_name and target_name == b_name:
                return b["barangayID"]

            if not target_name and matched_geojson_name.lower() in b_name.lower():
                return b["barangayID"]

    # Fallback to proximity
    if fallback_rows is None:
        cursor = mysql.connection.cursor()
        try:
            cursor.execute("""
                SELECT barangayID, latitude, longitude
                FROM official_registry
                WHERE latitude IS NOT NULL AND longitude IS NOT NULL
            """)
            fallback_rows = cursor.fetchall()
        finally:
            cursor.close()

    if not fallback_rows:
        return 1

    nearest_id = 1
    nearest_dist = float("inf")
    for row in fallback_rows:
        dist = geodesic(
            (lat, lng),
            (float(row["latitude"]), float(row["longitude"]))
        ).meters
        if dist < nearest_dist:
            nearest_dist = dist
            nearest_id = row["barangayID"]

    return nearest_id


# ── Already flagged check ─────────────────────────────────────────────────────

def _already_flagged(place_id):
    """Return True if this place_id already has any flag in GEOSPATIAL_LOGS."""
    cursor = mysql.connection.cursor()
    cursor.execute("""
        SELECT logID FROM geospatial_logs
        WHERE placeID = %s
        LIMIT 1
    """, (place_id,))
    row = cursor.fetchone()
    cursor.close()
    return row is not None


def _load_existing_flags(place_ids):
    """Load existing flags for a bounded POI batch with one indexed lookup."""
    if not place_ids:
        return {}
    place_ids = list(dict.fromkeys(place_ids))
    placeholders = ", ".join(["%s"] * len(place_ids))
    cursor = mysql.connection.cursor()
    try:
        _detection_execute(cursor, f"""
            SELECT g.logID, g.placeID, g.flagColor,
                   EXISTS (
                       SELECT 1
                       FROM inspection_reports ir
                       WHERE ir.targetType = 'geospatial_log'
                         AND ir.targetID = g.logID
                         AND ir.verificationStatus = 'Verified'
                         AND ir.inspectionResult = 'Orange'
                   ) AS has_verified_orange
            FROM geospatial_logs g
            WHERE g.placeID IN ({placeholders})
            ORDER BY g.logID
        """, tuple(place_ids))
        rows = cursor.fetchall()
    finally:
        cursor.close()
    existing = {}
    for row in rows:
        existing.setdefault(row["placeID"], row)
    return existing


# ── Insert Red Flag ───────────────────────────────────────────────────────────

def _insert_red_flag(
    place_id, place_name, lat, lng, barangay_id, address=None,
    poi_types=(), commit=True,
):
    serialized_types = json.dumps(
        sorted(set(poi_types))) if poi_types else None
    cursor = mysql.connection.cursor()
    _columns, _values, _params = with_source(
        cursor,
        """(barangayID, reportID, detectedName, latitude, longitude,
             flagColor, placeID, nearestLandmark, placeTypes)""",
        "(%s, NULL, %s, %s, %s, 'Red', %s, %s, %s)",
        (barangay_id, place_name, lat, lng, place_id, address,
         serialized_types),
        # Found by a scan, with no registry link.
        SOURCE_DETECTION,
    )
    _detection_execute(
        cursor, f"INSERT INTO geospatial_logs {_columns} VALUES {_values}",
        _params)
    flag_id = cursor.lastrowid
    if commit:
        _detection_commit()
    cursor.close()
    return flag_id


def _is_non_business_place(place):
    """
    Return True if this POI is non-commercial (religious, public school, government,
    cemetery, park, infrastructure, residential).
    Such places must NEVER be flagged as unregistered commercial businesses.
    """
    # 1. Closed permanently
    types = set(place.get("types") or [])
    if place.get("primaryType"):
        types.add(place["primaryType"])

    # Non-business Google types
    disqualifying_types = {
        # Religious
        "place_of_worship", "church", "mosque", "hindu_temple", "synagogue",
        # Education / Schools
        "school", "primary_school", "secondary_school", "university",
        # Government & Municipal infrastructure
        "local_government_office", "city_hall", "courthouse", "embassy",
        "fire_station", "police", "post_office", "library",
        # Public parks, landmarks, cemetery
        "cemetery", "park", "natural_feature",
        # Transit
        "transit_station", "bus_station", "subway_station", "train_station", "light_rail_station",
        # Geographic / Boundaries / Residential
        "political", "neighborhood", "sublocality", "sublocality_level_1", "route", "locality"
    }

    if types.intersection(disqualifying_types):
        return True

    # Name heuristics for local public/community facilities
    name_lower = (place.get("name") or "").lower()
    non_business_keywords = [
        "barangay hall", "brgy hall", "covered court", "basketball court",
        "elementary school", "national high school", "integrated school",
        "parish church", "catholic church", "chapel", "kapilya", "iglesia ni cristo",
        "health center", "rural health", "police station", "municipal hall",
        "memorial park", "cemetery", "santo entiero", "waiting shed",
        "purok outpost", "tanod outpost"
    ]
    if any(kw in name_lower for kw in non_business_keywords):
        return True

    return False


# ── Main detection runner ─────────────────────────────────────────────────────


def run_detection(user_id=None, mode="quick"):
    if not _run_detection_lock.acquire(blocking=False):
        return None, "A detection scan is already in progress."
    try:
        return _run_detection_cycle(user_id=user_id, mode=mode)
    finally:
        _run_detection_lock.release()


def _run_detection_cycle(user_id=None, mode="quick"):
    """
    Detection cycle, resumable across days.

    Mode values:
      - quick: limited distributed discovery across Mataasnakahoy, optimized for a faster first pass
      - full: existing exhaustive municipality grid scan
    """
    if mode not in RUN_DETECTION_MODES:
        mode = "quick"
    request_started_at = time.monotonic()
    set_cancel("run_detection", False)
    _places_run_state.mode = mode
    _places_run_state.quick_scan_history = getattr(
        _places_run_state, "quick_scan_history", {})
    _places_run_state.calls = {
        "legacy_nearby": 0,
        "legacy_nearby_initial": 0,
        "legacy_nearby_adaptive": 0,
        "new_nearby": 0,
        "new_nearby_initial": 0,
        "new_nearby_adaptive": 0,
    }
    _places_run_state.api_errors = 0
    _places_run_state.results_received = 0
    _places_run_state.duplicate_results = 0
    _places_run_state.query_kind = "initial"
    _places_run_state.started_at = None
    _places_run_state.db_metrics_active = False
    _places_run_state.db_queries = 0
    _places_run_state.db_commits = 0
    _places_run_state.registry_match_time_seconds = 0.0
    _places_run_state.work_budget_exhausted = False
    _places_run_state.work_budget_reason = None

    quota_info = get_detection_quota_info()
    if quota_info.get("is_limit_reached"):
        limit = quota_info.get(
            "monthly_limit", API_QUOTA_CONFIG.run_detection_monthly_scans
        )
        return None, f"Monthly detection limit reached ({limit}/{limit} scans used for this month). Detection scans can only be run {limit} times a month."

    # Guard: check if official_registry has any records
    cursor = mysql.connection.cursor()
    try:
        cursor.execute("SELECT COUNT(*) AS total FROM official_registry")
        row = cursor.fetchone()
        reg_count = (row.get("total") if isinstance(
            row, dict) else row[0]) if row else 0
        if reg_count == 0:
            return None, "Cannot run detection: The official business registry is empty. Please import official business records first so REVELA has a baseline to cross-reference against."
    finally:
        cursor.close()

    run_id = create_detection_run(user_id)
    state = {
        "done_keys": [], "total_points": 0, "skipped_points": 0,
        "outside": 0, "incomplete_points": 0, "api_errors": 0,
        "api_error_stop": False,
    }
    inserted_flag_ids = []
    seen_place_ids = set()
    counters = {
        "new_flags": 0, "total_checked": 0, "matched": 0, "no_match": 0,
        "duplicates": 0, "non_business": 0, "closed_results": 0, "review": 0,
        "unique_in_bound_pois": 0,
        "actionable_business_candidates": 0,
    }

    try:
        def progress_callback(idx, total_steps, lat, lng, mode=None):
            mode_name = (mode or getattr(
                _places_run_state, "mode", "quick")).title()
            prefix = "Quick Discovery" if (mode or getattr(
                _places_run_state, "mode", "quick")) == "quick" else "Full Coverage"
            percentage = int((idx / max(total_steps, 1)) * 95)
            hub.publish_to_admins({
                "type": "detection_progress",
                "stage": "scanning",
                "current_step": idx + 1,
                "total_steps": total_steps,
                "percentage": percentage,
                "status": f"{prefix}: scanning area ({lat:.4f}, {lng:.4f}) — step {idx + 1} of {total_steps}..."
            })

        hub.publish_to_admins({
            "type": "detection_progress", "stage": "matching", "percentage": 1,
            "status": "Loading official business registry database..."
        })
        _ensure_place_types_column()
        registry = _load_registry()
        rejected_place_pairs = _load_rejected_place_pairs()
        registry_by_place_id = {}
        for entry in registry:
            place_id_value = entry.get("placeID")
            if place_id_value:
                registry_by_place_id.setdefault(
                    place_id_value, []).append(entry)
        registry_match_index = _RegistryMatchIndex(registry)
        lookup_cursor = mysql.connection.cursor()
        try:
            lookup_cursor.execute(
                "SELECT barangayID, barangayName FROM barangays")
            barangay_rows = lookup_cursor.fetchall()
        finally:
            lookup_cursor.close()
        try:
            reconcile_existing_flags(silent=True)
        except Exception as re_err:
            print(f"[Run Detection] Reconcile error: {re_err}")

        def process_places(places):
            pending_place_ids = {
                place.get("place_id")
                for place in places
                if place.get("place_id")
                and place.get("place_id") not in seen_place_ids
            }
            existing_flags = _load_existing_flags(pending_place_ids)
            non_business_red_ids = []
            writes_pending = False
            processing_complete = True
            for place in places:
                if _detection_result_processing_stopped():
                    processing_complete = False
                    break
                place_id = place.get("place_id")
                if not place_id:
                    continue
                if place_id in seen_place_ids:
                    counters["duplicates"] += 1
                    continue          # adjacent grid cells can return the same place
                seen_place_ids.add(place_id)
                counters["total_checked"] += 1

                place_name = place.get("name", "Unknown")
                loc = (place.get("geometry") or {}).get("location") or {}
                lat, lng = loc.get("lat"), loc.get("lng")
                address = place.get("vicinity")
                if not lat or not lng:
                    continue
                counters["unique_in_bound_pois"] += 1
                if place.get("business_status") in (
                    "CLOSED_PERMANENTLY", "CLOSED_TEMPORARILY"
                ):
                    counters["closed_results"] += 1

                existing_flag = existing_flags.get(place_id)

                if existing_flag and existing_flag["flagColor"] in ("Green", "Orange", "Black", "Purple"):
                    continue

                barangay_id = _get_barangay_id_by_coords(
                    lat, lng, barangay_rows, registry
                )

                if _is_non_business_place(place):
                    counters["non_business"] += 1
                    if existing_flag and existing_flag["flagColor"] == "Red":
                        non_business_red_ids.append(existing_flag["logID"])
                    continue
                counters["actionable_business_candidates"] += 1

                matching_by_place = _registry_entry_for_place_id(
                    place_id, registry_by_place_id, rejected_place_pairs
                )
                p_types = place.get("types") or []
                if place.get("primaryType"):
                    p_types = list(p_types) + [place.get("primaryType")]
                poi_types = tuple(sorted(set(p_types)))

                if matching_by_place:
                    nearest = matching_by_place
                    dist = 0.0
                    sim_score = 1.0
                    match_status = "auto"
                else:
                    matching_started_at = time.perf_counter()
                    try:
                        nearest, dist, sim_score, match_status = _match_poi_to_registry(
                            place_name, lat, lng, registry,
                            poi_barangay_id=barangay_id,
                            poi_types=poi_types,
                            poi_address=address or "",
                            registry_index=registry_match_index,
                            place_id=place_id,
                            rejected_place_pairs=rejected_place_pairs,
                        )
                    finally:
                        _places_run_state.registry_match_time_seconds += (
                            time.perf_counter() - matching_started_at
                        )

                if nearest is None or match_status == "no_match":
                    # Guard: Detection skips creating a Red flag for any Google POI whose
                    # placeID is already held by an official registry business
                    if place_id in registry_by_place_id:
                        counters["matched"] += 1
                        continue

                    counters["no_match"] += 1
                    if not existing_flag:
                        flag_id = _insert_red_flag(
                            place_id, place_name, lat, lng, barangay_id, address,
                            poi_types=poi_types,
                            commit=False,
                        )
                        inserted_flag_ids.append(flag_id)
                        counters["new_flags"] += 1
                        writes_pending = True
                else:
                    counters["matched"] += 1
                    target_color = _detection_status_color(
                        nearest.get("applicationStatus")
                    )
                    if match_status == "review":
                        target_color = "Yellow"
                        counters["review"] += 1
                    elif (
                        nearest.get("applicationStatus") == "Expired"
                        and existing_flag
                        and existing_flag.get("has_verified_orange")
                    ):
                        target_color = "Orange"

                    target_barangay_id = nearest.get(
                        "barangayID") or barangay_id
                    _match_registry_to_google(
                        place_id, nearest["businessID"], nearest["businessName"],
                        target_color=target_color, lat=lat, lng=lng, barangay_id=target_barangay_id,
                        match_score=sim_score, match_status=match_status,
                        poi_types=poi_types,
                        poi_address=address,
                        commit=False,
                        rejected_place_pairs=rejected_place_pairs,
                    )
                    writes_pending = True

            if non_business_red_ids:
                placeholders = ", ".join(["%s"] * len(non_business_red_ids))
                cursor = mysql.connection.cursor()
                try:
                    _detection_execute(cursor,
                                       "DELETE FROM geospatial_logs "
                                       f"WHERE logID IN ({placeholders})",
                                       tuple(non_business_red_ids),
                                       )
                    writes_pending = True
                finally:
                    cursor.close()
            if writes_pending:
                _detection_commit()
            return processing_complete

        _places_run_state.started_at = time.monotonic()
        points = _detection_points_for_mode(mode, barangay_rows)
        _places_run_state.db_metrics_active = True
        try:
            _scan_grid(process_places, progress_callback, state,
                       detection_mode=mode, points=points)
        finally:
            _places_run_state.db_metrics_active = False

        if is_cancelled("run_detection"):
            # Keep newly inserted Red flags and checkpoints in sync on cancellation.
            _cleanup_cancelled_detection(
                inserted_flag_ids, state["done_keys"])
            update_detection_run_status(run_id, "cancelled")
            hub.publish_to_admins({
                "type": "detection_progress", "stage": "completed", "percentage": 100,
                "status": (
                    "Detection cancelled. Newly inserted Red flags from this scan "
                    "were removed; committed updates to existing matches or "
                    "reconciliation may remain."
                )
            })
            return None, (
                "Detection cancelled. Newly inserted Red flags were removed; "
                "committed updates to existing matches or reconciliation may remain."
            )

        new_flags = counters["new_flags"]
        total_checked = counters["total_checked"]
        done_total = state["skipped_points"] + len(state["done_keys"])
        terminal_gaps = _grid_scan_has_terminal_gaps(state)
        scan_terminal = done_total >= state["total_points"] or terminal_gaps
        elapsed = _detection_elapsed_metrics(request_started_at)
        places_usage = _log_detection_summary(
            run_id, state, counters, elapsed=elapsed
        )
        print(
            f"[Run Detection] grid summary completed={done_total}/{state['total_points']} "
            f"incomplete_dense_or_failed_points={state['incomplete_points']} "
            f"outside_boundary_results={state['outside']}"
        )

        if terminal_gaps:
            update_detection_run_status(
                run_id, "completed_with_gaps",
                new_flags=new_flags, total_checked=total_checked)
            msg = (
                f"Scan reached all {state['total_points']} grid points, but "
                f"{state['incomplete_points']} dense cells remained saturated. "
                f"{new_flags} new flags were recorded; this attempt counts toward "
                "the monthly scan limit."
            )
            hub.publish_to_admins({
                "type": "detection_progress", "stage": "completed",
                "percentage": 100, "status": msg
            })
        elif not scan_terminal:
            update_detection_run_status(
                run_id, "partial", new_flags=new_flags, total_checked=total_checked)
            msg = (
                f"Scan partial: {done_total} of {state['total_points']} grid points completed. "
                f"{new_flags} new flags recorded. "
                f"{state['incomplete_points']} dense or failed points need another scan."
                + (
                    " Places API returned an error; remaining cells were not requested."
                    if state["api_error_stop"] else
                    " Run again later to finish."
                )
            )
            if state.get("work_budget_stop"):
                msg = (
                    f"Scan paused at its work limit: {done_total} of "
                    f"{state['total_points']} grid points completed. "
                    f"{new_flags} new flags recorded; run again to continue."
                )
            hub.publish_to_admins({
                "type": "detection_progress", "stage": "completed", "percentage": 100,
                "status": msg
            })
        else:
            update_detection_run_status(
                run_id, "completed", new_flags=new_flags, total_checked=total_checked)
            hub.publish_to_admins({
                "type": "detection_progress", "stage": "completed", "percentage": 100,
                "status": f"Scan complete! Discovered {new_flags} new unregistered business{'' if new_flags == 1 else 'es'}."
            })

        return {
            "status": (
                "completed_with_gaps" if terminal_gaps else
                "partial" if not scan_terminal else "completed"
            ),
            "new_flags":        new_flags,
            "total_checked":    total_checked,
            "completed_points": done_total,
            "attempted_points": (
                done_total + state["incomplete_points"]
            ),
            "total_points":     state["total_points"],
            "outside_boundary": state["outside"],
            "incomplete_points": state["incomplete_points"],
            "api_errors": getattr(_places_run_state, "api_errors", 0),
            "run_summary": {
                "detection_mode": mode,
                "results_received": getattr(_places_run_state, "results_received", 0),
                "duplicates": (
                    getattr(_places_run_state, "duplicate_results", 0)
                    + counters["duplicates"]
                ),
                "non_business": counters["non_business"],
                "closed_results": counters["closed_results"],
                "matched": counters["matched"],
                "no_match": counters["no_match"],
                "review": counters["review"],
                "new_flags": counters["new_flags"],
                "initial_requests": (
                    _places_run_state.calls["legacy_nearby_initial"]
                    + _places_run_state.calls["new_nearby_initial"]
                ),
                "adaptive_requests": (
                    _places_run_state.calls["legacy_nearby_adaptive"]
                    + _places_run_state.calls["new_nearby_adaptive"]
                ),
                "api_errors": getattr(_places_run_state, "api_errors", 0),
                "api_error_stop": state["api_error_stop"],
                "work_budget_stop": state.get("work_budget_stop", False),
                "work_budget_reason": getattr(
                    _places_run_state, "work_budget_reason", None
                ),
                "work_budget_max_seconds": RUN_DETECTION_MAX_SECONDS,
                "work_budget_max_requests": RUN_DETECTION_MAX_REQUESTS,
                **elapsed,
                **_detection_performance_metrics(
                    counters, registry, registry_match_index
                ),
                "quota_stop": None,
            },
            "quota_stop": None,
            "quota":            get_detection_quota_info(),
            "places_usage":     places_usage,
        }, None

    except PlacesBudgetExceeded as be:
        mysql.connection.rollback()
        done_total = state["skipped_points"] + len(state["done_keys"])
        places_usage = _log_detection_summary(
            run_id, state, counters, stop_reason=str(be),
            elapsed=_detection_elapsed_metrics(request_started_at),
        )
        update_detection_run_status(
            run_id, "partial",
            new_flags=counters["new_flags"], total_checked=counters["total_checked"])
        msg = (f"{be} Progress is saved: {done_total} of {state['total_points']} grid points are done, "
               f"{counters['new_flags']} new flag(s) recorded in this run. Run Detection again later to continue "
               "where it stopped. This did not use one of your monthly scans.")
        hub.publish_to_admins({
            "type": "detection_progress", "stage": "completed", "percentage": 100, "status": msg
        })
        return {
            "status": be.reason,
            "quota_reason": be.reason,
            "run_summary": {
                "detection_mode": mode,
                "results_received": getattr(_places_run_state, "results_received", 0),
                "duplicates": (
                    getattr(_places_run_state, "duplicate_results", 0)
                    + counters["duplicates"]
                ),
                "non_business": counters["non_business"],
                "closed_results": counters["closed_results"],
                "matched": counters["matched"],
                "no_match": counters["no_match"],
                "review": counters["review"],
                "new_flags": counters["new_flags"],
                "initial_requests": (
                    _places_run_state.calls["legacy_nearby_initial"]
                    + _places_run_state.calls["new_nearby_initial"]
                ),
                "adaptive_requests": (
                    _places_run_state.calls["legacy_nearby_adaptive"]
                    + _places_run_state.calls["new_nearby_adaptive"]
                ),
                "api_errors": getattr(_places_run_state, "api_errors", 0),
                "api_error_stop": state["api_error_stop"],
                "work_budget_stop": state.get("work_budget_stop", False),
                "work_budget_reason": getattr(
                    _places_run_state, "work_budget_reason", None
                ),
                "work_budget_max_seconds": RUN_DETECTION_MAX_SECONDS,
                "work_budget_max_requests": RUN_DETECTION_MAX_REQUESTS,
                **_detection_elapsed_metrics(request_started_at),
                **_detection_performance_metrics(
                    counters, registry, registry_match_index
                ),
                "quota_stop": be.reason,
            },
            "places_usage": places_usage,
            "completed_points": done_total,
            "attempted_points": (
                done_total + state["incomplete_points"]
            ),
            "total_points": state["total_points"],
        }, msg

    except Exception as e:
        mysql.connection.rollback()
        elapsed = _detection_elapsed_metrics(request_started_at)
        print(
            f"[Run Detection] run={run_id} mode={mode} "
            f"failed ({type(e).__name__}) "
            f"error={e!r} "
            f"elapsed_seconds={elapsed['elapsed_seconds']} "
            f"scan_elapsed_seconds={elapsed['scan_elapsed_seconds']}"
        )
        traceback.print_exc()
        update_detection_run_status(run_id, "failed")
        return None, str(e)


# ── Get all flags ─────────────────────────────────────────────────────────────

#: The label the Map used to infer for a pin, kept verbatim - same rules, same
#: columns - as the fallback for databases without geospatial_logs.source.
#:
#: It is expressed in the NEW vocabulary rather than the old one. The old
#: names (registry_only, registry_and_maps, maps_only, inspector_reported)
#: described a guess; the new ones describe the same guess in the same
#: vocabulary the stored column uses. Emitting both would leave the frontend
#: carrying two vocabularies forever.
#:
#: 'registry' and 'registry_detected' here are guesses about a registry-only
#: business; 'detection' and 'manual' are guesses about a pin. Only the stored
#: column knows for sure, which is why it wins whenever it exists.
_OLD_MAP_FLAG_SOURCE = """CASE
        WHEN g.reportedByUserID IS NOT NULL AND g.flagColor != 'Green' THEN 'manual'
        WHEN g.placeID IS NOT NULL AND r.businessID IS NOT NULL THEN 'registry_detected'
        WHEN g.placeID IS NULL AND r.businessID IS NOT NULL THEN 'registry'
        ELSE 'detection'
    END"""


def _registry_row_flag_color_sql(alias="r", *, ladder=False):
    """Flag colour for an official_registry row that has no geospatial_log pin.

    get_flags UNIONs two sources. The geospatial_logs branch can use
    _effective_flag_color_sql, which is pin-centric. A registry-only business
    has no pin, so it needs its own expression - but it must agree with the
    shared rule, including the Black-lock and Orange-warning arms, or the same
    business would render one colour from the pin branch and another from the
    registry branch.

    ELSE 'Yellow' matches status_to_color()'s unknown-status fallback.
    """
    return registry_row_color_sql(alias, ladder=ladder)


def get_flags(color=None, barangay_id=None, page=1, per_page=50, reported_by_user_id=None):
    """
    Return paginated flag entries with optional filters.

    Results are a UNION of two sources:
      1. geospatial_logs  — POIs detected via Google Places scan or reported by inspectors.
      2. official_registry — Businesses with stored coordinates that have NO matching
         geospatial_log yet.  These appear as "virtual" flags so that all 515+ registry
         businesses with GPS coordinates are visible on the map regardless of whether a
         detection scan has run.  Their flagColor is derived from applicationStatus:
           Active  → Green
           Expired → Red
           Revoked → Black
           Closed  → Purple
           Pending → Yellow  (anything else → Yellow)
    """
    try:
        cursor = mysql.connection.cursor()

        # One shared colour expression per branch, used for both the filter and
        # the rendered value. ladder_columns_available() is False until the
        # ladder migration has run, which leaves this query byte-identical to
        # before on a database without warningLevel / blackLocked.
        ladder = ladder_columns_available(cursor)
        effective_flag_color = _effective_flag_color_sql("g", ladder=ladder)
        registry_flag_color = _registry_row_flag_color_sql("r", ladder=ladder)
        unlock = "0"

        # ── Build per-source WHERE fragments ────────────────────────────────────
        # Filters that apply to the geospatial_logs branch
        geo_conditions = []
        geo_params = []
        from api.registry.inspection_link import confirmed_pin_column_available
        if confirmed_pin_column_available(cursor):
            geo_conditions.append("""NOT EXISTS (
                SELECT 1 FROM official_registry canonical
                WHERE canonical.businessID = g.businessID
                  AND canonical.confirmedLogID IS NOT NULL
                  AND canonical.confirmedLogID <> g.logID)""")

        # Filters that apply to the registry-only branch
        reg_conditions = [
            # Exclude registry rows that already have a geospatial_log (avoids duplicates)
            """
            NOT EXISTS (
                SELECT 1 FROM geospatial_logs g2
                WHERE (g2.businessID IS NOT NULL AND g2.businessID = r.businessID)
                   OR (g2.placeID IS NOT NULL AND g2.placeID = r.placeID
                       AND (g2.businessID IS NULL OR g2.businessID = r.businessID))
                   OR (g2.businessID IS NULL AND g2.detectedName = r.businessName AND g2.barangayID = r.barangayID)
            )
            """,
        ]
        reg_params = []

        # reporter filter only applies to geospatial_logs (registry has no reporter)
        if reported_by_user_id:
            geo_conditions.append("g.reportedByUserID = %s")
            geo_params.append(reported_by_user_id)
            # When filtering by reporter, registry-only rows should be excluded
            reg_conditions.append("FALSE")

        if color:
            # Filter on the same derived colour the rows below are rendered
            # with. The per-colour branching this replaces compared
            # g.flagColor and applicationStatus directly, so filtering by a
            # colour could return rows rendered in a different colour, and it
            # hard-coded the retired "Orange only when Expired" rule. Both
            # branches now go through the shared builder, so the Map filter
            # and the Map pin cannot disagree.
            geo_conditions.append(f"({effective_flag_color}) = %s")
            geo_params.append(color)
            reg_conditions.append(f"({registry_flag_color}) = %s")
            reg_params.append(color)

        if barangay_id:
            geo_conditions.append("g.barangayID = %s")
            geo_params.append(barangay_id)
            reg_conditions.append("r.barangayID = %s")
            reg_params.append(barangay_id)

        geo_where = ("WHERE " + " AND ".join(geo_conditions)
                     ) if geo_conditions else ""
        # always has at least 3 conditions
        reg_where = "WHERE " + " AND ".join(reg_conditions)

        offset = (page - 1) * per_page

        # ── Count across both branches ───────────────────────────────────────────
        count_sql = f"""
            SELECT COUNT(*) AS total FROM (
                SELECT g.logID
                FROM geospatial_logs g
                {geo_where}

                UNION ALL

                SELECT -CAST(2147483648 + r.registryOrdinal AS SIGNED) AS logID
                FROM (
                    SELECT official_registry.*,
                           ROW_NUMBER() OVER (ORDER BY businessID) AS registryOrdinal
                    FROM official_registry
                ) r
                {reg_where}
            ) AS combined
        """
        cursor.execute(count_sql, geo_params + reg_params)
        total = cursor.fetchone()["total"]

        # ── Fetch combined rows ──────────────────────────────────────────────────
        fetch_sql = f"""
            SELECT * FROM (

                -- Branch 1: existing geospatial_logs entries
                SELECT
                    g.logID,
                    COALESCE(g.businessID, r.businessID) AS businessID,
                    g.detectedName,
                    COALESCE(g.latitude, r.latitude) AS latitude,
                    COALESCE(g.longitude, r.longitude) AS longitude,
                    {effective_flag_color} AS flagColor,
                    g.detectedDate,
                    g.nearestLandmark,
                    g.notes,
                    g.placeID,
                    g.reportedByUserID,
                    g.noticeLevel,
                    {unlock} AS blackDispatchUnlocked,
                    b.barangayID,
                    b.barangayName,
                    r.businessSize,
                    COALESCE(g.nearestLandmark, r.businessAddress) AS resolvedAddress,
                    {_flag_source_sql("g", _OLD_MAP_FLAG_SOURCE, cursor)}
                        AS flagSource,
                    {origin_source_sql("g", cursor)} AS originSource,
                    {registry_link_sql("g")} AS registryLinked,
                    {verified_green_at_sql("g", ladder=ladder)} AS verifiedGreenAt,
                    (
                        SELECT verificationStatus
                        FROM inspection_reports
                        WHERE targetID = g.logID
                          AND targetType = 'geospatial_log'
                        ORDER BY irTimestamp DESC
                        LIMIT 1
                    ) AS verificationStatus,
                    r.matchStatus,
                    r.coordSource,
                    r.matchScore
                FROM geospatial_logs g
                LEFT JOIN barangays b ON g.barangayID = b.barangayID
                LEFT JOIN LATERAL (
                    SELECT businessID, businessSize, businessAddress, latitude, longitude, applicationStatus,
                           matchStatus, coordSource, matchScore
                    FROM official_registry
                    WHERE (g.businessID IS NOT NULL AND businessID = g.businessID)
                       OR (g.placeID IS NOT NULL AND placeID = g.placeID
                           AND (g.businessID IS NULL OR businessID = g.businessID))
                       OR (g.businessID IS NULL AND barangayID = g.barangayID AND businessName = g.detectedName)
                    ORDER BY (g.businessID IS NOT NULL AND businessID = g.businessID) DESC,
                             (g.placeID IS NOT NULL AND placeID = g.placeID) DESC
                    LIMIT 1
                ) r ON TRUE
                {geo_where}

                UNION ALL

                -- Branch 2: registry-only businesses (have coordinates, no geospatial_log yet)
                SELECT
                    -CAST(2147483648 + r.registryOrdinal AS SIGNED) AS logID,
                    r.businessID               AS businessID,
                    r.businessName             AS detectedName,
                    r.latitude                 AS latitude,
                    r.longitude                AS longitude,
                    {registry_flag_color}            AS flagColor,
                    COALESCE(r.lastRenewalDate, NOW()) AS detectedDate,
                    r.businessAddress          AS nearestLandmark,
                    NULL                       AS notes,
                    NULL                       AS placeID,
                    NULL                       AS reportedByUserID,
                    0                          AS noticeLevel,
                    {unlock}                   AS blackDispatchUnlocked,
                    b.barangayID               AS barangayID,
                    b.barangayName             AS barangayName,
                    r.businessSize             AS businessSize,
                    r.businessAddress          AS resolvedAddress,
                    '{SOURCE_REGISTRY}'        AS flagSource,
                    '{SOURCE_REGISTRY}'        AS originSource,
                    1                          AS registryLinked,
                    NULL                       AS verifiedGreenAt,
                    NULL                       AS verificationStatus,
                    r.matchStatus              AS matchStatus,
                    r.coordSource              AS coordSource,
                    r.matchScore               AS matchScore
                FROM (
                    SELECT official_registry.*,
                           ROW_NUMBER() OVER (ORDER BY businessID) AS registryOrdinal
                    FROM official_registry
                ) r
                LEFT JOIN barangays b ON r.barangayID = b.barangayID
                {reg_where}

            ) AS combined
            ORDER BY detectedDate DESC, logID DESC
            LIMIT %s OFFSET %s
        """
        cursor.execute(fetch_sql, geo_params + reg_params + [per_page, offset])
        rows = cursor.fetchall()
        cursor.close()

        for row in rows:
            decorate_compliance(row)
            if row.get("detectedDate"):
                row["detectedDate"] = str(row["detectedDate"])
            if row.get("latitude") is not None:
                row["latitude"] = float(row["latitude"])
            if row.get("longitude") is not None:
                row["longitude"] = float(row["longitude"])
            if row.get("matchScore") is not None:
                row["matchScore"] = float(row["matchScore"])

        return {
            "data":     rows,
            "total":    total,
            "page":     page,
            "per_page": per_page,
            "pages":    max(1, -(-total // per_page)),
        }, None

    except Exception as e:
        return None, str(e)


# ── Insert Yellow Flag ────────────────────────────────────────────────────────

class YellowFlagSubmissionConflict(Exception):
    """Raised when an idempotency key is reused for different report data."""


class YellowFlagValidationError(ValueError):
    """A client-correctable Yellow Flag input or boundary failure."""


def _validate_yellow_flag_barangay(cursor, lat, lng, barangay_id):
    """Validate the selected registry barangay, without proximity fallbacks."""
    cursor.execute(
        "SELECT barangayName FROM barangays WHERE barangayID = %s",
        (barangay_id,),
    )
    row = cursor.fetchone()
    if not row:
        raise YellowFlagValidationError(
            "The selected barangay does not exist.")

    def key(name):
        name = str(name or "").lower().replace("(pob.)", "").strip()
        for prefix in ("barangay ", "brgy. ", "brgy "):
            if name.startswith(prefix):
                name = name[len(prefix):]
                break
        return _normalize_barangay_name(name)

    selected_key = key(row["barangayName"])
    polygons = [
        polygon for name, polygon in _BARANGAY_POLYGONS.items()
        if key(_GEOJSON_BARANGAY_ALIASES.get(name, name)) == selected_key
    ]
    if len(polygons) != 1:
        raise RuntimeError(
            "Official barangay boundary data is unavailable or ambiguous."
        )
    try:
        scope = validate_barangay_scope(barangay_id, polygons[0])
    except ValueError as error:
        raise RuntimeError(
            "Official barangay boundary data is invalid.") from error
    if not scope.contains_coordinate(lat, lng):
        raise YellowFlagValidationError(
            "Coordinates do not fall within the selected barangay boundary."
        )


def insert_yellow_flag(
    business_name,
    lat,
    lng,
    barangay_id,
    notes=None,
    flag_color='Yellow',
    reported_by_user_id=None,
    client_submission_id=None,
    business_address=None,
):
    """Manually insert a Yellow Flag."""
    if flag_color != 'Yellow':
        return None, YellowFlagValidationError(
            "Only Yellow flags can be manually created."
        )
    if (
        isinstance(lat, bool) or isinstance(lng, bool)
        or not isinstance(lat, (int, float))
        or not isinstance(lng, (int, float))
    ):
        return None, YellowFlagValidationError(
            "Valid numeric latitude and longitude are required."
        )
    try:
        lat, lng = float(lat), float(lng)
    except (OverflowError, TypeError, ValueError):
        return None, YellowFlagValidationError(
            "Valid numeric latitude and longitude are required."
        )
    if not (
        math.isfinite(lat) and math.isfinite(lng)
        and -90 <= lat <= 90 and -180 <= lng <= 180
    ):
        return None, YellowFlagValidationError(
            "Coordinates must be finite and within WGS84 bounds."
        )
    if (
        isinstance(barangay_id, bool)
        or not isinstance(barangay_id, int) or barangay_id <= 0
    ):
        return None, YellowFlagValidationError(
            "A positive integer barangayID is required."
        )
    if (
        not isinstance(business_name, str)
        or not business_name.strip() or len(business_name) > 255
    ):
        return None, YellowFlagValidationError(
            "Business name is required (maximum 255 characters)."
        )
    # Older clients/queued reports predate the description field. When supplied,
    # retain it verbatim as the flag's address/landmark, independently of the pin.
    if business_address is not None and (
        not isinstance(business_address, str)
        or not business_address.strip() or len(business_address) > 255
    ):
        return None, YellowFlagValidationError(
            "Business address / Street / Purok / Landmark is required (maximum 255 characters)."
        )

    cursor = None
    try:
        # Coordinates describe the business, not the inspector's physical location.
        # Retain the production municipality predicate and its existing tolerance.
        if not _within_municipality(lat, lng):
            return None, YellowFlagValidationError(
                "Cannot place a flag outside the official municipality boundaries."
            )

        cursor = mysql.connection.cursor()
        _validate_yellow_flag_barangay(cursor, lat, lng, barangay_id)
        if client_submission_id:
            # Both branches are an inspector reporting from the field. The
            # idempotent branch is the same event retried, not a different
            # kind of flag.
            _columns, _values, _params = with_source(
                cursor,
                """(barangayID, reportID, detectedName, latitude, longitude,
                     flagColor, notes, reportedByUserID, clientSubmissionID, nearestLandmark)""",
                "(%s, NULL, %s, %s, %s, %s, %s, %s, %s, %s)",
                (barangay_id, business_name, lat, lng, flag_color, notes,
                 reported_by_user_id, client_submission_id, business_address),
                SOURCE_MANUAL,
            )
            cursor.execute(
                f"""INSERT INTO geospatial_logs {_columns} VALUES {_values}
                    ON DUPLICATE KEY UPDATE logID = LAST_INSERT_ID(logID)""",
                _params)
            created = cursor.rowcount == 1
            log_id = cursor.lastrowid
            cursor.execute("""
                SELECT barangayID, detectedName, latitude, longitude, notes,
                       flagColor, reportedByUserID, nearestLandmark
                FROM geospatial_logs
                WHERE logID = %s
            """, (log_id,))
            existing = cursor.fetchone()
            if existing:
                values = (
                    existing.get("barangayID"),
                    existing.get("detectedName"),
                    existing.get("latitude"),
                    existing.get("longitude"),
                    existing.get("notes"),
                    existing.get("flagColor"),
                    existing.get("reportedByUserID"),
                    existing.get("nearestLandmark"),
                ) if isinstance(existing, dict) else existing[:8]
                same_report = (
                    int(values[0]) == int(barangay_id)
                    and values[1] == business_name
                    and round(float(values[2]), 8) == round(float(lat), 8)
                    and round(float(values[3]), 8) == round(float(lng), 8)
                    and values[4] == notes
                    and values[5] == flag_color
                    and int(values[6]) == int(reported_by_user_id)
                    and values[7] == business_address
                )
                if not same_report:
                    mysql.connection.rollback()
                    cursor.close()
                    return None, YellowFlagSubmissionConflict(
                        "This submission ID was already used for different report data."
                    )
        else:
            _columns, _values, _params = with_source(
                cursor,
                """(barangayID, reportID, detectedName, latitude, longitude,
                     flagColor, notes, reportedByUserID, nearestLandmark)""",
                "(%s, NULL, %s, %s, %s, %s, %s, %s, %s)",
                (barangay_id, business_name, lat, lng, flag_color, notes,
                 reported_by_user_id, business_address),
                SOURCE_MANUAL,
            )
            cursor.execute(
                f"INSERT INTO geospatial_logs {_columns} VALUES {_values}",
                _params)
            created = True
            log_id = cursor.lastrowid
        mysql.connection.commit()
        cursor.close()

        # Fire admin notification (non-blocking)
        if reported_by_user_id and created:
            try:
                from api.notifications.service import notify_yellow_flag_reported
                notify_yellow_flag_reported(
                    log_id=log_id,
                    business_name=business_name,
                    barangay_id=barangay_id,
                    reporter_user_id=reported_by_user_id,
                    flag_color=flag_color,
                )
            except Exception as ne:
                print(f"insert_yellow_flag notification error: {ne}")

        return {
            "logID": log_id,
            "lat": lat,
            "lng": lng,
            "alreadyAccepted": not created,
            "businessAddress": business_address,
        }, None
    except YellowFlagValidationError as e:
        mysql.connection.rollback()
        cursor.close()
        return None, e
    except Exception as e:
        if cursor is not None:
            try:
                mysql.connection.rollback()
            finally:
                cursor.close()
        return None, str(e)


def update_flag_color(log_id, color):
    """Update a flag's color manually (e.g. to Purple, Orange, Yellow, or Red).
    Supports both real geospatial_logs (log_id > 0) and virtual registry flags (log_id < 0).
    """
    try:
        cursor = mysql.connection.cursor()

        if color == "Black":
            cursor.close()
            return False, "Use the audited Black escalation action to set a flag to Black."

        if log_id < 0:
            biz_id = _registry_business_id_for_virtual_log_id(cursor, log_id)
            if biz_id is None:
                cursor.close()
                return False, "Business not found"
            if color == "Orange":
                cursor.close()
                return False, (
                    "Orange requires an explicit verified inspection warning "
                    "and cannot be assigned to a registry-only flag."
                )
            # Registry-only flag: a Black locked business keeps its colour.
            # A Closed one does not - reopening is a normal admin correction.
            try:
                assert_not_black_locked(
                    cursor, biz_id, action="recolour this flag")
            except BlackLockedError as exc:
                cursor.close()
                return False, exc
            status_map = {
                "Green": "Active",
                "Purple": "Closed",
                "Red": "Expired",
                "Black": "Revoked",
                "Yellow": "Pending"
            }
            app_status = status_map.get(color)
            if app_status is None:
                cursor.close()
                return False, f"Unsupported registry flag color: {color}"
            cursor.execute(
                "UPDATE official_registry SET applicationStatus = %s WHERE businessID = %s", (app_status, biz_id))
            mysql.connection.commit()
            cursor.close()

            try:
                from api.notifications import hub
                hub.publish_to_admins({
                    "type": "flag_updated",
                    "logID": log_id,
                    "color": color
                })
            except Exception:
                pass
            return True, None

        cursor.execute(
            "SELECT flagColor, detectedName, barangayID, businessID "
            "FROM geospatial_logs WHERE logID = %s", (log_id,))
        row = cursor.fetchone()
        if not row:
            cursor.close()
            return False, "Flag not found"

        if (row.get("flagColor") == "Black"
                or (row.get("businessID")
                    and is_black_locked(cursor, row["businessID"]))):
            cursor.close()
            return False, "Black flags cannot be edited."

        if color == "Green":
            cursor.close()
            return False, (
                "Map pins can only be marked Green after Business ID review "
                "and compliance confirmation."
            )

        cursor.execute("""
            UPDATE geospatial_logs
            SET flagColor = %s
            WHERE logID = %s
        """, (color, log_id))

        # Propagate changes: if marked Purple, set registry status to Closed
        if color == 'Purple':
            cursor.execute("""
                UPDATE official_registry
                SET applicationStatus = 'Closed'
                WHERE LOWER(businessName) = LOWER(%s) AND barangayID = %s
            """, (row["detectedName"], row["barangayID"]))
        elif color == 'Green' and row["flagColor"] == 'Purple':
            cursor.execute("""
                UPDATE official_registry
                SET applicationStatus = 'Active'
                WHERE LOWER(businessName) = LOWER(%s) AND barangayID = %s AND applicationStatus = 'Closed'
            """, (row["detectedName"], row["barangayID"]))

        mysql.connection.commit()
        cursor.close()

        try:
            from api.notifications import hub
            hub.publish_to_admins({
                "type": "flag_updated",
                "logID": log_id,
                "color": color
            })
        except Exception:
            pass

        return True, None
    except Exception as e:
        return False, str(e)


class BarangayChangeConfirmationRequired(ValueError):
    def __init__(self, current_barangay_id, new_barangay_id,
                 current_barangay_name, new_barangay_name):
        self.current_barangay_id = current_barangay_id
        self.new_barangay_id = new_barangay_id
        self.current_barangay_name = current_barangay_name
        self.new_barangay_name = new_barangay_name
        super().__init__(
            f"The new pin is in {new_barangay_name}, but this record is "
            f"currently assigned to {current_barangay_name}. Saving will "
            "update the record's barangay. Continue?"
        )


def _barangay_change_confirmation_error(
    cursor, current_barangay_id, new_barangay_id, confirmed_barangay_id
):
    if current_barangay_id is None or new_barangay_id is None:
        return None

    if str(current_barangay_id) == str(new_barangay_id):
        return None
    if str(confirmed_barangay_id) == str(new_barangay_id):
        return None

    cursor.execute(
        "SELECT barangayID, barangayName FROM barangays "
        "WHERE barangayID IN (%s, %s)",
        (current_barangay_id, new_barangay_id),
    )
    names = {}
    for row in cursor.fetchall() or []:
        if isinstance(row, dict):
            names[str(row.get("barangayID"))] = row.get("barangayName")
        else:
            names[str(row[0])] = row[1]

    current_name = names.get(
        str(current_barangay_id), f"Barangay ID {current_barangay_id}"
    )
    new_name = names.get(
        str(new_barangay_id), f"Barangay ID {new_barangay_id}"
    )
    return BarangayChangeConfirmationRequired(
        current_barangay_id,
        new_barangay_id,
        current_name,
        new_name,
    )


def update_flag_location(
    log_id: int,
    lat: float,
    lng: float,
    actor_user_id=None,
    confirm_barangay_id=None,
):
    """
    Update coordinates of a flag manually (e.g. via drag-and-drop on the map).
    Handles both:
      - log_id > 0: real geospatial_logs entry
            - log_id < 0: virtual registry entry resolved through its registry ordinal
    Also updates barangayID based on new coordinates and backfills official_registry.
    """
    try:
        cursor = mysql.connection.cursor()
        new_barangay_id = _get_barangay_id_by_coords(lat, lng)

        if log_id < 0:
            biz_id = _registry_business_id_for_virtual_log_id(cursor, log_id)
            if biz_id is None:
                cursor.close()
                return False, "Business not found"
            cursor.execute(
                """SELECT businessID, businessName, businessAddress, barangayID,
                          latitude, longitude, coordSource, placeID, placeIDKind,
                          matchScore, matchStatus, resolveKey
                   FROM official_registry WHERE businessID=%s""",
                (biz_id,),
            )
            row = cursor.fetchone()
            if not row:
                cursor.close()
                return False, "Business not found"
            try:
                assert_not_black_locked(
                    cursor, biz_id, action="edit Black flag details")
            except BlackLockedError as exc:
                cursor.close()
                return False, exc
            confirmation_error = _barangay_change_confirmation_error(
                cursor,
                row.get("barangayID"),
                new_barangay_id,
                confirm_barangay_id,
            )
            if confirmation_error:
                cursor.close()
                return False, confirmation_error
            old_lat, old_lng = row.get("latitude"), row.get("longitude")
            final_barangay_id = new_barangay_id or row.get("barangayID")
            from api.registry.places_resolver import compute_resolve_key
            resolve_key = compute_resolve_key(
                row.get("businessName"), row.get("businessAddress"),
                final_barangay_id,
            )
            coordinates_changed = (
                old_lat is None or old_lng is None
                or (float(old_lat), float(old_lng)) != (float(lat), float(lng))
            )
            if coordinates_changed:
                from api.registry.reverify import (
                    _ensure_history_table,
                    record_location_history,
                )
                _ensure_history_table(cursor)
                record_location_history(
                    cursor, biz_id, "manual_corrected", "manual_correction",
                    resolve_key, old_row=row, new_lat=lat, new_lng=lng,
                    new_source="manual", candidate_source="manual",
                    new_address=row.get("businessAddress"),
                    new_barangay_id=final_barangay_id,
                    actor_user_id=actor_user_id,
                )
            cursor.execute("""
                UPDATE official_registry
                SET latitude = %s,
                    longitude = %s,
                    barangayID = COALESCE(%s, barangayID),
                    coordSource = 'manual',
                    matchStatus = 'approved',
                    coordFetchedAt = NOW(),
                    placeID = NULL,
                    placeIDKind = NULL,
                    resolveKey = %s
                WHERE businessID = %s
            """, (lat, lng, new_barangay_id, resolve_key, biz_id))
            mysql.connection.commit()
            cursor.close()

            try:
                from api.notifications import hub
                hub.publish_to_admins({
                    "type": "flag_location_updated",
                    "logID": log_id,
                    "latitude": lat,
                    "longitude": lng
                })
            except Exception:
                pass

            return True, None

        # Real flag in geospatial_logs
        cursor.execute(
            "SELECT detectedName, barangayID, placeID, latitude, longitude, "
            "businessID, flagColor FROM geospatial_logs WHERE logID = %s",
            (log_id,))
        row = cursor.fetchone()
        if not row:
            cursor.close()
            return False, "Flag not found"

        if (row.get("flagColor") == "Black"
                or (row.get("businessID")
                    and is_black_locked(cursor, row["businessID"]))):
            cursor.close()
            return False, "Black flags cannot be edited."

        detected_name = row["detectedName"]
        old_place_id = row.get("placeID")
        original_barangay_id = row.get("barangayID")

        # Resolve the linked registry row before confirming so the prompt uses
        # its stored barangay, not only the geospatial pin's barangay.
        target_biz_id = row.get("businessID")
        registry_match = None
        if target_biz_id:
            cursor.execute(
                "SELECT businessID, barangayID FROM official_registry "
                "WHERE businessID = %s LIMIT 1",
                (target_biz_id,),
            )
            registry_match = cursor.fetchone()
            if not registry_match:
                target_biz_id = None

        if not target_biz_id and old_place_id:
            cursor.execute(
                "SELECT businessID, barangayID FROM official_registry "
                "WHERE placeID = %s LIMIT 1",
                (old_place_id,),
            )
            registry_match = cursor.fetchone()
            if registry_match:
                target_biz_id = registry_match["businessID"]

        if not target_biz_id and detected_name:
            cursor.execute(
                """SELECT businessID, barangayID FROM official_registry
                   WHERE LOWER(businessName) = LOWER(%s)
                     AND (barangayID = %s OR barangayID = %s)
                   LIMIT 1""",
                (detected_name, original_barangay_id, new_barangay_id),
            )
            registry_match = cursor.fetchone()
            if registry_match:
                target_biz_id = registry_match["businessID"]

        current_barangay_id = (
            registry_match.get("barangayID")
            if target_biz_id and registry_match
            else original_barangay_id
        )
        confirmation_error = _barangay_change_confirmation_error(
            cursor,
            current_barangay_id,
            new_barangay_id,
            confirm_barangay_id,
        )
        if confirmation_error:
            cursor.close()
            return False, confirmation_error

        # Admin physically moved the pin: clear placeID on geospatial_logs
        cursor.execute("""
            UPDATE geospatial_logs
            SET latitude = %s,
                longitude = %s,
                barangayID = COALESCE(%s, barangayID),
                placeID = NULL
            WHERE logID = %s
        """, (lat, lng, new_barangay_id, log_id))

        # Backfill the pre-resolved official-registry match by businessID.
        if target_biz_id:
            cursor.execute(
                """SELECT businessID, businessName, businessAddress, barangayID,
                          latitude, longitude, coordSource, placeID, placeIDKind,
                          matchScore, matchStatus
                   FROM official_registry WHERE businessID=%s""",
                (target_biz_id,),
            )
            registry_row = cursor.fetchone()
            if registry_row:
                final_barangay_id = new_barangay_id or registry_row.get(
                    "barangayID")
                from api.registry.places_resolver import compute_resolve_key
                resolve_key = compute_resolve_key(
                    registry_row.get("businessName"),
                    registry_row.get("businessAddress"),
                    final_barangay_id,
                )
                old_lat = registry_row.get("latitude")
                old_lng = registry_row.get("longitude")
                coordinates_changed = (
                    old_lat is None or old_lng is None
                    or (float(old_lat), float(old_lng)) != (float(lat), float(lng))
                )
                if coordinates_changed:
                    from api.registry.reverify import (
                        _ensure_history_table,
                        record_location_history,
                    )
                    _ensure_history_table(cursor)
                    record_location_history(
                        cursor, target_biz_id, "manual_corrected",
                        "manual_correction", resolve_key, old_row=registry_row,
                        new_lat=lat, new_lng=lng, new_source="manual",
                        candidate_source="manual",
                        new_address=registry_row.get("businessAddress"),
                        new_barangay_id=final_barangay_id,
                        actor_user_id=actor_user_id,
                    )
            cursor.execute("""
                UPDATE official_registry
                SET latitude = %s,
                    longitude = %s,
                    barangayID = COALESCE(%s, barangayID),
                    coordSource = 'manual',
                    matchStatus = 'approved',
                    coordFetchedAt = NOW(),
                    placeID = NULL,
                    placeIDKind = NULL,
                    resolveKey = %s
                WHERE businessID = %s
            """, (lat, lng, new_barangay_id, resolve_key, target_biz_id))

        mysql.connection.commit()
        cursor.close()

        try:
            from api.notifications import hub
            hub.publish_to_admins({
                "type": "flag_location_updated",
                "logID": log_id,
                "latitude": lat,
                "longitude": lng
            })
        except Exception:
            pass

        return True, None
    except Exception as e:
        try:
            mysql.connection.rollback()
        except Exception:
            pass
        return False, str(e)


# ── Escalate to Black Flag ────────────────────────────────────────────────────

class FlagEscalationForbidden(PermissionError):
    """Only a current admin may escalate a business. HTTP 403."""


class FlagEscalationConflict(RuntimeError):
    """The current color or missing ladder prevents escalation. HTTP 409."""


class FlagEscalationNotFound(LookupError):
    """The requested pin or registry business does not exist. HTTP 404."""


def escalate_to_black(log_id, actor_user_id):
    """Admin escalation from Red/Yellow/Orange, independent of warning level.

    The pin, registry lock and audit event commit together. Registry-only flags
    use unique negative virtual IDs; unregistered physical pins only change the pin.
    This action does not require an inspection or change Black verification.
    """
    cursor = None
    committed = False
    try:
        cursor = mysql.connection.cursor()
        cursor.execute(
            "SELECT userRole FROM users WHERE userID = %s AND isActive = 1",
            (actor_user_id,))
        actor = cursor.fetchone()
        if not actor or actor.get("userRole") not in ("Admin", "SUPER_ADMIN", "System Administrator"):
            return False, FlagEscalationForbidden("Only an admin may escalate to Black.")

        if not _has_enforcement_columns(
                cursor, ("warningLevel", "blackLocked", "blackLockedAt", "blackLockedBy")):
            return False, FlagEscalationConflict(
                "Cannot escalate to Black: enforcement_state is unavailable.")

        registry_id = (
            _registry_business_id_for_virtual_log_id(cursor, log_id)
            if log_id < 0 else None
        )
        if log_id < 0 and registry_id is None:
            return False, FlagEscalationNotFound("Business not found")
        pin = None
        if log_id >= 0:
            cursor.execute(f"""
                SELECT g.logID,
                       {_registry_column_sql('g', 'businessID')} AS registryBusinessID,
                       {_effective_flag_color_sql('g', ladder=True)} AS effectiveFlagColor
                FROM geospatial_logs g WHERE g.logID = %s FOR UPDATE
            """, (log_id,))
            pin = cursor.fetchone()
            if pin is None:
                return False, FlagEscalationNotFound("Flag not found")
            registry_id = pin.get("registryBusinessID")

        registry = None
        registry_state = None
        if registry_id is not None:
            cursor.execute("""SELECT businessID, businessName, barangayID,
                       applicationStatus
                FROM official_registry WHERE businessID = %s FOR UPDATE""", (registry_id,))
            registry = cursor.fetchone()
            if registry is not None:
                cursor.execute(
                    """SELECT warningLevel, blackLocked
                       FROM enforcement_state
                       WHERE subjectType = 'business' AND subjectID = %s
                       FOR UPDATE""",
                    (str(registry_id),),
                )
                registry_state = cursor.fetchone() or {
                    "warningLevel": 0, "blackLocked": 0}
        if log_id < 0 and registry is None:
            return False, FlagEscalationNotFound("Business not found")

        current_color = (
            status_to_color(
                registry["applicationStatus"],
                warning_level=registry_state["warningLevel"],
                black_locked=registry_state["blackLocked"],
            )
            if registry else pin["effectiveFlagColor"]
        )
        if current_color not in ("Red", "Yellow", "Orange"):
            return False, FlagEscalationConflict(
                "This business is already Black." if current_color == "Black" else
                f"Cannot escalate from '{current_color}' to Black.")

        if registry is not None:
            cursor.execute(
                """SELECT ir.reportID, ir.verificationStatus
                   FROM inspection_reports ir
                   JOIN geospatial_logs g ON g.logID = ir.targetID
                   WHERE ir.targetType = 'geospatial_log'
                     AND (ir.verificationStatus IS NULL
                          OR ir.verificationStatus <> 'Verified')
                     AND (g.businessID = %s
                          OR (g.businessID IS NULL
                              AND g.detectedName = %s
                              AND g.barangayID = %s))
                   ORDER BY ir.irTimestamp DESC
                   LIMIT 1""",
                (registry_id, registry["businessName"],
                 registry["barangayID"]),
            )
        else:
            cursor.execute(
                """SELECT ir.reportID, ir.verificationStatus
                   FROM inspection_reports ir
                   WHERE ir.targetType = 'geospatial_log'
                     AND ir.targetID = %s
                     AND (ir.verificationStatus IS NULL
                          OR ir.verificationStatus <> 'Verified')
                   ORDER BY ir.irTimestamp DESC
                   LIMIT 1""",
                (log_id,),
            )
        pending_inspection = cursor.fetchone()
        if pending_inspection:
            report_id = pending_inspection.get("reportID")
            status = pending_inspection.get("verificationStatus") or "Assigned"
            return False, FlagEscalationConflict(
                "Cannot escalate to Black while an inspection is still open "
                f"(report #{report_id}, status {status}). Verify it or send it "
                "back first.")

        if registry:
            previous_level = registry_state["warningLevel"]
            previous_black = registry_state["blackLocked"]
            cursor.execute("""UPDATE official_registry
                SET applicationStatus = 'Revoked'
                WHERE businessID = %s""", (registry_id,))
            cursor.execute(
                """INSERT INTO enforcement_state (
                       subjectType, subjectID, warningLevel, blackLocked,
                       blackLockedAt, blackLockedBy
                   ) VALUES ('business', %s, %s, 1, NOW(), %s)
                   ON DUPLICATE KEY UPDATE blackLocked = 1,
                       blackLockedAt = NOW(),
                       blackLockedBy = VALUES(blackLockedBy)""",
                (str(registry_id), previous_level, actor_user_id),
            )
            record_enforcement_event(
                cursor, business_id=registry_id, event_type=BLACK_LOCKED,
                actor_user_id=actor_user_id, reason="Admin escalation from Map",
                previous_level=previous_level, new_level=previous_level,
                previous_black=previous_black, new_black=True)
            cursor.execute(
                "UPDATE geospatial_logs SET flagColor = 'Black' WHERE businessID = %s", (registry_id,))

        if pin is not None:
            if registry is None:
                cursor.execute(
                    """SELECT warningLevel, blackLocked
                       FROM enforcement_state
                       WHERE subjectType = 'geospatial_log' AND subjectID = %s
                       FOR UPDATE""",
                    (str(log_id),),
                )
                pin_state = cursor.fetchone() or {
                    "warningLevel": 0, "blackLocked": 0}
                cursor.execute(
                    """INSERT INTO enforcement_state (
                           subjectType, subjectID, warningLevel, blackLocked,
                           blackLockedAt, blackLockedBy
                       ) VALUES ('geospatial_log', %s, %s, 1, NOW(), %s)
                       ON DUPLICATE KEY UPDATE blackLocked = 1,
                           blackLockedAt = NOW(),
                           blackLockedBy = VALUES(blackLockedBy)""",
                    (str(log_id), pin_state["warningLevel"], actor_user_id),
                )
                record_enforcement_event(
                    cursor, subject_type="geospatial_log", subject_id=log_id,
                    event_type=BLACK_LOCKED, actor_user_id=actor_user_id,
                    reason="Admin escalation from Map",
                    previous_level=pin_state["warningLevel"],
                    new_level=pin_state["warningLevel"],
                    previous_black=pin_state["blackLocked"], new_black=True,
                )
            cursor.execute(
                "UPDATE geospatial_logs SET flagColor = 'Black' WHERE logID = %s", (log_id,))

        mysql.connection.commit()
        committed = True

        try:
            from api.notifications import hub
            hub.publish_to_admins({
                "type": "flag_updated",
                "logID": log_id,
                "color": "Black"
            })
        except Exception:
            pass

        return True, None

    except Exception as e:
        return False, str(e)
    finally:
        if cursor is not None:
            # Read refusals release any row locks as well as closing the cursor.
            if not committed:
                mysql.connection.rollback()
            cursor.close()


# ── Delete Flag ───────────────────────────────────────────────────────────────

class PinDeletionConflict(RuntimeError):
    """A changed or protected pin must not be partially deleted."""


def delete_flag(log_id, actor_role=None):
    """
    Delete a single flag.
    - If log_id < 0: virtual registry entry. Removes its official_registry entry.
    - If log_id > 0: isolates deletion strictly to log_id.
      Does NOT perform broad delete across all same-named businesses or logs.
      Before deleting geospatial_logs, repoints any inspection_reports / lifecycle events
      to a primary surviving duplicate log if one exists, otherwise removes them.
    """
    cursor = None
    committed = False
    try:
        cursor = mysql.connection.cursor()

        if log_id < 0:
            biz_id = _registry_business_id_for_virtual_log_id(cursor, log_id)
            if biz_id is None:
                return False, "Business not found"
            from api.registry.inspection_link import confirmed_pin_column_available
            has_confirmed_pin = confirmed_pin_column_available(cursor)
            cursor.execute("SELECT businessID" + (", confirmedLogID" if has_confirmed_pin else "")
                           + " FROM official_registry WHERE businessID = %s FOR UPDATE", (biz_id,))
            registry_row = cursor.fetchone()
            if not registry_row:
                return False, "Business not found"
            assert_business_deletable(cursor, biz_id, actor_role)
            if registry_row.get("confirmedLogID") is not None:
                raise PinDeletionConflict(
                    "This registry business now has a confirmed map pin. Refresh the map; the business was not deleted.")
            cursor.execute("SELECT logID FROM geospatial_logs WHERE businessID = %s LIMIT 1 FOR UPDATE", (biz_id,))
            if cursor.fetchone():
                raise PinDeletionConflict(
                    "This registry business now has a map pin. Refresh the map; the business was not deleted.")
            cursor.execute(
                "DELETE FROM official_registry WHERE businessID = %s", (biz_id,))
            mysql.connection.commit()
            committed = True

            try:
                from api.notifications import hub
                hub.publish_to_admins({
                    "type": "flag_deleted",
                    "logID": log_id
                })
            except Exception:
                pass
            return True, None

        # Find the specific flag
        cursor.execute(
            """SELECT logID, businessID, reportID, detectedName, barangayID,
                      placeID, latitude, longitude, flagColor
               FROM geospatial_logs WHERE logID = %s FOR UPDATE""",
            (log_id,)
        )
        flag = cursor.fetchone()

        if not flag:
            return False, "Flag not found"

        if (flag.get("flagColor") == "Black"
            or (flag.get("businessID")
                and is_black_locked(cursor, flag["businessID"]))):
            raise BlackBusinessDeletionForbidden(
                "Black flags cannot be deleted, including by SUPER_ADMIN.")

        from api.registry.inspection_link import GreenRegistryLinkError, release_confirmed_pin
        try:
            release_confirmed_pin(cursor, log_id)
        except GreenRegistryLinkError as exc:
            raise PinDeletionConflict(str(exc)) from exc

        # Check if there is an explicit surviving duplicate log for this establishment
        surviving_log = None
        if flag.get("businessID"):
            cursor.execute(
                """SELECT logID, reportID FROM geospatial_logs
                   WHERE businessID = %s AND logID <> %s
                   ORDER BY (reportID IS NOT NULL) DESC, logID ASC LIMIT 1""",
                (flag["businessID"], log_id)
            )
            surviving_log = cursor.fetchone()

        if not surviving_log and flag.get("placeID"):
            cursor.execute(
                """SELECT logID, reportID FROM geospatial_logs
                   WHERE placeID = %s AND logID <> %s
                   ORDER BY (reportID IS NOT NULL) DESC, logID ASC LIMIT 1""",
                (flag["placeID"], log_id)
            )
            surviving_log = cursor.fetchone()

        # Check if this flag has inspection reports
        cursor.execute(
            "SELECT reportID FROM inspection_reports WHERE targetID = %s", (log_id,))
        reports = cursor.fetchall()

        if reports:
            if surviving_log:
                surv_id = surviving_log["logID"]
                cursor.execute(
                    "UPDATE inspection_reports SET targetID = %s WHERE targetID = %s",
                    (surv_id, log_id)
                )
                cursor.execute(
                    "UPDATE inspection_lifecycle_events SET targetLogID = %s WHERE targetLogID = %s",
                    (surv_id, log_id)
                )
                if flag.get("reportID") and not surviving_log.get("reportID"):
                    cursor.execute(
                        "UPDATE geospatial_logs SET reportID = %s WHERE logID = %s AND reportID IS NULL",
                        (flag["reportID"], surv_id)
                    )
            else:
                cursor.execute(
                    "DELETE FROM inspection_reports WHERE targetID = %s", (log_id,))

        # Strictly delete ONLY this logID
        cursor.execute(
            "DELETE FROM geospatial_logs WHERE logID = %s", (log_id,))

        mysql.connection.commit()
        committed = True

        try:
            from api.notifications import hub
            hub.publish_to_admins({
                "type": "flag_deleted",
                "logID": log_id
            })
        except Exception:
            pass

        return True, None

    except (BlackBusinessDeletionForbidden, PinDeletionConflict) as exc:
        return False, exc
    except Exception as e:
        if e.args and e.args[0] in (1205, 1213, 1451):
            return False, PinDeletionConflict(
                "The pin or a linked record changed during deletion. Refresh and retry.")
        return False, str(e)
    finally:
        if cursor is not None:
            if not committed:
                mysql.connection.rollback()
            cursor.close()


# ── DBSCAN parameters (recalibrate during testing if over/under-clustering) ───
#
# DBSCAN_EPS_RAD   — neighbourhood search radius expressed in radians.
#                    20 m is chosen to match the ~8–15 m commercial lot
#                    frontage typical of a rural Filipino municipality;
#                    two adjacent flagged venues will therefore be pulled
#                    into the same cluster only if they are genuinely
#                    co-located, not merely on the same street block.
#
# DBSCAN_MIN_SAMPLES — minimum flags required to form a dense cluster.
#                    Set to 3 so that a pair of adjacent detections does
#                    NOT qualify as a systemic hotspot; at least three
#                    co-located Red Flags must exist. Isolated detections
#                    (label == -1) are treated as statistical anomalies
#                    and are discarded before the result is returned.
#
# To recalibrate: adjust DBSCAN_EPS_M (converted automatically) and/or
# DBSCAN_MIN_SAMPLES, then re-run and inspect cluster counts vs map.
EARTH_RADIUS_M = 6_371_000
DBSCAN_EPS_M = 20                            # metres  ← change this to retune
DBSCAN_EPS_RAD = DBSCAN_EPS_M / EARTH_RADIUS_M  # radians fed to sklearn
# MinPts  ← change this to retune
DBSCAN_MIN_SAMPLES = 3


def get_red_flag_clusters():
    """
    Barangay Risk Heatmap — geographic hotspot detection for Red Flags.

    Implements the second analytic level described in the system design:
    DBSCAN is used to collate neighbouring Red Flags into dense clusters
    while discarding single detections as statistical anomalies (noise).

    Algorithm
    ---------
    1. Pull every Red Flag coordinate from geospatial_logs.
    2. Run DBSCAN (haversine metric, eps = DBSCAN_EPS_M metres,
       min_samples = DBSCAN_MIN_SAMPLES) to identify spatially dense
       groups without requiring a pre-specified cluster count.
    3. Discard noise points (label == -1) — isolated flags are treated
       as anomalies, not hotspots.
    4. For each true cluster compute:
         • centroid  – mean lat/lng of member flags
         • size      – number of Red Flags in the cluster
         • logIDs    – contributing log IDs (for drill-down)
         • radius_m  – max geodesic distance from centroid to any member
           (used by the front end to size the circle overlay)
    5. Return clusters sorted largest-first.

    Returns
    -------
    (list[dict], None)   on success
    (None, str)          on error
    """
    try:
        cursor = mysql.connection.cursor()
        cursor.execute("""
            SELECT logID, latitude, longitude
            FROM   geospatial_logs
            WHERE  flagColor = 'Red'
              AND  latitude  IS NOT NULL
              AND  longitude IS NOT NULL
        """)
        rows = cursor.fetchall()
        cursor.close()

        if not rows:
            return [], None

        # ── Build coordinate matrix in radians ──────────────────────────────
        log_ids = [r["logID"] for r in rows]
        lats = [float(r["latitude"]) for r in rows]
        lngs = [float(r["longitude"]) for r in rows]

        coords_rad = np.radians(np.column_stack([lats, lngs]))   # (N, 2)

        # ── DBSCAN ──────────────────────────────────────────────────────────
        db = DBSCAN(
            eps=DBSCAN_EPS_RAD,
            min_samples=DBSCAN_MIN_SAMPLES,
            algorithm="ball_tree",
            metric="haversine",
        ).fit(coords_rad)

        labels = db.labels_   # -1 = noise (isolated flag)

        # ── Aggregate per cluster ────────────────────────────────────────────
        from collections import defaultdict
        groups = defaultdict(list)
        for idx, label in enumerate(labels):
            groups[label].append(idx)

        clusters = []
        for label, indices in groups.items():

            # label == -1 → DBSCAN noise: isolated flags that do not share a
            # 20-m neighbourhood with ≥ 2 others.  Per the system design these
            # are statistical anomalies and are intentionally discarded here.
            if label == -1:
                continue

            member_lats = [lats[i] for i in indices]
            member_lngs = [lngs[i] for i in indices]
            member_ids = [log_ids[i] for i in indices]

            centroid_lat = sum(member_lats) / len(member_lats)
            centroid_lng = sum(member_lngs) / len(member_lngs)

            # Radius = max geodesic distance from centroid to any member flag.
            # A minimum of DBSCAN_EPS_M is enforced so that very tight clusters
            # (e.g. two flags at nearly identical coordinates) are still visible
            # as a circle on the map at town-level zoom.
            radius_m = 0.0
            for mlat, mlng in zip(member_lats, member_lngs):
                from geopy.distance import geodesic
                d = geodesic((centroid_lat, centroid_lng), (mlat, mlng)).meters
                if d > radius_m:
                    radius_m = d

            radius_m = max(radius_m, DBSCAN_EPS_M)

            clusters.append({
                "clusterID":   int(label),
                "centroidLat": round(centroid_lat, 7),
                "centroidLng": round(centroid_lng, 7),
                "size":        len(indices),
                "radius_m":    round(radius_m, 1),
                "logIDs":      member_ids,
            })

        # Largest hotspots first
        clusters.sort(key=lambda c: c["size"], reverse=True)
        return clusters, None

    except Exception as e:
        return None, str(e)
