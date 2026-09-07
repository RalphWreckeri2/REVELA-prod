import os
import json
import csv
import io
import re
import html
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

        # 2. Query MySQL for verified reports
        cursor = mysql.connection.cursor()
        cursor.execute("""
            SELECT
                ir.reportID,
                ir.irTimestamp,
                ir.photoPath
            FROM inspection_reports ir
            WHERE ir.verificationStatus = 'Verified'
              AND (ir.photoPath IS NULL OR (ir.photoPath NOT LIKE 'archived://%%' AND ir.photoPath NOT LIKE '[\"archived://%%'))
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


def _build_html_dossier(reports_data, filter_type, archive_dt):
    """
    Generates a standalone, responsive, print-optimized HTML compliance dossier.
    Includes municipal BPLO branding, summary statistics, search/filtering,
    and embedded photos side-by-side with full audit metadata.
    """
    filter_labels = {
        "older_365d": "Inspections Older than 1 Year (>365 Days)",
        "older_180d": "Inspections Older than 6 Months (>180 Days)",
        "older_90d": "Inspections Older than 3 Months (>90 Days)",
        "older_30d": "Inspections Older than 30 Days",
        "all_verified": "All Verified Inspections",
    }
    filter_title = filter_labels.get(filter_type, filter_type)
    date_formatted = archive_dt.strftime("%B %d, %Y • %I:%M %p")

    total_reports = len(reports_data)
    total_photos_disk = sum(
        sum(1 for p in r.get("photos", []) if p.get("exists_on_disk"))
        for r in reports_data
    )

    green_count = sum(1 for r in reports_data if (r.get("result_color") or "").strip().lower() == "green")
    yellow_count = sum(1 for r in reports_data if (r.get("result_color") or "").strip().lower() == "yellow")
    orange_count = sum(1 for r in reports_data if (r.get("result_color") or "").strip().lower() == "orange")
    red_count = sum(1 for r in reports_data if (r.get("result_color") or "").strip().lower() == "red")

    def get_badge(result_color):
        rc = (result_color or "").strip().lower()
        if rc == "green":
            return ("COMPLIANT", "#065f46", "#d1fae5", "#10b981")
        elif rc == "yellow":
            return ("NOTICE OF VIOLATION", "#92400e", "#fef3c7", "#f59e0b")
        elif rc == "orange":
            return ("WARNING ISSUED", "#9a3412", "#ffedd5", "#f97316")
        elif rc == "red":
            return ("NON-COMPLIANT", "#991b1b", "#fee2e2", "#ef4444")
        elif rc == "purple":
            return ("RE-INSPECTION REQUIRED", "#5b21b6", "#ede9fe", "#8b5cf6")
        else:
            label = html.escape((result_color or "VERIFIED").upper())
            return (label, "#1f2937", "#f3f4f6", "#9ca3af")

    cards_html = []
    for rep in reports_data:
        badge_label, badge_text_col, badge_bg_col, badge_border_col = get_badge(rep.get("result_color"))
        b_name = html.escape(str(rep.get("business_name") or "Unknown Establishment"))
        barangay = html.escape(str(rep.get("barangay") or "Mataasnakahoy"))
        inspector = html.escape(str(rep.get("inspector") or "BPLO Inspector"))
        rep_id = rep.get("report_id")
        log_id = rep.get("log_id") or "N/A"
        ir_ts = html.escape(str(rep.get("timestamp") or "N/A"))
        notice_lvl = rep.get("notice_level") if rep.get("notice_level") is not None else 0
        lat_val = rep.get("latitude") or ""
        lng_val = rep.get("longitude") or ""
        coords_str = f"{lat_val}, {lng_val}" if (lat_val and lng_val) else "Not Recorded"
        landmark = html.escape(str(rep.get("landmark") or "None specified"))
        res_time = str(rep.get("resolution_time") or "")
        res_str = f"{res_time} mins" if res_time else "N/A"
        remarks_text = html.escape(str(rep.get("remarks") or "").strip())

        photos = rep.get("photos") or []
        photos_html = []

        if not photos:
            photos_html.append("""
                <div class="evidence-box no-photo">
                    <span class="icon">📷</span>
                    <div>
                        <strong>No Photo Attached</strong>
                        <p>This inspection was verified and recorded without field photos.</p>
                    </div>
                </div>
            """)
        else:
            photos_grid = []
            for p in photos:
                arcname = html.escape(p.get("arcname") or "")
                orig_fn = html.escape(p.get("orig_filename") or "")
                if p.get("exists_on_disk"):
                    photos_grid.append(f"""
                        <div class="photo-thumb-wrap">
                            <a href="{arcname}" target="_blank" title="Click to view full photo: {orig_fn}">
                                <img src="{arcname}" alt="Evidence: {orig_fn}" loading="lazy" />
                            </a>
                            <div class="photo-caption">{orig_fn}</div>
                        </div>
                    """)
                else:
                    photos_grid.append(f"""
                        <div class="photo-thumb-wrap missing">
                            <div class="missing-photo-placeholder">
                                <span>⚠️ Photo File Unavailable</span>
                                <small>{orig_fn}</small>
                                <p>File was not present on server disk when archive was downloaded (container restarted prior to archival).</p>
                            </div>
                        </div>
                    """)
            photos_html.append(f"""
                <div class="photos-grid">
                    {''.join(photos_grid)}
                </div>
            """)

        remarks_block = ""
        if remarks_text:
            remarks_block = f"""
                <div class="remarks-box">
                    <span class="remarks-label">INSPECTOR REMARKS / FINDINGS:</span>
                    <p>{remarks_text}</p>
                </div>
            """
        else:
            remarks_block = """
                <div class="remarks-box empty">
                    <span class="remarks-label">INSPECTOR REMARKS:</span>
                    <p>No remarks recorded.</p>
                </div>
            """

        map_link = ""
        if lat_val and lng_val:
            map_link = f' <a href="https://maps.google.com/?q={lat_val},{lng_val}" target="_blank" class="map-link">View Map ↗</a>'

        search_corpus = f"{rep_id} {b_name} {barangay} {inspector} {badge_label} {remarks_text}".lower()

        cards_html.append(f"""
            <article class="dossier-card" data-search="{html.escape(search_corpus)}">
                <div class="card-header">
                    <div class="header-left">
                        <div class="report-tag">REPORT #{rep_id} &bull; TARGET #{log_id}</div>
                        <h2 class="biz-name">{b_name}</h2>
                        <div class="location-badge">📍 {barangay}</div>
                    </div>
                    <div class="header-right">
                        <span class="result-badge" style="color: {badge_text_col}; background: {badge_bg_col}; border: 1.5px solid {badge_border_col};">
                            ● {badge_label}
                        </span>
                    </div>
                </div>

                <div class="meta-grid">
                    <div class="meta-item">
                        <span class="lbl">Inspected By</span>
                        <span class="val">👤 {inspector}</span>
                    </div>
                    <div class="meta-item">
                        <span class="lbl">Inspection Date</span>
                        <span class="val">📅 {ir_ts}</span>
                    </div>
                    <div class="meta-item">
                        <span class="lbl">Notice Level</span>
                        <span class="val">Level {notice_lvl}</span>
                    </div>
                    <div class="meta-item">
                        <span class="lbl">Resolution Time</span>
                        <span class="val">⏱️ {res_str}</span>
                    </div>
                    <div class="meta-item">
                        <span class="lbl">GPS Coordinates</span>
                        <span class="val">🌐 {coords_str}{map_link}</span>
                    </div>
                    <div class="meta-item">
                        <span class="lbl">Nearest Landmark</span>
                        <span class="val">🏛️ {landmark}</span>
                    </div>
                </div>

                {remarks_block}

                <div class="evidence-section">
                    <div class="evidence-header">
                        <span class="evidence-title">PHOTO EVIDENCE &amp; VISUAL RECORDS</span>
                    </div>
                    {''.join(photos_html)}
                </div>
            </article>
        """)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>REVELA Inspection Dossier - {html.escape(filter_title)}</title>
    <style>
        :root {{
            --bg-page: #f8fafc;
            --bg-card: #ffffff;
            --text-main: #0f172a;
            --text-muted: #64748b;
            --primary: #10b981;
            --primary-dark: #059669;
            --border: #e2e8f0;
            --border-soft: #f1f5f9;
            --radius-lg: 14px;
            --radius-md: 8px;
            --shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.07), 0 2px 4px -2px rgba(0, 0, 0, 0.05);
        }}
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
            background-color: var(--bg-page);
            color: var(--text-main);
            line-height: 1.5;
            padding: 24px 16px;
        }}
        .container {{
            max-width: 1080px;
            margin: 0 auto;
        }}
        .municipal-header {{
            background: var(--bg-card);
            border: 1px solid var(--border);
            border-radius: var(--radius-lg);
            padding: 24px 28px;
            box-shadow: var(--shadow);
            margin-bottom: 24px;
        }}
        .header-top {{
            display: flex;
            justify-content: space-between;
            align-items: flex-start;
            flex-wrap: wrap;
            gap: 16px;
            border-bottom: 1px solid var(--border-soft);
            padding-bottom: 18px;
        }}
        .republic-text {{
            font-size: 11px;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 1px;
            color: var(--text-muted);
        }}
        .muni-title {{
            font-size: 20px;
            font-weight: 800;
            color: #0f172a;
            margin-top: 2px;
        }}
        .bplo-sub {{
            font-size: 13px;
            font-weight: 600;
            color: var(--primary-dark);
            margin-top: 2px;
        }}
        .actions-group {{
            display: flex;
            gap: 10px;
            align-items: center;
        }}
        .btn-print {{
            background: #0f172a;
            color: #ffffff;
            border: none;
            padding: 10px 18px;
            border-radius: var(--radius-md);
            font-weight: 600;
            font-size: 13px;
            cursor: pointer;
            display: inline-flex;
            align-items: center;
            gap: 8px;
            transition: background 0.15s ease;
        }}
        .btn-print:hover {{
            background: #334155;
        }}
        .stats-banner {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
            gap: 12px;
            margin-top: 18px;
        }}
        .stat-pill {{
            background: var(--bg-page);
            border: 1px solid var(--border);
            border-radius: var(--radius-md);
            padding: 12px 14px;
        }}
        .stat-num {{
            font-size: 22px;
            font-weight: 800;
            color: var(--text-main);
        }}
        .stat-lbl {{
            font-size: 11px;
            font-weight: 600;
            text-transform: uppercase;
            color: var(--text-muted);
            letter-spacing: 0.5px;
        }}
        .search-container {{
            margin-top: 18px;
            display: flex;
            gap: 12px;
            align-items: center;
        }}
        .search-input {{
            flex: 1;
            padding: 10px 16px;
            border: 1.5px solid var(--border);
            border-radius: var(--radius-md);
            font-size: 13px;
            outline: none;
            transition: border-color 0.2s;
        }}
        .search-input:focus {{
            border-color: var(--primary);
        }}
        .search-count {{
            font-size: 12px;
            color: var(--text-muted);
            white-space: nowrap;
        }}
        .dossier-card {{
            background: var(--bg-card);
            border: 1px solid var(--border);
            border-radius: var(--radius-lg);
            padding: 24px;
            margin-bottom: 20px;
            box-shadow: var(--shadow);
            page-break-inside: avoid;
            break-inside: avoid;
        }}
        .card-header {{
            display: flex;
            justify-content: space-between;
            align-items: flex-start;
            flex-wrap: wrap;
            gap: 12px;
            margin-bottom: 16px;
        }}
        .report-tag {{
            font-size: 11px;
            font-weight: 700;
            color: var(--text-muted);
            letter-spacing: 0.5px;
        }}
        .biz-name {{
            font-size: 19px;
            font-weight: 800;
            color: var(--text-main);
            margin: 2px 0;
        }}
        .location-badge {{
            font-size: 13px;
            font-weight: 600;
            color: var(--text-muted);
        }}
        .result-badge {{
            font-size: 12px;
            font-weight: 700;
            letter-spacing: 0.5px;
            padding: 5px 12px;
            border-radius: 20px;
            white-space: nowrap;
        }}
        .meta-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 12px;
            background: var(--bg-page);
            border: 1px solid var(--border);
            border-radius: var(--radius-md);
            padding: 14px 16px;
            margin-bottom: 16px;
        }}
        .meta-item {{
            display: flex;
            flex-direction: column;
        }}
        .meta-item .lbl {{
            font-size: 11px;
            font-weight: 600;
            text-transform: uppercase;
            color: var(--text-muted);
        }}
        .meta-item .val {{
            font-size: 13px;
            font-weight: 600;
            color: var(--text-main);
            margin-top: 2px;
        }}
        .map-link {{
            color: var(--primary-dark);
            text-decoration: none;
            font-size: 11px;
            font-weight: 700;
            margin-left: 6px;
        }}
        .map-link:hover {{ text-decoration: underline; }}
        .remarks-box {{
            border-left: 3.5px solid var(--primary);
            background: #f0fdf4;
            padding: 12px 16px;
            border-radius: 0 var(--radius-md) var(--radius-md) 0;
            margin-bottom: 18px;
        }}
        .remarks-box.empty {{
            border-left-color: var(--border);
            background: var(--bg-page);
        }}
        .remarks-label {{
            font-size: 11px;
            font-weight: 700;
            letter-spacing: 0.5px;
            color: var(--text-muted);
        }}
        .remarks-box p {{
            font-size: 13px;
            color: var(--text-main);
            margin-top: 4px;
        }}
        .evidence-section {{
            margin-top: 14px;
        }}
        .evidence-header {{
            font-size: 11px;
            font-weight: 700;
            letter-spacing: 0.7px;
            color: var(--text-muted);
            margin-bottom: 10px;
        }}
        .photos-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
            gap: 14px;
        }}
        .photo-thumb-wrap {{
            background: #000;
            border-radius: var(--radius-md);
            overflow: hidden;
            border: 1px solid var(--border);
            box-shadow: 0 1px 3px rgba(0,0,0,0.05);
        }}
        .photo-thumb-wrap img {{
            width: 100%;
            height: 180px;
            object-fit: cover;
            display: block;
            transition: transform 0.2s ease;
        }}
        .photo-thumb-wrap a:hover img {{
            transform: scale(1.03);
        }}
        .photo-caption {{
            background: #ffffff;
            font-size: 11px;
            color: var(--text-muted);
            padding: 6px 10px;
            text-overflow: ellipsis;
            white-space: nowrap;
            overflow: hidden;
            border-top: 1px solid var(--border);
        }}
        .missing-photo-placeholder {{
            padding: 24px 16px;
            background: #fffbeb;
            color: #92400e;
            font-size: 12px;
            text-align: center;
        }}
        .missing-photo-placeholder span {{
            display: block;
            font-weight: 700;
            font-size: 13px;
            margin-bottom: 4px;
        }}
        .missing-photo-placeholder small {{
            display: block;
            opacity: 0.8;
            margin-bottom: 8px;
        }}
        .missing-photo-placeholder p {{
            font-size: 11px;
            line-height: 1.4;
        }}
        .evidence-box.no-photo {{
            display: flex;
            align-items: center;
            gap: 12px;
            background: var(--bg-page);
            border: 1px dashed var(--border);
            border-radius: var(--radius-md);
            padding: 12px 16px;
            color: var(--text-muted);
        }}
        .evidence-box.no-photo .icon {{
            font-size: 20px;
        }}
        .evidence-box.no-photo strong {{
            color: var(--text-main);
            font-size: 13px;
        }}
        .evidence-box.no-photo p {{
            font-size: 12px;
            margin-top: 2px;
        }}
        .dossier-footer {{
            text-align: center;
            font-size: 12px;
            color: var(--text-muted);
            margin-top: 32px;
            padding: 16px 0;
            border-top: 1px solid var(--border);
        }}
        @media print {{
            @page {{
                size: A4 portrait;
                margin: 12mm 10mm;
            }}
            body {{
                background: #ffffff !important;
                color: #000000 !important;
                padding: 0 !important;
                font-size: 9.5pt !important;
            }}
            .no-print, .actions-group, .search-container {{
                display: none !important;
            }}
            .container {{
                max-width: 100% !important;
                margin: 0 !important;
            }}
            .municipal-header {{
                border: none !important;
                box-shadow: none !important;
                padding: 0 0 10px 0 !important;
                margin-bottom: 12px !important;
                border-bottom: 2px solid #000 !important;
            }}
            .stats-banner {{
                margin-top: 8px !important;
                gap: 8px !important;
            }}
            .stat-pill {{
                padding: 6px 10px !important;
            }}
            .stat-num {{
                font-size: 16px !important;
            }}
            .stat-lbl {{
                font-size: 9px !important;
            }}
            .dossier-card {{
                box-shadow: none !important;
                border: 1px solid #94a3b8 !important;
                border-radius: 6px !important;
                padding: 12px 16px !important;
                margin-bottom: 14px !important;
                page-break-inside: avoid !important;
                break-inside: avoid !important;
            }}
            .biz-name {{
                font-size: 15px !important;
            }}
            .meta-grid {{
                padding: 8px 10px !important;
                gap: 6px 12px !important;
                margin-bottom: 10px !important;
            }}
            .meta-item .lbl {{
                font-size: 9px !important;
            }}
            .meta-item .val {{
                font-size: 11px !important;
            }}
            .remarks-box {{
                padding: 8px 12px !important;
                margin-bottom: 10px !important;
            }}
            .remarks-box p {{
                font-size: 11px !important;
            }}
            .photo-thumb-wrap img {{
                height: 110px !important;
            }}
            .dossier-card:nth-of-type(2n) {{
                page-break-after: always;
                break-after: page;
            }}
        }}
    </style>
</head>
<body>
    <div class="container">
        <header class="municipal-header">
            <div class="header-top">
                <div>
                    <div class="republic-text">Republic of the Philippines &bull; Province of Batangas</div>
                    <h1 class="muni-title">MUNICIPALITY OF MATAASNAKAHOY</h1>
                    <div class="bplo-sub">Business Permit &amp; Licensing Office (BPLO) &bull; REVELA Inspection Dossier</div>
                </div>
                <div class="actions-group no-print">
                    <button type="button" class="btn-print" onclick="window.print()">
                        🖨️ Print / Save as PDF
                    </button>
                </div>
            </div>

            <div class="stats-banner">
                <div class="stat-pill">
                    <div class="stat-num">{total_reports}</div>
                    <div class="stat-lbl">Verified Reports</div>
                </div>
                <div class="stat-pill">
                    <div class="stat-num" style="color: #10b981;">{green_count}</div>
                    <div class="stat-lbl">Compliant</div>
                </div>
                <div class="stat-pill">
                    <div class="stat-num" style="color: #f59e0b;">{yellow_count}</div>
                    <div class="stat-lbl">Notice of Violation</div>
                </div>
                <div class="stat-pill">
                    <div class="stat-num" style="color: #ef4444;">{red_count}</div>
                    <div class="stat-lbl">Non-Compliant</div>
                </div>
                <div class="stat-pill">
                    <div class="stat-num">{total_photos_disk}</div>
                    <div class="stat-lbl">Photos in Package</div>
                </div>
            </div>

            <div class="search-container no-print">
                <input
                    type="text"
                    id="searchBox"
                    class="search-input"
                    placeholder="Quick search by Business Name, Barangay, Inspector, Result, or Report ID..."
                    oninput="filterCards()"
                />
                <span id="searchCount" class="search-count">{total_reports} report(s) listed</span>
            </div>
        </header>

        <main id="cardsList">
            {''.join(cards_html)}
        </main>

        <footer class="dossier-footer">
            <p><strong>REVELA Intelligent Monitoring System</strong> &bull; Municipality of Mataasnakahoy BPLO</p>
            <p>Archive Generated: {date_formatted} &bull; Filter Scope: {html.escape(filter_title)}</p>
            <p style="margin-top: 4px; font-size: 11px;">This document and attached visual evidence constitute official municipal compliance records.</p>
        </footer>
    </div>

    <script>
        function filterCards() {{
            const query = (document.getElementById('searchBox').value || '').toLowerCase().trim();
            const cards = document.querySelectorAll('.dossier-card');
            let visible = 0;
            cards.forEach(c => {{
                const corpus = c.getAttribute('data-search') || '';
                if (!query || corpus.includes(query)) {{
                    c.style.display = '';
                    visible++;
                }} else {{
                    c.style.display = 'none';
                }}
            }});
            document.getElementById('searchCount').innerText = `${{visible}} of ${{cards.length}} report(s) shown`;
        }}
    </script>
</body>
</html>"""


def generate_evidence_archive_zip(evidence_dir, filter_type):
    """
    Queries verified reports matching filter_type.
    Gathers physical photo files, compiles an audit manifest.csv,
    generates an offline interactive inspection_dossier.html, and packages
    them into a standalone ZIP archive for municipal archival.
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
            LEFT JOIN geospatial_logs g ON ir.targetID = g.logID
            LEFT JOIN barangays b ON g.barangayID = b.barangayID
            LEFT JOIN users u ON ir.userID = u.userID
            WHERE ir.verificationStatus = 'Verified'
              AND (ir.photoPath IS NULL OR (ir.photoPath NOT LIKE 'archived://%%' AND ir.photoPath NOT LIKE '[\"archived://%%'))
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
        reports_for_dossier = []

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
                rep_photo_entries = []

                if not photos:
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
                        "N/A",
                        "N/A",
                        "No Photo Attached",
                    ])
                    archived_reports_count += 1
                else:
                    rep_had_file_on_disk = False
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
                            rep_had_file_on_disk = True

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
                            rep_photo_entries.append({
                                "orig_filename": orig_filename,
                                "arcname": archive_arcname,
                                "exists_on_disk": True,
                            })
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
                            rep_photo_entries.append({
                                "orig_filename": orig_filename,
                                "arcname": archive_arcname,
                                "exists_on_disk": False,
                            })

                    archived_reports_count += 1

                reports_for_dossier.append({
                    "report_id": rep_id,
                    "log_id": log_id,
                    "business_name": b_name,
                    "barangay": barangay,
                    "inspector": inspector,
                    "result_color": result_color,
                    "notice_level": notice_lvl,
                    "timestamp": ir_ts,
                    "deadline": deadline_val,
                    "resolution_time": res_time,
                    "latitude": lat_val,
                    "longitude": lng_val,
                    "landmark": landmark,
                    "remarks": remarks,
                    "photos": rep_photo_entries,
                })

            # 1. Interactive Offline HTML Dossier
            dossier_html = _build_html_dossier(reports_for_dossier, filter_type, datetime.now())
            zip_file.writestr("inspection_dossier.html", dossier_html.encode("utf-8"))

            # 2. Audit manifest spreadsheet
            zip_file.writestr("manifest.csv", manifest_stream.getvalue().encode("utf-8-sig"))

            # 3. Readme instructions
            readme_text = f"""========================================================================
MUNICIPALITY OF MATAASNAKAHOY - BUSINESS PERMIT & LICENSING OFFICE (BPLO)
REVELA INSPECTION ARCHIVE & AUDIT PACKAGE
========================================================================
Archive Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
Filter Type: {filter_type}
Verified Reports Matched: {len(reports)}
Physical Photos Archived in Package: {archived_photos_count}

PACKAGE CONTENTS:
1. inspection_dossier.html:
   *** RECOMMENDED VIEW FOR BPLO STAFF ***
   Interactive visual dossier viewable in any modern browser (Chrome, Edge,
   Safari, Firefox) completely offline.
   - Embeds photo evidence directly alongside business names, inspector details,
     inspection flags, and GPS coordinates.
   - Includes real-time instant search to quickly locate businesses or barangays.
   - Features a one-click "Print / Save as PDF" button with official municipal formatting.

2. manifest.csv:
   Audit spreadsheet containing all 17 metadata fields for records auditing
   (compatible with Microsoft Excel, Google Sheets, LibreOffice).

3. evidence/ (if physical photos were present on server):
   High-resolution photo evidence renamed and categorized by Report ID,
   Business Name, and Inspection Date.

REVELA Intelligent Monitoring System
Municipality of Mataasnakahoy
"""
            zip_file.writestr("README_ARCHIVE.txt", readme_text.encode("utf-8"))

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
    and updates the report's photoPath in MySQL to 'archived://<filename>' (or 'archived://none'
    if report had no photo) to maintain full audit integrity without leaving broken images.
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
              AND (photoPath IS NULL OR (photoPath NOT LIKE 'archived://%%' AND photoPath NOT LIKE '[\"archived://%%'))
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
            rep_id = rep.get("reportID")

            if not raw_photo_path:
                cursor.execute("""
                    UPDATE inspection_reports
                    SET photoPath = 'archived://none'
                    WHERE reportID = %s
                """, (rep_id,))
                updated_reports_count += 1
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
                """, (updated_val, rep_id))
                updated_reports_count += 1

        mysql.connection.commit()
        cursor.close()

        freed_mb = round(freed_bytes / (1024 * 1024), 2)
        return {
            "deletedFiles": deleted_files_count,
            "updatedReports": updated_reports_count,
            "freedBytes": freed_bytes,
            "freedMB": freed_mb,
            "message": f"Successfully cleared {deleted_files_count} photo file(s) and archived {updated_reports_count} report(s), freeing {freed_mb} MB.",
        }, None

    except Exception as e:
        return None, str(e)

