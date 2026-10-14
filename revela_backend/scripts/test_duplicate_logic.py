"""Opt-in duplicate import/sync test for a disposable local MySQL database."""

import io
import os
import sys
from contextlib import ExitStack
from unittest.mock import patch

from flask import Flask


_OPT_IN = "REVELA_RUN_DUPLICATE_LOGIC_TEST"
_HOST = "REVELA_LOCAL_MYSQL_HOST"
_PORT = "REVELA_LOCAL_MYSQL_PORT"
_DATABASE = "REVELA_LOCAL_MYSQL_DATABASE"
_USER = "REVELA_LOCAL_MYSQL_USER"
_PASSWORD = "REVELA_LOCAL_MYSQL_PASSWORD"
_EXPECTED_HOST = "127.0.0.1"
_EXPECTED_DATABASE = "revela_test_duplicate_logic"
_EXPECTED_USER = "revela_duplicate_test"
_EXPECTED_ACCOUNT = "revela_duplicate_test@127.0.0.1"
_TEST_BUSINESS_IDS = ("B-001", "B-002")


def _local_database_settings():
    if os.getenv(_OPT_IN) != "1":
        raise RuntimeError(
            f"Refusing database changes: set {_OPT_IN}=1 to opt in."
        )

    host = os.getenv(_HOST)
    if host != _EXPECTED_HOST:
        raise RuntimeError(f"Refusing database changes: {_HOST} must be {_EXPECTED_HOST}.")

    database = os.getenv(_DATABASE)
    if database != _EXPECTED_DATABASE:
        raise RuntimeError(
            f"Refusing database changes: {_DATABASE} must be "
            f"{_EXPECTED_DATABASE}."
        )

    username = os.getenv(_USER)
    if username != _EXPECTED_USER:
        raise RuntimeError(
            f"Refusing database changes: {_USER} must be {_EXPECTED_USER}."
        )

    port_text = os.getenv(_PORT, "")
    if not port_text.isdecimal() or not 1 <= int(port_text) <= 65535:
        raise RuntimeError(
            f"Refusing database changes: {_PORT} must be a valid local port."
        )

    password = os.getenv(_PASSWORD)
    if not password:
        raise RuntimeError(
            f"Refusing database changes: provide {_PASSWORD} in the environment."
        )

    return host, int(port_text), database, username, password


def run_test():
    host, port, database, username, password = _local_database_settings()

    # Import application extensions and registry code only after local-only
    # opt-in and connection settings have been validated.
    sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from app import mysql
    from api.registry import service as registry_service

    app = Flask(__name__)
    app.config.update(
        MYSQL_HOST=host,
        MYSQL_PORT=port,
        MYSQL_USER=username,
        MYSQL_PASSWORD=password,
        MYSQL_DB=database,
        MYSQL_CURSORCLASS="DictCursor",
    )
    mysql.init_app(app)

    with app.app_context():
        cursor = mysql.connection.cursor()
        try:
            cursor.execute(
                "SELECT DATABASE() AS selected_database, "
                "CURRENT_USER() AS authenticated_account"
            )
            identity = cursor.fetchone()
            if (
                not identity
                or identity["selected_database"] != _EXPECTED_DATABASE
                or identity["authenticated_account"] != _EXPECTED_ACCOUNT
            ):
                raise RuntimeError(
                    "Refusing database changes: local database/account "
                    "identity check failed."
                )

            for table in ("official_registry", "geospatial_logs"):
                cursor.execute(f"SELECT COUNT(*) AS row_count FROM `{table}`")
                if cursor.fetchone()["row_count"]:
                    raise RuntimeError(
                        f"Refusing database changes: {table} must be empty."
                    )
        finally:
            cursor.close()

        csv_content = """Business ID,businessName,barangay,businessAddress,latitude,longitude
B-001,REVELA Synthetic Test Store,Lumanglipa,123 Main St,13.9667,121.1167
B-001,REVELA Synthetic Test Store,Lumanglipa,123 Main St,13.9667,121.1167
B-001,REVELA Synthetic Test Store,Lumanglipa,123 Main St,13.9667,121.1167
""".encode("utf-8")
        csv_content_sync = """Business ID,businessName,barangay,businessAddress,latitude,longitude
B-001,REVELA Synthetic Test Store,Lumanglipa,123 Main St,13.9667,121.1167
B-001,REVELA Synthetic Test Store,Lumanglipa,123 Main St,13.9667,121.1167
B-001,REVELA Synthetic Test Store,Lumanglipa,123 Main St,13.9667,121.1167
B-002,REVELA Synthetic Test Store,Lumanglipa,New Branch Address,13.9668,121.1168
""".encode("utf-8")

        try:
            # Coordinates are synthetic and included to avoid geocoding.
            # Fail closed if future changes try to resolve coordinates online.
            with ExitStack() as stack:
                stack.enter_context(patch.object(
                    registry_service,
                    "_resolve_location",
                    side_effect=RuntimeError(
                        "Network location resolution is disabled in this test."
                    ),
                ))

                print(
                    "--- Test 1: Uploading duplicate synthetic business IDs ---"
                )
                summary, error = registry_service.upload_registry(
                    io.BytesIO(csv_content), ".csv"
                )
                if error or summary is None:
                    raise RuntimeError(f"Upload test failed: {error or 'no result'}")
                print(
                    f"Result: {summary['inserted']} inserted, "
                    f"{summary['skipped']} skipped, "
                    f"{summary.get('updated', 0)} updated."
                )

                print("--- Test 2: Re-uploading the same synthetic rows ---")
                summary, error = registry_service.upload_registry(
                    io.BytesIO(csv_content), ".csv"
                )
                if error or summary is None:
                    raise RuntimeError(
                        f"Repeated upload test failed: {error or 'no result'}"
                    )
                print(
                    f"Result: {summary['inserted']} inserted, "
                    f"{summary['skipped']} skipped, "
                    f"{summary.get('updated', 0)} updated."
                )

                print("--- Test 3: Syncing duplicate and new synthetic IDs ---")
                summary, error = registry_service.sync_registry(
                    io.BytesIO(csv_content_sync), ".csv"
                )
                if error or summary is None:
                    raise RuntimeError(f"Sync test failed: {error or 'no result'}")
                print(
                    f"Result: {summary['inserted']} inserted, "
                    f"{summary['skipped']} skipped, "
                    f"{summary['updated']} updated."
                )
        finally:
            cursor = mysql.connection.cursor()
            try:
                cursor.execute(
                    "DELETE FROM geospatial_logs "
                    "WHERE businessID IN (%s, %s)",
                    _TEST_BUSINESS_IDS,
                )
                cursor.execute(
                    "DELETE FROM official_registry "
                    "WHERE businessID IN (%s, %s)",
                    _TEST_BUSINESS_IDS,
                )
                mysql.connection.commit()
            except Exception:
                mysql.connection.rollback()
                raise
            finally:
                cursor.close()


if __name__ == "__main__":
    run_test()
