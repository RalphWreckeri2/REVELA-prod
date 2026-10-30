"""DBSCAN population tests against the audit runner's disposable MySQL server."""

import unittest

from shapely.geometry import box

from api.analytics.hotspots import (
    HOTSPOT_POPULATION_OBJECTIVE,
    HOTSPOT_POPULATION_UNREGISTERED,
    build_hotspot_population_sql,
    cluster_hotspot_rows,
    count_hotspot_dispositions,
    resolve_hotspot_parameters,
)


connect_to_disposable_mysql = None


class HotspotPopulationMySQLTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if connect_to_disposable_mysql is None:
            raise RuntimeError("The disposable MySQL runner must inject its connection.")
        cls.db = connect_to_disposable_mysql()
        with cls.db.cursor() as cursor:
            cursor.execute("""
                CREATE TABLE barangays (
                    barangayID INT PRIMARY KEY,
                    barangayName VARCHAR(100) NOT NULL
                )
            """)
            cursor.execute("""
                CREATE TABLE official_registry (
                    businessID VARCHAR(64) PRIMARY KEY
                )
            """)
            cursor.execute("""
                CREATE TABLE geospatial_logs (
                    logID INT PRIMARY KEY,
                    businessID VARCHAR(64) NULL,
                    barangayID INT NULL,
                    detectedName VARCHAR(100) NOT NULL,
                    detectedDate DATE NULL,
                    flagColor VARCHAR(16) NOT NULL,
                    blackLocked TINYINT NOT NULL DEFAULT 0,
                    latitude DOUBLE NULL,
                    longitude DOUBLE NULL,
                    source VARCHAR(32) NULL
                )
            """)
            cursor.execute(
                "INSERT INTO barangays (barangayID, barangayName) "
                "VALUES (1, 'Fixture Barangay')"
            )
            cursor.execute(
                "INSERT INTO official_registry (businessID) VALUES ('LINKED-RED')"
            )
            cursor.executemany("""
                INSERT INTO geospatial_logs
                    (logID, businessID, barangayID, detectedName, detectedDate,
                     flagColor, blackLocked, latitude, longitude, source)
                VALUES (%s, %s, 1, %s, '2026-01-01', %s, %s, %s, %s, %s)
            """, [
                (1, None, "Red detection", "Red", 0, 13.00000, 121.00000, "detection"),
                (2, None, "Red manual", "Red", 0, 13.00001, 121.00000, "manual"),
                (3, "LINKED-RED", "Linked Red", "Red", 0, 13.00002, 121.00000, "detection"),
                (4, "UNLINKED-ID", "Business ID Red", "Red", 0, 13.00003, 121.00000, "detection"),
                (5, None, "Black-locked pin", "Red", 1, 13.00004, 121.00000, "detection"),
                (6, None, "Missing coordinates", "Red", 0, None, None, "detection"),
            ])
        cls.db.commit()

    @classmethod
    def tearDownClass(cls):
        cls.db.close()

    @classmethod
    def population_rows(
        cls, population, *, minimum_log_id=None, maximum_log_id=None
    ):
        parameters, _ = resolve_hotspot_parameters({})
        flags = list(parameters["flags"])
        if population == HOTSPOT_POPULATION_UNREGISTERED:
            flags = [flag for flag in flags if flag == "Red"]
        extra_conditions = []
        extra_params = []
        if minimum_log_id is not None:
            extra_conditions.append("g.logID >= %s")
            extra_params.append(minimum_log_id)
        if maximum_log_id is not None:
            extra_conditions.append("g.logID < %s")
            extra_params.append(maximum_log_id)
        extra_where = "".join(f" AND {condition}" for condition in extra_conditions)
        sql, params = build_hotspot_population_sql(
            "CASE WHEN COALESCE(g.blackLocked, 0) <> 0 "
            "THEN 'Black' ELSE g.flagColor END",
            "EXISTS (SELECT 1 FROM official_registry r "
            "WHERE r.businessID = g.businessID)",
            None,
            None,
            population=population,
            flags=flags,
            extra_where_sql=extra_where,
            extra_params=tuple(extra_params),
        )
        with cls.db.cursor() as cursor:
            cursor.execute(sql, params)
            rows = list(cursor.fetchall())
        return rows, flags, parameters

    def test_objective_includes_black_locked_and_registry_linked_candidates_excludes(self):
        objective_rows, objective_flags, _ = self.population_rows(
            HOTSPOT_POPULATION_OBJECTIVE,
            maximum_log_id=1000,
        )
        candidate_rows, candidate_flags, _ = self.population_rows(
            HOTSPOT_POPULATION_UNREGISTERED,
            maximum_log_id=1000,
        )

        objective_eligible = {
            row["logID"] for row in objective_rows
            if row["disposition"] == "eligible"
        }
        candidate_eligible = {
            row["logID"] for row in candidate_rows
            if row["disposition"] == "eligible"
        }
        self.assertEqual(objective_flags, ["Red", "Black"])
        self.assertEqual(candidate_flags, ["Red"])
        self.assertEqual(objective_eligible, {1, 2, 3, 4, 5})
        self.assertEqual(candidate_eligible, {1})
        self.assertEqual(
            next(row for row in objective_rows if row["logID"] == 5)["flagColor"],
            "Black",
        )
        self.assertEqual(
            next(row for row in candidate_rows if row["logID"] == 3)["disposition"],
            "registry_linked",
        )
        self.assertNotIn(5, {row["logID"] for row in candidate_rows})
        objective_counts = count_hotspot_dispositions(
            objective_rows,
            population=HOTSPOT_POPULATION_OBJECTIVE,
            flags=objective_flags,
        )
        self.assertEqual(objective_counts["excluded"]["missing_coordinates"], 1)

    def test_199_red_detection_shape_has_identical_population_inputs_and_clusters(self):
        with self.db.cursor() as cursor:
            cursor.executemany("""
                INSERT INTO geospatial_logs
                    (logID, businessID, barangayID, detectedName, detectedDate,
                     flagColor, blackLocked, latitude, longitude, source)
                VALUES (%s, NULL, 1, 'Shape fixture', '2026-01-01',
                        'Red', 0, 13.001, 121.001, 'detection')
            """, [(log_id,) for log_id in range(1000, 1199)])
        self.db.commit()

        objective_rows, _, parameters = self.population_rows(
            HOTSPOT_POPULATION_OBJECTIVE,
            minimum_log_id=1000,
        )
        candidate_rows, _, _ = self.population_rows(
            HOTSPOT_POPULATION_UNREGISTERED,
            minimum_log_id=1000,
        )
        objective_ids = sorted(
            row["logID"] for row in objective_rows
            if row["disposition"] == "eligible"
        )
        candidate_ids = sorted(
            row["logID"] for row in candidate_rows
            if row["disposition"] == "eligible"
        )
        self.assertEqual(len(objective_ids), 199)
        self.assertEqual(objective_ids, candidate_ids)

        polygons = [{
            "barangay_id": 1,
            "barangay_name": "Fixture Barangay",
            "geometry": box(120.9, 12.9, 121.1, 13.1),
        }]
        objective_clusters, _ = cluster_hotspot_rows(
            objective_rows, parameters, polygons
        )
        candidate_clusters, _ = cluster_hotspot_rows(
            candidate_rows, parameters, polygons
        )
        self.assertEqual(objective_clusters, candidate_clusters)
        self.assertEqual(objective_clusters[0]["log_ids"], objective_ids)
