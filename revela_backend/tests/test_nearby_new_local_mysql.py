"""Opt-in integration tests for a disposable, loopback-only MySQL database.

Provision the database separately. This module never creates a database and
will not connect unless REVELA_RUN_LOCAL_MYSQL_TESTS=1 is explicitly set.
"""

import os
import unittest
from unittest.mock import MagicMock, patch

from flask import Flask

from api.flags import service
from app import mysql


_OPT_IN = "REVELA_RUN_LOCAL_MYSQL_TESTS"
_ISOLATION_ACK = "REVELA_LOCAL_MYSQL_ISOLATION_ACK"
_DATABASE = "REVELA_LOCAL_MYSQL_DATABASE"
_PORT = "REVELA_LOCAL_MYSQL_PORT"
_USER = "REVELA_LOCAL_MYSQL_USER"
_PASSWORD = "REVELA_LOCAL_MYSQL_PASSWORD"
_EXPECTED_DATABASE = "revela_test_nearby_phase2"
_EXPECTED_USER = "revela_nearby_test"
_EXPECTED_ACCOUNT = "revela_nearby_test@127.0.0.1"

_BASE_SCHEMA = (
    """
    CREATE TABLE IF NOT EXISTS users (
        userID INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
        fullName VARCHAR(255) NULL
    ) ENGINE=InnoDB
    """,
    """
    CREATE TABLE IF NOT EXISTS barangays (
        barangayID INT NOT NULL PRIMARY KEY,
        barangayName VARCHAR(128) NOT NULL,
        UNIQUE KEY uq_local_barangay_name (barangayName)
    ) ENGINE=InnoDB
    """,
    """
    CREATE TABLE IF NOT EXISTS official_registry (
        businessID VARCHAR(50) NOT NULL PRIMARY KEY,
        barangayID INT NULL,
        businessName VARCHAR(255) NOT NULL,
        applicationStatus VARCHAR(32) NULL,
        businessType VARCHAR(128) NULL,
        lineOfBusiness VARCHAR(255) NULL,
        businessAddress TEXT NULL,
        placeID VARCHAR(255) NULL,
        placeIDKind VARCHAR(32) NULL,
        coordSource VARCHAR(32) NULL,
        coordFetchedAt DATETIME NULL,
        matchScore DECIMAL(4,3) NULL,
        matchStatus VARCHAR(24) NULL,
        latitude DECIMAL(10,8) NULL,
        longitude DECIMAL(11,8) NULL,
        KEY idx_local_registry_place (placeID),
        KEY idx_local_registry_barangay (barangayID)
    ) ENGINE=InnoDB
    """,
    """
    CREATE TABLE IF NOT EXISTS geospatial_logs (
        logID BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
        barangayID INT NULL,
        businessID VARCHAR(50) NULL,
        reportID INT NULL,
        detectedName VARCHAR(255) NULL,
        latitude DECIMAL(10,8) NULL,
        longitude DECIMAL(11,8) NULL,
        flagColor VARCHAR(24) NULL,
        placeID VARCHAR(255) NULL,
        nearestLandmark TEXT NULL,
        placeTypes JSON NULL,
        KEY idx_local_geo_place (placeID),
        KEY idx_local_geo_business (businessID),
        KEY idx_local_geo_color_coords (flagColor, latitude, longitude),
        KEY idx_local_geo_detected_barangay (detectedName, barangayID)
    ) ENGINE=InnoDB
    """,
    """
    CREATE TABLE IF NOT EXISTS registry_rejected_places (
        businessID VARCHAR(50) NOT NULL,
        placeID VARCHAR(255) NOT NULL,
        PRIMARY KEY (businessID, placeID),
        KEY idx_local_rejected_place (placeID)
    ) ENGINE=InnoDB
    """,
    """
    CREATE TABLE IF NOT EXISTS inspection_reports (
        reportID BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
        targetType VARCHAR(32) NULL,
        targetID BIGINT NULL,
        verificationStatus VARCHAR(32) NULL,
        inspectionResult VARCHAR(32) NULL,
        KEY idx_local_inspection_target (targetType, targetID),
        KEY idx_local_inspection_verification
            (targetType, targetID, verificationStatus, inspectionResult)
    ) ENGINE=InnoDB
    """,
)


def _local_database_settings():
    if os.getenv(_OPT_IN) != "1":
        raise unittest.SkipTest(
            f"Set {_OPT_IN}=1 to opt in to local MySQL integration tests."
        )
    if os.getenv(_ISOLATION_ACK) != "DISPOSABLE_MYSQL_WITHOUT_EXTERNAL_NETWORK":
        raise unittest.SkipTest(
            f"Set {_ISOLATION_ACK}=DISPOSABLE_MYSQL_WITHOUT_EXTERNAL_NETWORK "
            "only after provisioning a disposable MySQL instance with no "
            "external network access."
        )

    database = os.getenv(_DATABASE, "")
    if database != _EXPECTED_DATABASE:
        raise unittest.SkipTest(
            f"{_DATABASE} must be exactly '{_EXPECTED_DATABASE}'."
        )

    port_text = os.getenv(_PORT, "")
    if not port_text.isdecimal() or not 1 <= int(port_text) <= 65535:
        raise unittest.SkipTest(
            f"Set {_PORT} to the port of the explicitly provisioned local server."
        )

    username = os.getenv(_USER)
    password = os.getenv(_PASSWORD)
    if username != _EXPECTED_USER or not password:
        raise unittest.SkipTest(
            f"Set {_USER} to '{_EXPECTED_USER}' and provide {_PASSWORD} "
            "for the disposable local database."
        )

    return database, int(port_text), username, password


class NearbyNewLocalMySQLIntegrationTests(unittest.TestCase):
    """Exercise real SQL persistence only against an explicitly opted-in DB."""

    _schema_initialized = False

    @classmethod
    def setUpClass(cls):
        database, port, username, password = _local_database_settings()
        cls.app = Flask(__name__)
        cls.app.config.update(
            MYSQL_HOST="127.0.0.1",
            MYSQL_PORT=port,
            MYSQL_USER=username,
            MYSQL_PASSWORD=password,
            MYSQL_DB=database,
            MYSQL_CURSORCLASS="DictCursor",
        )
        # Intentionally do not call create_app(): it starts background jobs.
        mysql.init_app(cls.app)
        cls.database_name = database

    def setUp(self):
        self.app_context = self.app.app_context()
        self.app_context.push()
        self.addCleanup(self.app_context.pop)
        previous_reconcile_time = service._last_reconcile_time
        service._last_reconcile_time = 0
        self.addCleanup(
            setattr, service, "_last_reconcile_time", previous_reconcile_time
        )
        if not self._schema_initialized:
            self._prepare_empty_schema()
            type(self)._schema_initialized = True
        else:
            self._clear_test_data()
        self.addCleanup(self._clear_test_data)

    def _prepare_empty_schema(self):
        cursor = mysql.connection.cursor()
        try:
            cursor.execute(
                "SELECT DATABASE() AS selected_database, "
                "CURRENT_USER() AS authenticated_account"
            )
            selected = cursor.fetchone()
            if not selected or selected["selected_database"] != self.database_name:
                self.fail("Connected database did not match the opted-in test database.")
            if selected["authenticated_account"] != _EXPECTED_ACCOUNT:
                self.fail(
                    "Connected MySQL account did not match the dedicated "
                    "loopback-only test account."
                )

            for statement in _BASE_SCHEMA:
                cursor.execute(statement)

            for table in (
                "barangays",
                "registry_rejected_places",
                "inspection_reports",
                "users",
                "official_registry",
                "geospatial_logs",
                "scan_point_log",
                "detection_runs",
                "places_api_usage",
                "registry_workflow_events",
            ):
                cursor.execute(f"SHOW TABLES LIKE %s", (table,))
                exists = cursor.fetchone()
                if exists:
                    cursor.execute(f"SELECT COUNT(*) AS row_count FROM `{table}`")
                    count = cursor.fetchone()["row_count"]
                    if count:
                        self.fail(
                            f"Refusing to use non-empty test table {table}; "
                            "provision a fresh disposable database."
                        )
        finally:
            cursor.close()

        # Runtime helpers create only these application-owned tables.
        service._budget_tables_ready = False
        service._place_types_column_ready = False
        from api.registry import audit
        audit._table_ready = False
        service._ensure_budget_tables()
        from api.models.detection_runs import ensure_detection_runs_table
        ensure_detection_runs_table()
        from api.registry.audit import ensure_registry_workflow_events
        ensure_registry_workflow_events()

    @staticmethod
    def _clear_test_data():
        cursor = mysql.connection.cursor()
        try:
            for table in (
                "registry_workflow_events",
                "places_api_usage",
                "scan_point_log",
                "detection_runs",
                "geospatial_logs",
                "official_registry",
                "registry_rejected_places",
                "inspection_reports",
                "barangays",
                "users",
            ):
                cursor.execute(f"DELETE FROM `{table}`")
            mysql.connection.commit()
        finally:
            cursor.close()

    def _seed_minimum_rows(self):
        cursor = mysql.connection.cursor()
        try:
            cursor.execute(
                "INSERT INTO barangays (barangayID, barangayName) "
                "VALUES (%s, %s)",
                (1, "Barangay I"),
            )
            cursor.execute(
                """
                INSERT INTO official_registry
                    (businessID, barangayID, businessName, applicationStatus,
                     businessType, lineOfBusiness, businessAddress,
                     coordSource, latitude, longitude)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    "LOCAL-BIZ-1", 1, "Silva Pharmacy", "Active",
                    "Pharmacy", "Pharmacy", "Poblacion, Mataasnakahoy",
                    "csv", 13.9667, 121.1167,
                ),
            )
            cursor.execute(
                """
                INSERT INTO geospatial_logs
                    (barangayID, detectedName, latitude, longitude,
                     flagColor, placeID, nearestLandmark, placeTypes)
                VALUES (%s, %s, %s, %s, 'Red', %s, %s, %s)
                """,
                (
                    1, "Silva Pharmacy", 13.9667, 121.1167,
                    "old-silva-place", "Poblacion, Mataasnakahoy",
                    '["pharmacy"]',
                ),
            )
            mysql.connection.commit()
        finally:
            cursor.close()

    def _nearby_responses(self):
        return {
            "places": [
                {
                    "id": "new-silva-place",
                    "displayName": {"text": "Silva Pharmacy"},
                    "location": {"latitude": 13.9667, "longitude": 121.1167},
                    "formattedAddress": "Poblacion, Mataasnakahoy",
                    "primaryType": "pharmacy",
                    "businessStatus": "OPERATIONAL",
                },
                {
                    "id": "local-unregistered-place",
                    "displayName": {"text": "Lakeside Variety Store"},
                    "location": {"latitude": 13.9667, "longitude": 121.1167},
                    "formattedAddress": "Poblacion, Mataasnakahoy",
                    "primaryType": "store",
                    "businessStatus": "OPERATIONAL",
                },
                {
                    "id": "local-library-place",
                    "displayName": {"text": "Community Library"},
                    "location": {"latitude": 13.9667, "longitude": 121.1167},
                    "primaryType": "library",
                    "businessStatus": "OPERATIONAL",
                },
            ]
        }

    def test_reconciliation_matching_classification_checkpoint_and_resume(self):
        self._seed_minimum_rows()
        point_a = (13.9667, 121.1167)
        point_b = (13.9750, 121.1167)
        points = [point_a, point_b]
        phase = {"name": "first"}
        calls = {point_a: 0, point_b: 0}

        def mocked_post(_url, **kwargs):
            self.assertEqual(_url, service.NEW_NEARBY_URL)
            center = kwargs["json"]["locationRestriction"]["circle"]["center"]
            point = (center["latitude"], center["longitude"])
            calls[point] += 1
            response = MagicMock()
            if point == point_b and phase["name"] == "first":
                response.status_code = 503
                response.text = "offline simulated failure"
                response.json.return_value = {}
            else:
                response.status_code = 200
                response.json.return_value = self._nearby_responses()
            return response

        with (
            patch.dict("os.environ", {"GOOGLE_MAPS_API_KEY": "local-test-key"}),
            patch.object(service, "RUN_DETECTION_NEARBY_API", "new"),
            patch.object(service, "get_detection_quota_info", return_value={
                "is_limit_reached": False,
                "monthly_limit": 10,
                "registry_count": 1,
            }),
            patch.object(service, "_detection_points_for_mode", return_value=points),
            patch.object(service, "_within_municipality", return_value=True),
            patch.object(service, "_get_barangay_id_by_coords", return_value=1),
            patch.object(service.quota_settings, "cap", side_effect=lambda key: {
                "quota.nearby_new.daily": 10,
                "quota.nearby_new.monthly": 20,
                "run_detection.max_seconds": 90,
                "run_detection.max_requests": 10,
                "run_detection.grid_step_degrees": 0.009,
            }.get(key, 100)),
            patch.object(service, "reserve_usage_slot", return_value=(True, None)),
            patch.object(service.http, "post", side_effect=mocked_post) as post,
            patch.object(service, "_nearby_last_request_at", 0),
            patch.object(service.time, "sleep"),
            patch.object(service.hub, "publish_to_admins"),
            patch.object(service, "_log_detection_summary", return_value={}),
        ):
            first, first_error = service.run_detection(mode="full")
            self.assertIsNone(first_error)
            self.assertEqual(first["status"], "partial")
            self.assertEqual(first["completed_points"], 1)
            self.assertEqual(first["incomplete_points"], 1)
            self.assertEqual(first["run_summary"]["matched"], 1)
            self.assertEqual(first["run_summary"]["new_flags"], 1)
            self.assertEqual(first["run_summary"]["non_business"], 1)

            fingerprint = service._checkpoint_configuration_fingerprint("full")
            point_a_key = service._checkpoint_point_key(*point_a, fingerprint)
            point_b_key = service._checkpoint_point_key(*point_b, fingerprint)
            cursor = mysql.connection.cursor()
            try:
                cursor.execute("SELECT pointKey FROM scan_point_log")
                self.assertEqual(
                    {row["pointKey"] for row in cursor.fetchall()},
                    {point_a_key},
                )
                cursor.execute(
                    "SELECT placeID, businessID, flagColor FROM geospatial_logs "
                    "WHERE placeID IN (%s, %s, %s)",
                    (
                        "new-silva-place",
                        "local-unregistered-place",
                        "local-library-place",
                    ),
                )
                flags = {row["placeID"]: row for row in cursor.fetchall()}
                self.assertEqual(flags["new-silva-place"]["businessID"], "LOCAL-BIZ-1")
                self.assertEqual(flags["new-silva-place"]["flagColor"], "Green")
                self.assertIsNone(flags["local-unregistered-place"]["businessID"])
                self.assertEqual(flags["local-unregistered-place"]["flagColor"], "Red")
                self.assertNotIn("local-library-place", flags)
                cursor.execute(
                    "SELECT flagColor, businessID FROM geospatial_logs "
                    "WHERE placeID = %s",
                    ("old-silva-place",),
                )
                self.assertIsNone(cursor.fetchone())
                cursor.execute(
                    "SELECT COUNT(*) AS event_count "
                    "FROM registry_workflow_events "
                    "WHERE businessID = %s AND eventType = 'reconciled'",
                    ("LOCAL-BIZ-1",),
                )
                self.assertGreater(cursor.fetchone()["event_count"], 0)
            finally:
                cursor.close()

            phase["name"] = "resume"
            second, second_error = service.run_detection(mode="full")

        self.assertIsNone(second_error)
        self.assertEqual(second["status"], "completed")
        self.assertEqual(second["completed_points"], 2)
        self.assertEqual(calls, {point_a: 1, point_b: 2})
        self.assertEqual(post.call_count, 3)
        cursor = mysql.connection.cursor()
        try:
            cursor.execute("SELECT pointKey FROM scan_point_log")
            self.assertEqual(
                {row["pointKey"] for row in cursor.fetchall()},
                {point_a_key, point_b_key},
            )
            cursor.execute(
                "SELECT COUNT(*) AS row_count FROM geospatial_logs "
                "WHERE placeID = %s AND flagColor = 'Red'",
                ("local-unregistered-place",),
            )
            self.assertEqual(cursor.fetchone()["row_count"], 1)
            cursor.execute(
                "SELECT COUNT(*) AS row_count FROM geospatial_logs "
                "WHERE placeID = %s",
                ("local-library-place",),
            )
            self.assertEqual(cursor.fetchone()["row_count"], 0)
        finally:
            cursor.close()

    def test_cancellation_removes_new_red_flags_and_checkpoints(self):
        self._seed_minimum_rows()
        point = (13.9667, 121.1167)
        response_body = {
            "places": [{
                "id": "cancelled-unregistered-place",
                "displayName": {"text": "One Time Market"},
                "location": {"latitude": point[0], "longitude": point[1]},
                "primaryType": "store",
                "businessStatus": "OPERATIONAL",
            }]
        }
        response = MagicMock(status_code=200, text="")
        response.json.return_value = response_body
        quota = {
            "is_limit_reached": False,
            "monthly_limit": 10,
            "registry_count": 1,
        }

        with (
            patch.dict("os.environ", {"GOOGLE_MAPS_API_KEY": "local-test-key"}),
            patch.object(service, "RUN_DETECTION_NEARBY_API", "new"),
            patch.object(service, "get_detection_quota_info", return_value=quota),
            patch.object(service, "_detection_points_for_mode", return_value=[point]),
            patch.object(service, "_within_municipality", return_value=True),
            patch.object(service, "_get_barangay_id_by_coords", return_value=1),
            patch.object(service.quota_settings, "cap", side_effect=lambda key: {
                "quota.nearby_new.daily": 10,
                "quota.nearby_new.monthly": 20,
                "run_detection.max_seconds": 90,
                "run_detection.max_requests": 10,
                "run_detection.grid_step_degrees": 0.009,
            }.get(key, 100)),
            patch.object(service, "reserve_usage_slot", return_value=(True, None)),
            patch.object(service.http, "post", return_value=response),
            patch.object(service, "_nearby_last_request_at", 0),
            patch.object(service.time, "sleep"),
            patch.object(service.hub, "publish_to_admins"),
            patch.object(service, "_log_detection_summary", return_value={}),
            patch.object(service, "is_cancelled", side_effect=[False, True]),
        ):
            result, error = service.run_detection(mode="full")

        self.assertIsNone(result)
        self.assertIn("Detection cancelled", error)
        cursor = mysql.connection.cursor()
        try:
            cursor.execute(
                "SELECT COUNT(*) AS row_count FROM geospatial_logs "
                "WHERE placeID = %s",
                ("cancelled-unregistered-place",),
            )
            self.assertEqual(cursor.fetchone()["row_count"], 0)
            cursor.execute("SELECT COUNT(*) AS row_count FROM scan_point_log")
            self.assertEqual(cursor.fetchone()["row_count"], 0)
            cursor.execute(
                "SELECT status FROM detection_runs ORDER BY runID DESC LIMIT 1"
            )
            self.assertEqual(cursor.fetchone()["status"], "cancelled")
        finally:
            cursor.close()


if __name__ == "__main__":
    unittest.main()
