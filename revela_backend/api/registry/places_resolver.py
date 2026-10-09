"""
api/registry/places_resolver.py

Resolve a BPLO business to a map pin using Google Places API (New) Text Search, falling
back to the Geocoding API. Designed to stay inside Google's free monthly SKU thresholds
and to respect the 30-day cache limit on Google-derived lat/lng.

Places resolution is enabled by default; set PLACES_RESOLVER_ENABLED=0 to turn it off.

Environment variables (all optional unless noted)
    PLACES_RESOLVER_ENABLED   "0" to disable (default "1" => Places-first resolution)
  GOOGLE_MAPS_API_KEY       required (already used by service.py)
  GEO_MUNICIPALITY / GEO_PROVINCE      default Mataasnakahoy / Batangas
  PLACES_CENTER             "lat,lng"  -> adds a location bias to Text Search (unset = no bias)
  PLACES_BBOX               "min_lat,max_lat,min_lng,max_lng" -> reject results outside (unset = no check)
  PLACES_BIAS_RADIUS_M      default 8000
  PLACES_AUTO_ACCEPT        default 0.80   name-similarity >= this: accept as 'auto'
  PLACES_REVIEW_MIN         default 0.55   between REVIEW_MIN and AUTO_ACCEPT: 'review'
  TS_MONTHLY_CAP / TS_DAILY_CAP   Text Search budget (default 2500/month, 75/day)
  PD_MONTHLY_CAP / PD_DAILY_CAP   Place Details budget (default 3000/month, 90/day)

Scheduled maintenance (cron / task scheduler), inside an app context:
    from api.registry.places_resolver import refresh_expired_coords, purge_expired_coords
    refresh_expired_coords()              # ~ daily; renews coords older than 20 days
    purge_expired_coords(dry_run=False)   # safety net; clears Google coords older than 28 days
"""
import hashlib
import math
import os
import random
import re
import threading
import time
from difflib import SequenceMatcher

import requests

from app import mysql
from api.utils.name_match import name_match, parse_name
from api.utils.places_quota import read_usage, reserve_usage_slot

PLACES_SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"
PLACE_DETAILS_URL = "https://places.googleapis.com/v1/places/{pid}"
GEOCODE_URL = "https://maps.googleapis.com/maps/api/geocode/json"

MUNICIPALITY = os.getenv("GEO_MUNICIPALITY", "Mataasnakahoy")
PROVINCE = os.getenv("GEO_PROVINCE", "Batangas")
DEFAULT_CENTER = (13.9667, 121.1167)
DEFAULT_BIAS_RADIUS_M = 8000.0
BIAS_RADIUS_M = float(os.getenv("PLACES_BIAS_RADIUS_M", "8000"))
AUTO_ACCEPT = float(os.getenv("PLACES_AUTO_ACCEPT", "0.80"))
REVIEW_MIN = float(os.getenv("PLACES_REVIEW_MIN", "0.55"))
TS_MONTHLY_CAP = int(os.getenv("TS_MONTHLY_CAP", "2500"))
TS_DAILY_CAP = int(os.getenv("TS_DAILY_CAP", "75"))
PD_MONTHLY_CAP = int(os.getenv("PD_MONTHLY_CAP", "3000"))
PD_DAILY_CAP = int(os.getenv("PD_DAILY_CAP", "90"))
REFRESH_AFTER_DAYS = 20
PURGE_AFTER_DAYS = 28

_halted = None  # set to a message after a 401/403 so we stop spending calls until restart
_api_state = threading.local()
_places_request_lock = threading.Lock()
_last_places_request_at = 0.0


def enabled():
    return os.getenv("PLACES_RESOLVER_ENABLED", "1") == "1"


def reset_run_state():
    """Clear run-scoped quota state before starting a new resolver run."""
    _api_state.quota_halted = False
    _api_state.last_error = None
    _api_state.outcome = None
    _api_state.quota_reason = None


def get_places_call_usage():
    """Return persistent usage for each Registry API method for today and this month."""
    return {
        "text_search": read_usage(mysql.connection, "imp_ts_month", "imp_ts_day"),
        "details": read_usage(mysql.connection, "imp_pd_month", "imp_pd_day"),
        "geocoding": read_usage(mysql.connection, "geo_month", "geo_day"),
    }


def get_text_search_quota_status():
    usage = get_places_call_usage()["text_search"]
    return {
        "used": usage["month"],
        "cap": TS_MONTHLY_CAP,
        "remaining": max(0, TS_MONTHLY_CAP - usage["month"]),
        "monthly_quota_exceeded": usage["month"] >= TS_MONTHLY_CAP,
        "used_today": usage["day"],
        "daily_cap": TS_DAILY_CAP,
        "daily_remaining": max(0, TS_DAILY_CAP - usage["day"]),
        "daily_quota_exceeded": usage["day"] >= TS_DAILY_CAP,
    }


def compute_resolve_key(name, address, barangay_id):
    """
    Computes a deterministic SHA-1 hash of businessName, businessAddress, and barangayID.
    Used for caching so re-running the resolver on unchanged datasets consumes zero API calls.
    """
    n = str(name or "").strip().lower()
    a = str(address or "").strip().lower()
    b = str(barangay_id or "").strip().lower()
    raw = f"{n}|{a}|{b}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def compute_places_refresh_key(name, address, barangay_id):
    """Use a separate cache key for one-time Places rechecks of old geocode pins."""
    n = str(name or "").strip().lower()
    a = str(address or "").strip().lower()
    b = str(barangay_id or "").strip().lower()
    raw = f"{n}|{a}|{b}|places-refresh-v1"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def _floats(env, n):
    raw = os.getenv(env, "").strip()
    if not raw:
        return None
    try:
        vals = tuple(float(x) for x in raw.split(","))
    except ValueError:
        return None
    return vals if len(vals) == n else None


def _is_within_municipal_bounds(lat, lng):
    """
    Screens candidate coordinates against Mataasnakahoy geographic bounds.
    Replaces unconstrained bounding box with Mataasnakahoy municipal polygon boundary screening
    and center bias radius (8,000m from center: 13.9667, 121.1167).
    """
    if lat is None or lng is None:
        return False
    try:
        lat = float(lat)
        lng = float(lng)
    except (ValueError, TypeError):
        return False

    # Polygon boundary screening (primary)
    try:
        from api.flags.service import _within_municipality
        return _within_municipality(lat, lng)
    except Exception:
        pass

    box = _floats("PLACES_BBOX", 4)
    if box:
        return box[0] <= lat <= box[1] and box[2] <= lng <= box[3]

    # Center bias radius check (8,000m)
    center = _floats("PLACES_CENTER", 2) or DEFAULT_CENTER
    radius_m = BIAS_RADIUS_M or DEFAULT_BIAS_RADIUS_M
    try:
        lat1, lon1 = math.radians(center[0]), math.radians(center[1])
        lat2, lon2 = math.radians(lat), math.radians(lng)
        dlat = lat2 - lat1
        dlon = lon2 - lon1
        a = math.sin(dlat / 2)**2 + math.cos(lat1) * \
            math.cos(lat2) * math.sin(dlon / 2)**2
        c = 2 * math.asin(math.sqrt(a))
        dist_m = 6371000.0 * c
        return dist_m <= radius_m
    except Exception:
        return False


def _in_bbox(lat, lng):
    """Backwards-compatible alias for municipal bounds screening."""
    return _is_within_municipal_bounds(lat, lng)


# ------------------------------ matching ------------------------------------
def normalize(s):
    tokens, _ = parse_name(s)
    return " ".join(tokens)


def similarity(a, b, reg_line='', poi_types=()):
    score, _ = name_match(a, b, reg_line=reg_line, poi_types=poi_types)
    return score


# ------------------------------ budget guard ---------------------------------
_MONTH_KEY = "DATE_SUB(CURDATE(), INTERVAL DAYOFMONTH(CURDATE()) - 1 DAY)"
def reserve_call(prefix, monthly_cap, daily_cap=None):
    """Atomically reserve a method's monthly and daily slots; fail closed on DB errors."""
    daily_cap = daily_cap if daily_cap is not None else 2_147_483_647
    try:
        allowed, reason = reserve_usage_slot(
            mysql.connection,
            f"{prefix}_month",
            f"{prefix}_day",
            monthly_cap,
            daily_cap,
        )
        _api_state.quota_reason = reason
        if not allowed:
            print(f"[places_resolver budget] {reason} for {prefix}")
        return allowed
    except Exception as e:
        _api_state.quota_reason = "quota_ledger_error"
        print(f"[places_resolver budget] reservation failed closed for {prefix}: {e}")
        return False


def _api_get_json(resp, label):
    """Return parsed JSON for 200; record HTTP errors without treating them as empty results."""
    global _halted
    if resp.status_code == 200:
        try:
            return resp.json()
        except ValueError as e:
            _api_state.last_error = f"{label} invalid JSON response: {e}"
            _api_state.outcome = "api_error"
            print(f"[places_resolver] {_api_state.last_error}")
            return None
    body = getattr(resp, "text", "") or ""
    if resp.status_code in (401, 403):
        _halted = f"{label} {resp.status_code}: {body[:200]}"
        print(f"[places_resolver] HALTED until restart -> {_halted}")
    else:
        print(f"[places_resolver] {label} HTTP {resp.status_code}: {body[:2000]}")
    _api_state.last_error = f"{label} HTTP {resp.status_code}"
    _api_state.outcome = "api_error"
    return None


def _429_is_per_minute(body):
    text = str(body or "").lower()
    return any(marker in text for marker in (
        "perminute", "per_minute", "per minute", "requestsperminute",
        "rate_limit_exceeded", "rate limit", "per-minute",
    ))


def _429_is_daily_quota(body):
    text = str(body or "").lower()
    return any(marker in text for marker in (
        "resource_exhausted", "perday", "per_day", "per day",
        "requestsperday", "daily quota", "quota exceeded",
    ))


def _places_request(label, request, reserve):
    """Send a budgeted, serialized Places API request with bounded minute-limit retries."""
    global _last_places_request_at
    max_retries = 3
    for attempt in range(max_retries + 1):
        if getattr(_api_state, "quota_halted", False):
            _api_state.outcome = getattr(_api_state, "quota_reason", None) or "skipped_quota"
            _api_state.last_error = "Places quota exhausted for this run"
            return None
        with _places_request_lock:
            elapsed = time.monotonic() - _last_places_request_at
            if _last_places_request_at and elapsed < 0.3:
                time.sleep(random.uniform(0.3, 0.5) - elapsed)
            if not reserve():
                _api_state.quota_halted = True
                reason = getattr(_api_state, "quota_reason", None) or "skipped_quota"
                _api_state.outcome = (
                    "api_error" if reason == "quota_ledger_error" else reason
                )
                _api_state.last_error = f"{label} {reason.replace('_', ' ')}"
                print(
                    f"[places_resolver] {label} not sent: "
                    f"{reason.replace('_', ' ')}"
                )
                return None
            try:
                resp = request()
                _last_places_request_at = time.monotonic()
            except requests.RequestException as e:
                _api_state.last_error = f"{label} network error: {e}"
                _api_state.outcome = "api_error"
                print(f"[places_resolver] {label} network error: {e}")
                return None

        if resp.status_code == 429:
            body = getattr(resp, "text", "") or ""
            print(f"[places_resolver] {label} HTTP 429 body: {body[:2000]}")
            if _429_is_per_minute(body):
                if attempt < max_retries:
                    delay = (2 ** (attempt + 1)) * random.uniform(0.8, 1.2)
                    print(f"[places_resolver] {label} per-minute quota; retry "
                          f"{attempt + 1}/{max_retries} in {delay:.2f}s")
                    time.sleep(delay)
                    continue
                _api_state.last_error = f"{label} per-minute quota retries exhausted (HTTP 429)"
                _api_state.outcome = "api_error"
                return None
            if _429_is_daily_quota(body) or not _429_is_per_minute(body):
                _api_state.quota_halted = True
                _api_state.outcome = "skipped_quota"
                _api_state.last_error = f"{label} daily quota exhausted (HTTP 429)"
                print(f"[places_resolver] {label} daily quota exhausted; stopping Places calls for this run")
                return None

        data = _api_get_json(resp, label)
        if data is None and resp.status_code in (401, 403):
            _api_state.quota_halted = True
        elif data is not None:
            _api_state.last_error = None
            _api_state.outcome = None
        return data
    return None


# ------------------------------ resolution -----------------------------------
def _text_search(name, address, barangay, post=requests.post, reserve=None):
    _api_state.last_error = None
    _api_state.outcome = None
    parts = [str(p).strip() for p in (name, address, barangay, MUNICIPALITY, PROVINCE)
             if p is not None and str(p).strip() and str(p).strip().lower() != "nan"]
    body = {"textQuery": ", ".join(parts), "regionCode": "PH", "pageSize": 5}
    center = _floats("PLACES_CENTER", 2) or DEFAULT_CENTER
    body["locationBias"] = {"circle": {
        "center": {"latitude": center[0], "longitude": center[1]},
        "radius": BIAS_RADIUS_M or DEFAULT_BIAS_RADIUS_M,
    }}
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": os.getenv("GOOGLE_MAPS_API_KEY", ""),
        # Pro-tier fields only. Strictly do NOT add Enterprise fields (rating, userRatingCount, regularOpeningHours, websiteUri).
        "X-Goog-FieldMask": "places.id,places.displayName,places.location,places.primaryType,places.types",
    }
    data = _places_request(
        "TextSearch",
        lambda: post(PLACES_SEARCH_URL, headers=headers, json=body, timeout=10),
        reserve or (lambda: True),
    )
    return data if data is not None else {}


def _geocode_fallback(address, barangay, get=requests.get):
    parts = [str(p).strip() for p in (address, barangay, MUNICIPALITY, PROVINCE, "Philippines")
             if p is not None and str(p).strip() and str(p).strip().lower() != "nan"]
    params = {"address": ", ".join(parts), "components": "country:PH",
              "key": os.getenv("GOOGLE_MAPS_API_KEY", "")}
    try:
        data = _api_get_json(
            get(GEOCODE_URL, params=params, timeout=10), "Geocode") or {}
    except requests.RequestException as e:
        _api_state.last_error = f"Geocode network error: {e}"
        _api_state.outcome = "api_error"
        print(f"[places_resolver] Geocode network error: {e}")
        return None
    if data.get("status") in ("OVER_DAILY_LIMIT", "OVER_QUERY_LIMIT"):
        _api_state.last_error = f"Geocode quota exhausted: {data.get('status')}"
        _api_state.outcome = "skipped_quota"
        _api_state.quota_reason = "geocode_quota_exceeded"
        print(f"[places_resolver] {_api_state.last_error}")
        return None
    if data.get("status") == "REQUEST_DENIED":
        global _halted
        _halted = f"Geocode {data.get('status')}"
        _api_state.last_error = _halted
        _api_state.outcome = "api_error"
        print(f"[places_resolver] HALTED until restart -> {_halted}")
        return None
    if data.get("status") != "OK" or not data.get("results"):
        if data.get("status") not in ("ZERO_RESULTS", "OK"):
            _api_state.last_error = f"Geocode API status {data.get('status')}"
            _api_state.outcome = "api_error"
            print(f"[places_resolver] {_api_state.last_error}")
        return None
    top = data["results"][0]
    loc = top["geometry"]["location"]
    lt = top["geometry"].get("location_type", "")
    lat, lng = loc["lat"], loc["lng"]
    if not _is_within_municipal_bounds(lat, lng):
        return None
    partial = bool(top.get("partial_match"))
    if lt in ("ROOFTOP", "RANGE_INTERPOLATED") and not partial:
        status = "auto"
    elif lt in ("ROOFTOP", "RANGE_INTERPOLATED", "GEOMETRIC_CENTER"):
        status = "review"
    else:  # APPROXIMATE: area centroid, would stack many businesses on one pin
        return None
    return {"lat": lat, "lng": lng, "meta": {
        "coord_source": "geocode", "place_id": top.get("place_id"), "place_id_kind": "address",
        "score": None, "match_status": status, "match_type": f"geocode_{lt.lower()}"}}


def resolve_location(name, address, barangay, business_id=None, barangay_id=None,
                     line_of_business='', reserve_geocode=None, refresh_geocode=False,
                     force=False, preferred_place_id=None,
                     _post=requests.post, _get=requests.get):
    """Returns (lat, lng, meta); API/quota failures are distinguished from no-match results.

    force=True skips the resolveKey cache so an already-attempted record is looked up again
    (used by api.registry.reverify).
    """
    _api_state.last_error = None
    _api_state.outcome = None
    if not os.getenv("GOOGLE_MAPS_API_KEY"):
        return None, None, {"reason": "api_error", "api_error": "Google Maps API key is not configured"}
    if _halted:
        return None, None, {"reason": "api_error", "api_error": str(_halted)}
    if getattr(_api_state, "quota_halted", False):
        return None, None, {
            "reason": getattr(_api_state, "quota_reason", None) or "skipped_quota",
            "api_error": getattr(_api_state, "last_error", None),
            "budget_exhausted": True,
        }
    # 1. Compute resolveKey for caching
    b_ref = barangay_id if barangay_id is not None else barangay
    current_key = (
        compute_places_refresh_key(name, address, b_ref)
        if refresh_geocode else compute_resolve_key(name, address, b_ref)
    )

    # 2. Check if resolveKey in DB matches: skip API call if unchanged
    if business_id and not force:
        cur = mysql.connection.cursor()
        try:
            cur.execute(
                """SELECT resolveKey, latitude, longitude, coordSource, placeID,
                          placeIDKind, matchScore, matchStatus, lineOfBusiness
                   FROM official_registry
                   WHERE businessID = %s""",
                (business_id,),
            )
            stored = cur.fetchone()
            if stored:
                if not line_of_business:
                    line_of_business = (stored.get("lineOfBusiness") if isinstance(
                        stored, dict) else (stored[8] if len(stored) > 8 else "")) or ""
                stored_key = stored.get("resolveKey") if isinstance(
                    stored, dict) else stored[0]
                if stored_key and stored_key == current_key:
                    stored_lat = stored.get("latitude") if isinstance(
                        stored, dict) else stored[1]
                    stored_lng = stored.get("longitude") if isinstance(
                        stored, dict) else stored[2]
                    if stored_lat is not None and stored_lng is not None:
                        return float(stored_lat), float(stored_lng), {
                            "coord_source": stored.get("coordSource"),
                            "place_id": stored.get("placeID"),
                            "place_id_kind": stored.get("placeIDKind"),
                            "score": float(stored.get("matchScore")) if stored.get("matchScore") is not None else None,
                            "match_status": stored.get("matchStatus"),
                            "match_type": "cached_resolve_key",
                            "resolve_key": current_key,
                        }
                    else:
                        # Previously resolved with identical key as unlocatable
                        return None, None, {"resolve_key": current_key, "match_status": stored.get("matchStatus")}
        except Exception as e:
            print(f"[places_resolver] resolveKey lookup error: {e}")
        finally:
            cur.close()

    # 3. Check registry_rejected_places for this businessID
    rejected_pids = set()
    if business_id:
        cur = mysql.connection.cursor()
        try:
            cur.execute(
                "SELECT placeID FROM registry_rejected_places WHERE businessID = %s",
                (business_id,),
            )
            rows = cur.fetchall()
            rejected_pids = {r["placeID"] if isinstance(
                r, dict) else r[0] for r in rows}
        except Exception as e:
            print(f"[places_resolver] registry_rejected_places error: {e}")
        finally:
            cur.close()

    # 4. Reserve immediately before every Text Search attempt (including retries).
    seen_places = in_bounds_places = None
    best, best_score = None, 0.0
    data = _text_search(
        name, address, barangay, post=_post,
        reserve=lambda: reserve_call("imp_ts", TS_MONTHLY_CAP, TS_DAILY_CAP),
    )
    call_outcome = getattr(_api_state, "outcome", None)
    if call_outcome in ("skipped_quota", "monthly_quota_exceeded",
                        "daily_quota_exceeded", "api_error"):
        return None, None, {
            "reason": call_outcome,
            "api_error": getattr(_api_state, "last_error", None),
            "budget_exhausted": call_outcome in (
                "skipped_quota", "monthly_quota_exceeded", "daily_quota_exceeded"
            ),
        }
    discarded_rejected = False
    seen_places = len(data.get("places", []) or [])
    in_bounds_places = 0

    for p in data.get("places", []):
        loc = p.get("location") or {}
        lat, lng = loc.get("latitude"), loc.get("longitude")
        if lat is None or lng is None or not _is_within_municipal_bounds(lat, lng):
            continue
        in_bounds_places += 1

        pid = p.get("id")
        if pid and pid in rejected_pids:
            discarded_rejected = True
            continue
        if preferred_place_id and pid == preferred_place_id:
            best, best_score = p, 1.0
            break

        poi_types = p.get("types", []) or []
        if p.get("primaryType"):
            poi_types = list(poi_types) + [p.get("primaryType")]
        s = similarity(name, (p.get("displayName") or {}).get(
            "text", ""), reg_line=line_of_business, poi_types=poi_types)
        if s > best_score:
            best, best_score = p, s

    if best and best_score >= REVIEW_MIN:
        status = "review" if discarded_rejected else (
            "auto" if best_score >= AUTO_ACCEPT else "review")
        return best["location"]["latitude"], best["location"]["longitude"], {
            "coord_source": "places",
            "place_id": best["id"],
            "place_id_kind": "poi",
            "score": round(best_score, 3),
            "match_status": status,
            "match_type": "places_poi",
            "resolve_key": current_key,
        }
    elif discarded_rejected:
        return None, None, {
            "coord_source": None,
            "place_id": None,
            "place_id_kind": None,
            "score": None,
            "match_status": "review",
            "match_type": "rejected_place_discarded",
            "resolve_key": current_key,
        }

    if _halted:
        return None, None, {"reason": "api_error", "api_error": str(_halted)}

    # 5. Geocode Fallback
    geocode_budget_exhausted = False
    if not refresh_geocode and address and reserve_geocode:
        if reserve_geocode():
            g = _geocode_fallback(address, barangay, get=_get)
            if g:
                g["meta"]["resolve_key"] = current_key
                return g["lat"], g["lng"], g["meta"]
        else:
            geocode_budget_exhausted = True
            print("[places_resolver budget] Geocode daily/monthly cap reached; skipping fallback")

    if _halted:
        return None, None, {"reason": "api_error", "api_error": str(_halted)}
    if getattr(_api_state, "outcome", None) == "skipped_quota":
        return None, None, {
            "reason": "skipped_quota",
            "quota_kind": getattr(_api_state, "quota_reason", None) or "geocode",
            "budget_exhausted": True,
            "api_error": getattr(_api_state, "last_error", None),
        }
    if getattr(_api_state, "outcome", None) == "api_error":
        return None, None, {
            "reason": "api_error",
            "api_error": getattr(_api_state, "last_error", None),
        }

    meta = {"resolve_key": current_key}
    if geocode_budget_exhausted:
        meta["budget_exhausted"] = True
        meta["reason"] = "skipped_quota"
        meta["quota_kind"] = "geocode"
    if seen_places is not None:
        if seen_places == 0:
            meta["reason"] = "no_text_results"
        elif not in_bounds_places:
            meta["reason"] = "out_of_bounds"
        else:
            meta["reason"] = "below_threshold"
            meta["best_score"] = round(best_score, 3)
            meta["best_name"] = ((best or {}).get("displayName") or {}).get("text")
    return None, None, meta


def record_coord_meta(cursor, business_id, meta):
    """Persist provenance for coordinates written by CSV, Places, or Geocoding."""
    if not meta:
        return
    resolve_key = meta.get("resolve_key")
    if meta.get("coord_source") == "csv":
        if resolve_key:
            cursor.execute(
                "UPDATE official_registry SET coordSource='csv', resolveKey=%s WHERE businessID=%s", (resolve_key, business_id))
        else:
            cursor.execute(
                "UPDATE official_registry SET coordSource='csv' WHERE businessID=%s", (business_id,))
        return
    cursor.execute(
        """UPDATE official_registry SET coordSource=%s, placeID=%s, placeIDKind=%s,
           coordFetchedAt=NOW(), matchScore=%s, matchStatus=%s,
           resolveKey=COALESCE(%s, resolveKey) WHERE businessID=%s""",
        (meta.get("coord_source"), meta.get("place_id"), meta.get("place_id_kind"),
         meta.get("score"), meta.get("match_status"), resolve_key, business_id))


# ------------------------------ pins (geospatial_logs) -----------------------
def _update_pin(cursor, barangay_id, name, old_lat, old_lng, new_lat, new_lng, business_id=None):
    """Update the map pin only if it is still a copy of the registry coordinate being replaced."""
    if old_lat is None or old_lng is None:
        return
    if business_id:
        cursor.execute(
            """UPDATE geospatial_logs SET latitude=%s, longitude=%s
               WHERE ((businessID = %s) OR (businessID IS NULL AND barangayID=%s AND detectedName=%s))
                 AND ABS(latitude-%s) < 0.000001 AND ABS(longitude-%s) < 0.000001""",
            (new_lat, new_lng, business_id, barangay_id, name, float(old_lat), float(old_lng)))
    else:
        cursor.execute(
            """UPDATE geospatial_logs SET latitude=%s, longitude=%s
               WHERE barangayID=%s AND detectedName=%s
                 AND ABS(latitude-%s) < 0.000001 AND ABS(longitude-%s) < 0.000001""",
            (new_lat, new_lng, barangay_id, name, float(old_lat), float(old_lng)))


def _g(row, key, idx):
    return row[key] if isinstance(row, dict) else row[idx]


# ------------------------------ maintenance ----------------------------------
def refresh_expired_coords(limit=500):
    """Renew Google-derived coordinates older than REFRESH_AFTER_DAYS via Place Details (Essentials)."""
    if not enabled():
        return {"refreshed": 0, "skipped": "resolver disabled"}
    if not os.getenv("GOOGLE_MAPS_API_KEY") or _halted:
        return {"refreshed": 0, "skipped": "no key or halted"}
    reset_run_state()
    cur = mysql.connection.cursor()
    cur.execute(
        """SELECT businessID, barangayID, businessName, latitude, longitude, placeID
           FROM official_registry
           WHERE coordSource IN ('places','geocode') AND placeID IS NOT NULL
             AND matchStatus IS NOT NULL AND matchStatus NOT IN ('rejected', 'approved')
             AND (coordFetchedAt IS NULL OR coordFetchedAt < NOW() - INTERVAL %s DAY)
           ORDER BY coordFetchedAt IS NULL DESC, coordFetchedAt ASC LIMIT %s""",
        (REFRESH_AFTER_DAYS, int(limit)))
    rows = cur.fetchall()
    done = failed = 0
    for r in rows:
        if _halted or getattr(_api_state, "quota_halted", False):
            break
        bid, brgy, name = _g(r, "businessID", 0), _g(
            r, "barangayID", 1), _g(r, "businessName", 2)
        olat, olng, pid = _g(r, "latitude", 3), _g(
            r, "longitude", 4), _g(r, "placeID", 5)
        data = _places_request(
            "PlaceDetails",
            lambda: requests.get(PLACE_DETAILS_URL.format(pid=pid), timeout=10, headers={
                "X-Goog-Api-Key": os.getenv("GOOGLE_MAPS_API_KEY", ""),
                "X-Goog-FieldMask": "location",
            }),
            lambda: reserve_call("imp_pd", PD_MONTHLY_CAP, PD_DAILY_CAP),
        )
        if data is None and getattr(_api_state, "outcome", None) in (
            "skipped_quota", "monthly_quota_exceeded", "daily_quota_exceeded"
        ):
            break
        loc = (data or {}).get("location")
        if not loc:
            failed += 1
            continue
        cur.execute("UPDATE official_registry SET latitude=%s, longitude=%s, coordFetchedAt=NOW() "
                    "WHERE businessID=%s", (loc["latitude"], loc["longitude"], bid))
        _update_pin(cur, brgy, name, olat, olng,
                    loc["latitude"], loc["longitude"], business_id=bid)
        mysql.connection.commit()
        done += 1
    cur.close()
    return {"refreshed": done, "failed": failed, "candidates": len(rows)}


def purge_expired_coords(dry_run=True):
    """Safety net: clear Google-derived coordinates that were not refreshed in time (>= PURGE_AFTER_DAYS).
    Defaults to dry_run so nothing is deleted until you choose to."""
    cur = mysql.connection.cursor()
    cur.execute(
        """SELECT businessID, barangayID, businessName, latitude, longitude FROM official_registry
           WHERE coordSource IN ('places','geocode') AND latitude IS NOT NULL
             AND coordFetchedAt < NOW() - INTERVAL %s DAY""", (PURGE_AFTER_DAYS,))
    rows = cur.fetchall()
    if not dry_run:
        for r in rows:
            bid, brgy, name = _g(r, "businessID", 0), _g(
                r, "barangayID", 1), _g(r, "businessName", 2)
            _update_pin(cur, brgy, name, _g(r, "latitude", 3), _g(
                r, "longitude", 4), None, None, business_id=bid)
            cur.execute(
                "UPDATE official_registry SET latitude=NULL, longitude=NULL WHERE businessID=%s", (bid,))
        mysql.connection.commit()
    cur.close()
    return {"expired": len(rows), "dry_run": dry_run}


# ------------------------------ review queue ---------------------------------
def list_review_queue(page=1, per_page=20, search=""):
    cur = mysql.connection.cursor()
    try:
        from api.registry.reverify import _ensure_history_table
        _ensure_history_table(cur)
        search_term = str(search or "").strip()
        search_pattern = f"%{search_term}%"
        cur.execute(
            """SELECT COUNT(*) AS c
               FROM official_registry r
               LEFT JOIN barangays b ON r.barangayID = b.barangayID
               WHERE r.matchStatus='review'
                 AND (%s = '' OR r.businessName LIKE %s
                      OR CAST(r.businessID AS CHAR) LIKE %s
                      OR r.businessAddress LIKE %s
                      OR b.barangayName LIKE %s)""",
            (search_term, search_pattern, search_pattern, search_pattern, search_pattern),
        )
        row = cur.fetchone()
        total = int(_g(row, "c", 0))
        cur.execute(
            """SELECT r.businessID, r.barangayID, b.barangayName, r.businessName, r.businessAddress,
                      COALESCE(h.newLat, r.latitude) AS latitude,
                      COALESCE(h.newLng, r.longitude) AS longitude,
                      COALESCE(h.placeID, r.placeID) AS placeID,
                      r.latitude AS originalLatitude, r.longitude AS originalLongitude,
                      h.id AS reviewHistoryID,
                      r.coordSource, r.matchScore, r.matchStatus
               FROM official_registry r
               LEFT JOIN barangays b ON r.barangayID = b.barangayID
               LEFT JOIN registry_pin_history h
                 ON h.id = (
                     SELECT MAX(h2.id) FROM registry_pin_history h2
                     WHERE h2.businessID = r.businessID AND h2.outcome = 'review'
                 )
               WHERE r.matchStatus='review'
                 AND (%s = '' OR r.businessName LIKE %s
                      OR CAST(r.businessID AS CHAR) LIKE %s
                      OR r.businessAddress LIKE %s
                      OR b.barangayName LIKE %s)
               ORDER BY r.businessID LIMIT %s OFFSET %s""",
            (
                search_term, search_pattern, search_pattern, search_pattern,
                search_pattern, per_page, max(0, (page - 1) * per_page),
            ))
        items = []
        for r in cur.fetchall():
            d = dict(r) if isinstance(r, dict) else dict(zip(
                ["businessID", "barangayID", "barangayName", "businessName", "businessAddress", "latitude",
                 "longitude", "placeID", "originalLatitude", "originalLongitude", "reviewHistoryID",
                 "coordSource", "matchScore", "matchStatus"], r))
            for k in ("latitude", "longitude", "originalLatitude", "originalLongitude", "matchScore"):
                d[k] = float(d[k]) if d.get(k) is not None else None
            d.setdefault("originalLatitude", d.get("latitude"))
            d.setdefault("originalLongitude", d.get("longitude"))
            d.setdefault("reviewHistoryID", None)
            d["mapsUrl"] = (f"https://www.google.com/maps/search/?api=1&query=x&query_place_id={d['placeID']}"
                            if d.get("placeID") else None)
            items.append(d)
        return {"data": items, "total": total, "page": page, "limit": per_page}, None
    except Exception as e:
        return None, str(e)
    finally:
        cur.close()


def decide_review(business_id, approve):
    cur = mysql.connection.cursor()
    try:
        from api.registry.reverify import _ensure_history_table
        _ensure_history_table(cur)
        cur.execute("SELECT barangayID, businessName, latitude, longitude, placeID FROM official_registry "
                    "WHERE businessID=%s AND matchStatus='review'", (business_id,))
        r = cur.fetchone()
        if not r:
            return False, "Not found or not awaiting review"
        cur.execute(
            """SELECT id AS reviewHistoryID, newLat, newLng, placeID, score
               FROM registry_pin_history
               WHERE businessID=%s AND outcome='review'
               ORDER BY id DESC LIMIT 1""",
            (business_id,),
        )
        proposal = cur.fetchone()
        proposal_id = (
            proposal.get("reviewHistoryID") if isinstance(proposal, dict)
            else proposal[0] if proposal else None
        )
        proposal_lat = (
            proposal.get("newLat") if isinstance(proposal, dict)
            else proposal[1] if proposal else None
        )
        proposal_lng = (
            proposal.get("newLng") if isinstance(proposal, dict)
            else proposal[2] if proposal else None
        )
        proposal_place_id = (
            proposal.get("placeID") if isinstance(proposal, dict)
            else proposal[3] if proposal else None
        )
        proposal_score = (
            proposal.get("score") if isinstance(proposal, dict)
            else proposal[4] if proposal else None
        )
        has_reverify_proposal = (
            proposal_id is not None
            and proposal_lat is not None
            and proposal_lng is not None
        )
        if approve:
            if has_reverify_proposal:
                cur.execute(
                    """UPDATE official_registry
                       SET latitude=%s, longitude=%s, placeID=%s, placeIDKind='poi',
                           matchScore=%s, coordFetchedAt=NOW(),
                           matchStatus='approved', coordSource='manual'
                       WHERE businessID=%s AND matchStatus='review'""",
                    (proposal_lat, proposal_lng, proposal_place_id, proposal_score, business_id),
                )
                _update_pin(
                    cur,
                    _g(r, "barangayID", 0),
                    _g(r, "businessName", 1),
                    _g(r, "latitude", 2),
                    _g(r, "longitude", 3),
                    proposal_lat,
                    proposal_lng,
                    business_id=business_id,
                )
                cur.execute(
                    "UPDATE registry_pin_history SET outcome='review_approved' WHERE id=%s",
                    (proposal_id,),
                )
            else:
                cur.execute(
                    "UPDATE official_registry SET matchStatus='approved', coordSource='manual' WHERE businessID=%s",
                    (business_id,),
                )
        else:
            pid = proposal_place_id if has_reverify_proposal else _g(r, "placeID", 4)
            if pid:
                cur.execute(
                    "INSERT IGNORE INTO registry_rejected_places (businessID, placeID) VALUES (%s, %s)",
                    (business_id, pid)
                )
            if has_reverify_proposal:
                cur.execute(
                    "UPDATE official_registry SET matchStatus=NULL, matchScore=NULL WHERE businessID=%s",
                    (business_id,),
                )
                cur.execute(
                    "UPDATE registry_pin_history SET outcome='review_rejected' WHERE id=%s",
                    (proposal_id,),
                )
            else:
                _update_pin(cur, _g(r, "barangayID", 0), _g(r, "businessName", 1),
                            _g(r, "latitude", 2), _g(r, "longitude", 3), None, None, business_id=business_id)
                cur.execute("""UPDATE official_registry SET matchStatus='rejected', latitude=NULL, longitude=NULL,
                               placeID=NULL, placeIDKind=NULL, coordSource=NULL, coordFetchedAt=NULL
                               WHERE businessID=%s""", (business_id,))
        mysql.connection.commit()
        return True, None
    except Exception as e:
        mysql.connection.rollback()
        return False, str(e)
    finally:
        cur.close()
