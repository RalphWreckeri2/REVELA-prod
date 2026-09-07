import os
import json
import csv
import io
import re
import tempfile
import zipfile
from datetime import datetime, timedelta

from app import mysql



# ── Inspector task list ───────────────────────────────────────────────────────

def _as_user_id(user_id):
    """JWT identity is stored as string; DB column is numeric."""
    try:
        return int(user_id)
    except (TypeError, ValueError):
        return user_id


def get_inspector_tasks(user_id):
    """
    Return all inspection reports assigned to this inspector
    where verificationStatus is 'Assigned' or 'Reassigned'.
    Joins geospatial_logs for flag details and barangays for name.
    """
    try:
        uid = _as_user_id(user_id)
        cursor = mysql.connection.cursor()
        cursor.execute("""
            SELECT
                ir.reportID,
                ir.userID,
                ir.targetID          AS logID,
                ir.inspectionResult,
                ir.verificationStatus,
                ir.wasReassigned,
                ir.remarks,
                ir.photoPath,
                ir.irTimestamp,
                ir.deadline,
                ir.nearestLandmark,
                g.detectedName,
                g.flagColor,
                g.noticeLevel        AS currentNoticeLevel,
                g.latitude,
                g.longitude,
                b.barangayName
            FROM inspection_reports ir
            JOIN geospatial_logs g  ON ir.targetID   = g.logID
            LEFT JOIN barangays b   ON g.barangayID  = b.barangayID
            WHERE ir.userID = %s
              AND ir.verificationStatus IN ('Assigned', 'Reassigned')
            ORDER BY ir.irTimestamp DESC
        """, (uid,))
        rows = cursor.fetchall()
        cursor.close()

        for row in rows:
            if row.get("irTimestamp"):
                row["irTimestamp"] = str(row["irTimestamp"])
            if row.get("deadline"):
                row["deadline"] = str(row["deadline"])

        return {"data": rows, "total": len(rows)}, None

    except Exception as e:
        return None, str(e)


def get_inspector_reports_history(user_id):
    """
    All inspection reports for this inspector (any status), newest first.
    Used by the mobile app history tab.
    """
    try:
        uid = _as_user_id(user_id)
        cursor = mysql.connection.cursor()
        cursor.execute("""
            SELECT
                ir.reportID,
                ir.userID,
                ir.targetID          AS logID,
                ir.inspectionResult,
                ir.verificationStatus,
                ir.wasReassigned,
                ir.remarks,
                ir.photoPath,
                ir.irTimestamp,
                ir.deadline,
                ir.nearestLandmark,
                g.detectedName,
                g.flagColor,
                g.noticeLevel        AS currentNoticeLevel,
                g.latitude,
                g.longitude,
                b.barangayName
            FROM inspection_reports ir
            JOIN geospatial_logs g  ON ir.targetID   = g.logID
            LEFT JOIN barangays b   ON g.barangayID  = b.barangayID
            WHERE ir.userID = %s
            ORDER BY ir.irTimestamp DESC
            LIMIT 200
        """, (uid,))
        rows = cursor.fetchall()
        cursor.close()

        for row in rows:
            if row.get("irTimestamp"):
                row["irTimestamp"] = str(row["irTimestamp"])
            if row.get("deadline"):
                row["deadline"] = str(row["deadline"])

        return {"data": rows, "total": len(rows)}, None

    except Exception as e:
        return None, str(e)


# ── Assign inspection ─────────────────────────────────────────────────────────

def assign_inspection(log_id, inspector_user_id, deadline, assigned_by):
    """
    Create an INSPECTION_REPORTS row linking a geospatial log to an inspector.
    targetType is always 'geospatial_log' since we're dispatching from the flag map.
    Prevents duplicate open assignments for the same logID.
    """
    try:
        cursor = mysql.connection.cursor()

        # Guard: check the log exists
        cursor.execute(
            "SELECT logID, flagColor FROM geospatial_logs WHERE logID = %s",
            (log_id,)
        )
        flag = cursor.fetchone()
        if not flag:
            cursor.close()
            return None, f"Flag #{log_id} not found"

        # Guard: inspector user exists and has Inspector role
        cursor.execute(
            "SELECT userID, fullName, userRole FROM users WHERE userID = %s AND userRole = 'Inspector'",
            (inspector_user_id,)
        )
        inspector = cursor.fetchone()
        if not inspector:
            cursor.close()
            return None, f"Inspector userID {inspector_user_id} not found"

        # Check if ANY report already exists for this flag (any status).
        # Re-dispatching reuses the existing row so the count stays correct.
        cursor.execute("""
            SELECT reportID, verificationStatus FROM inspection_reports
            WHERE targetID = %s
            ORDER BY reportID DESC
            LIMIT 1
        """, (log_id,))
        existing = cursor.fetchone()

        if existing and existing["verificationStatus"] in ('Assigned', 'Reassigned', 'In Progress'):
            cursor.close()
            return None, "This business is already undergoing inspection and cannot be double-booked."


        # First-ever dispatch → 'Assigned'. Any existing report means the
        # admin is RE-dispatching, so it lands in 'Reassigned'.
        is_reassign = existing is not None
        new_status = 'Reassigned' if is_reassign else 'Assigned'

        if existing:
            # Update the existing row — clear previous submission data
            # when re-dispatching a Submitted/Verified task
            cursor.execute("""
                UPDATE inspection_reports
                SET userID = %s,
                    verificationStatus = %s,
                    wasReassigned = 1,
                    deadline = %s,
                    inspectionResult = NULL,
                    remarks = NULL,
                    photoPath = NULL,
                    resolutionTime = NULL,
                    nearestLandmark = NULL,
                    irTimestamp = NOW()
                WHERE reportID = %s
            """, (inspector_user_id, new_status, deadline, existing["reportID"]))
            report_id = existing["reportID"]
        else:
            cursor.execute("""
                INSERT INTO inspection_reports
                    (userID, targetID, targetType, verificationStatus, deadline)
                VALUES (%s, %s, 'geospatial_log', %s, %s)
            """, (inspector_user_id, log_id, new_status, deadline))
            report_id = cursor.lastrowid

        mysql.connection.commit()
        cursor.close()

        try:
            from api.notifications import hub
            hub.publish_to_admins({
                "type": "inspection_updated",
                "reportID": report_id,
                "logID": log_id,
                "inspectorID": inspector_user_id,
                "inspector": inspector["fullName"],
                "status": new_status,
            })
        except Exception:
            pass

        return {
            "reportID":   report_id,
            "logID":      log_id,
            "inspectorID": inspector_user_id,
            "inspector":  inspector["fullName"],
            "status":     new_status,
        }, None

    except Exception as e:
        return None, str(e)


# ── Submit inspection ─────────────────────────────────────────────────────────

def submit_inspection(log_id, user_id, inspection_result,
                      notice_level=0,
                      verified_lat=None, verified_lng=None,
                      notes=None, photo_url=None):
    """
    Inspector submits their field report for a given logID.
    Updates the existing Assigned report row to 'Submitted'.
    verifiedLat/Lng stored in nearestLandmark as JSON-ish string for now
    (extend schema if you add dedicated columns later).
    """
    try:
        cursor = mysql.connection.cursor()

        # Find the open assignment for this inspector + log
        uid = _as_user_id(user_id)
        cursor.execute("""
            SELECT reportID, irTimestamp FROM inspection_reports
            WHERE targetID = %s
              AND userID   = %s
              AND verificationStatus IN ('Assigned', 'Reassigned')
            LIMIT 1
        """, (log_id, uid))
        report = cursor.fetchone()

        if not report:
            cursor.close()
            return None, "No open assignment found for this flag and inspector"

        # Calculate resolution time in minutes
        cursor.execute("""
            SELECT TIMESTAMPDIFF(MINUTE, irTimestamp, NOW()) AS mins
            FROM inspection_reports WHERE reportID = %s
        """, (report["reportID"],))
        timing = cursor.fetchone()
        resolution_mins = timing["mins"] if timing else None

        # Build a coords string for nearestLandmark if coords provided
        landmark = None
        if verified_lat and verified_lng:
            landmark = f"{verified_lat},{verified_lng}"

        cursor.execute("""
            UPDATE inspection_reports
            SET inspectionResult    = %s,
                noticeLevel         = %s,
                verificationStatus  = 'Submitted',
                remarks             = %s,
                photoPath           = %s,
                nearestLandmark     = COALESCE(%s, nearestLandmark),
                resolutionTime      = %s
            WHERE reportID = %s
        """, (
            inspection_result,
            notice_level,
            notes,
            photo_url,
            landmark,
            resolution_mins,
            report["reportID"],
        ))

        # Retrieve the current flagColor to return in the backend payload
        cursor.execute("SELECT flagColor FROM geospatial_logs WHERE logID = %s", (log_id,))
        geo_log = cursor.fetchone()
        flag_color = geo_log["flagColor"] if geo_log else "Red"

        mysql.connection.commit()
        cursor.close()

        try:
            from api.notifications import hub
            hub.publish_to_admins({
                "type": "inspection_submitted",
                "reportID": report["reportID"],
                "logID": log_id,
                "inspectionResult": inspection_result,
                "status": "Submitted",
            })
        except Exception:
            pass

        return {
            "reportID":         report["reportID"],
            "inspectionResult": inspection_result,
            "status":           "Submitted",
            "resolutionMins":   resolution_mins,
            "flagColor":        flag_color,
        }, None

    except Exception as e:
        return None, str(e)


# ── Reassign submitted (redo) ─────────────────────────────────────────────────

def reassign_submitted_report(report_id, inspector_user_id, deadline, assigned_by):
    """
    Admin sends a submitted report back to the field for redo.
    Clears submission data and sets verificationStatus to Reassigned.
    """
    try:
        cursor = mysql.connection.cursor()

        cursor.execute(
            """
            SELECT reportID, targetID, verificationStatus
            FROM inspection_reports
            WHERE reportID = %s
            """,
            (report_id,),
        )
        report = cursor.fetchone()
        if not report:
            cursor.close()
            return None, f"Report #{report_id} not found"

        if report["verificationStatus"] not in ("Submitted", "Verified"):
            cursor.close()
            return None, (
                f"Report is '{report['verificationStatus']}' — "
                "only Submitted or Verified reports can be sent back for redo"
            )


        cursor.execute(
            """
            SELECT userID, fullName, userRole FROM users
            WHERE userID = %s AND userRole = 'Inspector'
            """,
            (inspector_user_id,),
        )
        inspector = cursor.fetchone()
        if not inspector:
            cursor.close()
            return None, f"Inspector userID {inspector_user_id} not found"

        cursor.execute(
            """
            UPDATE inspection_reports
            SET userID = %s,
                verificationStatus = 'Reassigned',
                wasReassigned = 1,
                inspectionResult = NULL,
                remarks = NULL,
                photoPath = NULL,
                resolutionTime = NULL,
                nearestLandmark = NULL,
                deadline = %s,
                irTimestamp = NOW()
            WHERE reportID = %s
            """,
            (inspector_user_id, deadline, report_id),
        )

        mysql.connection.commit()
        cursor.close()

        try:
            from api.notifications import hub
            hub.publish_to_admins({
                "type": "inspection_updated",
                "reportID": report_id,
                "logID": report["targetID"],
                "inspectorID": inspector_user_id,
                "inspector": inspector["fullName"],
                "status": "Reassigned",
            })
        except Exception:
            pass

        return {
            "reportID": report_id,
            "logID": report["targetID"],
            "inspectorID": inspector_user_id,
            "inspector": inspector["fullName"],
            "status": "Reassigned",
        }, None

    except Exception as e:
        return None, str(e)


# ── Verify inspection ─────────────────────────────────────────────────────────

def verify_inspection(report_id):
    """
    Admin confirms the inspection result.
    1. Set verificationStatus → 'Verified'
    2. Update geospatial_logs.flagColor to match inspectionResult
    """
    try:
        cursor = mysql.connection.cursor()

        cursor.execute("""
            SELECT reportID, targetID, inspectionResult, noticeLevel, verificationStatus
            FROM inspection_reports
            WHERE reportID = %s
        """, (report_id,))
        report = cursor.fetchone()

        if not report:
            cursor.close()
            return None, f"Report #{report_id} not found"

        if report["verificationStatus"] != "Submitted":
            cursor.close()
            return None, f"Report is '{report['verificationStatus']}' — only Submitted reports can be verified"

        if not report["inspectionResult"]:
            cursor.close()
            return None, "Report has no inspection result to verify"

        # Update report status
        cursor.execute("""
            UPDATE inspection_reports
            SET verificationStatus = 'Verified'
            WHERE reportID = %s
        """, (report_id,))

        # Propagate result → geospatial_logs
        cursor.execute("""
            UPDATE geospatial_logs
            SET flagColor = %s,
                noticeLevel = %s
            WHERE logID = %s
        """, (report["inspectionResult"], report["noticeLevel"], report["targetID"]))

        # If verified result is Purple (Closed / Abandoned),
        # also mark the official_registry entry as 'Closed'.
        if report["inspectionResult"] == "Purple":
            cursor.execute("SELECT detectedName, barangayID FROM geospatial_logs WHERE logID = %s", (report["targetID"],))
            geo_row = cursor.fetchone()
            if geo_row and geo_row["detectedName"]:
                cursor.execute("""
                    UPDATE official_registry
                    SET applicationStatus = 'Closed'
                    WHERE LOWER(businessName) = LOWER(%s) AND barangayID = %s
                """, (geo_row["detectedName"], geo_row["barangayID"]))

        mysql.connection.commit()
        cursor.close()

        try:
            from api.notifications import hub
            hub.publish_to_admins({
                "type": "inspection_updated",
                "reportID": report_id,
                "logID": report["targetID"],
                "status": "Verified",
                "newFlagColor": report["inspectionResult"],
            })
        except Exception:
            pass

        return {
            "reportID":         report_id,
            "logID":            report["targetID"],
            "newFlagColor":     report["inspectionResult"],
            "status":           "Verified",
        }, None

    except Exception as e:
        return None, str(e)


# ── Get all inspections (admin) ───────────────────────────────────────────────

def get_all_inspections(status=None, barangay_id=None, page=1, per_page=20):
    """
    Admin view: paginated inspection reports with flag + inspector details.
    Filterable by verificationStatus and barangayID.
    """
    try:
        cursor = mysql.connection.cursor()

        conditions = []
        params = []

        if status:
            conditions.append("ir.verificationStatus = %s")
            params.append(status)

        if barangay_id:
            conditions.append("g.barangayID = %s")
            params.append(barangay_id)

        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
        offset = (page - 1) * per_page

        cursor.execute(
            f"""
            SELECT COUNT(*) AS total
            FROM inspection_reports ir
            JOIN (
                SELECT targetID, MAX(reportID) AS maxReportID
                FROM inspection_reports
                GROUP BY targetID
            ) latest_ir ON ir.reportID = latest_ir.maxReportID
            JOIN geospatial_logs g ON ir.targetID = g.logID
            {where}
            """,
            params,
        )
        total = cursor.fetchone()["total"]

        cursor.execute(
            f"""
            SELECT
                ir.reportID,
                ir.targetID          AS logID,
                ir.inspectionResult,
                ir.verificationStatus,
                ir.wasReassigned,
                ir.noticeLevel,
                ir.remarks,
                ir.photoPath,
                ir.irTimestamp,
                ir.deadline,
                ir.resolutionTime,
                ir.nearestLandmark,
                g.detectedName,
                g.flagColor,
                g.latitude,
                g.longitude,
                b.barangayName,
                u.fullName           AS inspectorName,
                u.userID             AS inspectorID
            FROM inspection_reports ir
            JOIN (
                SELECT targetID, MAX(reportID) AS maxReportID
                FROM inspection_reports
                GROUP BY targetID
            ) latest_ir ON ir.reportID = latest_ir.maxReportID
            JOIN geospatial_logs g  ON ir.targetID  = g.logID
            LEFT JOIN barangays b   ON g.barangayID = b.barangayID
            LEFT JOIN users u       ON ir.userID    = u.userID
            {where}
            ORDER BY ir.irTimestamp DESC
            LIMIT %s OFFSET %s
            """,
            params + [per_page, offset],
        )
        rows = cursor.fetchall()

        # Count ALL report rows (no latest-per-target collapse) so the UI can
        # disclose how many older revisions are grouped under newer reports.
        cursor.execute(
            f"""
            SELECT COUNT(*) AS total
            FROM inspection_reports ir
            JOIN geospatial_logs g ON ir.targetID = g.logID
            {where}
            """,
            params,
        )
        total_rows = cursor.fetchone()["total"]

        cursor.close()

        for row in rows:
            if row.get("irTimestamp"):
                row["irTimestamp"] = str(row["irTimestamp"])
            if row.get("deadline"):
                row["deadline"] = str(row["deadline"])

        return {
            "data":       rows,
            "total":      total,
            "total_rows": total_rows,
            "page":       page,
            "per_page":   per_page,
            "pages":      max(1, -(-total // per_page)),
        }, None

    except Exception as e:
        return None, str(e)


# ── Evidence Archival & Storage Cleanup ───────────────────────────────────────

def _extract_photo_filenames(photo_path_val):
    """
    Takes photoPath from DB (which can be a JSON string array or a single string)
    and returns a list of active photo filenames/paths that are NOT archived://.
    """
    if not photo_path_val:
        return []
    items = []
    if isinstance(photo_path_val, list):
        items = photo_path_val
    else:
        try:
            parsed = json.loads(photo_path_val)
            if isinstance(parsed, list):
                items = parsed
            else:
                items = [parsed]
        except Exception:
            items = [photo_path_val]

    result = []
    for item in items:
        if not item or not isinstance(item, str):
            continue
        item_str = item.strip()
        if item_str.startswith("archived://"):
            continue
        result.append(item_str)
    return result


def get_evidence_storage_stats(evidence_dir):
    """
    Scans the evidence directory and queries MySQL to compute:
    - Total files and total MB currently on server disk.
    - Counts and estimated storage for verified reports by age bracket:
      * older_365d: > 1 year
      * older_180d: > 6 months
      * older_90d:  > 90 days
      * older_30d:  > 30 days
      * all_verified: all verified reports with active evidence
    """
    try:
        # 1. Scan evidence directory
        total_files = 0
        total_bytes = 0
        file_sizes = {}
        if os.path.exists(evidence_dir):
            for entry in os.scandir(evidence_dir):
                if entry.is_file():
                    total_files += 1
                    try:
                        sz = entry.stat().st_size
                        total_bytes += sz
                        file_sizes[entry.name.lower()] = sz
                    except OSError:
                        pass

        total_mb = round(total_bytes / (1024 * 1024), 2)
        avg_file_size = (total_bytes / total_files) if total_files > 0 else (1.2 * 1024 * 1024)

        # 2. Query MySQL for verified reports with active photos
        cursor = mysql.connection.cursor()
        cursor.execute("""
            SELECT
                ir.reportID,
                ir.irTimestamp,
                ir.photoPath
            FROM inspection_reports ir
            WHERE ir.verificationStatus = 'Verified'
              AND ir.photoPath IS NOT NULL
              AND ir.photoPath != ''
              AND ir.photoPath NOT LIKE 'archived://%%'
              AND ir.photoPath NOT LIKE '[\"archived://%%'
        """)
        reports = cursor.fetchall()
        cursor.close()

        now = datetime.now()
        categories = {
            "older_365d": {"label": "Older than 1 year (>365 days)", "days": 365, "reports": 0, "photos": 0, "sizeBytes": 0},
            "older_180d": {"label": "Older than 6 months (>180 days)", "days": 180, "reports": 0, "photos": 0, "sizeBytes": 0},
            "older_90d":  {"label": "Older than 3 months (>90 days)",  "days": 90,  "reports": 0, "photos": 0, "sizeBytes": 0},
            "older_30d":  {"label": "Older than 30 days",             "days": 30,  "reports": 0, "photos": 0, "sizeBytes": 0},
            "all_verified": {"label": "All verified inspections",     "days": 0,   "reports": 0, "photos": 0, "sizeBytes": 0},
        }

        for rep in reports:
            ts = rep.get("irTimestamp")
            if not ts:
                continue
            if isinstance(ts, str):
                try:
                    ts = datetime.fromisoformat(ts.replace("Z", ""))
                except Exception:
                    continue
            age_days = (now - ts).days

            photos = _extract_photo_filenames(rep.get("photoPath"))
            if not photos:
                continue

            rep_bytes = 0
            for p in photos:
                fn = os.path.basename(p).lower()
                rep_bytes += file_sizes.get(fn, avg_file_size)

            num_photos = len(photos)

            for key, cat in categories.items():
                if cat["days"] == 0 or age_days >= cat["days"]:
                    cat["reports"] += 1
                    cat["photos"] += num_photos
                    cat["sizeBytes"] += rep_bytes

        formatted_categories = {}
        for k, cat in categories.items():
            formatted_categories[k] = {
                "label": cat["label"],
                "reportCount": cat["reports"],
                "photoCount": cat["photos"],
                "estimatedMB": round(cat["sizeBytes"] / (1024 * 1024), 2),
            }

        return {
            "totalFilesOnDisk": total_files,
            "totalDiskBytes": total_bytes,
            "totalDiskMB": total_mb,
            "categories": formatted_categories,
        }, None

    except Exception as e:
        return None, str(e)


def generate_evidence_archive_zip(evidence_dir, filter_type):
    """
    Queries verified reports matching filter_type.
    Gathers physical photo files and compiles an audit manifest.csv into a ZIP archive.
    Returns:
      (temp_zip_path, download_filename, stats_dict), None
      or None, error_message
    """
    try:
        day_map = {
            "older_365d": 365,
            "older_180d": 180,
            "older_90d": 90,
            "older_30d": 30,
            "all_verified": 0,
        }
        if filter_type not in day_map:
            return None, f"Invalid filter type: {filter_type}. Must be one of {list(day_map.keys())}"

        days = day_map[filter_type]
        cutoff_date = (datetime.now() - timedelta(days=days)) if days > 0 else None

        cursor = mysql.connection.cursor()
        query = """
            SELECT
                ir.reportID,
                ir.targetID AS logID,
                ir.inspectionResult,
                ir.noticeLevel,
                ir.verificationStatus,
                ir.remarks,
                ir.photoPath,
                ir.irTimestamp,
                ir.deadline,
                ir.resolutionTime,
                ir.nearestLandmark,
                g.detectedName,
                g.latitude,
                g.longitude,
                b.barangayName,
                u.fullName AS inspectorName
            FROM inspection_reports ir
            JOIN geospatial_logs g ON ir.targetID = g.logID
            LEFT JOIN barangays b ON g.barangayID = b.barangayID
            LEFT JOIN users u ON ir.userID = u.userID
            WHERE ir.verificationStatus = 'Verified'
              AND ir.photoPath IS NOT NULL
              AND ir.photoPath != ''
              AND ir.photoPath NOT LIKE 'archived://%%'
              AND ir.photoPath NOT LIKE '[\"archived://%%'
        """
        params = []
        if cutoff_date:
            query += " AND ir.irTimestamp <= %s"
            params.append(cutoff_date.strftime("%Y-%m-%d %H:%M:%S"))

        query += " ORDER BY ir.irTimestamp ASC"

        cursor.execute(query, tuple(params))
        reports = cursor.fetchall()
        cursor.close()

        if not reports:
            return None, "No verified inspection reports found matching the specified age filter."

        temp_zip = tempfile.NamedTemporaryFile(delete=False, suffix=".zip")
        temp_zip_path = temp_zip.name
        temp_zip.close()

        timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        download_filename = f"REVELA_Evidence_Archive_{filter_type}_{timestamp_str}.zip"

        manifest_stream = io.StringIO()
        csv_writer = csv.writer(manifest_stream)
        csv_writer.writerow([
            "Report ID",
            "Log ID",
            "Business Name",
            "Barangay",
            "Inspector Name",
            "Inspection Result",
            "Notice Level",
            "Inspection Date",
            "Deadline",
            "Resolution Time (mins)",
            "Latitude",
            "Longitude",
            "Nearest Landmark",
            "Inspector Remarks",
            "Original Filename",
            "Archive Filename",
            "Photo Status",
        ])

        archived_photos_count = 0
        archived_reports_count = 0
        total_uncompressed_bytes = 0

        with zipfile.ZipFile(temp_zip_path, "w", zipfile.ZIP_DEFLATED) as zip_file:
            for rep in reports:
                rep_id = rep.get("reportID")
                log_id = rep.get("logID") or rep.get("targetID") or ""
                b_name = rep.get("detectedName") or "Unknown_Business"
                clean_name = (re.sub(r"[^\w\-_]", "_", b_name)[:30]).strip("_") or "Business"
                barangay = rep.get("barangayName") or "Mataasnakahoy"
                inspector = rep.get("inspectorName") or "Inspector"
                result_color = rep.get("inspectionResult") or "Verified"
                notice_lvl = rep.get("noticeLevel") if rep.get("noticeLevel") is not None else 0
                remarks = rep.get("remarks") or ""
                ir_ts = str(rep.get("irTimestamp") or "")
                deadline_val = str(rep.get("deadline") or "")
                res_time = rep.get("resolutionTime") if rep.get("resolutionTime") is not None else ""
                lat_val = str(rep.get("latitude") or "")
                lng_val = str(rep.get("longitude") or "")
                landmark = rep.get("nearestLandmark") or ""
                date_str = ir_ts[:10].replace("-", "") or "unknown_date"

                photos = _extract_photo_filenames(rep.get("photoPath"))
                if not photos:
                    continue

                rep_had_photo = False
                for idx, p in enumerate(photos):
                    orig_filename = os.path.basename(p)
                    local_filepath = os.path.join(evidence_dir, orig_filename)

                    ext = os.path.splitext(orig_filename)[1].lower()
                    if ext not in (".jpg", ".jpeg", ".png", ".webp"):
                        ext = ".jpg"
                    archive_arcname = f"evidence/Report_{rep_id}_{clean_name}_{date_str}_{idx+1}{ext}"

                    if os.path.isfile(local_filepath):
                        zip_file.write(local_filepath, arcname=archive_arcname)
                        file_sz = os.path.getsize(local_filepath)
                        total_uncompressed_bytes += file_sz
                        archived_photos_count += 1
                        rep_had_photo = True

                        csv_writer.writerow([
                            rep_id,
                            log_id,
                            b_name,
                            barangay,
                            inspector,
                            result_color,
                            notice_lvl,
                            ir_ts,
                            deadline_val,
                            res_time,
                            lat_val,
                            lng_val,
                            landmark,
                            remarks,
                            orig_filename,
                            archive_arcname,
                            "Archived in ZIP",
                        ])
                    else:
                        csv_writer.writerow([
                            rep_id,
                            log_id,
                            b_name,
                            barangay,
                            inspector,
                            result_color,
                            notice_lvl,
                            ir_ts,
                            deadline_val,
                            res_time,
                            lat_val,
                            lng_val,
                            landmark,
                            remarks,
                            orig_filename,
                            "[FILE NOT ON DISK]",
                            "Missing on Server Disk (Container Restarted)",
                        ])

                if rep_had_photo:
                    archived_reports_count += 1

            # Summary text file included in every archive
            readme_text = f"""========================================================================
MUNICIPALITY OF MATAASNAKAHOY - BUSINESS PERMIT & LICENSING OFFICE (BPLO)
REVELA INSPECTION ARCHIVE & AUDIT PACKAGE
========================================================================
Archive Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
Filter Type: {filter_type}
Verified Reports Matched: {len(reports)}
Physical Photos Archived in Package: {archived_photos_count}

PACKAGE CONTENTS:
1. manifest.csv:
   Complete audit manifest spreadsheet containing:
   - Report ID & Log ID
   - Business Name & Barangay
   - Inspector Name (who conducted the inspection)
   - Inspection Result (Color flag) & Notice Level
   - Inspection Timestamps, Deadlines & Resolution Times
   - GPS Latitude & Longitude & Landmarks
   - Inspector Notes & Findings
   (Can be opened directly with Microsoft Excel or Google Sheets).

2. evidence/ (if photos exist on server disk):
   Folder containing high-resolution field photos taken by inspectors,
   organized and renamed by Report ID, Business Name, and Inspection Date.

REVELA Intelligent Monitoring System
Municipality of Mataasnakahoy
"""
            zip_file.writestr("README_ARCHIVE.txt", readme_text.encode("utf-8"))
            zip_file.writestr("manifest.csv", manifest_stream.getvalue().encode("utf-8-sig"))

        stats = {
            "archivedPhotos": archived_photos_count,
            "archivedReports": archived_reports_count,
            "totalReportsMatched": len(reports),
            "uncompressedBytes": total_uncompressed_bytes,
            "uncompressedMB": round(total_uncompressed_bytes / (1024 * 1024), 2),
        }
        return (temp_zip_path, download_filename, stats), None

    except Exception as e:
        return None, str(e)


def cleanup_archived_evidence(evidence_dir, filter_type):
    """
    Deletes physical photo files from disk matching the filter_type for Verified reports,
    and updates the report's photoPath in MySQL to 'archived://<filename>' to maintain
    full audit integrity without leaving broken images.
    """
    try:
        day_map = {
            "older_365d": 365,
            "older_180d": 180,
            "older_90d": 90,
            "older_30d": 30,
            "all_verified": 0,
        }
        if filter_type not in day_map:
            return None, f"Invalid filter type: {filter_type}."

        days = day_map[filter_type]
        cutoff_date = (datetime.now() - timedelta(days=days)) if days > 0 else None

        cursor = mysql.connection.cursor()
        query = """
            SELECT reportID, photoPath, irTimestamp
            FROM inspection_reports
            WHERE verificationStatus = 'Verified'
              AND photoPath IS NOT NULL
              AND photoPath != ''
              AND photoPath NOT LIKE 'archived://%%'
              AND photoPath NOT LIKE '[\"archived://%%'
        """
        params = []
        if cutoff_date:
            query += " AND irTimestamp <= %s"
            params.append(cutoff_date.strftime("%Y-%m-%d %H:%M:%S"))

        cursor.execute(query, tuple(params))
        reports = cursor.fetchall()

        deleted_files_count = 0
        updated_reports_count = 0
        freed_bytes = 0

        for rep in reports:
            raw_photo_path = rep.get("photoPath")
            if not raw_photo_path:
                continue

            is_json_array = False
            raw_items = []
            try:
                parsed = json.loads(raw_photo_path)
                if isinstance(parsed, list):
                    is_json_array = True
                    raw_items = parsed
                else:
                    raw_items = [raw_photo_path]
            except Exception:
                raw_items = [raw_photo_path]

            new_items = []
            rep_changed = False

            for item in raw_items:
                if not item or not isinstance(item, str):
                    continue
                item_str = item.strip()
                if item_str.startswith("archived://"):
                    new_items.append(item_str)
                    continue

                orig_filename = os.path.basename(item_str)
                local_filepath = os.path.join(evidence_dir, orig_filename)

                if os.path.isfile(local_filepath):
                    try:
                        sz = os.path.getsize(local_filepath)
                        os.remove(local_filepath)
                        freed_bytes += sz
                        deleted_files_count += 1
                    except OSError as oe:
                        print(f"Failed to delete {local_filepath}: {oe}")

                new_items.append(f"archived://{orig_filename}")
                rep_changed = True

            if rep_changed:
                updated_val = json.dumps(new_items) if is_json_array else new_items[0]
                cursor.execute("""
                    UPDATE inspection_reports
                    SET photoPath = %s
                    WHERE reportID = %s
                """, (updated_val, rep.get("reportID")))
                updated_reports_count += 1

        mysql.connection.commit()
        cursor.close()

        freed_mb = round(freed_bytes / (1024 * 1024), 2)
        return {
            "deletedFiles": deleted_files_count,
            "updatedReports": updated_reports_count,
            "freedBytes": freed_bytes,
            "freedMB": freed_mb,
            "message": f"Successfully deleted {deleted_files_count} photo(s) from server storage, freeing {freed_mb} MB.",
        }, None

    except Exception as e:
        return None, str(e)

