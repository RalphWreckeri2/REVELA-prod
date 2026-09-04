import datetime
from app import mysql

TABLE_SCHEMA = """
CREATE TABLE IF NOT EXISTS `detection_runs` (
  `runID` int NOT NULL AUTO_INCREMENT,
  `triggeredByUserID` int DEFAULT NULL,
  `startedAt` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `completedAt` datetime DEFAULT NULL,
  `status` varchar(50) NOT NULL DEFAULT 'running',
  `newFlags` int DEFAULT '0',
  `totalChecked` int DEFAULT '0',
  PRIMARY KEY (`runID`),
  KEY `fk_detection_user` (`triggeredByUserID`),
  CONSTRAINT `fk_detection_user` FOREIGN KEY (`triggeredByUserID`) REFERENCES `users` (`userID`) ON DELETE SET NULL ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
"""


def ensure_detection_runs_table():
    """Ensure the detection_runs table exists in the database."""
    try:
        cur = mysql.connection.cursor()
        cur.execute(TABLE_SCHEMA)
        mysql.connection.commit()
        cur.close()
    except Exception as e:
        print(f"[detection_runs] Error ensuring table exists: {e}")


def get_monthly_detection_count():
    """
    Count how many completed detection scans were executed in the current calendar month.
    Cancelled or failed runs do NOT consume the monthly quota.
    """
    ensure_detection_runs_table()
    cur = mysql.connection.cursor()
    cur.execute("""
        SELECT COUNT(*) AS cnt FROM detection_runs
        WHERE status = 'completed'
          AND YEAR(startedAt) = YEAR(CURRENT_DATE())
          AND MONTH(startedAt) = MONTH(CURRENT_DATE())
    """)
    row = cur.fetchone()
    cur.close()
    if isinstance(row, dict):
        return int(row.get("cnt", 0))
    elif isinstance(row, (list, tuple)):
        return int(row[0])
    return 0


def reset_detection_quota():
    """
    Resets the monthly detection quota counter for testing and admin operations.
    Sets completed detection runs status to 'reset' so new runs can be executed.
    """
    ensure_detection_runs_table()
    cur = mysql.connection.cursor()
    cur.execute("""
        UPDATE detection_runs
        SET status = 'reset'
        WHERE status = 'completed'
    """)
    mysql.connection.commit()
    cur.close()
    return True


def create_detection_run(user_id=None):
    """
    Record the start of a detection run. Returns the generated runID.
    """
    ensure_detection_runs_table()
    cur = mysql.connection.cursor()
    cur.execute("""
        INSERT INTO detection_runs (triggeredByUserID, startedAt, status)
        VALUES (%s, NOW(), 'running')
    """, (user_id,))
    mysql.connection.commit()
    run_id = cur.lastrowid
    cur.close()
    return run_id


def update_detection_run_status(run_id, status, new_flags=0, total_checked=0):
    """
    Update detection run outcome (status='completed', 'cancelled', or 'failed').
    """
    if not run_id:
        return
    ensure_detection_runs_table()
    cur = mysql.connection.cursor()
    cur.execute("""
        UPDATE detection_runs
        SET status = %s,
            completedAt = NOW(),
            newFlags = %s,
            totalChecked = %s
        WHERE runID = %s
    """, (status, new_flags, total_checked, run_id))
    mysql.connection.commit()
    cur.close()


def get_latest_detection_run():
    """Get metadata of the most recent completed detection run."""
    ensure_detection_runs_table()
    cur = mysql.connection.cursor()
    cur.execute("""
        SELECT r.runID, r.triggeredByUserID, r.startedAt, r.completedAt, 
               r.status, r.newFlags, r.totalChecked, u.fullName as triggeredByName
        FROM detection_runs r
        LEFT JOIN users u ON r.triggeredByUserID = u.userID
        WHERE r.status = 'completed'
        ORDER BY r.completedAt DESC, r.runID DESC
        LIMIT 1
    """)
    row = cur.fetchone()
    cur.close()
    return row


def get_detection_quota_info():
    """
    Returns quota details for detection scans:
    - monthly_limit: 2
    - used_this_month: count of completed scans this month
    - remaining_this_month: scans left
    - resets_on: date when monthly limit resets (1st of next month)
    - last_run: info about latest scan
    """
    monthly_limit = 2
    used = get_monthly_detection_count()
    remaining = max(0, monthly_limit - used)

    # Calculate reset date (1st of next month)
    today = datetime.date.today()
    if today.month == 12:
        next_month = datetime.date(today.year + 1, 1, 1)
    else:
        next_month = datetime.date(today.year, today.month + 1, 1)

    last_run = get_latest_detection_run()
    last_run_data = None
    if last_run and isinstance(last_run, dict):
        comp = last_run.get("completedAt")
        if isinstance(comp, (datetime.date, datetime.datetime)):
            comp_str = comp.strftime("%Y-%m-%d %H:%M:%S")
        else:
            comp_str = str(comp) if comp else None

        last_run_data = {
            "runID": last_run.get("runID"),
            "completedAt": comp_str,
            "newFlags": last_run.get("newFlags", 0),
            "totalChecked": last_run.get("totalChecked", 0),
            "triggeredByName": last_run.get("triggeredByName") or "Admin"
        }

    return {
        "monthly_limit": monthly_limit,
        "used_this_month": used,
        "remaining_this_month": remaining,
        "is_limit_reached": remaining <= 0,
        "resets_on": next_month.strftime("%B 1, %Y"),
        "last_run": last_run_data
    }
