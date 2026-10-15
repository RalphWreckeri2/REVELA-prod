"""Black-lock guard for official_registry.

Phase 1 deliverable only: nothing calls this yet. Phase 2 wires it into the
verify write path, the sync path and the manual-edit path so that a Black
locked business cannot be moved by any of them.

What "Black locked" means: official_registry.blackLocked is the permanent
habitable-offender lock. It is independent of applicationStatus, so a row can
be blackLocked while its applicationStatus still reads Active. That is the
whole reason this guard exists and why applicationStatus cannot answer it.

Only a SUPER_ADMIN unlock may clear it, and that route does not exist yet.

Fail-safe rule: if official_registry.blackLocked does not exist - because
migrations/20261015_01_enforcement_ladder_schema.sql has not been applied - the
guard reports "not locked" and lets the caller proceed. That is deliberate.
The alternative, treating an unreadable lock as locked, would freeze every
write path on every database that has not been migrated yet. The cost is that
the guard is inert until the migration runs, so it must not be the only thing
standing between a locked row and an edit; Phase 2 is expected to add a
database-level check alongside it.

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

_LOCK_READ_SQL = f"""SELECT {LOCK_COLUMN}
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
    """True only when the row exists and its blackLocked column is set.

    False for a missing businessID, a missing row, an unmigrated database and
    a NULL column alike - see the module docstring for why unmigrated means
    "not locked" rather than "locked".
    """
    if not business_id:
        return False
    if not lock_column_available(cursor):
        return False
    cursor.execute(_LOCK_READ_SQL, (business_id,))
    row = cursor.fetchone()
    if row is None:
        return False
    if isinstance(row, dict):
        return _truthy_lock_value(row)
    return _truthy_lock_value(row[0])


def assert_not_black_locked(cursor, business_id, *, action):
    """Refuse the action if this business is Black locked. Returns True otherwise.

    `action` is a short human phrase used in the error message, e.g.
    "write the registry flag colour" or "sync this business".
    """
    if is_black_locked(cursor, business_id):
        raise BlackLockedError(action, business_id)
    return True
