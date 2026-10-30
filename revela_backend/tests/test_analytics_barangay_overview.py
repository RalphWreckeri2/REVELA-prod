import unittest
from unittest.mock import MagicMock, patch

from flask import Flask

from api.analytics import routes


BARANGAY_NAMES = {
    1: "Barangay I",
    2: "Barangay II",
    3: "Barangay II-A",
    4: "Barangay III",
    5: "Barangay IV",
    6: "Barangay Bayorbor",
    7: "Barangay Bubuyan",
    8: "Barangay Calingatan",
    9: "Barangay Loob",
    10: "Barangay Lumanglipa",
    11: "Barangay Kinalaglagan",
    12: "Barangay Manggahan",
    13: "Barangay Nangkaan",
    14: "Barangay San Sebastian",
    15: "Barangay Santol",
    16: "Barangay Upa",
}


class BarangayOverviewCursor:
    def __init__(self):
        self.sql_calls = []
        self.rows = []

    def execute(self, sql, params=()):
        self.sql_calls.append((sql, params))
        is_barber_filter = "barbershopactivities" in params
        if "SELECT barangayID, barangayName FROM barangays" in sql:
            self.rows = [
                {"barangayID": key, "barangayName": value}
                for key, value in BARANGAY_NAMES.items()
            ]
        elif "SELECT COUNT(*) AS total FROM official_registry" in sql:
            total = (
                8 if is_barber_filter
                else 170 if "display_sector_key = %s" in sql
                else 602
            )
            self.rows = [{"total": total}]
        elif "SELECT o.barangayID, COUNT(*) AS total" in sql:
            total = (
                8 if is_barber_filter
                else 170 if "display_sector_key = %s" in sql
                else 602
            )
            self.rows = [{
                "barangayID": 1,
                "total": total,
            }]
        elif "FROM display_sector" in sql and "GROUP BY display_sector_key" in sql:
            self.rows = [
                {"display_sector_key": "retail", "display_sector_label": "Retail"},
                {"display_sector_key": "food_drink", "display_sector_label": "Food and drink"},
            ]
        elif "JOIN registry_sector_map sector_map" in sql:
            self.rows = [{
                "value": "retailsellinggroceries",
                "description": "retail selling in groceries",
                "sector_key": "retail",
                "count": 45,
            }]
            if "display_sector_key = %s" not in sql:
                self.rows.append({
                    "value": "realestatebuyingselling",
                    "description": "real estate buying, selling",
                    "sector_key": "real_estate",
                    "count": 54,
                })
        elif "LEFT JOIN registry_sector_map" in sql:
            count = 170 if "display_sector_key = %s" in sql else 602
            category = "retail" if "display_sector_key = %s" in sql else "unmapped"
            label = "Retail" if category == "retail" else "Needs classification"
            self.rows = [{
                "barangayID": 1,
                "category": category,
                "label": label,
                "count": count,
            }]
        elif "AS registered_on_map" in sql:
            self.rows = [{
                "barangayID": 1,
                "total": 495,
                "registered_on_map": 400,
                "detected_not_in_registry": 50,
                "detection_with_business_id": 5,
                "added_by_inspector": 30,
                "other_source": 10,
                "pins_without_location": 12,
            }]
        elif "AS waiting_for_review" in sql:
            self.rows = [{
                "barangayID": 1,
                "pending": 4,
                "waiting_for_review": 2,
                "verified": 3,
                "total": 9,
                "outcome_green": 1,
                "outcome_yellow": 1,
                "outcome_red": 1,
            }]
        elif "o.businessSize" in sql:
            self.rows = [{"barangayID": 1, "category": "MICRO", "count": 602}]
        elif "o.businessType" in sql:
            self.rows = [{"barangayID": 1, "category": "SOLE PROPRIETORSHIP", "count": 602}]
        elif "o.registrationType" in sql:
            self.rows = [{"barangayID": 1, "category": "NEW", "count": 602}]
        else:
            raise AssertionError(f"Unexpected read query: {sql}")

    def fetchall(self):
        return self.rows

    def fetchone(self):
        return self.rows[0]

    def close(self):
        pass


class BarangayOverviewTests(unittest.TestCase):
    def run_endpoint(self, query):
        app = Flask(__name__)
        cursor = BarangayOverviewCursor()
        mysql_stub = MagicMock()
        mysql_stub.connection.cursor.return_value = cursor
        with app.test_request_context(f"/api/analytics/barangay-overview?{query}"):
            with patch.object(routes, "mysql", mysql_stub), \
                    patch.object(routes, "ladder_columns_available", return_value=False):
                response, status = routes.get_barangay_overview.__wrapped__()
        return response.get_json(), status, cursor

    def test_returns_all_sixteen_rows_and_totals_with_business_id_detection_visible(self):
        data, status, cursor = self.run_endpoint(
            "barangay_id=1&barangay_ids=2,3"
        )

        self.assertEqual(status, 200)
        self.assertEqual(len(data["barangays"]), 16)
        self.assertEqual(
            [row["barangayID"] for row in data["barangays"]],
            list(range(1, 17)),
        )
        self.assertEqual(data["overall"]["registry_total"], 602)
        self.assertEqual(
            {option["sector_key"] for option in data["line_of_business_options"]},
            {"retail", "real_estate"},
        )
        self.assertEqual(data["overall"]["pins"]["total"], 495)
        self.assertEqual(data["overall"]["inspections"]["total"], 9)
        self.assertEqual(
            sum(row["registry_total"] for row in data["barangays"]), 602
        )
        self.assertEqual(
            sum(row["pins"]["total"] for row in data["barangays"]), 495
        )
        self.assertEqual(
            sum(row["inspections"]["total"] for row in data["barangays"]), 9
        )
        self.assertEqual(
            data["barangays"][0]["pins"]["detection_with_business_id"], 5
        )
        self.assertEqual(data["barangays"][0]["pins_without_location"], 12)
        self.assertEqual(data["barangays"][0]["registry"]["business_size"][0]["label"], "Micro")
        self.assertTrue(all(call[0].lstrip().upper().startswith("SELECT")
                            for call in cursor.sql_calls))
        self.assertFalse(any("barangayID IN" in sql for sql, _ in cursor.sql_calls))
        pin_sql = next(sql for sql, _ in cursor.sql_calls if "AS registered_on_map" in sql)
        self.assertIn("g.source IN ('registry', 'registry_detected')", pin_sql)
        self.assertIn("g.source = 'detection' AND g.businessID IS NULL", pin_sql)
        self.assertIn("g.source = 'detection' AND g.businessID IS NOT NULL", pin_sql)
        self.assertIn("g.source = 'manual'", pin_sql)
        self.assertIn("g.latitude IS NULL OR g.longitude IS NULL", pin_sql)
        self.assertTrue(all("reportID" not in sql or "ir.reportID" in sql
                            for sql, _ in cursor.sql_calls))
        self.assertTrue(any("ir.targetID = g.logID" in sql for sql, _ in cursor.sql_calls))
        self.assertFalse(any("g.reportID" in sql for sql, _ in cursor.sql_calls))

    def test_date_bounds_filter_pins_and_inspections_not_registry(self):
        _, status, cursor = self.run_endpoint(
            "detected_from=2026-10-01&inspection_from=2026-10-02"
        )

        self.assertEqual(status, 200)
        registry_queries = [
            sql for sql, _ in cursor.sql_calls
            if "FROM official_registry" in sql
        ]
        pin_queries = [sql for sql, _ in cursor.sql_calls if "FROM geospatial_logs g" in sql]
        inspection_queries = [
            (sql, params) for sql, params in cursor.sql_calls
            if "FROM inspection_reports ir" in sql
        ]
        self.assertTrue(all("detectedDate" not in sql and "irTimestamp" not in sql
                            for sql in registry_queries))
        self.assertTrue(any("detectedDate" in sql for sql in pin_queries))
        self.assertTrue(any("irTimestamp" in sql for sql, _ in inspection_queries))
        self.assertTrue(any(params == ["2026-10-01", "2026-10-02"]
                            for _, params in inspection_queries))

    def test_statuses_are_grouped_as_pending_waiting_and_verified(self):
        data, _, cursor = self.run_endpoint("")
        barangay = data["barangays"][0]

        self.assertEqual(barangay["inspections"]["pending"], 4)
        self.assertEqual(barangay["inspections"]["waiting_for_review"], 2)
        self.assertEqual(barangay["inspections"]["verified"], 3)
        self.assertEqual(barangay["inspections"]["outcomes"], {
            "Green": 1,
            "Yellow": 1,
            "Red": 1,
        })
        inspection_sql = next(
            sql for sql, _ in cursor.sql_calls if "AS waiting_for_review" in sql
        )
        self.assertIn("'Assigned', 'Reassigned', 'In Progress'", inspection_sql)
        self.assertIn("ir.verificationStatus = 'Submitted'", inspection_sql)
        self.assertIn("ir.verificationStatus = 'Verified'", inspection_sql)

    def test_sector_filter_changes_registry_only(self):
        data, status, cursor = self.run_endpoint("display_sector=retail")

        self.assertEqual(status, 200)
        self.assertEqual(data["overall"]["registry_total"], 170)
        self.assertEqual(data["overall"]["registry"]["display_sector"], [{
            "value": "retail",
            "label": "Retail",
            "short_label": "Retail",
            "count": 170,
        }])
        self.assertEqual(data["overall"]["pins"]["total"], 495)
        self.assertEqual(data["overall"]["inspections"]["total"], 9)
        self.assertEqual(data["display_sectors"][0]["value"], "retail")

        registry_queries = [
            sql for sql, _ in cursor.sql_calls if "FROM official_registry" in sql
        ]
        self.assertTrue(registry_queries)
        self.assertTrue(all("registry_sector_map" in sql for sql in registry_queries))
        pin_sql = next(sql for sql, _ in cursor.sql_calls if "AS registered_on_map" in sql)
        inspection_sql = next(
            sql for sql, _ in cursor.sql_calls if "AS waiting_for_review" in sql
        )
        self.assertNotIn("registry_sector_map", pin_sql)
        self.assertNotIn("registry_sector_map", inspection_sql)

    def test_primary_line_filter_changes_registry_only_and_uses_full_normalized_key(self):
        data, status, cursor = self.run_endpoint(
            "display_sector=retail&line_of_business_key=retailsellinggroceries"
        )

        self.assertEqual(status, 200)
        self.assertEqual(data["overall"]["registry_total"], 170)
        self.assertEqual(data["overall"]["pins"]["total"], 495)
        self.assertEqual(data["overall"]["inspections"]["total"], 9)
        self.assertEqual(data["line_of_business_options"][0], {
            "value": "retailsellinggroceries",
            "label": "Retail Selling In Groceries (45)",
            "sector_key": "retail",
            "count": 45,
        })
        self.assertEqual(
            {option["sector_key"] for option in data["line_of_business_options"]},
            {"retail"},
        )

        registry_queries = [
            (sql, params) for sql, params in cursor.sql_calls
            if "FROM official_registry o" in sql
        ]
        self.assertTrue(registry_queries)
        filtered_registry_queries = [
            (sql, params) for sql, params in registry_queries
            if "primary_line.normalized_line_of_business" in sql
        ]
        self.assertTrue(filtered_registry_queries)
        self.assertTrue(all(
            "line_of_business_key" not in sql for sql, _ in registry_queries
        ))
        self.assertTrue(any(
            "retailsellinggroceries" in params
            for _, params in filtered_registry_queries
        ))
        self.assertTrue(all(
            "COLLATE utf8mb4_unicode_ci" in sql
            for sql, _ in filtered_registry_queries
        ))
        pin_sql = next(
            sql for sql, _ in cursor.sql_calls if "AS registered_on_map" in sql
        )
        inspection_sql = next(
            sql for sql, _ in cursor.sql_calls if "AS waiting_for_review" in sql
        )
        self.assertNotIn("registry_sector_map", pin_sql)
        self.assertNotIn("primary_line", pin_sql)
        self.assertNotIn("registry_sector_map", inspection_sql)
        self.assertNotIn("primary_line", inspection_sql)

    def test_barber_primary_line_filter_keeps_map_and_inspection_totals(self):
        data, status, cursor = self.run_endpoint(
            "line_of_business_key=barbershopactivities"
        )

        self.assertEqual(status, 200)
        self.assertEqual(data["overall"]["registry_total"], 8)
        self.assertEqual(data["overall"]["pins"]["total"], 495)
        self.assertEqual(data["overall"]["inspections"]["total"], 9)
        registry_queries = [
            (sql, params) for sql, params in cursor.sql_calls
            if "FROM official_registry o" in sql
        ]
        filtered_registry_queries = [
            (sql, params) for sql, params in registry_queries
            if "AND EXISTS (" in sql
        ]
        self.assertTrue(filtered_registry_queries)
        self.assertTrue(all(
            "barbershopactivities" in params
            for _, params in filtered_registry_queries
        ))
        self.assertTrue(all(
            "COLLATE utf8mb4_unicode_ci" in sql
            for sql, _ in filtered_registry_queries
        ))
        pin_sql = next(
            sql for sql, _ in cursor.sql_calls if "AS registered_on_map" in sql
        )
        inspection_sql = next(
            sql for sql, _ in cursor.sql_calls if "AS waiting_for_review" in sql
        )
        self.assertNotIn("AND EXISTS (", pin_sql)
        self.assertNotIn("AND EXISTS (", inspection_sql)


if __name__ == "__main__":
    unittest.main()
