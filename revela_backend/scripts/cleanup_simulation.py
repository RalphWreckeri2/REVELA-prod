"""
Cleanup script to remove simulated test data after testing.
"""
import os
import pymysql
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))
if os.getenv("REVELA_ENV", "").strip().lower() != "revela-dev":
    raise SystemExit("This cleanup utility requires REVELA_ENV=revela-dev.")
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

with conn.cursor() as cur:
    cur.execute(
        "DELETE FROM geospatial_logs WHERE detectedName = 'SIMULATED 2025 BUSINESS'")
    cur.execute(
        "DELETE FROM official_registry WHERE businessName = 'SIMULATED 2025 BUSINESS'")
    cur.execute(
        "DELETE FROM revela_notifications WHERE type = 'new_year_rollover'")
    conn.commit()
    print("✅ Simulated test data cleaned up successfully!")

conn.close()
