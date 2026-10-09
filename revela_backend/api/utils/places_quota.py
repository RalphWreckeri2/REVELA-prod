"""Persistent, atomic request reservations for Google API usage."""

import re
import threading


_table_ready = False
_table_lock = threading.Lock()
_MONTH_KEY = "DATE_SUB(CURDATE(), INTERVAL DAYOFMONTH(CURDATE()) - 1 DAY)"


def _ensure_table(connection):
    global _table_ready
    if _table_ready:
        return
    with _table_lock:
        if _table_ready:
            return
        cursor = connection.cursor()
        try:
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS places_api_usage (
                    usageDate DATE NOT NULL,
                    kind VARCHAR(32) NOT NULL,
                    requestCount INT NOT NULL DEFAULT 0,
                    PRIMARY KEY (usageDate, kind)
                ) ENGINE=InnoDB
            """)
            connection.commit()
            _table_ready = True
        finally:
            cursor.close()


def reserve_usage_slot(connection, monthly_kind, daily_kind, monthly_cap, daily_cap):
    """Atomically reserve one monthly and daily slot, returning (allowed, reason)."""
    if not re.fullmatch(r"[a-z0-9_]{1,32}", monthly_kind) or not re.fullmatch(
        r"[a-z0-9_]{1,32}", daily_kind
    ):
        raise ValueError("Invalid Places usage ledger key")
    _ensure_table(connection)

    cursor = None
    try:
        connection.begin()
        cursor = connection.cursor()
        cursor.execute(
            f"INSERT IGNORE INTO places_api_usage (usageDate, kind, requestCount) "
            f"VALUES ({_MONTH_KEY}, %s, 0)",
            (monthly_kind,),
        )
        cursor.execute(
            "INSERT IGNORE INTO places_api_usage (usageDate, kind, requestCount) "
            "VALUES (CURDATE(), %s, 0)",
            (daily_kind,),
        )
        cursor.execute(
            f"UPDATE places_api_usage SET requestCount = requestCount + 1 "
            f"WHERE usageDate = {_MONTH_KEY} AND kind = %s AND requestCount < %s",
            (monthly_kind, monthly_cap),
        )
        month_ok = cursor.rowcount == 1
        day_ok = False
        if month_ok:
            cursor.execute(
                "UPDATE places_api_usage SET requestCount = requestCount + 1 "
                "WHERE usageDate = CURDATE() AND kind = %s AND requestCount < %s",
                (daily_kind, daily_cap),
            )
            day_ok = cursor.rowcount == 1
            if not day_ok:
                cursor.execute(
                    f"UPDATE places_api_usage SET requestCount = requestCount - 1 "
                    f"WHERE usageDate = {_MONTH_KEY} AND kind = %s",
                    (monthly_kind,),
                )
        connection.commit()
        if not month_ok:
            return False, "monthly_quota_exceeded"
        if not day_ok:
            return False, "daily_quota_exceeded"
        return True, None
    except Exception:
        connection.rollback()
        raise
    finally:
        if cursor is not None:
            cursor.close()


def read_usage(connection, monthly_kind, daily_kind):
    """Return persisted month/day counts for a method ledger."""
    _ensure_table(connection)
    cursor = connection.cursor()
    try:
        cursor.execute(
            f"SELECT requestCount FROM places_api_usage "
            f"WHERE usageDate = {_MONTH_KEY} AND kind = %s",
            (monthly_kind,),
        )
        month_row = cursor.fetchone()
        cursor.execute(
            "SELECT requestCount FROM places_api_usage "
            "WHERE usageDate = CURDATE() AND kind = %s",
            (daily_kind,),
        )
        day_row = cursor.fetchone()
        return {"month": _row_count(month_row), "day": _row_count(day_row)}
    finally:
        cursor.close()


def _row_count(row):
    if not row:
        return 0
    value = row.get("requestCount") if isinstance(row, dict) else row[0]
    return int(value or 0)
