"""Operational report reader. No registry census dependency and no writes."""
from datetime import datetime, timezone

from app import mysql
from api.flags.compliance import (
    current_confirmation_rows, confirmation_summary, utc_iso, is_report_compliant,
    decorate_compliance, origin_source_sql, registry_link_sql, verified_green_at_sql,
)
from api.registry.colors import _effective_flag_color_sql, ladder_columns_available


def get_inspection_verified_compliant():
    cursor = mysql.connection.cursor()
    try:
        ladder = ladder_columns_available(cursor)
        all_rows = current_confirmation_rows(cursor, ladder=ladder)
        records = [{
                "detectionReference": row["logID"],
                "businessName": row["detectedName"],
                "barangayID": row["barangayID"],
                "barangayName": row["barangayName"],
                "address": row["address"],
                "verifiedOn": row["confirmedAt"],
                "registryLinked": True,
            } for row in all_rows if row["confirmationSource"] == "inspection"]
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
                "verifiedOn": row["verifiedGreenAt"], "registryLinked": False})
        records.sort(key=lambda row: (str(row["businessName"] or ""), row["detectionReference"]))
        return {"data": records, "total": len(records),
                "confirmationSummary": confirmation_summary(all_rows),
                "unlinkedVerifiedPinCount": sum(not row["registryLinked"] for row in records),
                "generatedAt": utc_iso(datetime.now(timezone.utc))}
    finally:
        cursor.close()
