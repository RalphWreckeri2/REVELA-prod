from app import mysql


def insert_green_flag(barangay_id, business_name, lat, lng, address=None, color='Green'):
    cursor = mysql.connection.cursor()
    cursor.execute("""
        INSERT INTO geospatial_logs
            (barangayID, detectedName, latitude, longitude,
             flagColor, nearestLandmark)
        VALUES (%s, %s, %s, %s, %s, %s)
    """, (barangay_id, business_name, lat, lng, color, address))
    cursor.close()


def get_latest_flag(business_name, barangay_id):
    """Get the most recent flagColor for a business."""
    cursor = mysql.connection.cursor()
    cursor.execute(
        """
        SELECT flagColor, detectedDate
        FROM geospatial_logs
        WHERE detectedName = %s AND barangayID = %s
        ORDER BY detectedDate DESC
        LIMIT 1
        """,
        (business_name, barangay_id),
    )
    row = cursor.fetchone()
    cursor.close()
    return row
