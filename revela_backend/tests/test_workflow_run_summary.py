import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from flask import Flask

sys.path.insert(0, os.path.dirname(__file__))
from api.registry import routes
from api.registry import reverify
from api.flags import routes as flag_routes


class WorkflowRunSummaryTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)

    def read_run(self, run_id):
        with self.app.test_request_context(
            f"/api/registry/workflow-runs/{run_id}", method="GET"
        ):
            return routes.workflow_run_result.__wrapped__(run_id)

    def test_run_lookup_returns_only_results_for_the_requested_run_id(self):
        first_id = "11111111-1111-4111-8111-111111111111"
        second_id = "22222222-2222-4222-8222-222222222222"
        runs = {
            first_id: {
                "operation": "snap",
                "completed": True,
                "result": {"records": [{"businessID": "SNAP-1"}]},
            },
            second_id: {
                "operation": "reverify",
                "completed": True,
                "result": {"records": [{"businessID": "VERIFY-1"}]},
            },
        }
        with patch(
            "api.registry.audit.get_registry_workflow_run",
            side_effect=lambda run_id: runs[run_id],
        ):
            first_response, first_status = self.read_run(first_id)
            second_response, second_status = self.read_run(second_id)

        self.assertEqual(first_status, 200)
        self.assertEqual(second_status, 200)
        self.assertEqual(first_response.get_json()["result"]["records"], [
            {"businessID": "SNAP-1"},
        ])
        self.assertEqual(second_response.get_json()["result"]["records"], [
            {"businessID": "VERIFY-1"},
        ])

    def test_unavailable_or_invalid_run_results_are_explicit(self):
        run_id = "33333333-3333-4333-8333-333333333333"
        with patch("api.registry.audit.get_registry_workflow_run", return_value=None):
            response, status = self.read_run(run_id)
        self.assertEqual(status, 404)
        self.assertIn("not found", response.get_json()["error"])

        with patch("api.registry.audit.get_registry_workflow_run", return_value={
            "operation": "snap",
            "completed": False,
            "result": None,
        }):
            response, status = self.read_run(run_id)
        self.assertEqual(status, 202)
        self.assertIn("still in progress", response.get_json()["error"])

        response, status = self.read_run("not-a-uuid")
        self.assertEqual(status, 400)
        self.assertIn("Invalid", response.get_json()["error"])

    def test_reverify_result_records_exact_no_match_businesses_and_reasons(self):
        businesses = [
            {
                "businessID": f"NO-MATCH-{index}",
                "barangayID": 1,
                "businessName": f"Business {index}",
                "businessAddress": "Poblacion",
                "lineOfBusiness": "Retail",
                "applicationStatus": "Active",
                "coordSource": "geocode",
                "matchStatus": "auto",
                "latitude": 13.96,
                "longitude": 121.11,
                "placeID": None,
                "placeIDKind": "address",
                "businessType": "Store",
            }
            for index in range(6)
        ]
        connection = MagicMock()
        fake_mysql = SimpleNamespace(connection=connection)
        no_match = (None, None, {"reason": "no_candidate", "best_name": None})
        with (
            patch("app.mysql", fake_mysql),
            patch.object(reverify, "_ensure_history_table"),
            patch.object(reverify, "_load_rows", return_value=businesses),
            patch.object(reverify, "_recent_ids", return_value=set()),
            patch.object(reverify, "_attempted_ids", return_value=set()),
            patch.object(reverify, "_known_google_poi_business_ids", return_value=set()),
            patch.object(reverify, "_log_attempt"),
            patch.object(reverify, "_log_run_summary", return_value={}),
            patch("api.registry.audit.complete_registry_workflow_run") as complete_run,
            patch("api.registry.service._load_barangay_lookup", return_value={"Barangay I": 1}),
            patch("api.registry.places_resolver.reset_run_state"),
            patch("api.registry.places_resolver.resolve_location", return_value=no_match),
            patch("api.notifications.hub.publish_to_admins"),
        ):
            result, error = reverify._run(
                6, run_id="66666666-6666-4666-8666-666666666666"
            )

        self.assertIsNone(error)
        self.assertEqual(result["counts"]["no_match"], 6)
        self.assertEqual(
            result["operation_id"],
            "66666666-6666-4666-8666-666666666666",
        )
        complete_run.assert_called_once_with(result["operation_id"], result)
        self.assertEqual(
            {row["businessID"] for row in result["records"]},
            {row["businessID"] for row in businesses},
        )
        self.assertTrue(all(row["outcome"] == "no_match" for row in result["records"]))
        self.assertTrue(all(row["reason"] == "no_candidate" for row in result["records"]))

    def test_reconcile_response_and_saved_summary_use_the_same_run_records(self):
        run_id = "44444444-4444-4444-8444-444444444444"
        records = [
            {"record_id": "LOG-1", "outcome": "reconciled"},
            {"record_id": "LOG-2", "outcome": "no_match"},
        ]
        cursor = MagicMock()
        cursor.fetchone.side_effect = [{"total": 1}, {"total": 2}]
        connection = MagicMock()
        connection.cursor.return_value = cursor
        fake_mysql = SimpleNamespace(connection=connection)
        with (
            self.app.test_request_context(
                "/api/flags/reconcile",
                method="POST",
                json={"operation_id": run_id},
            ),
            patch.object(flag_routes, "mysql", fake_mysql),
            patch.object(flag_routes, "reconcile_existing_flags", return_value={
                "reconciled_records": 1,
                "records": records,
            }),
            patch("api.registry.audit.start_registry_workflow_run") as start_run,
            patch("api.registry.audit.complete_registry_workflow_run") as complete_run,
        ):
            response, status = flag_routes.reconcile_flags_route.__wrapped__()

        payload = response.get_json()
        self.assertEqual(status, 200)
        self.assertEqual(payload["operation_id"], run_id)
        self.assertEqual(payload["records"], records)
        self.assertEqual(payload["counts"], {
            "reconciled": 1,
            "no_match": 1,
            "failed": 0,
        })
        start_run.assert_called_once_with(run_id, "reconcile")
        complete_run.assert_called_once_with(run_id, {
            "counts": {"reconciled": 1, "no_match": 1, "failed": 0},
            "records": records,
            "total": 2,
            "message": "1 flag(s) reconciled out of 2 Red flag(s).",
            "operation_id": run_id,
        })


if __name__ == "__main__":
    unittest.main()
