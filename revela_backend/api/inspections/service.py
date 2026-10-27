import os
import json
import csv
import io
import re
import html
import tempfile
import zipfile
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from app import mysql
from api.registry.colors import (
    _effective_flag_color_sql, _registry_column_sql, ladder_columns_available,
)
from api.registry.locks import (
    BlackLockedError,
    assert_not_black_locked,
    record_enforcement_event,
)
from api.registry.service import (
    BLACK_UNLOCK_COLUMNS,
    _consume_black_dispatch_unlock,
    _has_enforcement_columns,
)
from api.models.inspection_lifecycle_events import (
    get_latest_inspection_cycle_id,
    log_inspection_event,
)
from api.registry.inspection_link import (
    GreenRegistryLinkError, prepare_green_link, save_green_link,
)
from api.inspections.evidence_cleanup import cleanup_evidence, recovery_storage_stats


# ── Inspector task list ───────────────────────────────────────────────────────

def _as_user_id(user_id):
    """JWT identity is stored as string; DB column is numeric."""
    try:
        return int(user_id)
    except (TypeError, ValueError):
        return user_id


def get_inspection_calendar(month_start, month_end, selected_date, user_id=None):
    """Return persisted lifecycle events for one month and the selected day."""
    try:
        cursor = mysql.connection.cursor()
        scope_sql = ""
        scope_params = ()
        if user_id is not None:
            scope_sql = " AND (e.assignedToUserID = %s OR e.actorUserID = %s)"
            scope_params = (user_id, user_id)

        cursor.execute(f"""
            SELECT DATE(e.eventTimestamp) AS activityDate, COUNT(*) AS activityCount
            FROM inspection_lifecycle_events e
            WHERE e.eventTimestamp >= %s AND e.eventTimestamp < %s
            {scope_sql}
            GROUP BY DATE(e.eventTimestamp)
            ORDER BY activityDate
        """, (month_start, month_end, *scope_params))
        day_counts = cursor.fetchall()

        cursor.execute(f"""
            SELECT e.eventID, e.reportID, e.targetLogID, e.cycleID, e.eventType,
                   e.eventTimestamp, e.flagColorAtEvent, e.inspectionResult,
                   e.remarks, g.detectedName, b.barangayName,
                   actor.fullName AS actorName, assigned.fullName AS assignedToName
            FROM inspection_lifecycle_events e
            LEFT JOIN geospatial_logs g ON g.logID = e.targetLogID
            LEFT JOIN barangays b ON b.barangayID = g.barangayID
            LEFT JOIN users actor ON actor.userID = e.actorUserID
            LEFT JOIN users assigned ON assigned.userID = e.assignedToUserID
            WHERE e.eventTimestamp >= %s AND e.eventTimestamp < %s
              AND DATE(e.eventTimestamp) = %s
            {scope_sql}
            ORDER BY e.eventTimestamp, e.eventID
        """, (month_start, month_end, selected_date, *scope_params))
        activities = cursor.fetchall()
        cursor.close()

        for event in activities:
            timestamp = event.get("eventTimestamp")
            if timestamp:
                event["eventTimestamp"] = timestamp.isoformat(sep=" ")
        return {
            "month": month_start.strftime("%Y-%m"),
            "selectedDate": selected_date.isoformat(),
            "days": [
                {
                    "date": row["activityDate"].isoformat(),
                    "count": int(row["activityCount"]),
                }
                for row in day_counts
            ],
            "activities": activities,
        }, None
    except Exception as exc:
        return None, str(exc)


def user_can_access_inspection_evidence(filename, user_id, is_admin=False):
    """Check that an active evidence file belongs to a visible inspection report."""
    cursor = mysql.connection.cursor()
    try:
        if is_admin:
            cursor.execute(
                """
                SELECT 1
                FROM inspection_reports
                WHERE photoPath LIKE %s
                LIMIT 1
                """,
                (f"%{filename}%",),
            )
        else:
            cursor.execute(
                """
                SELECT 1
                FROM inspection_reports
                WHERE photoPath LIKE %s AND userID = %s
                LIMIT 1
                """,
                (f"%{filename}%", _as_user_id(user_id)),
            )
        return cursor.fetchone() is not None
    finally:
        cursor.close()


def _validated_inspection_gps(latitude, longitude, accuracy=None):
    try:
        latitude = float(latitude)
        longitude = float(longitude)
        if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
            return None, None, None
    except (TypeError, ValueError):
        return None, None, None

    try:
        accuracy = float(accuracy) if accuracy is not None else None
        if accuracy is not None and (accuracy < 0 or accuracy != accuracy or accuracy == float("inf")):
            accuracy = None
    except (TypeError, ValueError):
        accuracy = None
    return latitude, longitude, accuracy


_gps_columns_ensured = False


def _ensure_gps_columns(cursor):
    global _gps_columns_ensured
    if _gps_columns_ensured:
        return
    try:
        cursor.execute(
            "SHOW COLUMNS FROM inspection_reports LIKE 'verifiedLatitude'")
        if not cursor.fetchone():
            cursor.execute("""
                ALTER TABLE inspection_reports
                ADD COLUMN verifiedLatitude DECIMAL(10, 8) DEFAULT NULL AFTER nearestLandmark,
                ADD COLUMN verifiedLongitude DECIMAL(11, 8) DEFAULT NULL AFTER verifiedLatitude,
                ADD COLUMN verifiedAccuracy DECIMAL(8, 2) DEFAULT NULL AFTER verifiedLongitude
            """)
        _gps_columns_ensured = True
    except Exception as e:
        print(f"[inspections] GPS columns ensure notice: {e}")


def _inspection_report_gps(report):
    latitude = report.get("verifiedLatitude")
    longitude = report.get("verifiedLongitude")
    accuracy = report.get("verifiedAccuracy")

    if latitude is None or longitude is None:
        legacy_location = report.get("nearestLandmark") or ""
        match = re.fullmatch(
            r"\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*",
            str(legacy_location),
        )
        if match:
            latitude, longitude = match.groups()

    return _validated_inspection_gps(latitude, longitude, accuracy)


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
                (
                    SELECT COALESCE(e.cycleID, e.eventID)
                    FROM inspection_lifecycle_events e
                    WHERE e.reportID = ir.reportID
                      AND e.eventType IN ('dispatched', 'reassigned')
                    ORDER BY e.eventID DESC
                    LIMIT 1
                ) AS assignmentCycleID,
                ir.userID,
                ir.targetID          AS logID,
                ir.inspectionResult,
                ir.verificationStatus,
                ir.wasReassigned,
                ir.remarks,
                ir.photoPath,
                ir.irTimestamp,
                COALESCE((
                    SELECT e.eventTimestamp
                    FROM inspection_lifecycle_events e
                    WHERE e.reportID = ir.reportID
                      AND e.eventType IN ('dispatched', 'reassigned')
                    ORDER BY e.eventID DESC
                    LIMIT 1
                ), ir.irTimestamp) AS dispatchedAt,
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
            if row.get("dispatchedAt"):
                row["dispatchedAt"] = str(row["dispatchedAt"])
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
                (
                    SELECT COALESCE(e.cycleID, e.eventID)
                    FROM inspection_lifecycle_events e
                    WHERE e.reportID = ir.reportID
                      AND e.eventType IN ('dispatched', 'reassigned')
                    ORDER BY e.eventID DESC
                    LIMIT 1
                ) AS assignmentCycleID,
                ir.userID,
                ir.targetID          AS logID,
                ir.inspectionResult,
                ir.verificationStatus,
                ir.wasReassigned,
                ir.remarks,
                ir.photoPath,
                ir.irTimestamp,
                COALESCE((
                    SELECT e.eventTimestamp
                    FROM inspection_lifecycle_events e
                    WHERE e.reportID = ir.reportID
                      AND e.eventType IN ('dispatched', 'reassigned')
                    ORDER BY e.eventID DESC
                    LIMIT 1
                ), ir.irTimestamp) AS dispatchedAt,
                ir.submittedAt,
                ir.submissionReceivedAt,
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
            ORDER BY ir.submittedAt IS NULL, ir.submittedAt DESC
            LIMIT 200
        """, (uid,))
        rows = cursor.fetchall()
        cursor.close()

        for row in rows:
            if row.get("irTimestamp"):
                row["irTimestamp"] = str(row["irTimestamp"])
            if row.get("dispatchedAt"):
                row["dispatchedAt"] = str(row["dispatchedAt"])
            if row.get("submittedAt"):
                row["submittedAt"] = str(row["submittedAt"])
            if row.get("submissionReceivedAt"):
                row["submissionReceivedAt"] = str(
                    row["submissionReceivedAt"]
                )
            if row.get("deadline"):
                row["deadline"] = str(row["deadline"])

        return {"data": rows, "total": len(rows)}, None

    except Exception as e:
        return None, str(e)


# ── Assign inspection ─────────────────────────────────────────────────────────

class InspectionAssignmentConflict(Exception):
    """The requested assignment is not allowed in the pin's current state.

    Distinct from InspectionSubmissionConflict, which is about an inspector
    handing work back. Surfaces as HTTP 409.
    """


class InspectionTargetNotFound(LookupError):
    """The map pin being assigned does not exist. Surfaces as HTTP 404."""


class BlackInspectionAssignmentConflict(InspectionAssignmentConflict):
    """Black dispatch/Follow-up needs an open SUPER_ADMIN grant. HTTP 409."""


class InspectionTargetInvalid(ValueError):
    """The assignment itself is malformed, e.g. no such inspector.
    Surfaces as HTTP 400.
    """


class InspectionVerificationConflict(Exception):
    """The verify was refused because of the business's ladder state.

    Raised before anything is written: a Black locked business cannot be
    re-verified to a different result, an Orange must carry the next warning
    level and no other, and a ladder result cannot be recorded at all on a
    database that has not had the migration applied. Surfaces as HTTP 409.
    """


def _coerce_notice_level(value):
    """Read a notice level as an int.

    A report row can hold None or a string depending on how the inspector's
    device sent it. Anything unreadable counts as 0, "no warning", so a
    malformed value can never invent a warning level.
    """
    if value is None or value is False:
        return 0
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


# Effective colours a business may still be inspected in. Green means the
# business is registered and compliant; Black is a permanent offender. Both
# are decided on the effective colour - the same value the Map renders - not
# the raw pin column, so a stale pin cannot make an ineligible business look
# eligible or vice versa.
INSPECTABLE_FLAG_COLORS = frozenset({"Red", "Yellow", "Orange", "Purple"})


def _black_dispatch_unlock_sql(cursor):
    """Black dispatch is disabled; legacy grants never appear in payloads."""
    return "0"


def _enforcement_state_table_available(cursor):
    cursor.execute(
        "SELECT TABLE_NAME FROM information_schema.TABLES "
        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s",
        ("enforcement_state",),
    )
    return cursor.fetchone() is not None


def assign_inspection(log_id, inspector_user_id, deadline, assigned_by,
                      expected_barangay_id=None):
    """
    Create an INSPECTION_REPORTS row linking a geospatial log to an inspector.
    targetType is always 'geospatial_log' since we're dispatching from the flag map.
    Prevents duplicate open assignments for the same logID.
    """
    try:
        cursor = mysql.connection.cursor()
        _ensure_gps_columns(cursor)

        # Guard: check the log exists, and resolve the effective colour in the
        # same round trip. _effective_flag_color_sql is the expression the
        # Map and Registry screens render, so eligibility and display cannot
        # disagree. For a pin with no registry match it falls back to the
        # pin's own colour, which is the only case where the registry cannot
        # speak. The ladder columns are only read once they exist.

        barangay_filter = " AND g.barangayID = %s" if expected_barangay_id is not None else ""
        flag_params = (
            log_id, expected_barangay_id) if expected_barangay_id is not None else (log_id,)
        cursor.execute(
            f"""
            SELECT g.logID, g.flagColor, g.businessID,
                   {_effective_flag_color_sql("g", ladder=ladder_columns_available(cursor))} AS effectiveFlagColor
            FROM geospatial_logs g
            WHERE g.logID = %s{barangay_filter}
            """,
            flag_params,
        )
        flag = cursor.fetchone()
        if not flag:
            cursor.close()
            return None, InspectionTargetNotFound(f"Flag #{log_id} not found")

        # Guard: eligibility, decided on the effective colour.
        effective_color = (flag.get("effectiveFlagColor")
                           or flag.get("flagColor"))
        if effective_color == "Black":
            cursor.close()
            return None, BlackInspectionAssignmentConflict(
                "Black businesses cannot be dispatched for inspection")
        if effective_color not in INSPECTABLE_FLAG_COLORS:
            if effective_color == "Green":
                reason = ("Green (registered) businesses cannot be inspected")
            else:
                reason = (f"{effective_color or 'Uncoloured'} businesses "
                          f"cannot be inspected")
            cursor.close()
            return None, InspectionAssignmentConflict(reason)

        # Guard: inspector user exists and has Inspector role
        cursor.execute(
            "SELECT userID, fullName, userRole, isActive FROM users "
            "WHERE userID = %s AND userRole = 'Inspector'",
            (inspector_user_id,)
        )
        inspector = cursor.fetchone()
        if not inspector:
            cursor.close()
            return None, InspectionTargetInvalid(
                f"Inspector userID {inspector_user_id} not found")
        if inspector.get("isActive") in (0, False):
            cursor.close()
            return None, InspectionTargetInvalid(
                f"Inspector userID {inspector_user_id} is inactive")

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
            return None, InspectionAssignmentConflict(
                "This business is already undergoing inspection and cannot be double-booked.")

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
                    submittedAt = NULL,
                    submissionReceivedAt = NULL,
                    remarks = NULL,
                    photoPath = NULL,
                    resolutionTime = NULL,
                    nearestLandmark = NULL,
                    verifiedLatitude = NULL,
                    verifiedLongitude = NULL,
                    verifiedAccuracy = NULL,
                    irTimestamp = UTC_TIMESTAMP(6)
                WHERE reportID = %s
            """, (inspector_user_id, new_status, deadline, existing["reportID"]))
            report_id = existing["reportID"]
        else:
            cursor.execute("""
                INSERT INTO inspection_reports
                    (userID, targetID, targetType, verificationStatus,
                     deadline, irTimestamp)
                VALUES (%s, %s, 'geospatial_log', %s, %s, UTC_TIMESTAMP(6))
            """, (inspector_user_id, log_id, new_status, deadline))
            report_id = cursor.lastrowid

        log_inspection_event(
            cursor,
            report_id,
            log_id,
            "reassigned" if is_reassign else "dispatched",
            actor_user_id=assigned_by,
            assigned_to_user_id=inspector_user_id,
            flag_color_at_event=flag.get("flagColor"),
        )

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
        mysql.connection.rollback()
        return None, str(e)


# ── Submit inspection ─────────────────────────────────────────────────────────

class InspectionSubmissionConflict(Exception):
    """A predictable conflict with the requested inspection assignment."""


def _same_submission_payload(report, inspection_result, notice_level, notes,
                             photo_url, verified_lat, verified_lng,
                             verified_accuracy):
    def same_number(left, right):
        if left is None or right is None:
            return left is None and right is None
        try:
            return abs(float(left) - float(right)) < 1e-7
        except (TypeError, ValueError):
            return False

    def normalized_photos(value):
        if value is None or value == "":
            return None
        try:
            decoded = json.loads(value) if isinstance(value, str) else value
            if isinstance(decoded, list):
                return sorted(str(item) for item in decoded)
        except (TypeError, ValueError):
            pass
        return str(value)

    def same_accuracy(left, right):
        # Compare the value MySQL retains in DECIMAL(8,2), not binary float noise.
        if left is None or right is None:
            return left is None and right is None
        try:
            left, right = Decimal(str(left)), Decimal(str(right))
            return (
                left.is_finite() and right.is_finite()
                and left.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                == right.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            )
        except (InvalidOperation, TypeError, ValueError):
            return False

    try:
        same_notice_level = int(report.get("noticeLevel") or 0) == int(
            notice_level or 0
        )
    except (TypeError, ValueError):
        same_notice_level = False

    return (
        report.get("inspectionResult") == inspection_result
        and same_notice_level
        and (report.get("remarks") or "").strip() == (notes or "").strip()
        and normalized_photos(report.get("photoPath"))
        == normalized_photos(photo_url)
        and same_number(report.get("verifiedLatitude"), verified_lat)
        and same_number(report.get("verifiedLongitude"), verified_lng)
        and same_accuracy(report.get("verifiedAccuracy"), verified_accuracy)
    )


def submit_inspection(log_id, user_id, inspection_result,
                      notice_level=0,
                      verified_lat=None, verified_lng=None, verified_accuracy=None,
                      notes=None, photo_url=None, report_id=None,
                      assignment_cycle_id=None, submitted_at=None):
    """
    Inspector submits their field report for a given logID.
    Updates the existing Assigned report row to 'Submitted'.
    GPS coordinates are stored separately; nearestLandmark retains the legacy
    coordinate string for compatibility with older report readers.
    """
    from api.inspections.notes_policy import InspectionNotesInvalid, validate_inspection_notes
    try:
        validate_inspection_notes(notes)
    except InspectionNotesInvalid as exc:
        return None, exc
    try:
        cursor = mysql.connection.cursor()
        _ensure_gps_columns(cursor)

        uid = _as_user_id(user_id)
        if report_id is not None:
            cursor.execute("""
                SELECT reportID, targetID, userID, irTimestamp,
                       verificationStatus, wasReassigned, submittedAt,
                       submissionReceivedAt,
                       inspectionResult, noticeLevel,
                       remarks, photoPath, verifiedLatitude,
                       verifiedLongitude, verifiedAccuracy
                FROM inspection_reports
                WHERE reportID = %s
                FOR UPDATE
            """, (report_id,))
        else:
            cursor.execute("""
                SELECT reportID, targetID, userID, irTimestamp,
                       verificationStatus, wasReassigned, submittedAt,
                       submissionReceivedAt,
                       inspectionResult, noticeLevel,
                       remarks, photoPath, verifiedLatitude,
                       verifiedLongitude, verifiedAccuracy
                FROM inspection_reports
                WHERE targetID = %s
                  AND userID = %s
                  AND verificationStatus IN ('Assigned', 'Reassigned')
                LIMIT 1
                FOR UPDATE
            """, (log_id, uid))
        report = cursor.fetchone()

        if not report:
            mysql.connection.rollback()
            cursor.close()
            return None, InspectionSubmissionConflict(
                "No matching inspection assignment was found."
            )
        if report_id is not None and (
            int(report.get("targetID", -1)) != int(log_id)
            or int(report.get("userID", -1)) != int(uid)
        ):
            mysql.connection.rollback()
            cursor.close()
            return None, InspectionSubmissionConflict(
                "The inspection assignment does not belong to this inspector."
            )

        cycle_id = get_latest_inspection_cycle_id(cursor, report["reportID"])
        if report.get("wasReassigned") and assignment_cycle_id is None:
            mysql.connection.rollback()
            cursor.close()
            return None, InspectionSubmissionConflict(
                "The current reassignment cycle is required to submit this report."
            )
        if (
            assignment_cycle_id is not None
            and str(assignment_cycle_id) != str(cycle_id)
        ):
            mysql.connection.rollback()
            cursor.close()
            return None, InspectionSubmissionConflict(
                "This inspection assignment has been reassigned."
            )

        verified_lat, verified_lng, verified_accuracy = _validated_inspection_gps(
            verified_lat, verified_lng, verified_accuracy)
        if report.get("verificationStatus") in ("Submitted", "Verified"):
            if _same_submission_payload(
                report, inspection_result, notice_level, notes, photo_url,
                verified_lat, verified_lng, verified_accuracy,
            ):
                result = {
                    "reportID": report["reportID"],
                    "inspectionResult": report["inspectionResult"],
                    "status": report["verificationStatus"],
                    "alreadyAccepted": True,
                    "submittedAt": (
                        str(report["submittedAt"])
                        if report.get("submittedAt") else None
                    ),
                    "submissionReceivedAt": (
                        str(report["submissionReceivedAt"])
                        if report.get("submissionReceivedAt") else None
                    ),
                }
                mysql.connection.commit()
                cursor.close()
                return result, None
            mysql.connection.rollback()
            cursor.close()
            return None, InspectionSubmissionConflict(
                "This inspection report was already submitted with different data."
            )
        if report.get("verificationStatus") not in ("Assigned", "Reassigned"):
            mysql.connection.rollback()
            cursor.close()
            return None, InspectionSubmissionConflict(
                "This inspection assignment is not open for submission."
            )

        # Calculate resolution time in minutes
        cursor.execute("""
            SELECT TIMESTAMPDIFF(MINUTE, irTimestamp, UTC_TIMESTAMP()) AS mins
            FROM inspection_reports WHERE reportID = %s
        """, (report["reportID"],))
        timing = cursor.fetchone()
        resolution_mins = timing["mins"] if timing else None

        landmark = None
        if verified_lat is not None and verified_lng is not None:
            landmark = f"{verified_lat},{verified_lng}"

        cursor.execute("""
            UPDATE inspection_reports
            SET inspectionResult    = %s,
                noticeLevel         = %s,
                verificationStatus  = 'Submitted',
                remarks             = %s,
                photoPath           = %s,
                nearestLandmark     = COALESCE(%s, nearestLandmark),
                verifiedLatitude    = %s,
                verifiedLongitude   = %s,
                verifiedAccuracy    = %s,
                resolutionTime      = %s,
                submittedAt         = %s,
                submissionReceivedAt = UTC_TIMESTAMP(6)
            WHERE reportID = %s
        """, (
            inspection_result,
            notice_level,
            notes,
            photo_url,
            landmark,
            verified_lat,
            verified_lng,
            verified_accuracy,
            resolution_mins,
            submitted_at,
            report["reportID"],
        ))

        cursor.execute("""
            SELECT submittedAt, submissionReceivedAt
            FROM inspection_reports
            WHERE reportID = %s
        """, (report["reportID"],))
        submission_timestamps = cursor.fetchone() or {}

        # Retrieve the current flagColor to return in the backend payload
        cursor.execute(
            "SELECT flagColor FROM geospatial_logs WHERE logID = %s", (log_id,))
        geo_log = cursor.fetchone()
        flag_color = geo_log["flagColor"] if geo_log else "Red"

        log_inspection_event(
            cursor,
            report["reportID"],
            log_id,
            "submitted",
            actor_user_id=uid,
            assigned_to_user_id=uid,
            flag_color_at_event=flag_color,
            inspection_result=inspection_result,
            remarks=notes,
            cycle_id=cycle_id,
        )

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
            "submittedAt": (
                str(submission_timestamps["submittedAt"])
                if submission_timestamps.get("submittedAt") else None
            ),
            "submissionReceivedAt": (
                str(submission_timestamps["submissionReceivedAt"])
                if submission_timestamps.get("submissionReceivedAt") else None
            ),
        }, None

    except Exception as e:
        mysql.connection.rollback()
        return None, str(e)


# ── Reassign submitted (redo) ─────────────────────────────────────────────────

def reassign_submitted_report(report_id, inspector_user_id, deadline, assigned_by):
    """
    Admin reassigns an active assignment or sends a submitted report back for
    redo. Clears submission data and sets verificationStatus to Reassigned.
    """
    try:
        cursor = mysql.connection.cursor()
        _ensure_gps_columns(cursor)

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

        if report["verificationStatus"] not in ("Assigned", "Submitted"):
            cursor.close()
            return None, (
                f"Report is '{report['verificationStatus']}' — "
                "only Assigned or Submitted reports can be reassigned"
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
            "SELECT flagColor FROM geospatial_logs WHERE logID = %s", (report["targetID"],))
        geo_flag = cursor.fetchone()

        cursor.execute(
            """
            UPDATE inspection_reports
            SET userID = %s,
                verificationStatus = 'Reassigned',
                wasReassigned = 1,
                inspectionResult = NULL,
                submittedAt = NULL,
                submissionReceivedAt = NULL,
                remarks = NULL,
                photoPath = NULL,
                resolutionTime = NULL,
                nearestLandmark = NULL,
                verifiedLatitude = NULL,
                verifiedLongitude = NULL,
                verifiedAccuracy = NULL,
                deadline = %s,
                irTimestamp = UTC_TIMESTAMP(6)
            WHERE reportID = %s
            """,
            (inspector_user_id, deadline, report_id),
        )

        # Sending a report back to the field is one of the ways a single-use
        # Black dispatch grant can stop being spent. The grant paid for ONE
        # inspection; if that inspection is bounced, the grant goes back to
        # zero rather than lingering until someone remembers.
        #
        # Only for a Reassigned (bounced) report. A Verified report being sent
        # back for a fresh look keeps its grant, because the inspection it paid
        # for did happen.
        relocked = False
        if report["verificationStatus"] == "Submitted":
            cursor.execute(
                "SELECT g.businessID FROM geospatial_logs g WHERE g.logID = %s",
                (report["targetID"],),
            )
            pin = cursor.fetchone()
            pin_business_id = pin.get("businessID") if isinstance(
                pin, dict) else (pin[0] if pin else None)
            if pin_business_id and _has_enforcement_columns(
                    cursor, BLACK_UNLOCK_COLUMNS):
                relocked = _consume_black_dispatch_unlock(
                    cursor, pin_business_id, assigned_by,
                    reason="Inspection sent back for redo")

        log_inspection_event(
            cursor,
            report_id,
            report["targetID"],
            "reassigned",
            actor_user_id=assigned_by,
            assigned_to_user_id=inspector_user_id,
            flag_color_at_event=geo_flag["flagColor"] if geo_flag else None,
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
        mysql.connection.rollback()
        return None, str(e)


# ── Verify inspection ─────────────────────────────────────────────────────────

def preview_green_registry_link(report_id, business_id):
    """Read-only identity review; entering a Business ID changes no state."""
    cursor = mysql.connection.cursor()
    try:
        cursor.execute("""SELECT reportID, targetID, targetType, inspectionResult, verificationStatus
                          FROM inspection_reports WHERE reportID = %s""", (report_id,))
        report = cursor.fetchone()
        if not report or report["inspectionResult"] != "Green" or report["verificationStatus"] != "Submitted":
            raise GreenRegistryLinkError("Only a Submitted Green inspection can be reviewed.")
        plan = prepare_green_link(cursor, report, business_id)
        pin, registry = plan["pin"], plan["registry"]
        cursor.execute("SELECT barangayID, barangayName FROM barangays ORDER BY barangayName")
        barangays = cursor.fetchall()
        return {
            "businessID": plan["businessID"], "reviewToken": plan["reviewToken"],
            "registryExists": registry is not None,
            "registry": ({key: registry.get(key) for key in (
                "businessID", "businessName", "businessAddress", "barangayID", "applicationStatus")}
                if registry else plan["newFields"]),
            "pin": {key: pin.get(key) for key in (
                "logID", "businessID", "detectedName", "barangayID", "latitude", "longitude", "source")},
            "missingRequiredFields": plan["missingRequiredFields"],
            "barangays": barangays,
        }, None
    except GreenRegistryLinkError as exc:
        return None, exc
    finally:
        mysql.connection.rollback()
        cursor.close()


def preview_warning_registry_link(report_id, business_id):
    """Review a Business ID before clearing a verified Orange field-pin warning."""
    cursor = mysql.connection.cursor()
    try:
        cursor.execute("""SELECT reportID, targetID, targetType, inspectionResult, verificationStatus
                          FROM inspection_reports WHERE reportID = %s""", (report_id,))
        report = cursor.fetchone()
        if (not report or report["inspectionResult"] != "Orange"
                or report["verificationStatus"] != "Verified"):
            raise GreenRegistryLinkError(
                "Only a Verified Orange inspection can be reviewed for compliance.")

        plan = prepare_green_link(cursor, report, business_id)
        pin, registry = plan["pin"], plan["registry"]
        cursor.execute("""SELECT es.warningLevel, es.blackLocked
                          FROM enforcement_state es
                          WHERE es.subjectType = 'geospatial_log'
                            AND es.subjectID = %s""",
                       (str(pin["logID"]),))
        pin_state = cursor.fetchone() or {}
        if (pin.get("flagColor") != "Orange"
                or _coerce_notice_level(pin_state.get("warningLevel")) <= 0):
            raise GreenRegistryLinkError(
                "This pin no longer has an active Orange warning.", conflict=True)
        if _coerce_notice_level(pin_state.get("blackLocked")):
            raise GreenRegistryLinkError(
                "A Black-locked pin cannot be cleared.", conflict=True)
        if registry and registry.get("applicationStatus") in ("Revoked", "Blacklisted"):
            raise GreenRegistryLinkError(
                "A revoked or Black-locked Registry business cannot be cleared.",
                conflict=True)
        return {
            "businessID": plan["businessID"],
            "reviewToken": plan["reviewToken"],
            "registryExists": registry is not None,
            "registry": ({key: registry.get(key) for key in (
                "businessID", "businessName", "barangayID", "applicationStatus")}
                if registry else plan["newFields"]),
            "pin": {key: pin.get(key) for key in (
                "logID", "detectedName", "barangayID", "latitude", "longitude")},
        }, None
    except GreenRegistryLinkError as exc:
        return None, exc
    finally:
        mysql.connection.rollback()
        cursor.close()


def verify_inspection(report_id, verified_by_user_id=None, update_location=False,
                      business_id=None, confirm_establishment=False,
                      registry_review_token=None, registry_fields=None):
    """
    Admin confirms the inspection result.
    1. Set verificationStatus → 'Verified'
    2. Update geospatial_logs.flagColor to match inspectionResult
    3. Optionally apply the inspector GPS after explicit admin confirmation.
    """
    cursor = None
    committed = False
    report = None
    try:
        cursor = mysql.connection.cursor()
        _ensure_gps_columns(cursor)

        cursor.execute("""
                 SELECT ir.reportID, ir.targetID, ir.targetType, ir.userID, ir.inspectionResult,
                     ir.noticeLevel, ir.verificationStatus, ir.verifiedLatitude,
                     ir.verifiedLongitude, ir.verifiedAccuracy, ir.nearestLandmark,
                     g.detectedName, g.barangayID, g.businessID
                 FROM inspection_reports ir
                 LEFT JOIN geospatial_logs g ON g.logID = ir.targetID
            WHERE ir.reportID = %s FOR UPDATE
        """, (report_id,))
        report = cursor.fetchone()

        if not report:
            cursor.close()
            return None, f"Report #{report_id} not found"

        green_link = None
        if report["inspectionResult"] == "Green":
            if update_location:
                raise GreenRegistryLinkError("Green confirmation preserves the original pin location. Leave updateLocation disabled.")
            if confirm_establishment is not True:
                raise GreenRegistryLinkError("Explicit admin confirmation is required to link this Business ID.")
            green_link = prepare_green_link(cursor, report, business_id, lock=True,
                                            required_fields=registry_fields if report["verificationStatus"] == "Submitted" else None)
            if (report["verificationStatus"] == "Verified"
                    and green_link["registry"]
                    and green_link["registry"].get("confirmedLogID") == report["targetID"]
                    and green_link["pin"].get("businessID") == green_link["businessID"]):
                return {"reportID": report_id, "logID": report["targetID"],
                        "businessID": green_link["businessID"], "status": "Verified",
                        "alreadyVerified": True, "locationUpdated": False}, None
            if registry_review_token != green_link["reviewToken"]:
                raise GreenRegistryLinkError("Registry or pin details changed. Review the Business ID again before confirming.", conflict=True)

        if report["verificationStatus"] != "Submitted":
            cursor.close()
            return None, f"Report is '{report['verificationStatus']}' — only Submitted reports can be verified"

        if not report["inspectionResult"]:
            cursor.close()
            return None, "Report has no inspection result to verify"

        cycle_id = get_latest_inspection_cycle_id(cursor, report_id)
        cursor.execute(
            "SELECT flagColor, noticeLevel FROM geospatial_logs WHERE logID = %s",
            (report["targetID"],))
        geo_flag = cursor.fetchone()

        # ── Decide everything before writing anything ───────────────────────────
        # Every refusal below returns before the first UPDATE, so a rejected
        # verify never leaves a half-applied state behind.
        result_color = report["inspectionResult"]
        notice_level = _coerce_notice_level(report.get("noticeLevel"))
        pin_business_id = report.get("businessID")
        if green_link:
            pin_business_id = green_link["businessID"]
        uses_ladder = result_color in ("Orange", "Black")

        ladder_available = ladder_columns_available(cursor)

        if uses_ladder and not ladder_available:
            # Fail closed. Recording a warning or a Black lock on a database
            # that cannot store them would silently lose the enforcement state,
            # which is worse than refusing the verification.
            cursor.close()
            return None, InspectionVerificationConflict(
                f"{result_color} cannot be verified: this database has not had "
                "the enforcement ladder migration applied, so official_registry "
                "has no warningLevel or blackLocked column to record it in."
            )

        registry_row = None
        registry_enforcement_state = None
        pin_enforcement_state = None
        pin_warning_base_color = None
        dispatch_unlock_available = False
        if pin_business_id:
            cursor.execute(
                "SELECT applicationStatus FROM official_registry "
                "WHERE businessID = %s LIMIT 1",
                (pin_business_id,),
            )
            registry_row = cursor.fetchone()
            if registry_row is not None and ladder_available:
                cursor.execute(
                    """SELECT warningLevel, blackLocked, blackDispatchUnlocked,
                              warningBaseColor
                       FROM enforcement_state
                       WHERE subjectType = 'business' AND subjectID = %s
                       FOR UPDATE""",
                    (str(pin_business_id),),
                )
                registry_enforcement_state = cursor.fetchone() or {}
                dispatch_unlock_available = True

        if registry_row is None:
            pin_state_available = _enforcement_state_table_available(cursor)
            if result_color == "Orange" and not pin_state_available:
                cursor.close()
                return None, InspectionVerificationConflict(
                    "An Orange result on an unregistered pin cannot be verified "
                    "until the enforcement-state migration is applied."
                )
            if pin_state_available:
                cursor.execute(
                    """SELECT warningLevel, blackLocked, warningBaseColor
                       FROM enforcement_state
                       WHERE subjectType = 'geospatial_log' AND subjectID = %s
                       FOR UPDATE""",
                    (str(report["targetID"]),),
                )
                pin_enforcement_state = cursor.fetchone()

        # A newly linked pin can already carry enforcement. Keep its original
        # state/history and mirror its warning onto the business; entering an ID
        # must not bypass a pin lock or clear an unregistered pin's warning.
        linked_pin_warning = False
        if green_link:
            if not ladder_available:
                raise GreenRegistryLinkError("Apply the enforcement-state migration before linking a Green inspection.", conflict=True)
            if (registry_enforcement_state
                    and not _coerce_notice_level(registry_enforcement_state.get("blackDispatchUnlocked"))
                    and (_coerce_notice_level(registry_enforcement_state.get("warningLevel")) > 0
                         or _coerce_notice_level(registry_enforcement_state.get("blackLocked")))):
                raise GreenRegistryLinkError(
                    "This Registry business has an active warning or Black lock; resolve enforcement before confirming Green.",
                    conflict=True)
            cursor.execute("""SELECT warningLevel, blackLocked, warningBaseColor
                              FROM enforcement_state
                              WHERE subjectType = 'geospatial_log' AND subjectID = %s FOR UPDATE""",
                           (str(report["targetID"]),))
            pin_enforcement_state = cursor.fetchone()
            if (pin_enforcement_state and _coerce_notice_level(pin_enforcement_state.get("blackLocked"))
                    or geo_flag and geo_flag.get("flagColor") == "Black" and not report.get("businessID")):
                raise GreenRegistryLinkError("The original pin is Black locked and cannot be linked by a Green confirmation.", conflict=True)
            if (pin_enforcement_state
                    and _coerce_notice_level(pin_enforcement_state.get("warningLevel")) > 0):
                raise GreenRegistryLinkError(
                    "The original pin has an active warning; resolve it before confirming Green.", conflict=True)
            linked_pin_warning = bool(
                pin_enforcement_state
                and _coerce_notice_level(pin_enforcement_state.get("warningLevel"))
                and not (green_link["registry"] and green_link["registry"].get("confirmedLogID") == report["targetID"]))
            if registry_row is None:
                registry_row = {"applicationStatus": "Pending"}
                registry_enforcement_state = {}

        # A SUPER_ADMIN granted exactly one inspection of this Black business.
        # The grant opens this verify and nothing else: the business stays
        # Black and blackLocked is never touched.
        dispatch_unlocked = bool(
            dispatch_unlock_available
            and registry_enforcement_state is not None
            and _coerce_notice_level(
                registry_enforcement_state.get("blackDispatchUnlocked")))

        previous_level = (
            _coerce_notice_level(
                registry_enforcement_state.get("warningLevel"))
            if registry_enforcement_state is not None else
            _coerce_notice_level(pin_enforcement_state.get("warningLevel"))
            if pin_enforcement_state else
            _coerce_notice_level(geo_flag.get("noticeLevel"))
            if geo_flag else 0
        )
        if linked_pin_warning:
            previous_level = max(previous_level, _coerce_notice_level(pin_enforcement_state.get("warningLevel")))

        if result_color == "Orange":
            if pin_enforcement_state and _coerce_notice_level(
                    pin_enforcement_state.get("blackLocked")):
                cursor.close()
                return None, InspectionVerificationConflict(
                    "This detection pin is Black locked and cannot receive an Orange warning."
                )
            expected_level = previous_level + 1
            if not 1 <= notice_level <= 3:
                cursor.close()
                return None, InspectionVerificationConflict(
                    f"This report carries notice level {notice_level}, but "
                    f"an Orange verification must carry 1, 2 or 3."
                )
            if notice_level != expected_level:
                cursor.close()
                return None, InspectionVerificationConflict(
                    f"This business is at warning level {previous_level}, so "
                    f"the next Orange must be level {expected_level}. This "
                    f"report carries level {notice_level}."
                )
            if registry_row is None:
                pin_warning_base_color = (
                    pin_enforcement_state.get("warningBaseColor")
                    if pin_enforcement_state else None
                )
                if pin_warning_base_color not in ("Red", "Yellow", "Green", "Purple"):
                    current_color = geo_flag.get(
                        "flagColor") if geo_flag else None
                    if current_color in ("Red", "Yellow", "Green", "Purple"):
                        pin_warning_base_color = current_color
                    else:
                        cursor.execute(
                            """SELECT flagColorAtEvent
                               FROM inspection_lifecycle_events
                               WHERE targetLogID = %s
                                 AND eventType IN ('dispatched', 'reassigned')
                                 AND flagColorAtEvent IN ('Red', 'Yellow', 'Green', 'Purple')
                               ORDER BY eventID ASC
                               LIMIT 1""",
                            (report["targetID"],),
                        )
                        baseline = cursor.fetchone()
                        pin_warning_base_color = (
                            baseline.get(
                                "flagColorAtEvent") if baseline else None
                        )
                if pin_warning_base_color not in ("Red", "Yellow", "Green", "Purple"):
                    cursor.close()
                    return None, InspectionVerificationConflict(
                        "The pin's pre-warning color is unknown, so this Orange "
                        "result cannot be verified without guessing."
                    )

        if pin_business_id and not dispatch_unlocked:
            try:
                assert_not_black_locked(
                    cursor, pin_business_id,
                    action="verify this inspection")
            except BlackLockedError as exc:
                cursor.close()
                return None, InspectionVerificationConflict(str(exc))

        if green_link:
            if dispatch_unlocked:
                if not report.get("businessID"):
                    raise GreenRegistryLinkError("A Black dispatch grant cannot adopt an unlinked field pin.", conflict=True)
                # A legacy single-use grant records the finding only. Confirm
                # its existing pin reference without moving/recolouring it or
                # rewriting the locked business's location/provenance.
                cursor.execute("UPDATE official_registry SET confirmedLogID = %s WHERE businessID = %s",
                               (report["targetID"], pin_business_id))
            else:
                save_green_link(cursor, green_link)

        location_updated = False
        if update_location:
            latitude, longitude, _ = _inspection_report_gps(report)
            if latitude is None or longitude is None:
                cursor.close()
                return None, "This inspection has no valid GPS coordinates to apply"

            from api.flags.service import _get_barangay_id_by_coords, _within_municipality

            if not _within_municipality(latitude, longitude):
                cursor.close()
                return None, "Inspector GPS is outside the Mataasnakahoy boundary"

            new_barangay_id = _get_barangay_id_by_coords(latitude, longitude)
            if new_barangay_id is None:
                cursor.close()
                return None, "Could not determine the barangay for the inspector GPS"

            cursor.execute(
                """UPDATE geospatial_logs
                   SET latitude = %s, longitude = %s, barangayID = %s
                   WHERE logID = %s""",
                (latitude, longitude, new_barangay_id, report["targetID"]),
            )
            if cursor.rowcount != 1:
                mysql.connection.rollback()
                cursor.close()
                return None, "The target map pin could not be updated"

            if pin_business_id:
                cursor.execute(
                    """UPDATE official_registry
                       SET latitude = %s, longitude = %s, barangayID = %s
                       WHERE businessID = %s""",
                    (latitude, longitude, new_barangay_id,
                     pin_business_id),
                )
            location_updated = True

        # Update report status
        cursor.execute("""
            UPDATE inspection_reports
            SET verificationStatus = 'Verified'
            WHERE reportID = %s
        """, (report_id,))

        # Propagate result → geospatial_logs
        #
        # An unlocked-Black verify leaves the pin alone. The pin colour is the
        # last thing that would still read as something other than Black, and
        # a Black business briefly rendering Green on the map is exactly the
        # drift this ladder exists to prevent.
        pin_result_color = result_color
        if linked_pin_warning:
            pin_result_color = "Orange"
        if (pin_business_id is None and registry_row is None
                and pin_enforcement_state
                and _coerce_notice_level(pin_enforcement_state.get("warningLevel")) > 0
                and result_color not in ("Orange", "Black")):
            pin_result_color = "Orange"

        if not dispatch_unlocked:
            cursor.execute("""
                UPDATE geospatial_logs
                SET flagColor = %s,
                    noticeLevel = %s
                WHERE logID = %s
            """, (pin_result_color, notice_level, report["targetID"]))

        registry_closed = False
        registry_warning = None
        registry_updated = False
        ladder_events = []

        if result_color == "Purple":
            # Verified Purple (Closed / Abandoned) marks the registry entry
            # 'Closed'.
            #
            # Matching by name alone is not safe: two businesses can share a
            # name in one barangay, and closing the wrong one is worse than not
            # closing either. Prefer the pin's businessID; fall back to name +
            # barangay only for legacy pins that carry none. Either way the
            # affected row count is checked - previously a zero-row update
            # still returned "Verified" and the admin believed the permit had
            # been closed.
            if pin_business_id:
                cursor.execute("""
                    UPDATE official_registry
                    SET applicationStatus = 'Closed'
                    WHERE businessID = %s
                """, (pin_business_id,))
                registry_closed = cursor.rowcount > 0
                registry_updated = registry_closed
                if not registry_closed:
                    registry_warning = (
                        f"Pin is linked to business {pin_business_id}, but no "
                        f"registry row with that ID was updated; the permit "
                        f"status may not show as Closed."
                    )
            else:
                # Legacy pin with no businessID. Not an error - there may be
                # no registry record at all for an unregistered pin.
                cursor.execute(
                    """SELECT detectedName, barangayID
                       FROM geospatial_logs WHERE logID = %s""",
                    (report["targetID"],),
                )
                geo_row = cursor.fetchone()
                if geo_row and geo_row["detectedName"]:
                    cursor.execute("""
                        UPDATE official_registry
                        SET applicationStatus = 'Closed'
                        WHERE LOWER(businessName) = LOWER(%s) AND barangayID = %s
                    """, (geo_row["detectedName"], geo_row["barangayID"]))
                    registry_closed = cursor.rowcount > 0
                    registry_updated = registry_closed
                    if not registry_closed:
                        registry_warning = (
                            "Pin has no business ID and no registry row matched "
                            "its name and barangay; the permit status may not "
                            "show as Closed."
                        )

        if registry_row is not None and dispatch_unlocked:
            # The one inspection the grant paid for. Record what was found and
            # when, and nothing else: applicationStatus, warningLevel,
            # blackLocked and blackDispatchUnlocked's own semantics all stay
            # as they are. The business was Black before this verify and is
            # Black after it.
            cursor.execute(
                """UPDATE enforcement_state
                   SET lastInspectionResult = %s,
                       lastInspectedAt = NOW()
                   WHERE subjectType = 'business' AND subjectID = %s""",
                (result_color, str(pin_business_id)),
            )
            registry_updated = cursor.rowcount > 0
            if not registry_updated:
                registry_warning = (
                    f"The registry row for {pin_business_id} could not be "
                    "stamped with this inspection result."
                )

        elif registry_row is not None:
            # A registered target always records what was verified and when.
            # Orange and Black deliberately leave applicationStatus alone: a
            # warning is a warning level, not a permit status.
            new_status = {
                "Red": "Expired", "Yellow": "Pending", "Green": "Active",
            }.get(result_color)
            if new_status:
                cursor.execute(
                    "UPDATE official_registry SET applicationStatus = %s "
                    "WHERE businessID = %s",
                    (new_status, pin_business_id),
                )
                registry_updated = cursor.rowcount > 0
                if not registry_updated:
                    registry_warning = (
                        f"The registry row for {pin_business_id} could not be "
                        "updated; its permit status may be stale."
                    )
            else:
                registry_updated = True

            clears_warning = (
                result_color not in ("Orange", "Black")
                and previous_level > 0
                and not linked_pin_warning
            )
            clear_reason = (
                f"Cleared by verified {result_color} inspection"
                if clears_warning else None
            )
            state_warning_level = (
                notice_level if result_color == "Orange" else
                0 if clears_warning else previous_level)
            state_black_locked = (
                1 if result_color == "Black" else
                _coerce_notice_level(
                    registry_enforcement_state.get("blackLocked"))
                if registry_enforcement_state else 0
            )
            state_black_locked_by = (
                verified_by_user_id if result_color == "Black" else
                registry_enforcement_state.get("blackLockedBy")
                if registry_enforcement_state else None
            )
            state_warning_base = (
                {
                    "Active": "Green", "Expired": "Red", "Pending": "Yellow",
                    "Closed": "Purple", "Revoked": "Black",
                    "Blacklisted": "Black",
                }.get(registry_row.get("applicationStatus"))
                if result_color == "Orange" else
                None if clears_warning else
                registry_enforcement_state.get("warningBaseColor")
                if registry_enforcement_state else None
            )
            if linked_pin_warning and not state_warning_base:
                state_warning_base = pin_enforcement_state.get("warningBaseColor")
            state_updates = [
                "lastInspectionResult = VALUES(lastInspectionResult)",
                "lastInspectedAt = NOW()",
            ]
            if result_color == "Orange":
                state_updates.extend([
                    "warningLevel = VALUES(warningLevel)",
                    "warningBaseColor = COALESCE(warningBaseColor, VALUES(warningBaseColor))",
                ])
            if clears_warning:
                state_updates.extend([
                    "warningLevel = 0",
                    "warningBaseColor = NULL",
                    "warningClearedAt = VALUES(warningClearedAt)",
                    "warningClearedBy = VALUES(warningClearedBy)",
                    "warningClearReason = VALUES(warningClearReason)",
                ])
            if result_color == "Black":
                state_updates.extend([
                    "blackLocked = 1",
                    "blackLockedAt = NOW()",
                    "blackLockedBy = VALUES(blackLockedBy)",
                ])
            if linked_pin_warning:
                state_updates.extend([
                    "warningLevel = VALUES(warningLevel)",
                    "warningBaseColor = COALESCE(warningBaseColor, VALUES(warningBaseColor))",
                ])
            clear_metadata_values = (
                "NOW(), %s, %s" if clears_warning else "NULL, NULL, NULL")
            state_write_params = (
                str(pin_business_id), state_warning_level, state_warning_base,
                state_black_locked, int(result_color == "Black"),
                state_black_locked_by, result_color,
            )
            if clears_warning:
                state_write_params += (
                    verified_by_user_id,
                    clear_reason,
                )
            cursor.execute(
                """INSERT INTO enforcement_state (
                       subjectType, subjectID, warningLevel, warningBaseColor,
                       blackLocked, blackLockedAt, blackLockedBy,
                       lastInspectionResult, lastInspectedAt,
                       warningClearedAt, warningClearedBy, warningClearReason
                   ) VALUES ('business', %s, %s, %s, %s,
                             CASE WHEN %s = 1 THEN NOW() ELSE NULL END,
                             %s, %s, NOW(), """ + clear_metadata_values + ")\n"
                + "                   ON DUPLICATE KEY UPDATE "
                + ", ".join(state_updates),
                state_write_params,
            )
            registry_updated = registry_updated and cursor.rowcount >= 0

            # The audit trail shares this cursor, so it commits or rolls back
            # with the change it describes.
            if result_color == "Orange":
                ladder_events.append(dict(
                    event_type="warning_issued",
                    previous_level=previous_level, new_level=notice_level,
                    previous_black=None, new_black=None, reason=None))
            if clears_warning:
                locked = _coerce_notice_level(
                    (registry_enforcement_state or {}).get("blackLocked"))
                ladder_events.append(dict(
                    event_type="warning_cleared",
                    previous_level=previous_level, new_level=0,
                    previous_black=locked, new_black=locked,
                    reason=clear_reason))
            if result_color == "Black":
                ladder_events.append(dict(
                    event_type="black_locked",
                    previous_level=previous_level, new_level=previous_level,
                    previous_black=(registry_enforcement_state or {}).get(
                        "blackLocked"),
                    new_black=True, reason=None))

            for event in ladder_events:
                record_enforcement_event(
                    cursor,
                    business_id=pin_business_id,
                    event_type=event["event_type"],
                    actor_user_id=verified_by_user_id,
                    previous_level=event["previous_level"],
                    new_level=event["new_level"],
                    previous_black=event["previous_black"],
                    new_black=event["new_black"],
                    reason=event["reason"],
                )

        elif result_color == "Orange":
            if pin_enforcement_state:
                cursor.execute(
                    """UPDATE enforcement_state
                       SET warningLevel = %s,
                           warningBaseColor = COALESCE(warningBaseColor, %s),
                           lastInspectionResult = 'Orange',
                           lastInspectedAt = NOW()
                       WHERE subjectType = 'geospatial_log' AND subjectID = %s""",
                    (notice_level, pin_warning_base_color,
                     str(report["targetID"])),
                )
            else:
                cursor.execute(
                    """INSERT INTO enforcement_state (
                           subjectType, subjectID, warningLevel, warningBaseColor,
                           lastInspectionResult, lastInspectedAt
                       ) VALUES ('geospatial_log', %s, %s, %s, 'Orange', NOW())""",
                    (str(report["targetID"]),
                     notice_level, pin_warning_base_color),
                )
            cursor.execute(
                """INSERT INTO enforcement_events (
                    subjectType, subjectID, eventType, actorUserID, reason,
                    previousLevel, newLevel, previousBlack, newBlack, createdAt
                    ) VALUES ('geospatial_log', %s, 'warning_issued', %s, NULL,
                              %s, %s, 0, 0, UTC_TIMESTAMP(6))""",
                (str(report["targetID"]), verified_by_user_id,
                 previous_level, notice_level),
            )

        elif (registry_row is None and pin_business_id is None
              and pin_enforcement_state):
            cursor.execute(
                """UPDATE enforcement_state
                   SET lastInspectionResult = %s, lastInspectedAt = NOW()
                   WHERE subjectType = 'geospatial_log' AND subjectID = %s""",
                (result_color, str(report["targetID"])),
            )

        # Single use. The grant is spent the moment the inspection it paid for
        # reaches a verified state. blackLocked is not touched.
        unlock_spent = dispatch_unlocked and _consume_black_dispatch_unlock(
            cursor, pin_business_id, verified_by_user_id,
            reason="Inspection verified")

        log_inspection_event(
            cursor,
            report_id,
            report["targetID"],
            "verified",
            actor_user_id=verified_by_user_id,
            assigned_to_user_id=report["userID"],
            flag_color_at_event=geo_flag["flagColor"] if geo_flag else None,
            inspection_result=report["inspectionResult"],
            remarks=(f"Business ID {pin_business_id} {'created in registry' if not green_link['registry'] else 'linked to existing registry record'} and linked to original pin" if green_link else
                     "Map location updated to inspector GPS" if location_updated
                     else registry_warning),
            cycle_id=cycle_id,
        )

        mysql.connection.commit()
        committed = True
        cursor.close()

        try:
            from api.notifications import hub
            hub.publish_to_admins({
                "type": "inspection_updated",
                "reportID": report_id,
                "logID": report["targetID"],
                "status": "Verified",
                "newFlagColor": report["inspectionResult"],
                "locationUpdated": location_updated,
                "registryClosed": registry_closed,
                "registryWarning": registry_warning,
                "registryUpdated": registry_updated,
                "warningLevel": previous_level if result_color == "Orange"
                else notice_level if result_color == "Black"
                else None,
                "blackLocked": result_color == "Black",
            })
            if green_link and not dispatch_unlocked:
                hub.publish_to_admins({
                    "type": "registry_updated", "businessID": pin_business_id,
                    "logID": report["targetID"],
                })
        except Exception:
            pass

        return {
            "reportID":         report_id,
            "logID":            report["targetID"],
            "newFlagColor":     report["inspectionResult"],
            "status":           "Verified",
            "locationUpdated":  location_updated,
            **({"businessID": pin_business_id} if green_link else {}),
            # registryClosed is True only when an official_registry row was
            # actually updated. registryWarning explains a verified Purple whose
            # registry row could not be reached, so the admin is not misled.
            "registryClosed":   registry_closed,
            "registryWarning":  registry_warning,
            # registryUpdated covers every verified result, not just Purple:
            # Red, Yellow and Green move applicationStatus, Orange and Black
            # move the ladder columns, and all of them stamp
            # lastInspectionResult / lastInspectedAt.
            "registryUpdated":  registry_updated,
            # True when this verify consumed a single-use Black dispatch grant.
            "blackDispatchUnlockSpent": bool(unlock_spent),
        }, None

    except GreenRegistryLinkError as e:
        return None, e
    except Exception as e:
        mysql.connection.rollback()
        if ((report or {}).get("inspectionResult") == "Green"
                and e.args and e.args[0] in (1062, 1205, 1213)):
            return None, GreenRegistryLinkError(
                "The Business ID or pin was changed by another request. Review the link and retry.", conflict=True)
        return None, str(e)
    finally:
        if not committed:
            mysql.connection.rollback()
        if cursor is not None:
            try:
                cursor.close()
            except Exception:
                pass


# ── Get all inspections (admin) ───────────────────────────────────────────────

def get_all_inspections(status=None, barangay_id=None, page=1, per_page=20, report_ids=None):
    """
    Admin view: paginated inspection reports with flag + inspector details.
    Filterable by verificationStatus and barangayID.
    """
    try:
        cursor = mysql.connection.cursor()
        _ensure_gps_columns(cursor)

        conditions = []
        params = []

        if status:
            conditions.append("ir.verificationStatus = %s")
            params.append(status)

        if barangay_id:
            conditions.append("g.barangayID = %s")
            params.append(barangay_id)

        if report_ids is not None:
            if not report_ids:
                cursor.close()
                return {"data": [], "total": 0, "total_rows": 0, "page": page,
                        "per_page": per_page, "pages": 1}, None
            conditions.append("ir.reportID IN (" + ",".join(["%s"] * len(report_ids)) + ")")
            params.extend(report_ids)

        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
        offset = (page - 1) * per_page

        # Fetch both counts in a single round-trip using UNION ALL,
        # then pull the data rows in a second query.
        # Previously this was 3 separate queries; now it is 2.
        cursor.execute(
            f"""
            SELECT 'collapsed' AS cnt_type, COUNT(*) AS cnt
            FROM inspection_reports ir
            JOIN (
                SELECT targetID, MAX(reportID) AS maxReportID
                FROM inspection_reports
                GROUP BY targetID
            ) latest_ir ON ir.reportID = latest_ir.maxReportID
            JOIN geospatial_logs g ON ir.targetID = g.logID
            {where}

            UNION ALL

            SELECT 'all_rows' AS cnt_type, COUNT(*) AS cnt
            FROM inspection_reports ir
            JOIN geospatial_logs g ON ir.targetID = g.logID
            {where}
            """,
            params + params,  # params appear twice — once per UNION branch
        )
        counts = {r["cnt_type"]: r["cnt"] for r in cursor.fetchall()}
        total = counts.get("collapsed", 0)
        total_rows = counts.get("all_rows", 0)

        ladder = ladder_columns_available(cursor)
        pin_state_available = _enforcement_state_table_available(cursor)
        registry_effective_color = _effective_flag_color_sql(
            "g", ladder=ladder)
        registry_unlock = _black_dispatch_unlock_sql(cursor)
        business_id = f"COALESCE({_registry_column_sql('g', 'businessID')}, g.businessID)"
        business_name = f"COALESCE({_registry_column_sql('g', 'businessName')}, g.detectedName)"
        business_barangay = f"COALESCE({_registry_column_sql('g', 'barangayID')}, g.barangayID)"
        registry_warning = f"COALESCE({_registry_column_sql('g', 'warningLevel')}, 0)" if ladder else "0"
        registry_lock = f"COALESCE({_registry_column_sql('g', 'blackLocked')}, 0)" if ladder else "0"
        if pin_state_available:
            effective_color = (
                f"CASE WHEN {business_id} IS NULL "
                "AND COALESCE(pin_enforcement.blackLocked, 0) = 1 THEN 'Black' "
                f"WHEN {business_id} IS NULL "
                "AND COALESCE(pin_enforcement.warningLevel, 0) > 0 THEN 'Orange' "
                f"ELSE {registry_effective_color} END"
            )
            warning = (f"CASE WHEN {business_id} IS NULL "
                       f"THEN COALESCE(pin_enforcement.warningLevel, 0) "
                       f"ELSE {registry_warning} END")
            locked = (f"CASE WHEN {business_id} IS NULL "
                      f"THEN COALESCE(pin_enforcement.blackLocked, 0) "
                      f"ELSE {registry_lock} END")
            unlock = (f"CASE WHEN {business_id} IS NULL "
                      f"THEN COALESCE(pin_enforcement.blackDispatchUnlocked, 0) "
                      f"ELSE {registry_unlock} END")
            warning_base_color = "pin_enforcement.warningBaseColor"
            pin_state_join = """LEFT JOIN enforcement_state pin_enforcement
                ON pin_enforcement.subjectType = 'geospatial_log'
               AND pin_enforcement.subjectID = CAST(g.logID AS CHAR)"""
        else:
            effective_color = registry_effective_color
            warning = registry_warning
            locked = registry_lock
            unlock = registry_unlock
            warning_base_color = "NULL"
            pin_state_join = ""

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
                ir.verifiedLatitude,
                ir.verifiedLongitude,
                ir.verifiedAccuracy,
                g.detectedName,
                g.businessID AS linkedBusinessID,
                {effective_color} AS flagColor,
                COALESCE({_registry_column_sql('g', 'businessID')}, g.businessID) AS businessID,
                {_registry_column_sql('g', 'applicationStatus')} AS applicationStatus,
                {warning} AS warningLevel,
                {warning_base_color} AS warningBaseColor,
                {locked} AS blackLocked,
                {unlock} AS blackDispatchUnlocked,
                EXISTS (
                    SELECT 1 FROM inspection_reports pending
                    JOIN geospatial_logs pending_g ON pending_g.logID = pending.targetID
                    WHERE pending.targetType = 'geospatial_log'
                      AND (pending.verificationStatus IS NULL OR pending.verificationStatus <> 'Verified')
                      AND (pending_g.businessID = {business_id}
                           OR (pending_g.businessID IS NULL
                               AND pending_g.detectedName = {business_name}
                               AND pending_g.barangayID = {business_barangay}))
                ) AS hasNonVerifiedInspection,
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
            {pin_state_join}
            {where}
            ORDER BY ir.irTimestamp DESC
            LIMIT %s OFFSET %s
            """,
            params + [per_page, offset],
        )
        rows = cursor.fetchall()

        cursor.close()

        for row in rows:
            latitude, longitude, accuracy = _inspection_report_gps(row)
            row["verifiedLatitude"] = latitude
            row["verifiedLongitude"] = longitude
            row["verifiedAccuracy"] = accuracy
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

        avg_file_size = (
            total_bytes / total_files) if total_files > 0 else (1.2 * 1024 * 1024)
        recovery = recovery_storage_stats(evidence_dir)
        total_bytes += recovery["recoveryBytes"]
        total_files += recovery["recoveryFiles"]
        total_mb = round(total_bytes / (1024 * 1024), 2)

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
            "cleanupPending": recovery["cleanupPending"],
            "recoveryDiskMB": round(recovery["recoveryBytes"] / (1024 * 1024), 2),
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

    green_count = sum(1 for r in reports_data if (
        r.get("result_color") or "").strip().lower() == "green")
    yellow_count = sum(1 for r in reports_data if (
        r.get("result_color") or "").strip().lower() == "yellow")
    orange_count = sum(1 for r in reports_data if (
        r.get("result_color") or "").strip().lower() == "orange")
    red_count = sum(1 for r in reports_data if (
        r.get("result_color") or "").strip().lower() == "red")

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
        badge_label, badge_text_col, badge_bg_col, badge_border_col = get_badge(
            rep.get("result_color"))
        b_name = html.escape(
            str(rep.get("business_name") or "Unknown Establishment"))
        barangay = html.escape(str(rep.get("barangay") or "Mataasnakahoy"))
        inspector = html.escape(str(rep.get("inspector") or "BPLO Inspector"))
        rep_id = rep.get("report_id")
        log_id = rep.get("log_id") or "N/A"
        ir_ts = html.escape(str(rep.get("timestamp") or "N/A"))
        notice_lvl = rep.get("notice_level") if rep.get(
            "notice_level") is not None else 0
        lat_val = rep.get("latitude") or ""
        lng_val = rep.get("longitude") or ""
        coords_str = f"{lat_val}, {lng_val}" if (
            lat_val and lng_val) else "Not Recorded"
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
                <div class="card-left">
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
                </div>

                <div class="card-right">
                    <div class="evidence-section">
                        <div class="evidence-header">
                            <span class="evidence-title">PHOTO EVIDENCE</span>
                        </div>
                        {''.join(photos_html)}
                    </div>
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
            padding: 20px 24px;
            margin-bottom: 20px;
            box-shadow: var(--shadow);
            display: flex;
            flex-direction: row;
            gap: 20px;
            align-items: stretch;
            page-break-inside: avoid;
            break-inside: avoid;
        }}
        .card-left {{
            flex: 1;
            min-width: 0;
            display: flex;
            flex-direction: column;
            justify-content: space-between;
        }}
        .card-right {{
            width: 220px;
            min-width: 220px;
            max-width: 220px;
            display: flex;
            flex-direction: column;
            justify-content: center;
            align-items: stretch;
            border-left: 1px solid var(--border-soft);
            padding-left: 18px;
        }}
        @media (max-width: 768px) {{
            .dossier-card {{
                flex-direction: column;
            }}
            .card-right {{
                width: 100%;
                min-width: 100%;
                max-width: 100%;
                border-left: none;
                border-top: 1px solid var(--border-soft);
                padding-left: 0;
                padding-top: 16px;
                margin-top: 10px;
            }}
        }}
        .card-header {{
            display: flex;
            justify-content: space-between;
            align-items: flex-start;
            flex-wrap: wrap;
            gap: 12px;
            margin-bottom: 12px;
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
            grid-template-columns: repeat(3, 1fr);
            gap: 10px 14px;
            background: var(--bg-page);
            border: 1px solid var(--border);
            border-radius: var(--radius-md);
            padding: 12px 14px;
            margin-bottom: 12px;
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
            padding: 10px 14px;
            border-radius: 0 var(--radius-md) var(--radius-md) 0;
            margin-bottom: 0;
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
            display: flex;
            flex-direction: column;
            height: 100%;
            justify-content: center;
        }}
        .evidence-header {{
            font-size: 10px;
            font-weight: 700;
            letter-spacing: 0.7px;
            color: var(--text-muted);
            margin-bottom: 8px;
            text-align: center;
            text-transform: uppercase;
        }}
        .photos-grid {{
            display: flex;
            flex-direction: column;
            gap: 10px;
            align-items: center;
            justify-content: center;
        }}
        .photo-thumb-wrap {{
            background: #000;
            border-radius: var(--radius-md);
            overflow: hidden;
            border: 1px solid var(--border);
            box-shadow: 0 1px 3px rgba(0,0,0,0.05);
            width: 100%;
            max-width: 190px;
        }}
        .photo-thumb-wrap img {{
            width: 100%;
            height: 140px;
            object-fit: cover;
            display: block;
            transition: transform 0.2s ease;
        }}
        .photo-thumb-wrap a:hover img {{
            transform: scale(1.03);
        }}
        .photo-caption {{
            background: #ffffff;
            font-size: 10px;
            color: var(--text-muted);
            padding: 4px 8px;
            text-overflow: ellipsis;
            white-space: nowrap;
            overflow: hidden;
            border-top: 1px solid var(--border);
            text-align: center;
        }}
        .missing-photo-placeholder {{
            padding: 14px 10px;
            background: #fffbeb;
            color: #92400e;
            font-size: 11px;
            text-align: center;
            border-radius: var(--radius-md);
            border: 1px dashed #f59e0b;
        }}
        .missing-photo-placeholder span {{
            display: block;
            font-weight: 700;
            font-size: 12px;
            margin-bottom: 3px;
        }}
        .missing-photo-placeholder small {{
            display: block;
            opacity: 0.85;
            margin-bottom: 5px;
            word-break: break-all;
            font-size: 10px;
        }}
        .missing-photo-placeholder p {{
            font-size: 10px;
            line-height: 1.3;
        }}
        .evidence-box.no-photo {{
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            text-align: center;
            gap: 6px;
            background: var(--bg-page);
            border: 1px dashed var(--border);
            border-radius: var(--radius-md);
            padding: 14px 10px;
            color: var(--text-muted);
            height: 100%;
            min-height: 100px;
        }}
        .evidence-box.no-photo .icon {{
            font-size: 24px;
        }}
        .evidence-box.no-photo strong {{
            color: var(--text-main);
            font-size: 12px;
        }}
        .evidence-box.no-photo p {{
            font-size: 11px;
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
        .print-header {{
            display: none;
        }}
        @media print {{
            @page {{
                size: A4 portrait;
                margin: 8mm 10mm;
            }}
            body {{
                background: #ffffff !important;
                color: #000000 !important;
                padding: 0 !important;
                font-size: 8pt !important;
                line-height: 1.2 !important;
            }}
            .no-print, .actions-group, .search-container, .municipal-header, .dossier-footer {{
                display: none !important;
            }}
            .print-header {{
                display: flex !important;
                justify-content: space-between !important;
                align-items: center !important;
                border-bottom: 1.5px solid #0f172a !important;
                padding: 0 0 3px 0 !important;
                margin-bottom: 6px !important;
            }}
            .container {{
                max-width: 100% !important;
                margin: 0 !important;
                padding: 0 !important;
            }}
            .dossier-card {{
                display: flex !important;
                flex-direction: row !important;
                gap: 10px !important;
                align-items: stretch !important;
                box-shadow: none !important;
                border: 1px solid #94a3b8 !important;
                border-radius: 6px !important;
                padding: 6px 10px !important;
                margin-bottom: 8px !important;
                page-break-inside: avoid !important;
                break-inside: avoid !important;
                background: #ffffff !important;
                min-height: 105px !important;
            }}
            .card-left {{
                flex: 1 !important;
                min-width: 0 !important;
                display: flex !important;
                flex-direction: column !important;
                justify-content: space-between !important;
            }}
            .card-right {{
                width: 140px !important;
                min-width: 140px !important;
                max-width: 140px !important;
                border-left: 1px solid #e2e8f0 !important;
                padding-left: 8px !important;
                margin: 0 !important;
                display: flex !important;
                flex-direction: column !important;
                align-items: center !important;
                justify-content: center !important;
            }}
            .card-header {{
                display: flex !important;
                justify-content: space-between !important;
                align-items: center !important;
                margin-bottom: 3px !important;
            }}
            .report-tag {{
                font-size: 7pt !important;
                color: #64748b !important;
                display: inline-block !important;
                margin-right: 6px !important;
            }}
            .biz-name {{
                font-size: 11pt !important;
                font-weight: 800 !important;
                display: inline-block !important;
                margin: 0 !important;
                color: #0f172a !important;
            }}
            .location-badge {{
                font-size: 7.5pt !important;
                display: inline-block !important;
                margin-left: 6px !important;
                color: #475569 !important;
            }}
            .result-badge {{
                font-size: 7pt !important;
                padding: 1.5px 6px !important;
                font-weight: 700 !important;
            }}
            .meta-grid {{
                display: grid !important;
                grid-template-columns: repeat(3, 1fr) !important;
                gap: 2px 6px !important;
                padding: 3px 6px !important;
                margin-bottom: 3px !important;
                background: #f8fafc !important;
                border: 1px solid #e2e8f0 !important;
                border-radius: 4px !important;
            }}
            .meta-item .lbl {{
                font-size: 6pt !important;
                color: #64748b !important;
                text-transform: uppercase !important;
            }}
            .meta-item .val {{
                font-size: 7.5pt !important;
                font-weight: 600 !important;
                color: #0f172a !important;
            }}
            .remarks-box {{
                padding: 3px 6px !important;
                margin-bottom: 0 !important;
                border-left-width: 2.5px !important;
                border-radius: 3px !important;
            }}
            .remarks-label {{
                font-size: 6pt !important;
            }}
            .remarks-box p {{
                font-size: 7.5pt !important;
                line-height: 1.15 !important;
                margin-top: 1px !important;
            }}
            .evidence-section {{
                margin: 0 !important;
                padding: 0 !important;
                width: 100% !important;
                display: flex !important;
                flex-direction: column !important;
                align-items: center !important;
                justify-content: center !important;
            }}
            .evidence-header {{
                font-size: 6pt !important;
                margin-bottom: 2px !important;
                text-align: center !important;
            }}
            .photos-grid {{
                display: flex !important;
                flex-wrap: wrap !important;
                gap: 4px !important;
                justify-content: center !important;
                align-items: center !important;
                width: 100% !important;
            }}
            .photo-thumb-wrap {{
                border-radius: 4px !important;
                max-width: 130px !important;
                width: 100% !important;
            }}
            .photo-thumb-wrap img {{
                height: 80px !important;
                max-height: 80px !important;
                width: 100% !important;
                object-fit: cover !important;
                display: block !important;
            }}
            .photo-caption {{
                font-size: 5.5pt !important;
                padding: 1px 3px !important;
                text-align: center !important;
            }}
            .evidence-box.no-photo {{
                padding: 6px 4px !important;
                gap: 2px !important;
                border-radius: 4px !important;
                width: 100% !important;
                text-align: center !important;
                border: 1px dashed #cbd5e1 !important;
                background: #f8fafc !important;
                min-height: 80px !important;
                justify-content: center !important;
            }}
            .evidence-box.no-photo .icon {{
                font-size: 14px !important;
            }}
            .evidence-box.no-photo strong {{
                font-size: 7pt !important;
                display: block !important;
            }}
            .evidence-box.no-photo p {{
                font-size: 6pt !important;
                margin: 0 !important;
                line-height: 1.1 !important;
            }}
            .missing-photo-placeholder {{
                padding: 4px 6px !important;
                font-size: 6.5pt !important;
                border-radius: 4px !important;
                border: 1px dashed #f59e0b !important;
                background: #fffbeb !important;
                color: #92400e !important;
                text-align: center !important;
                width: 100% !important;
                line-height: 1.15 !important;
            }}
            .missing-photo-placeholder span {{
                font-size: 7pt !important;
                font-weight: 700 !important;
                display: block !important;
                margin-bottom: 1px !important;
            }}
            .missing-photo-placeholder small {{
                font-size: 5.5pt !important;
                display: block !important;
                margin-bottom: 2px !important;
                word-break: break-all !important;
            }}
            .missing-photo-placeholder p {{
                font-size: 5.5pt !important;
                margin: 0 !important;
            }}
            /* Maximize space: Up to 4 reports per page cleanly */
            .dossier-card:nth-of-type(4n) {{
                page-break-after: always !important;
                break-after: page !important;
                margin-bottom: 0 !important;
            }}
        }}
    </style>
</head>
<body>
    <div class="container">
        <!-- Compact Header for Print Mode Only -->
        <div class="print-header">
            <div>
                <strong style="font-size: 10pt; text-transform: uppercase;">MUNICIPALITY OF MATAASNAKAHOY &bull; BPLO</strong>
                <div style="font-size: 7.5pt; color: #475569;">REVELA Inspection Compliance Dossier &bull; {html.escape(filter_title)}</div>
            </div>
            <div style="text-align: right; font-size: 7.5pt; color: #475569;">
                <div>Archived: {date_formatted}</div>
                <div>Total Reports: <strong>{total_reports}</strong></div>
            </div>
        </div>

        <!-- Full Municipal Header for Screen Mode Only -->
        <header class="municipal-header no-print">
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
        cutoff_date = (datetime.now() - timedelta(days=days)
                       ) if days > 0 else None

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
                clean_name = (re.sub(r"[^\w\-_]", "_", b_name)
                              [:30]).strip("_") or "Business"
                barangay = rep.get("barangayName") or "Mataasnakahoy"
                inspector = rep.get("inspectorName") or "Inspector"
                result_color = rep.get("inspectionResult") or "Verified"
                notice_lvl = rep.get("noticeLevel") if rep.get(
                    "noticeLevel") is not None else 0
                remarks = rep.get("remarks") or ""
                ir_ts = str(rep.get("irTimestamp") or "")
                deadline_val = str(rep.get("deadline") or "")
                res_time = rep.get("resolutionTime") if rep.get(
                    "resolutionTime") is not None else ""
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
                        local_filepath = os.path.join(
                            evidence_dir, orig_filename)

                        ext = os.path.splitext(orig_filename)[1].lower()
                        if ext not in (".jpg", ".jpeg", ".png", ".webp"):
                            ext = ".jpg"
                        archive_arcname = f"evidence/Report_{rep_id}_{clean_name}_{date_str}_{idx+1}{ext}"

                        if os.path.isfile(local_filepath):
                            zip_file.write(
                                local_filepath, arcname=archive_arcname)
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
            dossier_html = _build_html_dossier(
                reports_for_dossier, filter_type, datetime.now())
            zip_file.writestr("inspection_dossier.html",
                              dossier_html.encode("utf-8"))

            # 2. Audit manifest spreadsheet
            zip_file.writestr(
                "manifest.csv", manifest_stream.getvalue().encode("utf-8-sig"))

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
            zip_file.writestr("README_ARCHIVE.txt",
                              readme_text.encode("utf-8"))

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
    """Archive verified evidence with recoverable filesystem/DB changes."""
    return cleanup_evidence(mysql.connection, evidence_dir, filter_type)
