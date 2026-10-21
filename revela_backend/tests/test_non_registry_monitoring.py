"""Non-registry monitoring uses real shared SQL on synthetic SQLite memory."""
import os
import sys
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(__file__))
from registry_sqlite import RegistryDB
from api.analytics.non_registry import build_non_registry_monitoring, non_registry_monitoring_sql
from api.flags.compliance import origin_source_sql
from api.flags import compliance_report
from api.models.geospatial import reset_source_column_cache


CHECKED_AT = datetime(2026, 10, 21, 6, 0, tzinfo=timezone.utc)


class NonRegistryMonitoringTests(unittest.TestCase):
    def setUp(self):
        reset_source_column_cache()
        self.addCleanup(reset_source_column_cache)
        self.db = RegistryDB()
        self.addCleanup(self.db.close)
        self.db.db.execute("INSERT INTO barangays VALUES (2, 'Barangay II')")

    def pin(self, number, color, *, source="detection", linked=False, barangay=1, name=None):
        business_id = f"REG-{number}" if linked else None
        if linked:
            self.db.db.execute("""INSERT INTO official_registry
                (businessID, businessName, barangayID, applicationStatus)
                VALUES (?, ?, ?, 'Active')""", (business_id, name or f"Pin {number}", barangay))
        self.db.db.execute("""INSERT INTO geospatial_logs
            (logID, businessID, barangayID, detectedName, flagColor, source, detectedDate, nearestLandmark)
            VALUES (?, ?, ?, ?, ?, ?, '2026-10-20 12:00:00', 'Fixture address')""",
                           (number, business_id, barangay, name or f"Pin {number}", color, source))

    def inspection(self, pin_id, status, result=None, *, report_id=None, timestamp="2026-10-20 13:00:00", target_type="geospatial_log"):
        report_id = report_id or pin_id
        self.db.db.execute("""INSERT INTO inspection_reports
            (reportID, targetID, targetType, userID, verificationStatus, inspectionResult, irTimestamp)
            VALUES (?, ?, ?, 9, ?, ?, ?)""", (report_id, pin_id, target_type, status, result, timestamp))

    def verify_green(self, pin_id, *, report_id=None, event_id=None):
        report_id = report_id or pin_id
        self.inspection(pin_id, "Verified", "Green", report_id=report_id)
        self.db.db.execute("""INSERT INTO inspection_lifecycle_events
            (eventID, reportID, targetLogID, eventType, actorUserID, inspectionResult, eventTimestamp)
            VALUES (?, ?, ?, 'verified', 2, 'Green', '2026-10-20 14:00:00')""",
                           (event_id or pin_id, report_id, pin_id))

    def snapshot(self, filters=None, *, ladder=True):
        filters = filters or {}
        cur = self.db.cursor()
        sql, params = non_registry_monitoring_sql(filters, ladder=ladder, source_sql=origin_source_sql("g", cur))
        cur.execute(sql, params)
        return build_non_registry_monitoring(cur.fetchall(), filters, generated_at=CHECKED_AT)

    def test_snapshot_covers_all_colors_and_excludes_real_registry_links(self):
        self.pin(1, "Red")
        self.pin(2, "Yellow", source="manual")
        self.inspection(2, "Assigned")
        self.pin(3, "Green")
        self.verify_green(3)
        self.pin(4, "Green", source="manual", barangay=2)
        self.verify_green(4)
        self.pin(5, "Green")  # Stored Green alone is not verification evidence.
        self.pin(6, "Orange", barangay=2)
        self.pin(7, "Black", barangay=2)
        self.pin(8, "Purple", barangay=2)
        self.pin(9, "Red", linked=True)
        snapshot = self.snapshot()
        self.assertEqual(snapshot["summary"], {"total": 8, "needs_verification": 2, "under_inspection": 1, "verified_green": 2})
        self.assertEqual(len(snapshot["records"]), 8)
        self.assertNotIn(9, [row["logID"] for row in snapshot["records"]])
        self.assertTrue(all(row["registryLinked"] is False for row in snapshot["records"]))
        self.assertEqual(sum(sum(row[color] for color in ("Green", "Red", "Yellow", "Orange", "Black", "Purple", "Unknown")) for row in snapshot["by_barangay"]), 8)
        self.assertEqual(snapshot["by_barangay"][0]["Green"], 2)
        self.assertEqual(snapshot["by_barangay"][1]["Green"], 1)
        self.assertEqual(snapshot["generated_at"], "2026-10-21T06:00:00Z")

    def test_membership_is_actual_link_not_name_color_or_source(self):
        self.pin(1, "Red", name="Matching registry name")
        self.db.db.execute("""INSERT INTO official_registry
            (businessID, businessName, barangayID, applicationStatus)
            VALUES ('IMPORTED', 'Matching registry name', 1, 'Active')""")
        self.pin(2, "Green", source="registry")
        self.pin(3, "Yellow", source="manual", linked=True)
        snapshot = self.snapshot()
        self.assertEqual([row["logID"] for row in snapshot["records"]], [2, 1])
        named = next(row for row in snapshot["records"] if row["logID"] == 1)
        self.assertEqual(named["flagColor"], "Green")
        self.assertFalse(named["registryLinked"])
        self.assertFalse(named["verifiedGreen"])

    def test_latest_inspection_is_single_row_and_matches_map_workflow(self):
        self.pin(1, "Yellow")
        self.inspection(1, "Verified", "Green", report_id=10)
        self.inspection(1, "Submitted", "Green", report_id=11)
        self.inspection(1, "Verified", "Green", report_id=12, target_type="other")
        snapshot = self.snapshot()
        self.assertEqual(snapshot["summary"]["total"], 1)
        self.assertEqual(snapshot["summary"]["under_inspection"], 1)
        self.assertEqual(snapshot["records"][0]["verificationStatus"], "Submitted")
        self.assertFalse(snapshot["records"][0]["verifiedGreen"])

    def test_green_history_or_later_enforcement_cannot_invent_current_compliance(self):
        for pin_id in range(1, 5):
            self.pin(pin_id, "Green")
            self.verify_green(pin_id)
        self.db.db.execute("UPDATE geospatial_logs SET flagColor='Orange' WHERE logID=1")
        self.db.db.execute("""INSERT INTO inspection_lifecycle_events
            (reportID, targetLogID, eventType, actorUserID, inspectionResult, eventTimestamp)
            VALUES (2, 2, 'reassigned', 2, NULL, '2026-10-20 15:00:00')""")
        self.db.db.execute("""INSERT INTO enforcement_state (subjectType, subjectID, warningLevel)
            VALUES ('geospatial_log', '3', 1)""")
        self.db.db.execute("""INSERT INTO enforcement_events (subjectType, subjectID, eventType, createdAt)
            VALUES ('geospatial_log', '4', 'warning_issued', '2026-10-20 15:00:00')""")
        snapshot = self.snapshot()
        self.assertEqual(snapshot["summary"]["verified_green"], 0)
        self.assertTrue(all(not row["verifiedGreen"] and row["verifiedGreenAt"] is None for row in snapshot["records"]))

    def test_verified_card_preserves_existing_export_origin_scope(self):
        for pin_id, source in enumerate(("detection", "manual", "registry", "unknown"), 1):
            self.pin(pin_id, "Green", source=source)
            self.verify_green(pin_id)
        snapshot = self.snapshot()
        self.assertEqual(snapshot["summary"]["total"], 4)
        self.assertEqual(snapshot["summary"]["verified_green"], 2)
        self.assertEqual({row["logID"] for row in snapshot["records"] if row["verifiedGreen"]}, {1, 2})

    def test_verified_card_matches_the_actual_export_filtered_to_not_in_registry(self):
        for pin_id, source in enumerate(("detection", "manual", "unknown"), 1):
            self.pin(pin_id, "Green", source=source)
            self.verify_green(pin_id)
        self.pin(4, "Green", linked=True)
        self.verify_green(4)
        snapshot = self.snapshot()
        with patch.object(compliance_report, "mysql", self.db), \
                patch.object(compliance_report, "ladder_columns_available", return_value=True):
            exported = compliance_report.get_inspection_verified_compliant()
        exported_ids = {row["detectionReference"] for row in exported["data"] if not row["registryLinked"]}
        monitored_ids = {row["logID"] for row in snapshot["records"] if row["verifiedGreen"]}
        self.assertEqual(monitored_ids, exported_ids)
        self.assertEqual(snapshot["summary"]["verified_green"], len(exported_ids))

    def test_filters_use_same_cohort_for_cards_chart_and_full_list(self):
        self.pin(1, "Red")
        self.pin(2, "Yellow", barangay=2)
        self.inspection(2, "Assigned")
        filtered = self.snapshot({"barangay_ids": [2], "flag_color": "Yellow", "verification_status": "Assigned"})
        self.assertEqual(filtered["summary"]["total"], 1)
        self.assertEqual(filtered["records"][0]["logID"], 2)
        self.assertEqual(filtered["by_barangay"][0]["Yellow"], 1)
        self.assertEqual(self.snapshot({"detected_from": "2027-01-01"})["summary"]["total"], 0)
        self.assertEqual(self.snapshot({"inspection_to": "2026-10-19"})["summary"]["total"], 0)
        self.assertEqual(self.snapshot({"inspection_to": "2026-10-20"})["summary"]["total"], 1)

    def test_registry_only_filters_are_ignored_and_disclosed(self):
        self.pin(1, "Red")
        filters = {"application_status": "Active", "line_of_business": "Retail", "business_size": "Large", "renewal_from": "2099-01-01"}
        filtered = self.snapshot(filters)
        self.assertEqual(filtered["summary"], self.snapshot()["summary"])
        self.assertEqual(set(filtered["ignored_filters"]), set(filters))

    def test_linking_a_pin_removes_it_from_all_non_registry_outputs(self):
        self.pin(1, "Red")
        self.assertEqual(self.snapshot()["summary"]["total"], 1)
        self.db.db.execute("""INSERT INTO official_registry
            (businessID, businessName, barangayID, applicationStatus) VALUES ('LINKED', 'Pin 1', 1, 'Active')""")
        self.db.db.execute("UPDATE geospatial_logs SET businessID='LINKED' WHERE logID=1")
        snapshot = self.snapshot()
        self.assertEqual(snapshot["summary"], {"total": 0, "needs_verification": 0, "under_inspection": 0, "verified_green": 0})
        self.assertEqual(snapshot["records"], [])
        self.assertEqual(snapshot["by_barangay"], [])

    def test_complete_snapshot_is_not_truncated_to_api_or_ui_page_sizes(self):
        self.db.db.executemany("""INSERT INTO geospatial_logs (detectedName, barangayID, flagColor, source)
            VALUES (?, 1, 'Red', 'detection')""", [(f"Fixture {index}",) for index in range(1005)])
        snapshot = self.snapshot()
        self.assertEqual(snapshot["summary"]["total"], 1005)
        self.assertEqual(len(snapshot["records"]), 1005)
        self.assertEqual(snapshot["by_barangay"][0]["Red"], 1005)

    def test_missing_source_column_and_pre_ladder_schema_do_not_invent_evidence(self):
        self.pin(1, "Green")
        self.verify_green(1)
        self.db.db.execute("ALTER TABLE geospatial_logs DROP COLUMN source")
        reset_source_column_cache()
        snapshot = self.snapshot(ladder=False)
        self.assertEqual(snapshot["records"][0]["originSource"], "unknown")
        self.assertEqual(snapshot["summary"]["verified_green"], 0)

    def test_snapshot_reads_do_not_write_or_modify_registry_and_inspection_state(self):
        self.pin(1, "Red")
        before = self.db.db.total_changes
        self.snapshot()
        self.assertEqual(self.db.db.total_changes, before)
        self.assertTrue(all(sql.lstrip().startswith("SELECT") for sql, _ in self.db.calls))

    def test_unknown_colors_still_count_as_pins_in_the_chart(self):
        self.pin(1, None)
        snapshot = self.snapshot()
        self.assertEqual(snapshot["summary"]["total"], 1)
        self.assertEqual(snapshot["by_barangay"][0]["Unknown"], 1)
        self.assertEqual(snapshot["records"][0]["flagColor"], "Unknown")


if __name__ == "__main__":
    unittest.main()
