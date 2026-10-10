import secrets
import threading

from flask_jwt_extended import create_access_token

from app import mysql
from api.notifications import hub


_session_table_ready = False
_session_table_lock = threading.Lock()


def _ensure_session_table():
    global _session_table_ready
    if _session_table_ready:
        return
    with _session_table_lock:
        if _session_table_ready:
            return
        cursor = mysql.connection.cursor()
        try:
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS user_active_sessions (
                    userID INT NOT NULL PRIMARY KEY,
                    sessionID CHAR(32) NOT NULL,
                    clientType VARCHAR(16) NOT NULL,
                    issuedAt DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    KEY idx_session_id (sessionID)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """)
            mysql.connection.commit()
            _session_table_ready = True
        finally:
            cursor.close()


def issue_session_token(user, client_type):
    """Issue a token and atomically replace the account's previously active session."""
    _ensure_session_table()
    user_id = int(user["userID"])
    session_id = secrets.token_hex(16)
    token = create_access_token(
        identity=str(user_id),
        additional_claims={
            "role": user["userRole"],
            "mustChangePassword": bool(user.get("mustChangePassword", False)),
            "session_id": session_id,
            "client_type": client_type,
        },
    )

    cursor = mysql.connection.cursor()
    try:
        cursor.execute("""
            INSERT INTO user_active_sessions (userID, sessionID, clientType, issuedAt)
            VALUES (%s, %s, %s, CURRENT_TIMESTAMP)
            ON DUPLICATE KEY UPDATE
                sessionID = VALUES(sessionID),
                clientType = VALUES(clientType),
                issuedAt = VALUES(issuedAt)
        """, (user_id, session_id, client_type))
        mysql.connection.commit()
    except Exception:
        mysql.connection.rollback()
        raise
    finally:
        cursor.close()
    hub.publish_to_user(
        user_id,
        {
            "type": "session_replaced",
            "title": "Account signed in on another device",
            "body": "This session ended because the account signed in on another device. Please sign in again.",
        },
    )
    return token


def is_active_session(user_id, session_id):
    if not session_id:
        return False
    _ensure_session_table()
    cursor = mysql.connection.cursor()
    try:
        cursor.execute(
            "SELECT 1 FROM user_active_sessions WHERE userID = %s AND sessionID = %s",
            (user_id, session_id),
        )
        return cursor.fetchone() is not None
    finally:
        cursor.close()


def revoke_session(user_id, session_id):
    if not session_id:
        return
    _ensure_session_table()
    cursor = mysql.connection.cursor()
    try:
        cursor.execute(
            "DELETE FROM user_active_sessions WHERE userID = %s AND sessionID = %s",
            (user_id, session_id),
        )
        mysql.connection.commit()
    except Exception:
        mysql.connection.rollback()
        raise
    finally:
        cursor.close()
