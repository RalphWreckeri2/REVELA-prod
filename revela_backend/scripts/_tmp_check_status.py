import pymysql

conn = pymysql.connect(host="127.0.0.1", port=3306, user="revela_user",
                       password="dalkoman1-9", database="revela_db")
cur = conn.cursor()

cur.execute("SHOW COLUMNS FROM official_registry LIKE 'applicationStatus'")
print("enum:", cur.fetchone())

cur.execute("SELECT applicationStatus, COUNT(*) FROM official_registry GROUP BY applicationStatus")
print("registry statuses:")
for r in cur.fetchall():
    print(" ", r)

cur.execute("""SELECT flagColor, COUNT(*) FROM geospatial_logs
               WHERE reportedByUserID IS NULL GROUP BY flagColor""")
print("registry-seeded map pins:")
for r in cur.fetchall():
    print(" ", r)

conn.close()
