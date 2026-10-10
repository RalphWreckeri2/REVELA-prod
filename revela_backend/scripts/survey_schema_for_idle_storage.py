"""Read-only survey of the live schema: is there anywhere to store last-activity?"""
import os
import sys

import MySQLdb
from dotenv import load_dotenv

BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND_ROOT)
load_dotenv(os.path.join(BACKEND_ROOT, ".env"))

conn = MySQLdb.connect(
    host=os.getenv("DB_HOST") or "localhost",
    port=int(os.getenv("DB_PORT") or 3306),
    user=os.getenv("DB_USER"),
    passwd=os.getenv("DB_PASSWORD"),
    db=os.getenv("DB_NAME"),
)
cur = conn.cursor()

cur.execute("SELECT VERSION()")
print("MySQL version:", cur.fetchone()[0])
cur.execute("SELECT @@time_zone, NOW(), UTC_TIMESTAMP()")
tz, now_local, now_utc = cur.fetchone()
print(f"time_zone={tz!r}  NOW()={now_local}  UTC={now_utc}")
print()

cur.execute("""
    SELECT TABLE_NAME
    FROM information_schema.TABLES
    WHERE TABLE_SCHEMA = DATABASE()
    ORDER BY TABLE_NAME
""")
tables = [r[0] for r in cur.fetchall()]
print(f"{len(tables)} tables:", ", ".join(tables))
print()

# Look for any column anywhere that could carry a last-activity timestamp.
CANDIDATES = (
    "lastactivity", "last_activity", "lastseen", "last_seen", "lastlogin",
    "last_login", "lastaccess", "last_access", "lastused", "last_used",
    "lastactive", "last_active", "lastactiveat", "last_active_at",
    "lastheartbeat", "last_heartbeat", "lasttouch", "last_touch",
    "lastping", "last_ping", "idle", "expiresat", "expires_at",
)
print("=== Searching every table for a usable last-activity column ===")
found = []
for table in tables:
    try:
        cur.execute("""
            SELECT COLUMN_NAME, COLUMN_TYPE, IS_NULLABLE
            FROM information_schema.COLUMNS
            WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s
            ORDER BY ORDINAL_POSITION
        """, (table,))
    except Exception:
        continue
    cols = cur.fetchall()
    for name, ctype, nullable in cols:
        if name.lower() in CANDIDATES:
            found.append((table, name, ctype, nullable))

if found:
    for row in found:
        print("  CANDIDATE:", row)
else:
    print("  NONE. No column in any table records last user activity.")

print()
print("=== Tables that look session/state related ===")
for table in tables:
    if any(k in table.lower() for k in
           ("session", "token", "auth", "user", "account", "login", "log")):
        cur.execute("""
            SELECT COLUMN_NAME, COLUMN_TYPE, COLUMN_KEY
            FROM information_schema.COLUMNS
            WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s
            ORDER BY ORDINAL_POSITION
        """, (table,))
        print(f"  {table}:")
        for name, ctype, key in cur.fetchall():
            print(f"      {name:24s} {ctype:16s} {key}")

print()
print("=== users table full definition (the session owner) ===")
if "users" in tables:
    cur.execute("SHOW CREATE TABLE users")
    print(cur.fetchone()[1])

print()
print("=== user_active_sessions current definition (if present) ===")
if "user_active_sessions" in tables:
    cur.execute("SHOW CREATE TABLE user_active_sessions")
    print(cur.fetchone()[1])
else:
    print("  <not present in this local database; created on first login by")
    print("   the existing CREATE TABLE IF NOT EXISTS bootstrap>")

cur.close()
conn.close()