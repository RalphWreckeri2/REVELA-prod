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


def _geocode(address: str, barangay: str) -> tuple[float | None, float | None]:
    """Call Google Geocoding API for a business address.
    Uses the full business address plus barangay for better accuracy.
    Returns (lat, lng) or (None, None) on failure."""
    if not GOOGLE_MAPS_API_KEY:
        return None, None

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


def _get_barangay_id(barangay_name: str) -> int | None:
    if not barangay_name or not barangay_name.strip():
        return None

    # Resolve district alias first
    cleaned = barangay_name.strip()
    alias = DISTRICT_ALIASES.get(cleaned.lower())
    if alias:
        cleaned = alias

    cursor = mysql.connection.cursor()

    # 1. Exact match (case-insensitive)
    cursor.execute(
        "SELECT barangayID FROM barangays WHERE LOWER(barangayName) = LOWER(%s)",
        (cleaned,),
    )
    row = cursor.fetchone()
    if row:
        cursor.close()
        return row["barangayID"]

    # 2. Partial match — also try removing spaces
    cleaned_nospace = cleaned.replace(" ", "")
    cursor.execute(
        """
        SELECT barangayID FROM barangays 
        WHERE LOWER(REPLACE(barangayName, ' ', '')) LIKE LOWER(%s)
        OR LOWER(barangayName) LIKE LOWER(%s)
        """,
        (f"%{cleaned_nospace}%", f"%{cleaned}%"),
    )
    row = cursor.fetchone()
    cursor.close()
    return row["barangayID"] if row else None


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
        "Expired": "Orange",
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
    cursor.execute(
        """
        UPDATE geospatial_logs g
        JOIN (
            SELECT logID
            FROM geospatial_logs
            WHERE barangayID = %s AND LOWER(TRIM(detectedName)) = LOWER(TRIM(%s))
            ORDER BY detectedDate DESC
            LIMIT 1
        ) latest ON g.logID = latest.logID
        SET g.flagColor = %s
        """,
        (barangay_id, str(business_name).strip(), flag_color),
    )
    if cursor.rowcount == 0 and lat is not None and lng is not None:
        cursor.execute(
            """
            INSERT INTO geospatial_logs
                (barangayID, detectedName, latitude, longitude, flagColor, nearestLandmark)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (barangay_id, str(business_name).strip(), lat, lng, flag_color, address)
        )


# ── Service functions ─────────────────────────────────────────────────────────
def upload_registry(file, ext: str):
    """Parse CSV/Excel → geocode → insert into OFFICIAL_REGISTRY.
    Returns (summary_dict, error_string)."""
    set_cancel("registry_import", False)
    try:
        raw = file.read()

        if ext == ".csv":
            df = pd.read_csv(io.BytesIO(raw), encoding="utf-8", dtype=str)
        else:
            df = pd.read_excel(io.BytesIO(raw), dtype=str)

        df = df.dropna(how="all")          # drop completely blank rows
        df = _normalise_columns(df)
        df = df.where(pd.notna(df), None)  # replace NaN with None

        total_rows = len(df)
        inserted = 0
        geocoded_ok = 0
        geocoded_failed = 0
        skipped = 0
        errors = []

        from api.notifications import hub
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

            # Resolve barangay
            barangay_raw = row.get("barangay") or ""
            print(f"Row {idx + 2} barangay: '{barangay_raw}'")
            barangay_id = _get_barangay_id(
                barangay_raw) if barangay_raw else None

            # If barangay not found, skip row — barangayID is NOT NULL
            if barangay_id is None:
                skipped += 1
                errors.append(
                    f"Row {idx + 2}: barangay '{barangay_raw}' not found — skipped")
                continue

            # Geocode
            address_raw = row.get("businessAddress") or ""
            lat, lng = None, None

            if address_raw:
                lat, lng = _geocode(address_raw, barangay_raw)
                if lat is not None:
                    geocoded_ok += 1
                else:
                    geocoded_failed += 1
            else:
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

            # Insert — skip duplicates (same name + barangayID)
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
                    WHERE LOWER(businessName) = LOWER(%s)
                    AND barangayID = %s
                )
                """,
                (
                    barangay_id,
                    str(business_name).strip(),
                    str(row.get("businessType") or "").strip() or None,
                    str(row.get("lineOfBusiness") or "").strip() or None,
                    str(address_raw).strip() or None,
                    lat,
                    lng,
                    status,
                    renewal_date,
                    str(row.get("businessSize") or "").strip(
                    ) or None,  # Added this line
                    # WHERE NOT EXISTS params
                    str(business_name).strip(),
                    barangay_id,
                ),
            )

            if cursor.rowcount > 0:
                inserted += 1
                flag_color = _status_to_flag_color(status)
                # Auto-seed Flag baseline into GEOSPATIAL_LOGS
                insert_green_flag(
                    barangay_id,
                    str(business_name).strip(),
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
    Existing rows match on LOWER(businessName) + barangayID and are overwritten
    with file values; new rows are inserted (same rules as upload).
    Returns (summary_dict, error_string)."""
    set_cancel("registry_import", False)
    try:
        raw = file.read()

        if ext == ".csv":
            df = pd.read_csv(io.BytesIO(raw), encoding="utf-8", dtype=str)
        else:
            df = pd.read_excel(io.BytesIO(raw), dtype=str)

        df = df.dropna(how="all")
        df = _normalise_columns(df)
        df = df.where(pd.notna(df), None)

        total_rows = len(df)
        inserted = 0
        updated = 0
        geocoded_ok = 0
        geocoded_failed = 0
        skipped = 0
        errors = []

        from api.notifications import hub
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
            barangay_id = _get_barangay_id(
                barangay_raw) if barangay_raw else None

            if barangay_id is None:
                skipped += 1
                errors.append(
                    f"Row {idx + 2}: barangay '{barangay_raw}' not found — skipped")
                continue

            address_raw = row.get("businessAddress") or ""
            lat, lng = None, None

            if address_raw:
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

            name_key = str(business_name).strip()
            btype = str(row.get("businessType") or "").strip() or None
            lob = str(row.get("lineOfBusiness") or "").strip() or None
            addr = str(address_raw).strip() or None
            bsize = str(row.get("businessSize") or "").strip() or None

            cursor.execute(
                """
                SELECT businessID, latitude, longitude FROM official_registry
                WHERE LOWER(TRIM(businessName)) = LOWER(TRIM(%s)) AND barangayID = %s
                LIMIT 1
                """,
                (name_key, barangay_id),
            )
            existing = cursor.fetchone()

            if existing:
                # Preserve existing coordinates if new geocoding returned None
                final_lat = lat if lat is not None else existing.get("latitude")
                final_lng = lng if lng is not None else existing.get("longitude")

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
        check_and_expire_old_permits()
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

        # Paginated rows
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
                (
                    SELECT CASE 
                        WHEN g.placeID IS NOT NULL THEN 'registry_and_maps' 
                        ELSE 'registry_only' 
                    END
                    FROM geospatial_logs g
                    WHERE LOWER(g.detectedName) = LOWER(r.businessName)
                    AND g.barangayID = r.barangayID
                    ORDER BY g.detectedDate DESC
                    LIMIT 1
                ) AS flagSource,
                (
                    SELECT g.flagColor
                    FROM geospatial_logs g
                    WHERE LOWER(g.detectedName) = LOWER(r.businessName)
                    AND g.barangayID = r.barangayID
                    ORDER BY g.detectedDate DESC
                    LIMIT 1
                ) AS flagColor
            FROM official_registry r
            LEFT JOIN barangays b ON r.barangayID = b.barangayID
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
        check_and_expire_old_permits()
        cursor = mysql.connection.cursor()

        # Main record + latest flagColor
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
                (
                    SELECT CASE 
                        WHEN g.placeID IS NOT NULL THEN 'registry_and_maps' 
                        ELSE 'registry_only' 
                    END
                    FROM geospatial_logs g
                    WHERE LOWER(g.detectedName) = LOWER(r.businessName)
                    AND g.barangayID = r.barangayID
                    ORDER BY g.detectedDate DESC
                    LIMIT 1
                ) AS flagSource,
                (
                    SELECT g.flagColor
                    FROM geospatial_logs g
                    WHERE LOWER(g.detectedName) = LOWER(r.businessName)
                      AND g.barangayID = r.barangayID
                    ORDER BY g.detectedDate DESC
                    LIMIT 1
                ) AS flagColor
            FROM official_registry r
            LEFT JOIN barangays b ON r.barangayID = b.barangayID
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
            cursor.execute(
                """
                UPDATE geospatial_logs g
                JOIN official_registry r ON LOWER(TRIM(g.detectedName)) = LOWER(TRIM(r.businessName)) AND g.barangayID = r.barangayID
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

