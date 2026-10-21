"""Check the configured database's migration metadata in a READ ONLY session.

Does not start Flask, run schedulers, apply migrations, or read business records.
Uses existing config/environment credentials without printing them.
"""
import argparse
import json
from pathlib import Path
import sys


def inspect_schema(connection):
    cursor = connection.cursor()
    try:
        cursor.execute("SELECT DATABASE() AS schema_name, @@session.transaction_read_only AS read_only")
        session = cursor.fetchone()
        if not session["read_only"]:
            raise RuntimeError("A READ ONLY session is required for the schema check.")
        cursor.execute("""SELECT TABLE_NAME, COLUMN_NAME, COLUMN_TYPE, IS_NULLABLE
            FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = DATABASE()
              AND ((TABLE_NAME = 'official_registry' AND COLUMN_NAME = 'confirmedLogID')
                OR (TABLE_NAME = 'enforcement_state' AND COLUMN_NAME IN
                    ('warningLevel', 'blackLocked', 'blackDispatchUnlocked')))""")
        columns = {(row["TABLE_NAME"], row["COLUMN_NAME"]): row for row in cursor.fetchall()}
        cursor.execute("""SELECT INDEX_NAME, COLUMN_NAME FROM information_schema.STATISTICS
            WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'official_registry'
              AND NON_UNIQUE = 0 ORDER BY INDEX_NAME, SEQ_IN_INDEX""")
        indexes = {}
        for row in cursor.fetchall():
            indexes.setdefault(row["INDEX_NAME"], []).append(row["COLUMN_NAME"])
        cursor.execute("""SELECT k.REFERENCED_TABLE_NAME, k.REFERENCED_COLUMN_NAME,
                                 r.DELETE_RULE, r.UPDATE_RULE
            FROM information_schema.KEY_COLUMN_USAGE k
            JOIN information_schema.REFERENTIAL_CONSTRAINTS r
              ON r.CONSTRAINT_SCHEMA = k.CONSTRAINT_SCHEMA
             AND r.CONSTRAINT_NAME = k.CONSTRAINT_NAME AND r.TABLE_NAME = k.TABLE_NAME
            WHERE k.TABLE_SCHEMA = DATABASE() AND k.TABLE_NAME = 'official_registry'
              AND k.COLUMN_NAME = 'confirmedLogID'""")
        foreign_keys = cursor.fetchall()
        column = columns.get(("official_registry", "confirmedLogID"))
        checks = {
            "confirmed_pin_nullable_integer": bool(column and column["COLUMN_TYPE"].lower().startswith("int") and column["IS_NULLABLE"] == "YES"),
            "confirmed_pin_unique": ["confirmedLogID"] in indexes.values(),
            "confirmed_pin_foreign_key": any(
                row["REFERENCED_TABLE_NAME"] == "geospatial_logs" and row["REFERENCED_COLUMN_NAME"] == "logID"
                and row["DELETE_RULE"] in ("RESTRICT", "NO ACTION") and row["UPDATE_RULE"] in ("RESTRICT", "NO ACTION")
                for row in foreign_keys),
            "enforcement_columns": all(("enforcement_state", name) in columns for name in (
                "warningLevel", "blackLocked", "blackDispatchUnlocked")),
        }
        return {"schema": session["schema_name"], "read_only": True,
                "status": "ready" if all(checks.values()) else "migration_required", "checks": checks}
    finally:
        cursor.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--connect-timeout", type=int, default=5)
    args = parser.parse_args()
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from config import Config
    import MySQLdb
    from MySQLdb.cursors import DictCursor

    connection = None
    try:
        connection = MySQLdb.connect(
            host=Config.MYSQL_HOST, port=Config.MYSQL_PORT,
            user=Config.MYSQL_USER, passwd=Config.MYSQL_PASSWORD, db=Config.MYSQL_DB,
            charset="utf8mb4", cursorclass=DictCursor, connect_timeout=args.connect_timeout,
            init_command="SET SESSION TRANSACTION READ ONLY",
        )
        result = inspect_schema(connection)
        result["target_scope"] = "loopback" if Config.MYSQL_HOST.lower() in ("localhost", "127.0.0.1", "::1") else "configured_remote"
        print(json.dumps(result, indent=2))
        return 0 if result["status"] == "ready" else 1
    except (MySQLdb.Error, RuntimeError, TypeError) as error:
        # Do not echo connection strings, hostnames or credentials in diagnostics.
        error_code = error.args[0] if error.args and isinstance(error.args[0], int) else None
        print(json.dumps({"status": "unavailable", "mysql_error_code": error_code,
                          "message": "Configured schema could not be checked. No migrations or data writes were run."}, indent=2))
        return 2
    finally:
        if connection is not None:
            connection.rollback()
            connection.close()


if __name__ == "__main__":
    raise SystemExit(main())
