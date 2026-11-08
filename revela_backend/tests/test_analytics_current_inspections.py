import sqlite3
import unittest

from api.analytics.routes import _LATEST_INSPECTION_REPORTS_SQL


class LatestInspectionReportsTests(unittest.TestCase):
    def test_selects_only_latest_report_for_each_target(self):
        connection = sqlite3.connect(":memory:")
        try:
            connection.execute(
                "CREATE TABLE inspection_reports "
                "(reportID INTEGER PRIMARY KEY, targetID INTEGER, verificationStatus TEXT)"
            )
            connection.executemany(
                "INSERT INTO inspection_reports VALUES (?, ?, ?)",
                [
                    (1, 100, "Submitted"),
                    (2, 100, "Verified"),
                    (3, 200, "Submitted"),
                ],
            )

            rows = connection.execute(
                f"SELECT ir.reportID, ir.verificationStatus "
                f"FROM {_LATEST_INSPECTION_REPORTS_SQL} ir ORDER BY ir.targetID"
            ).fetchall()
        finally:
            connection.close()

        self.assertEqual(rows, [(2, "Verified"), (3, "Submitted")])


if __name__ == "__main__":
    unittest.main()
