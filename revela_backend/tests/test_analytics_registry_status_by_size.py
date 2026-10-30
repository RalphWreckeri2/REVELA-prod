import unittest
from unittest.mock import MagicMock, patch

from flask import Flask

from api.analytics import routes


BARANGAYS = [
    {"barangayID": 1, "barangayName": "Barangay I"},
    {"barangayID": 2, "barangayName": "Barangay II"},
]

GROUPED_ROWS = [
    {
        "barangay_id": 1,
        "barangay_name": "Barangay I",
        "business_size": "MICRO",
        "application_status": "Active",
        "business_count": 2,
    },
    {
        "barangay_id": 1,
        "barangay_name": "Barangay I",
        "business_size": "MICRO",
        "application_status": "Pending",
        "business_count": 1,
    },
    {
        "barangay_id": 1,
        "barangay_name": "Barangay I",
        "business_size": "SMALL",
        "application_status": "Expired",
        "business_count": 1,
    },
    {
        "barangay_id": -1,
        "barangay_name": "Unknown/Unassigned",
        "business_size": "Unknown",
        "application_status": "Closed",
        "business_count": 1,
    },
]


class RegistryStatusCursor:
    def __init__(self, grouped_rows=None):
        self.calls = []
        self.grouped_rows = grouped_rows or GROUPED_ROWS
        self.rows = []

    def execute(self, sql, params=()):
        self.calls.append((sql, params))
        if "SELECT barangayID, barangayName" in sql:
            self.rows = BARANGAYS
        elif "FROM official_registry o" in sql:
            self.rows = self.grouped_rows
        else:
            raise AssertionError(f"Unexpected query: {sql}")

    def fetchall(self):
        return self.rows

    def close(self):
        pass


class RegistryStatusBySizeTests(unittest.TestCase):
    def run_endpoint(self, query="", grouped_rows=None):
        app = Flask(__name__)
        cursor = RegistryStatusCursor(grouped_rows)
        mysql_stub = MagicMock()
        mysql_stub.connection.cursor.return_value = cursor
        with app.test_request_context(
            f"/api/analytics/registry-status-by-size?{query}"
        ):
            with patch.object(routes, "mysql", mysql_stub):
                response, status = (
                    routes.get_registry_status_by_size.__wrapped__()
                )
        return response.get_json(), status, cursor

    def test_aggregates_status_and_size_counts_with_reconciling_totals(self):
        data, status, cursor = self.run_endpoint()

        self.assertEqual(status, 200)
        self.assertEqual(data["total"], 5)
        self.assertEqual(data["municipality"]["total"], 5)
        self.assertEqual(
            data["municipality"]["status_counts"]["Active"], 2
        )
        self.assertEqual(
            data["municipality"]["status_counts"]["Pending"], 1
        )
        self.assertEqual(
            data["municipality"]["status_counts"]["Expired"], 1
        )
        self.assertEqual(data["municipality"]["status_counts"]["Closed"], 1)
        self.assertEqual(
            data["municipality"]["status_percentages"]["Active"], 40.0
        )
        self.assertEqual(
            data["municipality"]["business_sizes"][0]["business_size"],
            "MICRO",
        )
        self.assertEqual(
            data["municipality"]["business_sizes"][0]["total"], 3
        )
        self.assertAlmostEqual(
            data["municipality"]["business_sizes"][0]
            ["status_percentages"]["Active"],
            200 / 3,
        )
        self.assertEqual(data["barangays"][0]["barangayID"], 1)
        self.assertEqual(data["barangays"][0]["total"], 4)
        self.assertEqual(data["barangays"][1]["total"], 0)
        self.assertIsNone(
            data["barangays"][1]["status_percentages"]["Active"]
        )
        self.assertEqual(data["barangays"][-1]["barangayName"], "Unknown/Unassigned")
        self.assertEqual(data["barangays"][-1]["total"], 1)
        self.assertEqual(
            sum(row["total"] for row in data["barangays"]),
            data["municipality"]["total"],
        )
        grouped_sql = next(
            sql for sql, _ in cursor.calls if "FROM official_registry o" in sql
        )
        self.assertIn("COUNT(DISTINCT o.businessID)", grouped_sql)
        self.assertIn("LEFT JOIN barangays b", grouped_sql)
        self.assertNotIn("geospatial_logs", grouped_sql.lower())
        self.assertNotIn("enforcement_state", grouped_sql.lower())
        self.assertNotIn("inspection_reports", grouped_sql.lower())
        for sensitive_column in (
            "businessName",
            "businessAddress",
            "latitude",
            "longitude",
            "placeID",
            "reportedByUserID",
        ):
            self.assertNotIn(sensitive_column.lower(), grouped_sql.lower())
        self.assertTrue(all(
            sql.lstrip().upper().startswith("SELECT")
            for sql, _ in cursor.calls
        ))

    def test_applies_registry_filters_and_reports_active_scope(self):
        data, status, cursor = self.run_endpoint(
            "barangay_id=1&business_size=MICRO&application_status=Active"
        )

        self.assertEqual(status, 200)
        grouped_sql, params = next(
            call for call in cursor.calls if "FROM official_registry o" in call[0]
        )
        self.assertIn("o.barangayID IN (%s)", grouped_sql)
        self.assertIn("o.businessSize = %s", grouped_sql)
        self.assertIn("o.applicationStatus = %s", grouped_sql)
        self.assertEqual(params, [1, "Active", "MICRO"])
        self.assertEqual(data["filters_applied"]["barangay_ids"], [1])
        self.assertEqual(data["filters_applied"]["business_size"], "MICRO")
        self.assertEqual(
            data["filters_applied"]["application_status"], "Active"
        )

    def test_reports_line_of_business_key_in_scope_metadata(self):
        data, status, _ = self.run_endpoint(
            "line_of_business_key=retailsellinggroceries"
        )

        self.assertEqual(status, 200)
        self.assertEqual(
            data["filters_applied"]["line_of_business_key"],
            "retailsellinggroceries",
        )
        self.assertIn("as_of", data)
        self.assertEqual(
            data["statuses"],
            ["Active", "Expired", "Revoked", "Pending", "Closed"],
        )


if __name__ == "__main__":
    unittest.main()
