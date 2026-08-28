#!/usr/bin/env python3
import os
from pathlib import Path

import pymysql


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


def column_exists(cursor, table: str, column: str) -> bool:
    cursor.execute(f"SHOW COLUMNS FROM {table} LIKE %s", (column,))
    return cursor.fetchone() is not None


def main() -> None:
    env_path = Path(__file__).resolve().parent.parent / ".env"
    env = load_env(env_path)

    host = env.get("DB_HOST", os.getenv("DB_HOST", "127.0.0.1"))
    port = int(env.get("DB_PORT", os.getenv("DB_PORT", "3306")))
    user = env.get("DB_USER", os.getenv("DB_USER"))
    password = env.get("DB_PASSWORD", os.getenv("DB_PASSWORD"))
    database = env.get("DB_NAME", os.getenv("DB_NAME", "revela_db"))

    if not user or not password:
        raise SystemExit("MySQL credentials are not configured in .env")

    conn = pymysql.connect(
        host=host,
        port=port,
        user=user,
        password=password,
        database=database,
        autocommit=True,
        cursorclass=pymysql.cursors.DictCursor,
    )
    try:
        with conn.cursor() as cursor:
            table = "geospatial_logs"
            columns = [
                ("notes", "TEXT NULL"),
                ("reportedByUserID", "INT DEFAULT NULL"),
                ("noticeLevel", "INT DEFAULT 0"),
            ]

            for column_name, definition in columns:
                if column_exists(cursor, table, column_name):
                    print(f"Column '{column_name}' already exists on {table}.")
                    continue

                if column_name == "notes":
                    cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column_name} {definition} AFTER placeID")
                else:
                    cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column_name} {definition}")
                print(f"Added column '{column_name}' to {table}.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
