from api.registry.places_resolver import list_review_queue, decide_review
from api.inspections import service as inspection_service
from api.flags.service import get_flags, update_flag_color
import os
import sys
import unittest
from flask import Flask
from unittest.mock import MagicMock, patch
from api.registry import routes as registry_routes
from api.registry.colors import _effective_flag_color_sql, reset_ladder_column_cache
from api.registry.locks import reset_lock_column_cache


def _count_query(cursor):
    """get_flags now issues an information_schema probe before its own queries.

    Pick the count query by content so the tests do not depend on how many
    queries ran before it.
    """
    for call in cursor.execute.call_args_list:
        sql = call[0][0]
        if "AS total" in sql:
            return sql, call[0][1] if len(call[0]) > 1 else []
    raise AssertionError("get_flags never ran its count query")

sys.path.insert(0, os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..")))


class ReviewQueueAndStatusExposureTests(unittest.TestCase):

    def setUp(self):
        schema_check = patch("api.registry.reverify._ensure_history_table")
        schema_check.start()
        self.addCleanup(schema_check.stop)

    @patch("api.registry.places_resolver.mysql")
    def test_address_reapproval_rejects_missing_or_invalid_choice_even_with_candidate_id(
        self, mock_mysql
    ):
        cursor = MagicMock()
        row = {
            "businessID": "BIZ-REQUIRE-CHOICE",
            "barangayID": 1,
            "businessName": "Choice Store",
            "businessAddress": "Updated address",
            "latitude": 13.962,
            "longitude": 121.112,
            "coordSource": "manual",
            "matchStatus": "review",
            "resolveKey": None,
        }
        mock_mysql.connection.cursor.return_value = cursor

        for choice in (None, "keep-whatever"):
            with self.subTest(choice=choice):
                cursor.fetchone.side_effect = [row, None, None]
                ok, error = decide_review(
                    "BIZ-REQUIRE-CHOICE",
                    approve=True,
                    location_choice=choice,
                    candidate_history_id=999,
                )
                self.assertFalse(ok)
                self.assertIn("explicit location choice", error)
        self.assertFalse(any(
            "UPDATE official_registry" in call.args[0]
            for call in cursor.execute.call_args_list
        ))
        mock_mysql.connection.commit.assert_not_called()

    def test_decision_http_route_rejects_missing_and_invalid_choice(self):
        app = Flask(__name__)
        route = registry_routes.review_location_decision.__wrapped__
        for payload in (
            {"businessID": "BIZ-HTTP", "candidateHistoryID": 88},
            {"businessID": "BIZ-HTTP", "locationChoice": "other"},
        ):
            with self.subTest(payload=payload):
                with app.test_request_context(
                    "/api/registry/review/decision", method="POST", json=payload
                ):
                    response = route()
                self.assertEqual(response[1], 400)

    @patch("api.registry.routes._review_actor_id", return_value=None)
    @patch("api.registry.routes.places_resolver.decide_review")
    def test_legacy_approve_http_route_returns_client_error_for_pending_pin(
        self, decide_review_mock, _actor_id
    ):
        app = Flask(__name__)
        decide_review_mock.return_value = (
            False, "This location re-approval requires an explicit location choice"
        )
        with app.test_request_context(
            "/api/registry/review/accept", method="POST",
            json={"businessID": "BIZ-HTTP-PENDING", "candidateHistoryID": 99},
        ):
            response = registry_routes.review_accept.__wrapped__()

        self.assertEqual(response[1], 400)
        self.assertEqual(response[0].get_json()["error"],
                         decide_review_mock.return_value[1])

    @patch("api.flags.service.mysql")
    def test_expired_registry_flags_are_returned_as_red(self, mock_mysql):
        mock_cursor = MagicMock()
        mock_mysql.connection.cursor.return_value = mock_cursor
        mock_cursor.fetchone.return_value = {"total": 0}
        mock_cursor.fetchall.return_value = []

        result, error = get_flags(color="Red")

        self.assertIsNone(error)
        self.assertEqual(result["data"], [])
        count_sql, count_params = _count_query(mock_cursor)
        # One bind per branch: the pin branch and the registry-only branch.
        self.assertEqual(count_params, ["Red", "Red"])
        self.assertIn("ir.verificationStatus = 'Verified'", count_sql)
        self.assertNotIn(
            "applicationStatus = 'Expired' THEN 'Orange'", count_sql)

    @patch("api.flags.service.mysql")
    def test_orange_filter_selects_explicit_geospatial_flags(self, mock_mysql):
        mock_cursor = MagicMock()
        mock_mysql.connection.cursor.return_value = mock_cursor
        mock_cursor.fetchone.return_value = {"total": 0}
        mock_cursor.fetchall.return_value = []

        result, error = get_flags(color="Orange")

        self.assertIsNone(error)
        self.assertEqual(result["data"], [])
        count_sql, count_params = _count_query(mock_cursor)
        self.assertEqual(count_params, ["Orange", "Orange"])

        # The filter is now the shared expression, so the retired "Orange only
        # when the registry row is Expired" restriction cannot come back.
        self.assertIn("ir.verificationStatus = 'Verified'", count_sql)
        self.assertIn("ir.inspectionResult = 'Orange'", count_sql)
        self.assertNotIn("r_chk.applicationStatus = 'Expired'", count_sql)
        # The same expression renders the rows, so filter and pin cannot drift.
        self.assertIn(_effective_flag_color_sql("g"), count_sql)
        fetch_sql = next(c[0][0] for c in mock_cursor.execute.call_args_list
                         if "ORDER BY detectedDate" in c[0][0])
        self.assertIn(_effective_flag_color_sql("g"), fetch_sql)

    @patch("api.inspections.service.log_inspection_event")
    @patch("api.inspections.service._ensure_gps_columns")
    @patch("api.inspections.service.mysql")
    def test_dispatch_keeps_existing_flag_color(
        self, mock_mysql, _ensure_gps_columns, _log_event
    ):
        mock_cursor = MagicMock()
        mock_mysql.connection.cursor.return_value = mock_cursor
        mock_cursor.fetchone.side_effect = [
            {"logID": 22, "flagColor": "Red"},
            {"userID": 9, "fullName": "Inspector", "userRole": "Inspector"},
            None,
        ]
        mock_cursor.lastrowid = 31

        result, error = inspection_service.assign_inspection(
            log_id=22,
            inspector_user_id=9,
            deadline=None,
            assigned_by=2,
        )

        self.assertIsNone(error)
        self.assertEqual(result["status"], "Assigned")
        self.assertFalse(any(
            "UPDATE geospatial_logs" in call.args[0]
            for call in mock_cursor.execute.call_args_list
        ))

    @patch("api.flags.service.mysql")
    def test_confirmed_orange_is_excluded_from_expired_red_filter(self, mock_mysql):
        mock_cursor = MagicMock()
        mock_mysql.connection.cursor.return_value = mock_cursor
        mock_cursor.fetchone.return_value = {"total": 0}
        mock_cursor.fetchall.return_value = []

        result, error = get_flags(color="Red")

        self.assertIsNone(error)
        self.assertEqual(result["data"], [])
        count_sql, count_params = _count_query(mock_cursor)
        self.assertEqual(count_params, ["Red", "Red"])
        self.assertIn("ir.verificationStatus = 'Verified'", count_sql)
        self.assertIn("ir.inspectionResult = 'Orange'", count_sql)

    @patch("api.flags.service.mysql")
    def test_registry_only_flag_cannot_turn_orange_into_expired(self, mock_mysql):
        mock_cursor = MagicMock()
        mock_mysql.connection.cursor.return_value = mock_cursor

        success, error = update_flag_color(-5, "Orange")

        self.assertFalse(success)
        self.assertIn("verified inspection warning", error)
        mock_cursor.execute.assert_not_called()

    @patch("api.inspections.service.log_inspection_event")
    @patch("api.inspections.service.get_latest_inspection_cycle_id", return_value=None)
    @patch("api.inspections.service._ensure_gps_columns")
    @patch("api.inspections.service.mysql")
    def test_submitted_orange_report_does_not_change_existing_flag(
        self, mock_mysql, _ensure_gps_columns, _cycle_id, _log_event
    ):
        mock_cursor = MagicMock()
        mock_mysql.connection.cursor.return_value = mock_cursor
        # Mirrors tests/test_inspection_submission_idempotency.py:139-145.
        # submit_inspection reads verificationStatus to decide whether the
        # assignment is open (inspections/service.py:605), and re-reads
        # submittedAt/submissionReceivedAt before reading the pin colour
        # (:658), so the first row needs the assignment fields and the
        # side_effect needs one more entry than it used to.
        mock_cursor.fetchone.side_effect = [
            {
                "reportID": 7, "targetID": 22, "userID": 9,
                "irTimestamp": "2026-10-11 12:00:00",
                "verificationStatus": "Assigned", "wasReassigned": 0,
                "submittedAt": None, "submissionReceivedAt": None,
                "inspectionResult": None, "noticeLevel": 0,
                "remarks": None, "photoPath": None,
                "verifiedLatitude": None, "verifiedLongitude": None,
                "verifiedAccuracy": None,
            },
            {"mins": 5},
            {"submittedAt": "2026-10-11 12:05:00",
             "submissionReceivedAt": "2026-10-11 12:05:01"},
            {"flagColor": "Red"},
        ]

        result, error = inspection_service.submit_inspection(
            log_id=22,
            user_id=9,
            inspection_result="Orange",
            notice_level=1,
        )

        self.assertIsNone(error)
        self.assertEqual(result["status"], "Submitted")
        self.assertEqual(result["flagColor"], "Red")
        self.assertTrue(any(
            "verificationStatus  = 'Submitted'" in call.args[0]
            for call in mock_cursor.execute.call_args_list
        ))
        self.assertFalse(any(
            "UPDATE geospatial_logs" in call.args[0]
            for call in mock_cursor.execute.call_args_list
        ))

    @patch("api.inspections.service.log_inspection_event")
    @patch("api.inspections.service.get_latest_inspection_cycle_id", return_value=None)
    @patch("api.inspections.service._ensure_gps_columns")
    @patch("api.inspections.service.mysql")
    def test_report_sent_back_for_redo_is_not_approved_orange(
        self, mock_mysql, _ensure_gps_columns, _cycle_id, _log_event
    ):
        mock_cursor = MagicMock()
        mock_mysql.connection.cursor.return_value = mock_cursor
        mock_cursor.fetchone.side_effect = [
            {"reportID": 8, "targetID": 22, "verificationStatus": "Submitted"},
            {"userID": 9, "fullName": "Inspector", "userRole": "Inspector"},
            {"flagColor": "Red"},
            # Sending a report back spends a single-use Black dispatch grant,
            # so the pin's businessID is read to find the registry row.
            {"businessID": "BIZ-1"},
        ]
        mock_cursor.fetchall.return_value = [("blackDispatchUnlocked",)]

        result, error = inspection_service.reassign_submitted_report(
            report_id=8,
            inspector_user_id=9,
            deadline=None,
            assigned_by=2,
        )

        self.assertIsNone(error)
        self.assertEqual(result["status"], "Reassigned")
        reset_sql = next(
            call.args[0] for call in mock_cursor.execute.call_args_list
            if "UPDATE inspection_reports" in call.args[0]
        )
        self.assertIn("verificationStatus = 'Reassigned'", reset_sql)
        self.assertIn("inspectionResult = NULL", reset_sql)
        self.assertFalse(any(
            "UPDATE geospatial_logs" in call.args[0]
            for call in mock_cursor.execute.call_args_list
        ))

    @patch("api.inspections.service.log_inspection_event")
    @patch("api.inspections.service.get_latest_inspection_cycle_id", return_value=None)
    @patch("api.inspections.service._ensure_gps_columns")
    @patch("api.inspections.service.mysql")
    def test_verified_warning_inspection_sets_explicit_orange_designation(
        self, mock_mysql, _ensure_gps_columns, _cycle_id, _log_event
    ):
        """An unregistered Orange pin still records the warning on the pin.

        The pin in this fixture carries no businessID, so there is no registry
        row and no ladder to advance: the verify writes the pin only, exactly
        as before Phase 2.
        """
        reset_ladder_column_cache()
        self.addCleanup(reset_ladder_column_cache)
        reset_lock_column_cache()
        self.addCleanup(reset_lock_column_cache)

        mock_cursor = MagicMock()
        mock_mysql.connection.cursor.return_value = mock_cursor
        mock_cursor.fetchall.return_value = [("warningLevel",), ("blackLocked",)]
        mock_cursor.fetchone.side_effect = [
            {
                "reportID": 4,
                "targetID": 22,
                "userID": 9,
                "inspectionResult": "Orange",
                "noticeLevel": 1,
                "verificationStatus": "Submitted",
                "verifiedLatitude": None,
                "verifiedLongitude": None,
                "verifiedAccuracy": None,
                "nearestLandmark": None,
                "detectedName": "Warned Shop",
                "barangayID": 1,
            },
            {"flagColor": "Red"},
        ]

        result, error = inspection_service.verify_inspection(
            4, verified_by_user_id=2
        )

        self.assertIsNone(error)
        self.assertEqual(result["newFlagColor"], "Orange")
        geospatial_update = next(
            call for call in mock_cursor.execute.call_args_list
            if "UPDATE geospatial_logs" in call.args[0]
        )
        self.assertEqual(geospatial_update.args[1], ("Orange", 1, 22))
        # No registry row was found, so nothing was written there.
        self.assertFalse(result["registryUpdated"])
        self.assertFalse(any(
            "UPDATE official_registry" in call.args[0]
            for call in mock_cursor.execute.call_args_list
        ))

    @patch("api.flags.service.mysql")
    def test_get_flags_includes_confidence_semantics(self, mock_mysql):
        """get_flags must include matchStatus, coordSource, matchScore, and businessID in returned rows."""
        mock_cursor = MagicMock()
        mock_mysql.connection.cursor.return_value = mock_cursor

        mock_cursor.fetchone.return_value = {"total": 2}
        mock_cursor.fetchall.return_value = [
            {
                "logID": 101,
                "businessID": "BIZ-FLAG-01",
                "detectedName": "Silva Pharmacy",
                "latitude": 13.965,
                "longitude": 121.115,
                "flagColor": "Green",
                "detectedDate": "2026-10-08 12:00:00",
                "matchStatus": "auto",
                "coordSource": "places",
                "matchScore": 0.95
            },
            {
                "logID": -202,
                "businessID": "BIZ-FLAG-02",
                "detectedName": "Jose Bakery",
                "latitude": 13.960,
                "longitude": 121.110,
                "flagColor": "Yellow",
                "detectedDate": "2026-10-08 12:00:00",
                "matchStatus": "review",
                "coordSource": "geocode",
                "matchScore": 0.60
            }
        ]

        res, err = get_flags()
        self.assertIsNone(err)
        self.assertEqual(len(res["data"]), 2)

        row1 = res["data"][0]
        self.assertEqual(row1["businessID"], "BIZ-FLAG-01")
        self.assertEqual(row1["matchStatus"], "auto")
        self.assertEqual(row1["coordSource"], "places")
        self.assertEqual(row1["matchScore"], 0.95)

        row2 = res["data"][1]
        self.assertEqual(row2["businessID"], "BIZ-FLAG-02")
        self.assertEqual(row2["matchStatus"], "review")
        self.assertEqual(row2["coordSource"], "geocode")
        self.assertEqual(row2["matchScore"], 0.60)

    @patch("api.registry.places_resolver.mysql")
    def test_list_review_queue_returns_candidates(self, mock_mysql):
        """list_review_queue must return records with matchStatus='review' including barangayName and mapsUrl."""
        mock_cursor = MagicMock()
        mock_mysql.connection.cursor.return_value = mock_cursor

        mock_cursor.fetchone.return_value = {"c": 1}
        mock_cursor.fetchall.return_value = [
            {
                "businessID": "BIZ-REV-01",
                "barangayID": 1,
                "barangayName": "Barangay I",
                "businessName": "Candidate Store",
                "businessAddress": "Main St",
                "latitude": 13.962,
                "longitude": 121.112,
                "placeID": "place_google_rev",
                "coordSource": "places",
                "matchScore": 0.65,
                "matchStatus": "review"
            }
        ]

        res, err = list_review_queue()
        self.assertIsNone(err)
        self.assertEqual(res["total"], 1)
        self.assertEqual(len(res["data"]), 1)

        item = res["data"][0]
        self.assertEqual(item["businessID"], "BIZ-REV-01")
        self.assertEqual(item["barangayName"], "Barangay I")
        self.assertEqual(item["matchStatus"], "review")
        self.assertEqual(item["matchScore"], 0.65)
        self.assertIn("place_google_rev", item["mapsUrl"])

    @patch("api.registry.places_resolver.mysql")
    def test_review_accept_locks_pin(self, mock_mysql):
        """Accepting a review candidate must set matchStatus='approved' and coordSource='manual'."""
        mock_cursor = MagicMock()
        mock_mysql.connection.cursor.return_value = mock_cursor

        mock_cursor.fetchone.return_value = {
            "barangayID": 1,
            "businessName": "Candidate Store",
            "businessAddress": "Current address",
            "latitude": 13.962,
            "longitude": 121.112,
            "placeID": "place_google_rev"
        }

        ok, err = decide_review("BIZ-REV-01", approve=True)
        self.assertTrue(ok)
        self.assertIsNone(err)

        update_calls = [
            c for c in mock_cursor.execute.call_args_list
            if "matchStatus='approved'" in c[0][0]
        ]
        self.assertEqual(len(update_calls), 1)
        sql = update_calls[0][0][0]
        self.assertIn("coordSource='manual'", sql)
        self.assertIn("resolveKey=%s", sql)
        self.assertEqual(update_calls[0][0][1][-1], "BIZ-REV-01")

    @patch("api.registry.places_resolver._update_pin")
    @patch("api.registry.places_resolver.mysql")
    def test_imported_location_choice_requires_current_candidate_and_audits_move(
        self, mock_mysql, update_pin
    ):
        cursor = MagicMock()
        cursor.fetchone.side_effect = [
            {
                "businessID": "BIZ-IMPORT-CHOICE",
                "barangayID": 1,
                "businessName": "Candidate Store",
                "businessAddress": "Updated address",
                "latitude": 13.962,
                "longitude": 121.112,
                "placeID": "old_place",
                "coordSource": "manual",
                "matchStatus": "review",
                "resolveKey": None,
            },
            {"addressReviewID": 51},
            {
                "id": 51,
                "newLat": 13.965,
                "newLng": 121.115,
                "placeID": None,
                "score": None,
                "candidateSource": "csv",
                "newCoordSource": "csv",
                "oldLat": 13.962,
                "oldLng": 121.112,
                "oldCoordSource": "manual",
                "oldPlaceID": "old_place",
                "oldPlaceIDKind": "poi",
                "oldMatchScore": 0.95,
                "oldMatchStatus": "approved",
                "oldAddress": "Old address",
                "newAddress": "Updated address",
                "oldBarangayID": 1,
                "newBarangayID": 1,
            },
        ]
        cursor.lastrowid = 52
        mock_mysql.connection.cursor.return_value = cursor
        with patch("api.registry.places_resolver._is_within_municipal_bounds", return_value=True):
            ok, error = decide_review(
                "BIZ-IMPORT-CHOICE", True, location_choice="imported",
                candidate_history_id=51, actor_user_id=9,
            )

        self.assertTrue(ok)
        self.assertIsNone(error)
        pin_update = next(
            call for call in cursor.execute.call_args_list
            if "SET latitude=%s, longitude=%s, placeID=%s" in call.args[0]
        )
        self.assertEqual(pin_update.args[1][:2], (13.965, 121.115))
        self.assertEqual(pin_update.args[1][-3], "BIZ-IMPORT-CHOICE")
        self.assertEqual(pin_update.args[1][-2:],
                         ("Updated address", 1))
        history_inserts = [
            call for call in cursor.execute.call_args_list
            if "INSERT INTO registry_pin_history" in call.args[0]
        ]
        self.assertEqual(len(history_inserts), 1)
        self.assertIn(13.962, history_inserts[0].args[1])
        update_pin.assert_called_once()

    @patch("api.registry.places_resolver.mysql")
    def test_stale_imported_candidate_id_is_rejected_without_registry_change(
        self, mock_mysql
    ):
        cursor = MagicMock()
        cursor.fetchone.side_effect = [
            {
                "businessID": "BIZ-STALE-CANDIDATE",
                "barangayID": 1,
                "businessName": "Candidate Store",
                "businessAddress": "Updated address",
                "latitude": 13.962,
                "longitude": 121.112,
                "coordSource": "manual",
                "matchStatus": "review",
                "resolveKey": None,
            },
            {"addressReviewID": 60},
            None,
        ]
        mock_mysql.connection.cursor.return_value = cursor
        ok, error = decide_review(
            "BIZ-STALE-CANDIDATE", True, location_choice="imported",
            candidate_history_id=59,
        )

        self.assertFalse(ok)
        self.assertIn("stale or unavailable", error)
        self.assertFalse(any(
            "UPDATE official_registry" in call.args[0]
            for call in cursor.execute.call_args_list
        ))
        mock_mysql.connection.commit.assert_not_called()

    @patch("api.registry.reverify.record_location_history",
           side_effect=RuntimeError("synthetic audit insert failure"))
    @patch("api.registry.places_resolver._is_within_municipal_bounds", return_value=True)
    @patch("api.registry.places_resolver.mysql")
    def test_imported_location_approval_rolls_back_when_audit_insert_fails(
        self, mock_mysql, _within_bounds, _record_history
    ):
        cursor = MagicMock()
        cursor.rowcount = 1
        cursor.fetchone.side_effect = [
            {
                "businessID": "BIZ-AUDIT-ROLLBACK",
                "barangayID": 1,
                "businessName": "Candidate Store",
                "businessAddress": "Updated address",
                "latitude": 13.962,
                "longitude": 121.112,
                "coordSource": "manual",
                "matchStatus": "review",
                "resolveKey": None,
            },
            {"addressReviewID": 61},
            {
                "id": 61,
                "newLat": 13.965,
                "newLng": 121.115,
                "candidateSource": "csv",
                "newCoordSource": "csv",
                "oldLat": 13.962,
                "oldLng": 121.112,
                "oldCoordSource": "manual",
                "oldBarangayID": 1,
                "newBarangayID": 1,
            },
        ]
        mock_mysql.connection.cursor.return_value = cursor

        ok, error = decide_review(
            "BIZ-AUDIT-ROLLBACK", True, location_choice="imported",
            candidate_history_id=61,
        )

        self.assertFalse(ok)
        self.assertIn("synthetic audit insert failure", error)
        self.assertTrue(any(
            "UPDATE official_registry" in call.args[0]
            for call in cursor.execute.call_args_list
        ))
        mock_mysql.connection.rollback.assert_called_once()
        mock_mysql.connection.commit.assert_not_called()

    @patch("api.registry.places_resolver.mysql")
    def test_review_reject_records_rejected_place_and_detaches_coords(self, mock_mysql):
        """Rejecting a candidate must insert into registry_rejected_places, set rejected status, and clear coords."""
        mock_cursor = MagicMock()
        mock_mysql.connection.cursor.return_value = mock_cursor

        mock_cursor.fetchone.return_value = {
            "barangayID": 1,
            "businessName": "Candidate Store",
            "latitude": 13.962,
            "longitude": 121.112,
            "placeID": "bad_place_candidate"
        }

        ok, err = decide_review("BIZ-REV-01", approve=False)
        self.assertTrue(ok)
        self.assertIsNone(err)

        # Verify insert into registry_rejected_places
        rej_calls = [
            c for c in mock_cursor.execute.call_args_list
            if "INSERT IGNORE INTO registry_rejected_places" in c[0][0]
        ]
        self.assertEqual(len(rej_calls), 1)
        self.assertEqual(rej_calls[0][0][1],
                         ("BIZ-REV-01", "bad_place_candidate"))

        # Verify detachment of coordinates on official_registry
        detach_calls = [
            c for c in mock_cursor.execute.call_args_list
            if "UPDATE official_registry SET matchStatus='rejected'" in c[0][0]
        ]
        self.assertEqual(len(detach_calls), 1)
        detach_sql = detach_calls[0][0][0]
        self.assertIn("latitude=NULL", detach_sql)
        self.assertIn("longitude=NULL", detach_sql)
        self.assertIn("placeID=NULL", detach_sql)

    @patch("api.registry.places_resolver.mysql")
    def test_review_reject_keeps_retained_pin_for_reapproval(self, mock_mysql):
        """Rejecting a retained pin during reapproval must preserve the known location history."""
        mock_cursor = MagicMock()
        mock_mysql.connection.cursor.return_value = mock_cursor

        mock_cursor.fetchone.side_effect = [
            {
                "businessID": "BIZ-REV-04",
                "barangayID": 1,
                "businessName": "Candidate Store",
                "businessAddress": "Updated address",
                "latitude": 13.962,
                "longitude": 121.112,
                "placeID": "existing_place",
                "coordSource": "manual",
                "matchStatus": "review",
                "resolveKey": None,
            },
            {"addressReviewID": 51},
            {"id": 52, "placeID": "imported_candidate"},
        ]

        ok, err = decide_review(
            "BIZ-REV-04", approve=False, candidate_history_id=52,
            actor_user_id=9,
        )
        self.assertTrue(ok)
        self.assertIsNone(err)

        reject_calls = [
            c for c in mock_cursor.execute.call_args_list
            if "UPDATE registry_pin_history" in c[0][0]
            and "candidate_rejected" in c[0][0]
        ]
        self.assertEqual(len(reject_calls), 1)
        self.assertFalse(any(
            "UPDATE official_registry" in call.args[0]
            for call in mock_cursor.execute.call_args_list
        ))
        self.assertEqual(
            next(call for call in mock_cursor.execute.call_args_list
                 if "INSERT IGNORE INTO registry_rejected_places" in call.args[0]
                 ).args[1],
            ("BIZ-REV-04", "imported_candidate"),
        )

    @patch("api.registry.places_resolver._update_pin")
    @patch("api.registry.places_resolver.mysql")
    def test_previous_pin_choice_does_not_consume_stale_reverify_proposal(
        self, mock_mysql, update_pin
    ):
        cursor = MagicMock()
        cursor.fetchone.side_effect = [
            {
                "businessID": "BIZ-REV-STALE",
                "barangayID": 1,
                "businessName": "Candidate Store",
                "businessAddress": "Updated address",
                "latitude": 13.962,
                "longitude": 121.112,
                "placeID": "retained_place",
                "coordSource": "manual",
                "matchStatus": "review",
            },
            {"addressReviewID": 91},
            None,
        ]
        mock_mysql.connection.cursor.return_value = cursor

        ok, error = decide_review(
            "BIZ-REV-STALE",
            approve=True,
            location_choice="previous",
            actor_user_id=9,
        )

        self.assertTrue(ok)
        self.assertIsNone(error)
        approval = next(
            call for call in cursor.execute.call_args_list
            if "matchStatus='approved'" in call.args[0]
        )
        self.assertIn("resolveKey", approval.args[0])
        self.assertNotIn("latitude=%s", approval.args[0])
        self.assertNotIn("longitude=%s", approval.args[0])
        self.assertNotIn("old-address-proposal", str(approval.args[1]))
        update_pin.assert_not_called()

    @patch("api.registry.places_resolver._update_pin")
    @patch("api.registry.places_resolver.mysql")
    def test_rejected_candidate_and_previous_choice_are_separate_audit_rows(
        self, mock_mysql, update_pin
    ):
        retained = {
            "businessID": "BIZ-DECISION-HISTORY",
            "barangayID": 1,
            "businessName": "History Store",
            "businessAddress": "Updated address",
            "latitude": 13.962,
            "longitude": 121.112,
            "placeID": "retained_place",
            "coordSource": "manual",
            "matchStatus": "review",
            "resolveKey": None,
        }
        reject_cursor = MagicMock()
        reject_cursor.fetchone.side_effect = [
            retained,
            {"addressReviewID": 76},
            {"id": 77, "placeID": "rejected_imported_place"},
        ]
        previous_cursor = MagicMock()
        previous_cursor.fetchone.side_effect = [retained, None, None]
        previous_cursor.rowcount = 1
        mock_mysql.connection.cursor.side_effect = [
            reject_cursor, previous_cursor]

        rejected, reject_error = decide_review(
            "BIZ-DECISION-HISTORY", approve=False,
            candidate_history_id=77, actor_user_id=9,
        )
        kept, keep_error = decide_review(
            "BIZ-DECISION-HISTORY", approve=True,
            location_choice="previous", actor_user_id=9,
        )

        self.assertTrue(rejected)
        self.assertIsNone(reject_error)
        self.assertTrue(kept)
        self.assertIsNone(keep_error)
        rejected_row_update = next(
            call for call in reject_cursor.execute.call_args_list
            if "UPDATE registry_pin_history" in call.args[0]
        )
        self.assertIn("candidate_rejected", rejected_row_update.args[0])
        self.assertEqual(rejected_row_update.args[1][1], 77)
        previous_decision = next(
            call for call in previous_cursor.execute.call_args_list
            if "INSERT INTO registry_pin_history" in call.args[0]
        )
        self.assertEqual(previous_decision.args[1][1], "location_kept")
        self.assertEqual(previous_decision.args[1][0], "BIZ-DECISION-HISTORY")
        self.assertFalse(any(
            "UPDATE registry_pin_history" in call.args[0]
            for call in previous_cursor.execute.call_args_list
        ))
        self.assertFalse(any(
            "UPDATE official_registry SET latitude=%s" in call.args[0]
            for call in previous_cursor.execute.call_args_list
        ))
        update_pin.assert_not_called()

    @patch("api.flags.service._get_barangay_id_by_coords", return_value=1)
    @patch("api.flags.service.mysql")
    def test_manual_flag_move_records_coordinate_history(
        self, mock_mysql, _barangay_for_coords
    ):
        from api.flags.service import update_flag_location

        cursor = MagicMock()
        cursor.fetchone.return_value = {
            "businessID": "BIZ-MANUAL-AUDIT",
            "businessName": "Audit Store",
            "businessAddress": "Current address",
            "barangayID": 1,
            "latitude": 13.962,
            "longitude": 121.112,
            "coordSource": "manual",
            "matchStatus": "review",
            "resolveKey": None,
        }
        mock_mysql.connection.cursor.return_value = cursor

        ok, error = update_flag_location(
            -123, 13.97, 121.12, actor_user_id=9
        )

        self.assertTrue(ok)
        self.assertIsNone(error)
        history_insert = next(
            call for call in cursor.execute.call_args_list
            if "INSERT INTO registry_pin_history" in call.args[0]
        )
        self.assertIn("oldLat", history_insert.args[0])
        self.assertIn("newLat", history_insert.args[0])
        self.assertIn("decisionAt", history_insert.args[0])
        self.assertIn(13.962, history_insert.args[1])
        self.assertIn(13.97, history_insert.args[1])
        self.assertEqual(history_insert.args[1][-1], "manual_corrected")
        mock_mysql.connection.commit.assert_called_once()

    @patch("api.flags.service._get_barangay_id_by_coords", return_value=1)
    @patch("api.flags.service.mysql")
    def test_manual_flag_move_rolls_back_history_when_pin_update_fails(
        self, mock_mysql, _barangay_for_coords
    ):
        from api.flags.service import update_flag_location

        cursor = MagicMock()
        cursor.fetchone.return_value = {
            "businessID": "BIZ-MANUAL-ROLLBACK",
            "businessName": "Rollback Store",
            "businessAddress": "Current address",
            "barangayID": 1,
            "latitude": 13.962,
            "longitude": 121.112,
            "coordSource": "manual",
            "matchStatus": "review",
            "resolveKey": None,
        }

        def fail_pin_update(sql, _params=None):
            if "UPDATE official_registry" in sql:
                raise RuntimeError("synthetic pin update failure")

        cursor.execute.side_effect = fail_pin_update
        mock_mysql.connection.cursor.return_value = cursor

        ok, error = update_flag_location(-124, 13.97, 121.12, actor_user_id=9)

        self.assertFalse(ok)
        self.assertIn("synthetic pin update failure", error)
        self.assertTrue(any(
            "INSERT INTO registry_pin_history" in call.args[0]
            for call in cursor.execute.call_args_list
        ))
        mock_mysql.connection.rollback.assert_called_once()
        mock_mysql.connection.commit.assert_not_called()

    @patch("api.registry.places_resolver._update_pin")
    @patch("api.registry.places_resolver.mysql")
    def test_approving_reverify_proposal_moves_pin_only_after_admin_approval(
        self, mock_mysql, update_pin
    ):
        cursor = MagicMock()
        cursor.fetchone.side_effect = [
            {
                "barangayID": 1,
                "businessName": "Candidate Store",
                "latitude": 13.962,
                "longitude": 121.112,
                "placeID": "existing_place",
            },
            None,
            {
                "reviewHistoryID": 42,
                "newLat": 13.965,
                "newLng": 121.115,
                "placeID": "proposed_place",
                "score": 0.68,
            },
        ]
        cursor.rowcount = 1
        mock_mysql.connection.cursor.return_value = cursor

        ok, error = decide_review("BIZ-REV-02", approve=True)

        self.assertTrue(ok)
        self.assertIsNone(error)
        proposal_update = next(
            call for call in cursor.execute.call_args_list
            if "SET latitude=%s, longitude=%s, placeID=%s" in call.args[0]
        )
        self.assertEqual(
            proposal_update.args[1][:4],
            (13.965, 121.115, "proposed_place", 0.68),
        )
        self.assertEqual(len(proposal_update.args[1][4]), 40)
        self.assertEqual(proposal_update.args[1][5], "BIZ-REV-02")
        update_pin.assert_called_once_with(
            cursor, 1, "Candidate Store", 13.962, 121.112, 13.965, 121.115,
            business_id="BIZ-REV-02",
        )
        self.assertTrue(any(
            "review_approved" in call.args[0]
            for call in cursor.execute.call_args_list
        ))

    @patch("api.registry.places_resolver._update_pin")
    @patch("api.registry.places_resolver.mysql")
    def test_rejecting_reverify_proposal_keeps_original_pin(self, mock_mysql, update_pin):
        cursor = MagicMock()
        cursor.fetchone.side_effect = [
            {
                "barangayID": 1,
                "businessName": "Candidate Store",
                "latitude": 13.962,
                "longitude": 121.112,
                "placeID": "existing_place",
            },
            None,
            {
                "reviewHistoryID": 43,
                "newLat": 13.965,
                "newLng": 121.115,
                "placeID": "proposed_place",
                "score": 0.68,
            },
        ]
        mock_mysql.connection.cursor.return_value = cursor

        ok, error = decide_review("BIZ-REV-03", approve=False)

        self.assertTrue(ok)
        self.assertIsNone(error)
        update_pin.assert_not_called()
        self.assertNotIn(
            "latitude=NULL",
            "\n".join(call.args[0] for call in cursor.execute.call_args_list),
        )
        rejected = next(
            call for call in cursor.execute.call_args_list
            if "INSERT IGNORE INTO registry_rejected_places" in call.args[0]
        )
        self.assertEqual(rejected.args[1], ("BIZ-REV-03", "proposed_place"))


if __name__ == "__main__":
    unittest.main()
