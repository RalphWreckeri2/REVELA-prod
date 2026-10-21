"""Read-only monitoring of the Map's actual Not-in-Registry pin population.

This is a descriptive snapshot, not a new compliance rule or WLC input. Cards,
barangay counts and the complete drill-down/export list share this one cohort.
"""
from datetime import datetime, timezone

from api.analytics.filters import geo_sql, inspection_sql
from api.flags.compliance import (
    decorate_compliance, is_report_compliant, registry_link_sql,
    utc_iso, verified_green_at_sql,
)
from api.registry.colors import _effective_flag_color_sql


PIN_COLORS = ("Green", "Red", "Yellow", "Orange", "Black", "Purple", "Unknown")
REGISTRY_ONLY_FILTERS = (
    "application_status", "line_of_business", "business_type", "business_size",
    "registration_type", "renewal_from", "renewal_to",
)


def non_registry_monitoring_sql(filters, *, ladder, source_sql):
    """One row per logID, with the latest inspection (no report join fan-out).

    Membership and verified Green evidence are exactly the shared Map/report
    definitions. Registry-only filters have no population here and are ignored.
    Geospatial filters and filters on the latest inspection remain applicable.
    No LIMIT: pagination is a presentation concern, never an export truncation.
    """
    geo, geo_params = geo_sql("g", filters, ladder=ladder)
    inspection, inspection_params = inspection_sql("ir", filters)
    return f"""
        SELECT g.logID, g.detectedName, g.barangayID,
               COALESCE(b.barangayName, 'Unknown barangay') AS barangayName,
               COALESCE(g.nearestLandmark, '') AS address,
               g.detectedDate,
               {_effective_flag_color_sql('g', ladder=ladder)} AS flagColor,
               {source_sql} AS originSource,
               {registry_link_sql('g')} AS registryLinked,
               {verified_green_at_sql('g', ladder=ladder)} AS verifiedGreenAt,
               ir.verificationStatus
        FROM geospatial_logs g
        LEFT JOIN barangays b ON b.barangayID = g.barangayID
        LEFT JOIN inspection_reports ir ON ir.reportID = (
            SELECT latest.reportID FROM inspection_reports latest
            WHERE latest.targetType = 'geospatial_log' AND latest.targetID = g.logID
            ORDER BY latest.irTimestamp DESC, latest.reportID DESC LIMIT 1
        )
        WHERE NOT ({registry_link_sql('g')}) {geo} {inspection}
        ORDER BY g.detectedDate DESC, g.logID DESC
    """, geo_params + inspection_params


def build_non_registry_monitoring(rows, filters=None, *, generated_at=None):
    summary = {"total": 0, "needs_verification": 0, "under_inspection": 0, "verified_green": 0}
    barangays = {}
    records = []
    for raw in rows:
        row = decorate_compliance(dict(raw))
        if row["registryLinked"]:
            continue
        color = row.get("flagColor") if row.get("flagColor") in PIN_COLORS else "Unknown"
        # Same current-workflow predicate used by the Map's inspection filter.
        status = row.get("verificationStatus")
        under_inspection = status is not None and status != "Verified"
        # Reuse the operational export's source + current verification rules.
        verified_green = is_report_compliant(row)
        records.append({
            "logID": int(row["logID"]),
            "detectedName": row.get("detectedName") or "Unnamed pin",
            "barangayID": row.get("barangayID"),
            "barangayName": row.get("barangayName") or "Unknown barangay",
            "address": row.get("address") or "",
            "flagColor": color, "originSource": row["originSource"],
            "registryLinked": False, "verificationStatus": status,
            "hasActiveInspection": under_inspection,
            "verifiedGreen": verified_green,
            "verifiedGreenAt": row["verifiedGreenAt"] if verified_green else None,
            # Detection timestamps retain the existing API's representation;
            # only lifecycle verification and snapshot dates are known UTC.
            "detectedDate": str(row["detectedDate"]) if row.get("detectedDate") is not None else None,
        })
        summary["total"] += 1
        summary["needs_verification"] += color in ("Red", "Yellow")
        summary["under_inspection"] += under_inspection
        summary["verified_green"] += verified_green
        key = row.get("barangayID")
        if key not in barangays:
            barangays[key] = {
                "barangayID": key,
                "barangayName": row.get("barangayName") or "Unknown barangay",
                **{name: 0 for name in PIN_COLORS},
            }
        barangays[key][color] += 1
    return {
        "summary": summary,
        "by_barangay": sorted(barangays.values(), key=lambda row: (row["barangayName"].casefold(), str(row["barangayID"]))),
        "records": records,
        "generated_at": utc_iso(generated_at or datetime.now(timezone.utc)),
        "ignored_filters": [key for key in REGISTRY_ONLY_FILTERS if (filters or {}).get(key)],
        "count_unit": "pins (distinct geospatial logID)",
    }
