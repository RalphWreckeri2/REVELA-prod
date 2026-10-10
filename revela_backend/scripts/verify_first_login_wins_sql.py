"""Validate the real SQL emitted by api/auth/sessions.py against a live MySQL.

Read-only with respect to the production schema: all write statements run
against a TEMPORARY table with the identical DDL, which MySQL drops when this
session ends.  The real user_active_sessions table is only ever SELECTed from.
"""
import os
import sys
from datetime import timedelta

BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND_ROOT)

import MySQLdb
from dotenv import load_dotenv
from flask import Flask
from flask_mysqldb import MySQL

load_dotenv(os.path.join(BACKEND_ROOT, ".env"))

conn = MySQLdb.connect(
    host=os.getenv("DB_HOST") or "localhost",
    port=int(os.getenv("DB_PORT") or 3306),
    user=os.getenv("DB_USER"),
    passwd=os.getenv("DB_PASSWORD"),
    db=os.getenv("DB_NAME"),
)
cur = conn.cursor()
failures = []


def check(label, condition, detail=""):
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {label}" + (f"  -> {detail}" if detail else ""))
    if not condition:
        failures.append(label)


print("=== 0. Production table state (read-only) ===")
cur.execute("""
    SELECT COLUMN_NAME, DATA_TYPE, COLUMN_KEY
    FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'user_active_sessions'
    ORDER BY ORDINAL_POSITION
""")
cols = cur.fetchall()
print("   columns found:", cols if cols else "<table not present in this database>")
if not cols:
    print("   NOTE: this local database has no user_active_sessions table.")
    print("         In local/dev it is created by the pre-existing")
    print("         CREATE TABLE IF NOT EXISTS bootstrap in sessions.py")
    print("         (left unchanged). Production already has it.")
else:
    have = {c[0]: c for c in cols}
    check("user_active_sessions has userID/sessionID/clientType/issuedAt",
          all(c in have for c in ("userID", "sessionID", "clientType", "issuedAt")),
          str(list(have)))
    check("userID is the PRIMARY KEY", have.get("userID", (None, None, ""))[2] == "PRI",
          have.get("userID", ("", "", ""))[2])

print()
print("=== 1. Temporary table replicating the real DDL ===")
cur.execute("DROP TEMPORARY TABLE IF EXISTS tmp_active_sessions")
cur.execute("""
    CREATE TEMPORARY TABLE tmp_active_sessions (
        userID INT NOT NULL PRIMARY KEY,
        sessionID CHAR(32) NOT NULL,
        clientType VARCHAR(16) NOT NULL,
        issuedAt DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        KEY idx_session_id (sessionID)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
""")
conn.commit()

INSERT_SQL = """
    INSERT INTO tmp_active_sessions (userID, sessionID, clientType, issuedAt)
    VALUES (%s, %s, %s, CURRENT_TIMESTAMP)
"""
CLAIM_SQL = """
    SELECT sessionID, clientType
    FROM tmp_active_sessions
    WHERE userID = %s
      AND issuedAt > CURRENT_TIMESTAMP - INTERVAL %s HOUR
"""
DELETE_EXPIRED_SQL = """
    DELETE FROM tmp_active_sessions
    WHERE userID = %s
      AND issuedAt <= CURRENT_TIMESTAMP - INTERVAL %s HOUR
"""
ACTIVE_SQL = """
    SELECT 1 FROM tmp_active_sessions
    WHERE userID = %s AND sessionID = %s
      AND issuedAt > CURRENT_TIMESTAMP - INTERVAL %s HOUR
"""
REVOKE_SQL = (
    "DELETE FROM tmp_active_sessions WHERE userID = %s AND sessionID = %s"
)

LIFETIME_HOURS = 12.0

print()
print("=== 2. Parameterized INTERVAL syntax is accepted by MySQL ===")
try:
    cur.execute(CLAIM_SQL, (999001, LIFETIME_HOURS))
    cur.fetchall()
    check("CLAIM_SQL with bound INTERVAL parameter executes", True)
except Exception as exc:
    check("CLAIM_SQL with bound INTERVAL parameter executes", False,
          f"{type(exc).__name__}: {exc}")

print()
print("=== 3. First login claims the slot; second collides on the PK ===")
cur.execute(INSERT_SQL, (999001, "a" * 32, "web"))
conn.commit()
cur.execute(CLAIM_SQL, (999001, LIFETIME_HOURS))
row = cur.fetchone()
check("winner's row is visible to CLAIM_SQL", row is not None, str(row))
check("clientType round-trips for the conflict message",
      row is not None and row[1] == "web", str(row))

err = None
try:
    cur.execute(INSERT_SQL, (999001, "b" * 32, "mobile"))
except Exception as exc:
    err = exc
conn.rollback()
check("second login raises a duplicate-key error", err is not None,
      f"{type(err).__name__ if err else None}")
check("errno is 1062 so _is_duplicate_entry matches it",
      err is not None and err.args[0] == 1062,
      f"errno={err.args[0] if err else None}")

cur.execute(CLAIM_SQL, (999001, LIFETIME_HOURS))
still = cur.fetchone()
check("loser's insert did NOT overwrite the winner's row",
      still is not None and still[0] == "a" * 32, str(still))

print()
print("=== 4. A live session is never deleted by the expiry cleanup ===")
cur.execute(DELETE_EXPIRED_SQL, (999001, LIFETIME_HOURS))
conn.commit()
cur.execute(CLAIM_SQL, (999001, LIFETIME_HOURS))
survivor = cur.fetchone()
check("fresh session survives DELETE ... issuedAt <= now - INTERVAL",
      survivor is not None, str(survivor))

print()
print("=== 5. Expiry derived from issuedAt + the 12h JWT lifetime ===")
cur.execute("UPDATE tmp_active_sessions SET issuedAt = issuedAt - INTERVAL 11 HOUR WHERE userID=999001")
conn.commit()
cur.execute(CLAIM_SQL, (999001, LIFETIME_HOURS))
check("11h old session still holds the slot", cur.fetchone() is not None)

cur.execute("UPDATE tmp_active_sessions SET issuedAt = issuedAt - INTERVAL 2 HOUR WHERE userID=999001")
conn.commit()
cur.execute(CLAIM_SQL, (999001, LIFETIME_HOURS))
check("13h old session no longer holds the slot", cur.fetchone() is None)

cur.execute(ACTIVE_SQL, (999001, "a" * 32, LIFETIME_HOURS))
check("is_active_session is False for an expired row", cur.fetchone() is None)

print()
print("=== 6. Expired row is cleared so a new login can proceed ===")
cur.execute(DELETE_EXPIRED_SQL, (999001, LIFETIME_HOURS))
conn.commit()
cur.execute(CLAIM_SQL, (999001, LIFETIME_HOURS))
check("expired row was removed", cur.fetchone() is None)
cur.execute(INSERT_SQL, (999001, "c" * 32, "mobile"))
conn.commit()
cur.execute(CLAIM_SQL, (999001, LIFETIME_HOURS))
row = cur.fetchone()
check("new login succeeds after expiry", row is not None and row[0] == "c" * 32, str(row))

print()
print("=== 7. Logout revokes only the presented session ===")
cur.execute(REVOKE_SQL, (999001, "wrong-session"))
conn.commit()
cur.execute(CLAIM_SQL, (999001, LIFETIME_HOURS))
check("wrong session id cannot revoke", cur.fetchone() is not None)
cur.execute(REVOKE_SQL, (999001, "c" * 32))
conn.commit()
cur.execute(CLAIM_SQL, (999001, LIFETIME_HOURS))
check("correct session id revokes", cur.fetchone() is None)

print()
print("=== 8. Query plans are key lookups, not full scans ===")
# Re-seed so the optimiser has a row to work with.
cur.execute(INSERT_SQL, (999003, "d" * 32, "web"))
conn.commit()
for label, sql, params in (
    ("CLAIM_SQL", CLAIM_SQL, (999003, LIFETIME_HOURS)),
    ("ACTIVE_SQL", ACTIVE_SQL, (999003, "d" * 32, LIFETIME_HOURS)),
    ("DELETE_EXPIRED_SQL", DELETE_EXPIRED_SQL, (999003, LIFETIME_HOURS)),
    ("REVOKE_SQL", REVOKE_SQL, (999003, "d" * 32)),
):
    cur.execute("EXPLAIN " + sql, params)
    plan = cur.fetchone()
    # EXPLAIN columns: id, select_type, table, partitions, type, possible_keys,
    #                  key, key_len, ref, rows, filtered, Extra
    access_type = plan[4]
    key = plan[6]
    print(f"   {label}: type={access_type} key={key}")
    check(f"{label} is a key lookup (no ALL/full scan)",
          access_type in ("const", "eq_ref", "ref", "range") and key == "PRIMARY",
          f"type={access_type} key={key}")
conn.rollback()

print()
print("=== 9. DictCursor row shape (the configured cursorclass) ===")
import MySQLdb.cursors

dict_cur = conn.cursor(MySQLdb.cursors.DictCursor)
dict_cur.execute(INSERT_SQL, (999005, "f" * 32, "mobile"))
conn.commit()
dict_cur.execute(CLAIM_SQL, (999005, LIFETIME_HOURS))
sample = dict_cur.fetchone()
dict_cur.execute("DELETE FROM tmp_active_sessions WHERE userID = %s", (999005,))
conn.commit()
dict_cur.close()
print("   DictCursor row:", sample)

from api.auth.sessions import _row_value
check("DictCursor returns a mapping, not a tuple",
      isinstance(sample, dict), type(sample).__name__)
check("_row_value reads a real DictCursor row by column name",
      _row_value(sample, "clientType", 1) == "mobile",
      repr(_row_value(sample, "clientType", 1)))
check("_row_value reads DictCursor row by name",
      _row_value({"clientType": "web"}, "clientType", 1) == "web")
check("_row_value falls back to tuple index",
      _row_value(("sid", "mobile"), "clientType", 1) == "mobile")
check("_row_value returns None for a missing column",
      _row_value({"a": 1}, "clientType", 1) is None)
check("_row_value tolerates None row", _row_value(None, "clientType", 1) is None)

cur.execute("DROP TEMPORARY TABLE IF EXISTS tmp_active_sessions")
conn.commit()
cur.close()
conn.close()

print()
if failures:
    print(f"RESULT: {len(failures)} CHECK(S) FAILED")
    for f in failures:
        print("  -", f)
    sys.exit(1)
print("RESULT: ALL CHECKS PASSED")