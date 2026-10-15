"""In-memory DBAPI adapter for registry workflow regressions.

Execute the shipped SQL, substituting only MySQL syntax unsupported by SQLite.
As in the existing color tests, the correlated ORDER BY lookups need SQLite
substitution. These fixtures have one registry candidate, so removing their
ranking gives exactly the same column values. CASE arms are never replaced.
"""
import re
import sqlite3


class RegistryDB:
    def __init__(self, *, ladder=True):
        self.db = sqlite3.connect(":memory:")
        self.db.row_factory = sqlite3.Row
        self.db.create_function("YEAR", 1, lambda value: int(str(value)[:4]) if value else None)
        self.connection = self
        self.calls = []
        self.db.executescript("""
            CREATE TABLE barangays (barangayID INTEGER PRIMARY KEY, barangayName TEXT);
            INSERT INTO barangays VALUES (1, 'Barangay I');
            CREATE TABLE users (userID INTEGER PRIMARY KEY, fullName TEXT, userRole TEXT, isActive INTEGER);
            INSERT INTO users VALUES (2, 'Admin', 'Admin', 1), (9, 'Inspector', 'Inspector', 1);
            CREATE TABLE official_registry (
                businessID TEXT PRIMARY KEY, businessName TEXT, barangayID INTEGER,
                applicationStatus TEXT, businessType TEXT, lineOfBusiness TEXT,
                businessAddress TEXT, lastRenewalDate TEXT, businessSize TEXT,
                registrationType TEXT, latitude REAL, longitude REAL, placeID TEXT,
                coordSource TEXT, placeIDKind TEXT, coordFetchedAt TEXT,
                matchScore REAL, matchStatus TEXT, resolveKey TEXT,
                warningLevel INTEGER DEFAULT 0, blackLocked INTEGER DEFAULT 0,
                blackLockedAt TEXT, blackLockedBy INTEGER, blackLockReason TEXT,
                warningClearedAt TEXT, warningClearedBy INTEGER, warningClearReason TEXT,
                lastInspectionResult TEXT, lastInspectedAt TEXT,
                blackDispatchUnlocked INTEGER DEFAULT 0, blackUnlockedAt TEXT,
                blackUnlockedBy INTEGER, blackUnlockReason TEXT);
            CREATE TABLE geospatial_logs (
                logID INTEGER PRIMARY KEY AUTOINCREMENT, businessID TEXT, barangayID INTEGER,
                detectedName TEXT, flagColor TEXT, noticeLevel INTEGER DEFAULT 0,
                latitude REAL, longitude REAL, placeID TEXT, placeTypes TEXT,
                detectedDate TEXT DEFAULT CURRENT_TIMESTAMP, reportID INTEGER,
                nearestLandmark TEXT, notes TEXT, reportedByUserID INTEGER, source TEXT);
            CREATE TABLE inspection_reports (
                reportID INTEGER PRIMARY KEY AUTOINCREMENT, targetID INTEGER,
                targetType TEXT DEFAULT 'geospatial_log', userID INTEGER,
                verificationStatus TEXT, inspectionResult TEXT, noticeLevel INTEGER DEFAULT 0,
                wasReassigned INTEGER DEFAULT 0, deadline TEXT, irTimestamp TEXT,
                remarks TEXT, photoPath TEXT, submittedAt TEXT, submissionReceivedAt TEXT,
                resolutionTime INTEGER, nearestLandmark TEXT, verifiedLatitude REAL,
                verifiedLongitude REAL, verifiedAccuracy REAL);
            CREATE TABLE inspection_lifecycle_events (
                eventID INTEGER PRIMARY KEY AUTOINCREMENT, reportID INTEGER, targetLogID INTEGER,
                cycleID INTEGER, eventType TEXT, actorUserID INTEGER, assignedToUserID INTEGER,
                flagColorAtEvent TEXT, inspectionResult TEXT, remarks TEXT, eventTimestamp TEXT);
            CREATE TABLE registry_enforcement_events (
                eventID INTEGER PRIMARY KEY AUTOINCREMENT, businessID TEXT, eventType TEXT,
                actorUserID INTEGER, reason TEXT, previousLevel INTEGER, newLevel INTEGER,
                previousBlack INTEGER, newBlack INTEGER);
            CREATE TABLE revela_notifications (
                recipientUserId INTEGER, type TEXT, title TEXT, body TEXT, link TEXT);
        """)
        if not ladder:
            self.db.executescript("""
                ALTER TABLE official_registry DROP COLUMN warningLevel;
                ALTER TABLE official_registry DROP COLUMN blackLocked;
            """)

    def cursor(self):
        return RegistryCursor(self)

    def commit(self):
        self.db.commit()

    def rollback(self):
        self.db.rollback()

    def close(self):
        self.db.close()

    def rows(self, sql, params=()):
        return [dict(row) for row in self.db.execute(sql, params)]

    def seed(self, *, status="Pending", level=1, locked=0, color="Orange", report=True):
        self.db.execute("""INSERT INTO official_registry
            (businessID, businessName, barangayID, applicationStatus, warningLevel, blackLocked,
             latitude, longitude, lastRenewalDate)
            VALUES ('B-1', 'ACME', 1, ?, ?, ?, 13.9667, 121.1167, '2020-01-01')""",
                        (status, level, locked))
        self.db.execute("""INSERT INTO geospatial_logs
            (logID, businessID, detectedName, barangayID, flagColor, noticeLevel, latitude, longitude, source)
            VALUES (1, 'B-1', 'ACME', 1, ?, ?, 13.9667, 121.1167, 'registry')""", (color, level))
        if report:
            self.db.execute("""INSERT INTO inspection_reports
                (reportID, targetID, userID, verificationStatus, inspectionResult, noticeLevel)
                VALUES (1, 1, 9, 'Verified', 'Orange', ?)""", (level,))
        self.commit()


class RegistryCursor:
    def __init__(self, connection):
        self.connection = connection
        self.cursor = connection.db.cursor()

    def execute(self, sql, params=()):
        self.connection.calls.append((sql, params))
        if "information_schema.COLUMNS" in sql:
            table = re.search(r"TABLE_NAME\s*=\s*'([^']+)'", sql)[1]
            sql = "SELECT name AS COLUMN_NAME FROM pragma_table_info(?) WHERE name IN (" + ",".join("?" for _ in params) + ")"
            params = (table, *params)
        elif sql.strip().startswith("SHOW COLUMNS"):
            table, column = re.search(r"SHOW COLUMNS FROM (\w+) LIKE '([^']+)'", sql).groups()
            sql, params = "SELECT name FROM pragma_table_info(?) WHERE name = ?", (table, column)
        else:
            sql = re.sub(
                r"ORDER BY \(r_chk\.businessID = (\w+)\.businessID\) DESC,\s*"
                r"\(r_chk\.placeID = \1\.placeID\) DESC\s*LIMIT 1", "LIMIT 1", sql)
            if "UPDATE geospatial_logs g" in sql and "JOIN official_registry r ON" in sql:
                join, assignments = re.search(
                    r"JOIN official_registry r ON\s*(.*?)\s+SET\s+(.*)", sql, re.DOTALL).groups()
                where = re.search(r"\n\s*WHERE YEAR\(r\.", assignments)
                if where:
                    assignments, condition = assignments[:where.start()], assignments[where.start():].strip()[6:]
                    join = f"({join}) AND ({condition})"
                assignments = assignments.replace("g.noticeLevel =", "noticeLevel =").replace("g.flagColor =", "flagColor =")
                # Keep r visible to SET as well as WHERE, as in MySQL's JOIN
                # update (the expiry expression reads r.warningLevel).
                sql = f"UPDATE geospatial_logs AS g SET {assignments} FROM official_registry AS r WHERE {join}"
            sql = sql.replace("%s", "?").replace("UTC_TIMESTAMP(6)", "CURRENT_TIMESTAMP").replace("NOW()", "CURRENT_TIMESTAMP").replace("CURDATE()", "CURRENT_DATE")
        self.cursor.execute(sql, params)
        return self

    @property
    def rowcount(self):
        return self.cursor.rowcount

    @property
    def lastrowid(self):
        return self.cursor.lastrowid

    def fetchone(self):
        row = self.cursor.fetchone()
        return dict(row) if row is not None else None

    def fetchall(self):
        return [dict(row) for row in self.cursor.fetchall()]

    def close(self):
        self.cursor.close()
