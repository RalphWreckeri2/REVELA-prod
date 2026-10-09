"""
Persistent admin-editable application settings.

Backed by a MySQL key/value table rather than a JSON file on disk, because
quota settings have to survive a redeploy and be identical for every worker.
(This differs from `api/analytics/service.py`, which stores the WLC weights in
`wlc_config.json` — fine for presentation weights, wrong for billing guards.)

Only administrators can reach the routes that write here; see
`api/admin_settings/routes.py`.
"""

import json
import threading

from app import mysql


_settings_table_ready = False
_settings_table_lock = threading.Lock()

TABLE_SCHEMA = """
CREATE TABLE IF NOT EXISTS revela_app_settings (
    settingKey   VARCHAR(96)  NOT NULL PRIMARY KEY,
    settingValue TEXT         NOT NULL,
    updatedBy    INT          DEFAULT NULL,
    updatedAt    DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP
                               ON UPDATE CURRENT_TIMESTAMP,
    KEY idx_settings_updated (updatedAt)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
"""


def ensure_settings_table():
    """Create the settings table once per process, retrying after a failure."""
    global _settings_table_ready
    if _settings_table_ready:
        return
    with _settings_table_lock:
        if _settings_table_ready:
            return
        cur = mysql.connection.cursor()
        try:
            cur.execute(TABLE_SCHEMA)
            mysql.connection.commit()
            _settings_table_ready = True
        finally:
            cur.close()


def load_all():
    """Return every persisted setting as a plain dict. Never raises."""
    try:
        ensure_settings_table()
    except Exception as exc:
        print(f"[app_settings] settings table unavailable ({exc}); "
              f"falling back to defaults")
        return {}
    cur = mysql.connection.cursor()
    try:
        cur.execute("SELECT settingKey, settingValue FROM revela_app_settings")
        rows = cur.fetchall() or []
    except Exception as exc:
        print(f"[app_settings] settings read failed ({exc}); "
              f"falling back to defaults")
        return {}
    finally:
        cur.close()

    values = {}
    for row in rows:
        key = row["settingKey"] if isinstance(row, dict) else row[0]
        raw = row["settingValue"] if isinstance(row, dict) else row[1]
        try:
            values[key] = json.loads(raw)
        except (TypeError, ValueError):
            # A hand-edited or corrupted row must not take the app down.
            print(f"[app_settings] Skipping malformed setting '{key}'")
    return values


def get(key, default=None):
    return load_all().get(key, default)


def save_many(entries, user_id=None):
    """Persist a batch of key/value settings. Returns (saved_count, error)."""
    if not entries:
        return 0, None
    try:
        ensure_settings_table()
    except Exception as exc:
        return 0, f"Settings storage is unavailable: {exc}"

    cur = mysql.connection.cursor()
    try:
        for key, value in entries.items():
            if not isinstance(key, str) or not key or len(key) > 96:
                return 0, f"Invalid setting key: {key!r}"
            cur.execute(
                "INSERT INTO revela_app_settings "
                "    (settingKey, settingValue, updatedBy) "
                "VALUES (%s, %s, %s) "
                "ON DUPLICATE KEY UPDATE "
                "    settingValue = VALUES(settingValue), "
                "    updatedBy = VALUES(updatedBy), "
                "    updatedAt = NOW()",
                (key, json.dumps(value), user_id),
            )
        mysql.connection.commit()
    except Exception as exc:
        mysql.connection.rollback()
        return 0, f"Could not persist settings: {exc}"
    finally:
        cur.close()
    return len(entries), None


def delete_many(keys):
    """Remove persisted overrides so the env baseline applies again."""
    if not keys:
        return 0, None
    try:
        ensure_settings_table()
    except Exception as exc:
        return 0, f"Settings storage is unavailable: {exc}"

    marks = ",".join(["%s"] * len(keys))
    cur = mysql.connection.cursor()
    try:
        cur.execute(
            f"DELETE FROM revela_app_settings WHERE settingKey IN ({marks})",
            tuple(keys),
        )
        removed = cur.rowcount or 0
        mysql.connection.commit()
    except Exception as exc:
        mysql.connection.rollback()
        return 0, f"Could not clear settings: {exc}"
    finally:
        cur.close()
    return removed, None
