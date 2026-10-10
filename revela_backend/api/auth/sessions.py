import secrets
import threading
import time
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


# ── Inactivity auto-logout (web portal) ───────────────────────────────────────
#
# A session idle for longer than this is refused by the backend.  This is a
# separate, shorter window than the 12-hour JWT expiry, which stays the hard
# ceiling.
#
# Only genuine user interaction reports activity (POST /api/auth/activity).
# Background traffic -- dashboard polling, notification SSE heartbeats, silent
# refreshes -- deliberately does NOT report activity, so it can never keep an
# abandoned session alive.
#
# ``_last_activity`` holds sessionID -> time.monotonic().  This is in-process
# state, the same single-worker model the SSE hub already relies on (see the
# Dockerfile note on ``--workers 1``).  When this process has not seen a session
# before -- a fresh login, or any session predating a restart -- the decision
# falls back to the database clock, so a restart never grants free grace.
DEFAULT_IDLE_TIMEOUT = timedelta(minutes=10)

_activity_lock = threading.Lock()
_last_activity = {}

# Message shown by the portal when the backend refuses an idle session.
IDLE_SESSION_MESSAGE = (
    "Your session ended due to inactivity. Please sign in again."
)


def idle_timeout_seconds():
    """Inactivity window in seconds, read from ``SESSION_IDLE_TIMEOUT``.

    Capped at the JWT lifetime. A session can only ever hold the account's slot
    while its token is alive, so an inactivity window longer than that would let
    a stale row block new logins for longer than the token that created it.
    """
    if has_app_context():
        configured = current_app.config.get("SESSION_IDLE_TIMEOUT")
        if isinstance(configured, timedelta):
            value = configured.total_seconds()
        elif isinstance(configured, (int, float)):
            value = float(configured)
        else:
            value = DEFAULT_IDLE_TIMEOUT.total_seconds()
        return max(min(value, session_lifetime_hours() * 3600.0), 0.0)
    return DEFAULT_IDLE_TIMEOUT.total_seconds()


def record_session_activity(session_id):
    """Mark a session as active right now (called on real user interaction)."""
    if not session_id:
        return
    now = time.monotonic()
    # Prune entries that can no longer influence any decision, so the map stays
    # bounded by the number of live sessions rather than growing forever.
    cutoff = idle_timeout_seconds() * 2
    with _activity_lock:
        for stale in [sid for sid, seen in _last_activity.items() if now - seen > cutoff]:
            del _last_activity[stale]
        _last_activity[session_id] = now


def seconds_since_activity(session_id):
    """Seconds since the last interaction, or ``None`` if unknown here."""
    if not session_id:
        return None
    now = time.monotonic()
    with _activity_lock:
        seen = _last_activity.get(session_id)
    if seen is None:
        return None
    return max(now - seen, 0.0)


def is_session_idle(session_id):
    """True only when this process *knows* the session has idled too long.

    Unknown sessions report False so callers fail closed (treat as active)
    rather than evicting a session on missing information.
    """
    elapsed = seconds_since_activity(session_id)
    if elapsed is None:
        return False
    return elapsed > idle_timeout_seconds()


def forget_session(session_id):
    if not session_id:
        return
    with _activity_lock:
        _last_activity.pop(session_id, None)


def _session_idle_since_issue(user_id, session_id):
    """Bootstrap check for a session this process has not seen.

    Compared with the database's ``CURRENT_TIMESTAMP`` rather than a Python
    timestamp: ``issuedAt`` is written with ``CURRENT_TIMESTAMP`` in the
    database's own timezone, so only the database can compare the two safely.
    """
    cursor = mysql.connection.cursor()
    try:
        cursor.execute("""
            SELECT 1 FROM user_active_sessions
            WHERE userID = %s AND sessionID = %s
              AND issuedAt <= CURRENT_TIMESTAMP - INTERVAL %s SECOND
        """, (int(user_id), session_id, idle_timeout_seconds()))
        return cursor.fetchone() is not None
    finally:
        cursor.close()


def _reject_if_idle(user_id, session_id):
    """True when the session must be refused for inactivity."""
    if session_is_idle(user_id, session_id, adopt=True):
        forget_session(session_id)
        return True
    return False


def session_is_idle(user_id, session_id, adopt=False):
    """Has this session gone too long without reported user interaction?

    Both the request path and the login path must answer this identically.
    When they disagree the login path fails closed on a session the request path
    would have already released, so a stale row keeps blocking new logins for
    the whole JWT lifetime.

    Falling back to the stored issue time is safe for the login path because the
    activity map is populated by *every* authenticated request: an entry that is
    missing means the session has made no request since this process started, so
    it cannot be a device that is genuinely active right now.

    Args:
        adopt: stamp the session as active when it is not idle. Only for the
            request path -- the login path must never extend someone else's
            session just because another device attempted to sign in.
    """
    elapsed = seconds_since_activity(session_id)
    if elapsed is not None:
        return elapsed > idle_timeout_seconds()

    if _session_idle_since_issue(user_id, session_id):
        return True
    if adopt:
        record_session_activity(session_id)
    return False


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
    minutes = max(int(idle_timeout_seconds() // 60), 1)
    return (
        f"This account is already signed in on {label}. Sign out on that device "
        f"first, or wait up to {minutes} minutes for that session to end on its own."
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
                active_session_id = _row_value(active, "sessionID", 0)
                if not session_is_idle(user_id, active_session_id):
                    raise ActiveSessionConflict(_row_value(active, "clientType", 1))

                # Either the previous session has already idled past the
                # inactivity limit, or this process has no activity record for
                # it and the stored issue time shows it is stale.  In both cases
                # it no longer holds the slot -- otherwise a device that walked
                # away could lock the account out for the full 12 hours.
                # Reuse revoke_session so cleanup is identical to every other
                # release path (explicit logout, inactivity eviction).
                cursor.fetchall()
                revoke_session(user_id, active_session_id)
                continue

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
    record_session_activity(session_id)
    return token


def check_active_session(user_id, session_id):
    """Return ``(is_active, code)``; ``code`` explains why a session is not active.

    ``session_idle``  -- refused for inactivity; the slot has been released.
    ``session_ended`` -- no such session (logged out, replaced, or expired).
    """
    if not session_id:
        return False, "session_ended"
    _ensure_session_table()
    cursor = mysql.connection.cursor()
    try:
        cursor.execute("""
            SELECT 1 FROM user_active_sessions
            WHERE userID = %s AND sessionID = %s
              AND issuedAt > CURRENT_TIMESTAMP - INTERVAL %s HOUR
        """, (int(user_id), session_id, session_lifetime_hours()))
        row_exists = cursor.fetchone() is not None
    finally:
        cursor.close()

    if not row_exists:
        forget_session(session_id)
        return False, "session_ended"

    if _reject_if_idle(int(user_id), session_id):
        # Release the slot immediately so another device can sign in instead of
        # waiting out the remaining JWT lifetime.
        revoke_session(user_id, session_id)
        return False, "session_idle"
    return True, None


def is_active_session(user_id, session_id):
    """True only while this exact session is the account's live, non-idle session."""
    active, _ = check_active_session(user_id, session_id)
    return active


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
        forget_session(session_id)