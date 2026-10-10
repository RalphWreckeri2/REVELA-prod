import threading

from app import mysql


_table_ready = False
_table_lock = threading.Lock()


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
                    businessID VARCHAR(50) NOT NULL,
                    eventType VARCHAR(24) NOT NULL,
                    resultStatus VARCHAR(24) NULL,
                    placeID VARCHAR(255) NULL,
                    latitude DECIMAL(10,8) NULL,
                    longitude DECIMAL(11,8) NULL,
                    matchScore DECIMAL(4,3) NULL,
                    eventAt DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    KEY idx_registry_workflow_type_time (eventType, eventAt),
                    KEY idx_registry_workflow_business (businessID, eventID)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
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
