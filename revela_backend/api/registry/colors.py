"""Shared SQL builders for the derived (registry-authoritative) flag colour.

These two functions used to live in api/analytics/routes.py. They were moved
here verbatim so that api/registry/service.py can reuse the exact expression
the Map already uses, without importing the analytics blueprint (which pulls in
google-genai and scikit-learn at import time).

Nothing in this module may gain imports. It must stay dependency-free so both
readers can import it cheaply and without side effects.

Both builders return a SQL expression STRING. They take the alias of the
geospatial_logs relation to read from and emit no bind parameters.

Precedence implemented by _effective_flag_color_sql:
    verified-Orange inspection > Revoked/Blacklisted > Closed > Pending > stored pin colour
The stored geospatial_logs.flagColor is used only when the pin has no
registry match, which is the only case where the registry cannot speak.
"""


def _verified_orange_sql(alias="g"):
    registry_match = f"""(
        (r_chk.businessID IS NOT NULL AND {alias}.businessID IS NOT NULL
            AND r_chk.businessID = {alias}.businessID)
        OR ({alias}.placeID IS NOT NULL AND r_chk.placeID = {alias}.placeID
            AND ({alias}.businessID IS NULL OR r_chk.businessID = {alias}.businessID))
        OR ({alias}.businessID IS NULL
            AND r_chk.barangayID = {alias}.barangayID
            AND r_chk.businessName = {alias}.detectedName)
    )"""
    return f"""(
        EXISTS (
            SELECT 1 FROM inspection_reports ir
            WHERE ir.targetType = 'geospatial_log'
              AND ir.targetID = {alias}.logID
              AND ir.verificationStatus = 'Verified'
              AND ir.inspectionResult = 'Orange'
        )
        AND (
            NOT EXISTS (
                SELECT 1 FROM official_registry r_chk
                WHERE {registry_match}
            )
            OR EXISTS (
                SELECT 1 FROM official_registry r_chk
                WHERE {registry_match}
                  AND r_chk.applicationStatus = 'Expired'
            )
        )
    )"""


def _effective_flag_color_sql(alias="g"):
    registry_status = f"""(
        SELECT r_chk.applicationStatus
        FROM official_registry r_chk
        WHERE (
            (r_chk.businessID IS NOT NULL AND {alias}.businessID IS NOT NULL
                AND r_chk.businessID = {alias}.businessID)
            OR ({alias}.placeID IS NOT NULL AND r_chk.placeID = {alias}.placeID
                AND ({alias}.businessID IS NULL OR r_chk.businessID = {alias}.businessID))
            OR ({alias}.businessID IS NULL
                AND r_chk.barangayID = {alias}.barangayID
                AND r_chk.businessName = {alias}.detectedName)
        )
        ORDER BY (r_chk.businessID = {alias}.businessID) DESC,
                 (r_chk.placeID = {alias}.placeID) DESC
        LIMIT 1
    )"""
    return f"""CASE
        WHEN { _verified_orange_sql(alias) } THEN 'Orange'
        WHEN {registry_status} = 'Active' THEN 'Green'
        WHEN {registry_status} = 'Expired' THEN 'Red'
        WHEN {registry_status} IN ('Revoked', 'Blacklisted') THEN 'Black'
        WHEN {registry_status} = 'Closed' THEN 'Purple'
        WHEN {registry_status} = 'Pending' THEN 'Yellow'
        ELSE {alias}.flagColor
    END"""