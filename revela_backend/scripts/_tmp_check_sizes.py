import pymysql

conn = pymysql.connect(
    host="127.0.0.1",
    port=3306,
    user="revela_user",
    password="dalkoman1-9",
    database="revela_db",
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
    print(f"Size: {row['size_label']} | Status: {row['applicationStatus']} | Count: {row['count']}")

conn.close()
