"""Operational report reader. No registry census dependency and no writes."""
from datetime import datetime, timezone

from app import mysql
from api.flags.compliance import (
    decorate_compliance, is_report_compliant, origin_source_sql,
    registry_link_sql, utc_iso, verified_green_at_sql,
)
from api.registry.colors import _effective_flag_color_sql, ladder_columns_available


def get_inspection_verified_compliant():
    cursor = mysql.connection.cursor()
    try:
        ladder = ladder_columns_available(cursor)
        source = origin_source_sql("g", cursor)
        cursor.execute(f"""
            SELECT g.logID, g.detectedName, g.barangayID, b.barangayName,
                   COALESCE(NULLIF(g.nearestLandmark, ''), r.businessAddress, '') AS address,
                   {source} AS originSource,
                   {_effective_flag_color_sql('g', ladder=ladder)} AS flagColor,
                   {registry_link_sql('g')} AS registryLinked,
                   {verified_green_at_sql('g', ladder=ladder)} AS verifiedGreenAt
            FROM geospatial_logs g
            LEFT JOIN barangays b ON b.barangayID = g.barangayID
            LEFT JOIN official_registry r ON r.businessID = g.businessID
            WHERE {source} IN ('detection', 'manual')
            ORDER BY g.detectedName, g.logID
        """)
        records = []
        for row in cursor.fetchall():
            decorate_compliance(row)
            if not is_report_compliant(row):
                continue
            records.append({
                "detectionReference": row["logID"],
                "businessName": row["detectedName"],
                "barangayID": row["barangayID"],
                "barangayName": row["barangayName"],
                "address": row["address"],
                "verifiedOn": row["verifiedGreenAt"],
                "registryLinked": row["registryLinked"],
            })
        return {"data": records, "total": len(records),
                "generatedAt": utc_iso(datetime.now(timezone.utc))}
    finally:
        cursor.close()
