"""Explicit, admin-reviewed registry identity links. Never commits its caller's work."""
import hashlib
import json
import re


class GreenRegistryLinkError(ValueError):
    def __init__(self, message, *, conflict=False):
        super().__init__(message)
        self.conflict = conflict


def normalize_business_id(value):
    """Use the same identity in confirmation and CSV/Excel imports."""
    if not isinstance(value, str):
        raise GreenRegistryLinkError("An official Business ID is required.")
    value = value.strip().lstrip("#").strip().upper()
    if (not re.fullmatch(r"[A-Z0-9][A-Z0-9 ./_-]{0,49}", value)
            or value in {"NAN", "NULL", "NONE", "N/A", "NA", "UNKNOWN"}):
        raise GreenRegistryLinkError(
            "Enter a valid Business ID (1–50 characters: letters, numbers, spaces, . / _ -).")
    return value


def confirmed_pin_column_available(cursor):
    cursor.execute("SHOW COLUMNS FROM official_registry LIKE 'confirmedLogID'")
    return any((row.get("Field", row.get("name")) if isinstance(row, dict) else row[0]) == "confirmedLogID"
                for row in cursor.fetchall())


def release_confirmed_pin(cursor, log_id, *, expected_business_id=None):
    """Clear a confirmed reference before intentionally deleting its pin.

    Caller locks the pin first, owns the transaction and must roll back on any
    failure. The registry-row lock serializes concurrent confirmation/imports.
    Never delete the registry row as a side effect of deleting a map pin.
    """
    if not confirmed_pin_column_available(cursor):
        return False
    cursor.execute("SELECT businessID FROM official_registry WHERE confirmedLogID = %s FOR UPDATE",
                   (log_id,))
    row = cursor.fetchone()
    if not row:
        return False
    if expected_business_id is not None and row["businessID"] != expected_business_id:
        raise GreenRegistryLinkError(
            "This pin is confirmed for another registry business. Refresh and review the link.",
            conflict=True)
    cursor.execute("""UPDATE official_registry SET confirmedLogID = NULL
                      WHERE businessID = %s AND confirmedLogID = %s""",
                   (row["businessID"], log_id))
    if cursor.rowcount != 1:
        raise GreenRegistryLinkError(
            "The confirmed pin link changed during deletion. Refresh and retry.", conflict=True)
    return True


def _name(value):
    return re.sub(r"\s+", " ", str(value or "")).strip().casefold()


def _conflict(message):
    raise GreenRegistryLinkError(message, conflict=True)


def prepare_green_link(cursor, report, business_id, *, lock=False, required_fields=None):
    """Read/validate identity and conflicts; the preview and final save share this gate.

    A name is never used to find a registry record. Exact Business ID identifies
    it; name + barangay (or an agreeing Place ID + barangay) and the admin's
    final confirmation establish that it is this establishment.
    """
    business_id = normalize_business_id(business_id)
    if report.get("targetType", "geospatial_log") != "geospatial_log":
        _conflict("Green registry linking requires the original map pin.")
    if not confirmed_pin_column_available(cursor):
        _conflict("Apply the confirmed registry pin migration before confirming Green.")
    suffix = " FOR UPDATE" if lock else ""
    cursor.execute("SELECT * FROM geospatial_logs WHERE logID = %s" + suffix,
                   (report["targetID"],))
    pin = cursor.fetchone()
    if not pin:
        _conflict("The original map pin no longer exists.")
    if pin.get("businessID") and normalize_business_id(pin["businessID"]) != business_id:
        _conflict(f"This pin is already linked to Business ID {pin['businessID']}.")
    try:
        lat, lng = float(pin["latitude"]), float(pin["longitude"])
        valid_coords = -90 <= lat <= 90 and -180 <= lng <= 180
    except (TypeError, ValueError, KeyError):
        valid_coords = False
    if not valid_coords:
        _conflict("The original pin needs valid coordinates before it can be linked.")

    cursor.execute("SELECT * FROM official_registry WHERE businessID = %s" + suffix,
                   (business_id,))
    registry = cursor.fetchone()
    # Retain the database's canonical PK spelling (legacy IDs can be mixed case).
    if registry:
        business_id = registry["businessID"]
        if registry.get("confirmedLogID") not in (None, pin["logID"]):
            _conflict("This Business ID is already confirmed against a different pin.")
        if registry.get("barangayID") != pin.get("barangayID"):
            _conflict("The registry barangay does not match this establishment. Resolve the identity mismatch first.")
        same_place = bool(pin.get("placeID") and pin["placeID"] == registry.get("placeID"))
        if (pin.get("placeID") and registry.get("placeID") and not same_place):
            _conflict("The registry and original pin have conflicting Place IDs.")
        if not same_place and _name(registry.get("businessName")) != _name(pin.get("detectedName")):
            _conflict("The registry business name does not match this establishment. Resolve the identity mismatch first.")
    cursor.execute("""SELECT businessID FROM official_registry
                      WHERE confirmedLogID = %s AND businessID <> %s""" + suffix,
                   (pin["logID"], business_id))
    if cursor.fetchone():
        _conflict("This pin is already confirmed against a different Business ID.")
    cursor.execute("""SELECT g.logID, g.source, g.reportedByUserID,
                             EXISTS (SELECT 1 FROM inspection_reports ir
                                     WHERE ir.targetID = g.logID
                                       AND ir.targetType = 'geospatial_log') AS hasInspection
                      FROM geospatial_logs g
                      WHERE g.businessID = %s AND g.logID <> %s""" + suffix,
                   (business_id, pin["logID"]))
    for other in cursor.fetchall():
        # Old registry-generated markers may remain as historical rows. Only
        # the confirmed pin is displayed. Never adopt another field pin/history.
        if (other.get("hasInspection") or other.get("reportedByUserID")
                or other.get("source") in ("manual", "detection", "registry_detected")):
            _conflict("This Business ID has another field pin or inspection history. Resolve the conflicting link first.")

    details = {} if required_fields is None else required_fields
    if not isinstance(details, dict) or set(details) - {"businessName", "barangayID"}:
        raise GreenRegistryLinkError("Only missing businessName and barangayID fields may be supplied.")
    new_fields = {"businessName": pin.get("detectedName"), "barangayID": pin.get("barangayID")}
    missing = [key for key, value in new_fields.items() if not value or (key == "businessName" and not _name(value))]
    if registry and details:
        # An identical retry of a newly created link is safe; changing the
        # submitted identity fields after creation requires a fresh review.
        if (registry.get("confirmedLogID") != pin["logID"]
                or any(registry.get(key) != value for key, value in details.items())):
            _conflict("The official registry record changed. Review the Business ID again.")
    if not registry:
        for key, value in details.items():
            if key not in missing:
                raise GreenRegistryLinkError(f"{key} is already available from the original pin.")
            new_fields[key] = value
        name = new_fields.get("businessName")
        if name and (not isinstance(name, str) or not name.strip() or len(name.strip()) > 255):
            raise GreenRegistryLinkError("businessName must be between 1 and 255 characters.")
        if isinstance(name, str):
            new_fields["businessName"] = name.strip()
        barangay = new_fields.get("barangayID")
        if barangay is not None:
            if isinstance(barangay, bool) or not str(barangay).isdigit():
                raise GreenRegistryLinkError("Select a valid barangay.")
            cursor.execute("SELECT barangayID FROM barangays WHERE barangayID = %s", (barangay,))
            row = cursor.fetchone()
            if not row:
                raise GreenRegistryLinkError("Select a valid barangay.")
            new_fields["barangayID"] = row["barangayID"]
    identity = ({key: registry.get(key) for key in (
        "businessID", "businessName", "businessAddress", "barangayID", "placeID")}
        if registry else None)
    token_data = [normalize_business_id(business_id), identity,
                  {key: pin.get(key) for key in ("logID", "detectedName", "barangayID", "latitude", "longitude", "placeID")}]
    token = hashlib.sha256(json.dumps(token_data, sort_keys=True, default=str).encode()).hexdigest()
    return {"businessID": business_id, "pin": pin, "registry": registry,
            "newFields": new_fields, "missingRequiredFields": [] if registry else missing,
            "reviewToken": token}


def save_green_link(cursor, plan):
    """All identity/enforcement checks must pass before this is called."""
    pin, registry, business_id = plan["pin"], plan["registry"], plan["businessID"]
    if not registry:
        fields = plan["newFields"]
        if not fields.get("businessName") or not fields.get("barangayID"):
            raise GreenRegistryLinkError("Supply the missing required registry fields before confirming.")
        cursor.execute("""INSERT INTO official_registry
                          (businessID, businessName, barangayID, latitude, longitude, applicationStatus)
                          VALUES (%s, %s, %s, %s, %s, 'Pending')""",
                       (business_id, fields["businessName"], fields["barangayID"], pin["latitude"], pin["longitude"]))
    cursor.execute("""UPDATE geospatial_logs SET businessID = %s,
                      detectedName = COALESCE(NULLIF(TRIM(detectedName), ''), %s),
                      barangayID = COALESCE(barangayID, %s) WHERE logID = %s""",
                   (business_id, plan["newFields"].get("businessName"),
                    plan["newFields"].get("barangayID"), pin["logID"]))
    # 'approved' describes the admin-confirmed location; keep the pin's actual
    # source on geospatial_logs. Do not label copied coordinates as a new geocode.
    cursor.execute("""UPDATE official_registry
                      SET confirmedLogID = %s, latitude = %s, longitude = %s,
                          coordSource = NULL, coordFetchedAt = NULL,
                          matchStatus = 'approved', matchScore = NULL, resolveKey = NULL
                      WHERE businessID = %s""",
                   (pin["logID"], pin["latitude"], pin["longitude"], business_id))
