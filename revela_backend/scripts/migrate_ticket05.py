import os
import MySQLdb
import dotenv

dotenv.load_dotenv()

def run_migration():
    host = os.getenv("DB_HOST", "127.0.0.1")
    port = int(os.getenv("DB_PORT", 3306))
    user = os.getenv("DB_USER", "revela_user")
    passwd = os.getenv("DB_PASSWORD", "dalkoman1-9")
    dbname = os.getenv("DB_NAME", "revela_db")

    print(f"Connecting to MySQL at {host}:{port}/{dbname}...")
    db = MySQLdb.connect(host=host, port=port, user=user, passwd=passwd, db=dbname)
    cursor = db.cursor()

    try:
        # 1. Stage A - geospatial_logs: add businessID column, index, and FK
        cursor.execute("DESCRIBE geospatial_logs")
        columns = [row[0] for row in cursor.fetchall()]
        if "businessID" not in columns:
            print("Adding businessID, idx_geo_business, idx_geo_place, and fk_geo_business to geospatial_logs...")
            cursor.execute("""
                ALTER TABLE geospatial_logs
                  ADD COLUMN businessID VARCHAR(50) COLLATE utf8mb4_unicode_ci NULL AFTER barangayID,
                  ADD KEY idx_geo_business (businessID),
                  ADD KEY idx_geo_place (placeID),
                  ADD CONSTRAINT fk_geo_business FOREIGN KEY (businessID)
                    REFERENCES official_registry (businessID) ON DELETE SET NULL ON UPDATE CASCADE
            """)
            print("Stage A.1: geospatial_logs altered successfully.")
        else:
            print("Stage A.1: geospatial_logs.businessID already exists.")

        # 2. Stage A - official_registry: add idx_reg_place and resolveKey
        cursor.execute("DESCRIBE official_registry")
        reg_columns = [row[0] for row in cursor.fetchall()]
        if "resolveKey" not in reg_columns:
            print("Adding resolveKey and idx_reg_place to official_registry...")
            cursor.execute("""
                ALTER TABLE official_registry
                  ADD KEY idx_reg_place (placeID),
                  ADD COLUMN resolveKey CHAR(40) NULL
            """)
            print("Stage A.2: official_registry altered successfully.")
        else:
            print("Stage A.2: official_registry.resolveKey already exists.")

        # 3. Stage A - registry_rejected_places table
        print("Creating table registry_rejected_places if not exists...")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS registry_rejected_places (
              businessID VARCHAR(50) COLLATE utf8mb4_unicode_ci NOT NULL,
              placeID VARCHAR(255) COLLATE utf8mb4_unicode_ci NOT NULL,
              rejectedAt DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
              PRIMARY KEY (businessID, placeID),
              CONSTRAINT fk_rej_business FOREIGN KEY (businessID)
                REFERENCES official_registry (businessID) ON DELETE CASCADE ON UPDATE CASCADE
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """)
        print("Stage A.3: registry_rejected_places created or already exists.")

        # 4. Stage B - Unambiguous Backfill
        print("Running Stage B unambiguous backfill...")
        cursor.execute("""
            UPDATE geospatial_logs g
            JOIN (
              SELECT barangayID, businessName, MIN(businessID) AS bid
              FROM official_registry
              GROUP BY barangayID, businessName
              HAVING COUNT(*) = 1
            ) r ON r.barangayID = g.barangayID AND LOWER(r.businessName) = LOWER(g.detectedName)
            SET g.businessID = r.bid
            WHERE g.businessID IS NULL AND g.flagColor <> 'Red'
        """)
        affected_rows = cursor.rowcount
        db.commit()
        print(f"Stage B: Unambiguous backfill complete. Rows updated: {affected_rows}")

        # Verify foreign keys
        cursor.execute("""
            SELECT CONSTRAINT_NAME, TABLE_NAME, COLUMN_NAME, REFERENCED_TABLE_NAME, REFERENCED_COLUMN_NAME
            FROM information_schema.KEY_COLUMN_USAGE
            WHERE TABLE_SCHEMA = %s AND TABLE_NAME IN ('geospatial_logs', 'registry_rejected_places')
              AND REFERENCED_TABLE_NAME IS NOT NULL
        """, (dbname,))
        fks = cursor.fetchall()
        print("Active Foreign Keys:")
        for fk in fks:
            print(f" - {fk[0]} on {fk[1]}.{fk[2]} -> {fk[3]}.{fk[4]}")

    finally:
        cursor.close()
        db.close()

if __name__ == "__main__":
    run_migration()
