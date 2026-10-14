import unittest
from datetime import datetime
from decimal import Decimal
from unittest.mock import MagicMock, patch

from flask import Flask

from api.inspections import routes, service


class InspectionSubmissionIdempotencyTests(unittest.TestCase):
    def setUp(self):
        self.mysql = MagicMock()
        self.connection = self.mysql.connection
        self.cursor = self.connection.cursor.return_value
        self.report = {
            "reportID": 100, "targetID": 20, "userID": 9,
            "irTimestamp": "2026-10-12 10:00:00",
            "submittedAt": "2026-10-14 02:46:00",
            "submissionReceivedAt": "2026-10-14 02:47:00",
            "verificationStatus": "Submitted", "wasReassigned": 0,
            "inspectionResult": "Yellow", "noticeLevel": 1,
            "remarks": "Please follow up", "photoPath": '["/evidence/photo.jpg"]',
            "verifiedLatitude": 14.6, "verifiedLongitude": 121.1,
            "verifiedAccuracy": Decimal("12.35"),
        }
        self.cursor.fetchone.return_value = self.report
        for name, mock in (
            ("mysql", self.mysql),
            ("_ensure_gps_columns", MagicMock()),
            ("get_latest_inspection_cycle_id", MagicMock(return_value=11)),
            ("log_inspection_event", MagicMock()),
        ):
            patcher = patch.object(service, name, mock)
            patcher.start()
            self.addCleanup(patcher.stop)
        publisher = patch("api.notifications.hub.publish_to_admins")
        self.publish = publisher.start()
        self.addCleanup(publisher.stop)

    def submit(self, **changes):
        payload = dict(
            log_id=20, user_id=9, report_id=100, assignment_cycle_id=11,
            inspection_result="Yellow", notice_level=1, verified_lat=14.6,
            verified_lng=121.1, verified_accuracy=12.345,
            notes="Please follow up", photo_url='["/evidence/photo.jpg"]',
        )
        payload.update(changes)
        return service.submit_inspection(**payload)

    def test_equivalent_retry_returns_original_timestamps_without_second_event(self):
        self.report["wasReassigned"] = 1
        result, error = self.submit(submitted_at=datetime(2026, 10, 14, 3))
        self.assertIsNone(error)
        self.assertTrue(result["alreadyAccepted"])
        self.assertEqual(result["submittedAt"], self.report["submittedAt"])
        self.assertEqual(result["submissionReceivedAt"], self.report["submissionReceivedAt"])
        self.assertEqual(self.cursor.execute.call_count, 1)
        self.assertIn("FOR UPDATE", self.cursor.execute.call_args.args[0])
        self.connection.commit.assert_called_once()
        service.log_inspection_event.assert_not_called()
        self.publish.assert_not_called()

    def test_verified_retry_also_preserves_confirmed_unknown_submission_time(self):
        self.report.update(verificationStatus="Verified", submittedAt=None)
        result, error = self.submit()
        self.assertIsNone(error)
        self.assertEqual(result["status"], "Verified")
        self.assertIsNone(result["submittedAt"])
        self.assertTrue(result["alreadyAccepted"])

    def test_accuracy_uses_decimal_half_up_not_float_equality(self):
        for accuracy, expected in ((12.345, True), (12.346, True), (12.344, False),
                                   (12.36, False), (None, False), (float("nan"), False)):
            with self.subTest(accuracy=accuracy):
                self.assertEqual(service._same_submission_payload(
                    self.report, "Yellow", 1, "Please follow up", '["/evidence/photo.jpg"]',
                    14.6, 121.1, accuracy,
                ), expected)

    def test_equivalent_photo_order_and_coordinate_decimal_precision(self):
        self.report.update(
            photoPath='["b", "a"]', verifiedLatitude=Decimal("14.60000000"),
            verifiedLongitude=Decimal("121.10000000"),
        )
        result, error = self.submit(photo_url='["a", "b"]')
        self.assertIsNone(error)
        self.assertTrue(result["alreadyAccepted"])

    def test_changed_retry_is_409_conflict_not_an_overwrite(self):
        result, error = self.submit(inspection_result="Red")
        self.assertIsNone(result)
        self.assertIsInstance(error, service.InspectionSubmissionConflict)
        self.assertIn("different data", str(error))
        self.connection.rollback.assert_called_once()
        self.connection.commit.assert_not_called()
        service.log_inspection_event.assert_not_called()

    def test_owner_and_target_are_fenced_by_report_identity(self):
        for changes in ({"user_id": 10}, {"log_id": 21}):
            with self.subTest(changes=changes):
                result, error = self.submit(**changes)
                self.assertIsNone(result)
                self.assertIsInstance(error, service.InspectionSubmissionConflict)
                self.assertIn("does not belong", str(error))
        self.connection.commit.assert_not_called()

    def test_old_assignment_cycle_cannot_submit_into_reassigned_report(self):
        service.get_latest_inspection_cycle_id.return_value = 12
        self.report.update(verificationStatus="Reassigned", wasReassigned=1)
        result, error = self.submit()
        self.assertIsNone(result)
        self.assertIsInstance(error, service.InspectionSubmissionConflict)
        self.connection.commit.assert_not_called()

    def test_missing_cycle_cannot_submit_or_claim_reassignment_idempotency(self):
        self.report["wasReassigned"] = 1
        for status in ("Reassigned", "Submitted"):
            with self.subTest(status=status):
                self.report["verificationStatus"] = status
                result, error = self.submit(assignment_cycle_id=None)
                self.assertIsNone(result)
                self.assertIn("cycle is required", str(error))
        self.connection.commit.assert_not_called()

    def test_missing_assignment_is_an_expected_conflict(self):
        self.cursor.fetchone.return_value = None
        result, error = self.submit()
        self.assertIsNone(result)
        self.assertIsInstance(error, service.InspectionSubmissionConflict)
        self.connection.rollback.assert_called_once()

    def test_distinct_open_reports_remain_submittable_with_utc_receipt(self):
        for report_id in (100, 101):
            with self.subTest(report_id=report_id):
                self.connection.reset_mock()
                self.cursor.reset_mock()
                service.log_inspection_event.reset_mock()
                self.cursor.fetchone.side_effect = [
                    dict(self.report, reportID=report_id, verificationStatus="Assigned"),
                    {"mins": 5},
                    {"submittedAt": datetime(2026, 10, 14, 2, 46),
                     "submissionReceivedAt": datetime(2026, 10, 14, 2, 47)},
                    {"flagColor": "Yellow"},
                ]
                result, error = self.submit(
                    report_id=report_id, submitted_at=datetime(2026, 10, 14, 2, 46),
                )
                self.assertIsNone(error)
                self.assertEqual(result["reportID"], report_id)
                self.assertEqual(result["status"], "Submitted")
                self.assertEqual(result["submittedAt"], "2026-10-14 02:46:00")
                self.assertEqual(result["submissionReceivedAt"], "2026-10-14 02:47:00")
                query, params = next(
                    call.args for call in self.cursor.execute.call_args_list
                    if "UPDATE inspection_reports" in call.args[0]
                )
                self.assertIn("submissionReceivedAt = UTC_TIMESTAMP(6)", query)
                self.assertEqual(params[-2], datetime(2026, 10, 14, 2, 46))
                self.connection.commit.assert_called_once()
                service.log_inspection_event.assert_called_once()

    def test_tasks_and_history_expose_cycle_and_distinct_timestamp_fields(self):
        self.cursor.fetchall.return_value = [{
            "irTimestamp": datetime(2026, 10, 14, 1),
            "dispatchedAt": datetime(2026, 10, 14, 1),
            "submittedAt": None, "submissionReceivedAt": None,
        }]
        for method in (service.get_inspector_tasks, service.get_inspector_reports_history):
            result, error = method(9)
            self.assertIsNone(error)
            query = self.cursor.execute.call_args.args[0]
            self.assertIn("AS assignmentCycleID", query)
            self.assertIn("AS dispatchedAt", query)
            self.assertEqual(result["data"][0]["dispatchedAt"], "2026-10-14 01:00:00")
        self.assertIn("ORDER BY ir.submittedAt IS NULL, ir.submittedAt DESC", query)

    def test_redispatch_clears_submission_timestamps_without_extra_schema_changes(self):
        self.cursor.fetchone.side_effect = [
            {"logID": 20, "flagColor": "Yellow"},
            {"userID": 9, "fullName": "Test Inspector", "userRole": "Inspector"},
            {"reportID": 100, "verificationStatus": "Verified"},
        ]
        result, error = service.assign_inspection(20, 9, None, 1)
        self.assertIsNone(error)
        self.assertEqual(result["status"], "Reassigned")
        query = next(call.args[0] for call in self.cursor.execute.call_args_list
                     if "UPDATE inspection_reports" in call.args[0])
        self.assertIn("submittedAt = NULL", query)
        self.assertIn("submissionReceivedAt = NULL", query)
        self.assertIn("irTimestamp = UTC_TIMESTAMP(6)", query)


class InspectionSubmissionRouteTests(unittest.TestCase):
    def request(self, body, result=None, error=None):
        with patch.object(routes, "get_jwt_identity", return_value=9), \
                patch.object(routes, "submit_inspection", return_value=(result, error)) as submit, \
                patch.object(routes.threading, "Thread") as thread:
            with Flask(__name__).test_request_context(
                "/api/inspections/submit", method="POST", json=body,
            ):
                response, status = routes.submit.__wrapped__()
        return response.get_json(), status, submit, thread

    def test_offset_timestamp_is_normalized_and_accepted_retry_starts_no_thread(self):
        response, status, submit, thread = self.request({
            "reportID": 100, "assignmentCycleID": 11, "logID": 20,
            "inspectionResult": "Yellow", "submittedAt": "2026-10-14T10:46:00+08:00",
        }, result={"reportID": 100, "status": "Submitted", "alreadyAccepted": True})
        self.assertEqual(status, 200)
        self.assertTrue(response["alreadyAccepted"])
        self.assertEqual(submit.call_args.kwargs["submitted_at"], datetime(2026, 10, 14, 2, 46))
        self.assertEqual(submit.call_args.kwargs["assignment_cycle_id"], 11)
        thread.assert_not_called()

    def test_timezone_less_timestamp_is_400_before_service_access(self):
        response, status, submit, thread = self.request({
            "logID": 20, "inspectionResult": "Yellow", "submittedAt": "2026-10-14 10:46:00",
        })
        self.assertEqual(status, 400)
        self.assertEqual(response["code"], "invalid_submission_timestamp")
        submit.assert_not_called()
        thread.assert_not_called()

    def test_predictable_conflict_has_409_code(self):
        response, status, _, thread = self.request(
            {"logID": 20, "inspectionResult": "Yellow"},
            error=service.InspectionSubmissionConflict("Old assignment"),
        )
        self.assertEqual(status, 409)
        self.assertEqual(response["code"], "inspection_submission_conflict")
        thread.assert_not_called()

    def test_fresh_submission_retains_production_background_notification_path(self):
        response, status, submit, thread = self.request(
            {"logID": 20, "inspectionResult": "Yellow"},
            result={"reportID": 100, "status": "Submitted"},
        )
        self.assertEqual(status, 200)
        self.assertEqual(response["reportID"], 100)
        self.assertIsNone(submit.call_args.kwargs["submitted_at"])
        self.assertIsNone(submit.call_args.kwargs["report_id"])
        thread.assert_called_once()
        thread.return_value.start.assert_called_once()

    def test_invalid_ids_and_non_object_json_fail_before_submit(self):
        base = {"logID": 20, "inspectionResult": "Yellow"}
        for body in (["logID", "inspectionResult"], dict(base, reportID=0),
                     dict(base, assignmentCycleID=-1), dict(base, reportID="bad")):
            _, status, submit, thread = self.request(body)
            self.assertEqual(status, 400)
            submit.assert_not_called()
            thread.assert_not_called()
