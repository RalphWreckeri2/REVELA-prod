#!/usr/bin/env python3
import argparse
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from api.registry.history_schema import (  # noqa: E402
    ADDED_HISTORY_COLUMNS,
    validate_history_columns,
)


DATABASE_NAME = "railway"
TABLE_NAME = "registry_pin_history"


class MigrationPreflightError(RuntimeError):
    pass


def load_env(path: Path) -> dict:
    values = {}
    if not path.exists():
        return values
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def _required_setting(env, key):
    value = env.get(key, os.getenv(key))
    if not value:
        raise MigrationPreflightError(
            f"Database setting {key} is not configured")
    return value


def preflight(cursor):
    cursor.execute("SELECT DATABASE() AS selected_database")
    database_row = cursor.fetchone()
    database = database_row.get("selected_database") if database_row else None
    if database != DATABASE_NAME:
        raise MigrationPreflightError(
            f"Wrong selected database {database!r}; expected {DATABASE_NAME!r}"
        )

    cursor.execute(
        "SELECT TABLE_NAME, ENGINE FROM information_schema.TABLES "
        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s",
        (TABLE_NAME,),
    )
    table_row = cursor.fetchone()
    if not table_row:
        raise MigrationPreflightError(
            f"Required table {TABLE_NAME} does not exist")
    if str(table_row.get("ENGINE") or "").casefold() != "innodb":
        raise MigrationPreflightError(
            f"{TABLE_NAME} must use InnoDB; found {table_row.get('ENGINE')!r}"
        )

    cursor.execute(
        "SELECT COLUMN_NAME, COLUMN_TYPE, IS_NULLABLE, COLUMN_DEFAULT, EXTRA "
        "FROM information_schema.COLUMNS "
        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s",
        (TABLE_NAME,),
    )
    columns = cursor.fetchall()
    missing, errors = validate_history_columns(
        columns, allow_missing_additions=True)
    if errors:
        raise MigrationPreflightError("; ".join(errors))
    return missing


def build_alter_statement(missing_columns):
    allowlist = {definition[0]: definition[1]
                 for definition in ADDED_HISTORY_COLUMNS}
    missing = set(missing_columns)
    if not missing:
        return None
    if not missing.issubset(allowlist):
        unexpected = ", ".join(sorted(missing - allowlist.keys()))
        raise MigrationPreflightError(
            f"Refusing non-allowlisted columns: {unexpected}")

    additions = [
        f"ADD COLUMN `{name}` {allowlist[name]} NULL"
        for name, _type, _nullable, _default, _extra in ADDED_HISTORY_COLUMNS
        if name in missing
    ]
    return f"ALTER TABLE `{TABLE_NAME}` " + ", ".join(additions)


def apply_migration(connection, apply=False):
    cursor = connection.cursor(dictionary=True)
    try:
        missing = preflight(cursor)
        statement = build_alter_statement(missing)
        if statement is None:
            return {"added": (), "statement": None, "verified": True}
        if not apply:
            return {"added": tuple(missing), "statement": statement, "verified": False}

        cursor.execute(statement)
        remaining = preflight(cursor)
        if remaining:
            raise MigrationPreflightError(
                "Postflight is missing columns: " + ", ".join(remaining)
            )
        return {"added": tuple(missing), "statement": statement, "verified": True}
    finally:
        cursor.close()


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Validate and optionally add registry_pin_history audit columns."
    )
    parser.add_argument(
        "--apply", action="store_true",
        help="execute the validated ALTER TABLE; without this flag only preflight",
    )
    args = parser.parse_args(argv)

    env_path = PROJECT_ROOT / ".env"
    env = load_env(env_path)
    database = env.get("DB_NAME", os.getenv("DB_NAME"))
    if database != DATABASE_NAME:
        raise SystemExit(
            f"Refusing connection: DB_NAME must be {DATABASE_NAME!r}, "
            f"found {database!r}"
        )

    try:
        host = _required_setting(env, "DB_HOST")
        port = int(_required_setting(env, "DB_PORT"))
        user = _required_setting(env, "DB_USER")
        password = _required_setting(env, "DB_PASSWORD")
    except (MigrationPreflightError, ValueError) as error:
        raise SystemExit(str(error)) from error

    import mysql.connector

    connection = mysql.connector.connect(
        host=host,
        port=port,
        user=user,
        password=password,
        database=DATABASE_NAME,
        autocommit=True,
    )
    try:
        result = apply_migration(connection, apply=args.apply)
    except MigrationPreflightError as error:
        raise SystemExit(f"Migration preflight failed: {error}") from error
    finally:
        connection.close()

    if result["verified"]:
        print("registry_pin_history schema verified; no further migration is needed")
    elif args.apply:
        print("Added and verified columns: " + ", ".join(result["added"]))
    else:
        print("Preflight passed; no changes made. Missing columns: "
              + ", ".join(result["added"]))
        print("Add --apply only after explicit deployment approval.")


if __name__ == "__main__":
    main()
