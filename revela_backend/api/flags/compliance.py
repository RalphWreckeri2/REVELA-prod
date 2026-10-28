"""Read-only current-compliance evidence shared by Map and operational reports.

Colour is always supplied by api.registry.colors. This module does not change
permit standing, warnings, inspection state, or the official registry.
"""
from datetime import datetime, timezone

from api.models.geospatial import geospatial_source_column_exists


def origin_source_sql(alias, cursor):
    """Only persisted provenance is evidence of origin; never guess legacy data."""
    if not geospatial_source_column_exists(cursor):
        return "'unknown'"
    return f"COALESCE({alias}.source, 'unknown')"


def registry_link_sql(alias="g"):
    """An actual, live foreign-key relationship, independent of colour matching."""
    return f"""EXISTS (
        SELECT 1 FROM official_registry linked_registry
        WHERE {alias}.businessID IS NOT NULL
          AND linked_registry.businessID = {alias}.businessID
    )"""


def verified_green_at_sql(alias="g", *, ladder=False):
    """Actual UTC admin-verification instant supporting the *current* pin.

    A lifecycle event is required: report dispatch/submission/update dates cannot
    stand in for verification. Reused reports, subsequent results/assignments,
    and later warning/Black enforcement invalidate old evidence. Requiring the
    still-applied Green pin also avoids treating a registry colour fallback as
    proof that a superseded field finding remains applied.

    actorUserID is recorded by the existing admin-only verify route. We do not
    reinterpret that historical action using the actor's present-day role.
    """
    enforcement = ""
    if ladder:
        enforcement = f"""AND NOT EXISTS (
            SELECT 1 FROM enforcement_events later_enforcement
            WHERE later_enforcement.eventType IN ('warning_issued', 'black_locked')
              AND later_enforcement.createdAt > verified.eventTimestamp
              AND (
                (later_enforcement.subjectType = 'geospatial_log'
                 AND later_enforcement.subjectID = CAST({alias}.logID AS CHAR))
                OR (later_enforcement.subjectType = 'business'
                    AND later_enforcement.subjectID = CAST({alias}.businessID AS CHAR))
              )
        )"""
    return f"""(
        SELECT verified.eventTimestamp
        FROM inspection_lifecycle_events verified
        JOIN inspection_reports evidence ON evidence.reportID = verified.reportID
        WHERE verified.targetLogID = {alias}.logID
          AND verified.eventType = 'verified'
          AND verified.inspectionResult = 'Green'
          AND verified.actorUserID IS NOT NULL
          AND evidence.targetType = 'geospatial_log'
          AND evidence.targetID = {alias}.logID
          AND evidence.verificationStatus = 'Verified'
          AND evidence.inspectionResult = 'Green'
          AND {alias}.flagColor = 'Green'
          AND verified.eventID = (
              SELECT MAX(latest_event.eventID)
              FROM inspection_lifecycle_events latest_event
              WHERE latest_event.targetLogID = {alias}.logID
          )
          {enforcement}
        ORDER BY verified.eventID DESC
        LIMIT 1
    )"""


def utc_iso(value):
    if value is None:
        return None
    if not isinstance(value, datetime):
        try:
            value = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return None
    if value.tzinfo is None:
        # log_inspection_event explicitly uses UTC_TIMESTAMP(6).
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def decorate_compliance(row):
    """One eligibility definition for the Map projection and report reader."""
    row["verifiedGreenAt"] = utc_iso(row.get("verifiedGreenAt"))
    row["registryLinked"] = row.get("registryLinked") in (True, 1, "1")
    row["originSource"] = row.get("originSource") or "unknown"
    row["inspectionVerifiedCompliant"] = (
        row.get("flagColor") == "Green" and row["verifiedGreenAt"] is not None
    )
    return row


def is_report_compliant(row):
    origin = row.get("originSource")
    eligible_origin = origin in ("detection", "manual")
    return eligible_origin and row.get("inspectionVerifiedCompliant") is True


def current_confirmation_rows(cursor, *, ladder=False, barangay_ids=None):
    """One row per confirmed registry business, never one row per report/event.

    Office history has no structured pin FK. Only the server-written audit
    suffix identifying this *current* canonical pin is sufficient evidence;
    older free-text events cannot safely be assigned to a different pin.
    """
    from api.registry.colors import _effective_flag_color_sql

    origin_source = origin_source_sql("g", cursor)
    office_at = """(SELECT e.createdAt FROM enforcement_events e
        WHERE e.subjectType = 'business' AND e.subjectID = CAST(r.businessID AS CHAR)
          AND e.eventType = 'compliance_confirmed'
          AND e.reason LIKE CONCAT('% for original pin #', g.logID)
          AND NOT EXISTS (SELECT 1 FROM enforcement_events later
              WHERE later.eventType IN ('warning_issued', 'black_locked')
                AND later.createdAt > e.createdAt
                AND ((later.subjectType = 'business' AND later.subjectID = CAST(r.businessID AS CHAR))
                  OR (later.subjectType = 'geospatial_log' AND later.subjectID = CAST(g.logID AS CHAR))))
        ORDER BY e.createdAt DESC, e.eventID DESC LIMIT 1)"""
    cursor.execute(f"""SELECT r.businessID, g.logID, g.detectedName, g.barangayID,
                    b.barangayName, COALESCE(NULLIF(g.nearestLandmark, ''), r.businessAddress, '') AS address,
                    {origin_source} AS originSource,
                    {_effective_flag_color_sql('g', ladder=ladder)} AS flagColor,
                    {office_at} AS officeAt,
                    {verified_green_at_sql('g', ladder=ladder)} AS inspectionAt
             FROM official_registry r
             JOIN geospatial_logs g ON g.logID = r.confirmedLogID AND g.businessID = r.businessID
             LEFT JOIN barangays b ON b.barangayID = g.barangayID""")
    rows = []
    for row in cursor.fetchall():
        if row["flagColor"] != "Green" or (barangay_ids and row["barangayID"] not in barangay_ids):
            continue
        office, inspection = utc_iso(row.get("officeAt")), utc_iso(row.get("inspectionAt"))
        if office and inspection:
            # An exact timestamp tie cannot order separate tables; choose the
            # verified event deterministically, never count the business twice.
            source = "inspection" if inspection >= office else "office"
        else:
            source = "inspection" if inspection else "office" if office else None
        if not source:
            continue
        rows.append({**row, "confirmationSource": source,
                     "confirmedAt": inspection if source == "inspection" else office})
    return rows


def confirmation_summary(rows):
    office = sum(row["confirmationSource"] == "office" for row in rows)
    inspection = sum(row["confirmationSource"] == "inspection" for row in rows)
    return {"office_confirmed": office, "inspection_verified": inspection,
            "total_confirmed": len(rows), "count_unit": "distinct confirmed registry businesses"}
