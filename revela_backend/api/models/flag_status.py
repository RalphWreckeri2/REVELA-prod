"""SQL rules shared by registry synchronization and effective map colors.

Permit standing is registry-owned. A still-applied, verified Black/Purple field
finding is inspection-owned; changing a permit does not revoke that finding.
Orange remains a warning overlay on expired/unregistered businesses, so a valid
permit renewal can legitimately make the map Green without changing a report.
"""


def latest_verified_result_sql(alias="g"):
    # Redispatch reuses/clears the report row. The verified lifecycle event is
    # durable across that operation. Reports support pre-event legacy data.
    return f"""COALESCE(
        (SELECT e.inspectionResult
         FROM inspection_lifecycle_events e
         WHERE e.targetLogID = {alias}.logID AND e.eventType = 'verified'
         ORDER BY e.eventID DESC LIMIT 1),
        (SELECT ir.inspectionResult
         FROM inspection_reports ir
         WHERE ir.targetType = 'geospatial_log' AND ir.targetID = {alias}.logID
           AND ir.verificationStatus = 'Verified'
         ORDER BY ir.reportID DESC LIMIT 1)
    )"""


def permit_color_sql(status_sql):
    return f"""CASE {status_sql}
        WHEN 'Active' THEN 'Green'
        WHEN 'Expired' THEN 'Red'
        WHEN 'Revoked' THEN 'Black'
        WHEN 'Blacklisted' THEN 'Black'
        WHEN 'Closed' THEN 'Purple'
        WHEN 'Pending' THEN 'Yellow'
    END"""


def matched_registry_status_sql(alias="g"):
    return f"""(SELECT r_chk.applicationStatus
        FROM official_registry r_chk
        WHERE ({alias}.businessID IS NOT NULL AND r_chk.businessID = {alias}.businessID)
           OR ({alias}.placeID IS NOT NULL AND r_chk.placeID = {alias}.placeID
               AND ({alias}.businessID IS NULL OR r_chk.businessID = {alias}.businessID))
           OR ({alias}.businessID IS NULL AND r_chk.barangayID = {alias}.barangayID
               AND r_chk.businessName = {alias}.detectedName)
        ORDER BY (r_chk.businessID = {alias}.businessID) DESC,
                 (r_chk.placeID = {alias}.placeID) DESC
        LIMIT 1)"""


def effective_flag_color_sql(registry_color_sql, alias="g", *, known_color=None):
    """Resolve a map color without modifying any inspection lifecycle state.

    known_color lets UPDATE callers bind a baseline color exactly once. The
    subqueries are evaluated inside the UPDATE, using InnoDB's current read,
    rather than a potentially stale import snapshot.
    """
    verified = latest_verified_result_sql(alias)
    if known_color is None:
        orange_eligible = f"({registry_color_sql} IS NULL OR {registry_color_sql} = 'Red')"
    else:
        orange_eligible = "TRUE" if known_color == "Red" else "FALSE"
    return f"""CASE
        WHEN {alias}.flagColor IN ('Black', 'Purple')
         AND {alias}.flagColor = {verified} THEN {alias}.flagColor
        WHEN {orange_eligible} AND {verified} = 'Orange' THEN 'Orange'
        ELSE COALESCE({registry_color_sql}, {alias}.flagColor)
    END"""
