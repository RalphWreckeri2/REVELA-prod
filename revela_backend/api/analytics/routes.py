import json
import math
import traceback
import os
from google import genai
from google.genai import types

from flask import Blueprint, jsonify, request
from api.middleware.decorators import jwt_required, admin_required
from api.analytics.service import get_wlc_config, update_wlc_config
from api.analytics.filters import (
    parse_analytics_filters,
    registry_sql,
    geo_sql,
    geo_on_extra,
    barangay_b_sql,
    inspection_sql,
    filters_without,
)

analytics_bp = Blueprint("analytics", __name__)


@analytics_bp.route("/all", methods=["GET"])
@jwt_required()
def get_all_analytics():
    try:
        F = parse_analytics_filters(request.args)
        res_response, status_code = _get_all_analytics_inner(F)
        data = res_response.get_json()
        
        from flask_jwt_extended import get_jwt_identity
        uid = int(get_jwt_identity())
        
        from app import mysql
        cursor = mysql.connection.cursor()
        cursor.execute(
            """
            SELECT id, body FROM revela_notifications
            WHERE recipientUserId = %s AND type = 'new_year_rollover' AND readAt IS NULL
            ORDER BY id DESC LIMIT 1
            """,
            (uid,)
        )
        notif = cursor.fetchone()
        cursor.close()
        
        import re
        rollover_info = None
        if notif:
            body = notif["body"]
            m = re.search(r"Welcome to (\d+)!.*marked (\d+) active", body)
            year = int(m.group(1)) if m else __import__('datetime').date.today().year
            count = int(m.group(2)) if m else 0
            rollover_info = {
                "detected": True,
                "count": count,
                "year": year,
                "notification_id": notif["id"]
            }
            
        data["new_year_rollover"] = rollover_info
        return jsonify(data), status_code
    except Exception as e:
        return jsonify({"error": str(e), "trace": traceback.format_exc()}), 500


def _get_all_analytics_inner(F=None):
    if F is None:
        F = {}
    from app import mysql
    from api.registry.service import check_and_expire_old_permits
    rollover_info = check_and_expire_old_permits()

    cur = mysql.connection.cursor()

    Fx = F or {}
    reg_all, reg_all_p = registry_sql("official_registry", Fx)
    reg_no_status, reg_no_status_p = registry_sql(
        "official_registry", filters_without(Fx, "application_status"))
    reg_o, reg_o_p = registry_sql("o", Fx)
    geo_g, geo_g_p = geo_sql("g", Fx)
    geo_g2, geo_g2_p = geo_sql("g2", Fx)
    geo_on_g, geo_on_g_p = geo_on_extra("g", Fx)
    brgy_b, brgy_b_p = barangay_b_sql(Fx)
    insp_ir, insp_ir_p = inspection_sql("ir", Fx)

    # ── WLC config ────────────────────────────────────────────────────────────
    config = get_wlc_config()
    w1 = config.get("w1_risk", 40) / 100
    w2 = config.get("w2_sector", 40) / 100
    w3 = config.get("w3_distance", 20) / 100
    bplo_lat = config.get("bplo_lat", 13.9667)
    bplo_lng = config.get("bplo_lng", 121.1167)
    sector_scores = config.get("sectors", {})

    # ══════════════════════════════════════════════════════════════════════════
    # TIER 1 — DESCRIPTIVE
    # ══════════════════════════════════════════════════════════════════════════

    cur.execute(
        "SELECT COUNT(*) AS n FROM official_registry WHERE 1=1" + reg_all,
        reg_all_p,
    )
    total_businesses = cur.fetchone()["n"]

    cur.execute(
        "SELECT COUNT(*) AS n FROM official_registry WHERE applicationStatus = 'Active'"
        + reg_no_status,
        reg_no_status_p,
    )
    active_count = cur.fetchone()["n"]

    cur.execute(
        "SELECT COUNT(*) AS n FROM official_registry WHERE applicationStatus = 'Expired'"
        + reg_no_status,
        reg_no_status_p,
    )
    expired_count = cur.fetchone()["n"]

    cur.execute(
        "SELECT COUNT(*) AS n FROM official_registry WHERE applicationStatus = 'Closed'"
        + reg_no_status,
        reg_no_status_p,
    )
    closed_count = cur.fetchone()["n"]

    cur.execute(
        "SELECT COUNT(*) AS n FROM official_registry WHERE applicationStatus = 'Pending'"
        + reg_no_status,
        reg_no_status_p,
    )
    pending_count = cur.fetchone()["n"]

    cur.execute(
        "SELECT COUNT(*) AS n FROM official_registry WHERE applicationStatus = 'Revoked'"
        + reg_no_status,
        reg_no_status_p,
    )
    revoked_count = cur.fetchone()["n"]

    cur.execute(
        "SELECT COUNT(*) AS n FROM official_registry WHERE YEAR(lastRenewalDate) = YEAR(CURDATE())"
        + reg_all,
        reg_all_p,
    )
    current_year_count = cur.fetchone()["n"]

    cur.execute(
        "SELECT COUNT(*) AS n FROM geospatial_logs g WHERE g.flagColor != 'Green' AND (g.placeID IS NOT NULL OR g.reportedByUserID IS NOT NULL OR g.flagColor = 'Orange' OR EXISTS (SELECT 1 FROM inspection_reports ir WHERE ir.targetID = g.logID))" + geo_g,
        geo_g_p,
    )
    total_flagged = cur.fetchone()["n"]

    compliance_rate = round(
        (active_count / total_businesses * 100), 1) if total_businesses else 0

    # Enforcement progress
    cur.execute(f"""
        SELECT
            b.barangayName,
            COUNT(DISTINCT CASE WHEN g.flagColor = 'Green'  THEN g.logID END) AS green_count,
            COUNT(DISTINCT CASE WHEN g.flagColor = 'Red'    THEN g.logID END) AS red_count,
            COUNT(DISTINCT CASE WHEN g.flagColor = 'Yellow' THEN g.logID END) AS yellow_count,
            COUNT(DISTINCT CASE WHEN g.flagColor = 'Black'  THEN g.logID END) AS black_count,
            COUNT(DISTINCT CASE WHEN g.flagColor = 'Orange' THEN g.logID END) AS orange_count,
            COUNT(DISTINCT CASE WHEN g.flagColor = 'Purple' THEN g.logID END) AS purple_count
        FROM barangays b
        LEFT JOIN geospatial_logs g ON g.barangayID = b.barangayID 
            AND (g.placeID IS NOT NULL OR g.reportedByUserID IS NOT NULL OR g.flagColor = 'Orange' OR EXISTS (SELECT 1 FROM inspection_reports ir WHERE ir.targetID = g.logID)){geo_on_g}
        WHERE 1=1 {brgy_b}
        GROUP BY b.barangayID, b.barangayName
        ORDER BY b.barangayName
    """, geo_on_g_p + brgy_b_p)
    enforcement_progress = [
        {
            "barangayName": row["barangayName"],
            "green_count":  row["green_count"] or 0,
            "red_count":    row["red_count"] or 0,
            "yellow_count": row["yellow_count"] or 0,
            "black_count":  row["black_count"] or 0,
            "orange_count": row["orange_count"] or 0,
            "purple_count": row["purple_count"] or 0,
        }
        for row in cur.fetchall()
    ]

    # Sectoral distribution
    cur.execute(f"""
        SELECT COALESCE(lineOfBusiness, 'Unclassified') AS sector, COUNT(*) AS count
        FROM official_registry
        WHERE 1=1 {reg_all}
        GROUP BY lineOfBusiness
        ORDER BY count DESC
    """, reg_all_p)
    sectoral_distribution = [
        {"sector": row["sector"], "count": row["count"]}
        for row in cur.fetchall()
    ]

    # Nature per barangay
    cur.execute(f"""
        SELECT COALESCE(b.barangayName, 'Unknown') AS barangayName, COALESCE(o.lineOfBusiness, 'Unclassified') AS nature, COUNT(*) AS count
        FROM official_registry o
        LEFT JOIN barangays b ON o.barangayID = b.barangayID
        WHERE 1=1 {reg_o}
        GROUP BY b.barangayName, nature
        ORDER BY b.barangayName ASC, count DESC
    """, reg_o_p)
    
    nature_per_barangay_raw = cur.fetchall()
    
    # Process into a format suitable for stacked bar chart: [{barangayName: 'Brgy 1', 'Retail': 10, 'Food': 5}, ...]
    nature_per_barangay_dict = {}
    for row in nature_per_barangay_raw:
        brgy = row["barangayName"]
        nature = row["nature"]
        count = row["count"]
        if brgy not in nature_per_barangay_dict:
            nature_per_barangay_dict[brgy] = {"barangayName": brgy}
        nature_per_barangay_dict[brgy][nature] = count
    
    nature_per_barangay = list(nature_per_barangay_dict.values())


    # Business size
    cur.execute(f"""
        SELECT COALESCE(businessSize, 'Unknown') AS size_label, COUNT(*) AS count
        FROM official_registry
        WHERE 1=1 {reg_all}
        GROUP BY businessSize
        ORDER BY count DESC
    """, reg_all_p)
    business_size_dist = [
        {"size_label": row["size_label"], "count": row["count"]}
        for row in cur.fetchall()
    ]

    # Business type (Legal Structure)
    cur.execute(f"""
        SELECT COALESCE(businessType, 'Unknown') AS type_label, COUNT(*) AS count
        FROM official_registry
        WHERE 1=1 {reg_all}
        GROUP BY businessType
        ORDER BY count DESC
    """, reg_all_p)
    business_type_dist = [
        {"type_label": row["type_label"], "count": row["count"]}
        for row in cur.fetchall()
    ]

    # Compliance by Business Size
    cur.execute(f"""
        SELECT COALESCE(businessSize, 'Unknown') AS size_label,
               SUM(CASE WHEN applicationStatus = 'Active' THEN 1 ELSE 0 END) AS active_count,
               SUM(CASE WHEN applicationStatus != 'Active' THEN 1 ELSE 0 END) AS inactive_count
        FROM official_registry
        WHERE 1=1 {reg_all}
        GROUP BY businessSize
    """, reg_all_p)
    compliance_by_size = [
        {
            "size_label": row["size_label"],
            "active_count": row["active_count"] or 0,
            "inactive_count": row["inactive_count"] or 0
        }
        for row in cur.fetchall()
    ]

    # Compliance timeline
    cur.execute(f"""
        SELECT
            DATE_FORMAT(lastRenewalDate, '%%Y-%%m') AS month,
            SUM(CASE WHEN applicationStatus = 'Active'  THEN 1 ELSE 0 END) AS active_count,
            SUM(CASE WHEN applicationStatus != 'Active' THEN 1 ELSE 0 END) AS non_active_count
        FROM official_registry
        WHERE lastRenewalDate >= DATE_SUB(NOW(), INTERVAL 12 MONTH)
        {reg_no_status}
        GROUP BY month
        ORDER BY month
    """, reg_no_status_p)
    compliance_timeline = [
        {
            "month":            row["month"],
            "active_count":     row["active_count"] or 0,
            "non_active_count": row["non_active_count"] or 0,
        }
        for row in cur.fetchall()
    ]

    # Audit summary
    cur.execute(f"""
        SELECT COUNT(*) AS n FROM inspection_reports ir
        JOIN geospatial_logs g ON ir.targetID = g.logID
        WHERE 1=1 {insp_ir} {geo_g}
    """, insp_ir_p + geo_g_p)
    total_inspections = cur.fetchone()["n"]

    cur.execute(f"""
        SELECT ir.inspectionResult, COUNT(*) AS count
        FROM inspection_reports ir
        JOIN geospatial_logs g ON ir.targetID = g.logID
        WHERE ir.inspectionResult IS NOT NULL {insp_ir} {geo_g}
        GROUP BY ir.inspectionResult
    """, insp_ir_p + geo_g_p)
    result_breakdown = [
        {"inspectionResult": row["inspectionResult"], "count": row["count"]}
        for row in cur.fetchall()
    ]

    # ══════════════════════════════════════════════════════════════════════════
    # TIER 2 — DIAGNOSTIC
    # ══════════════════════════════════════════════════════════════════════════

    # Barangay risk heatmap
    cur.execute(f"""
        SELECT
            b.barangayID,
            b.barangayName,
            COUNT(DISTINCT CASE WHEN g.flagColor != 'Green' THEN g.logID END) AS flagged_count,
            COUNT(DISTINCT CASE WHEN g.flagColor = 'Red'    THEN g.logID END) AS red_count,
            COUNT(DISTINCT CASE WHEN g.flagColor = 'Yellow' THEN g.logID END) AS yellow_count,
            COUNT(DISTINCT CASE WHEN g.flagColor = 'Black'  THEN g.logID END) AS black_count,
            COUNT(DISTINCT CASE WHEN g.flagColor = 'Orange' THEN g.logID END) AS orange_count,
            COUNT(DISTINCT CASE WHEN g.flagColor = 'Purple' THEN g.logID END) AS purple_count
        FROM barangays b
        LEFT JOIN geospatial_logs g ON g.barangayID = b.barangayID 
            AND (g.placeID IS NOT NULL OR g.reportedByUserID IS NOT NULL OR g.flagColor = 'Orange' OR EXISTS (SELECT 1 FROM inspection_reports ir WHERE ir.targetID = g.logID)){geo_on_g}
        WHERE 1=1 {brgy_b}
        GROUP BY b.barangayID, b.barangayName
        ORDER BY flagged_count DESC
    """, geo_on_g_p + brgy_b_p)
    barangay_risk_data = [
        {
            "barangayID":    row["barangayID"],
            "barangayName":  row["barangayName"],
            "flagged_count": row["flagged_count"] or 0,
            "red_count":     row["red_count"] or 0,
            "yellow_count":  row["yellow_count"] or 0,
            "black_count":   row["black_count"] or 0,
            "orange_count":  row["orange_count"] or 0,
            "purple_count":  row["purple_count"] or 0,
        }
        for row in cur.fetchall()
    ]

    high_risk_barangays = sum(
        1 for r in barangay_risk_data
        if r["red_count"] > 0 or r["flagged_count"] >= 5
    )

    # Category non-compliance
    # NOTE: join is normalized (case/whitespace-insensitive) because detected names
    # from the field rarely match registry names character-for-character — an exact
    # match dumps most logs into the 'Unclassified' bucket. We also count DISTINCT
    # detected entities (name + barangay), not raw detection events, so the ranking
    # reflects how many unique businesses are flagged per line of business.
    cur.execute(f"""
        SELECT
            COALESCE(o.lineOfBusiness, 'Unclassified') AS category,
            COUNT(DISTINCT CONCAT(LOWER(TRIM(g.detectedName)), '|', g.barangayID)) AS flagged_count
        FROM geospatial_logs g
        LEFT JOIN official_registry o ON LOWER(TRIM(g.detectedName)) = LOWER(TRIM(o.businessName))
            AND g.barangayID = o.barangayID{reg_o}
        WHERE 1=1 AND g.flagColor != 'Green' 
          AND (g.placeID IS NOT NULL OR g.reportedByUserID IS NOT NULL OR g.flagColor = 'Orange' OR EXISTS (SELECT 1 FROM inspection_reports ir WHERE ir.targetID = g.logID)) {geo_g}
        GROUP BY category
        ORDER BY flagged_count DESC
        LIMIT 10
    """, reg_o_p + geo_g_p)
    category_noncompliance = [
        {"category": row["category"], "flagged_count": row["flagged_count"]}
        for row in cur.fetchall()
    ]

    # Weekly red-flag trend
    cur.execute(f"""
        SELECT
            DATE_FORMAT(
                DATE_SUB(g.detectedDate, INTERVAL WEEKDAY(g.detectedDate) DAY),
                '%%Y-%%m-%%d'
            ) AS week_start,
            COUNT(DISTINCT CASE WHEN g.flagColor = 'Red' THEN g.logID END) AS new_red_flags
        FROM geospatial_logs g
        WHERE g.detectedDate >= DATE_SUB(NOW(), INTERVAL 8 WEEK) 
          AND (g.placeID IS NOT NULL OR g.reportedByUserID IS NOT NULL OR g.flagColor = 'Orange' OR EXISTS (SELECT 1 FROM inspection_reports ir WHERE ir.targetID = g.logID)) {geo_g}
        GROUP BY week_start
        ORDER BY week_start
    """, geo_g_p)
    flag_trend = [
        {"week_start": str(row["week_start"]),
         "new_red_flags": row["new_red_flags"] or 0}
        for row in cur.fetchall()
    ]

    # DBSCAN Hotspot Intelligence
    dbscan_insight = "Not enough data to pinpoint specific high-risk zones."
    dbscan_clusters = []
    try:
        cur.execute(f"""
            SELECT g.latitude, g.longitude, COALESCE(b.barangayName, 'Unknown Area') as barangayName
            FROM geospatial_logs g
            LEFT JOIN barangays b ON g.barangayID = b.barangayID
            WHERE g.flagColor IN ('Red', 'Black')
              AND g.latitude IS NOT NULL
              AND g.longitude IS NOT NULL
              AND (g.placeID IS NOT NULL OR g.reportedByUserID IS NOT NULL OR g.flagColor = 'Orange' OR EXISTS (SELECT 1 FROM inspection_reports ir WHERE ir.targetID = g.logID)) {geo_g}
        """, geo_g_p)
        hotspot_data = cur.fetchall()

        if len(hotspot_data) >= 3:
            import numpy as np
            from sklearn.cluster import DBSCAN
            from collections import Counter

            # Convert coords to radians for Haversine distance
            coords = np.radians(
                [[float(r['latitude']), float(r['longitude'])] for r in hotspot_data])

            # 20 meters in radians (10m is often too strict due to GPS drift, 20m provides a better result)
            kms_per_radian = 6371.0088
            epsilon = 0.02 / kms_per_radian

            db = DBSCAN(eps=epsilon, min_samples=3,
                        algorithm='ball_tree', metric='haversine').fit(coords)
            labels = db.labels_

            valid_labels = [lbl for lbl in labels if lbl != -1]  # -1 is noise
            largest_cluster_label = -1
            if valid_labels:
                # Find largest cluster
                largest_cluster_label = Counter(
                    valid_labels).most_common(1)[0][0]
                cluster_size = Counter(valid_labels).most_common(1)[0][1]

            # Export points for visualization
            for idx, row in enumerate(hotspot_data):
                dbscan_clusters.append({
                    "lat": float(row['latitude']),
                    "lng": float(row['longitude']),
                    "cluster": int(labels[idx]),
                    "is_primary": bool(int(labels[idx]) == largest_cluster_label and int(labels[idx]) != -1),
                    "barangay": row['barangayName']
                })

            if valid_labels:

                # Find dominant barangay in this cluster
                cluster_barangays = [hotspot_data[i]['barangayName'] for i, lbl in enumerate(
                    labels) if lbl == largest_cluster_label]
                dominant_barangay = Counter(
                    cluster_barangays).most_common(1)[0][0]

                dbscan_insight = f"Primary Hotspot: {cluster_size} unregistered/high-risk businesses located closely together near {dominant_barangay}. Immediate inspection recommended."
            else:
                dbscan_insight = "No densely packed zones of high-risk businesses detected at this time."
    except Exception as e:
        print(f"DBSCAN Error: {e}")
        dbscan_insight = "Hotspot detection temporarily unavailable."

    # Moran's I Proxy (Spatial Autocorrelation)
    morans_insight = "Not enough data to determine broader geographic patterns."
    morans_data = {"points": [], "threshold": 0}
    try:
        cur.execute(f"""
            SELECT 
                b.barangayName,
                AVG(g.latitude) as lat,
                AVG(g.longitude) as lng,
                COUNT(DISTINCT CASE WHEN g.flagColor IN ('Red', 'Black') THEN g.logID END) as severe_count
            FROM barangays b
            JOIN geospatial_logs g ON b.barangayID = g.barangayID 
                AND (g.placeID IS NOT NULL OR g.reportedByUserID IS NOT NULL OR g.flagColor = 'Orange' OR EXISTS (SELECT 1 FROM inspection_reports ir WHERE ir.targetID = g.logID)){geo_on_g}
            WHERE g.latitude IS NOT NULL AND g.longitude IS NOT NULL {brgy_b}
            GROUP BY b.barangayID, b.barangayName
        """, geo_on_g_p + brgy_b_p)
        brgy_spatial = cur.fetchall()

        if len(brgy_spatial) >= 4:
            import numpy as np

            points = [
                {'name': r['barangayName'], 'lat': float(r['lat']), 'lng': float(
                    r['lng']), 'risk': float(r['severe_count'])}
                for r in brgy_spatial if r['lat'] and r['lng']
            ]

            if len(points) >= 4:
                risk_values = [p['risk'] for p in points]
                threshold = np.percentile(risk_values, 75) if sum(
                    risk_values) > 0 else 0
                
                morans_data["threshold"] = float(threshold)
                morans_data["points"] = [
                    {"barangay": p['name'], "risk": p['risk'], "is_high_risk": bool(p['risk'] > threshold and p['risk'] > 0)}
                    for p in points
                ]
                
                high_risk_points = [
                    p for p in points if p['risk'] > threshold and p['risk'] > 0]

                if len(high_risk_points) >= 2:
                    all_lat = np.mean([p['lat'] for p in points])
                    all_lng = np.mean([p['lng'] for p in points])
                    hr_lat = np.mean([p['lat'] for p in high_risk_points])
                    hr_lng = np.mean([p['lng'] for p in high_risk_points])

                    ns = "Northern" if hr_lat > all_lat else "Southern"
                    ew = "Eastern" if hr_lng > all_lng else "Western"

                    def haversine(lat1, lon1, lat2, lon2):
                        R = 6371
                        dLat, dLon = np.radians(
                            lat2 - lat1), np.radians(lon2 - lon1)
                        a = np.sin(dLat/2)**2 + np.cos(np.radians(lat1)) * \
                            np.cos(np.radians(lat2)) * np.sin(dLon/2)**2
                        return R * 2 * np.arctan2(np.sqrt(a), np.sqrt(1-a))

                    all_dists = [haversine(points[i]['lat'], points[i]['lng'], points[j]['lat'], points[j]['lng'])
                                 for i in range(len(points)) for j in range(i+1, len(points))]
                    hr_dists = [haversine(high_risk_points[i]['lat'], high_risk_points[i]['lng'], high_risk_points[j]['lat'], high_risk_points[j]['lng'])
                                for i in range(len(high_risk_points)) for j in range(i+1, len(high_risk_points))]

                    avg_all = np.mean(all_dists)
                    avg_hr = np.mean(hr_dists) if hr_dists else 0

                    if 0 < avg_hr < (avg_all * 0.85):
                        morans_insight = f"Concentrated Risk: High-risk barangays are heavily grouped together, primarily located in the {ns}-{ew} sector."
                    elif avg_hr > (avg_all * 1.15):
                        morans_insight = f"Widespread Risk: High-risk barangays are scattered widely across the municipality."
                    else:
                        morans_insight = f"No Obvious Pattern: High-risk areas are distributed randomly without obvious clustering."
                else:
                    morans_insight = "Not enough variation in risk to determine regional patterns."
    except Exception as e:
        print(f"Moran's I Proxy Error: {e}")
        morans_insight = "Regional pattern analysis temporarily unavailable."

    # ══════════════════════════════════════════════════════════════════════════
    # TIER 3 — PRESCRIPTIVE (WLC / OPS)
    # ══════════════════════════════════════════════════════════════════════════

    # NOTE: Per the manuscript (§3.1 Prescriptive Analytics), only Red, Yellow,
    # and Black flags are weighed in the WLC/OPS model. Green (compliant),
    # Orange (under monitoring via warning letters), and Purple (permanently
    # closed/abandoned) establishments are excluded from this computation, as
    # they no longer represent active compliance risks requiring field
    # deployment. flagged_count therefore counts ONLY Red/Yellow/Black logs,
    # which drives the risk-score scaling term, the non-compliance rate, and
    # the proportional inspector allocation in dispatch recommendations.
    cur.execute(f"""
        SELECT
            b.barangayID,
            b.barangayName,
            COUNT(DISTINCT CASE WHEN g.flagColor IN ('Red', 'Yellow', 'Black') THEN g.logID END) AS flagged_count,
            COUNT(DISTINCT CASE WHEN g.flagColor = 'Red'    THEN g.logID END) AS red_count,
            COUNT(DISTINCT CASE WHEN g.flagColor = 'Yellow' THEN g.logID END) AS yellow_count,
            COUNT(DISTINCT CASE WHEN g.flagColor = 'Black'  THEN g.logID END) AS black_count,
            AVG(g.latitude)                                          AS avg_lat,
            AVG(g.longitude)                                         AS avg_lng,
            COUNT(DISTINCT o.businessID)                             AS total_registered
        FROM barangays b
        LEFT JOIN geospatial_logs   g ON g.barangayID = b.barangayID 
            AND (g.placeID IS NOT NULL OR g.reportedByUserID IS NOT NULL OR g.flagColor = 'Orange' OR EXISTS (SELECT 1 FROM inspection_reports ir WHERE ir.targetID = g.logID)){geo_on_g}
        LEFT JOIN official_registry o ON o.barangayID = b.barangayID{reg_o}
        WHERE 1=1 {brgy_b}
        GROUP BY b.barangayID, b.barangayName
    """, geo_on_g_p + reg_o_p + brgy_b_p)
    rows = cur.fetchall()

    max_flagged = max((r["flagged_count"] or 0 for r in rows), default=1) or 1
    rankings = []

    for row in rows:
        flagged = int(row["flagged_count"] or 0)
        red = int(row["red_count"] or 0)
        yellow = int(row["yellow_count"] or 0)
        black = int(row["black_count"] or 0)
        total_reg = int(row["total_registered"] or 0)
        avg_lat = row["avg_lat"]
        avg_lng = row["avg_lng"]

        risk_score = min(
            ((red * 3 + yellow * 2 + black * 4) / max(flagged, 1))
            * (flagged / max_flagged) * 100,
            100,
        )

        sector_score = float(sector_scores.get(row["barangayName"], 50))

        if avg_lat and avg_lng:
            R = 6371
            dlat = math.radians(float(avg_lat) - bplo_lat)
            dlng = math.radians(float(avg_lng) - bplo_lng)
            a = (math.sin(dlat / 2) ** 2
                 + math.cos(math.radians(bplo_lat))
                 * math.cos(math.radians(float(avg_lat)))
                 * math.sin(dlng / 2) ** 2)
            dist_km = R * 2 * math.asin(math.sqrt(a))
            distance_score = min(dist_km / 20 * 100, 100)
        else:
            distance_score = 50

        # Convert distance penalty to a normalized addition so OPS scales 0-100 properly
        ops_score = round(w1 * risk_score + w2 *
                          sector_score + w3 * (100 - distance_score), 1)
        ops_score = max(0.0, min(100.0, ops_score))

        non_compliance_rate = round(
            (flagged / total_reg * 100), 1) if total_reg else 0

        risk_level = (
            "High" if ops_score >= 60 else
            "Medium" if ops_score >= 30 else
            "Low"
        )

        rankings.append({
            "barangayID":          row["barangayID"],
            "barangayName":        row["barangayName"],
            "ops_score":           ops_score,
            "risk_score":          round(risk_score, 1),
            "sector_score":        sector_score,
            "distance_score":      round(distance_score, 1),
            "flagged_count":       flagged,
            "red_count":           red,
            "yellow_count":        yellow,
            "black_count":         black,
            "non_compliance_rate": non_compliance_rate,
            "risk_level":          risk_level,
        })

    rankings.sort(key=lambda x: x["ops_score"], reverse=True)
    for i, r in enumerate(rankings):
        r["rank"] = i + 1

    # --- Dispatch Recommendations ---
    from api.analytics.dispatch import generate_recommendations

    cur.execute(
        "SELECT COUNT(*) AS n FROM users WHERE userRole = 'Inspector' AND isActive = 1")
    inspector_row = cur.fetchone()
    total_inspectors = int(inspector_row["n"]) if inspector_row and inspector_row["n"] else 6

    # Pass the actual WLC weights (w1, w2, w3 are already normalised floats from config)
    dispatch_weights = {"w1": w1, "w2": w2, "w3": w3}
    dispatch_recommendations = generate_recommendations(rankings, total_inspectors, dispatch_weights)

    # ══════════════════════════════════════════════════════════════════════════
    # TIER 4 — OPERATIONS
    # ══════════════════════════════════════════════════════════════════════════
    
    # 1. Inspector Leaderboard
    # Driven FROM users (LEFT JOIN reports) so EVERY active inspector appears —
    # including those with zero assigned/reported tasks. The old INNER-JOIN-
    # from-reports version silently omitted idle inspectors, which made the
    # AI assistant under-count the workforce. Filter fragments live in the ON
    # clauses so date/status filters don't re-inner-join and hide them again.
    cur.execute(f"""
        SELECT 
            u.userID, 
            u.fullName, 
            COUNT(ir.reportID) as total_assigned, 
            SUM(CASE WHEN ir.verificationStatus IN ('Verified', 'Submitted') THEN 1 ELSE 0 END) as total_completed, 
            AVG(ir.resolutionTime) as avg_resolution_time,
            (SELECT COUNT(*) FROM geospatial_logs g2 WHERE g2.reportedByUserID = u.userID AND g2.flagColor = 'Yellow'{geo_g2}) as yellow_flags_reported
        FROM users u
        LEFT JOIN inspection_reports ir ON ir.userID = u.userID{insp_ir}
        LEFT JOIN geospatial_logs g ON ir.targetID = g.logID{geo_g}
        WHERE u.userRole = 'Inspector' AND u.isActive = 1
        GROUP BY u.userID
        ORDER BY total_completed DESC
    """, geo_g2_p + insp_ir_p + geo_g_p)
    inspector_stats = list(cur.fetchall())
    for stat in inspector_stats:
        if stat["avg_resolution_time"] is not None:
            stat["avg_resolution_time"] = float(stat["avg_resolution_time"])
        else:
            stat["avg_resolution_time"] = 0.0

    # 2. Inspection Status Breakdown
    cur.execute(f"""
        SELECT COALESCE(ir.verificationStatus, 'Unassigned') as status, COUNT(ir.reportID) as count
        FROM inspection_reports ir
        LEFT JOIN geospatial_logs g ON ir.targetID = g.logID
        WHERE 1=1 {insp_ir} {geo_g}
        GROUP BY ir.verificationStatus
    """, insp_ir_p + geo_g_p)
    status_breakdown = list(cur.fetchall())

    # 3. Inspection Timeline
    cur.execute(f"""
        SELECT DATE(ir.irTimestamp) as date, COUNT(ir.reportID) as count
        FROM inspection_reports ir
        LEFT JOIN geospatial_logs g ON ir.targetID = g.logID
        WHERE 1=1 {insp_ir} {geo_g}
        GROUP BY DATE(ir.irTimestamp)
        ORDER BY date ASC
    """, insp_ir_p + geo_g_p)
    timeline_rows = list(cur.fetchall())
    inspection_timeline = []
    for row in timeline_rows:
        inspection_timeline.append({
            "date": row["date"].strftime("%Y-%m-%d") if row["date"] else None,
            "count": row["count"]
        })

    cur.close()

    return jsonify({
        "applied_filters": Fx,
        "new_year_rollover": rollover_info,
        "descriptive": {
            "kpis": {
                "total_businesses":    total_businesses,
                "active_count":        active_count,
                "expired_count":       expired_count,
                "closed_count":        closed_count,
                "pending_count":       pending_count,
                "revoked_count":       revoked_count,
                "current_year_count":  current_year_count,
                "total_flagged":       total_flagged,
                "compliance_rate":     compliance_rate,
                "high_risk_barangays": high_risk_barangays,
            },
            "enforcement_progress":  enforcement_progress,
            "nature_per_barangay":   nature_per_barangay,
            "sectoral_distribution": sectoral_distribution,
            "business_size_dist":    business_size_dist,
            "business_type_dist":    business_type_dist,
            "compliance_by_size":    compliance_by_size,
            "compliance_timeline":   compliance_timeline,
            "audit_summary": {
                "total_inspections": total_inspections,
                "result_breakdown":  result_breakdown,
            },
        },
        "diagnostic": {
            "barangay_risk_data":     barangay_risk_data,
            "category_noncompliance": category_noncompliance,
            "flag_trend":             flag_trend,
            "dbscan_insight":         dbscan_insight,
            "morans_insight":         morans_insight,
            "dbscan_clusters":        dbscan_clusters,
            "morans_data":            morans_data,
        },
        "prescriptive": {
            "rankings":   rankings,
            "wlc_config": config,
            "dispatch_recommendations": dispatch_recommendations,
        },
        "operations": {
            "inspector_stats": inspector_stats,
            "status_breakdown": status_breakdown,
            "inspection_timeline": inspection_timeline,
        },
    }), 200


@analytics_bp.route("/filter-metadata", methods=["GET"])
@jwt_required()
def analytics_filter_metadata():
    """Distinct values for analytics filter controls (registry, flags, inspections)."""
    from app import mysql

    cur = mysql.connection.cursor()
    cur.execute(
        """
        SELECT DISTINCT applicationStatus AS v FROM official_registry
        WHERE applicationStatus IS NOT NULL AND TRIM(applicationStatus) <> ''
        ORDER BY applicationStatus
        """
    )
    application_statuses = [r["v"] for r in cur.fetchall()]

    cur.execute(
        """
        SELECT DISTINCT lineOfBusiness AS v FROM official_registry
        WHERE lineOfBusiness IS NOT NULL AND TRIM(lineOfBusiness) <> ''
        ORDER BY lineOfBusiness
        LIMIT 500
        """
    )
    lines_of_business = [r["v"] for r in cur.fetchall()]

    cur.execute(
        """
        SELECT DISTINCT businessType AS v FROM official_registry
        WHERE businessType IS NOT NULL AND TRIM(businessType) <> ''
        ORDER BY businessType
        LIMIT 500
        """
    )
    business_types = [r["v"] for r in cur.fetchall()]

    cur.execute(
        """
        SELECT DISTINCT businessSize AS v FROM official_registry
        WHERE businessSize IS NOT NULL AND TRIM(businessSize) <> ''
        ORDER BY businessSize
        """
    )
    business_sizes = [r["v"] for r in cur.fetchall()]

    cur.execute(
        """
        SELECT DISTINCT inspectionResult AS v FROM inspection_reports
        WHERE inspectionResult IS NOT NULL AND TRIM(inspectionResult) <> ''
        ORDER BY inspectionResult
        """
    )
    inspection_results = [r["v"] for r in cur.fetchall()]

    cur.execute(
        """
        SELECT DISTINCT verificationStatus AS v FROM inspection_reports
        WHERE verificationStatus IS NOT NULL AND TRIM(verificationStatus) <> ''
        ORDER BY verificationStatus
        """
    )
    verification_statuses = [r["v"] for r in cur.fetchall()]

    cur.close()

    return jsonify({
        "flag_colors": ["Green", "Yellow", "Red", "Black", "Orange", "Purple"],
        "application_statuses": application_statuses,
        "lines_of_business": lines_of_business,
        "business_types": business_types,
        "business_sizes": business_sizes,
        "inspection_results": inspection_results,
        "verification_statuses": verification_statuses,
    }), 200


# ─────────────────────────────────────────────────────────────────────────────
@analytics_bp.route("/ops-rankings", methods=["GET"])
@jwt_required()
def get_ops_rankings_only():
    """Lightweight endpoint to fetch real-time OPS priority rankings for the Maps/Dispatch UI."""
    try:
        from app import mysql
        cur = mysql.connection.cursor()

        config = get_wlc_config()
        w1 = config.get("w1_risk", 40) / 100
        w2 = config.get("w2_sector", 40) / 100
        w3 = config.get("w3_distance", 20) / 100
        bplo_lat = config.get("bplo_lat", 13.9667)
        bplo_lng = config.get("bplo_lng", 121.1167)
        sector_scores = config.get("sectors", {})

        # Same exclusion rule as the main analytics endpoint: only Red/Yellow/
        # Black flags feed the OPS ranking shown in the Priority Dispatch Queue.
        cur.execute("""
            SELECT
                b.barangayID,
                b.barangayName,
                COUNT(DISTINCT CASE WHEN g.flagColor IN ('Red', 'Yellow', 'Black') THEN g.logID END) AS flagged_count,
                COUNT(DISTINCT CASE WHEN g.flagColor = 'Red'    THEN g.logID END) AS red_count,
                COUNT(DISTINCT CASE WHEN g.flagColor = 'Yellow' THEN g.logID END) AS yellow_count,
                COUNT(DISTINCT CASE WHEN g.flagColor = 'Black'  THEN g.logID END) AS black_count,
                AVG(g.latitude)                                          AS avg_lat,
                AVG(g.longitude)                                         AS avg_lng
            FROM barangays b
            LEFT JOIN geospatial_logs g ON g.barangayID = b.barangayID 
                AND (g.placeID IS NOT NULL OR g.reportedByUserID IS NOT NULL OR g.flagColor = 'Orange' OR EXISTS (SELECT 1 FROM inspection_reports ir WHERE ir.targetID = g.logID))
            GROUP BY b.barangayID, b.barangayName
        """)
        rows = cur.fetchall()

        max_flagged = max(
            (r["flagged_count"] or 0 for r in rows), default=1) or 1
        rankings = []

        for row in rows:
            flagged = int(row["flagged_count"] or 0)
            risk_score = min(
                (((int(row["red_count"] or 0) * 3 + int(row["yellow_count"] or 0) * 2 + int(row["black_count"] or 0) * 4) / max(flagged, 1))
                 * (flagged / max_flagged) * 100), 100
            )
            sector_score = float(sector_scores.get(row["barangayName"], 50))

            if row["avg_lat"] and row["avg_lng"]:
                R = 6371
                a = (math.sin(math.radians(float(row["avg_lat"]) - bplo_lat) / 2) ** 2
                     + math.cos(math.radians(bplo_lat)) *
                     math.cos(math.radians(float(row["avg_lat"])))
                     * math.sin(math.radians(float(row["avg_lng"]) - bplo_lng) / 2) ** 2)
                distance_score = min(
                    (R * 2 * math.asin(math.sqrt(a))) / 20 * 100, 100)
            else:
                distance_score = 50

            ops_score = max(0.0, min(100.0, round(
                w1 * risk_score + w2 * sector_score + w3 * (100 - distance_score), 1)))

            rankings.append({
                "barangayID": row["barangayID"],
                "barangayName": row["barangayName"],
                "ops_score": ops_score,
                "flagged_count": flagged,
                "red_count": int(row["red_count"] or 0),
                "yellow_count": int(row["yellow_count"] or 0),
                "black_count": int(row["black_count"] or 0),
                "risk_level": "High" if ops_score >= 60 else "Medium" if ops_score >= 30 else "Low"
            })

        rankings.sort(key=lambda x: x["ops_score"], reverse=True)
        for i, r in enumerate(rankings):
            r["rank"] = i + 1
        cur.close()
        return jsonify({"data": rankings}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ─────────────────────────────────────────────────────────────────────────────
@analytics_bp.route("/wlc-config", methods=["GET"])
@jwt_required()
def get_config():
    return jsonify(get_wlc_config()), 200


@analytics_bp.route("/wlc-config", methods=["PUT"])
@admin_required()
def update_config():
    data = request.get_json()
    if not data:
        return jsonify({"error": "No configuration data provided."}), 400
    updated_config, error = update_wlc_config(data)
    if error:
        return jsonify({"error": error}), 500
    return jsonify({"message": "WLC configuration updated successfully.", "data": updated_config}), 200


@analytics_bp.route("/chat", methods=["POST"])
@jwt_required()
def analytics_chat():
    data = request.get_json()
    chart_id = data.get("chartId")
    chart_data = data.get("data")
    messages = data.get("messages", [])
    user_query = data.get("userQuery")

    if not user_query:
        return jsonify({"error": "User query is required"}), 400

    gemini_api_key = os.environ.get("GEMINI_API_KEY")
    if not gemini_api_key:
        return jsonify({"error": "GEMINI_API_KEY is not configured in the backend environment."}), 500

    client = genai.Client(api_key=gemini_api_key)

    # ── Summarize global dashboard data so the LLM gets digestible context ──
    if chart_id == "global_dashboard" and isinstance(chart_data, dict):
        summary_parts = []

        # KPIs
        kpis = chart_data.get("kpis", {})
        if kpis:
            summary_parts.append(f"KPIs: {json.dumps(kpis)}")

        # Geographic (barangay breakdown) – all barangays
        geo = chart_data.get("geographic", [])
        if geo:
            try:
                sorted_geo = sorted(geo, key=lambda x: sum(v for k, v in x.items() if k != "barangay" and isinstance(v, (int, float))), reverse=True)
            except Exception:
                sorted_geo = geo
            summary_parts.append(f"All Barangays (by business volume, highest first): {json.dumps(sorted_geo)}")

        # Sectoral (business lines) – all sectors
        sectors = chart_data.get("sectoral", [])
        if sectors:
            try:
                sorted_sectors = sorted(sectors, key=lambda x: x.get("count", x.get("value", 0)), reverse=True)
            except Exception:
                sorted_sectors = sectors
            summary_parts.append(f"All Business Sectors (by count, highest first): {json.dumps(sorted_sectors)}")

        # Business sizes
        sizes = chart_data.get("size", [])
        if sizes:
            summary_parts.append(f"Business Size Distribution: {json.dumps(sizes)}")

        # Legal structure
        legal = chart_data.get("legalStructure", [])
        if legal:
            summary_parts.append(f"Business Legal Structure: {json.dumps(legal)}")

        # Compliance by size
        comp_size = chart_data.get("complianceBySize", [])
        if comp_size:
            summary_parts.append(f"Compliance by Business Size: {json.dumps(comp_size)}")

        # Compliance timeline
        timeline = chart_data.get("complianceTimeline", [])
        if timeline:
            summary_parts.append(f"Compliance Timeline (12 months): {json.dumps(timeline)}")

        # Enforcement / Flag breakdown (aggregate totals across all barangays)
        enforcement = chart_data.get("enforcement", [])
        if enforcement:
            total_green = sum(b.get("green_count", 0) for b in enforcement)
            total_red = sum(b.get("red_count", 0) for b in enforcement)
            total_yellow = sum(b.get("yellow_count", 0) for b in enforcement)
            total_black = sum(b.get("black_count", 0) for b in enforcement)
            total_orange = sum(b.get("orange_count", 0) for b in enforcement)
            flag_summary = {
                "green_flags": total_green,
                "yellow_flags": total_yellow,
                "red_flags": total_red,
                "black_flags": total_black,
                "orange_flags": total_orange,
                "total_non_green_flags": total_red + total_yellow + total_black + total_orange
            }
            summary_parts.append(f"Flag Color Breakdown (system-wide totals): {json.dumps(flag_summary)}")
            # Also include top flagged barangays
            flagged_barangays = [b for b in enforcement if (b.get("red_count", 0) + b.get("yellow_count", 0) + b.get("black_count", 0) + b.get("orange_count", 0)) > 0]
            if flagged_barangays:
                flagged_barangays.sort(key=lambda x: x.get("red_count", 0) + x.get("yellow_count", 0) + x.get("black_count", 0) + x.get("orange_count", 0), reverse=True)
                summary_parts.append(f"Barangays with non-green flags: {json.dumps(flagged_barangays[:10])}")

        # Audit summary
        audit = chart_data.get("audit", {})
        if audit:
            summary_parts.append(f"Inspection/Audit Summary: {json.dumps(audit)}")

        # Barangay risk data (diagnostic) – top 10
        brgy_risk = chart_data.get("barangayRisk", [])
        if brgy_risk:
            summary_parts.append(f"Top Barangay Risk Data: {json.dumps(brgy_risk[:10])}")

        # Category noncompliance (diagnostic)
        cat_noncomp = chart_data.get("categoryNoncompliance", [])
        if cat_noncomp:
            summary_parts.append(f"Category Noncompliance: {json.dumps(cat_noncomp)}")

        # Flag trend (diagnostic)
        flag_trend = chart_data.get("flagTrend", [])
        if flag_trend:
            summary_parts.append(f"Flag Trend: {json.dumps(flag_trend)}")

        # ── PRESCRIPTIVE TIER ──

        # OPS/WLC Rankings (sorted by ops_score descending)
        ops_rankings = chart_data.get("opsRankings", [])
        if ops_rankings:
            # Include key fields only to keep concise
            slim_rankings = [{
                "rank": r.get("rank"),
                "barangay": r.get("barangayName"),
                "ops_score": r.get("ops_score"),
                "risk_score": r.get("risk_score"),
                "sector_score": r.get("sector_score"),
                "distance_score": r.get("distance_score"),
                "risk_level": r.get("risk_level"),
                "flagged_count": r.get("flagged_count"),
                "non_compliance_rate": r.get("non_compliance_rate"),
            } for r in ops_rankings]
            summary_parts.append(f"OPS Priority Rankings (WLC-based, all barangays): {json.dumps(slim_rankings)}")

        # WLC Config (weights)
        wlc_config = chart_data.get("wlcConfig", {})
        if wlc_config:
            summary_parts.append(f"WLC Weight Configuration: {json.dumps(wlc_config)}")

        # Dispatch Recommendations
        dispatch = chart_data.get("dispatchRecommendations", [])
        if dispatch:
            summary_parts.append(f"Dispatch Recommendations: {json.dumps(dispatch[:10])}")

        # ── OPERATIONS TIER ──

        # Inspector stats
        inspector_stats = chart_data.get("inspectorStats", [])
        if inspector_stats:
            summary_parts.append(
                f"Inspector Performance Stats (this list includes ALL active "
                f"inspectors — entries with zero assigned tasks are idle, not "
                f"missing): {json.dumps(inspector_stats)}"
            )
            summary_parts.append(
                f"Total active inspectors: {len(inspector_stats)}"
            )

        # Status breakdown
        status_breakdown = chart_data.get("statusBreakdown", [])
        if status_breakdown:
            summary_parts.append(f"Inspection Status Breakdown: {json.dumps(status_breakdown)}")

        # Inspection timeline
        insp_timeline = chart_data.get("inspectionTimeline", [])
        if insp_timeline:
            summary_parts.append(f"Inspection Timeline (monthly): {json.dumps(insp_timeline)}")

        data_context = "\n".join(summary_parts) if summary_parts else "No data available."

        system_message = (
            "You are the REVELA AI Analyst — the built-in analytics assistant for REVELA.\n\n"

            "## About REVELA\n"
            "REVELA is a Geospatial Business Intelligence System for Compliance Monitoring and Non-Registered Business Detection. "
            "It is a web-based platform used by the Business Permits and Licensing Office (BPLO) of a "
            "local government unit (municipality) in the Philippines (Mataansnakahoy, Batangas). It digitizes the management of "
            "business permits, regulatory compliance, and enforcement operations.\n\n"

            "## Key Domain Concepts\n"
            "- **Official Registry**: The master list of all businesses registered in the municipality. "
            "Each business has an application status: Active (permit is current), Expired (permit lapsed and was not renewed), "
            "Closed (business voluntarily closed), Revoked (permit was revoked by the LGU), or Pending (application is being processed).\n"
            "- **Barangays**: The smallest administrative division in the Philippines. Businesses are grouped by barangay.\n"
            "- **Business Size**: Classified as Micro, Small, Medium, or Large based on asset size per Philippine DTI standards.\n"
            "- **Lines of Business**: The industry or trade a business operates in (e.g., 'Retail selling', 'Renting or leasing').\n"
            "- **Flag System**: Businesses can be flagged with color-coded flags during inspections or reviews:\n"
            "  - Green = Fully compliant\n"
            "  - Yellow = Suspected of being unregistered, needs attention\n"
            "  - Red = Serious violations, requires enforcement action\n"
            "  - Black = Critical / ordered to cease operations\n"
            "  - Orange = Under investigation or special monitoring\n"
            "  - Purple = Confirmed closed or permanently abandoned establishment\n"
            "- **Compliance Rate**: Percentage of businesses with Active status out of total registered.\n"
            "- **Inspections**: Field inspections conducted by municipal inspectors. A business may have zero inspections "
            "if it has not yet been scheduled — this is normal, especially for newly registered businesses or if the "
            "inspection program is still being rolled out.\n"
            "- **Compliance by Size**: Shows how many Active vs Non-Active businesses exist per size category. "
            "'Non-Active' includes Expired, Closed, and Pending — it does NOT necessarily mean the business is violating rules, unless the status is Revoked (which means the business is a notorious offender).\n"
            "- **Compliance Timeline**: Monthly trend of active vs non-active business counts over the past 12 months.\n"
            "- **Barangay Risk**: Diagnostic data showing which barangays have the highest concentration of non-compliant businesses.\n"
            "- **Category Noncompliance**: Which business categories (lines of business) have the most non-compliant entries.\n"
            "- **Flag Trend**: Weekly trend of new flags raised.\n"
            "- **OPS Score (Operational Priority Score)**: A composite score (0-100) computed using WLC (Weighted Linear Combination) "
            "that ranks barangays by inspection priority. Higher score = higher priority for dispatching inspectors.\n"
            "- **WLC Weights**: The OPS score is computed from three weighted sub-scores:\n"
            "  - Risk Score (w1): Based on the severity and count of flags (red, yellow, black) in the barangay\n"
            "  - Sector Score (w2): Based on the risk profile of the dominant business sectors in the barangay\n"
            "  - Distance Score (w3): Based on proximity to the BPLO office (closer = easier to dispatch)\n"
            "- **Risk Level**: Derived from OPS score — High (>=60), Medium (>=30), Low (<30)\n"
            "- **Dispatch Recommendations**: AI-generated suggestions for which barangays to prioritize for inspector dispatch, based on OPS rankings.\n"
            "- **Inspector Stats**: Performance metrics for individual inspectors (inspections completed, resolution time, etc.).\n"
            "- **Inspection Status Breakdown**: Distribution of inspection statuses (Pending, In Progress, Completed, etc.).\n\n"

            "## Important Guidelines\n"
            "- Do NOT flag zero inspections as an anomaly — inspections are conducted on a rolling schedule and many businesses may not have been inspected yet.\n"
            "- 'Non-Active' in compliance charts means the business status is not 'Active' — it includes Expired, Closed, and Pending. Do not confuse this with violations unless the status is Revoked (which means the business is a notorious offender).\n"
            "- ALWAYS respect the numerical 'rank' exactly as provided in the OPS Priority Rankings and Dispatch Recommendations. Do NOT re-order barangays yourself (e.g. do not promote a lower-ranked barangay above a higher-ranked one just because of flag colors). Follow the exact WLC-computed ranking order.\n"
            "- When discussing compliance, frame it in terms of permit renewal and regulatory status, not moral judgments.\n"
            "- Be helpful to BPLO staff — suggest actionable next steps like 'consider prioritizing inspections in Barangay X' or 'the high proportion of Micro businesses suggests focusing outreach on small enterprise compliance'.\n"
            "- Use Filipino-friendly language when appropriate (e.g., barangay, BPLO).\n\n" 
 
            "## Dashboard Data\n"
            f"{data_context}\n\n"
            "Answer questions concisely, professionally, and accurately based ONLY on this data. "
            "Use specific numbers to support your answers. "
            "If asked about trends or insights, provide actionable recommendations relevant to BPLO operations."
        )
    else:
        # Single chart mode (legacy)
        system_message = (
            f"You are the REVELAsys Analytics AI Assistant. "
            f"You help users understand their business registry and enforcement data. "
            f"The user is asking about the '{chart_id}' chart. "
            f"Here is the JSON data for this chart: {chart_data}. "
            f"Answer their questions concisely, professionally, and accurately based ONLY on this data."
        )

    try:
        contents = []
        for msg in messages:
            role = "user" if msg.get("role") == "user" else "model"
            content_text = msg.get("content", "")
            if content_text:
                contents.append(types.Content(
                    role=role,
                    parts=[types.Part.from_text(text=content_text)]
                ))
        
        contents.append(types.Content(
            role="user",
            parts=[types.Part.from_text(text=user_query)]
        ))

        preferred_model = os.environ.get("GEMINI_MODEL")
        models_to_try = [preferred_model] if preferred_model else []

        # 1. Discover available models from the Gemini API directly for this key
        try:
            for m in client.models.list():
                m_name = (m.name or "").replace("models/", "").strip()
                actions = getattr(m, "supported_actions", None) or []
                if "generateContent" in actions or not actions:
                    if m_name and m_name not in models_to_try:
                        if "flash" in m_name:
                            models_to_try.insert(1 if preferred_model else 0, m_name)
                        elif "gemini" in m_name:
                            models_to_try.append(m_name)
        except Exception as le:
            print(f"[Gemini] Note on model discovery: {le}")

        # 2. Add standard candidate fallbacks
        for f in ["gemini-3.6-flash", "gemini-2.5-flash", "gemini-2.0-flash", "gemini-1.5-flash", "gemini-1.5-pro"]:
            if f not in models_to_try:
                models_to_try.append(f)

        print(f"[Gemini] Candidate models: {models_to_try}")

        response = None
        last_error = None
        for m in models_to_try:
            try:
                response = client.models.generate_content(
                    model=m,
                    contents=contents,
                    config=types.GenerateContentConfig(
                        system_instruction=system_message,
                        temperature=0.4,
                        max_output_tokens=1024,
                    )
                )
                if response and response.text:
                    print(f"[Gemini] Succeeded with model '{m}'")
                    break
            except Exception as me:
                print(f"[Gemini] Failed with model '{m}': {me}")
                last_error = me
                continue

        if not response or not response.text:
            raise last_error or Exception("No response returned by the Gemini AI model.")

        return jsonify({
            "response": response.text
        }), 200
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": f"AI Assistant Error: {str(e)}"}), 500

