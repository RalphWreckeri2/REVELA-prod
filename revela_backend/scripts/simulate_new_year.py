"""
Simulate New Year Expiration helper script.
Creates a test business from a previous year (2025) with an Active permit and a Green map flag.
When you open the REVELA web app as an Admin, the New Year Rollover will trigger!
"""
import sys
import os
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
    # 1. Clean previous simulation if any
    cur.execute("DELETE FROM geospatial_logs WHERE detectedName = 'SIMULATED 2025 BUSINESS'")
    cur.execute("DELETE FROM official_registry WHERE businessName = 'SIMULATED 2025 BUSINESS'")
    cur.execute("DELETE FROM revela_notifications WHERE type = 'new_year_rollover'")

    # 2. Get Barangay I ID
    cur.execute("SELECT barangayID FROM barangays LIMIT 1")
    brgy = cur.fetchone()
    bid = brgy["barangayID"] if brgy else 1

    # 3. Insert active business from 2025
    cur.execute("""
        INSERT INTO official_registry 
            (barangayID, businessName, businessType, lineOfBusiness, businessAddress, applicationStatus, lastRenewalDate, latitude, longitude)
        VALUES 
            (%s, 'SIMULATED 2025 BUSINESS', 'Retail Store', 'General Merchandise', 'Poblacion, Mataasnakahoy', 'Active', '2025-08-15 09:00:00', 13.9667, 121.1167)
    """, (bid,))

    # 4. Insert corresponding Green map pin in geospatial_logs
    cur.execute("""
        INSERT INTO geospatial_logs 
            (barangayID, detectedName, latitude, longitude, flagColor, nearestLandmark)
        VALUES 
            (%s, 'SIMULATED 2025 BUSINESS', 13.9667, 121.1167, 'Green', 'Near Municipal Hall')
    """, (bid,))

    conn.commit()
    print("==================================================================")
    print("✅ TEST DATA SEEDED SUCCESSFULLY!")
    print("Business: 'SIMULATED 2025 BUSINESS'")
    print("Permit Status: Active (Permit Year: 2025)")
    print("Map Flag: Green")
    print("------------------------------------------------------------------")
    print("👉 Now, open or refresh the REVELA Web App (Home Page) as Admin.")
    print("You should see the 'Happy New Year!' popup!")
    print("After rollover, its status will be Expired and its pin will be Red.")
    print("==================================================================")

conn.close()
