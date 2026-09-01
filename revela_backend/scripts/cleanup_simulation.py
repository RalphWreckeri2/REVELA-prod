"""
Cleanup script to remove simulated test data after testing.
"""
import pymysql

conn = pymysql.connect(
    host="127.0.0.1",
    port=3306,
    user="revela_user",
    password="dalkoman1-9",
    database="revela_db",
    cursorclass=pymysql.cursors.DictCursor
)

with conn.cursor() as cur:
    cur.execute("DELETE FROM geospatial_logs WHERE detectedName = 'SIMULATED 2025 BUSINESS'")
    cur.execute("DELETE FROM official_registry WHERE businessName = 'SIMULATED 2025 BUSINESS'")
    cur.execute("DELETE FROM revela_notifications WHERE type = 'new_year_rollover'")
    conn.commit()
    print("✅ Simulated test data cleaned up successfully!")

conn.close()
