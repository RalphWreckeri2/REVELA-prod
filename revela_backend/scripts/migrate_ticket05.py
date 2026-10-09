import os
import MySQLdb
import dotenv

dotenv.load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))


def _index_names(cursor, table_name):
    cursor.execute(f"SHOW INDEX FROM `{table_name}`")
    return {
        row.get("Key_name") if isinstance(row, dict) else row[2]
        for row in cursor.fetchall()
    }


def _ensure_index(cursor, table_name, index_name, column_name):
    if index_name in _index_names(cursor, table_name):
        return
    cursor.execute(
        f"ALTER TABLE `{table_name}` ADD KEY `{index_name}` (`{column_name}`)"
    )


def run_migration():
    host = os.getenv("DB_HOST") or os.getenv("MYSQLHOST") or "127.0.0.1"
    port = int(os.getenv("DB_PORT") or os.getenv("MYSQLPORT") or 3306)
    user = os.getenv("DB_USER") or os.getenv("MYSQLUSER") or "revela_user"
    passwd = os.getenv("DB_PASSWORD") or os.getenv("MYSQLPASSWORD")
    if not passwd:
        raise RuntimeError("Set DB_PASSWORD before running this migration.")
    dbname = os.getenv("DB_NAME") or os.getenv("MYSQLDATABASE") or "revela_db"

    print(f"Connecting to MySQL at {host}:{port}/{dbname}...")
    db = MySQLdb.connect(host=host, port=port, user=user,
                         passwd=passwd, db=dbname)
    cursor = db.cursor()

    try:
        # 1. Stage A - geospatial_logs: repair each object independently so a
        # partially applied earlier migration can safely be rerun.
        cursor.execute("DESCRIBE geospatial_logs")
        columns = [row[0] for row in cursor.fetchall()]
        if "businessID" not in columns:
            cursor.execute("""
                ALTER TABLE geospatial_logs
                  ADD COLUMN businessID VARCHAR(50) COLLATE utf8mb4_unicode_ci NULL AFTER barangayID
            """)
        _ensure_index(cursor, "geospatial_logs",
                      "idx_geo_business", "businessID")
        _ensure_index(cursor, "geospatial_logs", "idx_geo_place", "placeID")
        cursor.execute("""
            SELECT CONSTRAINT_NAME
            FROM information_schema.TABLE_CONSTRAINTS
            WHERE TABLE_SCHEMA = %s
              AND TABLE_NAME = 'geospatial_logs'
              AND CONSTRAINT_NAME = 'fk_geo_business'
              AND CONSTRAINT_TYPE = 'FOREIGN KEY'
        """, (dbname,))
        if not cursor.fetchone():
            cursor.execute("""
                ALTER TABLE geospatial_logs
                  ADD CONSTRAINT fk_geo_business FOREIGN KEY (businessID)
                    REFERENCES official_registry (businessID)
                    ON DELETE SET NULL ON UPDATE CASCADE
            """)
        print("Stage A.1: geospatial_logs schema verified.")

        # 2. Stage A - official_registry: independently ensure both objects.
        cursor.execute("DESCRIBE official_registry")
        reg_columns = [row[0] for row in cursor.fetchall()]
        if "resolveKey" not in reg_columns:
            cursor.execute("""
                ALTER TABLE official_registry
                  ADD COLUMN resolveKey CHAR(40) NULL
            """)
        _ensure_index(cursor, "official_registry", "idx_reg_place", "placeID")
        print("Stage A.2: official_registry schema verified.")

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
        print(
            f"Stage B: Unambiguous backfill complete. Rows updated: {affected_rows}")

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
