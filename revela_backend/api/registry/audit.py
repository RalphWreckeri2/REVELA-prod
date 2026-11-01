import json
import threading

from app import mysql


_table_ready = False
_table_lock = threading.Lock()
_runs_table_ready = False
_runs_table_lock = threading.Lock()


def ensure_registry_workflow_runs():
    global _runs_table_ready
    if _runs_table_ready:
        return
    with _runs_table_lock:
        if _runs_table_ready:
            return
        cursor = mysql.connection.cursor()
        try:
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS registry_workflow_runs (
                    runID CHAR(36) NOT NULL PRIMARY KEY,
                    operationType VARCHAR(24) NOT NULL,
                    startedAt DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    completedAt DATETIME NULL,
                    result LONGTEXT NULL,
                    KEY idx_registry_workflow_runs_started (startedAt)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """)
            mysql.connection.commit()
            _runs_table_ready = True
        finally:
            cursor.close()


def start_registry_workflow_run(run_id, operation_type):
    ensure_registry_workflow_runs()
    cursor = mysql.connection.cursor()
    try:
        cursor.execute(
            """INSERT INTO registry_workflow_runs (runID, operationType)
               VALUES (%s, %s)""",
            (run_id, operation_type),
        )
        mysql.connection.commit()
    finally:
        cursor.close()


def complete_registry_workflow_run(run_id, result):
    ensure_registry_workflow_runs()
    cursor = mysql.connection.cursor()
    try:
        cursor.execute(
            """UPDATE registry_workflow_runs
               SET completedAt = CURRENT_TIMESTAMP, result = %s
               WHERE runID = %s""",
            (json.dumps(result, separators=(",", ":"), default=str), run_id),
        )
        if cursor.rowcount != 1:
            raise RuntimeError(f"Unknown registry workflow run {run_id!r}.")
        mysql.connection.commit()
    finally:
        cursor.close()


def get_registry_workflow_run(run_id):
    ensure_registry_workflow_runs()
    cursor = mysql.connection.cursor()
    try:
        cursor.execute(
            """SELECT operationType, completedAt, result
               FROM registry_workflow_runs WHERE runID = %s""",
            (run_id,),
        )
        row = cursor.fetchone()
        if not row:
            return None
        if isinstance(row, dict):
            operation_type = row["operationType"]
            completed_at = row["completedAt"]
            result = row["result"]
        else:
            operation_type, completed_at, result = row
        return {
            "operation": operation_type,
            "completed": completed_at is not None,
            "result": json.loads(result) if result else None,
        }
    finally:
        cursor.close()


def ensure_registry_workflow_events():
    global _table_ready
    if _table_ready:
        return
    with _table_lock:
        if _table_ready:
            return
        cursor = mysql.connection.cursor()
        try:
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS registry_workflow_events (
                    eventID BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
                    businessID VARCHAR(50) COLLATE utf8mb4_unicode_ci NOT NULL,
                    eventType VARCHAR(24) NOT NULL,
                    resultStatus VARCHAR(24) NULL,
                    placeID VARCHAR(255) NULL,
                    latitude DECIMAL(10,8) NULL,
                    longitude DECIMAL(11,8) NULL,
                    matchScore DECIMAL(4,3) NULL,
                    eventAt DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    KEY idx_registry_workflow_type_time (eventType, eventAt),
                    KEY idx_registry_workflow_business (businessID, eventID)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """)
            mysql.connection.commit()
            _table_ready = True
        finally:
            cursor.close()


def record_registry_workflow_event(
    cursor,
    business_id,
    event_type,
    result_status=None,
    place_id=None,
    latitude=None,
    longitude=None,
    match_score=None,
):
    ensure_registry_workflow_events()
    cursor.execute("""
        INSERT INTO registry_workflow_events
            (businessID, eventType, resultStatus, placeID, latitude, longitude, matchScore)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
    """, (
        business_id,
        event_type,
        result_status,
        place_id,
        latitude,
        longitude,
        match_score,
    ))
