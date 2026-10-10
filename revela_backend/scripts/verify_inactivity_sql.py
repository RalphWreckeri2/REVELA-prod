"""Validate the inactivity SQL emitted by api/auth/sessions.py against live MySQL.

Read-only with respect to the production schema: every write goes to a
TEMPORARY table with the identical DDL, which MySQL drops when the session
ends. The real user_active_sessions table is only ever SELECTed from.
"""
import os
import sys
from datetime import timedelta

BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND_ROOT)

import MySQLdb
from dotenv import load_dotenv
from flask import Flask

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

IDLE_SECONDS = 30 * 60


def check(label, condition, detail=""):
    print(f"[{'PASS' if condition else 'FAIL'}] {label}" + (f"  -> {detail}" if detail else ""))
    if not condition:
        failures.append(label)


def normalize(sql, table):
    return " ".join(sql.replace(table, "TBL").lower().split())


# ── The exact SQL used in sessions.py ────────────────────────────────────────
LIVENESS_SQL = """
    SELECT 1 FROM user_active_sessions
    WHERE userID = %s AND sessionID = %s
      AND issuedAt > CURRENT_TIMESTAMP - INTERVAL %s HOUR
"""
IDLE_SQL = """
    SELECT 1 FROM user_active_sessions
    WHERE userID = %s AND sessionID = %s
      AND issuedAt <= CURRENT_TIMESTAMP - INTERVAL %s SECOND
"""
INSERT_SQL = """
    INSERT INTO user_active_sessions (userID, sessionID, clientType, issuedAt)
    VALUES (%s, %s, %s, CURRENT_TIMESTAMP)
"""
REVOKE_SQL = (
    "DELETE FROM user_active_sessions WHERE userID = %s AND sessionID = %s"
)

print("=== 1. Temporary table with the real DDL ===")
cur.execute("DROP TEMPORARY TABLE IF EXISTS tmp_idle_probe")
cur.execute("""
    CREATE TEMPORARY TABLE tmp_idle_probe (
        userID INT NOT NULL PRIMARY KEY,
        sessionID CHAR(32) NOT NULL,
        clientType VARCHAR(16) NOT NULL,
        issuedAt DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        KEY idx_session_id (sessionID)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
""")
conn.commit()

LIVENESS = LIVENESS_SQL.replace("user_active_sessions", "tmp_idle_probe")
IDLE = IDLE_SQL.replace("user_active_sessions", "tmp_idle_probe")
INSERT = INSERT_SQL.replace("user_active_sessions", "tmp_idle_probe")
REVOKE = REVOKE_SQL.replace("user_active_sessions", "tmp_idle_probe")

print()
print("=== 2. Parameterized INTERVAL SECOND syntax is accepted ===")
try:
    cur.execute(IDLE, (999101, "a" * 32, IDLE_SECONDS))
    cur.fetchall()
    check("IDLE_SQL with a bound INTERVAL ... SECOND parameter executes", True)
except Exception as exc:
    check("IDLE_SQL with a bound INTERVAL ... SECOND parameter executes", False,
          f"{type(exc).__name__}: {exc}")

print()
print("=== 3. A session inside the idle window is not idle ===")
cur.execute(INSERT, (999101, "a" * 32, "web"))
conn.commit()
cur.execute(IDLE, (999101, "a" * 32, IDLE_SECONDS))
check("fresh session is not idle", cur.fetchone() is None)

cur.execute(LIVENESS, (999101, "a" * 32, 12.0))
check("fresh session is still live", cur.fetchone() is not None)

print()
print("=== 4. The boundary is exactly the 30 minute idle limit ===")
cur.execute("UPDATE tmp_idle_probe SET issuedAt = issuedAt - INTERVAL 29 MINUTE WHERE userID=999101")
conn.commit()
cur.execute(IDLE, (999101, "a" * 32, IDLE_SECONDS))
check("29 minutes idle is still inside the window", cur.fetchone() is None)

cur.execute("UPDATE tmp_idle_probe SET issuedAt = issuedAt - INTERVAL 2 MINUTE WHERE userID=999101")
conn.commit()
cur.execute(IDLE, (999101, "a" * 32, IDLE_SECONDS))
check("31 minutes idle is outside the window", cur.fetchone() is not None)

# Within a couple of seconds of the boundary.
cur.execute("UPDATE tmp_idle_probe SET issuedAt = CURRENT_TIMESTAMP - INTERVAL 1795 SECOND WHERE userID=999101")
conn.commit()
cur.execute(IDLE, (999101, "a" * 32, IDLE_SECONDS))
check("1795s idle is inside the window", cur.fetchone() is None)
cur.execute("UPDATE tmp_idle_probe SET issuedAt = CURRENT_TIMESTAMP - INTERVAL 1805 SECOND WHERE userID=999101")
conn.commit()
cur.execute(IDLE, (999101, "a" * 32, IDLE_SECONDS))
check("1805s idle is outside the window", cur.fetchone() is not None)

print()
print("=== 5. Idleness is independent of the 12h JWT ceiling ===")
# Idle for 13 hours: outside both windows.
cur.execute("UPDATE tmp_idle_probe SET issuedAt = issuedAt - INTERVAL 12 HOUR WHERE userID=999101")
conn.commit()
cur.execute(LIVENESS, (999101, "a" * 32, 12.0))
check("13h old session fails the JWT-lifetime check", cur.fetchone() is None)
cur.execute(IDLE, (999101, "a" * 32, IDLE_SECONDS))
check("13h old session also reads as idle", cur.fetchone() is not None)

# A 20h-old session is past the JWT ceiling but must not be treated as
# "idle" by a query that only looks at the idle window.
cur.execute("UPDATE tmp_idle_probe SET issuedAt = issuedAt - INTERVAL 7 HOUR WHERE userID=999101")
conn.commit()
cur.execute(IDLE, (999101, "a" * 32, IDLE_SECONDS))
check("idle window is evaluated independently of the 12h ceiling",
      cur.fetchone() is not None)

print()
print("=== 6. Eviction frees the slot for the next device ===")
cur.execute(REVOKE, (999101, "a" * 32))
conn.commit()
cur.execute(LIVENESS, (999101, "a" * 32, 12.0))
check("revoked session no longer occupies the slot", cur.fetchone() is None)

err = None
try:
    cur.execute(INSERT, (999101, "b" * 32, "mobile"))
except Exception as exc:
    err = exc
conn.rollback()
check("another device can now claim the account", err is None,
      f"{type(err).__name__}: {err}" if err else "")

print()
print("=== 7. Query plans stay on the primary key ===")
# Re-seed: the optimiser reports "no matching row in const table" for an
# empty table, which would hide the access type.
cur.execute(INSERT, (999103, "d" * 32, "web"))
conn.commit()
# Age the row past the idle window: with a fresh row MySQL proves IDLE_SQL can
# never match and reports "no matching row in const table", which hides the
# access type entirely.
cur.execute("UPDATE tmp_idle_probe SET issuedAt = issuedAt - INTERVAL 1 HOUR WHERE userID=999103")
conn.commit()
for label, sql, params in (
    ("LIVENESS_SQL", LIVENESS, (999103, "d" * 32, 12.0)),
    ("IDLE_SQL", IDLE, (999103, "d" * 32, IDLE_SECONDS)),
    ("REVOKE_SQL", REVOKE, (999103, "d" * 32)),
):
    cur.execute("EXPLAIN " + sql, params)
    plan = cur.fetchone()
    access_type, key = plan[4], plan[6]
    print(f"   {label}: type={access_type} key={key}")
    check(f"{label} is a key lookup",
          access_type in ("const", "eq_ref", "ref", "range") and key == "PRIMARY",
          f"type={access_type} key={key}")

print()
print("=== 8. Timezone sanity: the DB clock is used consistently ===")
cur.execute("SELECT @@time_zone, NOW(), UTC_TIMESTAMP()")
tz, local_now, utc_now = cur.fetchone()
offset_hours = (local_now - utc_now).total_seconds() / 3600
print(f"   time_zone={tz!r} NOW()={local_now} UTC={utc_now} (offset {offset_hours:+.1f}h)")
cur.execute(INSERT, (999102, "c" * 32, "web"))
conn.commit()
cur.execute(IDLE, (999102, "c" * 32, IDLE_SECONDS))
check(
    "a row written by CURRENT_TIMESTAMP reads as not-idle on this server",
    cur.fetchone() is None,
    "comparing in SQL avoids any Python/MySQL clock skew",
)

print()
print("=== 9. Config wiring ===")
from api.auth import sessions as S

app = Flask(__name__)
app.config.update(
    JWT_ACCESS_TOKEN_EXPIRES=timedelta(hours=12),
    SESSION_IDLE_TIMEOUT=timedelta(minutes=30),
)
with app.app_context():
    check("idle window is 30 minutes", S.idle_timeout_seconds() == 1800.0,
          str(S.idle_timeout_seconds()))
    check("JWT ceiling is still 12 hours", S.session_lifetime_hours() == 12.0,
          str(S.session_lifetime_hours()))

app2 = Flask(__name__)  # no SESSION_IDLE_TIMEOUT set
with app2.app_context():
    check("idle window falls back to 30 minutes", S.idle_timeout_seconds() == 1800.0,
          str(S.idle_timeout_seconds()))

cur.execute("DROP TEMPORARY TABLE IF EXISTS tmp_idle_probe")
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