import unittest
from datetime import datetime
from flask import Flask
from unittest.mock import MagicMock, patch

from api.inspections import service as inspection_service
from api.inspections import routes as inspection_routes


class InspectionSubmissionIdempotencyTests(unittest.TestCase):
    def setUp(self):
        self.connection = MagicMock()
        self.cursor = MagicMock()
        self.connection.cursor.return_value = self.cursor
        self.report = {
            "reportID": 100,
            "targetID": 20,
            "userID": 9,
            "irTimestamp": "2026-10-12 10:00:00",
            "submittedAt": "2026-10-14 02:46:00",
            "submissionReceivedAt": "2026-10-14 02:47:00",
            "verificationStatus": "Submitted",
            "inspectionResult": "Yellow",
            "noticeLevel": 1,
            "remarks": "Please follow up",
            "photoPath": '["/evidence/photo.jpg"]',
            "verifiedLatitude": 14.6,
            "verifiedLongitude": 121.1,
            "verifiedAccuracy": 8.0,
        }

    @patch(
        "api.inspections.service.get_latest_inspection_cycle_id",
        return_value=11,
    )
    @patch("api.inspections.service._ensure_gps_columns")
    @patch("api.inspections.service.mysql")
    def test_equivalent_retry_is_confirmed_without_second_event_or_update(
        self, mock_mysql, _ensure_columns, _cycle
    ):
        mock_mysql.connection = self.connection
        self.cursor.fetchone.return_value = dict(
            self.report,
            wasReassigned=1,
        )

        result, error = inspection_service.submit_inspection(
            log_id=20,
            user_id=9,
            report_id=100,
            inspection_result="Yellow",
            notice_level=1,
            verified_lat=14.6,
            verified_lng=121.1,
            verified_accuracy=8,
            notes="Please follow up",
            photo_url='["/evidence/photo.jpg"]',
            assignment_cycle_id=11,
        )

        self.assertIsNone(error)
        self.assertEqual(result["reportID"], 100)
        self.assertTrue(result["alreadyAccepted"])
        self.assertEqual(result["status"], "Submitted")
        self.assertEqual(result["submittedAt"], self.report["submittedAt"])
        self.assertEqual(
            result["submissionReceivedAt"],
            self.report["submissionReceivedAt"],
        )
        self.connection.commit.assert_called_once()
        self.connection.rollback.assert_not_called()
        self.assertEqual(self.cursor.execute.call_count, 1)
        query, params = self.cursor.execute.call_args.args
        self.assertIn("FOR UPDATE", query)
        self.assertEqual(params, (100,))

    @patch(
        "api.inspections.service.get_latest_inspection_cycle_id",
        return_value=11,
    )
    @patch("api.inspections.service._ensure_gps_columns")
    @patch("api.inspections.service.mysql")
    def test_conflicting_retry_is_rejected_without_overwriting_report(
        self, mock_mysql, _ensure_columns, _cycle
    ):
        mock_mysql.connection = self.connection
        self.cursor.fetchone.return_value = dict(self.report)

        result, error = inspection_service.submit_inspection(
            log_id=20,
            user_id=9,
            report_id=100,
            inspection_result="Red",
            notice_level=1,
            verified_lat=14.6,
            verified_lng=121.1,
            verified_accuracy=8,
            notes="Different result",
            photo_url='["/evidence/photo.jpg"]',
        )

        self.assertIsNone(result)
        self.assertIsInstance(
            error, inspection_service.InspectionSubmissionConflict
        )
        self.assertIn("different data", str(error))
        self.connection.rollback.assert_called_once()
        self.connection.commit.assert_not_called()
        self.assertEqual(self.cursor.execute.call_count, 1)

    @patch(
        "api.inspections.service.get_latest_inspection_cycle_id",
        return_value=12,
    )
    @patch("api.inspections.service._ensure_gps_columns")
    @patch("api.inspections.service.mysql")
    def test_old_assignment_cycle_cannot_submit_into_reassigned_report(
        self, mock_mysql, _ensure_columns, _cycle
    ):
        mock_mysql.connection = self.connection
        open_report = dict(
            self.report,
            verificationStatus="Reassigned",
            inspectionResult=None,
            noticeLevel=0,
            remarks=None,
            photoPath=None,
            verifiedLatitude=None,
            verifiedLongitude=None,
            verifiedAccuracy=None,
        )
        self.cursor.fetchone.return_value = open_report

        result, error = inspection_service.submit_inspection(
            log_id=20,
            user_id=9,
            report_id=100,
            assignment_cycle_id=11,
            inspection_result="Yellow",
        )

        self.assertIsNone(result)
        self.assertIsInstance(
            error, inspection_service.InspectionSubmissionConflict
        )
        self.assertIn("reassigned", str(error))
        self.connection.rollback.assert_called_once()
        self.connection.commit.assert_not_called()
        self.assertEqual(self.cursor.execute.call_count, 1)

    @patch(
        "api.inspections.service.get_latest_inspection_cycle_id",
        return_value=12,
    )
    @patch("api.inspections.service._ensure_gps_columns")
    @patch("api.inspections.service.mysql")
    def test_missing_cycle_is_not_accepted_as_current_reassignment(
        self, mock_mysql, _ensure_columns, _cycle
    ):
        mock_mysql.connection = self.connection
        open_report = dict(
            self.report,
            wasReassigned=1,
            verificationStatus="Reassigned",
            inspectionResult=None,
            noticeLevel=0,
            remarks=None,
            photoPath=None,
            verifiedLatitude=None,
            verifiedLongitude=None,
            verifiedAccuracy=None,
        )
        self.cursor.fetchone.return_value = open_report

        result, error = inspection_service.submit_inspection(
            log_id=20,
            user_id=9,
            report_id=100,
            inspection_result="Yellow",
        )

        self.assertIsNone(result)
        self.assertIsInstance(
            error, inspection_service.InspectionSubmissionConflict
        )
        self.assertIn("cycle is required", str(error))
        self.connection.rollback.assert_called_once()
        self.connection.commit.assert_not_called()
        self.assertEqual(self.cursor.execute.call_count, 1)

    @patch(
        "api.inspections.service.get_latest_inspection_cycle_id",
        return_value=12,
    )
    @patch("api.inspections.service._ensure_gps_columns")
    @patch("api.inspections.service.mysql")
    def test_missing_cycle_cannot_claim_idempotency_after_reassignment(
        self, mock_mysql, _ensure_columns, _cycle
    ):
        mock_mysql.connection = self.connection
        reassigned_report = dict(self.report, wasReassigned=1)
        self.cursor.fetchone.return_value = reassigned_report

        result, error = inspection_service.submit_inspection(
            log_id=20,
            user_id=9,
            report_id=100,
            inspection_result="Yellow",
            notice_level=1,
            verified_lat=14.6,
            verified_lng=121.1,
            verified_accuracy=8,
            notes="Please follow up",
            photo_url='["/evidence/photo.jpg"]',
        )

        self.assertIsNone(result)
        self.assertIsInstance(
            error, inspection_service.InspectionSubmissionConflict
        )
        self.assertIn("cycle is required", str(error))
        self.connection.rollback.assert_called_once()
        self.connection.commit.assert_not_called()
        self.assertEqual(self.cursor.execute.call_count, 1)

    @patch("api.inspections.service.log_inspection_event")
    @patch(
        "api.inspections.service.get_latest_inspection_cycle_id",
        return_value=11,
    )
    @patch("api.inspections.service._ensure_gps_columns")
    @patch("api.inspections.service.mysql")
    def test_distinct_open_report_identities_remain_submittable(
        self, mock_mysql, _ensure_columns, _cycle, _log_event
    ):
        mock_mysql.connection = self.connection
        for report_id in (100, 101):
            with self.subTest(report_id=report_id):
                self.cursor.reset_mock()
                self.connection.reset_mock()
                self.connection.cursor.return_value = self.cursor
                self.cursor.fetchone.side_effect = [
                    {
                        "reportID": report_id,
                        "targetID": 20,
                        "userID": 9,
                        "irTimestamp": "2026-10-12 10:00:00",
                        "verificationStatus": "Assigned",
                        "inspectionResult": None,
                        "noticeLevel": 0,
                        "remarks": None,
                        "photoPath": None,
                        "verifiedLatitude": None,
                        "verifiedLongitude": None,
                        "verifiedAccuracy": None,
                    },
                    {"mins": 5},
                    {
                        "submittedAt": datetime(2026, 10, 14, 2, 46),
                        "submissionReceivedAt": datetime(2026, 10, 14, 2, 47),
                    },
                    {"flagColor": "Yellow"},
                ]

                result, error = inspection_service.submit_inspection(
                    log_id=20,
                    user_id=9,
                    report_id=report_id,
                    inspection_result="Yellow",
                    submitted_at=datetime(2026, 10, 14, 2, 46),
                )

                self.assertIsNone(error)
                self.assertEqual(result["reportID"], report_id)
                self.connection.commit.assert_called_once()
                update_query, update_params = next(
                    call.args
                    for call in self.cursor.execute.call_args_list
                    if "UPDATE inspection_reports" in call.args[0]
                    and "submittedAt" in call.args[0]
                )
                self.assertIn(
                    "submissionReceivedAt = UTC_TIMESTAMP(6)",
                    update_query,
                )
                self.assertEqual(update_params[-2], datetime(2026, 10, 14, 2, 46))
                self.assertEqual(
                    result["submittedAt"],
                    "2026-10-14 02:46:00",
                )
                self.assertEqual(
                    result["submissionReceivedAt"],
                    "2026-10-14 02:47:00",
                )
                first_query, first_params = self.cursor.execute.call_args_list[0].args
                self.assertIn("FOR UPDATE", first_query)
                self.assertEqual(first_params, (report_id,))

    @patch("api.inspections.service.mysql")
    def test_history_is_ordered_by_submission_time_not_dispatch_time(
        self, mock_mysql
    ):
        mock_mysql.connection.cursor.return_value = self.cursor
        self.cursor.fetchall.return_value = []

        result, error = inspection_service.get_inspector_reports_history(9)

        self.assertIsNone(error)
        self.assertEqual(result["data"], [])
        query = self.cursor.execute.call_args.args[0]
        self.assertIn(
            "ORDER BY ir.submittedAt IS NULL, ir.submittedAt DESC",
            query,
        )
        self.assertIn("AS dispatchedAt", query)

    @patch("api.inspections.routes.submit_inspection")
    @patch("api.inspections.routes.get_jwt_identity", return_value=9)
    def test_route_returns_409_for_predictable_assignment_conflict(
        self, _identity, mock_submit
    ):
        mock_submit.return_value = (
            None,
            inspection_service.InspectionSubmissionConflict(
                "This report was already submitted with different data."
            ),
        )
        app = Flask(__name__)
        with app.test_request_context(
            "/api/inspections/submit",
            method="POST",
            json={
                "reportID": 100,
                "assignmentCycleID": 11,
                "logID": 20,
                "inspectionResult": "Red",
            },
        ):
            response, status = inspection_routes.submit.__wrapped__()

        self.assertEqual(status, 409)
        self.assertEqual(response.get_json()["code"], "inspection_submission_conflict")
        mock_submit.assert_called_once()
        self.assertEqual(
            mock_submit.call_args.kwargs["assignment_cycle_id"],
            11,
        )

    @patch("api.inspections.routes.submit_inspection")
    @patch("api.inspections.routes.get_jwt_identity", return_value=9)
    def test_route_normalizes_offset_submission_timestamp_to_utc(
        self, _identity, mock_submit
    ):
        mock_submit.return_value = (
            {
                "reportID": 100,
                "inspectionResult": "Yellow",
                "status": "Submitted",
                "alreadyAccepted": True,
            },
            None,
        )
        with Flask(__name__).test_request_context(
            "/api/inspections/submit",
            method="POST",
            json={
                "reportID": 100,
                "logID": 20,
                "inspectionResult": "Yellow",
                "submittedAt": "2026-10-14T10:46:00+08:00",
            },
        ):
            _response, status = inspection_routes.submit.__wrapped__()

        self.assertEqual(status, 200)
        self.assertEqual(
            mock_submit.call_args.kwargs["submitted_at"],
            datetime(2026, 10, 14, 2, 46),
        )

    @patch("api.inspections.routes.submit_inspection")
    @patch("api.inspections.routes.get_jwt_identity", return_value=9)
    def test_route_rejects_timezone_less_submission_timestamp(
        self, _identity, mock_submit
    ):
        with Flask(__name__).test_request_context(
            "/api/inspections/submit",
            method="POST",
            json={
                "reportID": 100,
                "logID": 20,
                "inspectionResult": "Yellow",
                "submittedAt": "2026-10-14 10:46:00",
            },
        ):
            _response, status = inspection_routes.submit.__wrapped__()

        self.assertEqual(status, 400)
        mock_submit.assert_not_called()

    @patch("api.inspections.routes.submit_inspection")
    @patch("api.inspections.routes.get_jwt_identity", return_value=9)
    def test_route_returns_success_for_already_accepted_retry(
        self, _identity, mock_submit
    ):
        mock_submit.return_value = (
            {
                "reportID": 100,
                "inspectionResult": "Yellow",
                "status": "Submitted",
                "alreadyAccepted": True,
            },
            None,
        )
        app = Flask(__name__)
        with app.test_request_context(
            "/api/inspections/submit",
            method="POST",
            json={
                "reportID": 100,
                "logID": 20,
                "inspectionResult": "Yellow",
            },
        ):
            response, status = inspection_routes.submit.__wrapped__()

        self.assertEqual(status, 200)
        self.assertTrue(response.get_json()["alreadyAccepted"])


if __name__ == "__main__":
    unittest.main()
