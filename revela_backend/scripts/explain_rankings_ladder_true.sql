-- ======================================================================
-- REVELA analytics: WLC/OPS barangay-ranking aggregate (TIER 3)
-- provenance: ref 29d4891; api/analytics/routes.py:984-1001 (statement), :996/:998 (joins), :988-991 (colour columns); api/registry/colors.py:229-249 (_effective_flag_color_sql), :116-130 (ladder probe); api/analytics/filters.py:69-112 (registry_sql), :157-160 (geo_on_extra), :163-169 (barangay_b_sql)
-- ladder=True  filters=none  registrationType_supported=True
-- bound params (positional): []
-- Paste into a NON-PRODUCTION client only. Use EXPLAIN, never EXPLAIN ANALYZE.
-- ======================================================================
EXPLAIN FORMAT=JSON
        SELECT
            b.barangayID,
            b.barangayName,
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
            AVG(g.latitude)                                          AS avg_lat,
            AVG(g.longitude)                                         AS avg_lng,
            COUNT(DISTINCT o.businessID)                             AS total_registered
        FROM barangays b
        LEFT JOIN geospatial_logs   g ON g.barangayID = b.barangayID 
            AND (g.placeID IS NOT NULL OR g.reportedByUserID IS NOT NULL OR g.flagColor = 'Orange' OR EXISTS (SELECT 1 FROM inspection_reports ir WHERE ir.targetID = g.logID))
        LEFT JOIN official_registry o ON o.barangayID = b.barangayID
        WHERE 1=1 
        GROUP BY b.barangayID, b.barangayName
    
;
