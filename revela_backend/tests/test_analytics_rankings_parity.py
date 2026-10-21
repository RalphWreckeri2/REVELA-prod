"""Parity: the split barangay-ranking aggregate vs the shipped fan-out join.

Executes the real generated SQL on an in-memory SQLite engine through the
existing tests/registry_sqlite.py harness. That harness substitutes only the
MySQL-specific correlated ORDER BY syntax and the DBAPI cursor shape; the CASE
arms and every join/aggregate are the shipped text.

This proves VALUE parity on the fixture. It does not exercise MySQL's planner,
so derived-table materialization and index access stay unproven here.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.path.insert(0, os.path.dirname(__file__))

from registry_sqlite import RegistryDB  # noqa: E402

from api.analytics import routes  # noqa: E402
from api.analytics.filters import (  # noqa: E402
    barangay_b_sql,
    geo_on_extra,
    parse_analytics_filters,
    registry_sql,
)
from api.registry.colors import _effective_flag_color_sql  # noqa: E402

COUNT_KEYS = ("flagged_count", "red_count", "yellow_count", "black_count",
              "total_registered", "unregistered_candidate_count", "dispatchable_red_count",
              "dispatchable_yellow_count", "dispatchable_business_count")
AVG_KEYS = ("avg_lat", "avg_lng")

# Two registry rows in barangay 1 fan out against its two geo rows; barangay 5
# has geo rows but no registry; barangay 4 has a registry row but no geo;
# barangay 3 is empty on both sides; log 6 is not actionable and must be dropped.
_REGISTRY_ROWS = [
    ("B-1", "ACME",  1, "Active",  0, 0, 13.1, 121.1, "2020-01-01", "New"),
    ("B-2", "BETA",  1, "Expired", 2, 0, 13.2, 121.2, "2020-01-01", "Renewal"),
    ("B-3", "GAMMA", 2, "Pending", 0, 1, 13.3, 121.3, "2020-01-01", "New"),
    ("B-4", "DELTA", 4, "Active",  0, 0, 13.4, 121.4, "2020-01-01", "New"),
]


def _seed(db, ladder):
    db.db.executescript("""
        INSERT INTO barangays (barangayID, barangayName) VALUES
            (2, 'Barangay II'), (3, 'Barangay III'),
            (4, 'Barangay IV'), (5, 'Barangay V');
    """)
    if ladder:
        cols = "businessID, businessName, barangayID, applicationStatus, warningLevel, blackLocked, latitude, longitude, lastRenewalDate, registrationType"
        values = _REGISTRY_ROWS
    else:
        cols = "businessID, businessName, barangayID, applicationStatus, latitude, longitude, lastRenewalDate, registrationType"
        values = [(r[0], r[1], r[2], r[3], r[6], r[7], r[8], r[9]) for r in _REGISTRY_ROWS]
    placeholders = ",".join("(" + ",".join("?" * len(v)) + ")" for v in values)
    db.db.execute(
        f"INSERT INTO official_registry ({cols}) VALUES {placeholders}",
        [x for v in values for x in v],
    )
    db.db.executescript("""
        INSERT INTO enforcement_state (subjectType, subjectID, warningLevel, blackLocked) VALUES
            ('business', 'B-1', 0, 0),
            ('business', 'B-2', 2, 0),
            ('business', 'B-3', 0, 1),
            ('business', 'B-4', 0, 0);
        INSERT INTO geospatial_logs
            (logID, businessID, barangayID, detectedName, flagColor, latitude, longitude, placeID, reportedByUserID)
        VALUES
            (1, 'B-1', 1, 'ACME',  'Green',  13.10, 121.10, 'P1', NULL),
            (2, 'B-2', 1, 'BETA',  'Yellow', 13.20, 121.20, NULL, 9),
            (3, 'B-3', 2, 'GAMMA', 'Green',  13.30, 121.30, 'P3', NULL),
            (4, NULL,  5, 'PIN4',  'Red',    13.40, 121.40, NULL, 9),
            (5, NULL,  5, 'PIN5',  'Yellow', 13.50, 121.50, 'P5', NULL),
            (6, NULL,  1, 'PIN6',  'Green',  13.60, 121.60, NULL, NULL);
        INSERT INTO inspection_reports
            (reportID, targetID, targetType, userID, verificationStatus, inspectionResult)
        VALUES (1, 1, 'geospatial_log', 9, 'Verified', 'Orange');
    """)
    db.commit()


def _build(builder, F, ladder):
    eff = _effective_flag_color_sql("g", ladder=ladder)
    geo_on_g, geo_on_g_p = geo_on_extra("g", F, ladder=ladder)
    reg_o, reg_o_p = registry_sql("o", F)
    brgy_b, brgy_b_p = barangay_b_sql(F)
    return builder(eff, geo_on_g, geo_on_g_p, reg_o, reg_o_p, brgy_b, brgy_b_p)


class RankingsParityTests(unittest.TestCase):

    def _parity(self, raw_filters, ladder):
        db = RegistryDB(ladder=ladder)
        self.addCleanup(db.close)
        _seed(db, ladder)
        F = parse_analytics_filters(dict(raw_filters))
        F["registration_type_supported"] = True

        orig_sql, orig_p = _build(routes._barangay_rankings_sql, F, ladder)
        new_sql, new_p = _build(routes._barangay_rankings_sql_split, F, ladder)
        self.assertEqual(orig_p, new_p, "bound params must match positionally")

        orig = sorted(self._run(db, orig_sql, orig_p), key=lambda r: r["barangayID"])
        new = sorted(self._run(db, new_sql, new_p), key=lambda r: r["barangayID"])

        self.assertEqual([r["barangayID"] for r in orig],
                         [r["barangayID"] for r in new])
        self.assertEqual([r["barangayName"] for r in orig],
                         [r["barangayName"] for r in new])
        for a, b in zip(orig, new):
            for key in COUNT_KEYS:
                self.assertEqual(a[key], b[key],
                                 f"{key} differs in barangay {a['barangayID']}")
            for key in AVG_KEYS:
                if a[key] is None or b[key] is None:
                    self.assertEqual(a[key], b[key],
                                     f"{key} NULL-ness differs in barangay {a['barangayID']}")
                else:
                    self.assertAlmostEqual(a[key], b[key], places=9)
        return orig, new

    @staticmethod
    def _run(db, sql, params):
        cur = db.cursor()
        cur.execute(sql, params)
        return cur.fetchall()

    def test_no_filters_ladder_true(self):
        orig, _ = self._parity({}, True)
        self.assertEqual({r["barangayID"] for r in orig}, {1, 2, 3, 4, 5})

    def test_no_filters_ladder_false(self):
        self._parity({}, False)

    def test_barangay_filter(self):
        orig, _ = self._parity({"barangay_ids": "1,2"}, True)
        self.assertEqual({r["barangayID"] for r in orig}, {1, 2})

    def test_flag_color_filter_each_colour(self):
        for colour in ("Red", "Yellow", "Black", "Green", "Orange"):
            with self.subTest(colour=colour):
                self._parity({"flag_color": colour}, True)

    def test_application_status_filter(self):
        self._parity({"application_status": "Active"}, True)

    def test_registration_type_filter(self):
        self._parity({"registration_type": "New"}, True)

    def test_combined_filters_ladder_false(self):
        self._parity({"barangay_ids": "1",
                      "flag_color": "Red",
                      "application_status": "Expired"}, False)

    def test_empty_and_single_sided_barangays(self):
        """Barangay 3 empty, 4 registry-only, 5 geo-only must match exactly."""
        orig, _ = self._parity({}, True)
        by_id = {r["barangayID"]: r for r in orig}
        self.assertEqual(by_id[3]["flagged_count"], 0)
        self.assertIsNone(by_id[3]["avg_lat"])
        self.assertEqual(by_id[3]["total_registered"], 0)
        self.assertEqual(by_id[4]["flagged_count"], 0)
        self.assertIsNone(by_id[4]["avg_lat"])
        self.assertEqual(by_id[4]["total_registered"], 1)
        self.assertEqual(by_id[5]["total_registered"], 0)
        self.assertEqual(by_id[5]["avg_lat"], 13.45)

    def test_shipped_form_still_fans_out(self):
        F = parse_analytics_filters({})
        F["registration_type_supported"] = True
        sql, _ = _build(routes._barangay_rankings_sql, F, True)
        self.assertIn("LEFT JOIN geospatial_logs   g ON g.barangayID = b.barangayID", sql)
        self.assertIn("LEFT JOIN official_registry o ON o.barangayID = b.barangayID", sql)
        self.assertIn("GROUP BY b.barangayID, b.barangayName", sql)

    def test_split_form_groups_each_side(self):
        F = parse_analytics_filters({})
        F["registration_type_supported"] = True
        sql, _ = _build(routes._barangay_rankings_sql_split, F, True)
        # Geospatial side: the split is written with an inner derived table that
        # computes eff_color once per actionable geo row (GROUP BY the logID
        # primary key), then the aggregate regroups by barangayID.  This asserts
        # the generated SQL text only; MySQL planner behavior is not tested here.
        self.assertIn("AS eff_color", sql)
        self.assertIn("GROUP BY g.logID", sql)
        self.assertIn("GROUP BY c.barangayID", sql)
        self.assertIn("GROUP BY o.barangayID", sql)
        self.assertIn("COALESCE(ga.flagged_count, 0)", sql)
        self.assertNotIn("LEFT JOIN geospatial_logs   g ON g.barangayID = b.barangayID", sql)

    def test_split_expands_color_case_once_textually(self):
        """The GENERATED SQL carries the effective-colour CASE once in the split
        against four in the shipped form.  'ELSE g.flagColor' closes the CASE
        exactly once per expansion. WLC v2 also uses it in two conditional
        location averages, dispatchable counts and the unregistered-candidate
        count (ten total, including the business-capacity identity predicate).
        This is a TEXT property: it does not measure
        how many times MySQL evaluates the expression, nor prove materialization.
        """
        F = parse_analytics_filters({})
        F["registration_type_supported"] = True
        orig_sql, _ = _build(routes._barangay_rankings_sql, F, True)
        new_sql, _ = _build(routes._barangay_rankings_sql_split, F, True)
        self.assertEqual(orig_sql.count("ELSE g.flagColor"), 10)
        self.assertEqual(new_sql.count("ELSE g.flagColor"), 1)

    def test_gate_defaults_off(self):
        prev = os.environ.pop("REVELA_ANALYTICS_RANKINGS_SPLIT", None)
        try:
            self.assertFalse(routes._rankings_split_enabled())
        finally:
            if prev is not None:
                os.environ["REVELA_ANALYTICS_RANKINGS_SPLIT"] = prev


if __name__ == "__main__":
    unittest.main()
