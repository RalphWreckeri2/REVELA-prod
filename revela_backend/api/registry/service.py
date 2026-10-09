import pandas as pd
import requests as http
import io
import os
import re
from app import mysql
from api.models.geospatial import insert_green_flag
from api.utils.cancellation import is_cancelled, set_cancel
from api.registry import places_resolver


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
GEOCODE_MONTHLY_CAP = int(os.getenv("GEOCODE_MONTHLY_CAP", "8000"))
# 1500 geocodes per day
GEOCODE_DAILY_CAP = int(os.getenv("GEOCODE_DAILY_CAP", "1500"))
# maximum 1500 businesses per import batch
MAX_IMPORT_PER_BATCH = int(os.getenv("MAX_IMPORT_PER_BATCH", "1500"))
_geo_tables_ready = False
# no '%' characters
_GEO_MONTH_KEY = "DATE_SUB(CURDATE(), INTERVAL DAYOFMONTH(CURDATE()) - 1 DAY)"


def get_geocode_remaining_today():
    """Return remaining geocode requests allowed today."""
    global _geo_tables_ready
    cur = mysql.connection.cursor()
    try:
        if not _geo_tables_ready:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS places_api_usage (
                    usageDate DATE NOT NULL, kind VARCHAR(20) NOT NULL,
                    requestCount INT NOT NULL DEFAULT 0, PRIMARY KEY (usageDate, kind)
                ) ENGINE=InnoDB
            """)
            _geo_tables_ready = True
        cur.execute(
            "SELECT requestCount FROM places_api_usage WHERE usageDate = CURDATE() AND kind = 'geo_day'")
        row = cur.fetchone()
        used = int((row.get("requestCount") if isinstance(
            row, dict) else row[0]) or 0) if row else 0
        return max(0, GEOCODE_DAILY_CAP - used)
    finally:
        cur.close()


def get_geocode_remaining_month():
    """Return remaining geocode requests allowed this month."""
    global _geo_tables_ready
    cur = mysql.connection.cursor()
    try:
        cur.execute(
            f"SELECT requestCount FROM places_api_usage WHERE usageDate = {_GEO_MONTH_KEY} AND kind = 'geo_month'")
        row = cur.fetchone()
        used = int((row.get("requestCount") if isinstance(
            row, dict) else row[0]) or 0) if row else 0
        return max(0, GEOCODE_MONTHLY_CAP - used)
    finally:
        cur.close()


def _reserve_geocode_call():
    """Take one Geocoding request from the monthly + daily budget. False = over budget or DB problem."""
    global _geo_tables_ready
    cur = mysql.connection.cursor()
    try:
        if not _geo_tables_ready:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS places_api_usage (
                    usageDate DATE NOT NULL, kind VARCHAR(20) NOT NULL,
                    requestCount INT NOT NULL DEFAULT 0, PRIMARY KEY (usageDate, kind)
                ) ENGINE=InnoDB
            """)
            _geo_tables_ready = True
        cur.execute(
            f"INSERT IGNORE INTO places_api_usage (usageDate, kind, requestCount) VALUES ({_GEO_MONTH_KEY}, 'geo_month', 0)")
        cur.execute(
            "INSERT IGNORE INTO places_api_usage (usageDate, kind, requestCount) VALUES (CURDATE(), 'geo_day', 0)")
        cur.execute(f"""
            UPDATE places_api_usage SET requestCount = requestCount + 1
            WHERE usageDate = {_GEO_MONTH_KEY} AND kind = 'geo_month' AND requestCount < %s
        """, (GEOCODE_MONTHLY_CAP,))
        month_ok = cur.rowcount == 1
        day_ok = False
        if month_ok:
            cur.execute("""
                UPDATE places_api_usage SET requestCount = requestCount + 1
                WHERE usageDate = CURDATE() AND kind = 'geo_day' AND requestCount < %s
            """, (GEOCODE_DAILY_CAP,))
            day_ok = cur.rowcount == 1
            if not day_ok:
                cur.execute(f"""
                    UPDATE places_api_usage SET requestCount = requestCount - 1
                    WHERE usageDate = {_GEO_MONTH_KEY} AND kind = 'geo_month'
                """)
        mysql.connection.commit()
        return month_ok and day_ok
    except Exception as e:
        mysql.connection.rollback()
        print(f"[Geocode budget] error, skipping geocode: {e}")
        return False                 # fail closed
    finally:
        cur.close()


def reset_geocode_daily_quota() -> bool:
    """Reset the daily geocoding usage counter for CURDATE() to allow re-testing."""
    cur = mysql.connection.cursor()
    try:
        cur.execute(
            "DELETE FROM places_api_usage WHERE usageDate = CURDATE() AND kind = 'geo_day'")
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
    if not GOOGLE_MAPS_API_KEY:
        return None, None

    if not _reserve_geocode_call():
        return None, None            # row is still saved, just without coordinates

    address_parts = [
        str(part).strip() for part in [address, barangay, "Mataasnakahoy", "Batangas", "Philippines"]
        if _clean_str(part)
    ]
    full_address = ", ".join(address_parts)

    try:
        resp = http.get(
            "https://maps.googleapis.com/maps/api/geocode/json",
            params={"address": full_address, "key": GOOGLE_MAPS_API_KEY},
            timeout=10,
        )
        data = resp.json()
        if data.get("status") == "OK":
            loc = data["results"][0]["geometry"]["location"]
            return loc["lat"], loc["lng"]
    except Exception:
        pass
    return None, None


def _resolve_location(business_name, address, barangay, business_id=None, barangay_id=None, line_of_business=None):
    """Returns (lat, lng, meta).
    PLACES_RESOLVER_ENABLED=1 -> Places Text Search (+ quality-gated geocode fallback), meta describes provenance.
    Otherwise -> legacy _geocode behaviour unchanged, meta=None."""
    name_str = _clean_str(business_name) or ""
    addr_str = _clean_str(address) or ""
    brgy_str = _clean_str(barangay) or ""
    lob_str = _clean_str(line_of_business) or ""

    if places_resolver.enabled():
        return places_resolver.resolve_location(
            name_str, addr_str, brgy_str,
            business_id=business_id,
            barangay_id=barangay_id,
            line_of_business=lob_str,
            reserve_geocode=_reserve_geocode_call)

    # Local BPLO data often contains only vague location labels such as "District IV"
    # or "Purok 5". In those cases, use the business name + barangay as a geocode
    # fallback instead of failing outright; it still places the pin in the correct barangay.
    geo_target = addr_str
    if not geo_target:
        geo_target = name_str or brgy_str

    if not geo_target and not brgy_str:
        return None, None, None

    lat, lng = _geocode(geo_target, brgy_str)
    if lat is None and name_str and brgy_str:
        lat, lng = _geocode(f"{name_str}, {brgy_str}", brgy_str)
    return lat, lng, None


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


def _normalise_status(raw: str) -> str:
    mapping = {
        "active":         "Active",
        "expired":        "Expired",
        "revoked":        "Revoked",
        "pending":        "Pending",
        "for issuance":   "Pending",
        "cancelled":      "Revoked",
        "lapsed":         "Expired",
        "license issued": "Active",
        "issued":         "Active",
        "closed":         "Closed",
    }
    return mapping.get(str(raw).strip().lower(), "Pending")


def _status_to_flag_color(status: str) -> str:
    mapping = {
        "Active": "Green",
        "Pending": "Yellow",
        "Expired": "Red",
        "Revoked": "Black",
        "Closed": "Purple"
    }
    return mapping.get(status, "Yellow")


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


def _sync_flag_color(cursor, barangay_id, business_name: str, status: str, lat=None, lng=None, address=None, business_id=None):
    """
    Propagate a registry permit-status change to the business's map pin
    (preferring exact businessID match, then name + barangay).
    If no map pin exists yet and coordinates are provided, auto-seed a new pin.
    """
    flag_color = _status_to_flag_color(status)
    name_clean = str(business_name).strip()

    cursor.execute(
        """
        SELECT logID, flagColor, latitude, longitude
        FROM geospatial_logs
        WHERE (businessID IS NOT NULL AND businessID = %s)
           OR (businessID IS NULL AND barangayID = %s AND detectedName = %s)
        ORDER BY (businessID = %s) DESC, detectedDate DESC
        LIMIT 1
        """,
        (business_id, barangay_id, name_clean, business_id),
    )
    existing_pin = cursor.fetchone()

    if existing_pin:
        cursor.execute(
            """
            UPDATE geospatial_logs
            SET flagColor = %s,
                businessID = COALESCE(businessID, %s),
                latitude = COALESCE(latitude, %s),
                longitude = COALESCE(longitude, %s)
            WHERE logID = %s
            """,
            (flag_color, business_id, lat, lng, existing_pin["logID"]),
        )
    elif lat is not None and lng is not None:
        cursor.execute(
            """
            INSERT INTO geospatial_logs
                (barangayID, businessID, detectedName, latitude, longitude, flagColor, nearestLandmark)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (barangay_id, business_id, name_clean, lat, lng, flag_color, address),
        )


# ── Service functions ─────────────────────────────────────────────────────────
def upload_registry(file, ext: str):
    """Parse CSV/Excel → geocode → insert into OFFICIAL_REGISTRY.
    Returns (summary_dict, error_string)."""
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
            has_valid_coords = (
                df["latitude"].notna() & (df["latitude"].astype(str).str.strip() != "") &
                df["longitude"].notna() & (
                    df["longitude"].astype(str).str.strip() != "")
            )

        has_address = pd.Series(True, index=df.index)
        if "businessAddress" in df.columns:
            has_address = df["businessAddress"].notna() & (
                df["businessAddress"].astype(str).str.strip() != "")

        biz_id_col = "Business ID" if "Business ID" in df.columns else (
            "businessID" if "businessID" in df.columns else ("business_id" if "business_id" in df.columns else None))
        biz_ids = df[biz_id_col].astype(str).str.strip().str.lstrip("#").str.strip().str.upper(
        ) if biz_id_col else pd.Series("", index=df.index)
        is_new = ~biz_ids.isin(existing_db_ids)
        is_first_occurrence = ~biz_ids.duplicated()

        needs_geo = ~has_valid_coords & has_address & is_new & is_first_occurrence
        rows_needing_geocode = int(needs_geo.sum())

        if GOOGLE_MAPS_API_KEY and rows_needing_geocode > 0:
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
        geocoded_ok = 0
        geocoded_failed = 0
        skipped = 0
        errors = []
        inserted_ids = []

        seen_counts = {}

        from api.notifications import hub

        # Load all barangays once upfront instead of one DB cursor per row.
        barangay_lookup = _load_barangay_lookup()
        cursor = mysql.connection.cursor()

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

            raw_lat = row.get("latitude")
            raw_lng = row.get("longitude")
            if raw_lat is not None and raw_lng is not None and str(raw_lat).strip().lower() != "nan" and str(raw_lng).strip().lower() != "nan":
                try:
                    lat, lng = float(raw_lat), float(raw_lng)
                    geocoded_ok += 1
                except Exception:
                    lat, lng = None, None

            curr_resolve_key = places_resolver.compute_resolve_key(
                name_key, address_raw, barangay_id)
            geo_meta = {"coord_source": "csv",
                        "resolve_key": curr_resolve_key} if lat is not None else None
            lob = _clean_upper(row.get("lineOfBusiness"))
            if lat is None and address_raw:
                lat, lng, geo_meta = _resolve_location(
                    name_key, address_raw, barangay_raw,
                    business_id=biz_id, barangay_id=barangay_id,
                    line_of_business=lob)
                if lat is not None:
                    geocoded_ok += 1
                else:
                    geocoded_failed += 1
            elif lat is None:
                geocoded_failed += 1

            # Status of Application (license/permit standing)
            # Missing/blank status → Pending (Yellow), never Active. See sync_registry.
            status_raw = (
                row.get("applicationStatus")
                or "Pending"
            )
            status = _normalise_status(status_raw)

            # Registration Type (New vs Renewal)
            reg_type = _normalise_registration_type(
                row.get("registrationType"))

            # Renewal date
            renewal_date = _parse_renewal_date(row.get("lastRenewalDate"))

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
                    curr_resolve_key,
                ),
            )

            if cursor.rowcount > 0:
                inserted += 1
                inserted_ids.append(biz_id)
                places_resolver.record_coord_meta(cursor, biz_id, geo_meta)
                flag_color = _status_to_flag_color(status)
                # Auto-seed Flag baseline into GEOSPATIAL_LOGS
                insert_green_flag(
                    barangay_id,
                    name_key,
                    lat,
                    lng,
                    address_raw,
                    color=flag_color,
                    business_id=biz_id
                )
            else:
                skipped += 1

        mysql.connection.commit()
        cursor.close()

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
            "geocoded_ok":      geocoded_ok,
            "geocoded_failed":  geocoded_failed,
            "skipped":          skipped,
            # cap at 20 so response stays small
            "errors":           errors[:20],
        }, None

    except Exception as e:
        return None, str(e)


def sync_registry(file, ext: str):
    """Parse CSV/Excel → geocode → upsert OFFICIAL_REGISTRY.
    Existing rows match on businessName + barangayID and are overwritten
    with file values; new rows are inserted (same rules as upload).
    Returns (summary_dict, error_string)."""
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

        inserted = 0
        updated = 0
        skipped = 0
        geocoded_ok = 0
        geocoded_failed = 0
        errors = []
        inserted_ids = []
        matched_db_ids = set()

        from api.notifications import hub

        # Load all barangays once upfront instead of one DB cursor per row.
        barangay_lookup = _load_barangay_lookup()
        cursor = mysql.connection.cursor()

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
                SELECT businessID, latitude, longitude, coordSource, matchStatus, resolveKey FROM official_registry
                WHERE businessID = %s
                """,
                (biz_id,),
            )
            existing = cursor.fetchone()

            is_locked = False
            is_rejected = False
            if existing:
                src = (existing.get("coordSource") or "").strip().lower()
                m_stat = (existing.get("matchStatus") or "").strip().lower()
                if src == "manual" or m_stat == "approved":
                    is_locked = True
                if m_stat == "rejected":
                    is_rejected = True

            curr_resolve_key = places_resolver.compute_resolve_key(
                name_key, address_raw, barangay_id)
            lob = _clean_upper(row.get("lineOfBusiness"))
            lat, lng = None, None
            reused_existing = False
            geo_meta = None

            raw_lat = row.get("latitude")
            raw_lng = row.get("longitude")
            csv_has_coords = False
            if raw_lat is not None and raw_lng is not None and str(raw_lat).strip().lower() != "nan" and str(raw_lng).strip().lower() != "nan":
                try:
                    lat, lng = float(raw_lat), float(raw_lng)
                    csv_has_coords = True
                except Exception:
                    csv_has_coords = False
                    lat, lng = None, None

            if is_locked:
                # Locked records (manual or approved) strictly preserve existing coordinates.
                # CSV or automated sweeps cannot overwrite them.
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
            elif existing and existing.get("resolveKey") == curr_resolve_key:
                # Unchanged record according to SHA-1 resolveKey: consumes zero Google API calls!
                if existing.get("latitude") is not None and existing.get("longitude") is not None:
                    lat = float(existing["latitude"])
                    lng = float(existing["longitude"])
                    reused_existing = True
                    geocoded_ok += 1
                else:
                    # Previously evaluated with identical key as unlocatable
                    geocoded_failed += 1
            elif existing and existing.get("latitude") is not None and existing.get("longitude") is not None:
                # Unlocked existing business already has valid coordinates — reuse them (consumes 0 Google quota!)
                lat = float(existing["latitude"])
                lng = float(existing["longitude"])
                reused_existing = True
                geocoded_ok += 1
            elif is_rejected:
                # Rejected match: do not re-send to automated resolver
                lat, lng = None, None
                geocoded_failed += 1
            elif address_raw:
                lat, lng, geo_meta = _resolve_location(
                    name_key, address_raw, barangay_raw,
                    business_id=biz_id, barangay_id=barangay_id,
                    line_of_business=lob)
                if lat is not None:
                    geocoded_ok += 1
                else:
                    geocoded_failed += 1
            else:
                geocoded_failed += 1

            status_raw = (
                row.get("applicationStatus")
                or "Active"
            )
            if geo_meta is None and lat is not None and not reused_existing:
                # coordinates came from the uploaded file
                geo_meta = {"coord_source": "csv",
                            "resolve_key": curr_resolve_key}
            status = _normalise_status(status_raw)

            reg_type = _normalise_registration_type(
                row.get("registrationType"))

            renewal_date = _parse_renewal_date(row.get("lastRenewalDate"))

            btype = _clean_upper(row.get("businessType"))
            lob = _clean_upper(row.get("lineOfBusiness"))
            addr = address_raw
            bsize = _clean_upper(row.get("businessSize"))

            if existing:
                if is_locked:
                    final_lat = existing.get("latitude")
                    final_lng = existing.get("longitude")
                else:
                    final_lat = lat if lat is not None else existing.get(
                        "latitude")
                    final_lng = lng if lng is not None else existing.get(
                        "longitude")

                if not is_locked and not reused_existing and lat is not None:
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
                            curr_resolve_key,
                            biz_id,
                        ),
                    )
                else:
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
                            curr_resolve_key,
                            biz_id,
                        ),
                    )
                updated += 1
                if not is_locked and not reused_existing and lat is not None:
                    places_resolver.record_coord_meta(cursor, biz_id, geo_meta)
                # Propagate status → flag color on the map pin (auto-seed if missing)
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
                        curr_resolve_key,
                    ),
                )
                if cursor.rowcount > 0:
                    inserted += 1
                    inserted_ids.append(biz_id)
                    places_resolver.record_coord_meta(cursor, biz_id, geo_meta)
                    flag_color = _status_to_flag_color(status)
                    insert_green_flag(
                        barangay_id,
                        name_key,
                        lat,
                        lng,
                        addr,
                        color=flag_color,
                        business_id=biz_id
                    )

        mysql.connection.commit()
        cursor.close()

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
            "geocoded_ok":      geocoded_ok,
            "geocoded_failed":  geocoded_failed,
            "skipped":          skipped,
            "errors":           errors[:20],
        }, None

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
        cursor = mysql.connection.cursor()

        # Load all businesses without coordinates that are eligible for snapping
        cursor.execute("""
            SELECT businessID, barangayID, businessName, businessAddress,
                   lineOfBusiness, applicationStatus, coordSource, matchStatus,
                   resolveKey, latitude, longitude
            FROM official_registry
            WHERE (
                    latitude IS NULL
                    OR (
                        coordSource = 'geocode'
                        AND longitude IS NOT NULL
                        AND (
                            resolveKey IS NULL
                            OR resolveKey <> SHA1(CONCAT(
                                LOWER(TRIM(COALESCE(businessName, ''))), '|',
                                LOWER(TRIM(COALESCE(businessAddress, ''))), '|',
                                LOWER(TRIM(COALESCE(CAST(barangayID AS CHAR), ''))),
                                '|places-refresh-v1'
                            ))
                        )
                    )
                  )
              AND matchStatus NOT IN ('approved', 'rejected')
              AND (coordSource IS NULL OR coordSource NOT IN ('manual', 'csv'))
            ORDER BY businessID
            LIMIT %s
        """, (int(limit),))
        candidates = cursor.fetchall()
        cursor.close()

        total = len(candidates)
        if total == 0:
            msg = "All registry businesses already have coordinates — nothing to snap!"
            hub.publish_to_admins({
                "type": "snap_progress",
                "stage": "completed",
                "percentage": 100,
                "snapped": 0,
                "failed": 0,
                "cached": 0,
                "total": 0,
                "status": msg
            })
            hub.publish_to_admins({"type": "registry_updated"})
            return {
                "total_candidates": 0,
                "snapped": 0,
                "failed": 0,
                "cached": 0,
                "message": msg
            }, None

        hub.publish_to_admins({
            "type": "snap_progress",
            "stage": "running",
            "percentage": 0,
            "snapped": 0,
            "failed": 0,
            "cached": 0,
            "total": total,
            "status": f"Found {total} businesses to resolve. Starting Places name search..."
        })

        # Load barangay lookup for name→ID resolution
        barangay_lookup = _load_barangay_lookup()

        snapped = 0
        failed = 0
        cached = 0
        budget_hit = False

        for idx, biz in enumerate(candidates):
            bid = biz.get("businessID") if isinstance(biz, dict) else biz[0]
            brgy_id = biz.get("barangayID") if isinstance(
                biz, dict) else biz[1]
            name = biz.get("businessName") if isinstance(biz, dict) else biz[2]
            address = biz.get("businessAddress") if isinstance(
                biz, dict) else biz[3]
            lob = biz.get("lineOfBusiness") if isinstance(
                biz, dict) else biz[4]
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
                # Break before attempting API calls so we don't save a budget failure as unresolvable
                break

            lat, lng, geo_meta = None, None, None
            if places_resolver.enabled():
                lat, lng, geo_meta = places_resolver.resolve_location(
                    name or "", address or "", brgy_name or "",
                    business_id=bid,
                    barangay_id=brgy_id,
                    line_of_business=lob or "",
                    reserve_geocode=_reserve_geocode_call,
                    refresh_geocode=refresh_geocode
                )
                if geo_meta and geo_meta.get("resolve_key") is None:
                    geo_meta["resolve_key"] = curr_key

                if lat is None and geo_meta and geo_meta.get("budget_exhausted"):
                    budget_hit = True
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
                                            AND matchStatus NOT IN ('approved', 'rejected')
                """, (lat, lng, coord_src, place_id, place_id_kind,
                      match_score, match_status, curr_key, bid, int(refresh_geocode)))

                if cur2.rowcount > 0:
                    # Seed or update the map pin
                    flag_color = _status_to_flag_color(app_status)
                    _sync_flag_color(cur2, brgy_id, name, app_status, lat, lng,
                                     address, business_id=bid)
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
            msg += f" Daily geocoding budget reached — run again tomorrow to continue (progress is saved)."

        hub.publish_to_admins({
            "type": "snap_progress",
            "stage": "completed",
            "percentage": 100,
            "snapped": snapped,
            "failed": failed,
            "cached": cached,
            "total": total,
            "status": msg,
            "budget_hit": budget_hit
        })
        hub.publish_to_admins({"type": "registry_updated"})

        return {
            "total_candidates": total,
            "snapped": snapped,
            "failed": failed,
            "cached": cached,
            "budget_hit": budget_hit,
            "message": msg
        }, None

    except Exception as e:
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
            "SELECT businessID, businessName, barangayID FROM official_registry WHERE businessID = %s", (business_id,))
        row = cursor.fetchone()
        if not row:
            cursor.close()
            return False, "Business not found"

        old_name = row["businessName"]
        barangay_id = row["barangayID"]

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
            params.append(_normalise_status(data["applicationStatus"]))
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
                        WHERE LOWER(detectedName) = LOWER(%s) AND barangayID = %s
                    """, (new_name, old_name, barangay_id))
                current_name = new_name

            # Keep the map pin in sync when the permit status changes
            # (otherwise an Expired/Revoked/Closed business stays Green on the map)
            if "applicationStatus" in data:
                _sync_flag_color(
                    cursor,
                    barangay_id,
                    current_name,
                    _normalise_status(data["applicationStatus"]),
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


def delete_business(business_id):
    """Delete a business from the registry."""
    try:
        cursor = mysql.connection.cursor()

        cursor.execute(
            """SELECT businessID, businessName, barangayID, latitude, longitude, placeID
               FROM official_registry WHERE businessID = %s""",
            (business_id,)
        )
        row = cursor.fetchone()
        if not row:
            cursor.close()
            return False, "Business not found"

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
    except Exception as e:
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
                CASE
                    WHEN g.logID IS NULL THEN NULL
                    WHEN g.placeID IS NOT NULL THEN 'registry_and_maps'
                    ELSE 'registry_only'
                END AS flagSource,
                g.flagColor
            FROM official_registry r
            LEFT JOIN barangays b ON r.barangayID = b.barangayID
            LEFT JOIN LATERAL (
                SELECT logID, placeID, flagColor
                FROM geospatial_logs
                WHERE (businessID IS NOT NULL AND businessID = r.businessID)
                   OR (businessID IS NULL AND barangayID = r.barangayID AND detectedName = r.businessName)
                ORDER BY (businessID = r.businessID) DESC, detectedDate DESC
                LIMIT 1
            ) g ON TRUE
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
        cursor.execute(
            """
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
                CASE
                    WHEN g.logID IS NULL THEN NULL
                    WHEN g.placeID IS NOT NULL THEN 'registry_and_maps'
                    ELSE 'registry_only'
                END AS flagSource,
                g.flagColor
            FROM official_registry r
            LEFT JOIN barangays b ON r.barangayID = b.barangayID
            LEFT JOIN LATERAL (
                SELECT logID, placeID, flagColor
                FROM geospatial_logs
                WHERE (businessID IS NOT NULL AND businessID = r.businessID)
                   OR (businessID IS NULL AND barangayID = r.barangayID AND detectedName = r.businessName)
                ORDER BY (businessID = r.businessID) DESC, detectedDate DESC
                LIMIT 1
            ) g ON TRUE
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
    If so, mark them as 'Expired' and set their map pin flagColor to 'Red'.
    Also insert an in-app notification for all admin users and publish SSE.
    """
    try:
        cursor = mysql.connection.cursor()

        # 1. Count active businesses from previous years
        cursor.execute(
            """
            SELECT COUNT(*) AS cnt FROM official_registry
            WHERE YEAR(lastRenewalDate) < YEAR(CURDATE()) AND applicationStatus = 'Active'
            """
        )
        row = cursor.fetchone()
        cnt = row["cnt"] if row else 0

        if cnt > 0:
            current_year = __import__('datetime').date.today().year

            # 2. Update map flag colors in geospatial_logs to Red (Expired)
            # utf8mb4_unicode_ci handles case-insensitive matching — LOWER(TRIM())
            # wrapping on column sides prevents the new indexes from being used.
            cursor.execute(
                """
                UPDATE geospatial_logs g
                JOIN official_registry r ON g.detectedName = r.businessName AND g.barangayID = r.barangayID
                SET g.flagColor = 'Red'
                WHERE YEAR(r.lastRenewalDate) < YEAR(CURDATE()) AND r.applicationStatus = 'Active'
                """
            )

            # 3. Update registry status to 'Expired'
            cursor.execute(
                """
                UPDATE official_registry
                SET applicationStatus = 'Expired'
                WHERE YEAR(lastRenewalDate) < YEAR(CURDATE()) AND applicationStatus = 'Active'
                """
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
                "active business permits from previous years as Expired and their map flags as Red. "
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
