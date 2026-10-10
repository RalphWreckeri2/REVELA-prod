import unittest
from datetime import date, datetime
from unittest.mock import MagicMock, patch

from api.inspections import service as inspection_service
from api.registry import routes as registry_routes


class WorkflowViewTests(unittest.TestCase):
    def setUp(self):
        self.cursor = MagicMock()
        self.connection = MagicMock()
        self.connection.cursor.return_value = self.cursor
        self.mysql = MagicMock(connection=self.connection)

    def test_calendar_uses_persisted_dates_and_preserves_event_timestamp(self):
        event_time = datetime(2026, 10, 10, 9, 15, 30)
        self.cursor.fetchall.side_effect = [
            [{"activityDate": date(2026, 10, 10), "activityCount": 1}],
            [{
                "eventID": 7,
                "eventType": "submitted",
                "eventTimestamp": event_time,
                "targetLogID": 44,
            }],
        ]

        with patch.object(inspection_service, "mysql", self.mysql):
            result, error = inspection_service.get_inspection_calendar(
                date(2026, 10, 1),
                date(2026, 11, 1),
                date(2026, 10, 10),
                user_id="12",
            )

        self.assertIsNone(error)
        self.assertEqual(result["days"], [{"date": "2026-10-10", "count": 1}])
        self.assertEqual(
            result["activities"][0]["eventTimestamp"],
            "2026-10-10 09:15:30",
        )
        calls = self.cursor.execute.call_args_list
        self.assertIn("DATE(e.eventTimestamp)", calls[0].args[0])
        self.assertIn("e.eventTimestamp", calls[1].args[0])
        self.assertIn("e.assignedToUserID = %s", calls[1].args[0])
        self.assertEqual(calls[1].args[1], (
            date(2026, 10, 1),
            date(2026, 11, 1),
            date(2026, 10, 10),
            "12",
            "12",
        ))

    def test_workflow_summary_counts_unique_businesses_and_uses_latest_event(self):
        self.cursor.fetchone.return_value = {"total": 2}
        self.cursor.fetchall.return_value = [
            {"businessID": "B-2", "eventID": 9},
            {"businessID": "B-1", "eventID": 5},
        ]

        with patch.object(registry_routes, "mysql", self.mysql):
            total, records = registry_routes._workflow_summary_rows("snapped")

        self.assertEqual(total, 2)
        self.assertEqual(len(records), 2)
        queries = [call.args[0] for call in self.cursor.execute.call_args_list]
        self.assertIn("COUNT(DISTINCT e.businessID)", queries[0])
        self.assertIn("MAX(eventID)", queries[1])
        self.assertEqual(
            [call.args[1] for call in self.cursor.execute.call_args_list],
            [("snapped",), ("snapped", "snapped")],
        )

    def test_reverification_summary_counts_unique_businesses_and_latest_attempt(self):
        self.cursor.fetchone.return_value = {"total": 2}
        self.cursor.fetchall.return_value = [
            {"businessID": "B-2", "eventAt": datetime(2026, 10, 10, 9)},
            {"businessID": "B-1", "eventAt": datetime(2026, 10, 9, 9)},
        ]

        with (
            patch.object(registry_routes, "mysql", self.mysql),
            patch("api.registry.reverify._ensure_history_table"),
        ):
            total, records = registry_routes._reverification_summary()

        self.assertEqual(total, 2)
        self.assertEqual(len(records), 2)
        queries = [call.args[0] for call in self.cursor.execute.call_args_list]
        self.assertIn("COUNT(DISTINCT businessID)", queries[0])
        self.assertIn("MAX(id)", queries[1])
        self.assertIn("GROUP BY businessID", queries[1])

    def test_evidence_access_is_scoped_to_owner_unless_current_admin(self):
        self.cursor.fetchone.return_value = (1,)

        with patch.object(inspection_service, "mysql", self.mysql):
            self.assertTrue(
                inspection_service.user_can_access_inspection_evidence(
                    "a" * 32 + ".jpg", "12"
                )
            )
            self.assertTrue(
                inspection_service.user_can_access_inspection_evidence(
                    "a" * 32 + ".jpg", "12", is_admin=True
                )
            )

        calls = self.cursor.execute.call_args_list
        self.assertIn("AND userID = %s", calls[0].args[0])
        self.assertEqual(calls[0].args[1], (f"%{'a' * 32}.jpg%", 12))
        self.assertNotIn("userID = %s", calls[1].args[0])


if __name__ == "__main__":
    unittest.main()
