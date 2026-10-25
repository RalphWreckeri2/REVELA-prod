"""Guarded, opt-in schema change; never run automatically or on import.

Dry-run unless --apply and --acknowledge-backup are both supplied. Does not
rewrite events; historical DATETIME(0) ordering remains ambiguous.
"""
import argparse
from pathlib import Path


MIGRATION = (Path(__file__).resolve().parents[1]
             / "migrations/20261026_01_inspection_lifecycle_precision.sql")


def inspect(cursor, expected_database):
    cursor.execute("SELECT DATABASE() AS selected_database")
    if cursor.fetchone()["selected_database"] != expected_database:
        raise RuntimeError("Selected database does not match --expect-database.")
    cursor.execute("""SELECT COLUMN_TYPE, IS_NULLABLE, COLUMN_DEFAULT
                      FROM information_schema.COLUMNS
                      WHERE TABLE_SCHEMA = DATABASE()
                        AND TABLE_NAME = 'inspection_lifecycle_events'
                        AND COLUMN_NAME = 'eventTimestamp'""")
    row = cursor.fetchone()
    if not row or row["IS_NULLABLE"] != "NO":
        raise RuntimeError("eventTimestamp is missing or not the expected NOT NULL column.")
    kind = row["COLUMN_TYPE"].lower()
    default = str(row["COLUMN_DEFAULT"] or "").lower()
    if (kind not in ("datetime", "datetime(6)")
            or default not in ("current_timestamp", "current_timestamp()", "current_timestamp(6)")):
        raise RuntimeError("Unexpected eventTimestamp definition; review the schema manually.")
    return kind


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expect-database", required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--acknowledge-backup", action="store_true")
    args = parser.parse_args()
    if args.apply and not args.acknowledge_backup:
        parser.error("--apply requires --acknowledge-backup")

    # Importing configuration and opening a connection occurs only on an
    # explicit CLI invocation. Do not print connection details or credentials.
    from config import Config
    import MySQLdb
    from MySQLdb.cursors import DictCursor

    connection = MySQLdb.connect(
        host=Config.MYSQL_HOST, port=Config.MYSQL_PORT, user=Config.MYSQL_USER,
        passwd=Config.MYSQL_PASSWORD, db=Config.MYSQL_DB,
        charset="utf8mb4", cursorclass=DictCursor, connect_timeout=5,
    )
    try:
        cursor = connection.cursor()
        try:
            kind = inspect(cursor, args.expect_database)
            if kind == "datetime(6)":
                print("Already migrated; no schema changes made.")
                return 0
            if not args.apply:
                print("Preflight passed. No changes made; --apply requires explicit approval and backup acknowledgement.")
                return 0
            cursor.execute(MIGRATION.read_text(encoding="utf-8"))
            connection.commit()
            if inspect(cursor, args.expect_database) != "datetime(6)":
                raise RuntimeError("Postflight did not find DATETIME(6).")
            print("Future inspection events now retain microseconds; historical timestamps were not reconstructed.")
            return 0
        finally:
            cursor.close()
    finally:
        connection.close()


if __name__ == "__main__":
    raise SystemExit(main())
