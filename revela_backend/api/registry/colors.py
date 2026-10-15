"""Shared SQL builders and the pure-Python equivalent of the flag colour.

These two builders used to live in api/analytics/routes.py. They were moved
here verbatim so that api/registry/service.py can reuse the exact expression
the Map already uses, without importing the analytics blueprint (which pulls in
google-genai and scikit-learn at import time).

Nothing in this module may gain imports. It must stay dependency-free so both
readers can import it cheaply and without side effects.

Both builders return a SQL expression STRING. They take the alias of the
geospatial_logs relation to read from and emit no bind parameters.

status_to_color() is the pure-Python twin of _effective_flag_color_sql. It
exists so a single, testable place defines the ladder order, instead of every
caller growing its own copy (api/registry/service.py still carries a private
_status_to_flag_color with the old status-only table).

Precedence, highest first:
    Black lock  >  Orange warning  >  registry status  >  stored pin colour

The Black lock and the Orange warning come from official_registry.warningLevel
and official_registry.blackLocked. Neither is written by anything yet, so the
SQL builders only emit those two arms when the caller opts in with
ladder=True AND the columns are actually present. See _effective_flag_color_sql.

The stored geospatial_logs.flagColor is used only when the pin has no registry
match, which is the only case where the registry cannot speak.
"""

# ── Pure-Python ladder ────────────────────────────────────────────────────────

#: Registry status -> colour. The historical table, unchanged.
STATUS_COLORS = {
    "Active": "Green",
    "Pending": "Yellow",
    "Expired": "Red",
    "Revoked": "Black",
    "Blacklisted": "Black",
    "Closed": "Purple",
}

#: A status this build does not recognise is treated as unvetted, not compliant.
UNKNOWN_STATUS_COLOR = "Yellow"

#: The first warning level that means "Orange". Level 0 means "no warning".
FIRST_WARNING_LEVEL = 1


def _coerce_level(value):
    """Best-effort int for a level that may arrive as None, '' or a string."""
    if value is None or value is False:
        return 0
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def status_to_color(status, *, warning_level=0, black_locked=False):
    """Resolve one registry row to its flag colour, Black > Orange > status.

    status           official_registry.applicationStatus, or None.
    warning_level    official_registry.warningLevel, 0..3. None/''/'x' count
                     as 0 so an unreadable value never invents a warning.
    black_locked     official_registry.blackLocked. Any truthy value locks.

    Unlike the SQL there is no stored pin colour to fall back to, so an
    unrecognised status resolves to Yellow, matching the long-standing
    _status_to_flag_color in api/registry/service.py. That is the one place the
    two implementations legitimately disagree: the SQL's ELSE arm returns the
    pin colour because only the SQL has the pin in scope.
    """
    if black_locked:
        return "Black"
    if _coerce_level(warning_level) >= FIRST_WARNING_LEVEL:
        return "Orange"
    return STATUS_COLORS.get(status, UNKNOWN_STATUS_COLOR)


# ── Column availability probe ─────────────────────────────────────────────────

#: Columns the ladder arms read. Absent until
#: migrations/20261015_01_enforcement_ladder_schema.sql has been applied.
LADDER_COLUMNS = ("warningLevel", "blackLocked")

_LADDER_PROBE_SQL = """SELECT COLUMN_NAME
FROM information_schema.COLUMNS
WHERE TABLE_SCHEMA = DATABASE()
  AND TABLE_NAME = 'official_registry'
  AND COLUMN_NAME IN (%s, %s)"""

_ladder_columns_present = None

#: The single column _LADDER_PROBE_SQL selects, and the key a DictCursor row
#: carries it under.
_PROBE_COLUMN = "COLUMN_NAME"


def _probe_column_name(row):
    """Read COLUMN_NAME out of a probe row, for either cursor shape.

    config.py sets MYSQL_CURSORCLASS = "DictCursor", so in the running app every
    row is a mapping and row[0] raises KeyError: 0. Scripts and tests connect
    with the default tuple cursor, so both shapes reach this function. The
    probe is the one place here that must not assume either - a dict row is
    truthy, so it would otherwise be swallowed by a bare except and read as
    "column absent", quietly disabling the ladder on a migrated database.
    """
    if isinstance(row, dict):
        return row.get(_PROBE_COLUMN)
    try:
        return row[0]
    except (TypeError, KeyError, IndexError):
        return None


def ladder_columns_available(cursor):
    """True once both ladder columns exist. Probed once, then cached.

    Cached because the answer cannot change without a migration, and this sits
    on the request path of every Map, Registry and Analytics query. A database
    that has not been migrated yet answers False, which is what keeps the
    ladder arms out of the SQL entirely.
    """
    global _ladder_columns_present
    if _ladder_columns_present is not None:
        return _ladder_columns_present
    cursor.execute(_LADDER_PROBE_SQL, LADDER_COLUMNS)
    found = {_probe_column_name(row) for row in cursor.fetchall()}
    _ladder_columns_present = all(col in found for col in LADDER_COLUMNS)
    return _ladder_columns_present


def reset_ladder_column_cache():
    """Forget the probe result. For tests and for re-probing after a migration."""
    global _ladder_columns_present
    _ladder_columns_present = None


# ── SQL builders ──────────────────────────────────────────────────────────────


def _registry_match_sql(alias="g"):
    """The correlated official_registry match shared by every lookup below."""
    return f"""(
            (r_chk.businessID IS NOT NULL AND {alias}.businessID IS NOT NULL
                AND r_chk.businessID = {alias}.businessID)
            OR ({alias}.placeID IS NOT NULL AND r_chk.placeID = {alias}.placeID
                AND ({alias}.businessID IS NULL OR r_chk.businessID = {alias}.businessID))
            OR ({alias}.businessID IS NULL
                AND r_chk.barangayID = {alias}.barangayID
                AND r_chk.businessName = {alias}.detectedName)
        )"""


def _registry_column_sql(alias, column):
    """One column from the single winning registry row for this pin.

    The ORDER BY and LIMIT pick exactly one row, the same way for every column,
    so warningLevel and blackLocked are always read from the row the status
    came from. A pin with no registry match yields NULL for all three.
    """
    return f"""(
        SELECT r_chk.{column}
        FROM official_registry r_chk
        WHERE {_registry_match_sql(alias)}
        ORDER BY (r_chk.businessID = {alias}.businessID) DESC,
                 (r_chk.placeID = {alias}.placeID) DESC
        LIMIT 1
    )"""


def _registry_status_sql(alias="g"):
    return f"""(
        SELECT r_chk.applicationStatus
        FROM official_registry r_chk
        WHERE {_registry_match_sql(alias)}
        ORDER BY (r_chk.businessID = {alias}.businessID) DESC,
                 (r_chk.placeID = {alias}.placeID) DESC
        LIMIT 1
    )"""


def _verified_orange_sql(alias="g"):
    """True when this pin has a verified Orange inspection behind it.

    TEMPORARY FALLBACK - REMOVE IN PHASE 2.

    warningLevel is not written by anything yet, so this stands in for the
    ladder until Phase 2 makes verify_inspection write the real level. Until
    then it is the only thing that can produce Orange on a registered row.

    The old form of this predicate additionally required the matched registry
    row to be Expired. That restriction is gone: a verified Orange inspection
    now makes the pin Orange whatever the status. The registration is
    unsigned here, so this is the intended user-visible change of Phase 1.
    """
    return f"""(
        EXISTS (
            SELECT 1 FROM inspection_reports ir
            WHERE ir.targetType = 'geospatial_log'
              AND ir.targetID = {alias}.logID
              AND ir.verificationStatus = 'Verified'
              AND ir.inspectionResult = 'Orange'
        )
    )"""


def _effective_flag_color_sql(alias="g", *, ladder=False):
    """The derived colour every reader must use.

    ladder=True adds the two Black-lock / Orange-warning arms. It is opt-in and
    off by default because official_registry.warningLevel and .blackLocked may
    not exist yet: MySQL raises "Unknown column" at execution time for a column
    that is not there, so a builder that always emitted the ladder arms would
    break every Map, Registry and Analytics query on an unmigrated database.

    With ladder=False the emitted SQL is byte-for-byte what it has always been,
    apart from the dropped Expired restriction in _verified_orange_sql. Phase 2
    passes ladder=ladder_columns_available(cursor) at the call sites once the
    migration has run and something writes the columns.
    """
    registry_status = _registry_status_sql(alias)

    ladder_arms = ""
    if ladder:
        # COALESCE so a pin with no registry row, or a row whose columns are
        # still NULL, resolves to "no lock, no warning" instead of falling
        # through the CASE.
        ladder_arms = f"""        WHEN COALESCE({_registry_column_sql(alias, "blackLocked")}, 0) <> 0 THEN 'Black'
        WHEN COALESCE({_registry_column_sql(alias, "warningLevel")}, 0) >= {FIRST_WARNING_LEVEL} THEN 'Orange'
"""

    return f"""CASE
{ladder_arms}        WHEN {_verified_orange_sql(alias)} THEN 'Orange'
        WHEN {registry_status} = 'Active' THEN 'Green'
        WHEN {registry_status} = 'Expired' THEN 'Red'
        WHEN {registry_status} IN ('Revoked', 'Blacklisted') THEN 'Black'
        WHEN {registry_status} = 'Closed' THEN 'Purple'
        WHEN {registry_status} = 'Pending' THEN 'Yellow'
        ELSE {alias}.flagColor
    END"""
