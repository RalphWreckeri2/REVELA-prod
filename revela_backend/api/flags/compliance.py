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
    eligible_origin = (
        origin == "detection"
        or (origin == "manual" and row.get("registryLinked") is False)
    )
    return eligible_origin and row.get("inspectionVerifiedCompliant") is True
