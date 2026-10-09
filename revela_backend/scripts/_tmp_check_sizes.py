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
    cursorclass=pymysql.cursors.DictCursor
)
cur = conn.cursor()

cur.execute("""
    SELECT 
        COALESCE(businessSize, 'Unknown') AS size_label, 
        applicationStatus, 
        COUNT(*) AS count 
    FROM official_registry 
    GROUP BY businessSize, applicationStatus
""")

for row in cur.fetchall():
    print(
        f"Size: {row['size_label']} | Status: {row['applicationStatus']} | Count: {row['count']}")

conn.close()
