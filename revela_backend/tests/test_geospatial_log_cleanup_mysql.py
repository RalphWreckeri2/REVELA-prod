"""Disposable-MySQL coverage for detection-pin cleanup SQL."""

import unittest

from shapely.geometry import Polygon

from scripts.cleanup_detection_geospatial_logs import (
    AUDIT_TABLE,
    apply_plan,
    build_plan,
    map_barangay_ids,
    read_totals,
)
from tests import test_registry_inspection_sync as mysql_test_support


class GeospatialLogCleanupMySQLTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if mysql_test_support.connect_to_disposable_mysql is None:
            raise unittest.SkipTest(
                "Use scripts/run_registry_sync_audit.py with the disposable MySQL server."
            )
        cls.db = mysql_test_support.connect_to_disposable_mysql()
        with cls.db.cursor() as cursor:
            cursor.execute(
                """CREATE TABLE barangays (
                    barangayID INT PRIMARY KEY,
                    barangayName VARCHAR(80) NOT NULL
                ) ENGINE=InnoDB"""
            )
            cursor.execute(
                """CREATE TABLE geospatial_logs (
                    logID INT AUTO_INCREMENT PRIMARY KEY,
                    barangayID INT NOT NULL,
                    businessID VARCHAR(50) NULL,
                    reportID INT NULL,
                    latitude DECIMAL(10,8) NULL,
                    longitude DECIMAL(11,8) NULL,
                    source VARCHAR(24) NOT NULL,
                    flagColor VARCHAR(50) NULL
                ) ENGINE=InnoDB"""
            )
            cursor.execute(
                """CREATE TABLE inspection_reports (
                    reportID INT AUTO_INCREMENT PRIMARY KEY,
                    targetID INT NOT NULL
                ) ENGINE=InnoDB"""
            )
            cursor.execute(
                "INSERT INTO barangays (barangayID, barangayName) VALUES "
                "(1, 'Barangay I'), (2, 'Barangay II')"
            )
        cls.db.commit()

    @classmethod
    def tearDownClass(cls):
        cls.db.close()

    def setUp(self):
        with self.db.cursor() as cursor:
            cursor.execute("DELETE FROM inspection_reports")
            cursor.execute("DELETE FROM geospatial_logs")
            cursor.execute(
                """INSERT INTO geospatial_logs
                    (logID, barangayID, businessID, reportID, latitude, longitude, source, flagColor)
                    VALUES
                    (1, 1, NULL, NULL, 13.90500000, 121.11500000, 'detection', 'Yellow'),
                    (2, 1, NULL, NULL, 13.90500000, 121.13000000, 'detection', 'Red'),
                    (3, 1, 'BIZ-3', NULL, 13.90500000, 121.13000000, 'detection', 'Red'),
                    (4, 1, NULL, 44, 13.90500000, 121.13000000, 'detection', 'Yellow'),
                    (5, 1, NULL, NULL, 13.90500000, 121.13000000, 'detection', 'Red'),
                    (6, 1, NULL, NULL, 13.90500000, 121.11500000, 'registry', 'Green'),
                    (7, 1, NULL, NULL, 13.90500000, 121.11500000, 'manual', 'Yellow'),
                    (8, 1, NULL, NULL, 13.90500000, 121.11500000, 'registry_detected', 'Green')
                """
            )
            cursor.execute(
                "INSERT INTO inspection_reports (reportID, targetID) VALUES (10, 5)"
            )
        self.db.commit()

    def _plan(self, cursor):
        boundaries = [
            ("District I (Pob.)", Polygon([
                (121.10, 13.90), (121.11, 13.90), (121.11, 13.91),
                (121.10, 13.91), (121.10, 13.90),
            ])),
            ("Barangay II-A (Pob.)", Polygon([
                (121.11, 13.90), (121.12, 13.90), (121.12, 13.91),
                (121.11, 13.91), (121.11, 13.90),
            ])),
        ]
        ids_by_name, _ = map_barangay_ids(
            boundaries,
            [
                {"barangayID": 1, "barangayName": "Barangay I"},
                {"barangayID": 2, "barangayName": "Barangay II-A"},
            ],
        )
        self.assertEqual(ids_by_name, {
            "District I (Pob.)": 1,
            "Barangay II-A (Pob.)": 2,
        })
        return build_plan(cursor, boundaries, ids_by_name)

    def test_mysql_plan_and_confirmed_sql_preserve_safeguards(self):
        with self.db.cursor() as cursor:
            before = read_totals(cursor)
            plan = self._plan(cursor)

        self.assertEqual(before, {
            "pins": 8,
            "detected_not_in_registry": 4,
            "red": 3,
        })
        self.assertEqual(plan["pair_counts"][(1, 2)], 1)
        self.assertEqual([row["logID"] for row in plan["updates"]], [1])
        self.assertEqual([row["logID"] for row in plan["deletions"]], [2])
        self.assertEqual(
            {row["logID"]: row["blockers"] for row in plan["outside"] if row["blockers"]},
            {
                3: ["businessID is not NULL"],
                4: ["reportID is not NULL"],
                5: ["an inspection_reports row references targetID"],
            },
        )
        self.assertGreater(plan["outside"][0]["distance_m"], 0)

        # Planning is read-only; the test then exercises the production MySQL DML.
        with self.db.cursor() as cursor:
            self.assertEqual(read_totals(cursor), before)
            cursor.execute(
                "SELECT barangayID FROM geospatial_logs WHERE logID = 1"
            )
            self.assertEqual(cursor.fetchone()["barangayID"], 1)

        backup_table = "geospatial_logs_backup_20990101"
        apply_plan(self.db, plan, backup_table)

        with self.db.cursor() as cursor:
            cursor.execute(
                "SELECT barangayID FROM geospatial_logs WHERE logID = 1"
            )
            self.assertEqual(cursor.fetchone()["barangayID"], 2)
            cursor.execute(
                "SELECT COUNT(*) AS count FROM geospatial_logs WHERE logID = 2"
            )
            self.assertEqual(cursor.fetchone()["count"], 0)
            cursor.execute(
                "SELECT COUNT(*) AS count FROM geospatial_logs "
                "WHERE source IN ('registry', 'registry_detected', 'manual')"
            )
            self.assertEqual(cursor.fetchone()["count"], 3)
            cursor.execute(
                f"SELECT logID, oldBarangayID, newBarangayID, rule "
                f"FROM `{AUDIT_TABLE}` ORDER BY logID"
            )
            audit_rows = cursor.fetchall()
            self.assertEqual(
                [(row["logID"], row["oldBarangayID"], row["newBarangayID"]) for row in audit_rows],
                [(1, 1, "2"), (2, 1, "deleted")],
            )
            cursor.execute(f"SELECT COUNT(*) AS count FROM `{backup_table}`")
            self.assertEqual(cursor.fetchone()["count"], 2)
            after = read_totals(cursor)
        self.assertEqual(after, {
            "pins": 7,
            "detected_not_in_registry": 3,
            "red": 2,
        })
