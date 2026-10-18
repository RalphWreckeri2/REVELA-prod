import pandas as pd
import requests as http
import io
import math
import os
import re
import threading
from datetime import date
from app import mysql
from api.models.geospatial import insert_green_flag
from api.utils.cancellation import (
    commit_unless_cancelled,
    is_cancelled,
    set_cancel,
)
from api.registry import places_resolver
from api.registry.colors import (
    _effective_flag_color_sql,
    ladder_columns_available,
    status_to_color,
    registry_row_color_sql,
)
from api.models.geospatial import (
    SOURCE_COLUMN,
    SOURCE_REGISTRY,
    geospatial_source_column_exists,
    with_source,
)
from api.registry.locks import (
    BLACK_RELOCKED,
    WARNING_CLEARED,
    BlackLockedError,
    BlackBusinessDeletionForbidden,
    assert_business_deletable,
    assert_not_black_locked,
    is_black_locked,
    record_enforcement_event,
)
from api.utils.places_quota import (
    MANILA_DATE_SQL, read_usage, reserve_usage_slot,
)
from api.utils.quota_config import API_QUOTA_CONFIG
from api.utils import quota_settings


GOOGLE_MAPS_API_KEY = os.getenv("GOOGLE_MAPS_API_KEY")

# Column name aliases — maps whatever the Excel/CSV header is → our internal key.
# Add more aliases here if the BPLO file uses different headers.
COLUMN_MAP = {
    # business id
    "business_id":                     "Business ID",
    "businessid":                      "Business ID",
    "business_id_no":                  "Business ID",
    "business_no":                     "Business ID",
    "business_identification_no":      "Business ID",
    "business_identification_number":  "Business ID",
    "business_identification":         "Business ID",
    "businessidentificationno":        "Business ID",
    "id":                              "Business ID",
    "permit_no":                       "Business ID",
    "permit_number":                   "Business ID",

    # business name
    "business_name":       "businessName",
    "businessname":        "businessName",
    "name":                "businessName",
    "trade_name":          "businessName",
    "tradename":           "businessName",

    # business type
    "business_type":       "businessType",
    "type_of_business":    "businessType",
    "typeofbusiness":      "businessType",

    # line of business
    "line_of_business":    "lineOfBusiness",
    "lineofbusiness":      "lineOfBusiness",
    "line":                "lineOfBusiness",
    "business_activity":   "lineOfBusiness",

    # address
    "business_address":    "businessAddress",
    "businessaddress":     "businessAddress",
    "address":             "businessAddress",
    "location":            "businessAddress",

    # barangay
    "barangay":            "barangay",
    "brgy":                "barangay",
    "barangay_name":       "barangay",
    "brgy_name":           "barangay",

    # application / permit status (license standing)
    "status":                   "applicationStatus",
    "application_status":       "applicationStatus",
    "status_of_application":    "applicationStatus",
    "statusofapplication":      "applicationStatus",

    # registration type (New vs Renewal)
    "status_of_registration":   "registrationType",
    "statusofregistration":     "registrationType",
    "registration_status":      "registrationType",
    "registrationstatus":       "registrationType",
    "registration_type":        "registrationType",
    "registrationtype":         "registrationType",
    "type_of_registration":     "registrationType",
    "typeofregistration":       "registrationType",

    # year of registration
    "year_of_registration":     "lastRenewalDate",
    "yearofregistration":       "lastRenewalDate",
    "year":                     "lastRenewalDate",

    # owner (we'll read it but not store it)
    "name_of_owner_applicant":  "ownerName",
    "nameofownerapplicant":     "ownerName",
    "owner":                    "ownerName",
    "applicant":                "ownerName",

    # barangay name
    "barangay_name":            "barangay",
    "barangayname":             "barangay",

    # size of business
    "size_of_business":         "businessSize",
    "sizeofbusiness":           "businessSize",
    "size":                     "businessSize",

    # renewal date / issue date
    "last_renewal_date":   "lastRenewalDate",
    "lastrenewaldate":     "lastRenewalDate",
    "renewal_date":        "lastRenewalDate",
    "renewaldate":         "lastRenewalDate",
    "issue_date":          "lastRenewalDate",
    "issuedate":           "lastRenewalDate",
    "date_issued":         "lastRenewalDate",
    "dateissued":          "lastRenewalDate",
    "date_of_issue":       "lastRenewalDate",
    "permit_date":         "lastRenewalDate",

    # coordinates if provided in CSV
    "latitude":            "latitude",
    "lat":                 "latitude",
    "longitude":           "longitude",
    "lng":                 "longitude",
    "long":                "longitude",
}

VALID_STATUSES = {"Active", "Expired", "Revoked", "Pending", "Closed"}

# Raw permit status (case-insensitive) -> canonical status. This is the only
# place a raw status is accepted. Anything not listed here is rejected.
_STATUS_ALIASES = {
    "active":         "Active",
    "expired":        "Expired",
    "revoked":        "Revoked",
    "blacklisted":    "Revoked",
    "pending":        "Pending",
    "for issuance":   "Pending",
    "cancelled":      "Revoked",
    "lapsed":         "Expired",
    "license issued": "Active",
    "issued":         "Active",
    "closed":         "Closed",
}
_geocode_state = threading.local()
_RETRYABLE_RESOLUTION_FAILURES = {
    "api_error",
    "skipped_quota",
    "monthly_quota_exceeded",
    "daily_quota_exceeded",
    "quota_ledger_error",
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _clean_str(val) -> str | None:
    """Safely convert any input to a stripped string, returning None for empty/null/NaN values."""
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None
    if isinstance(val, float) and val.is_integer():
        s = str(int(val)).strip()
    else:
        s = str(val).strip()
    if not s or s.lower() == "nan":
        return None
    return s


def _clean_upper(val) -> str | None:
    """Safely convert any input to an uppercase stripped string, returning None for empty/null/NaN values."""
    s = _clean_str(val)
    return s.upper() if s else None


def _parse_coordinate_pair(raw_lat, raw_lng):
    """Accept only finite latitude/longitude pairs in geographic ranges."""
    if raw_lat is None or raw_lng is None:
        return None
    try:
        lat, lng = float(raw_lat), float(raw_lng)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(lat) or not math.isfinite(lng):
        return None
    if not -90 <= lat <= 90 or not -180 <= lng <= 180:
        return None
    return lat, lng


def _coordinate_pair_within_municipality(coordinate_pair):
    if coordinate_pair is None:
        return False
    from api.flags.service import is_within_municipality_boundary

    return is_within_municipality_boundary(*coordinate_pair)


def _preserve_import_coordinates(coord_source, match_status, has_csv_coords):
    """Keep manual/approved pins, and trusted CSV pins absent a replacement coordinate."""
    source = (coord_source or "").strip().lower()
    status = (match_status or "").strip().lower()
    return (
        source == "manual"
        or status in ("approved", "review")
        or (source == "csv" and not has_csv_coords)
    )


def _clear_warning_for_active_import(cursor, business_id):
    """Clear a current warning when an authoritative import marks a business Active."""
    if not ladder_columns_available(cursor):
        return None

    cursor.execute(
        """SELECT warningLevel, blackLocked
           FROM enforcement_state
           WHERE subjectType = 'business' AND subjectID = %s
           FOR UPDATE""",
        (str(business_id),),
    )
    state = cursor.fetchone() or {}
    previous_level = _coerce_int(state.get("warningLevel"))
    if previous_level <= 0 or _coerce_int(state.get("blackLocked")):
        return None

    reason = "Cleared by Active permit status in registry import"
    cursor.execute(
        """UPDATE enforcement_state
           SET warningLevel = 0,
               warningBaseColor = NULL,
               warningClearedAt = NOW(),
               warningClearedBy = NULL,
               warningClearReason = %s
           WHERE subjectType = 'business' AND subjectID = %s
             AND warningLevel > 0 AND COALESCE(blackLocked, 0) = 0""",
        (reason, str(business_id)),
    )
    if cursor.rowcount != 1:
        return None

    record_enforcement_event(
        cursor,
        business_id=business_id,
        event_type=WARNING_CLEARED,
        reason=reason,
        previous_level=previous_level,
        new_level=0,
        previous_black=False,
        new_black=False,
    )
    return previous_level


def _resolution_key_for_cache(resolve_key, meta):
    """Do not cache outcomes that may succeed when quotas/API availability recover."""
    if not resolve_key or not meta:
        return resolve_key
    if meta.get("budget_exhausted") or meta.get("reason") in _RETRYABLE_RESOLUTION_FAILURES:
        return None
    return resolve_key


def _is_retryable_resolution_failure(meta):
    return bool(
        meta
        and (
            meta.get("budget_exhausted")
            or meta.get("reason") in _RETRYABLE_RESOLUTION_FAILURES
        )
    )


def _log_registry_places_summary(workflow, counts):
    usage = _places_usage_snapshot(workflow)
    if usage is None:
        return
    print(
        f"[{workflow}] summary "
        f"resolved={counts.get('resolved', 0)} no_match={counts.get('no_match', 0)} "
        f"skipped_quota={counts.get('skipped_quota', 0)} "
        f"api_error={counts.get('api_error', 0)} cache_hits={counts.get('cache_hits', 0)} "
        f"TextSearch calls today={usage['text_search']['day']} "
        f"month={usage['text_search']['month']}; "
        f"PlaceDetails calls today={usage['details']['day']} "
        f"month={usage['details']['month']}; "
        f"Geocoding calls today={usage['geocoding']['day']} "
        f"month={usage['geocoding']['month']}"
    )


def _places_usage_snapshot(workflow):
    try:
        return places_resolver.get_places_call_usage()
    except Exception as e:
        print(f"[{workflow}] summary usage lookup failed: {e}")
        return None


def normalize_business_address(raw_address, barangay_name=None) -> str | None:
    """Normalise messy imported addresses without blanking out valid values.

    The goal is to strip obvious location noise such as district / purok / barangay
    suffixes when they are attached to an otherwise usable street/building address,
    but to preserve the original cleaned value instead of returning None for every
    vague-but-real local description.
    """
    value = _clean_str(raw_address)
    if not value:
        return None

    value = value.replace("&", " and ")
    value = re.sub(r"\s+", " ", value).strip()

    replacements = {
        r"(?i)\bst\.?\b": "Street",
        r"(?i)\bave\.?\b": "Avenue",
        r"(?i)\bblvd\.?\b": "Boulevard",
        r"(?i)\brd\.?\b": "Road",
        r"(?i)\bdr\.?\b": "Drive",
        r"(?i)\bln\.?\b": "Lane",
    }
    for pattern, replacement in replacements.items():
        value = re.sub(pattern, replacement, value)

    # Strip district / barangay / purok / block type labels anywhere in the value,
    # since these are often appended as location metadata instead of the actual street.
    value = re.sub(
        r"(?i)\s*,?\s*(?:district|brgy|barangay)\s+[ivxlcdm0-9a-z.-]+", "", value)
    value = re.sub(
        r"(?i)\s*,?\s*(?:purok|blk|block|lot|phase|subd|subdivision)\s+[a-z0-9.-]+", "", value)
    value = re.sub(
        r"(?i)(?:\s*[.,;]?\s*(?:mataasnakahoy|batangas|philippines))+\s*$", "", value)

    value = re.sub(r"\s+", " ", value).strip(" ,;.-")
    value = re.sub(r"\s+([,.])", r"\1", value)

    # Preserve a cleaned raw value instead of nulling out valid local business addresses.
    if not value:
        fallback = _clean_str(raw_address) or ""
        return fallback.upper() if fallback else ""

    return value.strip(" ,;.-").upper()


def _normalise_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Rename raw CSV/Excel headers to our internal field names."""
    df.columns = [str(c).strip() for c in df.columns]
    rename = {}
    for col in df.columns:
        clean = col.lower().strip()
        key_stripped = clean.replace(" ", "_").replace(
            "-", "_").replace(".", "").replace(",", "")
        key_raw = clean.replace(" ", "_").replace("-", "_")
        if key_stripped in COLUMN_MAP:
            rename[col] = COLUMN_MAP[key_stripped]
        elif key_raw in COLUMN_MAP:
            rename[col] = COLUMN_MAP[key_raw]
    df = df.rename(columns=rename)
    return df


# free tier is 10,000/month
GEOCODE_MONTHLY_CAP = API_QUOTA_CONFIG.geocoding.monthly
# 1500 geocodes per day
GEOCODE_DAILY_CAP = API_QUOTA_CONFIG.geocoding.daily
# maximum 1500 businesses per import batch
MAX_IMPORT_PER_BATCH = int(os.getenv("MAX_IMPORT_PER_BATCH", "1500"))


def get_geocode_remaining_today():
    """Return remaining geocode requests allowed today."""
    usage = read_usage(mysql.connection, "geo_month", "geo_day")
    return max(0, quota_settings.cap("quota.geocoding.daily") - usage["day"])


def get_geocode_remaining_month():
    """Return remaining geocode requests allowed this month."""
    usage = read_usage(mysql.connection, "geo_month", "geo_day")
    return max(
        0, quota_settings.cap("quota.geocoding.monthly") - usage["month"]
    )


def _reserve_geocode_call():
    """Take one Geocoding request from the monthly + daily budget. False = over budget or DB problem."""
    try:
        allowed, _reason = reserve_usage_slot(
            mysql.connection, "geo_month", "geo_day",
            quota_settings.cap("quota.geocoding.monthly"),
            quota_settings.cap("quota.geocoding.daily"),
        )
        return allowed
    except Exception as e:
        print(f"[Geocode budget] error, skipping geocode: {e}")
        return False                 # fail closed


def reset_geocode_daily_quota() -> bool:
    """Reset the daily Manila-date geocoding counter to allow re-testing."""
    cur = mysql.connection.cursor()
    try:
        cur.execute(
            f"DELETE FROM places_api_usage WHERE usageDate = {MANILA_DATE_SQL} "
            "AND kind = 'geo_day'")
        mysql.connection.commit()
        return True
    except Exception as e:
        mysql.connection.rollback()
        print(f"[Geocode budget] reset error: {e}")
        return False
    finally:
        cur.close()


def _geocode(address: str, barangay: str) -> tuple[float | None, float | None]:
    """Call Google Geocoding API for a business address.
    Uses the full business address plus barangay for better accuracy.
    Returns (lat, lng) or (None, None) on failure."""
    _geocode_state.outcome = None
    api_key = os.getenv("GOOGLE_MAPS_API_KEY") or GOOGLE_MAPS_API_KEY
    if not api_key:
        _geocode_state.outcome = "api_error"
        print("[Geocode] API key is not configured")
        return None, None

    if not _reserve_geocode_call():
        try:
            _geocode_state.outcome = (
                "skipped_quota"
                if get_geocode_remaining_today() <= 0 or get_geocode_remaining_month() <= 0
                else "api_error"
            )
        except Exception as e:
            _geocode_state.outcome = "api_error"
            print(
                f"[Geocode] Could not read quota after reservation denial: {e}")
        print(f"[Geocode] request not sent: {_geocode_state.outcome}")
        return None, None            # row is still saved, just without coordinates

    address_parts = [
        str(part).strip() for part in [address, barangay, "Mataasnakahoy", "Batangas", "Philippines"]
        if _clean_str(part)
    ]
    full_address = ", ".join(address_parts)

    try:
        resp = http.get(
            "https://maps.googleapis.com/maps/api/geocode/json",
            params={"address": full_address, "key": api_key},
            timeout=10,
        )
        if resp.status_code != 200:
            _geocode_state.outcome = "api_error"
            print(
                f"[Geocode] HTTP {resp.status_code}: "
                f"{(getattr(resp, 'text', '') or '')[:1000]}"
            )
            return None, None
        data = resp.json()
        if data.get("status") == "OK":
            loc = data["results"][0]["geometry"]["location"]
            _geocode_state.outcome = None
            return loc["lat"], loc["lng"]
        status = data.get("status", "UNKNOWN_ERROR")
        if status in ("OVER_DAILY_LIMIT", "OVER_QUERY_LIMIT"):
            _geocode_state.outcome = "skipped_quota"
            print(f"[Geocode] quota response: {status}")
        elif status == "ZERO_RESULTS":
            _geocode_state.outcome = "no_match"
        else:
            _geocode_state.outcome = "api_error"
            print(
                f"[Geocode] API response: {status}: {data.get('error_message', '')[:500]}")
    except (http.RequestException, ValueError, KeyError, IndexError, TypeError) as e:
        _geocode_state.outcome = "api_error"
        print(f"[Geocode] request failed: {e}")
    return None, None


def search_address_candidates(
    street_address: str,
    barangay: str | None = None,
    *,
    get=http.get,
    reserve=None,
) -> tuple[list[dict] | None, str | None]:
    """Search a local address, retaining precision metadata for safe auto-resolution."""
    address = _clean_str(street_address)
    barangay_name = _clean_str(barangay) if barangay is not None else ""
    api_key = os.getenv("GOOGLE_MAPS_API_KEY") or GOOGLE_MAPS_API_KEY
    if not api_key:
        return None, "not_configured"
    if not address:
        return None, "invalid_request"

    reserve_call = reserve or _reserve_geocode_call
    if not reserve_call():
        return None, "quota_exceeded"

    address_parts = [address]
    if barangay_name:
        address_parts.append(barangay_name)
    address_parts.extend(["Mataasnakahoy", "Batangas", "Philippines"])
    full_address = ", ".join(address_parts)
    try:
        response = get(
            "https://maps.googleapis.com/maps/api/geocode/json",
            params={
                "address": full_address,
                "components": "country:PH",
                "region": "ph",
                "key": api_key,
            },
            timeout=10,
        )
    except http.RequestException:
        # Request exception text may include the API-key query parameter.
        print("[Geocode search] Network error")
        return None, "network_error"

    if response.status_code != 200:
        print(f"[Geocode search] HTTP {response.status_code}")
        return None, "provider_error"

    try:
        data = response.json()
    except (ValueError, TypeError):
        print("[Geocode search] Invalid JSON response")
        return None, "provider_error"

    if not isinstance(data, dict):
        return None, "provider_error"
    status = data.get("status")
    if status == "ZERO_RESULTS":
        return [], None
    if status in ("OVER_DAILY_LIMIT", "OVER_QUERY_LIMIT"):
        return None, "quota_exceeded"
    if status != "OK":
        return None, "provider_error"

    raw_results = data.get("results")
    if not isinstance(raw_results, list):
        return None, "provider_error"

    candidates = []
    for result in raw_results:
        if not isinstance(result, dict):
            continue
        geometry = result.get("geometry") or {}
        if not isinstance(geometry, dict):
            continue
        location = geometry.get("location") or {}
        if not isinstance(location, dict):
            continue
        try:
            lat = float(location["lat"])
            lng = float(location["lng"])
        except (KeyError, OverflowError, TypeError, ValueError):
            continue
        if (
            not math.isfinite(lat)
            or not math.isfinite(lng)
            or not -90 <= lat <= 90
            or not -180 <= lng <= 180
        ):
            continue
        formatted_address = str(result.get("formatted_address", "")).strip()
        if not formatted_address:
            continue
        candidates.append({
            "formattedAddress": formatted_address,
            "latitude": lat,
            "longitude": lng,
            "placeId": str(result.get("place_id", "")),
            "locationType": geometry.get("location_type"),
            "resultTypes": result.get("types"),
            # Google omits partial_match for a full match. Unknown/malformed
            # metadata remains unknown, rather than upgrading it to precise.
            "partialMatch": result.get("partial_match", False),
            "addressComponents": result.get("address_components"),
            # Count BEFORE filtering/capping: one surviving candidate must not
            # hide an ambiguous provider response.
            "providerResultCount": len(raw_results),
        })
        if len(candidates) == 5:
            break
    return candidates, None


def reverse_geocode_coordinates(
    latitude: float,
    longitude: float,
    *,
    get=http.get,
    reserve=None,
) -> tuple[str | None, str | None]:
    """Return the most precise formatted address for a validated GPS point."""
    api_key = os.getenv("GOOGLE_MAPS_API_KEY") or GOOGLE_MAPS_API_KEY
    if not api_key:
        return None, "not_configured"
    if (
        isinstance(latitude, bool)
        or isinstance(longitude, bool)
        or not isinstance(latitude, (int, float))
        or not isinstance(longitude, (int, float))
    ):
        return None, "invalid_request"
    try:
        latitude, longitude = float(latitude), float(longitude)
    except (OverflowError, TypeError, ValueError):
        return None, "invalid_request"
    if not (
        math.isfinite(latitude) and math.isfinite(longitude)
        and -90 <= latitude <= 90 and -180 <= longitude <= 180
    ):
        return None, "invalid_request"

    reserve_call = reserve or _reserve_geocode_call
    if not reserve_call():
        return None, "quota_exceeded"

    try:
        response = get(
            "https://maps.googleapis.com/maps/api/geocode/json",
            params={
                "latlng": f"{latitude:.6f},{longitude:.6f}",
                "result_type": (
                    "street_address|premise|subpremise|route|"
                    "point_of_interest|establishment"
                ),
                "key": api_key,
            },
            timeout=10,
        )
    except http.RequestException:
        print("[Reverse geocode] Network error")
        return None, "network_error"

    if response.status_code != 200:
        return None, "provider_error"

    try:
        data = response.json()
    except (ValueError, TypeError):
        return None, "provider_error"

    if not isinstance(data, dict):
        return None, "provider_error"
    status = data.get("status")
    if status == "ZERO_RESULTS":
        return None, None
    if status in ("OVER_DAILY_LIMIT", "OVER_QUERY_LIMIT"):
        return None, "quota_exceeded"
    if status != "OK":
        return None, "provider_error"

    results = data.get("results")
    if not isinstance(results, list):
        return None, "provider_error"
    for result in results:
        if not isinstance(result, dict):
            continue
        address = result.get("formatted_address")
        if isinstance(address, str) and address.strip():
            return address.strip(), None
    return None, "provider_error"


def _resolve_location(
    business_name,
    address,
    barangay,
    business_id=None,
    barangay_id=None,
    line_of_business=None,
    business_type=None,
    quota_scope="registry_import",
):
    """Returns (lat, lng, meta).
    PLACES_RESOLVER_ENABLED=1 -> Places Text Search (+ quality-gated geocode fallback), meta describes provenance.
    Otherwise -> legacy Geocoding, with the same explicit provenance metadata."""
    name_str = _clean_str(business_name) or ""
    addr_str = _clean_str(address) or ""
    brgy_str = _clean_str(barangay) or ""
    lob_str = _clean_str(line_of_business) or ""
    type_str = _clean_str(business_type) or ""

    if places_resolver.enabled():
        return places_resolver.resolve_location(
            name_str, addr_str, brgy_str,
            business_id=business_id,
            barangay_id=barangay_id,
            line_of_business=lob_str,
            business_type=type_str,
            reserve_geocode=_reserve_geocode_call,
            quota_scope=quota_scope)

    # Local BPLO data often contains only vague location labels such as "District IV"
    # or "Purok 5". In those cases, use the business name + barangay as a geocode
    # fallback instead of failing outright; it still places the pin in the correct barangay.
    geo_target = addr_str
    if not geo_target:
        geo_target = name_str or brgy_str

    if not geo_target and not brgy_str:
        return None, None, None

    resolve_key = places_resolver.compute_resolve_key(
        name_str, addr_str, barangay_id if barangay_id is not None else brgy_str
    )
    lat, lng = _geocode(geo_target, brgy_str)
    if lat is None and _geocode_state.outcome in ("api_error", "skipped_quota"):
        reason = _geocode_state.outcome
        return None, None, {
            "reason": reason,
            "budget_exhausted": reason == "skipped_quota",
            "resolve_key": resolve_key,
        }
    name_target = f"{name_str}, {brgy_str}" if name_str and brgy_str else name_str
    if lat is None and name_target and name_target != geo_target:
        lat, lng = _geocode(name_target, brgy_str)
    if lat is None and _geocode_state.outcome in ("api_error", "skipped_quota"):
        reason = _geocode_state.outcome
        return None, None, {
            "reason": reason,
            "budget_exhausted": reason == "skipped_quota",
            "resolve_key": resolve_key,
        }
    if lat is None:
        return None, None, {"reason": "no_geocode_results", "resolve_key": resolve_key}
    return lat, lng, {
        "coord_source": "geocode",
        "place_id": None,
        "place_id_kind": "address",
        "score": None,
        "match_status": "review",
        "resolve_key": resolve_key,
    }


DISTRICT_ALIASES = {
    "district i":   "Barangay I",
    "district ii":  "Barangay II",
    "district iii": "Barangay III",
    "district iv":  "Barangay IV",
}


def _load_barangay_lookup() -> dict[str, int]:
    """
    Load all barangays into a dict keyed by lowercased, stripped name.
    Used during bulk imports to avoid one DB cursor per row.
    Returns {lower_name: barangayID, ...}
    """
    cursor = mysql.connection.cursor()
    cursor.execute("SELECT barangayID, barangayName FROM barangays")
    rows = cursor.fetchall()
    cursor.close()
    lookup = {}
    for row in rows:
        name = _clean_str(row.get("barangayName"))
        if not name:
            continue
        lookup[name.lower()] = row["barangayID"]
        # Also index without spaces for fuzzy matching
        lookup[name.lower().replace(" ", "")] = row["barangayID"]
    return lookup


def _resolve_barangay_id(barangay_name, lookup: dict[str, int]) -> int | None:
    """
    Resolve a raw barangay name to a barangayID using a preloaded lookup dict.
    Falls back to partial matching when an exact match isn't found.
    """
    cleaned = _clean_str(barangay_name)
    if not cleaned:
        return None

    alias = DISTRICT_ALIASES.get(cleaned.lower())
    if alias:
        cleaned = alias

    # Exact match (case-insensitive via lowercasing)
    result = lookup.get(cleaned.lower())
    if result:
        return result

    # Partial match — strip spaces and try substring
    cleaned_nospace = cleaned.lower().replace(" ", "")
    result = lookup.get(cleaned_nospace)
    if result:
        return result

    # Substring fallback
    for key, bid in lookup.items():
        if cleaned.lower() in key or key in cleaned.lower():
            return bid
        if cleaned_nospace in key.replace(" ", "") or key.replace(" ", "") in cleaned_nospace:
            return bid

    return None


def _get_barangay_id(barangay_name: str) -> int | None:
    """
    Single-use lookup for callers outside of bulk import loops.
    Uses a fresh DB query — prefer _resolve_barangay_id + _load_barangay_lookup
    when processing many rows at once.
    """
    lookup = _load_barangay_lookup()
    return _resolve_barangay_id(barangay_name, lookup)


def _normalise_registration_type(raw) -> str | None:
    """Normalize registration type to 'NEW' or 'RENEWAL'."""
    if raw is None or (isinstance(raw, float) and pd.isna(raw)):
        return None
    val = str(raw).strip()
    if not val:
        return None
    val_lower = val.lower()
    if "renew" in val_lower:
        return "RENEWAL"
    if "new" in val_lower.split() or val_lower.startswith("new") or val_lower == "new":
        return "NEW"
    return val.upper()


def _normalise_status(raw: str) -> tuple[str | None, str | None]:
    """Map a raw permit status onto a canonical status.

    Returns (status, error). status is None and error is set when the value
    is blank or not a status this system recognises. Callers must reject the
    row: previously unrecognised values silently became "Pending", which
    turned typos, and statuses such as "Orange" or "Black", into Yellow.

    Only the aliases below are accepted. Flag colours (Red/Green/Yellow/
    Purple/Black/Orange) are not statuses and are rejected like any other
    unrecognised value.
    """
    cleaned = _clean_str(raw)
    if not cleaned:
        return None, ("missing permit status (expected one of "
                      f"{', '.join(sorted(VALID_STATUSES))})")
    status = _STATUS_ALIASES.get(cleaned.casefold())
    if status is None:
        return None, (
            f"unrecognised permit status {cleaned!r} (expected one of "
            f"{', '.join(sorted(VALID_STATUSES))})")
    return status, None


def _status_for_compare(raw) -> str | None:
    """Lenient status used only for change detection, never for storage.

    Legacy rows may hold values this build does not recognise. Comparing them
    by their own cleaned text keeps change detection correct instead of
    folding every unknown value into one bucket.
    """
    status, _ = _normalise_status(raw)
    if status is not None:
        return status
    cleaned = _clean_str(raw)
    return cleaned.casefold() if cleaned else None


def _status_to_flag_color(status: str) -> str:
    """Deprecated shim. Use api.registry.colors.status_to_color.

    This was a private copy of the status-only mapping. It now delegates, so
    the registry write paths and the SQL the Map renders cannot drift. It is
    called from four write paths (import, sync, snap and manual status edit);
    those must keep treating a status they do not recognise as Yellow.
    """
    return status_to_color(status)


def _parse_renewal_date(raw) -> str | None:
    """
    Safely parse a renewal date from raw input (string, datetime, int/float year).
    Avoids pandas interpreting integer year values (e.g. 2026) as epoch nanoseconds (1970).
    """
    if raw is None or (isinstance(raw, float) and pd.isna(raw)):
        return None
    try:
        if isinstance(raw, (int, float)) and 1900 <= int(raw) <= 2100:
            return f"{int(raw):04d}-01-01 00:00:00"
        raw_str = str(raw).strip()
        if raw_str.isdigit() and len(raw_str) == 4:
            return f"{int(raw_str):04d}-01-01 00:00:00"
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            return pd.to_datetime(raw, dayfirst=False).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return None


def _annual_expiration_eligible(status, renewal_date, current_year):
    """Match the scheduled rule: Active permits renewed before this calendar year."""
    if status != "Active" or not renewal_date:
        return False
    parsed_renewal_date = _parse_renewal_date(renewal_date)
    return bool(
        parsed_renewal_date
        and int(parsed_renewal_date[:4]) < current_year
    )


def _effective_import_status(status, renewal_date, current_year):
    """Derive the stored permit status using the scheduled annual rule."""
    if _annual_expiration_eligible(status, renewal_date, current_year):
        return "Expired"
    return status


def _sync_text_value(value):
    """Compare imported text without case or repeated-whitespace differences."""
    cleaned = _clean_str(value)
    return re.sub(r"\s+", " ", cleaned).strip().casefold() if cleaned else None


def _sync_upper_value(value):
    cleaned = _sync_text_value(value)
    return cleaned.upper() if cleaned else None


def _sync_barangay_value(value):
    """Compare database integer IDs with values returned as numeric strings."""
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        try:
            numeric_value = float(value)
            if math.isfinite(numeric_value) and numeric_value.is_integer():
                return int(numeric_value)
        except (TypeError, ValueError):
            pass
        cleaned = _clean_str(value)
        return cleaned.casefold() if cleaned else None


def _registry_sync_location_fields_unchanged(existing, name, address, barangay_id):
    return (
        _sync_upper_value(existing.get("businessName")
                          ) == _sync_upper_value(name)
        and _sync_text_value(existing.get("businessAddress")) == _sync_text_value(address)
        and _sync_barangay_value(existing.get("barangayID")) == _sync_barangay_value(barangay_id)
    )


def _sync_coordinate_value(value):
    if value is None:
        return None
    try:
        coordinate = float(value)
        return coordinate if math.isfinite(coordinate) else None
    except (TypeError, ValueError):
        return _sync_text_value(value)


def _sync_coord_meta_changed(existing, meta):
    if not meta:
        return False
    source = _sync_text_value(meta.get("coord_source"))
    if source != _sync_text_value(existing.get("coordSource")):
        return True
    resolve_key = meta.get("resolve_key")
    if resolve_key and resolve_key != existing.get("resolveKey"):
        return True
    if source == "csv":
        return False
    fields = (
        ("place_id", "placeID", _sync_text_value),
        ("place_id_kind", "placeIDKind", _sync_text_value),
        ("score", "matchScore", _sync_coordinate_value),
        ("match_status", "matchStatus", _sync_text_value),
    )
    return any(
        normalize(meta.get(meta_field)) != normalize(existing.get(db_field))
        for meta_field, db_field, normalize in fields
    )


def _registry_sync_business_fields_changed(existing, incoming):
    """Return whether normalized imported registry fields differ from storage."""
    fields = (
        ("businessName", _sync_upper_value, _sync_upper_value),
        ("businessType", _sync_upper_value, _sync_upper_value),
        ("lineOfBusiness", _sync_upper_value, _sync_upper_value),
        ("businessAddress", _sync_text_value, _sync_text_value),
        ("barangayID", _sync_barangay_value, _sync_barangay_value),
        ("applicationStatus", _status_for_compare, _status_for_compare),
        ("lastRenewalDate", _parse_renewal_date, _parse_renewal_date),
        ("businessSize", _sync_upper_value, _sync_upper_value),
        ("registrationType", _normalise_registration_type,
         _normalise_registration_type),
    )
    for field, normalize_existing, normalize_incoming in fields:
        stored_value = existing.get(field)
        imported_value = incoming.get(field)
        if field == "registrationType" and imported_value is None:
            imported_value = stored_value
        if normalize_existing(stored_value) != normalize_incoming(imported_value):
            return True
    return False


def _sync_flag_color(cursor, barangay_id, business_name: str, status: str, lat=None, lng=None, address=None, business_id=None, *, skip_open_unlinked=False):
    """
    Propagate a registry permit-status change to the business's map pin
    (preferring exact businessID match, then name + barangay).
    If no map pin exists yet and coordinates are provided, auto-seed a new pin.
    """
    flag_color = _status_to_flag_color(status)
    name_clean = str(business_name).strip()
    ladder = ladder_columns_available(cursor)
    history_sql = "0" if ladder else """EXISTS (
        SELECT 1 FROM inspection_reports ir
        WHERE ir.targetType = 'geospatial_log' AND ir.targetID = g.logID
          AND ir.verificationStatus = 'Verified' AND ir.inspectionResult = 'Orange'
    )"""
    color_sql = _effective_flag_color_sql(
        "g", ladder=True) if ladder else "NULL"
    # New import seed paths may reuse a detected pin, but must not adopt or
    # recolour an unlinked pin while an inspection is still in flight. Existing
    # callers retain their current guards and semantics through the default.
    open_guard = """AND NOT EXISTS (
        SELECT 1 FROM inspection_reports pending
        WHERE pending.targetType = 'geospatial_log' AND pending.targetID = g.logID
          AND (pending.verificationStatus IS NULL OR pending.verificationStatus <> 'Verified')
    )""" if skip_open_unlinked else ""

    cursor.execute(
        f"""
        SELECT g.logID, g.flagColor, g.latitude, g.longitude,
               {history_sql} AS has_verified_orange,
               {color_sql} AS effectiveFlagColor
        FROM geospatial_logs g
        WHERE (g.businessID IS NOT NULL AND g.businessID = %s)
           OR (g.businessID IS NULL AND g.barangayID = %s AND g.detectedName = %s {open_guard})
        ORDER BY (g.businessID = %s) DESC, g.detectedDate DESC
        LIMIT 1
        """,
        (business_id, barangay_id, name_clean, business_id),
    )
    existing_pin = cursor.fetchone()
    if (
        existing_pin
        and not ladder
        and status == "Expired"
        and existing_pin.get("has_verified_orange")
    ):
        flag_color = "Orange"

    if existing_pin:
        if ladder:
            flag_color = existing_pin.get("effectiveFlagColor") or flag_color
        cursor.execute(
            """
            UPDATE geospatial_logs
            SET flagColor = %s,
                businessID = COALESCE(businessID, %s),
                latitude = COALESCE(latitude, %s),
                longitude = COALESCE(longitude, %s),
                detectedName = %s
            WHERE logID = %s
            """,
            (flag_color, business_id, lat, lng, name_clean,
             existing_pin["logID"]),
        )
        return True
    elif lat is not None and lng is not None:
        _columns, _values, _params = with_source(
            cursor,
            """(barangayID, businessID, detectedName, latitude, longitude,
                 flagColor, nearestLandmark)""",
            "(%s, %s, %s, %s, %s, %s, %s)",
            (barangay_id, business_id, name_clean, lat, lng, flag_color,
             address),
            # Seeded from official_registry, not found by a scan.
            SOURCE_REGISTRY,
        )
        cursor.execute(
            f"INSERT INTO geospatial_logs {_columns} VALUES {_values}",
            _params)
        return True
    return False


# ── Service functions ─────────────────────────────────────────────────────────
def upload_registry(file, ext: str):
    """Parse CSV/Excel → geocode → insert into OFFICIAL_REGISTRY.
    Returns (summary_dict, error_string)."""
    places_resolver.reset_run_state()
    set_cancel("registry_import", False)
    try:
        raw = file.read()

        if ext == ".csv":
            try:
                df = pd.read_csv(io.BytesIO(raw), encoding="utf-8", dtype=str)
            except UnicodeDecodeError:
                df = pd.read_csv(io.BytesIO(raw), encoding="latin1", dtype=str)
        else:
            df = pd.read_excel(io.BytesIO(raw), dtype=str)

        df = df.dropna(how="all")          # drop completely blank rows
        df = _normalise_columns(df)
        df = df.where(pd.notna(df), None)  # replace NaN with None

        total_rows = len(df)
        if total_rows == 0:
            return None, "The uploaded file contains no data rows."

        if total_rows > MAX_IMPORT_PER_BATCH:
            return None, (
                f"Maximum {MAX_IMPORT_PER_BATCH} businesses can be imported per batch (your file has {total_rows} rows). "
                f"Please split your file into batches of up to {MAX_IMPORT_PER_BATCH} rows."
            )
        import_year = date.today().year

        # Fetch existing IDs to avoid geocoding duplicates
        cursor = mysql.connection.cursor()
        cursor.execute("SELECT businessID FROM official_registry")
        existing_db_ids = set()
        for r in cursor.fetchall():
            val = r.get("businessID") if isinstance(r, dict) else r[0]
            if val:
                existing_db_ids.add(str(val).strip())
        cursor.close()

        # Count rows that actually need geocoding (those without valid pre-filled coordinates, with an address, and not duplicates)
        has_valid_coords = pd.Series(False, index=df.index)
        if "latitude" in df.columns and "longitude" in df.columns:
            coordinate_pairs = [
                _parse_coordinate_pair(lat, lng)
                for lat, lng in zip(df["latitude"], df["longitude"])
            ]
            has_valid_coords = pd.Series(
                [_coordinate_pair_within_municipality(pair)
                 for pair in coordinate_pairs],
                index=df.index,
            )
            has_out_of_bounds_coords = pd.Series(
                [pair is not None and not _coordinate_pair_within_municipality(pair)
                 for pair in coordinate_pairs],
                index=df.index,
            )
        else:
            has_out_of_bounds_coords = pd.Series(False, index=df.index)

        has_address = pd.Series(True, index=df.index)
        if "businessAddress" in df.columns:
            has_address = df["businessAddress"].notna() & (
                df["businessAddress"].astype(str).str.strip() != "")
        if "businessName" in df.columns:
            has_address = has_address | (
                df["businessName"].notna()
                & (df["businessName"].astype(str).str.strip() != "")
            )

        biz_id_col = "Business ID" if "Business ID" in df.columns else (
            "businessID" if "businessID" in df.columns else ("business_id" if "business_id" in df.columns else None))
        biz_ids = df[biz_id_col].astype(str).str.strip().str.lstrip("#").str.strip().str.upper(
        ) if biz_id_col else pd.Series("", index=df.index)
        is_new = ~biz_ids.isin(existing_db_ids)
        is_first_occurrence = ~biz_ids.duplicated()

        needs_geo = (
            ~has_valid_coords & ~has_out_of_bounds_coords
            & has_address & is_new & is_first_occurrence
        )
        rows_needing_geocode = int(needs_geo.sum())

        if GOOGLE_MAPS_API_KEY and rows_needing_geocode > 0 and not places_resolver.enabled():
            remaining_today = get_geocode_remaining_today()
            remaining_month = get_geocode_remaining_month()
            remaining = min(remaining_today, remaining_month)

            if remaining <= 0:
                return None, (
                    f"Geocoding quota reached (Daily cap: {GEOCODE_DAILY_CAP}, Monthly cap: {GEOCODE_MONTHLY_CAP}). "
                    "Please import your next batch tomorrow/next month, or include latitude and longitude columns."
                )

            if rows_needing_geocode > remaining:
                return None, (
                    f"Remaining geocoding quota is {remaining} businesses. "
                    f"Your file requires geocoding for {rows_needing_geocode} new businesses without coordinates. "
                    f"Please upload a file with at most {remaining} new businesses to geocode, or wait until quota resets."
                )

        inserted = 0
        expired_by_renewal_date = 0
        geocoded_ok = 0
        geocoded_failed = 0
        coordinates_out_of_bounds = 0
        no_match_count = 0
        skipped_quota = 0
        api_error_count = 0
        skipped = 0
        invalid_status_rows = 0
        invalid_status_values = {}
        errors = []
        inserted_ids = []

        seen_counts = {}

        from api.notifications import hub

        # Load all barangays once upfront instead of one DB cursor per row.
        barangay_lookup = _load_barangay_lookup()
        cursor = mysql.connection.cursor()
        from api.registry.reverify import _ensure_history_table
        _ensure_history_table(cursor)

        for idx, row in df.iterrows():
            if idx % 5 == 0:
                hub.publish_to_admins({
                    "type": "registry_progress",
                    "processed": idx,
                    "total": total_rows
                })

            if is_cancelled("registry_import"):
                mysql.connection.rollback()
                cursor.close()
                return None, "Import cancelled by user — no data was saved."

            business_name = row.get("businessName")
            biz_id_raw = row.get("Business ID") or row.get(
                "businessID") or row.get("business_id")
            biz_id = (_clean_str(biz_id_raw) or "").lstrip("#").strip().upper()

            if not biz_id:
                skipped += 1
                errors.append(f"Row {idx + 2}: missing Business ID — skipped")
                continue

            # Status of Application (license/permit standing).
            # Rejected here, before geocoding, so a bad row costs no quota.
            status_raw = row.get("applicationStatus")
            status, status_error = _normalise_status(status_raw)
            if status is None:
                skipped += 1
                invalid_status_rows += 1
                invalid_key = _clean_str(status_raw) or ""
                invalid_status_values[invalid_key] = (
                    invalid_status_values.get(invalid_key, 0) + 1)
                errors.append(f"Row {idx + 2}: {status_error} — skipped")
                continue

            # businessName is required
            name_key = _clean_upper(business_name)
            if not name_key:
                skipped += 1
                errors.append(f"Row {idx + 2}: missing businessName — skipped")
                continue

            # Resolve barangay using the preloaded dict (no per-row DB call)
            barangay_raw = row.get("barangay")
            barangay_id = _resolve_barangay_id(barangay_raw, barangay_lookup)

            # If barangay not found, skip row — barangayID is NOT NULL
            if barangay_id is None:
                skipped += 1
                errors.append(
                    f"Row {idx + 2}: barangay '{_clean_str(barangay_raw) or 'missing'}' not found — skipped")
                continue

            # Track duplicates within this CSV
            if biz_id in seen_counts:
                skipped += 1
                errors.append(
                    f"Row {idx + 2}: duplicate Business ID '{biz_id}' within the CSV — skipped")
                continue
            seen_counts[biz_id] = 1

            if biz_id in existing_db_ids:
                skipped += 1
                errors.append(
                    f"Row {idx + 2}: duplicate Business ID '{biz_id}' already exists in the database — skipped")
                continue

            # Geocode
            address_raw = normalize_business_address(
                row.get("businessAddress"), row.get("barangay"))
            lat, lng = None, None

            coordinate_pair = _parse_coordinate_pair(
                row.get("latitude"), row.get("longitude")
            )
            if (
                coordinate_pair is not None
                and not _coordinate_pair_within_municipality(coordinate_pair)
            ):
                coordinate_pair = None
                coordinates_out_of_bounds += 1
                errors.append(
                    f"Row {idx + 2}: coordinates are outside the Mataasnakahoy boundary — ignored"
                )
            if coordinate_pair:
                lat, lng = coordinate_pair
                geocoded_ok += 1

            curr_resolve_key = places_resolver.compute_resolve_key(
                name_key, address_raw, barangay_id)
            geo_meta = {"coord_source": "csv",
                        "resolve_key": curr_resolve_key} if lat is not None else None
            lob = _clean_upper(row.get("lineOfBusiness"))
            if lat is None and (address_raw or name_key):
                business_type = _clean_upper(row.get("businessType"))
                lat, lng, geo_meta = _resolve_location(
                    name_key, address_raw, barangay_raw,
                    business_id=biz_id, barangay_id=barangay_id,
                    line_of_business=lob, business_type=business_type)
                if lat is not None:
                    geocoded_ok += 1
                else:
                    geocoded_failed += 1
                    if _is_retryable_resolution_failure(geo_meta):
                        if geo_meta.get("reason") == "api_error":
                            api_error_count += 1
                        else:
                            skipped_quota += 1
                    else:
                        no_match_count += 1
            elif lat is None:
                geocoded_failed += 1
                no_match_count += 1

            # Registration Type (New vs Renewal)
            reg_type = _normalise_registration_type(
                row.get("registrationType"))

            # Renewal date
            renewal_date = _parse_renewal_date(row.get("lastRenewalDate"))
            imported_status = status
            status = _effective_import_status(
                status, renewal_date, import_year)
            expired_by_renewal_date_row = (
                imported_status != status and status == "Expired"
            )

            addr_key = address_raw

            # Insert — ignore duplicates if the DB already has this biz_id
            cursor.execute(
                """
                INSERT IGNORE INTO official_registry
                    (businessID, barangayID, businessName, businessType, lineOfBusiness,
                    businessAddress, latitude, longitude, applicationStatus,
                    lastRenewalDate, businessSize, registrationType, resolveKey)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    biz_id,
                    barangay_id,
                    name_key,
                    _clean_upper(row.get("businessType")),
                    _clean_upper(row.get("lineOfBusiness")),
                    addr_key,
                    lat,
                    lng,
                    status,
                    renewal_date,
                    _clean_upper(row.get("businessSize")),
                    reg_type,
                    _resolution_key_for_cache(curr_resolve_key, geo_meta),
                ),
            )

            if cursor.rowcount > 0:
                inserted += 1
                if expired_by_renewal_date_row:
                    expired_by_renewal_date += 1
                inserted_ids.append(biz_id)
                if lat is not None:
                    places_resolver.record_coord_meta(cursor, biz_id, geo_meta)
                if not _is_retryable_resolution_failure(geo_meta):
                    if not _sync_flag_color(
                        cursor,
                        barangay_id,
                        name_key,
                        status,
                        lat,
                        lng,
                        address_raw,
                        business_id=biz_id,
                        skip_open_unlinked=(status != "Expired"),
                    ):
                        insert_green_flag(
                            barangay_id,
                            name_key,
                            lat,
                            lng,
                            address_raw,
                            color=_status_to_flag_color(status),
                            business_id=biz_id,
                        )
            else:
                skipped += 1

        if not commit_unless_cancelled(
            "registry_import", mysql.connection.commit
        ):
            mysql.connection.rollback()
            cursor.close()
            return None, "Import cancelled by user — no data was saved."

        cursor.close()
        _log_registry_places_summary(
            "registry import",
            {
                "resolved": geocoded_ok,
                "no_match": no_match_count,
                "skipped_quota": skipped_quota,
                "api_error": api_error_count,
            },
        )

        try:
            hub.publish_to_admins({
                "type": "registry_progress",
                "processed": total_rows,
                "total": total_rows,
                "status": "Import complete!"
            })
            hub.publish_to_admins({
                "type": "registry_updated"
            })
        except Exception:
            pass

        return {
            "total_rows":       total_rows,
            "inserted":         inserted,
            "expired_by_renewal_date": expired_by_renewal_date,
            "inserted_ids":     inserted_ids,
            "geocoded_ok":      geocoded_ok,
            "geocoded_failed":  geocoded_failed,
            "coordinates_out_of_bounds": coordinates_out_of_bounds,
            "resolved":         geocoded_ok,
            "no_match":         no_match_count,
            "skipped_quota":    skipped_quota,
            "api_error":        api_error_count,
            "cache_hits":       0,
            "skipped":          skipped,
            # cap at 20 so response stays small
            "invalid_status_rows": invalid_status_rows,
            "invalid_status_values": invalid_status_values,
            # errors is truncated below; the two counters above are not.
            "errors":           errors[:20],
        }, None

    except Exception as e:
        return None, str(e)


class RegistryValidationError(ValueError):
    """Caller-supplied registry data failed validation. HTTP 400."""


class RegistryNotFoundError(LookupError):
    """The requested registry record does not exist. HTTP 404."""


class RegistryInspectionInProgress(RuntimeError):
    """The Registry row cannot be edited while a linked inspection is open."""


class SyncProtectionLookupError(RuntimeError):
    """The pre-run protection lookup failed, so sync must not start.

    Same fail-closed contract as OpenInspectionLookupError: if we cannot tell
    which rows are protected, syncing anyway would overwrite exactly the rows
    the guard exists to protect.
    """


class OpenInspectionLookupError(RuntimeError):
    """Raised when the open-inspection guard cannot be evaluated."""


def _find_open_inspection_for_business(cursor, business_id, business_name,
                                       barangay_id):
    """Find a not-yet-verified inspection linked to this Registry business."""
    cursor.execute(
        """SELECT ir.reportID, ir.verificationStatus
           FROM inspection_reports ir
           JOIN geospatial_logs g ON g.logID = ir.targetID
           WHERE ir.targetType = 'geospatial_log'
             AND (ir.verificationStatus IS NULL
                  OR ir.verificationStatus <> 'Verified')
             AND (
                 g.businessID = %s
                 OR (g.businessID IS NULL
                     AND g.barangayID = %s
                     AND g.detectedName = %s)
             )
           ORDER BY ir.irTimestamp DESC
           LIMIT 1""",
        (business_id, barangay_id, business_name),
    )
    return cursor.fetchone()


def _load_open_inspection_keys(cursor):
    """Batch-load the businesses whose inspection is not yet verified.

    "Open" deliberately means "not verified" - either an explicit
    verificationStatus, or no status at all - rather than an explicit list of
    statuses, so a new assignment state cannot silently become syncable.

    Rows are matched through the map pin the way every other join in this
    module does: geospatial_logs.businessID where the pin carries one, and
    barangayID + detectedName for legacy pins with businessID IS NULL.

    Fails closed. If either query cannot run we cannot know which rows are
    protected, and syncing anyway would overwrite exactly the rows this guard
    exists to protect, so the caller must abort.
    """
    business_ids = set()
    name_brgy_pairs = set()

    cursor.execute("""
        SELECT DISTINCT g.businessID
        FROM geospatial_logs g
        JOIN inspection_reports ir
          ON ir.targetID = g.logID
         AND ir.targetType = 'geospatial_log'
        WHERE (ir.verificationStatus IS NULL OR ir.verificationStatus <> 'Verified')
          AND g.businessID IS NOT NULL
    """)
    for row in cursor.fetchall() or ():
        business_ids.add(row.get("businessID"))

    cursor.execute("""
        SELECT DISTINCT g.detectedName, g.barangayID
        FROM geospatial_logs g
        JOIN inspection_reports ir
          ON ir.targetID = g.logID
         AND ir.targetType = 'geospatial_log'
        WHERE (ir.verificationStatus IS NULL OR ir.verificationStatus <> 'Verified')
          AND g.businessID IS NULL
    """)
    for row in cursor.fetchall() or ():
        name_brgy_pairs.add((row.get("detectedName"),
                             row.get("barangayID")))

    return business_ids, name_brgy_pairs


class RegistryLadderConflict(Exception):
    """The ladder action was refused because of the row's current state.

    Surfaces as HTTP 409. Distinct from RegistryValidationError (the request
    was malformed) and from RegistryLadderUnavailable (the schema is missing).
    """


class RegistryLadderUnavailable(RuntimeError):
    """The ladder schema this action needs is not present on this database.

    Surfaces as HTTP 409. Every Phase 3A action refuses rather than
    half-applying: a partial ladder state is worse than a refusal.
    """


#: Enforcement-state fields clear_warning needs. The action refuses if the
#: generalized state schema is unavailable rather than losing audit metadata.
CLEAR_WARNING_COLUMNS = (
    "warningLevel", "blackLocked", "warningClearedAt", "warningClearedBy",
    "warningClearReason",
)

#: Legacy state fields retained for old in-flight verification compatibility.
BLACK_UNLOCK_COLUMNS = ("blackLocked", "blackDispatchUnlocked")


def _coerce_int(value):
    """Read a ladder column as an int. None and rubbish both count as 0."""
    if value is None or value is False:
        return 0
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _has_enforcement_columns(cursor, names):
    """True when every named enforcement column exists on enforcement_state.

    Asked in one round trip. Unlike the Phase 1 cached probe this is not
    memoised: these actions are admin-scale, not on a request path, and a
    migration applied while the app is running should take effect without a
    restart.
    """
    placeholders = ", ".join(["%s"] * len(names))
    cursor.execute(
        "SELECT COLUMN_NAME FROM information_schema.COLUMNS "
        "WHERE TABLE_SCHEMA = DATABASE() "
        "  AND TABLE_NAME = 'enforcement_state' "
        f"  AND COLUMN_NAME IN ({placeholders})",
        tuple(names),
    )
    found = set()
    for row in cursor.fetchall() or ():
        found.add(row.get("COLUMN_NAME") if isinstance(row, dict)
                  else row[0])
    return all(name in found for name in names)


def _load_ladder_state(cursor, business_id, columns):
    """Read permit status and enforcement state for a registered business.

    Returns None when the Registry business does not exist. A missing state
    row returns NULL enforcement values, which behave as the field defaults.
    """
    state_columns = ", ".join(f"es.{column}" for column in columns)
    cursor.execute(
        f"""SELECT r.applicationStatus, {state_columns}
            FROM official_registry r
            LEFT JOIN enforcement_state es
              ON es.subjectType = 'business'
             AND es.subjectID = CAST(r.businessID AS CHAR)
            WHERE r.businessID = %s
            LIMIT 1""",
        (business_id,),
    )
    row = cursor.fetchone()
    if row is None:
        return None
    if isinstance(row, dict):
        return row
    return dict(zip(["applicationStatus"] + list(columns), row))


def _ladder_not_migrated(what):
    return RegistryLadderUnavailable(
        f"{what} is unavailable: this database has not had the enforcement "
        "state migration applied. Nothing was changed."
    )


def _clear_pin_mirror(cursor, business_id):
    """Put the business's pin back in step with its registry row.

    The pin carries a mirrored copy of the warning (noticeLevel) and its own
    stored colour. After a clear both have to follow the registry row, or the
    Map keeps rendering Orange through the stored-pin fallback even though the
    warning is gone.

    The colour is the real shared rule rather than a copy of it:
    _effective_flag_color_sql with the registry row already resolved is
    exactly what every reader renders, so the pin cannot land on a different
    answer than a screen would show.
    """
    registry = _effective_flag_color_sql(
        "g", ladder=_has_enforcement_columns(
            cursor, ("warningLevel", "blackLocked")))
    cursor.execute(
        f"""
        UPDATE geospatial_logs g
        JOIN official_registry r ON r.businessID = %s
          AND (
                (g.businessID IS NOT NULL AND g.businessID = r.businessID)
             OR (g.businessID IS NULL AND g.barangayID = r.barangayID
                 AND g.detectedName = r.businessName)
          )
        SET g.noticeLevel = 0,
            g.flagColor = {registry}
        """,
        (business_id,),
    )
    return cursor.rowcount


def clear_warning(business_id, cleared_by_user_id, reason=None):
    """Clear a business's Orange warning level. Admin or SUPER_ADMIN.

    Allowed only when there is a warning to clear, the business is not Black
    locked, and no inspection is still in flight. Sets warningLevel to 0 and
    records who, when and why.

    Never touches applicationStatus, blackLocked or blackDispatchUnlocked.
    Clearing the warning ladder is not a clearance of anything else: an Active
    business that was warned goes back to Green, and a Pending or Expired one
    goes back to its own permit colour.

    Returns (summary, error). `error` is a RegistryLadderConflict (409),
    RegistryLadderUnavailable (409) or RegistryNotFoundError (404).
    """
    try:
        cursor = mysql.connection.cursor()

        if not _has_enforcement_columns(cursor, CLEAR_WARNING_COLUMNS):
            cursor.close()
            return None, _ladder_not_migrated("Clearing a warning")

        state = _load_ladder_state(cursor, business_id, CLEAR_WARNING_COLUMNS)
        if state is None:
            cursor.close()
            return None, RegistryNotFoundError("Business not found")

        level = _coerce_int(state.get("warningLevel"))
        if level <= 0:
            cursor.close()
            return None, RegistryLadderConflict(
                "This business has no warning to clear: its warning level is "
                f"{level}, not above 0."
            )

        if (_coerce_int(state.get("blackLocked"))
                or state.get("applicationStatus") in ("Revoked", "Blacklisted")):
            cursor.close()
            return None, RegistryLadderConflict(
                "This business is Black locked, so its warning cannot be "
                "cleared separately. Only a SUPER_ADMIN unlock applies."
            )

        # An inspection in flight is not Verified yet, so it may still move
        # the level. Clearing underneath it would race.
        cursor.execute(
            """SELECT ir.reportID, ir.verificationStatus
               FROM inspection_reports ir
               JOIN geospatial_logs g ON g.logID = ir.targetID
               WHERE ir.targetType = 'geospatial_log'
                 AND (g.businessID = %s
                      OR (g.businessID IS NULL AND g.detectedName = (
                            SELECT r3.businessName
                            FROM official_registry r3
                            WHERE r3.businessID = %s)
                          AND g.barangayID = (
                            SELECT r2.barangayID
                            FROM official_registry r2
                            WHERE r2.businessID = %s)))
                 AND (ir.verificationStatus IS NULL
                      OR ir.verificationStatus <> 'Verified')
               ORDER BY ir.irTimestamp DESC
               LIMIT 1""",
            (business_id, business_id, business_id),
        )
        pending = cursor.fetchone()
        if pending:
            report_id = (pending.get("reportID") if isinstance(pending, dict)
                         else pending[0])
            status = ((pending.get("verificationStatus")
                       if isinstance(pending, dict) else pending[1])
                      or "Assigned")
            cursor.close()
            return None, RegistryLadderConflict(
                "This business has an inspection that is not yet Verified "
                f"(report #{report_id}, status {status}). Verify it or send it "
                "back first."
            )

        cursor.execute(
            """UPDATE enforcement_state
               SET warningLevel = 0,
                   warningBaseColor = NULL,
                   warningClearedAt = NOW(),
                   warningClearedBy = %s,
                   warningClearReason = %s
               WHERE subjectType = 'business'
                 AND subjectID = %s
                 AND warningLevel > 0""",
            (cleared_by_user_id, reason, str(business_id)),
        )
        if cursor.rowcount != 1:
            mysql.connection.rollback()
            cursor.close()
            return None, RegistryLadderConflict(
                f"The enforcement state for {business_id} could not be updated, "
                "so the warning was not cleared."
            )

        pins_updated = _clear_pin_mirror(cursor, business_id)

        locked = _coerce_int(state.get("blackLocked"))
        record_enforcement_event(
            cursor, business_id=business_id, event_type=WARNING_CLEARED,
            actor_user_id=cleared_by_user_id, reason=reason,
            previous_level=level, new_level=0,
            previous_black=locked, new_black=locked)

        mysql.connection.commit()
        cursor.close()
        try:
            from api.notifications import hub
            hub.publish_to_admins(
                {"type": "registry_updated", "businessID": business_id})
        except Exception:
            pass
        return {
            "businessID": business_id,
            "warningCleared": True,
            "previousWarningLevel": level,
            "warningLevel": 0,
            "pinsUpdated": pins_updated,
        }, None

    except (RegistryLadderConflict, RegistryLadderUnavailable,
            RegistryNotFoundError):
        raise
    except Exception as e:
        mysql.connection.rollback()
        return None, str(e)


def unlock_black_dispatch(business_id, unlocked_by_user_id, reason=None):
    """Reject the legacy unlock operation; Black businesses are never dispatched."""
    return None, RegistryLadderConflict(
        "Black businesses cannot be dispatched for inspection.")


def _enforcement_tables_available(cursor):
    cursor.execute(
        "SELECT TABLE_NAME FROM information_schema.TABLES "
        "WHERE TABLE_SCHEMA = DATABASE() "
        "AND TABLE_NAME IN (%s, %s)",
        ("enforcement_state", "enforcement_events"),
    )
    found = set()
    for row in cursor.fetchall() or ():
        found.add(row.get("TABLE_NAME") if isinstance(row, dict) else row[0])
    return found == {"enforcement_state", "enforcement_events"}


def clear_pin_warning(log_id, cleared_by_user_id, reason=None):
    """Clear an Orange warning on an unregistered detection pin.

    Requires the generalized enforcement tables. The base color must be known
    so clearing the warning never guesses Green or leaves the pin Orange.
    """
    cursor = None
    try:
        cursor = mysql.connection.cursor()
        if not _enforcement_tables_available(cursor):
            cursor.close()
            return None, RegistryLadderUnavailable(
                "Clearing a detection-pin warning requires the enforcement "
                "state and event tables. Apply the enforcement-state migration first."
            )

        cursor.execute(
            """SELECT g.logID, g.businessID, g.placeID, g.detectedName,
                      g.barangayID, g.flagColor, es.warningLevel,
                      es.blackLocked, es.warningBaseColor
               FROM geospatial_logs g
               LEFT JOIN enforcement_state es
                 ON es.subjectType = 'geospatial_log'
                AND es.subjectID = CAST(g.logID AS CHAR)
               WHERE g.logID = %s
               FOR UPDATE""",
            (log_id,),
        )
        pin = cursor.fetchone()
        if not pin:
            cursor.close()
            return None, RegistryNotFoundError(f"Detection pin #{log_id} not found")

        cursor.execute(
            """SELECT r.businessID
               FROM official_registry r
               WHERE (%s IS NOT NULL AND r.businessID = %s)
                  OR (%s IS NOT NULL AND r.placeID = %s
                      AND (%s IS NULL OR r.businessID = %s))
                  OR (%s IS NULL AND r.barangayID = %s
                      AND r.businessName = %s)
               LIMIT 1""",
            (pin["businessID"], pin["businessID"],
             pin["placeID"], pin["placeID"], pin["businessID"], pin["businessID"],
             pin["businessID"], pin["barangayID"], pin["detectedName"]),
        )
        linked_registry_row = cursor.fetchone()
        if linked_registry_row:
            mysql.connection.rollback()
            cursor.close()
            return None, RegistryLadderConflict(
                "This pin is linked to a Registry business. Clear its warning "
                "from the linked Inspection record instead."
            )

        level = _coerce_int(pin.get("warningLevel"))
        if level <= 0 or pin.get("flagColor") != "Orange":
            mysql.connection.rollback()
            cursor.close()
            return None, RegistryLadderConflict(
                "This detection pin has no active Orange warning to clear."
            )
        if _coerce_int(pin.get("blackLocked")) or pin.get("flagColor") == "Black":
            mysql.connection.rollback()
            cursor.close()
            return None, RegistryLadderConflict(
                "A Black-locked detection pin cannot have its warning cleared."
            )

        base_color = pin.get("warningBaseColor")
        if base_color not in ("Red", "Yellow", "Green", "Purple"):
            mysql.connection.rollback()
            cursor.close()
            return None, RegistryLadderConflict(
                "The pin's pre-warning color is unknown, so it cannot be "
                "cleared without guessing. Review its inspection history first."
            )

        cursor.execute(
            """SELECT reportID, verificationStatus
               FROM inspection_reports
               WHERE targetType = 'geospatial_log'
                 AND targetID = %s
                 AND (verificationStatus IS NULL OR verificationStatus <> 'Verified')
               ORDER BY irTimestamp DESC
               LIMIT 1""",
            (log_id,),
        )
        pending = cursor.fetchone()
        if pending:
            mysql.connection.rollback()
            cursor.close()
            return None, RegistryLadderConflict(
                "This detection pin has an inspection that is not yet Verified. "
                "Verify it or send it back first."
            )

        cursor.execute(
            """UPDATE enforcement_state
               SET warningLevel = 0,
                   warningBaseColor = NULL,
                   warningClearedAt = NOW(),
                   warningClearedBy = %s,
                   warningClearReason = %s
               WHERE subjectType = 'geospatial_log'
                 AND subjectID = %s
                 AND warningLevel > 0""",
            (cleared_by_user_id, reason, str(log_id)),
        )
        if cursor.rowcount != 1:
            mysql.connection.rollback()
            cursor.close()
            return None, RegistryLadderConflict(
                "The detection-pin warning changed before it could be cleared. "
                "Refresh and try again."
            )

        cursor.execute(
            """UPDATE geospatial_logs
               SET noticeLevel = 0, flagColor = %s
               WHERE logID = %s AND flagColor = 'Orange'""",
            (base_color, log_id),
        )
        if cursor.rowcount != 1:
            mysql.connection.rollback()
            cursor.close()
            return None, RegistryLadderConflict(
                "The detection pin changed before it could be cleared. "
                "Refresh and try again."
            )

        cursor.execute(
            """INSERT INTO enforcement_events (
                   subjectType, subjectID, eventType, actorUserID, reason,
                   previousLevel, newLevel, previousBlack, newBlack
               ) VALUES ('geospatial_log', %s, 'warning_cleared', %s, %s,
                         %s, 0, 0, 0)""",
            (str(log_id), cleared_by_user_id, reason, level),
        )

        mysql.connection.commit()
        cursor.close()
        try:
            from api.notifications import hub
            hub.publish_to_admins(
                {"type": "registry_updated", "logID": log_id})
        except Exception:
            pass
        return {
            "logID": log_id,
            "subjectType": "geospatial_log",
            "warningCleared": True,
            "previousWarningLevel": level,
            "warningLevel": 0,
            "flagColor": base_color,
        }, None
    except (RegistryLadderConflict, RegistryLadderUnavailable,
            RegistryNotFoundError):
        if cursor is not None:
            cursor.close()
        raise
    except Exception as e:
        mysql.connection.rollback()
        if cursor is not None:
            cursor.close()
        return None, str(e)


def _consume_black_dispatch_unlock(cursor, business_id, actor_user_id,
                                   reason=None):
    """Spend a single-use grant. Returns True if one was spent.

    Called when an inspection on an unlocked Black business reaches a terminal
    state. blackLocked is NOT touched: the business was Black before the grant
    and is Black after it.
    """
    cursor.execute(
        """UPDATE enforcement_state
           SET blackDispatchUnlocked = 0
              WHERE subjectType = 'business'
                 AND subjectID = %s
                 AND blackDispatchUnlocked = 1""",
        (str(business_id),),
    )
    if cursor.rowcount == 0:
        return False
    record_enforcement_event(
        cursor, business_id=business_id, event_type=BLACK_RELOCKED,
        actor_user_id=actor_user_id, reason=reason,
        previous_black=1, new_black=1)
    return True


#: The label the registry readers used to infer. Kept verbatim as the
#: fallback for databases without geospatial_logs.source: it still answers the
#: only question we can answer there, "is there a map pin for this row?".
_OLD_REGISTRY_FLAG_SOURCE = """CASE
        WHEN g.logID IS NULL THEN NULL
        WHEN g.placeID IS NOT NULL THEN 'registry_detected'
        ELSE 'registry'
    END"""


def _flag_source_sql(alias, fallback, cursor):
    """Prefer the stored source; fall back to the old inferred label.

    The old CASE answers "where did this pin come from?" by guessing from
    which columns happen to be set. That guess is what the source column
    replaces. When the column is absent the guess is all there is, so it stays.
    """
    stored = (f"{alias}.source"
              if geospatial_source_column_exists(cursor) else "NULL")
    return f"COALESCE({stored}, ({fallback}))"


#: Columns the pin projection must expose under the alias `g`.
#:
#: _effective_flag_color_sql and _flag_source_sql are written against an alias
#: that carries all of these: g.logID and g.flagColor for the inspection and
#: ELSE arms, and g.businessID / g.placeID / g.barangayID / g.detectedName for
#: the registry match. The Registry readers get that alias from a LATERAL
#: derived table, and a derived table exposes ONLY what it selects - so a column
#: missing here is not a NULL, it is "Unknown column 'g.x'", which MySQL raises
#: at execution time and which 500s the whole page.
_REGISTRY_PIN_LATERAL_COLUMNS = (
    "logID", "placeID", "flagColor",
    "businessID", "barangayID", "detectedName",
)


def _registry_pin_lateral_sql(cursor):
    """LEFT JOIN LATERAL projecting the registry row's most recent pin as `g`.

    Both Registry readers join this. The colour builders must be handed a `g`
    that carries every column they reference, so the projection is defined once
    here rather than spelled out at each call site.

    `source` joins the projection only when geospatial_logs has the column:
    naming a column that is not there breaks the query outright, so an
    unmigrated database must not see it.
    """
    columns = list(_REGISTRY_PIN_LATERAL_COLUMNS)
    if geospatial_source_column_exists(cursor):
        columns.append(SOURCE_COLUMN)
    projection = ", ".join(columns)
    return f"""LEFT JOIN LATERAL (
                SELECT {projection}
                FROM geospatial_logs
                WHERE (businessID IS NOT NULL AND businessID = r.businessID)
                   OR (businessID IS NULL AND barangayID = r.barangayID AND detectedName = r.businessName)
                ORDER BY (businessID = r.businessID) DESC, detectedDate DESC
                LIMIT 1
            ) g ON TRUE"""


def _ladder_select_sql(cursor):
    """SELECT list for the ladder fields the Registry page buttons read.

    Returns SQL, not values: if the enforcement table is unavailable, fields
    resolve to literal 0 rather than breaking Registry reads.

    The aliases are the wire contract. registryLadderPolicy.js reads
    warningLevel, blackLocked and blackDispatchUnlocked; changing either side
    silently breaks both buttons.
    """
    parts = []
    if ladder_columns_available(cursor):
        parts += [
            "(SELECT es.warningLevel FROM enforcement_state es "
            "WHERE es.subjectType = 'business' "
            "AND es.subjectID = CAST(r.businessID AS CHAR) LIMIT 1) AS warningLevel",
            "(SELECT es.blackLocked FROM enforcement_state es "
            "WHERE es.subjectType = 'business' "
            "AND es.subjectID = CAST(r.businessID AS CHAR) LIMIT 1) AS blackLocked",
        ]
    else:
        parts += ["0 AS warningLevel", "0 AS blackLocked"]
    if _has_enforcement_columns(cursor, BLACK_UNLOCK_COLUMNS):
        parts += [
            "(SELECT es.blackDispatchUnlocked FROM enforcement_state es "
            "WHERE es.subjectType = 'business' "
            "AND es.subjectID = CAST(r.businessID AS CHAR) LIMIT 1) AS blackDispatchUnlocked"
        ]
    else:
        parts += ["0 AS blackDispatchUnlocked"]
    return ",\n                ".join(parts)


def _load_sync_protection_keys(cursor):
    """Preload the rows this sync run must not touch.

    Returns (black_locked_ids, closed_ids), both sets of businessID.

    Black locked: a permanent habitual-offender lock. Sync may not touch it -
    it must never see the row, never move its pin and never recolour it.

    Closed: the permit is gone. Sync may not reopen it by accident. A manual
    admin edit can still reopen one; this guard is about a CSV import silently
    resurrecting a closed business.

    Revoked permits are protected even without the ladder columns. A newly
    imported Revoked row is accepted once and frozen by later syncs.

    Fails closed. A caller that cannot answer this question must abort rather
    than guess.
    """
    black_locked_ids = set()
    closed_ids = set()

    black_condition = "r.applicationStatus IN ('Revoked', 'Blacklisted')"
    registry_state_join = ""
    if ladder_columns_available(cursor):
        registry_state_join = """
            LEFT JOIN enforcement_state es
              ON es.subjectType = 'business'
             AND es.subjectID = CAST(r.businessID AS CHAR)
        """
        black_condition = (
            f"(COALESCE(es.blackLocked, 0) = 1 OR {black_condition})")
    cursor.execute(f"""
        SELECT r.businessID FROM official_registry r
        {registry_state_join}
        WHERE {black_condition} AND r.businessID IS NOT NULL
    """)
    for row in cursor.fetchall() or ():
        black_locked_ids.add(row.get("businessID"))

    cursor.execute("""
        SELECT businessID FROM official_registry
        WHERE applicationStatus = 'Closed' AND businessID IS NOT NULL
    """)
    for row in cursor.fetchall() or ():
        closed_ids.add(row.get("businessID"))

    return black_locked_ids, closed_ids


def sync_registry(file, ext: str):
    """Parse CSV/Excel → geocode → upsert OFFICIAL_REGISTRY.
    Existing rows match on businessID and only changed business fields are
    written; new rows are inserted (same validation rules as upload).
    Returns (summary_dict, error_string)."""
    places_resolver.reset_run_state()
    set_cancel("registry_import", False)
    try:
        raw = file.read()

        if ext == ".csv":
            try:
                df = pd.read_csv(io.BytesIO(raw), encoding="utf-8", dtype=str)
            except UnicodeDecodeError:
                df = pd.read_csv(io.BytesIO(raw), encoding="latin1", dtype=str)
        else:
            df = pd.read_excel(io.BytesIO(raw), dtype=str)

        df = df.dropna(how="all")
        df = _normalise_columns(df)
        df = df.where(pd.notna(df), None)

        total_rows = len(df)
        if total_rows == 0:
            return None, "The uploaded file contains no data rows."

        if total_rows > MAX_IMPORT_PER_BATCH:
            return None, (
                f"Maximum {MAX_IMPORT_PER_BATCH} businesses can be synced per batch (your file has {total_rows} rows). "
                f"Please split your file into batches of up to {MAX_IMPORT_PER_BATCH} rows."
            )
        import_year = date.today().year

        inserted = 0
        updated = 0
        expired_by_renewal_date = 0
        unchanged = 0
        skipped = 0
        skipped_open_inspection = 0
        skipped_black_lock = 0
        skipped_closed = 0
        cleared_warnings = 0
        invalid_status_rows = 0
        invalid_status_values = {}
        geocoded_ok = 0
        geocoded_failed = 0
        coordinates_out_of_bounds = 0
        no_match_count = 0
        cache_hits = 0
        skipped_quota = 0
        api_error_count = 0
        errors = []
        inserted_ids = []
        matched_db_ids = set()

        from api.notifications import hub

        # Load all barangays once upfront instead of one DB cursor per row.
        barangay_lookup = _load_barangay_lookup()
        cursor = mysql.connection.cursor()

        # Rows under inspection are frozen for this run. Loaded once so the
        # per-row cost stays zero. Nothing has been written yet, so failing
        # here leaves the registry exactly as it was.
        try:
            open_inspection_ids, open_inspection_names = (
                _load_open_inspection_keys(cursor))
        except OpenInspectionLookupError:
            raise
        except Exception as exc:
            raise OpenInspectionLookupError(
                "Could not check open inspections; sync aborted, "
                f"nothing was changed. ({exc})"
            ) from exc

        # Same contract, same reason: Black locked and Closed rows are frozen
        # for this run. Loaded once so the per-row cost stays zero, and raised
        # before anything is written.
        try:
            black_locked_ids, closed_ids = _load_sync_protection_keys(cursor)
        except SyncProtectionLookupError:
            raise
        except Exception as exc:
            raise SyncProtectionLookupError(
                "Could not read the Black lock / Closed protections; sync "
                f"aborted, nothing was changed. ({exc})"
            ) from exc

        for idx, row in df.iterrows():
            if idx % 5 == 0:
                hub.publish_to_admins({
                    "type": "registry_progress",
                    "processed": idx,
                    "total": total_rows
                })

            if is_cancelled("registry_import"):
                mysql.connection.rollback()
                cursor.close()
                return None, "Sync cancelled by user — no data was saved."

            business_name = row.get("businessName")
            biz_id_raw = row.get("Business ID") or row.get(
                "businessID") or row.get("business_id")
            biz_id = (_clean_str(biz_id_raw) or "").lstrip("#").strip().upper()

            if not biz_id:
                skipped += 1
                errors.append(f"Row {idx + 2}: missing Business ID — skipped")
                continue

            name_key = _clean_upper(business_name)
            if not name_key:
                skipped += 1
                errors.append(f"Row {idx + 2}: missing businessName — skipped")
                continue

            barangay_raw = row.get("barangay")
            barangay_id = _resolve_barangay_id(barangay_raw, barangay_lookup)

            if barangay_id is None:
                skipped += 1
                errors.append(
                    f"Row {idx + 2}: barangay '{_clean_str(barangay_raw) or 'missing'}' not found — skipped")
                continue

            address_raw = normalize_business_address(
                row.get("businessAddress"), row.get("barangay"))
            addr_key = address_raw

            geo_meta = None
            reused_existing = False

            # Track ALL IDs processed in this CSV to prevent duplicate inserts crashing the transaction
            if biz_id in matched_db_ids:
                # If we've already synced this ID in this run, treat it as skip.
                skipped += 1
                errors.append(
                    f"Row {idx + 2}: duplicate Business ID '{biz_id}' within the CSV — skipped")
                continue
            matched_db_ids.add(biz_id)

            # Check if this business already exists in the database
            cursor.execute(
                """
                SELECT businessID, barangayID, businessName, businessType,
                       lineOfBusiness, businessAddress, applicationStatus,
                       lastRenewalDate, businessSize, registrationType,
                       latitude, longitude, coordSource, placeID, placeIDKind,
                       matchScore, matchStatus, resolveKey
                FROM official_registry
                WHERE businessID = %s
                """,
                (biz_id,),
            )
            existing = cursor.fetchone()

            # An inspection is in flight for this business: leave the whole
            # row alone. This sits before any UPDATE, before the coordinate
            # resolution below, and well before _sync_flag_color, which runs
            # outside the business_fields_changed guard. New rows (no existing
            # record) are unaffected and fall through to the INSERT branch.
            if existing and (
                biz_id in open_inspection_ids
                or (name_key, barangay_id) in open_inspection_names
            ):
                skipped += 1
                skipped_open_inspection += 1
                errors.append(
                    f"Row {idx + 2}: open inspection in progress — skipped")
                continue

            # Black locked or Closed: frozen for this run, like an open
            # inspection. Sits before the status validation, before any
            # geocoding and before _sync_flag_color. `skipped` stays the
            # running total for every reason a row is dropped.
            if existing:
                if biz_id in black_locked_ids:
                    skipped += 1
                    skipped_black_lock += 1
                    errors.append(
                        f"Row {idx + 2}: business is Black locked "
                        "— skipped")
                    continue
                if biz_id in closed_ids:
                    skipped += 1
                    skipped_closed += 1
                    errors.append(
                        f"Row {idx + 2}: permit is Closed — skipped "
                        "(reopen it from the registry page)")
                    continue

            # Status of Application (license/permit standing).
            # Rejected before any geocoding, so a bad row costs no quota.
            status_raw = row.get("applicationStatus")
            status, status_error = _normalise_status(status_raw)
            if status is None:
                skipped += 1
                invalid_status_rows += 1
                invalid_key = _clean_str(status_raw) or ""
                invalid_status_values[invalid_key] = (
                    invalid_status_values.get(invalid_key, 0) + 1)
                errors.append(f"Row {idx + 2}: {status_error} — skipped")
                continue

            is_locked = False
            is_rejected = False
            existing_source = ""
            if existing:
                existing_source = (existing.get(
                    "coordSource") or "").strip().lower()
                m_stat = (existing.get("matchStatus") or "").strip().lower()
                if m_stat == "rejected":
                    is_rejected = True
            location_fields_unchanged = bool(
                existing
                and _registry_sync_location_fields_unchanged(
                    existing, name_key, address_raw, barangay_id
                )
            )
            stored_resolve_key = (
                places_resolver.compute_resolve_key(
                    existing.get("businessName"),
                    existing.get("businessAddress"),
                    existing.get("barangayID"),
                )
                if existing else None
            )

            curr_resolve_key = places_resolver.compute_resolve_key(
                name_key, address_raw, barangay_id)
            lob = _clean_upper(row.get("lineOfBusiness"))
            lat, lng = None, None
            reused_existing = False
            geo_meta = None

            coordinate_pair = _parse_coordinate_pair(
                row.get("latitude"), row.get("longitude")
            )
            coordinate_out_of_bounds = (
                coordinate_pair is not None
                and not _coordinate_pair_within_municipality(coordinate_pair)
            )
            if coordinate_out_of_bounds:
                coordinate_pair = None
                coordinates_out_of_bounds += 1
                errors.append(
                    f"Row {idx + 2}: coordinates are outside the Mataasnakahoy boundary — ignored"
                )
            csv_has_coords = coordinate_pair is not None
            imported_candidate_pair = coordinate_pair
            if existing:
                is_locked = _preserve_import_coordinates(
                    existing_source, existing.get(
                        "matchStatus"), csv_has_coords
                )
            if coordinate_pair:
                lat, lng = coordinate_pair

            pending_location_reapproval = bool(
                existing
                and (
                    existing_source == "manual"
                    or (existing.get("matchStatus") or "").strip().lower() in ("approved", "review")
                )
                and (
                    _sync_text_value(existing.get(
                        "businessAddress")) != _sync_text_value(address_raw)
                    or _sync_barangay_value(existing.get("barangayID")) != _sync_barangay_value(barangay_id)
                )
            )

            if is_locked:
                # Preserve manual/approved pins and CSV pins without replacement coordinates.
                if existing.get("latitude") is not None and existing.get("longitude") is not None:
                    lat = float(existing["latitude"])
                    lng = float(existing["longitude"])
                    reused_existing = True
                    geocoded_ok += 1
            elif csv_has_coords:
                # Unlocked row with valid CSV coordinates
                geo_meta = {"coord_source": "csv",
                            "resolve_key": curr_resolve_key}
                geocoded_ok += 1
            elif is_rejected:
                if existing.get("latitude") is not None and existing.get("longitude") is not None:
                    lat = float(existing["latitude"])
                    lng = float(existing["longitude"])
                    reused_existing = True
                geocoded_failed += 1
            elif existing and (
                existing.get("resolveKey") == curr_resolve_key
                or (
                    location_fields_unchanged
                    and existing.get("resolveKey") == stored_resolve_key
                )
            ):
                # Unchanged record according to SHA-1 resolveKey: consumes zero Google API calls!
                if existing.get("latitude") is not None and existing.get("longitude") is not None:
                    lat = float(existing["latitude"])
                    lng = float(existing["longitude"])
                    reused_existing = True
                    cache_hits += 1
                    geocoded_ok += 1
                else:
                    # Previously evaluated with identical key as unlocatable
                    geocoded_failed += 1
                    no_match_count += 1
            elif address_raw or name_key:
                business_type = _clean_upper(row.get("businessType"))
                lat, lng, geo_meta = _resolve_location(
                    name_key, address_raw, barangay_raw,
                    business_id=biz_id, barangay_id=barangay_id,
                    line_of_business=lob, business_type=business_type)
                if lat is not None:
                    geocoded_ok += 1
                else:
                    geocoded_failed += 1
                    if _is_retryable_resolution_failure(geo_meta):
                        if geo_meta.get("reason") == "api_error":
                            api_error_count += 1
                        else:
                            skipped_quota += 1
                    else:
                        no_match_count += 1
            else:
                geocoded_failed += 1
                no_match_count += 1

            if geo_meta is None and lat is not None and not reused_existing:
                # coordinates came from the uploaded file
                geo_meta = {"coord_source": "csv",
                            "resolve_key": curr_resolve_key}

            reg_type = _normalise_registration_type(
                row.get("registrationType"))

            renewal_date = _parse_renewal_date(row.get("lastRenewalDate"))
            imported_status = status
            previous_status = (
                _status_for_compare(existing.get("applicationStatus"))
                if existing else None
            )
            status = _effective_import_status(
                status, renewal_date, import_year)
            expired_by_renewal_date_row = (
                imported_status != status and status == "Expired"
            )

            btype = _clean_upper(row.get("businessType"))
            lob = _clean_upper(row.get("lineOfBusiness"))
            addr = address_raw
            bsize = _clean_upper(row.get("businessSize"))
            business_fields_changed = existing is not None and (
                _registry_sync_business_fields_changed(
                    existing,
                    {
                        "barangayID": barangay_id,
                        "businessName": name_key,
                        "businessType": btype,
                        "lineOfBusiness": lob,
                        "businessAddress": addr,
                        "applicationStatus": status,
                        "lastRenewalDate": renewal_date,
                        "businessSize": bsize,
                        "registrationType": reg_type,
                    },
                )
            )

            if existing:
                coord_meta_written = False
                if pending_location_reapproval:
                    final_lat = existing.get("latitude")
                    final_lng = existing.get("longitude")
                    cursor.execute(
                        """
                        UPDATE official_registry SET
                            barangayID = %s,
                            businessName = %s,
                            businessType = %s,
                            lineOfBusiness = %s,
                            businessAddress = %s,
                            latitude = %s,
                            longitude = %s,
                            applicationStatus = %s,
                            lastRenewalDate = %s,
                            businessSize = %s,
                            registrationType = COALESCE(%s, registrationType),
                            coordSource = %s,
                            matchStatus = %s,
                            resolveKey = %s
                        WHERE businessID = %s
                        """,
                        (
                            barangay_id,
                            name_key,
                            btype,
                            lob,
                            addr,
                            final_lat,
                            final_lng,
                            status,
                            renewal_date,
                            bsize,
                            reg_type,
                            existing.get("coordSource") or "manual",
                            "review",
                            None,
                            biz_id,
                        ),
                    )
                    from api.registry.reverify import record_location_history
                    record_location_history(
                        cursor,
                        biz_id,
                        "review",
                        "address_reapproval",
                        curr_resolve_key,
                        old_row=existing,
                        new_lat=(imported_candidate_pair[0]
                                 if imported_candidate_pair else None),
                        new_lng=(imported_candidate_pair[1]
                                 if imported_candidate_pair else None),
                        new_source=(
                            "csv" if imported_candidate_pair else None),
                        candidate_source=(
                            "csv" if imported_candidate_pair else None),
                        new_address=addr,
                        new_barangay_id=barangay_id,
                    )
                    coord_meta_written = True
                    updated += 1
                elif is_locked:
                    final_lat = existing.get("latitude")
                    final_lng = existing.get("longitude")
                else:
                    final_lat = lat if lat is not None else existing.get(
                        "latitude")
                    final_lng = lng if lng is not None else existing.get(
                        "longitude")

                if not pending_location_reapproval and business_fields_changed and not is_locked and not reused_existing and lat is not None:
                    coord_source_val = geo_meta.get(
                        "coord_source", "csv") if geo_meta else "csv"
                    place_id_val = geo_meta.get(
                        "place_id") if geo_meta else None
                    place_id_kind_val = geo_meta.get(
                        "place_id_kind") if geo_meta else None
                    score_val = geo_meta.get("score") if geo_meta else None
                    match_status_val = geo_meta.get(
                        "match_status", "auto" if coord_source_val == "places" else None) if geo_meta else None

                    cursor.execute(
                        """
                        UPDATE official_registry SET
                            barangayID = %s,
                            businessName = %s,
                            businessType = %s,
                            lineOfBusiness = %s,
                            businessAddress = %s,
                            latitude = %s,
                            longitude = %s,
                            applicationStatus = %s,
                            lastRenewalDate = %s,
                            businessSize = %s,
                            registrationType = COALESCE(%s, registrationType),
                            coordSource = %s,
                            placeID = %s,
                            placeIDKind = %s,
                            coordFetchedAt = NOW(),
                            matchScore = %s,
                            matchStatus = %s,
                            resolveKey = %s
                        WHERE businessID = %s
                        """,
                        (
                            barangay_id,
                            name_key,
                            btype,
                            lob,
                            addr,
                            final_lat,
                            final_lng,
                            status,
                            renewal_date,
                            bsize,
                            reg_type,
                            coord_source_val,
                            place_id_val,
                            place_id_kind_val,
                            score_val,
                            match_status_val,
                            _resolution_key_for_cache(
                                curr_resolve_key, geo_meta),
                            biz_id,
                        ),
                    )
                    coord_meta_written = True
                elif not pending_location_reapproval and business_fields_changed:
                    cursor.execute(
                        """
                        UPDATE official_registry SET
                            barangayID = %s,
                            businessName = %s,
                            businessType = %s,
                            lineOfBusiness = %s,
                            businessAddress = %s,
                            latitude = %s,
                            longitude = %s,
                            applicationStatus = %s,
                            lastRenewalDate = %s,
                            businessSize = %s,
                            registrationType = COALESCE(%s, registrationType),
                            resolveKey = COALESCE(%s, resolveKey)
                        WHERE businessID = %s
                        """,
                        (
                            barangay_id,
                            name_key,
                            btype,
                            lob,
                            addr,
                            final_lat,
                            final_lng,
                            status,
                            renewal_date,
                            bsize,
                            reg_type,
                            _resolution_key_for_cache(
                                curr_resolve_key, geo_meta),
                            biz_id,
                        ),
                    )
                elif not pending_location_reapproval:
                    unchanged += 1
                    coordinates_changed = (
                        not is_locked
                        and not reused_existing
                        and lat is not None
                        and (
                            _sync_coordinate_value(existing.get("latitude"))
                            != _sync_coordinate_value(final_lat)
                            or _sync_coordinate_value(existing.get("longitude"))
                            != _sync_coordinate_value(final_lng)
                        )
                    )
                    if coordinates_changed:
                        cursor.execute(
                            """UPDATE official_registry
                               SET latitude=%s, longitude=%s
                               WHERE businessID=%s""",
                            (final_lat, final_lng, biz_id),
                        )

                should_record_coord_meta = (
                    not pending_location_reapproval
                    and not is_locked
                    and not reused_existing
                    and lat is not None
                    and _sync_coord_meta_changed(existing, geo_meta)
                )
                if should_record_coord_meta and not coord_meta_written:
                    places_resolver.record_coord_meta(cursor, biz_id, geo_meta)
                if business_fields_changed and not pending_location_reapproval:
                    updated += 1
                if (
                    expired_by_renewal_date_row
                    and previous_status != "Expired"
                    and (pending_location_reapproval or business_fields_changed)
                ):
                    expired_by_renewal_date += 1
                warning_cleared = None
                if status == "Active":
                    warning_cleared = _clear_warning_for_active_import(
                        cursor, biz_id)
                    if warning_cleared is not None:
                        cleared_warnings += 1
                if not pending_location_reapproval and not _is_retryable_resolution_failure(geo_meta):
                    old_lat = existing.get("latitude")
                    old_lng = existing.get("longitude")
                    if (
                        not is_locked and lat is not None and lng is not None
                        and old_lat is not None and old_lng is not None
                        and (float(old_lat), float(old_lng)) != (float(final_lat), float(final_lng))
                    ):
                        places_resolver._update_pin(
                            cursor, barangay_id, name_key, old_lat, old_lng,
                            final_lat, final_lng, business_id=biz_id,
                        )
                    _sync_flag_color(cursor, barangay_id, name_key,
                                     status, final_lat, final_lng, addr, business_id=biz_id)
                elif warning_cleared is not None:
                    _sync_flag_color(cursor, barangay_id, name_key,
                                     status, final_lat, final_lng, addr, business_id=biz_id)
            else:
                coord_src = None
                if lat is not None:
                    if geo_meta and geo_meta.get("coord_source"):
                        coord_src = geo_meta["coord_source"]
                    else:
                        coord_src = "csv"

                place_id_val = geo_meta.get("place_id") if geo_meta else None
                place_id_kind_val = geo_meta.get(
                    "place_id_kind") if geo_meta else None
                score_val = geo_meta.get("score") if geo_meta else None
                match_status_val = geo_meta.get(
                    "match_status") if geo_meta else None
                if coord_src == "places" and not match_status_val:
                    match_status_val = "auto"

                cursor.execute(
                    """
                    INSERT INTO official_registry
                        (businessID, barangayID, businessName, businessType, lineOfBusiness,
                        businessAddress, latitude, longitude, applicationStatus,
                        lastRenewalDate, businessSize, registrationType,
                        coordSource, placeID, placeIDKind, coordFetchedAt, matchScore, matchStatus, resolveKey)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                            CASE WHEN %s IS NOT NULL THEN NOW() ELSE NULL END, %s, %s, %s)
                    """,
                    (
                        biz_id,
                        barangay_id,
                        name_key,
                        btype,
                        lob,
                        addr,
                        lat,
                        lng,
                        status,
                        renewal_date,
                        bsize,
                        reg_type,
                        coord_src,
                        place_id_val,
                        place_id_kind_val,
                        coord_src,
                        score_val,
                        match_status_val,
                        _resolution_key_for_cache(curr_resolve_key, geo_meta),
                    ),
                )
                if cursor.rowcount > 0:
                    inserted += 1
                    if expired_by_renewal_date_row:
                        expired_by_renewal_date += 1
                    inserted_ids.append(biz_id)
                    if lat is not None:
                        places_resolver.record_coord_meta(
                            cursor, biz_id, geo_meta)
                    if not _is_retryable_resolution_failure(geo_meta):
                        # Reuse the existing pin/link helper before seeding.
                        # Its UPDATE preserves source, logID and inspections.
                        if not _sync_flag_color(
                            cursor, barangay_id, name_key, status,
                            lat, lng, addr, business_id=biz_id,
                            skip_open_unlinked=True,
                        ):
                            insert_green_flag(
                                barangay_id, name_key, lat, lng, addr,
                                color=_status_to_flag_color(status),
                                business_id=biz_id,
                            )

        if not commit_unless_cancelled(
            "registry_import", mysql.connection.commit
        ):
            mysql.connection.rollback()
            cursor.close()
            return None, "Sync cancelled by user — no data was saved."

        cursor.close()
        _log_registry_places_summary(
            "registry sync",
            {
                "resolved": geocoded_ok,
                "no_match": no_match_count,
                "skipped_quota": skipped_quota,
                "api_error": api_error_count,
                "cache_hits": cache_hits,
            },
        )

        try:
            hub.publish_to_admins({
                "type": "registry_progress",
                "processed": total_rows,
                "total": total_rows,
                "status": "Import complete!"
            })
            hub.publish_to_admins({
                "type": "registry_updated"
            })
        except Exception:
            pass

        return {
            "total_rows":       total_rows,
            "inserted":         inserted,
            "inserted_ids":     inserted_ids,
            "updated":          updated,
            "expired_by_renewal_date": expired_by_renewal_date,
            "unchanged":        unchanged,
            "geocoded_ok":      geocoded_ok,
            "geocoded_failed":  geocoded_failed,
            "coordinates_out_of_bounds": coordinates_out_of_bounds,
            "resolved":         geocoded_ok,
            "no_match":         no_match_count,
            "skipped_quota":    skipped_quota,
            "api_error":        api_error_count,
            "cache_hits":       cache_hits,
            "skipped":          skipped,
            "skipped_open_inspection": skipped_open_inspection,
            "skipped_black_lock": skipped_black_lock,
            "skipped_closed": skipped_closed,
            "cleared_warnings": cleared_warnings,
            "invalid_status_rows": invalid_status_rows,
            "invalid_status_values": invalid_status_values,
            # errors is truncated below; the two counters above are not.
            "errors":           errors[:20],
        }, None

    except (OpenInspectionLookupError, SyncProtectionLookupError):
        # Keep the type. The route answers 409 for these because nothing was
        # written and the caller should retry rather than treat it as a server
        # fault. Stringifying them here would force the route to decide by
        # matching message text, which a reword would silently break.
        raise
    except Exception as e:
        return None, str(e)


# ── Batch Pin Snapping ────────────────────────────────────────────────────────

def snap_unresolved_pins(limit: int = 200):
    """
    Cost-Optimized Batch Pin Snapper.

        Scans eligible businesses without coordinates and prior Geocoding pins
        that have not yet been checked against Places. Places Text Search is tried
        first when enabled, followed by Geocoding fallbacks for unresolved pins.

    Uses resolveKey caching: if the business name/address/barangay are
    unchanged from a previous attempt, zero API calls are made.
    Respects GEOCODE_DAILY_CAP and GEOCODE_MONTHLY_CAP budget guards.

    Returns (summary_dict, error_string).
    """
    from api.notifications import hub
    from api.models.geospatial import insert_green_flag
    from api.registry.audit import (
        ensure_registry_workflow_events,
        record_registry_workflow_event,
    )

    places_resolver.reset_run_state()
    api_key = os.getenv("GOOGLE_MAPS_API_KEY") or GOOGLE_MAPS_API_KEY
    if not api_key:
        err = "GOOGLE_MAPS_API_KEY is not configured on the server."
        hub.publish_to_admins({
            "type": "snap_progress",
            "stage": "completed",
            "percentage": 100,
            "snapped": 0,
            "failed": 0,
            "cached": 0,
            "total": 0,
            "status": err,
            "error": err
        })
        return None, err

    try:
        ensure_registry_workflow_events()
        cursor = mysql.connection.cursor()

        # Filter cached pins in Python before applying the per-run candidate limit.
        cursor.execute("""
            SELECT businessID, barangayID, businessName, businessAddress,
                   lineOfBusiness, applicationStatus, coordSource, matchStatus,
                   resolveKey, latitude, longitude, businessType
            FROM official_registry
            WHERE (
                    latitude IS NULL
                    OR (
                        coordSource = 'geocode'
                        AND longitude IS NOT NULL
                    )
                  )
              AND (matchStatus IS NULL OR matchStatus NOT IN ('approved', 'rejected'))
              AND (coordSource IS NULL OR coordSource NOT IN ('manual', 'csv'))
            ORDER BY businessID
        """)
        rows = cursor.fetchall()
        cursor.close()

        candidates = []
        cached = 0
        for biz in rows:
            if isinstance(biz, dict):
                stored_key = biz.get("resolveKey")
                coord_source = biz.get("coordSource")
                latitude = biz.get("latitude")
                longitude = biz.get("longitude")
                name = biz.get("businessName")
                address = biz.get("businessAddress")
                barangay_id = biz.get("barangayID")
            else:
                stored_key = biz[8]
                coord_source = biz[6]
                latitude = biz[9]
                longitude = biz[10]
                name = biz[2]
                address = biz[3]
                barangay_id = biz[1]

            refresh_geocode = (
                coord_source == "geocode"
                and latitude is not None
                and longitude is not None
            )
            current_key = (
                places_resolver.compute_places_refresh_key(
                    name or "", address or "", barangay_id
                )
                if refresh_geocode
                else places_resolver.compute_resolve_key(
                    name or "", address or "", barangay_id
                )
            )
            if stored_key and stored_key == current_key:
                cached += 1
                continue

            candidates.append(biz)
            if len(candidates) >= int(limit):
                break

        total = len(candidates)
        if total == 0:
            msg = (
                f"No new pins to resolve — {cached} businesses are already cached."
                if cached
                else "All registry businesses already have coordinates — nothing to snap!"
            )
            _log_registry_places_summary(
                "Snap Pins",
                {"resolved": 0, "no_match": 0, "cache_hits": cached},
            )
            hub.publish_to_admins({
                "type": "snap_progress",
                "stage": "completed",
                "percentage": 100,
                "snapped": 0,
                "failed": 0,
                "cached": cached,
                "total": 0,
                "status": msg
            })
            hub.publish_to_admins({"type": "registry_updated"})
            return {
                "total_candidates": 0,
                "snapped": 0,
                "failed": 0,
                "cached": cached,
                "message": msg
            }, None

        hub.publish_to_admins({
            "type": "snap_progress",
            "stage": "running",
            "percentage": 0,
            "snapped": 0,
            "failed": 0,
            "cached": cached,
            "total": total,
            "status": f"Found {total} businesses to resolve. Starting Places name search..."
        })

        # Load barangay lookup for name→ID resolution
        barangay_lookup = _load_barangay_lookup()

        snapped = 0
        failed = 0
        budget_hit = False
        api_error = False
        api_error_count = 0
        skipped_quota = 0
        no_match = 0
        skipped_black_lock = 0
        monthly_quota_exceeded = False
        budget_reason = None

        for idx, biz in enumerate(candidates):
            bid = biz.get("businessID") if isinstance(biz, dict) else biz[0]
            brgy_id = biz.get("barangayID") if isinstance(
                biz, dict) else biz[1]
            name = biz.get("businessName") if isinstance(biz, dict) else biz[2]
            address = biz.get("businessAddress") if isinstance(
                biz, dict) else biz[3]
            lob = biz.get("lineOfBusiness") if isinstance(
                biz, dict) else biz[4]
            business_type = biz.get("businessType") if isinstance(
                biz, dict) else biz[11]
            app_status = (biz.get("applicationStatus") if isinstance(
                biz, dict) else biz[5]) or "Active"
            stored_key = (biz.get("resolveKey")
                          if isinstance(biz, dict) else biz[8])
            coord_source = (biz.get("coordSource")
                            if isinstance(biz, dict) else biz[6])
            existing_lat = (biz.get("latitude")
                            if isinstance(biz, dict) else biz[9])
            existing_lng = (biz.get("longitude")
                            if isinstance(biz, dict) else biz[10])
            refresh_geocode = (
                coord_source == "geocode"
                and existing_lat is not None
                and existing_lng is not None
            )

            # Resolve the barangay name for geocoding
            brgy_name = None
            for k, v in barangay_lookup.items():
                if v == brgy_id:
                    brgy_name = k
                    break

            # Compute resolve key: skip if name/address hasn't changed and was previously unresolvable
            curr_key = (
                places_resolver.compute_places_refresh_key(
                    name or "", address or "", brgy_id)
                if refresh_geocode else
                places_resolver.compute_resolve_key(
                    name or "", address or "", brgy_id)
            )
            if stored_key and stored_key == curr_key:
                # Previously attempted with exact same data → cached failure, skip
                cached += 1
                # Still emit progress so the bar advances during cache-heavy batches
                if (idx + 1) % 5 == 0 or idx < 5 or idx == total - 1:
                    pct = min(99, int(((idx + 1) / max(total, 1)) * 95))
                    hub.publish_to_admins({
                        "type": "snap_progress",
                        "stage": "running",
                        "percentage": pct,
                        "snapped": snapped,
                        "failed": failed,
                        "cached": cached,
                        "total": total,
                        "status": f"Processing {idx + 1}/{total}... ({snapped} snapped, {failed} unresolvable, {cached} cached)"
                    })
                continue

            # Places can still resolve pins after the Geocoding budget is exhausted.
            if not places_resolver.enabled() and (
                get_geocode_remaining_today() <= 0
                or get_geocode_remaining_month() <= 0
            ):
                budget_hit = True
                budget_reason = "geocode_quota_exceeded"
                skipped_quota += total - idx
                # Break before attempting API calls so we don't save a budget failure as unresolvable
                break

            lat, lng, geo_meta = None, None, None
            if places_resolver.enabled():
                lat, lng, geo_meta = places_resolver.resolve_location(
                    name or "", address or "", brgy_name or "",
                    business_id=bid,
                    barangay_id=brgy_id,
                    line_of_business=lob or "",
                    business_type=business_type or "",
                    reserve_geocode=_reserve_geocode_call,
                    refresh_geocode=refresh_geocode,
                    quota_scope="snap_pins",
                )
                if geo_meta and geo_meta.get("resolve_key") is None:
                    geo_meta["resolve_key"] = curr_key

                if lat is None and geo_meta and geo_meta.get("reason") == "api_error":
                    api_error = True
                    api_error_count += 1
                    break
                if lat is None and geo_meta and geo_meta.get("budget_exhausted"):
                    budget_hit = True
                    budget_reason = geo_meta.get("reason")
                    skipped_quota += total - idx
                    monthly_quota_exceeded = (
                        budget_reason == "monthly_quota_exceeded"
                    )
                    break

            elif address:
                lat, lng = _geocode(address, brgy_name or "")
                if lat is not None:
                    geo_meta = {
                        "coord_source": "geocode",
                        "place_id": None,
                        "place_id_kind": "address",
                        "score": None,
                        "match_status": "auto",
                        "resolve_key": curr_key,
                    }
                elif _geocode_state.outcome in ("api_error", "skipped_quota"):
                    if _geocode_state.outcome == "api_error":
                        api_error = True
                        api_error_count += 1
                    else:
                        budget_hit = True
                        budget_reason = "geocode_quota_exceeded"
                        skipped_quota += total - idx
                    break

            # ── Try name-only geocode as last resort ───────────────────────────
            if lat is None and name and brgy_name and not refresh_geocode:
                lat, lng = _geocode(f"{name}, {brgy_name}", brgy_name)
                if lat is not None:
                    geo_meta = {
                        "coord_source": "geocode",
                        "place_id": None,
                        "place_id_kind": "address",
                        "score": None,
                        "match_status": "review",  # name-only = less precise
                        "resolve_key": curr_key,
                    }
                elif _geocode_state.outcome in ("api_error", "skipped_quota"):
                    if _geocode_state.outcome == "api_error":
                        api_error = True
                        api_error_count += 1
                    else:
                        budget_hit = True
                        budget_reason = "geocode_quota_exceeded"
                        skipped_quota += total - idx
                    break

            # ── Persist result ─────────────────────────────────────────────────
            cur2 = mysql.connection.cursor()
            if lat is not None and lng is not None:
                coord_src = (geo_meta or {}).get("coord_source", "geocode")
                place_id = (geo_meta or {}).get("place_id")
                place_id_kind = (geo_meta or {}).get("place_id_kind")
                match_score = (geo_meta or {}).get("score")
                match_status = (geo_meta or {}).get("match_status", "auto")

                cur2.execute("""
                    UPDATE official_registry SET
                        latitude = %s,
                        longitude = %s,
                        coordSource = %s,
                        placeID = COALESCE(%s, placeID),
                        placeIDKind = COALESCE(%s, placeIDKind),
                        coordFetchedAt = NOW(),
                        matchScore = %s,
                        matchStatus = %s,
                        resolveKey = %s
                    WHERE businessID = %s
                                            AND (latitude IS NULL OR (%s = 1 AND coordSource = 'geocode'))
                                            AND (coordSource IS NULL OR coordSource NOT IN ('manual', 'csv'))
                                            AND (matchStatus IS NULL OR matchStatus NOT IN ('approved', 'rejected'))
                """, (lat, lng, coord_src, place_id, place_id_kind,
                      match_score, match_status, curr_key, bid, int(refresh_geocode)))

                if cur2.rowcount > 0:
                    # Seed or update the map pin
                    flag_color = _status_to_flag_color(app_status)
                    places_resolver._update_pin(
                        cur2, brgy_id, name, existing_lat, existing_lng,
                        lat, lng, business_id=bid,
                    )
                    # The coordinates above were still written: snapping a pin
                    # is a location fix, not an enforcement action. Only the
                    # colour write is refused for a Black locked business.
                    if not is_black_locked(cur2, bid):
                        _sync_flag_color(cur2, brgy_id, name, app_status, lat,
                                         lng, address, business_id=bid)
                    else:
                        skipped_black_lock += 1
                    record_registry_workflow_event(
                        cur2,
                        bid,
                        "snapped",
                        result_status=match_status,
                        place_id=place_id,
                        latitude=lat,
                        longitude=lng,
                        match_score=match_score,
                    )
                    mysql.connection.commit()
                    snapped += 1
                else:
                    mysql.connection.rollback()
            else:
                if geo_meta and geo_meta.get("budget_exhausted"):
                    budget_hit = True
                    cur2.close()
                    break

                # Did we fail because a concurrent worker exhausted the budget?
                if get_geocode_remaining_today() <= 0 or get_geocode_remaining_month() <= 0:
                    budget_hit = True
                    cur2.close()
                    break

                # Store the resolveKey even on failure so we don't retry identical data next time
                cur2.execute(
                    "UPDATE official_registry SET resolveKey = %s WHERE businessID = %s",
                    (curr_key, bid)
                )
                mysql.connection.commit()
                failed += 1
                no_match += 1
            cur2.close()

            # Progress update: immediately for early items, then every 5 businesses, and on the last one
            if (idx + 1) % 5 == 0 or idx < 5 or idx == total - 1:
                pct = min(99, int(((idx + 1) / max(total, 1)) * 95))
                hub.publish_to_admins({
                    "type": "snap_progress",
                    "stage": "running",
                    "percentage": pct,
                    "snapped": snapped,
                    "failed": failed,
                    "cached": cached,
                    "total": total,
                    "status": f"Processing {idx + 1}/{total}... ({snapped} snapped, {failed} unresolvable, {cached} cached)"
                })

        msg = (
            f"Snap complete! {snapped} pins placed, {failed} could not be resolved"
            f"{', ' + str(cached) + ' already cached' if cached else ''}."
        )
        if budget_hit:
            if monthly_quota_exceeded:
                msg += " Monthly Text Search limit reached; remaining pins will resume next month."
            elif budget_reason == "daily_quota_exceeded":
                msg += " Daily Text Search limit reached; remaining pins will resume tomorrow."
            else:
                msg += " Daily geocoding budget reached — run again tomorrow to continue (progress is saved)."
        if api_error:
            msg += " Google Places returned an API error; this pin was left unchanged and can be retried next run."
        _log_registry_places_summary(
            "Snap Pins",
            {
                "resolved": snapped,
                "no_match": no_match,
                "skipped_quota": skipped_quota,
                "api_error": api_error_count,
                "cache_hits": cached,
            },
        )

        hub.publish_to_admins({
            "type": "snap_progress",
            "stage": "completed",
            "percentage": 100,
            "snapped": snapped,
            "failed": failed,
            "cached": cached,
            "total": total,
            "status": msg,
            "budget_hit": budget_hit,
            "monthly_quota_exceeded": monthly_quota_exceeded,
            "api_error": api_error,
        })
        hub.publish_to_admins({"type": "registry_updated"})

        return {
            "total_candidates": total,
            "snapped": snapped,
            "failed": failed,
            "cached": cached,
            "budget_hit": budget_hit,
            "monthly_quota_exceeded": monthly_quota_exceeded,
            "api_error": api_error,
            "skipped_quota": skipped_quota,
            "no_match": no_match,
            # Pins whose coordinates were fixed but whose colour was left
            # alone because the business is Black locked.
            "skipped_black_lock": skipped_black_lock,
            "usage": _places_usage_snapshot("Snap Pins"),
            "message": msg
        }, None

    except Exception as e:
        import traceback
        traceback.print_exc()
        err_msg = f"Snapping failed: {str(e)}"
        hub.publish_to_admins({
            "type": "snap_progress",
            "stage": "completed",
            "percentage": 100,
            "snapped": 0,
            "failed": 0,
            "cached": 0,
            "total": 0,
            "status": err_msg,
            "error": err_msg
        })
        return None, str(e)


def update_business(business_id, data: dict):
    """Manually update business information in the registry."""
    try:
        cursor = mysql.connection.cursor()

        # Check if business exists
        cursor.execute(
            "SELECT businessID, businessName, barangayID, applicationStatus "
            "FROM official_registry WHERE businessID = %s", (business_id,))
        row = cursor.fetchone()
        if not row:
            cursor.close()
            return False, RegistryNotFoundError("Business not found")

        old_name = row["businessName"]
        barangay_id = row["barangayID"]

        open_inspection = _find_open_inspection_for_business(
            cursor, business_id, old_name, barangay_id)
        if open_inspection:
            report_id = open_inspection.get("reportID")
            status = open_inspection.get("verificationStatus") or "Assigned"
            cursor.close()
            return False, RegistryInspectionInProgress(
                "This business has an inspection that is not yet Verified "
                f"(report #{report_id}, status {status}). Update or resolve "
                "the inspection from the Inspection page before editing "
                "Registry data."
            )

        # A Black locked business is closed to manual edits. Only a SUPER_ADMIN
        # unlock may change it, and that route does not exist yet.
        #
        # A Closed business is NOT locked: reopening one by hand is a normal
        # admin correction, and the status edit below is allowed to do it.
        try:
            assert_not_black_locked(
                cursor, business_id, action="edit this business")
        except BlackLockedError as exc:
            cursor.close()
            return False, exc

        # Validate the permit status before building any UPDATE, so a rejected
        # value changes nothing at all - not the registry row, not the pin.
        new_status = None
        if "applicationStatus" in data:
            new_status, status_error = _normalise_status(
                data["applicationStatus"])
            if new_status is None:
                cursor.close()
                return False, RegistryValidationError(status_error)

        # Build dynamic query to only update provided fields
        update_fields = []
        params = []

        if "businessName" in data:
            update_fields.append("businessName = %s")
            params.append(_clean_upper(data["businessName"]))
        if "businessType" in data:
            update_fields.append("businessType = %s")
            params.append(_clean_upper(data["businessType"]))
        if "lineOfBusiness" in data:
            update_fields.append("lineOfBusiness = %s")
            params.append(_clean_upper(data["lineOfBusiness"]))
        if "businessAddress" in data:
            update_fields.append("businessAddress = %s")
            params.append(normalize_business_address(
                data["businessAddress"]) if data["businessAddress"] else None)
        if "applicationStatus" in data:
            update_fields.append("applicationStatus = %s")
            params.append(new_status)
        if "businessSize" in data:
            update_fields.append("businessSize = %s")
            params.append(_clean_upper(data["businessSize"]))
        if "registrationType" in data:
            update_fields.append("registrationType = %s")
            params.append(_normalise_registration_type(data["registrationType"])
                          if data["registrationType"] else None)

        if update_fields:
            query = f"UPDATE official_registry SET {', '.join(update_fields)} WHERE businessID = %s"
            params.append(business_id)
            cursor.execute(query, tuple(params))

            # If the business name changed, update geospatial_logs to maintain the linkage
            current_name = old_name
            if "businessName" in data:
                new_name = _clean_upper(data["businessName"]) or ""
                if new_name.lower() != old_name.lower():
                    cursor.execute("""
                        UPDATE geospatial_logs
                        SET detectedName = %s
                        WHERE businessID = %s
                           OR (businessID IS NULL
                               AND LOWER(detectedName) = LOWER(%s)
                               AND barangayID = %s)
                    """, (new_name, business_id, old_name, barangay_id))
                current_name = new_name

            # Keep the map pin in sync when the permit status changes
            # (otherwise an Expired/Revoked/Closed business stays Green on the map)
            # business_id is required: pins created from the registry already carry
            # businessID, so the name+barangay fallback inside _sync_flag_color can
            # never match them (it only matches pins where businessID IS NULL).
            if "applicationStatus" in data:
                _sync_flag_color(
                    cursor,
                    barangay_id,
                    current_name,
                    new_status,
                    business_id=business_id,
                )

            mysql.connection.commit()

        cursor.close()

        try:
            from api.notifications import hub
            hub.publish_to_admins({
                "type": "registry_updated",
                "businessID": business_id
            })
        except Exception:
            pass

        return True, None
    except Exception as e:
        return False, str(e)


def delete_business(business_id, actor_role=None):
    """Delete a business from the registry."""
    try:
        cursor = mysql.connection.cursor()

        cursor.execute(
            """SELECT businessID, businessName, barangayID, latitude, longitude, placeID
               FROM official_registry WHERE businessID = %s FOR UPDATE""",
            (business_id,)
        )
        row = cursor.fetchone()
        if not row:
            cursor.close()
            return False, "Business not found"

        assert_business_deletable(cursor, business_id, actor_role)

        # Identify logs strictly tied to THIS business (avoid broad delete across same-named branches)
        target_log_ids = set()

        # Check if businessID column exists in geospatial_logs (post-migration)
        try:
            cursor.execute(
                "SELECT logID FROM geospatial_logs WHERE businessID = %s", (business_id,))
            for l in cursor.fetchall():
                target_log_ids.add(l["logID"])
        except Exception:
            pass

        # If not matched by businessID, match by placeID (if present)
        if not target_log_ids and row.get("placeID"):
            cursor.execute(
                "SELECT logID FROM geospatial_logs WHERE placeID = %s AND barangayID = %s",
                (row["placeID"], row["barangayID"])
            )
            for l in cursor.fetchall():
                target_log_ids.add(l["logID"])

        # Delete only inspection reports and geospatial logs specifically tied to this business
        for target_id in target_log_ids:
            cursor.execute(
                "DELETE FROM inspection_reports WHERE targetID = %s", (target_id,))
            cursor.execute(
                "DELETE FROM geospatial_logs WHERE logID = %s", (target_id,))

        cursor.execute(
            "DELETE FROM official_registry WHERE businessID = %s", (business_id,))
        mysql.connection.commit()
        cursor.close()

        try:
            from api.notifications import hub
            hub.publish_to_admins({
                "type": "registry_updated",
                "businessID": business_id
            })
        except Exception:
            pass

        return True, None
    except BlackBusinessDeletionForbidden as exc:
        mysql.connection.rollback()
        cursor.close()
        return False, exc
    except Exception as e:
        mysql.connection.rollback()
        return False, str(e)


def get_all_businesses(barangay_id=None, status=None, registration_type=None, search=None, page=1, per_page=10):
    """Return paginated list of businesses with optional filters."""
    try:
        # check_and_expire_old_permits is now handled by the APScheduler
        # background job in app.py — no longer called inline on read requests.
        cursor = mysql.connection.cursor()

        conditions = []
        params = []

        if barangay_id:
            conditions.append("r.barangayID = %s")
            params.append(barangay_id)

        if status and status in VALID_STATUSES:
            conditions.append("r.applicationStatus = %s")
            params.append(status)

        if registration_type and registration_type.upper() in ("NEW", "RENEWAL"):
            conditions.append("UPPER(r.registrationType) = %s")
            params.append(registration_type.upper())

        if search:
            clean_search = search.strip()
            clean_id = clean_search.lstrip("#").strip()
            conditions.append(
                "("
                "r.businessID LIKE %s OR "
                "r.businessID LIKE %s OR "
                "r.businessName LIKE %s OR "
                "r.businessType LIKE %s OR "
                "r.lineOfBusiness LIKE %s OR "
                "r.businessAddress LIKE %s OR "
                "b.barangayName LIKE %s"
                ")"
            )
            like = f"%{clean_search}%"
            like_id = f"%{clean_id}%" if clean_id else like
            params.extend([like, like_id, like, like, like, like, like])

        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

        # Total count — LEFT JOIN barangays b ensures b.barangayName is searchable
        cursor.execute(
            f"SELECT COUNT(*) AS total FROM official_registry r LEFT JOIN barangays b ON r.barangayID = b.barangayID {where}",
            params,
        )
        total = cursor.fetchone()["total"]

        # Paginated rows — LATERAL join replaces two correlated scalar subqueries
        # that previously hit geospatial_logs once per row each (N*2 extra queries).
        # A single LATERAL query fetches the most-recent log in one pass per row.
        # LOWER() is dropped from the JOIN condition: utf8mb4_unicode_ci handles
        # case-insensitive equality without a function wrapper.
        offset = (page - 1) * per_page
        # Report the colour the Map reports: _effective_flag_color_sql is the
        # exact expression the map/analytics readers use, so the Registry page
        # and the Map cannot drift apart. api.registry.colors is dependency-free.
        # ladder_columns_available() is False until the ladder migration has
        # run, which keeps this query byte-identical to before on a database
        # that does not have warningLevel / blackLocked yet.
        effective_flag_color = _effective_flag_color_sql(
            "g", ladder=ladder_columns_available(cursor))
        effective_flag_color = f"COALESCE(({effective_flag_color}), ({registry_row_color_sql('r', ladder=ladder_columns_available(cursor))}))"
        # warningLevel / blackLocked / blackDispatchUnlocked for the page's
        # Clear Warning and Unlock buttons. Zeros where the columns are absent.
        ladder_select = _ladder_select_sql(cursor)
        cursor.execute(
            f"""
            SELECT
                r.businessID,
                r.businessName,
                r.businessSize,
                r.registrationType,
                r.businessType,
                r.lineOfBusiness,
                r.businessAddress,
                r.latitude,
                r.longitude,
                r.coordSource,
                r.matchStatus,
                r.matchScore,
                r.placeID,
                r.applicationStatus,
                r.lastRenewalDate,
                b.barangayID,
                b.barangayName,
                {_flag_source_sql("g", _OLD_REGISTRY_FLAG_SOURCE, cursor)}
                    AS flagSource,
                {effective_flag_color} AS flagColor,
                {ladder_select}
            FROM official_registry r
            LEFT JOIN barangays b ON r.barangayID = b.barangayID
            {_registry_pin_lateral_sql(cursor)}
            {where}
            ORDER BY r.businessName ASC
            LIMIT %s OFFSET %s
            """,
            params + [per_page, offset],
        )
        rows = cursor.fetchall()
        cursor.close()

        # Serialise dates and floats
        for row in rows:
            if row.get("lastRenewalDate"):
                row["lastRenewalDate"] = str(row["lastRenewalDate"])
            if row.get("latitude") is not None:
                row["latitude"] = float(row["latitude"])
            if row.get("longitude") is not None:
                row["longitude"] = float(row["longitude"])
            if row.get("matchScore") is not None:
                row["matchScore"] = float(row["matchScore"])

        return {
            "data":      rows,
            "total":     total,
            "page":      page,
            "per_page":  per_page,
            "pages":     max(1, -(-total // per_page)),   # ceiling division
        }, None

    except Exception as e:
        if 'cursor' in locals() and cursor:
            cursor.close()
        mysql.connection.rollback()
        return None, str(e)


def get_business_by_id(business_id):
    """Return a single business record with flagColor and inspection history."""
    try:
        # check_and_expire_old_permits is now handled by the APScheduler
        # background job in app.py — no longer called inline on read requests.
        cursor = mysql.connection.cursor()

        # Main record + latest flagColor via LATERAL join (replaces two
        # correlated scalar subqueries that previously ran one-per-row).
        # See get_all_businesses: report the colour the Map reports, not the raw
        # pin column, and read the ladder columns only when they exist.
        effective_flag_color = _effective_flag_color_sql(
            "g", ladder=ladder_columns_available(cursor))
        effective_flag_color = f"COALESCE(({effective_flag_color}), ({registry_row_color_sql('r', ladder=ladder_columns_available(cursor))}))"
        # Same three fields as the list, from one builder, so the detail
        # modal and the list row can never disagree.
        ladder_select = _ladder_select_sql(cursor)

        cursor.execute(
            f"""
            SELECT
                r.businessID,
                r.businessName,
                r.businessSize,
                r.registrationType,
                r.businessType,
                r.lineOfBusiness,
                r.businessAddress,
                r.latitude,
                r.longitude,
                r.coordSource,
                r.matchStatus,
                r.matchScore,
                r.placeID,
                r.applicationStatus,
                r.lastRenewalDate,
                b.barangayID,
                b.barangayName,
                {_flag_source_sql("g", _OLD_REGISTRY_FLAG_SOURCE, cursor)}
                    AS flagSource,
                {effective_flag_color} AS flagColor,
                {ladder_select}
            FROM official_registry r
            LEFT JOIN barangays b ON r.barangayID = b.barangayID
            {_registry_pin_lateral_sql(cursor)}
            WHERE r.businessID = %s
            """,
            (business_id,),
        )
        row = cursor.fetchone()

        if not row:
            cursor.close()
            return None, None

        if row.get("lastRenewalDate"):
            row["lastRenewalDate"] = str(row["lastRenewalDate"])
        if row.get("latitude") is not None:
            row["latitude"] = float(row["latitude"])
        if row.get("longitude") is not None:
            row["longitude"] = float(row["longitude"])
        if row.get("matchScore") is not None:
            row["matchScore"] = float(row["matchScore"])

        # Inspection history
        cursor.execute(
            """
            SELECT
                ir.reportID,
                ir.inspectionResult,
                ir.verificationStatus,
                ir.remarks,
                ir.photoPath,
                ir.nearestLandmark,
                ir.irTimestamp,
                ir.resolutionTime,
                u.fullName AS inspectorName
            FROM inspection_reports ir
            JOIN users u ON ir.userID = u.userID
            WHERE CAST(ir.targetID AS CHAR) = %s AND ir.targetType = 'business'
            ORDER BY ir.irTimestamp DESC
            """,
            (str(business_id),),
        )
        inspections = cursor.fetchall()
        cursor.close()

        # Serialise timestamps
        for i in inspections:
            if i.get("irTimestamp"):
                i["irTimestamp"] = str(i["irTimestamp"])

        row["inspectionHistory"] = inspections

        return row, None

    except Exception as e:
        return None, str(e)


def check_and_expire_old_permits():
    """
    Check if there are any active business permits from a previous calendar year.
    If so, mark them as 'Expired' and refresh their map pin colour, preserving
    current warning levels (or verified history on an unmigrated database).
    Also insert an in-app notification for all admin users and publish SSE.
    """
    try:
        cursor = mysql.connection.cursor()

        # Defensive: a Black locked business must not be expired by the
        # rollover either. The lock is independent of applicationStatus, so
        # without this a habitual offender would silently be re-registered as
        # merely Expired.
        registry_state_join = ""
        lock_guard = ""
        ladder = ladder_columns_available(cursor)
        if ladder:
            registry_state_join = """
                LEFT JOIN enforcement_state es
                  ON es.subjectType = 'business'
                 AND es.subjectID = CAST(r.businessID AS CHAR)
            """
            lock_guard = " AND COALESCE(es.blackLocked, 0) = 0"
        else:
            # Column absent. The permit status below still needs expiring; only
            # the pin colour is unknowable, so expire and leave the pin alone.
            pass

        # Keep the indexed column bare so idx_reg_renewal can use a range scan.
        previous_year_predicate = (
            "r.lastRenewalDate < MAKEDATE(YEAR(CURDATE()), 1)"
        )

        # 1. Count active businesses from previous years
        cursor.execute(
            f"""SELECT COUNT(*) AS cnt
                                FROM official_registry r
                                {registry_state_join}
                                WHERE {previous_year_predicate}
                                    AND r.applicationStatus = 'Active'{lock_guard}"""
        )
        row = cursor.fetchone()
        cnt = row["cnt"] if row else 0

        if cnt > 0:
            current_year = __import__('datetime').date.today().year

            # 2. Update map flag colors in geospatial_logs to Red (Expired)
            # utf8mb4_unicode_ci handles case-insensitive matching — LOWER(TRIM())
            # wrapping on column sides prevents the new indexes from being used.
            warning_sql = ("COALESCE(es.warningLevel, 0) >= 1" if ladder else """EXISTS (
                SELECT 1 FROM inspection_reports ir
                WHERE ir.targetType = 'geospatial_log' AND ir.targetID = g.logID
                  AND ir.verificationStatus = 'Verified' AND ir.inspectionResult = 'Orange'
            )""")
            cursor.execute(
                f"""
                UPDATE geospatial_logs g
                JOIN official_registry r ON g.detectedName = r.businessName AND g.barangayID = r.barangayID
                {registry_state_join}
                SET g.flagColor = CASE
                    WHEN {warning_sql} THEN 'Orange'
                    ELSE 'Red'
                END
                                WHERE {previous_year_predicate}
                                    AND r.applicationStatus = 'Active'{lock_guard}
                                """,
            )

            # 3. Update registry status to 'Expired'
            cursor.execute(
                f"""UPDATE official_registry r
                                        {registry_state_join}
                                        SET r.applicationStatus = 'Expired'
                                        WHERE {previous_year_predicate}
                                            AND r.applicationStatus = 'Active'{lock_guard}"""
            )

            # 4. Fetch admin userIDs
            cursor.execute(
                """
                SELECT userID FROM users
                WHERE userRole IN ('Admin', 'SUPER_ADMIN', 'System Administrator')
                  AND isActive = 1
                """
            )
            admins = cursor.fetchall() or []

            # 5. Insert system notification for admins
            title = "New Year Rollover Detected!"
            body = (
                f"Welcome to {current_year}! The system has automatically marked {cnt} "
                "active business permits from previous years as Expired and updated their map flags, "
                "preserving admin-verified monitoring warnings. "
                "Please upload the new registry to synchronize their statuses."
            )
            link = "/registry"

            for a in admins:
                aid = int(a["userID"])
                cursor.execute(
                    """
                    INSERT INTO revela_notifications
                        (recipientUserId, type, title, body, link)
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    (aid, "new_year_rollover", title, body, link),
                )

            mysql.connection.commit()
            cursor.close()

            # 6. Publish to admins via SSE
            try:
                from api.notifications import hub
                hub.publish_to_admins({
                    "type": "new_year_rollover",
                    "title": title,
                    "body": body,
                    "link": link,
                    "count": cnt,
                    "year": current_year
                })
            except Exception as sse_err:
                print(f"Failed to publish rollover SSE: {sse_err}")

            return {
                "detected": True,
                "count": cnt,
                "year": current_year
            }

        cursor.close()
        return None
    except Exception as e:
        print(f"check_and_expire_old_permits error: {e}")
        try:
            if 'cursor' in locals() and cursor:
                cursor.close()
        except Exception:
            pass
        return None
