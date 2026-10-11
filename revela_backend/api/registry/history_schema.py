import re


BASELINE_HISTORY_COLUMNS = (
    ("id", "bigint", "NO", None, "auto_increment"),
    ("businessID", "varchar(50)", "NO", None, ""),
    ("attemptedAt", "datetime", "NO", "CURRENT_TIMESTAMP", "DEFAULT_GENERATED"),
    ("outcome", "varchar(20)", "NO", None, ""),
    ("reason", "varchar(30)", "YES", None, ""),
    ("stackSize", "int", "YES", None, ""),
    ("oldLat", "decimal(10,8)", "YES", None, ""),
    ("oldLng", "decimal(11,8)", "YES", None, ""),
    ("newLat", "decimal(10,8)", "YES", None, ""),
    ("newLng", "decimal(11,8)", "YES", None, ""),
    ("placeID", "varchar(255)", "YES", None, ""),
    ("score", "decimal(4,3)", "YES", None, ""),
    ("failReason", "varchar(30)", "YES", None, ""),
    ("bestName", "varchar(120)", "YES", None, ""),
    ("bestScore", "decimal(4,3)", "YES", None, ""),
)

ADDED_HISTORY_COLUMNS = (
    ("reviewType", "VARCHAR(24)", "YES", None, ""),
    ("reviewKey", "CHAR(40)", "YES", None, ""),
    ("candidateSource", "VARCHAR(20)", "YES", None, ""),
    ("oldCoordSource", "VARCHAR(24)", "YES", None, ""),
    ("newCoordSource", "VARCHAR(24)", "YES", None, ""),
    ("oldPlaceID", "VARCHAR(255)", "YES", None, ""),
    ("oldPlaceIDKind", "VARCHAR(32)", "YES", None, ""),
    ("oldMatchScore", "DECIMAL(4,3)", "YES", None, ""),
    ("oldMatchStatus", "VARCHAR(24)", "YES", None, ""),
    ("oldAddress", "TEXT", "YES", None, ""),
    ("newAddress", "TEXT", "YES", None, ""),
    ("oldBarangayID", "INT", "YES", None, ""),
    ("newBarangayID", "INT", "YES", None, ""),
    ("actorUserID", "BIGINT", "YES", None, ""),
    ("decisionAt", "DATETIME", "YES", None, ""),
)

ALL_HISTORY_COLUMNS = BASELINE_HISTORY_COLUMNS + ADDED_HISTORY_COLUMNS
REQUIRED_HISTORY_COLUMNS = frozenset(
    definition[0] for definition in ALL_HISTORY_COLUMNS
)


def _row_value(row, name):
    if isinstance(row, (tuple, list)):
        index = {
            "COLUMN_NAME": 0,
            "COLUMN_TYPE": 1,
            "IS_NULLABLE": 2,
            "COLUMN_DEFAULT": 3,
            "EXTRA": 4,
        }.get(name.upper())
        return row[index] if index is not None and index < len(row) else None
    for key in (name, name.upper(), name.lower()):
        if key in row:
            return row[key]
    return None


def _normalize_type(value):
    return re.sub(r"\s+", "", str(value or "").casefold())


def _normalize_default(value):
    if value is None:
        return None
    normalized = str(value).strip().upper()
    if normalized.endswith("()"):
        normalized = normalized[:-2]
    return normalized


def _definition_mismatches(actual, expected):
    name, column_type, nullable, default, extra = expected
    actual_type = _row_value(actual, "COLUMN_TYPE")
    actual_nullable = _row_value(actual, "IS_NULLABLE")
    actual_default = _row_value(actual, "COLUMN_DEFAULT")
    actual_extra = _row_value(actual, "EXTRA")
    mismatches = []

    if _normalize_type(actual_type) != _normalize_type(column_type):
        mismatches.append(
            f"{name}: type {actual_type!r}, expected {column_type}")
    if str(actual_nullable or "").upper() != nullable:
        mismatches.append(
            f"{name}: nullability {actual_nullable!r}, expected {nullable}"
        )
    if _normalize_default(actual_default) != _normalize_default(default):
        mismatches.append(
            f"{name}: default {actual_default!r}, expected {default!r}"
        )
    if str(actual_extra or "").casefold() != extra.casefold():
        mismatches.append(
            f"{name}: extra {actual_extra!r}, expected {extra!r}")
    return mismatches


def validate_history_columns(actual_rows, allow_missing_additions=False):
    """Return (missing additions, definition errors) for information_schema rows."""
    actual_by_name = {
        str(_row_value(row, "COLUMN_NAME")).casefold(): row
        for row in actual_rows
        if _row_value(row, "COLUMN_NAME") is not None
    }
    missing_additions = []
    errors = []

    for expected in BASELINE_HISTORY_COLUMNS:
        name = expected[0]
        actual = actual_by_name.get(name.casefold())
        if actual is None:
            errors.append(f"missing baseline column {name}")
        else:
            errors.extend(_definition_mismatches(actual, expected))

    for expected in ADDED_HISTORY_COLUMNS:
        name = expected[0]
        actual = actual_by_name.get(name.casefold())
        if actual is None:
            if allow_missing_additions:
                missing_additions.append(name)
            else:
                errors.append(f"missing required column {name}")
        else:
            errors.extend(_definition_mismatches(actual, expected))

    return tuple(missing_additions), tuple(errors)
