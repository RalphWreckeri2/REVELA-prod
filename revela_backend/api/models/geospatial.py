from app import mysql


#: Where a map pin came from. Stored on the row by
#: migrations/20261017_01_geospatial_source.sql, so the Map can say where a pin
#: is from instead of inferring it from which columns happen to be set.
#:
#:   registry            came from official_registry (import, sync, snap)
#:   registry_detected   a registry business that Google Places also found
#:   detection           found by a scan, no registry link
#:   manual              an inspector reported it from the field
#:   unknown             we cannot tell. Never guess.
#:
#: 'unknown' is the default on purpose: guessing is worse than admitting it.
SOURCE_REGISTRY = "registry"
SOURCE_REGISTRY_DETECTED = "registry_detected"
SOURCE_DETECTION = "detection"
SOURCE_MANUAL = "manual"
SOURCE_UNKNOWN = "unknown"

SOURCE_VALUES = (
    SOURCE_REGISTRY, SOURCE_REGISTRY_DETECTED, SOURCE_DETECTION,
    SOURCE_MANUAL, SOURCE_UNKNOWN,
)

SOURCE_COLUMN = "source"

_source_column_present = None


def geospatial_source_column_exists(cursor):
    """True once geospatial_logs.source exists. Probed once, then cached.

    Cached because the answer cannot change without a migration and this sits
    on the write path of every detection and flag submission.
    """
    global _source_column_present
    if _source_column_present is not None:
        return _source_column_present
    cursor.execute(
        """SELECT COLUMN_NAME FROM information_schema.COLUMNS
           WHERE TABLE_SCHEMA = DATABASE()
             AND TABLE_NAME = 'geospatial_logs'
             AND COLUMN_NAME = %s""",
        (SOURCE_COLUMN,),
    )
    _source_column_present = cursor.fetchone() is not None
    return _source_column_present


def reset_source_column_cache():
    """Forget the probe result. For tests, and after running the migration."""
    global _source_column_present
    _source_column_present = None


def with_source(cursor, columns, values, params, source):
    """Append `source` to an INSERT only when the column exists.

    Returns (columns_sql, values_sql, params). When the column is absent the
    INSERT is returned untouched, because MySQL raises "Unknown column" at
    execution time for a column that is not there - naming it would break the
    insert itself, not merely skip a label.

    Every caller uses this rather than hand-rolling the check, so "is the
    column there" is answered in exactly one place.
    """
    if source not in SOURCE_VALUES:
        raise ValueError("unknown geospatial source: %r" % (source,))
    if not geospatial_source_column_exists(cursor):
        return columns, values, tuple(params)
    return (_append_inside_parens(columns, SOURCE_COLUMN),
            _append_inside_parens(values, "%s"),
            tuple(params) + (source,))


def _append_inside_parens(group, item):
    """Insert `item` before the closing paren: "(a, b)" -> "(a, b, source)".

    The closing paren has to move. Appending after it would produce
    "(a, b), source", which is not a column list at all - and the INSERT would
    fail at the database rather than in a test.
    """
    head, separator, tail = group.strip().rpartition(")")
    if not separator:
        return f"{group.strip()}, {item}"
    return f"{head.rstrip()}, {item}{separator}{tail}"


def insert_green_flag(barangay_id, business_name, lat, lng, address=None, color='Green', business_id=None):
    cursor = mysql.connection.cursor()
    columns, values, params = with_source(
        cursor,
        """(barangayID, businessID, detectedName, latitude, longitude,
                 flagColor, nearestLandmark)""",
        "(%s, %s, %s, %s, %s, %s, %s)",
        (barangay_id, business_id, business_name, lat, lng, color, address),
        SOURCE_REGISTRY,
    )
    cursor.execute(
        f"INSERT INTO geospatial_logs {columns} VALUES {values}", params)
    cursor.close()


def get_latest_flag(business_name, barangay_id):
    """Get the most recent flagColor for a business."""
    cursor = mysql.connection.cursor()
    cursor.execute(
        """
        SELECT flagColor, detectedDate
        FROM geospatial_logs
        WHERE detectedName = %s AND barangayID = %s
        ORDER BY detectedDate DESC
        LIMIT 1
        """,
        (business_name, barangay_id),
    )
    row = cursor.fetchone()
    cursor.close()
    return row
