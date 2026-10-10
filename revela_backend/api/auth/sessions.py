import secrets
import threading
from datetime import timedelta

from flask import current_app, has_app_context
from flask_jwt_extended import create_access_token

from app import mysql


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


# ── First-login-wins session policy ───────────────────────────────────────────
#
# An account owns exactly one active session.  ``userID`` is the primary key of
# ``user_active_sessions``, so the row itself is the lock: a login may only take
# the slot by inserting.  There is deliberately no ``ON DUPLICATE KEY UPDATE``,
# because that would let the *second* login overwrite the first device's
# session.  A login that loses the insert races a valid session and is rejected
# instead.

# MySQL error raised when an INSERT collides with the ``userID`` primary key.
_DUPLICATE_ENTRY_ERRNO = 1062

# Mirrors ``Config.JWT_ACCESS_TOKEN_EXPIRES``.  Kept in sync with the JWT
# lifetime so a session row can never outlive the token it was issued with.
DEFAULT_SESSION_LIFETIME = timedelta(hours=12)

# An expired row is normally replaced on the first retry, so a handful of
# attempts is plenty.  The bound only exists so that pathological churn
# (repeated logout/login races) cannot spin forever.
_MAX_CLAIM_ATTEMPTS = 3

_CLIENT_LABELS = {
    "web": "a web browser",
    "mobile": "a mobile device",
}


class ActiveSessionConflict(Exception):
    """Raised when the account already holds a valid active session.

    The existing session is left completely untouched -- it is never overwritten,
    revoked, or expired early.
    """

    def __init__(self, active_client_type):
        self.active_client_type = active_client_type
        super().__init__(active_session_conflict_message(active_client_type))


def active_session_conflict_message(client_type):
    """User-facing explanation for a refused login.

    Wording is deliberately free of the words the clients key off when deciding
    an account was revoked by an administrator.
    """
    label = _CLIENT_LABELS.get(
        str(client_type or "").strip().lower(), "another device"
    )
    return (
        f"This account is already signed in on {label}. Sign out on that device "
        "first, or wait for the current session to expire."
    )


def session_lifetime_hours():
    """Session lifetime in hours, read from the app's JWT access-token lifetime.

    Expiry is always evaluated with the database's ``CURRENT_TIMESTAMP`` (see the
    SQL below) so it cannot drift from the value written to ``issuedAt``.  This
    helper only supplies the interval length.
    """
    if has_app_context():
        expires = current_app.config.get("JWT_ACCESS_TOKEN_EXPIRES")
        if isinstance(expires, timedelta):
            return max(expires.total_seconds() / 3600.0, 0.0)
        if isinstance(expires, (int, float)):
            return max(float(expires) / 3600.0, 0.0)
    return DEFAULT_SESSION_LIFETIME.total_seconds() / 3600.0


def _is_duplicate_entry(exc):
    """True when ``exc`` is MySQL's duplicate-key error."""
    args = getattr(exc, "args", None) or ()
    return bool(args) and args[0] == _DUPLICATE_ENTRY_ERRNO


def _row_value(row, key, index):
    """Read a column from a DB row regardless of DictCursor/tuple cursors."""
    if row is None:
        return None
    try:
        return row[key]
    except (TypeError, KeyError, IndexError):
        try:
            return row[index]
        except (TypeError, KeyError, IndexError):
            return None


def claim_active_session(user_id, session_id, client_type):
    """Atomically claim the account's single active-session slot.

    Succeeds by inserting a new row.  If a row already exists the insert is
    rejected by the primary key, and only a row that has already expired is
    cleared and retried -- a live session is never modified or removed.

    Raises:
        ActiveSessionConflict: a valid session already owns the slot.
    """
    user_id = int(user_id)
    lifetime_hours = session_lifetime_hours()
    cursor = mysql.connection.cursor()
    try:
        for _ in range(_MAX_CLAIM_ATTEMPTS):
            try:
                cursor.execute("""
                    INSERT INTO user_active_sessions (userID, sessionID, clientType, issuedAt)
                    VALUES (%s, %s, %s, CURRENT_TIMESTAMP)
                """, (user_id, session_id, client_type))
                mysql.connection.commit()
                return session_id
            except Exception as exc:
                mysql.connection.rollback()
                if not _is_duplicate_entry(exc):
                    raise

            # The insert lost the race against an existing row.  Look only for a
            # session that is still within its lifetime; an expired row does not
            # hold the slot.
            cursor.execute("""
                SELECT sessionID, clientType
                FROM user_active_sessions
                WHERE userID = %s
                  AND issuedAt > CURRENT_TIMESTAMP - INTERVAL %s HOUR
            """, (user_id, lifetime_hours))
            active = cursor.fetchone()
            if active is not None:
                raise ActiveSessionConflict(_row_value(active, "clientType", 1))

            # Nothing valid is holding the slot, so drop only expired rows.  The
            # expiry predicate means this can never remove a live session, even
            # if a new one appears between the SELECT and this DELETE.
            cursor.execute("""
                DELETE FROM user_active_sessions
                WHERE userID = %s
                  AND issuedAt <= CURRENT_TIMESTAMP - INTERVAL %s HOUR
            """, (user_id, lifetime_hours))
            mysql.connection.commit()

        # Never reached in practice; avoids returning a token with no session.
        raise RuntimeError("Could not claim the active session slot.")
    finally:
        cursor.close()


def issue_session_token(user, client_type):
    """Issue a token for the account's single active session.

    Raises:
        ActiveSessionConflict: another login already holds a valid session.
            That session is left untouched.
    """
    _ensure_session_table()
    user_id = int(user["userID"])
    session_id = secrets.token_hex(16)

    # Mint the token before claiming the slot.  If the claim is refused the
    # token is simply discarded, which is far better than the reverse order,
    # which would strand the account with a claimed slot and no usable token.
    token = create_access_token(
        identity=str(user_id),
        additional_claims={
            "role": user["userRole"],
            "mustChangePassword": bool(user.get("mustChangePassword", False)),
            "session_id": session_id,
            "client_type": client_type,
        },
    )

    # First login wins: this either claims the slot or raises, in which case the
    # first device keeps its session and never receives a "session replaced"
    # notice.
    claim_active_session(user_id, session_id, client_type)
    return token


def is_active_session(user_id, session_id):
    """True only while this exact session is the account's live session."""
    if not session_id:
        return False
    _ensure_session_table()
    cursor = mysql.connection.cursor()
    try:
        cursor.execute("""
            SELECT 1 FROM user_active_sessions
            WHERE userID = %s AND sessionID = %s
              AND issuedAt > CURRENT_TIMESTAMP - INTERVAL %s HOUR
        """, (int(user_id), session_id, session_lifetime_hours()))
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
            (int(user_id), session_id),
        )
        mysql.connection.commit()
    except Exception:
        mysql.connection.rollback()
        raise
    finally:
        cursor.close()