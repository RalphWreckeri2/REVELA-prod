import pandas as pd
import requests as http
import io
import os
from app import mysql
from api.models.geospatial import insert_green_flag
from api.utils.cancellation import is_cancelled, set_cancel


GOOGLE_MAPS_API_KEY = os.getenv("GOOGLE_MAPS_API_KEY")

# Column name aliases — maps whatever the Excel/CSV header is → our internal key.
# Add more aliases here if the BPLO file uses different headers.
COLUMN_MAP = {
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

    # application / permit status
    "status":                   "applicationStatus",
    "application_status":       "applicationStatus",
    "status_of_application":    "applicationStatus",
    "statusofapplication":      "applicationStatus",
    "status_of_registration":   "registrationStatus",
    "statusofregistration":     "registrationStatus",

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

    # renewal date
    "last_renewal_date":   "lastRenewalDate",
    "lastrenewaldate":     "lastRenewalDate",
    "renewal_date":        "lastRenewalDate",
    "renewaldate":         "lastRenewalDate",
    "issue_date":          "lastRenewalDate",
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

def _normalise_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Rename raw CSV/Excel headers to our internal field names."""
    df.columns = [str(c).strip() for c in df.columns]
    rename = {}
    for col in df.columns:
        key = col.lower().replace(" ", "_").replace("-", "_")
        if key in COLUMN_MAP:
            rename[col] = COLUMN_MAP[key]
    df = df.rename(columns=rename)
    return df


GEOCODE_MONTHLY_CAP  = int(os.getenv("GEOCODE_MONTHLY_CAP", "8000"))   # free tier is 10,000/month
GEOCODE_DAILY_CAP    = int(os.getenv("GEOCODE_DAILY_CAP", "500"))      # 500 geocodes per day
MAX_IMPORT_PER_BATCH = int(os.getenv("MAX_IMPORT_PER_BATCH", "500"))   # maximum 500 businesses per import batch
_geo_tables_ready = False
_GEO_MONTH_KEY = "DATE_SUB(CURDATE(), INTERVAL DAYOFMONTH(CURDATE()) - 1 DAY)"   # no '%' characters


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
        cur.execute("SELECT requestCount FROM places_api_usage WHERE usageDate = CURDATE() AND kind = 'geo_day'")
        row = cur.fetchone()
        used = int((row.get("requestCount") if isinstance(row, dict) else row[0]) or 0) if row else 0
        return max(0, GEOCODE_DAILY_CAP - used)
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
        cur.execute(f"INSERT IGNORE INTO places_api_usage (usageDate, kind, requestCount) VALUES ({_GEO_MONTH_KEY}, 'geo_month', 0)")
        cur.execute("INSERT IGNORE INTO places_api_usage (usageDate, kind, requestCount) VALUES (CURDATE(), 'geo_day', 0)")
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


def _geocode(address: str, barangay: str) -> tuple[float | None, float | None]:
    """Call Google Geocoding API for a business address.
    Uses the full business address plus barangay for better accuracy.
    Returns (lat, lng) or (None, None) on failure."""
    if not GOOGLE_MAPS_API_KEY:
        return None, None

    if not _reserve_geocode_call():
        return None, None            # row is still saved, just without coordinates

    address_parts = [
        part.strip() for part in [address, barangay, "Mataasnakahoy", "Batangas", "Philippines"]
        if part and str(part).strip()
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
        name = row["barangayName"].strip()
        lookup[name.lower()] = row["barangayID"]
        # Also index without spaces for fuzzy matching
        lookup[name.lower().replace(" ", "")] = row["barangayID"]
    return lookup


def _resolve_barangay_id(barangay_name: str, lookup: dict[str, int]) -> int | None:
    """
    Resolve a raw barangay name to a barangayID using a preloaded lookup dict.
    Falls back to partial matching when an exact match isn't found.
    """
    if not barangay_name or not barangay_name.strip():
        return None

    cleaned = barangay_name.strip()
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

    return None


def _get_barangay_id(barangay_name: str) -> int | None:
    """
    Single-use lookup for callers outside of bulk import loops.
    Uses a fresh DB query — prefer _resolve_barangay_id + _load_barangay_lookup
    when processing many rows at once.
    """
    lookup = _load_barangay_lookup()
    return _resolve_barangay_id(barangay_name, lookup)


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
        "renewal":        "Pending",
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
        return pd.to_datetime(raw).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return None


def _sync_flag_color(cursor, barangay_id, business_name: str, status: str, lat=None, lng=None, address=None):
    """
    Propagate a registry permit-status change to the business's map pin
    (its most recent geospatial_logs entry, matched case-insensitively on
    name + barangay — the same linkage the Registry page uses).
    If no map pin exists yet and coordinates are provided, auto-seed a new pin.
    """
    flag_color = _status_to_flag_color(status)
    name_clean = str(business_name).strip()

    cursor.execute(
        """
        SELECT logID, flagColor, latitude, longitude
        FROM geospatial_logs
        WHERE barangayID = %s AND detectedName = %s
        ORDER BY detectedDate DESC
        LIMIT 1
        """,
        (barangay_id, name_clean),
    )
    existing_pin = cursor.fetchone()

    if existing_pin:
        pin_id = existing_pin["logID"] if isinstance(existing_pin, dict) else existing_pin[0]
        cursor.execute(
            """
            UPDATE geospatial_logs
            SET flagColor = %s,
                latitude = COALESCE(latitude, %s),
                longitude = COALESCE(longitude, %s)
            WHERE logID = %s
            """,
            (flag_color, lat, lng, pin_id),
        )
    elif lat is not None and lng is not None:
        cursor.execute(
            """
            INSERT INTO geospatial_logs
                (barangayID, detectedName, latitude, longitude, flagColor, nearestLandmark)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (barangay_id, name_clean, lat, lng, flag_color, address),
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

        # Count rows that actually need geocoding (those without valid pre-filled coordinates)
        rows_needing_geocode = total_rows
        if "latitude" in df.columns and "longitude" in df.columns:
            has_valid_coords = (
                df["latitude"].notna() & (df["latitude"].astype(str).str.strip() != "") &
                df["longitude"].notna() & (df["longitude"].astype(str).str.strip() != "")
            )
            rows_needing_geocode = int((~has_valid_coords).sum())

        if rows_needing_geocode > 0:
            remaining_today = get_geocode_remaining_today()
            if remaining_today <= 0:
                return None, (
                    f"Daily geocoding quota reached ({GEOCODE_DAILY_CAP}/{GEOCODE_DAILY_CAP} businesses mapped today). "
                    "Please import your next batch of businesses tomorrow, or include latitude and longitude columns for all rows in your CSV."
                )

            if rows_needing_geocode > remaining_today:
                return None, (
                    f"Remaining geocoding quota for today is {remaining_today} businesses ({GEOCODE_DAILY_CAP - remaining_today} mapped already today). "
                    f"Your file requires geocoding for {rows_needing_geocode} businesses without coordinates. "
                    f"Please upload a file with at most {remaining_today} businesses to geocode, or wait until tomorrow so they all get pins."
                )

        inserted = 0
        geocoded_ok = 0
        geocoded_failed = 0
        skipped = 0
        errors = []
        inserted_ids = []  # track newly inserted businessIDs for scoped auto-snap

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

            # businessName is required
            if not business_name or str(business_name).strip() == "":
                skipped += 1
                errors.append(f"Row {idx + 2}: missing businessName — skipped")
                continue

            # Resolve barangay using the preloaded dict (no per-row DB call)
            barangay_raw = row.get("barangay") or ""
            barangay_id = _resolve_barangay_id(barangay_raw, barangay_lookup) if barangay_raw else None

            # If barangay not found, skip row — barangayID is NOT NULL
            if barangay_id is None:
                skipped += 1
                errors.append(
                    f"Row {idx + 2}: barangay '{barangay_raw}' not found — skipped")
                continue

            # Geocode
            address_raw = row.get("businessAddress") or ""
            lat, lng = None, None

            raw_lat = row.get("latitude")
            raw_lng = row.get("longitude")
            if raw_lat and raw_lng:
                try:
                    lat, lng = float(raw_lat), float(raw_lng)
                    geocoded_ok += 1
                except Exception:
                    lat, lng = None, None

            if lat is None and address_raw:
                lat, lng = _geocode(address_raw, barangay_raw)
                if lat is not None:
                    geocoded_ok += 1
                else:
                    geocoded_failed += 1
            elif lat is None:
                geocoded_failed += 1

            # Status (BPLO files may use application or registration status columns)
            # Missing/blank status → Pending (Yellow), never Active. See sync_registry.
            status_raw = (
                row.get("applicationStatus")
                or row.get("registrationStatus")
                or "Pending"
            )
            status = _normalise_status(status_raw)

            # Renewal date
            renewal_date = _parse_renewal_date(row.get("lastRenewalDate"))

            name_key = str(business_name).strip()

            # Insert — skip duplicates (same name + barangayID).
            # Collation utf8mb4_unicode_ci is case-insensitive so LOWER() is
            # redundant on both sides and prevents index use — removed.
            cursor.execute(
                """
                INSERT INTO official_registry
                    (barangayID, businessName, businessType, lineOfBusiness,
                    businessAddress, latitude, longitude, applicationStatus,
                    lastRenewalDate, businessSize)
                SELECT %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                FROM DUAL
                WHERE NOT EXISTS (
                    SELECT 1 FROM official_registry
                    WHERE businessName = %s
                    AND barangayID = %s
                )
                """,
                (
                    barangay_id,
                    name_key,
                    str(row.get("businessType") or "").strip() or None,
                    str(row.get("lineOfBusiness") or "").strip() or None,
                    str(address_raw).strip() or None,
                    lat,
                    lng,
                    status,
                    renewal_date,
                    str(row.get("businessSize") or "").strip() or None,
                    # WHERE NOT EXISTS params
                    name_key,
                    barangay_id,
                ),
            )

            if cursor.rowcount > 0:
                inserted += 1
                new_id = cursor.lastrowid
                if new_id:
                    inserted_ids.append(new_id)
                flag_color = _status_to_flag_color(status)
                # Auto-seed Flag baseline into GEOSPATIAL_LOGS
                insert_green_flag(
                    barangay_id,
                    name_key,
                    lat,
                    lng,
                    str(address_raw).strip() or None,
                    color=flag_color
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
        geocoded_ok = 0
        geocoded_failed = 0
        skipped = 0
        errors = []
        inserted_ids = []  # track newly inserted businessIDs for scoped auto-snap

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

            if not business_name or str(business_name).strip() == "":
                skipped += 1
                errors.append(f"Row {idx + 2}: missing businessName — skipped")
                continue

            barangay_raw = row.get("barangay") or ""
            barangay_id = _resolve_barangay_id(barangay_raw, barangay_lookup) if barangay_raw else None

            if barangay_id is None:
                skipped += 1
                errors.append(
                    f"Row {idx + 2}: barangay '{barangay_raw}' not found — skipped")
                continue

            name_key = str(business_name).strip()
            # Check if this business already exists in the database
            cursor.execute(
                """
                SELECT businessID, latitude, longitude FROM official_registry
                WHERE businessName = %s AND barangayID = %s
                LIMIT 1
                """,
                (name_key, barangay_id),
            )
            existing = cursor.fetchone()

            address_raw = row.get("businessAddress") or ""
            lat, lng = None, None

            raw_lat = row.get("latitude")
            raw_lng = row.get("longitude")
            if raw_lat and raw_lng:
                try:
                    lat, lng = float(raw_lat), float(raw_lng)
                    geocoded_ok += 1
                except Exception:
                    lat, lng = None, None
            elif existing and existing.get("latitude") is not None and existing.get("longitude") is not None:
                # Existing business already has valid coordinates — reuse them (consumes 0 Google quota!)
                lat, lng = float(existing["latitude"]), float(existing["longitude"])
                geocoded_ok += 1
            elif address_raw:
                lat, lng = _geocode(address_raw, barangay_raw)
                if lat is not None:
                    geocoded_ok += 1
                else:
                    geocoded_failed += 1
            else:
                geocoded_failed += 1

            status_raw = (
                row.get("applicationStatus")
                or row.get("registrationStatus")
                or "Active"
            )
            status = _normalise_status(status_raw)

            renewal_date = _parse_renewal_date(row.get("lastRenewalDate"))

            btype = str(row.get("businessType") or "").strip() or None
            lob = str(row.get("lineOfBusiness") or "").strip() or None
            addr = str(address_raw).strip() or None
            bsize = str(row.get("businessSize") or "").strip() or None

            if existing:
                # Preserve existing coordinates to avoid overwriting exact pins from detection scan with generic geocoded ones
                final_lat = existing.get("latitude") if existing.get("latitude") is not None else lat
                final_lng = existing.get("longitude") if existing.get("longitude") is not None else lng

                cursor.execute(
                    """
                    UPDATE official_registry SET
                        businessType = %s,
                        lineOfBusiness = %s,
                        businessAddress = %s,
                        latitude = %s,
                        longitude = %s,
                        applicationStatus = %s,
                        lastRenewalDate = %s,
                        businessSize = %s
                    WHERE businessID = %s
                    """,
                    (
                        btype,
                        lob,
                        addr,
                        final_lat,
                        final_lng,
                        status,
                        renewal_date,
                        bsize,
                        existing["businessID"],
                    ),
                )
                updated += 1
                # Propagate status → flag color on the map pin (auto-seed if missing)
                _sync_flag_color(cursor, barangay_id, name_key, status, final_lat, final_lng, addr)
            else:
                cursor.execute(
                    """
                    INSERT INTO official_registry
                        (barangayID, businessName, businessType, lineOfBusiness,
                        businessAddress, latitude, longitude, applicationStatus,
                        lastRenewalDate, businessSize)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
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
                    ),
                )
                if cursor.rowcount > 0:
                    inserted += 1
                    new_id = cursor.lastrowid
                    if new_id:
                        inserted_ids.append(new_id)
                    flag_color = _status_to_flag_color(status)
                    insert_green_flag(
                        barangay_id,
                        name_key,
                        lat,
                        lng,
                        addr,
                        color=flag_color
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


def update_business(business_id: int, data: dict):
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
            params.append(str(data["businessName"]).strip())
        if "businessType" in data:
            update_fields.append("businessType = %s")
            params.append(str(data["businessType"]).strip()
                          if data["businessType"] else None)
        if "lineOfBusiness" in data:
            update_fields.append("lineOfBusiness = %s")
            params.append(str(data["lineOfBusiness"]).strip()
                          if data["lineOfBusiness"] else None)
        if "businessAddress" in data:
            update_fields.append("businessAddress = %s")
            params.append(str(data["businessAddress"]).strip()
                          if data["businessAddress"] else None)
        if "applicationStatus" in data:
            update_fields.append("applicationStatus = %s")
            params.append(_normalise_status(data["applicationStatus"]))
        if "businessSize" in data:
            update_fields.append("businessSize = %s")
            params.append(str(data["businessSize"]).strip()
                          if data["businessSize"] else None)

        if update_fields:
            query = f"UPDATE official_registry SET {', '.join(update_fields)} WHERE businessID = %s"
            params.append(business_id)
            cursor.execute(query, tuple(params))

            # If the business name changed, update geospatial_logs to maintain the linkage
            current_name = old_name
            if "businessName" in data:
                new_name = str(data["businessName"]).strip()
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


def delete_business(business_id: int):
    """Delete a business from the registry."""
    try:
        cursor = mysql.connection.cursor()

        cursor.execute(
            "SELECT businessID, businessName, barangayID FROM official_registry WHERE businessID = %s", (business_id,))
        row = cursor.fetchone()
        if not row:
            cursor.close()
            return False, "Business not found"

        # Find associated geospatial logs mapped to this business
        cursor.execute(
            "SELECT logID FROM geospatial_logs WHERE LOWER(detectedName) = LOWER(%s) AND barangayID = %s",
            (row["businessName"], row["barangayID"])
        )
        logs = cursor.fetchall()

        for log in logs:
            cursor.execute(
                "DELETE FROM inspection_reports WHERE targetID = %s", (log["logID"],))
            cursor.execute(
                "DELETE FROM geospatial_logs WHERE logID = %s", (log["logID"],))

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


def get_all_businesses(barangay_id=None, status=None, search=None, page=1, per_page=10):
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

        if search:
            conditions.append(
                "(r.businessName LIKE %s OR r.businessType LIKE %s OR r.businessAddress LIKE %s)"
            )
            like = f"%{search}%"
            params.extend([like, like, like])

        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

        # Total count
        cursor.execute(
            f"SELECT COUNT(*) AS total FROM official_registry r {where}",
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
                r.businessType,
                r.lineOfBusiness,
                r.businessAddress,
                r.latitude,
                r.longitude,
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
                WHERE barangayID = r.barangayID
                  AND detectedName = r.businessName
                ORDER BY detectedDate DESC
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

        # Serialise dates
        for row in rows:
            if row.get("lastRenewalDate"):
                row["lastRenewalDate"] = str(row["lastRenewalDate"])

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


def get_business_by_id(business_id: int):
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
                r.businessType,
                r.lineOfBusiness,
                r.businessAddress,
                r.latitude,
                r.longitude,
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
                WHERE barangayID = r.barangayID
                  AND detectedName = r.businessName
                ORDER BY detectedDate DESC
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
            WHERE ir.targetID = %s AND ir.targetType = 'business'
            ORDER BY ir.irTimestamp DESC
            """,
            (business_id,),
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

