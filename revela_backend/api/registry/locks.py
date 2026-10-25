"""Black-lock guard and enforcement audit writer.

Black means the permanent blackLocked bit OR a Revoked permit. Revoked must
remain protected independently of enforcement_state. The legacy Blacklisted
status is the compatibility spelling of Revoked.

This module imports nothing, like its sibling api/registry/colors.py, so it
stays cheap to import and trivial to unit test with a fake cursor.
"""


class BlackLockedError(RuntimeError):
    """Raised when an action was refused because the business is Black locked.

    Carries business_id and action so a route can log the refusal into
    enforcement_events without re-deriving either value from the
    message string.
    """

    def __init__(self, action, business_id):
        self.action = action
        self.business_id = business_id
        super().__init__(
            f"Refused to {action}: business {business_id} is Black locked. "
            "Black businesses cannot be edited or deleted."
        )


def reset_lock_column_cache():
    """Compatibility no-op retained for callers and tests."""
    return None


def _truthy_lock_value(raw):
    """Read the column as a lock, tolerating NULL and driver type drift.

    TINYINT(1) arrives as 0/1 over most drivers, but a dict cursor returns a
    mapping and a misconfigured driver can hand back a string. Anything that
    is not clearly off counts as locked.
    """
    if raw is None:
        return False
    if isinstance(raw, dict):
        raw = raw.get("blackLocked")
        if raw is None:
            return False
    if isinstance(raw, str):
        return raw.strip().lower() not in ("", "0", "false", "none", "null")
    return bool(raw)


def is_black_locked(cursor, business_id):
    """True for enforcement_state.blackLocked or a revoked permit."""
    if not business_id:
        return False
    cursor.execute(
        """SELECT es.blackLocked, r.applicationStatus
           FROM official_registry r
           LEFT JOIN enforcement_state es
             ON es.subjectType = 'business'
            AND es.subjectID = CAST(r.businessID AS CHAR)
           WHERE r.businessID = %s
           LIMIT 1""",
        (business_id,),
    )
    row = cursor.fetchone()
    if row is None:
        return False
    if isinstance(row, dict):
        return _truthy_lock_value(row) or row.get(
            "applicationStatus") in ("Revoked", "Blacklisted")
    return _truthy_lock_value(row[0]) or row[1] in (
        "Revoked", "Blacklisted")


def assert_not_black_locked(cursor, business_id, *, action):
    """Refuse the action if this business is Black locked. Returns True otherwise.

    `action` is a short human phrase used in the error message, e.g.
    "write the registry flag colour" or "sync this business".
    """
    if is_black_locked(cursor, business_id):
        raise BlackLockedError(action, business_id)
    return True


class BlackBusinessDeletionForbidden(PermissionError):
    """Deleting a Black business requires the exact SUPER_ADMIN role. HTTP 403."""


def assert_business_deletable(cursor, business_id, actor_role):
    if is_black_locked(cursor, business_id):
        raise BlackBusinessDeletionForbidden(
            "Black businesses cannot be deleted, including by SUPER_ADMIN.")
    return True


# ── Append-only enforcement history ──────────────────────────────────────────

#: The event types enforcement_events accepts, including legacy grant history.
WARNING_ISSUED = "warning_issued"
WARNING_CLEARED = "warning_cleared"
BLACK_LOCKED = "black_locked"
BLACK_UNLOCKED = "black_unlocked"
BLACK_RELOCKED = "black_relocked"
COMPLIANCE_CONFIRMED = "compliance_confirmed"

ENFORCEMENT_EVENT_TYPES = (
    WARNING_ISSUED, WARNING_CLEARED, BLACK_LOCKED, BLACK_UNLOCKED,
    BLACK_RELOCKED, COMPLIANCE_CONFIRMED,
)

_INSERT_ENFORCEMENT_EVENT_SQL = """INSERT INTO enforcement_events (
    subjectType, subjectID, eventType, actorUserID, reason,
    previousLevel, newLevel, previousBlack, newBlack, createdAt
) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, UTC_TIMESTAMP(6))"""


def record_enforcement_event(cursor, *, business_id=None, subject_type="business",
                             subject_id=None, event_type,
                             actor_user_id=None, reason=None,
                             previous_level=None, new_level=None,
                             previous_black=None, new_black=None):
    """Append one row to enforcement_events on the caller's cursor.

    Deliberately takes a cursor rather than opening its own connection, so the
    event lands in the same transaction as the change it records. If the
    transaction rolls back, so does the history.

    Pass business_id for registered records, or subject_type/subject_id for
    a geospatial pin. The caller owns the transaction.
    """
    if event_type not in ENFORCEMENT_EVENT_TYPES:
        raise ValueError("unknown enforcement event type: %r" % (event_type,))
    resolved_subject_id = subject_id if subject_id is not None else business_id
    if resolved_subject_id is None:
        raise ValueError("an enforcement event requires a subject ID")
    cursor.execute(_INSERT_ENFORCEMENT_EVENT_SQL, (
        subject_type, str(
            resolved_subject_id), event_type, actor_user_id, reason,
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
