import os
import pymysql
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))
password = os.getenv("DB_PASSWORD") or os.getenv("MYSQLPASSWORD")
if not password:
    raise SystemExit("Set DB_PASSWORD before running this utility.")

conn = pymysql.connect(
    host=os.getenv("DB_HOST", "127.0.0.1"),
    port=int(os.getenv("DB_PORT", "3306")),
    user=os.getenv("DB_USER", "revela_user"),
    password=password,
    database=os.getenv("DB_NAME", "revela_db"),
)
cur = conn.cursor()

cur.execute("SHOW COLUMNS FROM official_registry LIKE 'applicationStatus'")
print("enum:", cur.fetchone())

cur.execute(
    "SELECT applicationStatus, COUNT(*) FROM official_registry GROUP BY applicationStatus")
print("registry statuses:")
for r in cur.fetchall():
    print(" ", r)

cur.execute("""SELECT flagColor, COUNT(*) FROM geospatial_logs
               WHERE reportedByUserID IS NULL GROUP BY flagColor""")
print("registry-seeded map pins:")
for r in cur.fetchall():
    print(" ", r)

conn.close()
