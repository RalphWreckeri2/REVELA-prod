-- Candidate split WLC/OPS ranking query; no filters; ladder=True.
-- Source: _barangay_rankings_sql_split in api/analytics/routes.py (uncommitted candidate).
-- Rendered locally from current SQL builders. Not executed; not EXPLAIN ANALYZE.
-- Compare plan only; no claim that this candidate is faster or approved for deployment.
EXPLAIN FORMAT=JSON
SELECT
            b.barangayID,
            b.barangayName,
            COALESCE(ga.flagged_count, 0)    AS flagged_count,
            COALESCE(ga.red_count, 0)        AS red_count,
            COALESCE(ga.yellow_count, 0)     AS yellow_count,
            COALESCE(ga.black_count, 0)      AS black_count,
            ga.avg_lat                       AS avg_lat,
            ga.avg_lng                       AS avg_lng,
            COALESCE(oa.total_registered, 0) AS total_registered
        FROM barangays b
        LEFT JOIN (
            SELECT
                g.barangayID,
                COUNT(DISTINCT CASE WHEN CASE
        WHEN COALESCE(COALESCE((
        SELECT es.blackLocked
        FROM official_registry r_chk
        LEFT JOIN enforcement_state es
          ON es.subjectType = 'business'
         AND es.subjectID = CAST(r_chk.businessID AS CHAR)
        WHERE (
            (r_chk.businessID IS NOT NULL AND g.businessID IS NOT NULL
                AND r_chk.businessID = g.businessID)
            OR (g.placeID IS NOT NULL AND r_chk.placeID = g.placeID
                AND (g.businessID IS NULL OR r_chk.businessID = g.businessID))
            OR (g.businessID IS NULL
                AND r_chk.barangayID = g.barangayID
                AND r_chk.businessName = g.detectedName)
        )
        ORDER BY (r_chk.businessID = g.businessID) DESC,
                 (r_chk.placeID = g.placeID) DESC
        LIMIT 1
    ), (
        SELECT es.blackLocked
        FROM enforcement_state es
        WHERE es.subjectType = 'geospatial_log'
          AND es.subjectID = CAST(g.logID AS CHAR)
        LIMIT 1
    ), 0), 0) <> 0 THEN 'Black'
        WHEN (
        SELECT r_chk.applicationStatus
        FROM official_registry r_chk
        WHERE (
            (r_chk.businessID IS NOT NULL AND g.businessID IS NOT NULL
                AND r_chk.businessID = g.businessID)
            OR (g.placeID IS NOT NULL AND r_chk.placeID = g.placeID
                AND (g.businessID IS NULL OR r_chk.businessID = g.businessID))
            OR (g.businessID IS NULL
                AND r_chk.barangayID = g.barangayID
                AND r_chk.businessName = g.detectedName)
        )
        ORDER BY (r_chk.businessID = g.businessID) DESC,
                 (r_chk.placeID = g.placeID) DESC
        LIMIT 1
    ) IN ('Revoked', 'Blacklisted') THEN 'Black'
        WHEN COALESCE((
        SELECT es.warningLevel
        FROM official_registry r_chk
        LEFT JOIN enforcement_state es
          ON es.subjectType = 'business'
         AND es.subjectID = CAST(r_chk.businessID AS CHAR)
        WHERE (
            (r_chk.businessID IS NOT NULL AND g.businessID IS NOT NULL
                AND r_chk.businessID = g.businessID)
            OR (g.placeID IS NOT NULL AND r_chk.placeID = g.placeID
                AND (g.businessID IS NULL OR r_chk.businessID = g.businessID))
            OR (g.businessID IS NULL
                AND r_chk.barangayID = g.barangayID
                AND r_chk.businessName = g.detectedName)
        )
        ORDER BY (r_chk.businessID = g.businessID) DESC,
                 (r_chk.placeID = g.placeID) DESC
        LIMIT 1
    ), (
        SELECT es.warningLevel
        FROM enforcement_state es
        WHERE es.subjectType = 'geospatial_log'
          AND es.subjectID = CAST(g.logID AS CHAR)
        LIMIT 1
    ), 0) >= 1 THEN 'Orange'
        WHEN (
        SELECT r_chk.applicationStatus
        FROM official_registry r_chk
        WHERE (
            (r_chk.businessID IS NOT NULL AND g.businessID IS NOT NULL
                AND r_chk.businessID = g.businessID)
            OR (g.placeID IS NOT NULL AND r_chk.placeID = g.placeID
                AND (g.businessID IS NULL OR r_chk.businessID = g.businessID))
            OR (g.businessID IS NULL
                AND r_chk.barangayID = g.barangayID
                AND r_chk.businessName = g.detectedName)
        )
        ORDER BY (r_chk.businessID = g.businessID) DESC,
                 (r_chk.placeID = g.placeID) DESC
        LIMIT 1
    ) = 'Active' THEN 'Green'
        WHEN (
        SELECT r_chk.applicationStatus
        FROM official_registry r_chk
        WHERE (
            (r_chk.businessID IS NOT NULL AND g.businessID IS NOT NULL
                AND r_chk.businessID = g.businessID)
            OR (g.placeID IS NOT NULL AND r_chk.placeID = g.placeID
                AND (g.businessID IS NULL OR r_chk.businessID = g.businessID))
            OR (g.businessID IS NULL
                AND r_chk.barangayID = g.barangayID
                AND r_chk.businessName = g.detectedName)
        )
        ORDER BY (r_chk.businessID = g.businessID) DESC,
                 (r_chk.placeID = g.placeID) DESC
        LIMIT 1
    ) = 'Expired' THEN 'Red'
        WHEN (
        SELECT r_chk.applicationStatus
        FROM official_registry r_chk
        WHERE (
            (r_chk.businessID IS NOT NULL AND g.businessID IS NOT NULL
                AND r_chk.businessID = g.businessID)
            OR (g.placeID IS NOT NULL AND r_chk.placeID = g.placeID
                AND (g.businessID IS NULL OR r_chk.businessID = g.businessID))
            OR (g.businessID IS NULL
                AND r_chk.barangayID = g.barangayID
                AND r_chk.businessName = g.detectedName)
        )
        ORDER BY (r_chk.businessID = g.businessID) DESC,
                 (r_chk.placeID = g.placeID) DESC
        LIMIT 1
    ) = 'Closed' THEN 'Purple'
        WHEN (
        SELECT r_chk.applicationStatus
        FROM official_registry r_chk
        WHERE (
            (r_chk.businessID IS NOT NULL AND g.businessID IS NOT NULL
                AND r_chk.businessID = g.businessID)
            OR (g.placeID IS NOT NULL AND r_chk.placeID = g.placeID
                AND (g.businessID IS NULL OR r_chk.businessID = g.businessID))
            OR (g.businessID IS NULL
                AND r_chk.barangayID = g.barangayID
                AND r_chk.businessName = g.detectedName)
        )
        ORDER BY (r_chk.businessID = g.businessID) DESC,
                 (r_chk.placeID = g.placeID) DESC
        LIMIT 1
    ) = 'Pending' THEN 'Yellow'
        ELSE g.flagColor
    END IN ('Red', 'Yellow', 'Black') THEN g.logID END) AS flagged_count,
                COUNT(DISTINCT CASE WHEN CASE
        WHEN COALESCE(COALESCE((
        SELECT es.blackLocked
        FROM official_registry r_chk
        LEFT JOIN enforcement_state es
          ON es.subjectType = 'business'
         AND es.subjectID = CAST(r_chk.businessID AS CHAR)
        WHERE (
            (r_chk.businessID IS NOT NULL AND g.businessID IS NOT NULL
                AND r_chk.businessID = g.businessID)
            OR (g.placeID IS NOT NULL AND r_chk.placeID = g.placeID
                AND (g.businessID IS NULL OR r_chk.businessID = g.businessID))
            OR (g.businessID IS NULL
                AND r_chk.barangayID = g.barangayID
                AND r_chk.businessName = g.detectedName)
        )
        ORDER BY (r_chk.businessID = g.businessID) DESC,
                 (r_chk.placeID = g.placeID) DESC
        LIMIT 1
    ), (
        SELECT es.blackLocked
        FROM enforcement_state es
        WHERE es.subjectType = 'geospatial_log'
          AND es.subjectID = CAST(g.logID AS CHAR)
        LIMIT 1
    ), 0), 0) <> 0 THEN 'Black'
        WHEN (
        SELECT r_chk.applicationStatus
        FROM official_registry r_chk
        WHERE (
            (r_chk.businessID IS NOT NULL AND g.businessID IS NOT NULL
                AND r_chk.businessID = g.businessID)
            OR (g.placeID IS NOT NULL AND r_chk.placeID = g.placeID
                AND (g.businessID IS NULL OR r_chk.businessID = g.businessID))
            OR (g.businessID IS NULL
                AND r_chk.barangayID = g.barangayID
                AND r_chk.businessName = g.detectedName)
        )
        ORDER BY (r_chk.businessID = g.businessID) DESC,
                 (r_chk.placeID = g.placeID) DESC
        LIMIT 1
    ) IN ('Revoked', 'Blacklisted') THEN 'Black'
        WHEN COALESCE((
        SELECT es.warningLevel
        FROM official_registry r_chk
        LEFT JOIN enforcement_state es
          ON es.subjectType = 'business'
         AND es.subjectID = CAST(r_chk.businessID AS CHAR)
        WHERE (
            (r_chk.businessID IS NOT NULL AND g.businessID IS NOT NULL
                AND r_chk.businessID = g.businessID)
            OR (g.placeID IS NOT NULL AND r_chk.placeID = g.placeID
                AND (g.businessID IS NULL OR r_chk.businessID = g.businessID))
            OR (g.businessID IS NULL
                AND r_chk.barangayID = g.barangayID
                AND r_chk.businessName = g.detectedName)
        )
        ORDER BY (r_chk.businessID = g.businessID) DESC,
                 (r_chk.placeID = g.placeID) DESC
        LIMIT 1
    ), (
        SELECT es.warningLevel
        FROM enforcement_state es
        WHERE es.subjectType = 'geospatial_log'
          AND es.subjectID = CAST(g.logID AS CHAR)
        LIMIT 1
    ), 0) >= 1 THEN 'Orange'
        WHEN (
        SELECT r_chk.applicationStatus
        FROM official_registry r_chk
        WHERE (
            (r_chk.businessID IS NOT NULL AND g.businessID IS NOT NULL
                AND r_chk.businessID = g.businessID)
            OR (g.placeID IS NOT NULL AND r_chk.placeID = g.placeID
                AND (g.businessID IS NULL OR r_chk.businessID = g.businessID))
            OR (g.businessID IS NULL
                AND r_chk.barangayID = g.barangayID
                AND r_chk.businessName = g.detectedName)
        )
        ORDER BY (r_chk.businessID = g.businessID) DESC,
                 (r_chk.placeID = g.placeID) DESC
        LIMIT 1
    ) = 'Active' THEN 'Green'
        WHEN (
        SELECT r_chk.applicationStatus
        FROM official_registry r_chk
        WHERE (
            (r_chk.businessID IS NOT NULL AND g.businessID IS NOT NULL
                AND r_chk.businessID = g.businessID)
            OR (g.placeID IS NOT NULL AND r_chk.placeID = g.placeID
                AND (g.businessID IS NULL OR r_chk.businessID = g.businessID))
            OR (g.businessID IS NULL
                AND r_chk.barangayID = g.barangayID
                AND r_chk.businessName = g.detectedName)
        )
        ORDER BY (r_chk.businessID = g.businessID) DESC,
                 (r_chk.placeID = g.placeID) DESC
        LIMIT 1
    ) = 'Expired' THEN 'Red'
        WHEN (
        SELECT r_chk.applicationStatus
        FROM official_registry r_chk
        WHERE (
            (r_chk.businessID IS NOT NULL AND g.businessID IS NOT NULL
                AND r_chk.businessID = g.businessID)
            OR (g.placeID IS NOT NULL AND r_chk.placeID = g.placeID
                AND (g.businessID IS NULL OR r_chk.businessID = g.businessID))
            OR (g.businessID IS NULL
                AND r_chk.barangayID = g.barangayID
                AND r_chk.businessName = g.detectedName)
        )
        ORDER BY (r_chk.businessID = g.businessID) DESC,
                 (r_chk.placeID = g.placeID) DESC
        LIMIT 1
    ) = 'Closed' THEN 'Purple'
        WHEN (
        SELECT r_chk.applicationStatus
        FROM official_registry r_chk
        WHERE (
            (r_chk.businessID IS NOT NULL AND g.businessID IS NOT NULL
                AND r_chk.businessID = g.businessID)
            OR (g.placeID IS NOT NULL AND r_chk.placeID = g.placeID
                AND (g.businessID IS NULL OR r_chk.businessID = g.businessID))
            OR (g.businessID IS NULL
                AND r_chk.barangayID = g.barangayID
                AND r_chk.businessName = g.detectedName)
        )
        ORDER BY (r_chk.businessID = g.businessID) DESC,
                 (r_chk.placeID = g.placeID) DESC
        LIMIT 1
    ) = 'Pending' THEN 'Yellow'
        ELSE g.flagColor
    END = 'Red'    THEN g.logID END) AS red_count,
                COUNT(DISTINCT CASE WHEN CASE
        WHEN COALESCE(COALESCE((
        SELECT es.blackLocked
        FROM official_registry r_chk
        LEFT JOIN enforcement_state es
          ON es.subjectType = 'business'
         AND es.subjectID = CAST(r_chk.businessID AS CHAR)
        WHERE (
            (r_chk.businessID IS NOT NULL AND g.businessID IS NOT NULL
                AND r_chk.businessID = g.businessID)
            OR (g.placeID IS NOT NULL AND r_chk.placeID = g.placeID
                AND (g.businessID IS NULL OR r_chk.businessID = g.businessID))
            OR (g.businessID IS NULL
                AND r_chk.barangayID = g.barangayID
                AND r_chk.businessName = g.detectedName)
        )
        ORDER BY (r_chk.businessID = g.businessID) DESC,
                 (r_chk.placeID = g.placeID) DESC
        LIMIT 1
    ), (
        SELECT es.blackLocked
        FROM enforcement_state es
        WHERE es.subjectType = 'geospatial_log'
          AND es.subjectID = CAST(g.logID AS CHAR)
        LIMIT 1
    ), 0), 0) <> 0 THEN 'Black'
        WHEN (
        SELECT r_chk.applicationStatus
        FROM official_registry r_chk
        WHERE (
            (r_chk.businessID IS NOT NULL AND g.businessID IS NOT NULL
                AND r_chk.businessID = g.businessID)
            OR (g.placeID IS NOT NULL AND r_chk.placeID = g.placeID
                AND (g.businessID IS NULL OR r_chk.businessID = g.businessID))
            OR (g.businessID IS NULL
                AND r_chk.barangayID = g.barangayID
                AND r_chk.businessName = g.detectedName)
        )
        ORDER BY (r_chk.businessID = g.businessID) DESC,
                 (r_chk.placeID = g.placeID) DESC
        LIMIT 1
    ) IN ('Revoked', 'Blacklisted') THEN 'Black'
        WHEN COALESCE((
        SELECT es.warningLevel
        FROM official_registry r_chk
        LEFT JOIN enforcement_state es
          ON es.subjectType = 'business'
         AND es.subjectID = CAST(r_chk.businessID AS CHAR)
        WHERE (
            (r_chk.businessID IS NOT NULL AND g.businessID IS NOT NULL
                AND r_chk.businessID = g.businessID)
            OR (g.placeID IS NOT NULL AND r_chk.placeID = g.placeID
                AND (g.businessID IS NULL OR r_chk.businessID = g.businessID))
            OR (g.businessID IS NULL
                AND r_chk.barangayID = g.barangayID
                AND r_chk.businessName = g.detectedName)
        )
        ORDER BY (r_chk.businessID = g.businessID) DESC,
                 (r_chk.placeID = g.placeID) DESC
        LIMIT 1
    ), (
        SELECT es.warningLevel
        FROM enforcement_state es
        WHERE es.subjectType = 'geospatial_log'
          AND es.subjectID = CAST(g.logID AS CHAR)
        LIMIT 1
    ), 0) >= 1 THEN 'Orange'
        WHEN (
        SELECT r_chk.applicationStatus
        FROM official_registry r_chk
        WHERE (
            (r_chk.businessID IS NOT NULL AND g.businessID IS NOT NULL
                AND r_chk.businessID = g.businessID)
            OR (g.placeID IS NOT NULL AND r_chk.placeID = g.placeID
                AND (g.businessID IS NULL OR r_chk.businessID = g.businessID))
            OR (g.businessID IS NULL
                AND r_chk.barangayID = g.barangayID
                AND r_chk.businessName = g.detectedName)
        )
        ORDER BY (r_chk.businessID = g.businessID) DESC,
                 (r_chk.placeID = g.placeID) DESC
        LIMIT 1
    ) = 'Active' THEN 'Green'
        WHEN (
        SELECT r_chk.applicationStatus
        FROM official_registry r_chk
        WHERE (
            (r_chk.businessID IS NOT NULL AND g.businessID IS NOT NULL
                AND r_chk.businessID = g.businessID)
            OR (g.placeID IS NOT NULL AND r_chk.placeID = g.placeID
                AND (g.businessID IS NULL OR r_chk.businessID = g.businessID))
            OR (g.businessID IS NULL
                AND r_chk.barangayID = g.barangayID
                AND r_chk.businessName = g.detectedName)
        )
        ORDER BY (r_chk.businessID = g.businessID) DESC,
                 (r_chk.placeID = g.placeID) DESC
        LIMIT 1
    ) = 'Expired' THEN 'Red'
        WHEN (
        SELECT r_chk.applicationStatus
        FROM official_registry r_chk
        WHERE (
            (r_chk.businessID IS NOT NULL AND g.businessID IS NOT NULL
                AND r_chk.businessID = g.businessID)
            OR (g.placeID IS NOT NULL AND r_chk.placeID = g.placeID
                AND (g.businessID IS NULL OR r_chk.businessID = g.businessID))
            OR (g.businessID IS NULL
                AND r_chk.barangayID = g.barangayID
                AND r_chk.businessName = g.detectedName)
        )
        ORDER BY (r_chk.businessID = g.businessID) DESC,
                 (r_chk.placeID = g.placeID) DESC
        LIMIT 1
    ) = 'Closed' THEN 'Purple'
        WHEN (
        SELECT r_chk.applicationStatus
        FROM official_registry r_chk
        WHERE (
            (r_chk.businessID IS NOT NULL AND g.businessID IS NOT NULL
                AND r_chk.businessID = g.businessID)
            OR (g.placeID IS NOT NULL AND r_chk.placeID = g.placeID
                AND (g.businessID IS NULL OR r_chk.businessID = g.businessID))
            OR (g.businessID IS NULL
                AND r_chk.barangayID = g.barangayID
                AND r_chk.businessName = g.detectedName)
        )
        ORDER BY (r_chk.businessID = g.businessID) DESC,
                 (r_chk.placeID = g.placeID) DESC
        LIMIT 1
    ) = 'Pending' THEN 'Yellow'
        ELSE g.flagColor
    END = 'Yellow' THEN g.logID END) AS yellow_count,
                COUNT(DISTINCT CASE WHEN CASE
        WHEN COALESCE(COALESCE((
        SELECT es.blackLocked
        FROM official_registry r_chk
        LEFT JOIN enforcement_state es
          ON es.subjectType = 'business'
         AND es.subjectID = CAST(r_chk.businessID AS CHAR)
        WHERE (
            (r_chk.businessID IS NOT NULL AND g.businessID IS NOT NULL
                AND r_chk.businessID = g.businessID)
            OR (g.placeID IS NOT NULL AND r_chk.placeID = g.placeID
                AND (g.businessID IS NULL OR r_chk.businessID = g.businessID))
            OR (g.businessID IS NULL
                AND r_chk.barangayID = g.barangayID
                AND r_chk.businessName = g.detectedName)
        )
        ORDER BY (r_chk.businessID = g.businessID) DESC,
                 (r_chk.placeID = g.placeID) DESC
        LIMIT 1
    ), (
        SELECT es.blackLocked
        FROM enforcement_state es
        WHERE es.subjectType = 'geospatial_log'
          AND es.subjectID = CAST(g.logID AS CHAR)
        LIMIT 1
    ), 0), 0) <> 0 THEN 'Black'
        WHEN (
        SELECT r_chk.applicationStatus
        FROM official_registry r_chk
        WHERE (
            (r_chk.businessID IS NOT NULL AND g.businessID IS NOT NULL
                AND r_chk.businessID = g.businessID)
            OR (g.placeID IS NOT NULL AND r_chk.placeID = g.placeID
                AND (g.businessID IS NULL OR r_chk.businessID = g.businessID))
            OR (g.businessID IS NULL
                AND r_chk.barangayID = g.barangayID
                AND r_chk.businessName = g.detectedName)
        )
        ORDER BY (r_chk.businessID = g.businessID) DESC,
                 (r_chk.placeID = g.placeID) DESC
        LIMIT 1
    ) IN ('Revoked', 'Blacklisted') THEN 'Black'
        WHEN COALESCE((
        SELECT es.warningLevel
        FROM official_registry r_chk
        LEFT JOIN enforcement_state es
          ON es.subjectType = 'business'
         AND es.subjectID = CAST(r_chk.businessID AS CHAR)
        WHERE (
            (r_chk.businessID IS NOT NULL AND g.businessID IS NOT NULL
                AND r_chk.businessID = g.businessID)
            OR (g.placeID IS NOT NULL AND r_chk.placeID = g.placeID
                AND (g.businessID IS NULL OR r_chk.businessID = g.businessID))
            OR (g.businessID IS NULL
                AND r_chk.barangayID = g.barangayID
                AND r_chk.businessName = g.detectedName)
        )
        ORDER BY (r_chk.businessID = g.businessID) DESC,
                 (r_chk.placeID = g.placeID) DESC
        LIMIT 1
    ), (
        SELECT es.warningLevel
        FROM enforcement_state es
        WHERE es.subjectType = 'geospatial_log'
          AND es.subjectID = CAST(g.logID AS CHAR)
        LIMIT 1
    ), 0) >= 1 THEN 'Orange'
        WHEN (
        SELECT r_chk.applicationStatus
        FROM official_registry r_chk
        WHERE (
            (r_chk.businessID IS NOT NULL AND g.businessID IS NOT NULL
                AND r_chk.businessID = g.businessID)
            OR (g.placeID IS NOT NULL AND r_chk.placeID = g.placeID
                AND (g.businessID IS NULL OR r_chk.businessID = g.businessID))
            OR (g.businessID IS NULL
                AND r_chk.barangayID = g.barangayID
                AND r_chk.businessName = g.detectedName)
        )
        ORDER BY (r_chk.businessID = g.businessID) DESC,
                 (r_chk.placeID = g.placeID) DESC
        LIMIT 1
    ) = 'Active' THEN 'Green'
        WHEN (
        SELECT r_chk.applicationStatus
        FROM official_registry r_chk
        WHERE (
            (r_chk.businessID IS NOT NULL AND g.businessID IS NOT NULL
                AND r_chk.businessID = g.businessID)
            OR (g.placeID IS NOT NULL AND r_chk.placeID = g.placeID
                AND (g.businessID IS NULL OR r_chk.businessID = g.businessID))
            OR (g.businessID IS NULL
                AND r_chk.barangayID = g.barangayID
                AND r_chk.businessName = g.detectedName)
        )
        ORDER BY (r_chk.businessID = g.businessID) DESC,
                 (r_chk.placeID = g.placeID) DESC
        LIMIT 1
    ) = 'Expired' THEN 'Red'
        WHEN (
        SELECT r_chk.applicationStatus
        FROM official_registry r_chk
        WHERE (
            (r_chk.businessID IS NOT NULL AND g.businessID IS NOT NULL
                AND r_chk.businessID = g.businessID)
            OR (g.placeID IS NOT NULL AND r_chk.placeID = g.placeID
                AND (g.businessID IS NULL OR r_chk.businessID = g.businessID))
            OR (g.businessID IS NULL
                AND r_chk.barangayID = g.barangayID
                AND r_chk.businessName = g.detectedName)
        )
        ORDER BY (r_chk.businessID = g.businessID) DESC,
                 (r_chk.placeID = g.placeID) DESC
        LIMIT 1
    ) = 'Closed' THEN 'Purple'
        WHEN (
        SELECT r_chk.applicationStatus
        FROM official_registry r_chk
        WHERE (
            (r_chk.businessID IS NOT NULL AND g.businessID IS NOT NULL
                AND r_chk.businessID = g.businessID)
            OR (g.placeID IS NOT NULL AND r_chk.placeID = g.placeID
                AND (g.businessID IS NULL OR r_chk.businessID = g.businessID))
            OR (g.businessID IS NULL
                AND r_chk.barangayID = g.barangayID
                AND r_chk.businessName = g.detectedName)
        )
        ORDER BY (r_chk.businessID = g.businessID) DESC,
                 (r_chk.placeID = g.placeID) DESC
        LIMIT 1
    ) = 'Pending' THEN 'Yellow'
        ELSE g.flagColor
    END = 'Black'  THEN g.logID END) AS black_count,
                AVG(g.latitude)  AS avg_lat,
                AVG(g.longitude) AS avg_lng
            FROM geospatial_logs g
            WHERE (g.placeID IS NOT NULL OR g.reportedByUserID IS NOT NULL OR g.flagColor = 'Orange' OR EXISTS (SELECT 1 FROM inspection_reports ir WHERE ir.targetID = g.logID))
            GROUP BY g.barangayID
        ) ga ON ga.barangayID = b.barangayID
        LEFT JOIN (
            SELECT
                o.barangayID,
                COUNT(DISTINCT o.businessID) AS total_registered
            FROM official_registry o
            WHERE 1=1
            GROUP BY o.barangayID
        ) oa ON oa.barangayID = b.barangayID
        WHERE 1=1;
