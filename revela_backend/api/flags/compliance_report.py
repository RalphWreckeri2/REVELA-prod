"""Operational report reader. No registry census dependency and no writes."""
from datetime import datetime, timezone

from app import mysql
from api.flags.compliance import (
    current_confirmation_rows, confirmation_summary, utc_iso, is_report_compliant,
    decorate_compliance, origin_source_sql, registry_link_sql, verified_green_at_sql,
)
from api.registry.colors import _effective_flag_color_sql, ladder_columns_available


def _warning_cleared_inspection_rows(cursor, *, ladder):
    """Verified Orange inspections later cleared for a currently Green registry business."""
    if not ladder:
        return []

    cursor.execute(
        "SELECT COLUMN_NAME FROM information_schema.COLUMNS "
        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'enforcement_state' "
        "AND COLUMN_NAME = %s",
        ("warningClearedAt",),
    )
    columns = cursor.fetchall()
    if not columns:
        return []

    source = origin_source_sql("g", cursor)
    effective_color = _effective_flag_color_sql("g", ladder=ladder)
    cursor.execute(f"""SELECT r.businessID, r.businessName AS registryBusinessName,
                          g.logID, g.detectedName, g.barangayID, b.barangayName,
                          COALESCE(NULLIF(g.nearestLandmark, ''), r.businessAddress, '') AS address,
                          {source} AS originSource, cleared.createdAt AS clearedAt
                   FROM official_registry r
                   JOIN geospatial_logs g ON g.businessID = r.businessID
                   JOIN enforcement_state state
                     ON state.subjectType = 'business'
                    AND state.subjectID = CAST(r.businessID AS CHAR)
                   JOIN enforcement_events cleared
                     ON cleared.eventType = 'warning_cleared'
                    AND cleared.actorUserID IS NOT NULL
                    AND (
                        (cleared.subjectType = 'business'
                         AND cleared.subjectID = CAST(r.businessID AS CHAR))
                        OR (cleared.subjectType = 'geospatial_log'
                            AND cleared.subjectID = CAST(g.logID AS CHAR))
                    )
                   JOIN inspection_lifecycle_events verified
                     ON verified.targetLogID = g.logID
                    AND verified.eventType = 'verified'
                    AND verified.inspectionResult = 'Orange'
                    AND verified.actorUserID IS NOT NULL
                   JOIN inspection_reports evidence
                     ON evidence.reportID = verified.reportID
                    AND evidence.targetType = 'geospatial_log'
                    AND evidence.targetID = g.logID
                    AND evidence.verificationStatus = 'Verified'
                    AND evidence.inspectionResult = 'Orange'
                   LEFT JOIN barangays b ON b.barangayID = g.barangayID
                   WHERE COALESCE(state.warningLevel, 0) = 0
                     AND COALESCE(state.blackLocked, 0) = 0
                     AND state.warningClearedAt IS NOT NULL
                     AND {effective_color} = 'Green'
                     AND cleared.createdAt >= verified.eventTimestamp
                     AND cleared.eventID = (
                         SELECT MAX(latest_clear.eventID)
                         FROM enforcement_events latest_clear
                         WHERE latest_clear.eventType = 'warning_cleared'
                           AND latest_clear.actorUserID IS NOT NULL
                           AND (
                               (latest_clear.subjectType = 'business'
                                AND latest_clear.subjectID = CAST(r.businessID AS CHAR))
                               OR (latest_clear.subjectType = 'geospatial_log'
                                   AND latest_clear.subjectID = CAST(g.logID AS CHAR))
                           )
                     )
                     AND NOT EXISTS (
                         SELECT 1
                         FROM enforcement_events later_enforcement
                         WHERE later_enforcement.eventType IN ('warning_issued', 'black_locked')
                           AND later_enforcement.createdAt > cleared.createdAt
                           AND (
                               (later_enforcement.subjectType = 'business'
                                AND later_enforcement.subjectID = CAST(r.businessID AS CHAR))
                               OR (later_enforcement.subjectType = 'geospatial_log'
                                   AND later_enforcement.subjectID = CAST(g.logID AS CHAR))
                           )
                     )
                     AND verified.eventID = (
                         SELECT MAX(latest_event.eventID)
                         FROM inspection_lifecycle_events latest_event
                         WHERE latest_event.targetLogID = g.logID
                     )
                   ORDER BY cleared.createdAt DESC, verified.eventID DESC""")
    return cursor.fetchall()


def get_inspection_verified_compliant():
    cursor = mysql.connection.cursor()
    try:
        ladder = ladder_columns_available(cursor)
        all_rows = current_confirmation_rows(cursor, ladder=ladder)
        records = [{
                "detectionReference": row["logID"],
                "businessName": row.get("registryBusinessName") or row["detectedName"],
                "detectedName": row["detectedName"],
                "barangayID": row["barangayID"],
                "barangayName": row["barangayName"],
                "address": row["address"],
                "originSource": row["originSource"],
                "verifiedOn": row["confirmedAt"],
                "registryLinked": True,
                "businessID": row["businessID"],
                "complianceBasis": "Inspection-verified Green",
            } for row in all_rows if row["confirmationSource"] == "inspection"]
        admin_confirmed_records = [{
                "detectionReference": row["logID"],
                "businessID": row["businessID"],
                "businessName": row.get("registryBusinessName") or row["detectedName"],
                "detectedName": row["detectedName"],
                "barangayID": row["barangayID"],
                "barangayName": row["barangayName"],
                "address": row["address"],
                "originSource": row["originSource"],
                "verificationMethod": "DIRECT_ADMIN_CONFIRMATION",
                "confirmedBy": row["officeConfirmedBy"],
                "confirmedByUserID": row["officeConfirmedByID"],
                "verifiedOn": row["confirmedAt"],
                "registryLinked": True,
            } for row in all_rows if row["confirmationSource"] == "office"]
        # Keep the pre-existing legacy unlinked-pin operational list/filter.
        # These are pin references, not provably distinct registered businesses;
        # never add them to the canonical confirmed-business breakdown above.
        source = origin_source_sql("g", cursor)
        cursor.execute(f"""SELECT g.logID, g.detectedName, g.barangayID, b.barangayName,
                          COALESCE(g.nearestLandmark, '') AS address,
                          {source} AS originSource,
                          {_effective_flag_color_sql('g', ladder=ladder)} AS flagColor,
                          {registry_link_sql('g')} AS registryLinked,
                          {verified_green_at_sql('g', ladder=ladder)} AS verifiedGreenAt
                   FROM geospatial_logs g
                   LEFT JOIN barangays b ON b.barangayID = g.barangayID
                   WHERE NOT ({registry_link_sql('g')}) AND {source} IN ('detection', 'manual')""")
        for row in cursor.fetchall():
            decorate_compliance(row)
            if not is_report_compliant(row):
                continue
            records.append({"detectionReference": row["logID"],
                "businessName": row["detectedName"], "barangayID": row["barangayID"],
                "barangayName": row["barangayName"], "address": row["address"],
                "originSource": row["originSource"],
                "verifiedOn": row["verifiedGreenAt"], "registryLinked": False})

        warning_cleared_records = []
        if ladder:
            existing_business_ids = {
                str(record["businessID"]) for record in records
                if record.get("businessID") is not None
            }
            for row in _warning_cleared_inspection_rows(cursor, ladder=ladder):
                business_id = str(row["businessID"])
                if business_id in existing_business_ids:
                    continue
                existing_business_ids.add(business_id)
                warning_cleared_records.append({
                    "detectionReference": row["logID"],
                    "businessID": row["businessID"],
                    "businessName": row.get("registryBusinessName") or row["detectedName"],
                    "detectedName": row["detectedName"],
                    "barangayID": row["barangayID"],
                    "barangayName": row["barangayName"],
                    "address": row["address"],
                    "originSource": row["originSource"],
                    "verifiedOn": utc_iso(row["clearedAt"]),
                    "registryLinked": True,
                    "complianceBasis": "Verified warning cleared by admin",
                })
            records.extend(warning_cleared_records)

        for record in records:
            record.setdefault("complianceBasis", "Inspection-verified Green")
        records.sort(key=lambda row: (str(row["businessName"] or ""), row["detectionReference"]))
        admin_confirmed_records.sort(
            key=lambda row: (str(row["businessName"] or ""), row["detectionReference"]))
        return {"data": records, "total": len(records),
                "adminConfirmedData": admin_confirmed_records,
                "adminConfirmedTotal": len(admin_confirmed_records),
                "warningClearedTotal": len(warning_cleared_records),
                "confirmationSummary": confirmation_summary(all_rows),
                "unlinkedVerifiedPinCount": sum(not row["registryLinked"] for row in records),
                "generatedAt": utc_iso(datetime.now(timezone.utc))}
    finally:
        cursor.close()
