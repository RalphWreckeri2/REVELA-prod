"""Black-lock guard for official_registry.

Black means the permanent blackLocked bit OR a Revoked permit. Revoked must
remain protected even on databases without the optional ladder columns.
The legacy Blacklisted status is the compatibility spelling of Revoked.

This module imports nothing, like its sibling api/registry/colors.py, so it
stays cheap to import and trivial to unit test with a fake cursor.
"""

#: The column this guard reads. Absent until the ladder migration is applied.
LOCK_COLUMN = "blackLocked"

_LOCK_PROBE_SQL = """SELECT COLUMN_NAME
FROM information_schema.COLUMNS
WHERE TABLE_SCHEMA = DATABASE()
  AND TABLE_NAME = 'official_registry'
  AND COLUMN_NAME = %s"""

_LOCK_READ_SQL = f"""SELECT {LOCK_COLUMN}, applicationStatus
FROM official_registry
WHERE businessID = %s
LIMIT 1"""

_lock_column_present = None


class BlackLockedError(RuntimeError):
    """Raised when an action was refused because the business is Black locked.

    Carries business_id and action so a Phase 2 route can log the refusal into
    registry_enforcement_events without re-deriving either value from the
    message string.
    """

    def __init__(self, action, business_id):
        self.action = action
        self.business_id = business_id
        super().__init__(
            f"Refused to {action}: business {business_id} is Black locked. "
            "Only a SUPER_ADMIN unlock may clear the lock."
        )


def lock_column_available(cursor):
    """True once official_registry.blackLocked exists. Probed once, then cached.

    Cached because the answer cannot change without a migration, and this is
    called on write paths. Pass a fresh cursor after a migration, or call
    reset_lock_column_cache().
    """
    global _lock_column_present
    if _lock_column_present is not None:
        return _lock_column_present
    cursor.execute(_LOCK_PROBE_SQL, (LOCK_COLUMN,))
    _lock_column_present = cursor.fetchone() is not None
    return _lock_column_present


def reset_lock_column_cache():
    """Forget the probe result. For tests and for re-probing after a migration."""
    global _lock_column_present
    _lock_column_present = None


def _truthy_lock_value(raw):
    """Read the column as a lock, tolerating NULL and driver type drift.

    TINYINT(1) arrives as 0/1 over most drivers, but a dict cursor returns a
    mapping and a misconfigured driver can hand back a string. Anything that
    is not clearly off counts as locked.
    """
    if raw is None:
        return False
    if isinstance(raw, dict):
        raw = raw.get(LOCK_COLUMN)
        if raw is None:
            return False
    if isinstance(raw, str):
        return raw.strip().lower() not in ("", "0", "false", "none", "null")
    return bool(raw)


def is_black_locked(cursor, business_id):
    """True for a lock bit or Revoked status, even without ladder columns."""
    if not business_id:
        return False
    has_lock = lock_column_available(cursor)
    sql = (_LOCK_READ_SQL if has_lock else
           "SELECT applicationStatus FROM official_registry WHERE businessID = %s LIMIT 1")
    cursor.execute(sql, (business_id,))
    row = cursor.fetchone()
    if row is None:
        return False
    if isinstance(row, dict):
        return (has_lock and _truthy_lock_value(row)) or row.get(
            "applicationStatus") in ("Revoked", "Blacklisted")
    status = (row[1] if len(row) > 1 else None) if has_lock else row[0]
    return (has_lock and _truthy_lock_value(row[0])) or status in (
        "Revoked", "Blacklisted")


def assert_not_black_locked(cursor, business_id, *, action):
    """Refuse the action if this business is Black locked. Returns True otherwise.

    `action` is a short human phrase used in the error message, e.g.
    "write the registry flag colour" or "sync this business".
    """
    if is_black_locked(cursor, business_id):
        raise BlackLockedError(action, business_id)
    return True


# ── Append-only enforcement history ──────────────────────────────────────────

#: The event types registry_enforcement_events accepts.
#:
#: black_relocked is Phase 3A and needs migrations/20261016_01. Until that
#: migration runs, an insert carrying it is rejected by the ENUM, which is
#: safe: the single-use grant is only spendable after the migration anyway.
WARNING_ISSUED = "warning_issued"
WARNING_CLEARED = "warning_cleared"
BLACK_LOCKED = "black_locked"
BLACK_UNLOCKED = "black_unlocked"
BLACK_RELOCKED = "black_relocked"

ENFORCEMENT_EVENT_TYPES = (
    WARNING_ISSUED, WARNING_CLEARED, BLACK_LOCKED, BLACK_UNLOCKED,
    BLACK_RELOCKED,
)

_INSERT_ENFORCEMENT_EVENT_SQL = """INSERT INTO registry_enforcement_events (
    businessID, eventType, actorUserID, reason,
    previousLevel, newLevel, previousBlack, newBlack
) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)"""


def record_enforcement_event(cursor, *, business_id, event_type,
                             actor_user_id=None, reason=None,
                             previous_level=None, new_level=None,
                             previous_black=None, new_black=None):
    """Append one row to registry_enforcement_events on the caller's cursor.

    Deliberately takes a cursor rather than opening its own connection, so the
    event lands in the same transaction as the change it records. If the
    transaction rolls back, so does the history.

    The caller is responsible for ensuring the table exists; see the migration
    preflight in migrations/20261015_01_enforcement_ladder_schema.sql.
    """
    if event_type not in ENFORCEMENT_EVENT_TYPES:
        raise ValueError("unknown enforcement event type: %r" % (event_type,))
    cursor.execute(_INSERT_ENFORCEMENT_EVENT_SQL, (
        business_id, event_type, actor_user_id, reason,
        _as_int(previous_level), _as_int(new_level),
        None if previous_black is None else int(bool(previous_black)),
        None if new_black is None else int(bool(new_black)),
    ))


def _as_int(value):
    """None stays None; anything else becomes an int, or None if unreadable."""
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
