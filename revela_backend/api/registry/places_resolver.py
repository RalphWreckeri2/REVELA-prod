"""
api/registry/places_resolver.py

Resolve a BPLO business to a map pin using Google Places API (New) Text Search, falling
back to the Geocoding API. Designed to stay inside Google's free monthly SKU thresholds
and to respect the 30-day cache limit on Google-derived lat/lng.

Everything is OFF by default: set PLACES_RESOLVER_ENABLED=1 to turn it on.

Environment variables (all optional unless noted)
  PLACES_RESOLVER_ENABLED   "1" to enable (default "0" => legacy geocode behaviour)
  GOOGLE_MAPS_API_KEY       required (already used by service.py)
  GEO_MUNICIPALITY / GEO_PROVINCE      default Mataasnakahoy / Batangas
  PLACES_CENTER             "lat,lng"  -> adds a location bias to Text Search (unset = no bias)
  PLACES_BBOX               "min_lat,max_lat,min_lng,max_lng" -> reject results outside (unset = no check)
  PLACES_BIAS_RADIUS_M      default 8000
  PLACES_AUTO_ACCEPT        default 0.80   name-similarity >= this: accept as 'auto'
  PLACES_REVIEW_MIN         default 0.55   between REVIEW_MIN and AUTO_ACCEPT: 'review'
  TS_MONTHLY_CAP / TS_DAILY_CAP   Text Search Pro budget (default 2500 / 500). Free cap is 5,000/mo
                                  PER SKU: if api/flags/service.py also calls Text Search, the SUM of both
                                  caps must stay below 5,000.
  PD_MONTHLY_CAP / PD_DAILY_CAP   Place Details (refresh) budget (default 3000 / 500)

Scheduled maintenance (cron / task scheduler), inside an app context:
    from api.registry.places_resolver import refresh_expired_coords, purge_expired_coords
    refresh_expired_coords()              # ~ daily; renews coords older than 20 days
    purge_expired_coords(dry_run=False)   # safety net; clears Google coords older than 28 days
"""
import os
import re
from difflib import SequenceMatcher

import requests

from app import mysql

PLACES_SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"
PLACE_DETAILS_URL = "https://places.googleapis.com/v1/places/{pid}"
GEOCODE_URL = "https://maps.googleapis.com/maps/api/geocode/json"

MUNICIPALITY = os.getenv("GEO_MUNICIPALITY", "Mataasnakahoy")
PROVINCE = os.getenv("GEO_PROVINCE", "Batangas")
BIAS_RADIUS_M = float(os.getenv("PLACES_BIAS_RADIUS_M", "8000"))
AUTO_ACCEPT = float(os.getenv("PLACES_AUTO_ACCEPT", "0.80"))
REVIEW_MIN = float(os.getenv("PLACES_REVIEW_MIN", "0.55"))
TS_MONTHLY_CAP = int(os.getenv("TS_MONTHLY_CAP", "2500"))
TS_DAILY_CAP = int(os.getenv("TS_DAILY_CAP", "500"))
PD_MONTHLY_CAP = int(os.getenv("PD_MONTHLY_CAP", "3000"))
PD_DAILY_CAP = int(os.getenv("PD_DAILY_CAP", "500"))
REFRESH_AFTER_DAYS = 20
PURGE_AFTER_DAYS = 28

_halted = None  # set to a message after a 401/403 so we stop spending calls until restart


def enabled():
    return os.getenv("PLACES_RESOLVER_ENABLED", "0") == "1"


def _floats(env, n):
    raw = os.getenv(env, "").strip()
    if not raw:
        return None
    try:
        vals = tuple(float(x) for x in raw.split(","))
    except ValueError:
        return None
    return vals if len(vals) == n else None


def _in_bbox(lat, lng):
    box = _floats("PLACES_BBOX", 4)
    if not box:
        return True  # no verified bounding box configured: rely on query + location bias
    return box[0] <= lat <= box[1] and box[2] <= lng <= box[3]


# ------------------------------ matching ------------------------------------
_STOP = {"inc", "corp", "corporation", "co", "company", "ltd", "enterprises",
         "enterprise", "trading", "services", "service", "the", "and", "of", "opc"}


def normalize(s):
    s = (s or "").lower().replace("&", " and ")
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    return " ".join(t for t in s.split() if t not in _STOP)


def similarity(a, b):
    ta, tb = normalize(a).split(), normalize(b).split()
    if not ta or not tb:
        return 0.0
    seq = SequenceMatcher(None, " ".join(sorted(ta)), " ".join(sorted(tb))).ratio()
    sa, sb = set(ta), set(tb)
    overlap = len(sa & sb) / min(len(sa), len(sb))
    # Containment is only strong evidence for longer names; short names (often just a surname)
    # must not auto-accept, so they cap below AUTO_ACCEPT and go to human review.
    m = min(len(sa), len(sb))
    weight = 0.9 if m >= 3 else (0.75 if m == 2 else 0.6)
    return max(seq, overlap * weight)


# ------------------------------ budget guard ---------------------------------
_MONTH_KEY = "DATE_SUB(CURDATE(), INTERVAL DAYOFMONTH(CURDATE()) - 1 DAY)"
_table_ready = False


def reserve_call(prefix, monthly_cap, daily_cap):
    """Atomically take one call from the monthly + daily budget (same table/pattern as
    service._reserve_geocode_call). Returns False when over budget or on any DB problem (fail closed).
    Note: like the existing helper, this commits on the shared request connection."""
    global _table_ready
    mk, dk = f"{prefix}_month", f"{prefix}_day"
    cur = mysql.connection.cursor()
    try:
        if not _table_ready:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS places_api_usage (
                    usageDate DATE NOT NULL, kind VARCHAR(20) NOT NULL,
                    requestCount INT NOT NULL DEFAULT 0, PRIMARY KEY (usageDate, kind)
                ) ENGINE=InnoDB
            """)
            _table_ready = True
        cur.execute(f"INSERT IGNORE INTO places_api_usage (usageDate, kind, requestCount) "
                    f"VALUES ({_MONTH_KEY}, %s, 0)", (mk,))
        cur.execute("INSERT IGNORE INTO places_api_usage (usageDate, kind, requestCount) "
                    "VALUES (CURDATE(), %s, 0)", (dk,))
        cur.execute(f"UPDATE places_api_usage SET requestCount = requestCount + 1 "
                    f"WHERE usageDate = {_MONTH_KEY} AND kind = %s AND requestCount < %s", (mk, monthly_cap))
        month_ok = cur.rowcount == 1
        day_ok = False
        if month_ok:
            cur.execute("UPDATE places_api_usage SET requestCount = requestCount + 1 "
                        "WHERE usageDate = CURDATE() AND kind = %s AND requestCount < %s", (dk, daily_cap))
            day_ok = cur.rowcount == 1
            if not day_ok:
                cur.execute(f"UPDATE places_api_usage SET requestCount = requestCount - 1 "
                            f"WHERE usageDate = {_MONTH_KEY} AND kind = %s", (mk,))
        mysql.connection.commit()
        return month_ok and day_ok
    except Exception as e:
        mysql.connection.rollback()
        print(f"[places_resolver budget] error, skipping call: {e}")
        return False
    finally:
        cur.close()


def _api_get_json(resp, label):
    """Return parsed JSON for 200; halt the resolver on 401/403; None otherwise."""
    global _halted
    if resp.status_code == 200:
        return resp.json()
    if resp.status_code in (401, 403):
        _halted = f"{label} {resp.status_code}: {resp.text[:200]}"
        print(f"[places_resolver] HALTED until restart -> {_halted}")
    else:
        print(f"[places_resolver] {label} HTTP {resp.status_code}")
    return None


# ------------------------------ resolution -----------------------------------
def _text_search(name, address, barangay, post=requests.post):
    parts = [str(p).strip() for p in (name, address, barangay, MUNICIPALITY, PROVINCE)
             if p is not None and str(p).strip() and str(p).strip().lower() != "nan"]
    body = {"textQuery": ", ".join(parts), "regionCode": "PH", "pageSize": 5}
    center = _floats("PLACES_CENTER", 2)
    if center:
        body["locationBias"] = {"circle": {
            "center": {"latitude": center[0], "longitude": center[1]}, "radius": BIAS_RADIUS_M}}
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": os.getenv("GOOGLE_MAPS_API_KEY", ""),
        # Pro-tier fields only. Do NOT add Enterprise fields (rating, phone, website, hours, reviews).
        "X-Goog-FieldMask": "places.id,places.displayName,places.location,places.businessStatus",
    }
    try:
        return _api_get_json(post(PLACES_SEARCH_URL, headers=headers, json=body, timeout=10), "TextSearch") or {}
    except requests.RequestException as e:
        print(f"[places_resolver] TextSearch network error: {e}")
        return {}


def _geocode_fallback(address, barangay, get=requests.get):
    parts = [str(p).strip() for p in (address, barangay, MUNICIPALITY, PROVINCE, "Philippines")
             if p is not None and str(p).strip() and str(p).strip().lower() != "nan"]
    params = {"address": ", ".join(parts), "components": "country:PH",
              "key": os.getenv("GOOGLE_MAPS_API_KEY", "")}
    try:
        data = _api_get_json(get(GEOCODE_URL, params=params, timeout=10), "Geocode") or {}
    except requests.RequestException as e:
        print(f"[places_resolver] Geocode network error: {e}")
        return None
    if data.get("status") in ("REQUEST_DENIED", "OVER_DAILY_LIMIT", "OVER_QUERY_LIMIT"):
        global _halted
        _halted = f"Geocode {data.get('status')}"
        print(f"[places_resolver] HALTED until restart -> {_halted}")
        return None
    if data.get("status") != "OK" or not data.get("results"):
        return None
    top = data["results"][0]
    loc = top["geometry"]["location"]
    lt = top["geometry"].get("location_type", "")
    lat, lng = loc["lat"], loc["lng"]
    if not _in_bbox(lat, lng):
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


def resolve_location(name, address, barangay, reserve_geocode=None,
                     _post=requests.post, _get=requests.get):
    """Returns (lat, lng, meta). (None, None, None) when unresolved/over budget (row still saved)."""
    if not os.getenv("GOOGLE_MAPS_API_KEY") or _halted:
        return None, None, None

    if reserve_call("imp_ts", TS_MONTHLY_CAP, TS_DAILY_CAP):
        data = _text_search(name, address, barangay, post=_post)
        best, best_score = None, 0.0
        for p in data.get("places", []):
            loc = p.get("location") or {}
            lat, lng = loc.get("latitude"), loc.get("longitude")
            if lat is None or lng is None or not _in_bbox(lat, lng):
                continue
            if p.get("businessStatus") == "CLOSED_PERMANENTLY":
                continue
            s = similarity(name, (p.get("displayName") or {}).get("text", ""))
            if s > best_score:
                best, best_score = p, s
        if best and best_score >= REVIEW_MIN:
            status = "auto" if best_score >= AUTO_ACCEPT else "review"
            return best["location"]["latitude"], best["location"]["longitude"], {
                "coord_source": "places", "place_id": best["id"], "place_id_kind": "poi",
                "score": round(best_score, 3), "match_status": status, "match_type": "places_poi"}
    if _halted:
        return None, None, None

    if address and reserve_geocode and reserve_geocode():
        g = _geocode_fallback(address, barangay, get=_get)
        if g:
            return g["lat"], g["lng"], g["meta"]
    return None, None, None


def record_coord_meta(cursor, business_id, meta):
    """Persist provenance for coordinates we just wrote. No-op when the resolver is disabled
    (so the new columns are never touched before the migration is applied)."""
    if not enabled() or not meta:
        return
    if meta["coord_source"] == "csv":
        cursor.execute("UPDATE official_registry SET coordSource='csv' WHERE businessID=%s", (business_id,))
        return
    cursor.execute(
        """UPDATE official_registry SET coordSource=%s, placeID=%s, placeIDKind=%s,
           coordFetchedAt=NOW(), matchScore=%s, matchStatus=%s WHERE businessID=%s""",
        (meta["coord_source"], meta["place_id"], meta["place_id_kind"],
         meta["score"], meta["match_status"], business_id))


# ------------------------------ pins (geospatial_logs) -----------------------
def _update_pin(cursor, barangay_id, name, old_lat, old_lng, new_lat, new_lng):
    """Update the map pin only if it is still a copy of the registry coordinate being replaced."""
    if old_lat is None or old_lng is None:
        return
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
    cur = mysql.connection.cursor()
    cur.execute(
        """SELECT businessID, barangayID, businessName, latitude, longitude, placeID
           FROM official_registry
           WHERE coordSource IN ('places','geocode') AND placeID IS NOT NULL
             AND matchStatus IS NOT NULL AND matchStatus <> 'rejected'
             AND (coordFetchedAt IS NULL OR coordFetchedAt < NOW() - INTERVAL %s DAY)
           ORDER BY coordFetchedAt IS NULL DESC, coordFetchedAt ASC LIMIT %s""",
        (REFRESH_AFTER_DAYS, int(limit)))
    rows = cur.fetchall()
    done = failed = 0
    for r in rows:
        if _halted or not reserve_call("imp_pd", PD_MONTHLY_CAP, PD_DAILY_CAP):
            break
        bid, brgy, name = _g(r, "businessID", 0), _g(r, "barangayID", 1), _g(r, "businessName", 2)
        olat, olng, pid = _g(r, "latitude", 3), _g(r, "longitude", 4), _g(r, "placeID", 5)
        try:
            resp = requests.get(PLACE_DETAILS_URL.format(pid=pid), timeout=10, headers={
                "X-Goog-Api-Key": os.getenv("GOOGLE_MAPS_API_KEY", ""),
                "X-Goog-FieldMask": "id,location"})
            data = _api_get_json(resp, "PlaceDetails")
        except requests.RequestException:
            data = None
        loc = (data or {}).get("location")
        if not loc:
            failed += 1
            continue
        cur.execute("UPDATE official_registry SET latitude=%s, longitude=%s, coordFetchedAt=NOW() "
                    "WHERE businessID=%s", (loc["latitude"], loc["longitude"], bid))
        _update_pin(cur, brgy, name, olat, olng, loc["latitude"], loc["longitude"])
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
            bid, brgy, name = _g(r, "businessID", 0), _g(r, "barangayID", 1), _g(r, "businessName", 2)
            _update_pin(cur, brgy, name, _g(r, "latitude", 3), _g(r, "longitude", 4), None, None)
            cur.execute("UPDATE official_registry SET latitude=NULL, longitude=NULL WHERE businessID=%s", (bid,))
        mysql.connection.commit()
    cur.close()
    return {"expired": len(rows), "dry_run": dry_run}


# ------------------------------ review queue ---------------------------------
def list_review_queue(page=1, per_page=20):
    cur = mysql.connection.cursor()
    try:
        cur.execute("SELECT COUNT(*) AS c FROM official_registry WHERE matchStatus='review'")
        row = cur.fetchone()
        total = int(_g(row, "c", 0))
        cur.execute(
            """SELECT businessID, barangayID, businessName, businessAddress, latitude, longitude,
                      placeID, coordSource, matchScore FROM official_registry
               WHERE matchStatus='review' ORDER BY businessID LIMIT %s OFFSET %s""",
            (per_page, max(0, (page - 1) * per_page)))
        items = []
        for r in cur.fetchall():
            d = dict(r) if isinstance(r, dict) else dict(zip(
                ["businessID", "barangayID", "businessName", "businessAddress", "latitude",
                 "longitude", "placeID", "coordSource", "matchScore"], r))
            for k in ("latitude", "longitude", "matchScore"):
                d[k] = float(d[k]) if d.get(k) is not None else None
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
        cur.execute("SELECT barangayID, businessName, latitude, longitude FROM official_registry "
                    "WHERE businessID=%s AND matchStatus='review'", (business_id,))
        r = cur.fetchone()
        if not r:
            return False, "Not found or not awaiting review"
        if approve:
            cur.execute("UPDATE official_registry SET matchStatus='approved' WHERE businessID=%s", (business_id,))
        else:
            _update_pin(cur, _g(r, "barangayID", 0), _g(r, "businessName", 1),
                        _g(r, "latitude", 2), _g(r, "longitude", 3), None, None)
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
