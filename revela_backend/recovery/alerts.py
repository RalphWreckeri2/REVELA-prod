"""Admin inbox + independent HTTPS alert/cron-heartbeat delivery."""
import logging
from urllib.parse import urlsplit

import requests

from recovery.storage import retry

log = logging.getLogger("revela.recovery")


def signal(url, event):
    if urlsplit(url).scheme != "https":
        raise ValueError("https_monitor_endpoint_required")
    def deliver():
        response = requests.post(url, json=event, timeout=(5, 15), allow_redirects=False)
        if not 200 <= response.status_code < 300:
            raise RuntimeError("monitor_delivery_failed")
    retry(deliver)


def admin_alert(event):
    """Inbox writes use the existing notification service; no open browser needed."""
    from flask import has_app_context
    if not has_app_context():
        return False
    try:
        from app import mysql
        from api.notifications.service import _ensure_tables
        from api.notifications import hub
        _ensure_tables()
        cursor = mysql.connection.cursor()
        try:
            cursor.execute("SELECT userID FROM users WHERE isActive=1 AND userRole IN ('Admin','SUPER_ADMIN','System Administrator')")
            admins = cursor.fetchall()
            body = ("Database backup needs attention: " + event["code"] +
                    ". Check Settings > Database Backups. Records since the last successful export may be at risk.")
            for admin in admins:
                cursor.execute("INSERT INTO revela_notifications (recipientUserId,type,title,body,link) VALUES (%s,%s,%s,%s,%s)",
                               (admin["userID"], "database_backup", "Database backup alert", body, "/settings"))
            mysql.connection.commit()
        finally:
            cursor.close()
        hub.publish_to_admins({"type": "database_backup_alert", "code": event["code"]})
        return bool(admins)
    except Exception:
        log.error("Database backup admin inbox delivery unavailable")
        return False


def failure_delivery(settings, event):
    result = {"admin_inbox": admin_alert(event)}
    try:
        signal(settings.alert_url, {"event": "database_backup_alert", **event})
        result["external_alert"] = "accepted_by_endpoint"
    except Exception:
        result["external_alert"] = "failed; independent missed-run monitor required"
        log.error("Database backup external alert delivery failed")
    return result
