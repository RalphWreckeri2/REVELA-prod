import threading
from typing import Any, Dict, List, Optional, Tuple

import requests
import os

from app import mysql
from api.notifications import hub

_tables_ready = False


def _ensure_tables() -> None:
    global _tables_ready
    if _tables_ready:
        return
    cur = mysql.connection.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS revela_notifications (
            id INT AUTO_INCREMENT PRIMARY KEY,
            recipientUserId INT NOT NULL,
            type VARCHAR(64) NOT NULL,
            title VARCHAR(255) NOT NULL,
            body TEXT,
            link VARCHAR(512),
            readAt DATETIME NULL,
            createdAt DATETIME DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_recipient (recipientUserId, readAt),
            INDEX idx_created (createdAt)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS user_app_preferences (
            userID INT PRIMARY KEY,
            email_inspection_alerts TINYINT(1) NOT NULL DEFAULT 1,
            updatedAt DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
    )
    mysql.connection.commit()
    cur.close()
    _tables_ready = True


def get_email_inspection_alerts(user_id: int) -> bool:
    _ensure_tables()
    cur = mysql.connection.cursor()
    cur.execute(
        "SELECT email_inspection_alerts FROM user_app_preferences WHERE userID = %s",
        (user_id,),
    )
    row = cur.fetchone()
    cur.close()
    if row is None:
        return True
    v = row.get("email_inspection_alerts")
    return bool(v) if v is not None else True


def set_email_inspection_alerts(user_id: int, enabled: bool) -> None:
    _ensure_tables()
    cur = mysql.connection.cursor()
    cur.execute(
        """
        INSERT INTO user_app_preferences (userID, email_inspection_alerts)
        VALUES (%s, %s)
        ON DUPLICATE KEY UPDATE email_inspection_alerts = VALUES(email_inspection_alerts)
        """,
        (user_id, 1 if enabled else 0),
    )
    mysql.connection.commit()
    cur.close()


def list_notifications(user_id: int, limit: int = 50) -> Tuple[Dict[str, Any], None]:
    _ensure_tables()
    cur = mysql.connection.cursor()
    cur.execute(
        """
        SELECT id, type, title, body, link, readAt, createdAt
        FROM revela_notifications
        WHERE recipientUserId = %s
        ORDER BY createdAt DESC
        LIMIT %s
        """,
        (user_id, limit),
    )
    rows = cur.fetchall()
    cur.close()
    for r in rows:
        if r.get("createdAt"):
            r["createdAt"] = str(r["createdAt"])
        if r.get("readAt"):
            r["readAt"] = str(r["readAt"])
    return {"data": rows}, None


def unread_count(user_id: int) -> Tuple[Dict[str, Any], None]:
    _ensure_tables()
    cur = mysql.connection.cursor()
    cur.execute(
        """
        SELECT COUNT(*) AS n FROM revela_notifications
        WHERE recipientUserId = %s AND readAt IS NULL
        """,
        (user_id,),
    )
    n = cur.fetchone()["n"]
    cur.close()
    return {"count": n}, None


def mark_notifications_read(user_id: int, notif_ids: Optional[List[int]] = None) -> Tuple[Dict[str, Any], None]:
    _ensure_tables()
    cur = mysql.connection.cursor()
    if notif_ids:
        placeholders = ",".join(["%s"] * len(notif_ids))
        cur.execute(
            f"""
            UPDATE revela_notifications SET readAt = NOW()
            WHERE recipientUserId = %s AND id IN ({placeholders}) AND readAt IS NULL
            """,
            (user_id, *notif_ids),
        )
    else:
        cur.execute(
            """
            UPDATE revela_notifications SET readAt = NOW()
            WHERE recipientUserId = %s AND readAt IS NULL
            """,
            (user_id,),
        )
    mysql.connection.commit()
    affected = cur.rowcount
    cur.close()
    return {"updated": affected}, None


def delete_notifications(user_id: int, notif_ids: Optional[List[int]] = None) -> Tuple[Dict[str, Any], None]:
    _ensure_tables()
    cur = mysql.connection.cursor()
    if notif_ids:
        placeholders = ",".join(["%s"] * len(notif_ids))
        cur.execute(
            f"""
            DELETE FROM revela_notifications
            WHERE recipientUserId = %s AND id IN ({placeholders})
            """,
            (user_id, *notif_ids),
        )
    else:
        cur.execute(
            """
            DELETE FROM revela_notifications
            WHERE recipientUserId = %s
            """,
            (user_id,),
        )
    mysql.connection.commit()
    affected = cur.rowcount
    cur.close()
    return {"deleted": affected}, None


def _send_resend_email(to_email: str, subject: str, text_body: str) -> bool:
    key = os.getenv("RESEND_API_KEY")
    from_addr = os.getenv("RESEND_FROM")
    if not key or not from_addr:
        return False
    try:
        r = requests.post(
            "https://api.resend.com/emails",
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
            },
            json={
                "from": from_addr,
                "to": [to_email],
                "subject": subject,
                "text": text_body,
            },
            timeout=15,
        )
        return r.status_code in (200, 201)
    except Exception as e:
        print(f"Resend inspection alert error: {e}")
        return False


def notify_inspection_assigned(
    report_id: int,
    log_id: int,
    inspector_user_id: int,
    status: str = "Assigned",
) -> None:
    """In-app notification for the inspector when admin assigns or reassigns."""
    try:
        _ensure_tables()
        cur = mysql.connection.cursor()

        cur.execute(
            "SELECT detectedName FROM geospatial_logs WHERE logID = %s",
            (log_id,),
        )
        g = cur.fetchone() or {}
        biz = g.get("detectedName") or f"Log #{log_id}"

        if status == "Reassigned":
            title = "Inspection sent back for redo"
            body = (
                f"An administrator returned “{biz}” for a new field visit. "
                f"Open the map to submit fresh evidence and remarks (report #{report_id})."
            )
        else:
            title = "New inspection assigned"
            body = (
                f"You have been assigned to inspect “{biz}”. "
                f"Open the map to view the site and submit your report (report #{report_id})."
            )

        cur.execute(
            """
            INSERT INTO revela_notifications
                (recipientUserId, type, title, body, link)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (
                int(inspector_user_id),
                "inspection_assigned",
                title,
                body,
                "/home",
            ),
        )
        mysql.connection.commit()
        mysql.connection.commit()
        cur.close()
    except Exception as e:
        print(f"notify_inspection_assigned error: {e}")

def notify_password_reset_request(inspector_name: str) -> None:
    """In-app notification for all admins when an inspector requests a manual password reset."""
    try:
        _ensure_tables()
        cur = mysql.connection.cursor()

        cur.execute(
            """
            SELECT userID FROM USERS
            WHERE userRole IN ('Admin', 'SUPER_ADMIN', 'System Administrator')
            """
        )
        admins = cur.fetchall() or []

        title = "Password Reset Requested"
        body = f"{inspector_name} has requested a manual password reset. Open User Management to generate a temporary password."
        link = "/users"

        for a in admins:
            aid = int(a["userID"])
            cur.execute(
                """
                INSERT INTO revela_notifications
                    (recipientUserId, type, title, body, link)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (aid, "password_reset_requested", title, body, link),
            )

        mysql.connection.commit()
        cur.close()

        # Push real-time event to all connected admins
        hub.publish_to_admins({
            "type": "password_reset_requested",
            "title": title,
            "body": body,
            "link": link
        })
    except Exception as e:
        print(f"notify_password_reset_request error: {e}")


def notify_inspection_submitted(
    report_id: int,
    log_id: int,
    inspector_user_id: int,
    inspection_result: str,
    has_evidence_photo: bool,
) -> None:
    """
    Insert in-app rows for each admin, push SSE, optionally email admins who opted in.
    """
    try:
        _ensure_tables()
        cur = mysql.connection.cursor()

        cur.execute(
            "SELECT fullName FROM USERS WHERE userID = %s",
            (inspector_user_id,),
        )
        insp_row = cur.fetchone() or {}
        inspector_name = insp_row.get("fullName") or "Inspector"

        cur.execute(
            "SELECT detectedName FROM geospatial_logs WHERE logID = %s",
            (log_id,),
        )
        g = cur.fetchone() or {}
        biz = g.get("detectedName") or f"Log #{log_id}"

        cur.execute(
            """
            SELECT userID, email, fullName FROM USERS
            WHERE userRole IN ('Admin', 'SUPER_ADMIN', 'System Administrator')
            """
        )
        admins = cur.fetchall() or []

        title = "Inspection submitted"
        photo_note = " Evidence photo attached." if has_evidence_photo else ""
        body = (
            f"{inspector_name} submitted a field inspection for “{biz}”. "
            f"Recorded result: {inspection_result}.{photo_note} "
            f"Open Inspections to review (report #{report_id})."
        )
        link = "/inspections"

        for a in admins:
            aid = int(a["userID"])
            cur.execute(
                """
                INSERT INTO revela_notifications
                    (recipientUserId, type, title, body, link)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (aid, "inspection_submitted", title, body, link),
            )

        mysql.connection.commit()
        cur.close()

        hub.publish_to_admins(
            {
                "type": "inspection_submitted",
                "reportID": report_id,
                "logID": log_id,
                "title": title,
                "body": body,
                "link": link,
            }
        )

        # Pre-fetch email preferences in the main thread to avoid Flask app context errors
        recipients = []
        for a in admins:
            aid = int(a["userID"])
            email = (a.get("email") or "").strip()
            if email and get_email_inspection_alerts(aid):
                recipients.append(email)

        def _emails(targets):
            for email in targets:
                _send_resend_email(
                    email,
                    f"[REVELA] {title} — {biz}",
                    body + "\n\n— REVELA Municipality Dashboard",
                )

        if recipients:
            threading.Thread(target=_emails, args=(
                recipients,), daemon=True).start()

    except Exception as e:
        print(f"notify_inspection_submitted error: {e}")


def notify_yellow_flag_reported(
    log_id: int,
    business_name: str,
    barangay_id: int,
    reporter_user_id: int,
    flag_color: str = "Yellow",
) -> None:
    """
    Notify all admins when an inspector manually flags a suspected / closed business.
    Inserts in-app notification rows + pushes SSE event to connected admin streams.
    """
    try:
        _ensure_tables()
        cur = mysql.connection.cursor()

        # Inspector name
        cur.execute(
            "SELECT fullName FROM USERS WHERE userID = %s",
            (reporter_user_id,),
        )
        insp_row = cur.fetchone() or {}
        inspector_name = insp_row.get("fullName") or "An inspector"

        # Barangay name
        cur.execute(
            "SELECT barangayName FROM barangays WHERE barangayID = %s",
            (barangay_id,),
        )
        brgy_row = cur.fetchone() or {}
        barangay_name = brgy_row.get("barangayName") or f"Barangay #{barangay_id}"

        # All admins
        cur.execute(
            """
            SELECT userID FROM USERS
            WHERE userRole IN ('Admin', 'SUPER_ADMIN', 'System Administrator')
            """
        )
        admins = cur.fetchall() or []

        color_label = "closed" if flag_color == "Orange" else "suspected unregistered"
        title = f"Yellow Flag — {color_label.title()} Business Reported"
        body = (
            f"{inspector_name} flagged \"{business_name}\" in {barangay_name} "
            f"as a {color_label} business. Open the Map to review (log #{log_id})."
        )
        link = "/map"

        for a in admins:
            aid = int(a["userID"])
            cur.execute(
                """
                INSERT INTO revela_notifications
                    (recipientUserId, type, title, body, link)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (aid, "yellow_flag_reported", title, body, link),
            )

        mysql.connection.commit()
        cur.close()

        hub.publish_to_admins(
            {
                "type": "yellow_flag_reported",
                "logID": log_id,
                "title": title,
                "body": body,
                "link": link,
                "flagColor": flag_color,
            }
        )

    except Exception as e:
        print(f"notify_yellow_flag_reported error: {e}")

