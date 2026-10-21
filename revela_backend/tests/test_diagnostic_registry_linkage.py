"""Diagnostic sector attribution and linkage must use identical registry rules."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(__file__))
from registry_sqlite import RegistryDB

from api.analytics import routes
from api.registry.colors import _effective_flag_color_sql


class DiagnosticRegistryLinkageTests(unittest.TestCase):
    def setUp(self):
        self.db = RegistryDB()
        self.addCleanup(self.db.close)
        self.db.db.executescript("""
            INSERT INTO official_registry
                (businessID, businessName, barangayID, applicationStatus, lineOfBusiness)
            VALUES
                ('B1', 'Registry name one', 1, 'Expired', 'Food'),
                ('B2', 'Unique registry name', 1, 'Expired', 'Retail'),
                ('B3', 'Duplicate name', 1, 'Expired', 'Services'),
                ('B4', 'Duplicate name', 1, 'Expired', 'Services');
            INSERT INTO geospatial_logs
                (logID, businessID, barangayID, detectedName, flagColor, placeID)
            VALUES
                (1, 'B1', 1, 'Different pin label', 'Red', 'P1'),
                (2, NULL, 1, 'Unique registry name', 'Red', 'P2'),
                (3, NULL, 1, 'Duplicate name', 'Red', 'P3'),
                (4, NULL, 1, 'No registry match', 'Red', 'P4'),
                (5, 'UNKNOWN', 1, 'Unique registry name', 'Red', 'P5');
        """)
        self.db.commit()
        self.effective_color = _effective_flag_color_sql("g", ladder=True)
        self.registry_match_sql = routes._diagnostic_registry_match_sql()

    def test_sector_attribution_and_linkage_summary_agree(self):
        cur = self.db.cursor()
        cur.execute(routes._diagnostic_category_risk_sql(
            self.effective_color, self.registry_match_sql, "", ""))
        sector_rows = cur.fetchall()
        cur.execute(routes._diagnostic_category_linkage_sql(
            self.effective_color, self.registry_match_sql, ""))
        linkage = cur.fetchone()

        self.assertEqual(sum(row["flagged_count"] for row in sector_rows), 2)
        self.assertEqual(
            {row["category"]: row["flagged_count"] for row in sector_rows},
            {"Food": 1, "Retail": 1},
        )
        self.assertEqual(linkage["total_flagged_records"], 5)
        self.assertEqual(linkage["linked_records"], 2)
        self.assertEqual(linkage["unlinked_records"], 2)
        self.assertEqual(linkage["ambiguous_records"], 1)


if __name__ == "__main__":
    unittest.main()
