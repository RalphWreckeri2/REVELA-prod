"""Find sessions that are blocking logins without a real signed-in device.

READ-ONLY by default. It never writes, so it is safe to point at production.

Reports, for each row in user_active_sessions:
  * ACTIVE   - a device is genuinely using the account now
  * RECENT   - issued within the inactivity window, may or may not be in use
  * STALE    - older than the inactivity window; this row BLOCKS a new login
               until it is cleared (see the note below)
  * EXPIRED  - past the 12h JWT lifetime; harmless, cleaned up on next login

To clear STALE rows, run with --clear. That DELETES records; it is opt-in and
never runs automatically.
"""
import os
import sys
from datetime import timedelta

BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND_ROOT)

import MySQLdb
from dotenv import load_dotenv

load_dotenv(os.path.join(BACKEND_ROOT, ".env"))

CLEAR = "--clear" in sys.argv
IDLE_SECONDS = int(os.getenv("DIAGNOSTIC_IDLE_SECONDS", 10 * 60))
JWT_HOURS = 12

conn = MySQLdb.connect(
    host=os.getenv("DB_HOST") or "localhost",
    port=int(os.getenv("DB_PORT") or 3306),
    user=os.getenv("DB_USER"),
    passwd=os.getenv("DB_PASSWORD"),
    db=os.getenv("DB_NAME"),
)
cur = conn.cursor()

cur.execute("""
    SELECT COLUMN_NAME FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'user_active_sessions'
""")
if not cur.fetchall():
    print("user_active_sessions does not exist in this database (it is created")
    print("on first login by the existing bootstrap). Nothing to inspect.")
    cur.close()
    conn.close()
    sys.exit(0)

cur.execute("""
    SELECT s.userID, s.sessionID, s.clientType, s.issuedAt,
           TIMESTAMPDIFF(SECOND, s.issuedAt, CURRENT_TIMESTAMP) AS age_seconds,
           u.fullName, u.email
    FROM user_active_sessions s
    LEFT JOIN users u ON u.userID = s.userID
    ORDER BY age_seconds DESC
""")
rows = cur.fetchall()

print(f"user_active_sessions: {len(rows)} row(s)\n")
if not rows:
    print("No sessions are being held. Any account can sign in.")
    cur.close()
    conn.close()
    sys.exit(0)

buckets = {"ACTIVE": [], "RECENT": [], "STALE": [], "EXPIRED": []}
for user_id, sid, client_type, issued_at, age, full_name, email in rows:
    if age >= JWT_HOURS * 3600:
        label = "EXPIRED"
    elif age > IDLE_SECONDS:
        label = "STALE"
    elif age > 60:
        label = "RECENT"
    else:
        label = "ACTIVE"
    buckets[label].append((user_id, sid, client_type, age, full_name, email))

WIDTH = {"ACTIVE": 70, "RECENT": 70, "STALE": 70, "EXPIRED": 70}
for label in ("STALE", "RECENT", "ACTIVE", "EXPIRED"):
    entries = buckets[label]
    if not entries:
        continue
    print(f"--- {label} ({len(entries)}) ---")
    for user_id, sid, client_type, age, full_name, email in entries:
        mins = age / 60.0
        print(
            f"  user {user_id:<5} {str(client_type):<7} "
            f"idle {mins:8.1f} min  session {sid[:12]}...  "
            f"{full_name or '?'} <{email or '?'}>"
        )
    print()

print("SUMMARY")
for label in ("ACTIVE", "RECENT", "STALE", "EXPIRED"):
    print(f"  {label:<8} {len(buckets[label])}")
print()

stale = buckets["STALE"]
if stale:
    print(
        "STALE rows are the cause of 'This account is already signed in'.\n"
        "They are released automatically on the next login attempt for that\n"
        "account, or when the 12-hour JWT lifetime elapses - a restart of the\n"
        "API server is no longer required for them to clear."
    )
    if CLEAR:
        print("\n--clear requested: removing STALE rows now.")
        removed = 0
        for user_id, sid, *_ in stale:
            cur.execute(
                "DELETE FROM user_active_sessions WHERE userID = %s AND sessionID = %s",
                (user_id, sid),
            )
            removed += cur.rowcount
        conn.commit()
        print(f"Removed {removed} stale row(s).")
    else:
        print(
            "\nRe-run with --clear to remove them. This DELETES records and "
            "will\nsign the affected users out of any device still using them."
        )
else:
    print("No stale sessions are holding any account.")

cur.close()
conn.close()