import os
import sys
import unittest
import datetime as datetime_module
from io import BytesIO
from unittest.mock import MagicMock, patch

import pandas as pd

sys.path.insert(0, os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..")))

from api.registry import service


class RegistryFlagColorTests(unittest.TestCase):

    def test_registry_statuses_use_approved_flag_colors(self):
        expected = {
            "Active": "Green",
            "Pending": "Yellow",
            "Expired": "Red",
            "Revoked": "Black",
            "Blacklisted": "Black",
            "Closed": "Purple",
        }
        for status, color in expected.items():
            with self.subTest(status=status):
                self.assertEqual(service._status_to_flag_color(status), color)

    def test_blacklisted_import_status_normalizes_to_revoked(self):
        self.assertEqual(service._normalise_status("Blacklisted"), "Revoked")

    def test_expired_registry_sync_seeds_red_flag(self):
        cursor = MagicMock()
        cursor.fetchone.return_value = None

        service._sync_flag_color(
            cursor,
            barangay_id=1,
            business_name="Expired Shop",
            status="Expired",
            lat=13.96,
            lng=121.11,
            business_id="BIZ-EXPIRED",
        )

        inserted_values = cursor.execute.call_args_list[-1].args[1]
        self.assertEqual(inserted_values[5], "Red")

    def test_verified_orange_survives_expired_registry_sync(self):
        cursor = MagicMock()
        cursor.fetchone.return_value = {
            "logID": 17,
            "flagColor": "Red",
            "latitude": 13.96,
            "longitude": 121.11,
            "has_verified_orange": 1,
        }

        service._sync_flag_color(
            cursor,
            barangay_id=1,
            business_name="Warned Shop",
            status="Expired",
            lat=13.96,
            lng=121.11,
            business_id="BIZ-WARNED",
        )

        update_sql, update_values = cursor.execute.call_args_list[-1].args
        self.assertIn("UPDATE geospatial_logs", update_sql)
        self.assertEqual(update_values[0], "Orange")
        self.assertNotIn("UPDATE official_registry", update_sql)

    def test_unapproved_orange_does_not_override_expired_registry_sync(self):
        cursor = MagicMock()
        cursor.fetchone.return_value = {
            "logID": 18,
            "flagColor": "Orange",
            "latitude": 13.96,
            "longitude": 121.11,
            "has_verified_orange": 0,
        }

        service._sync_flag_color(
            cursor,
            barangay_id=1,
            business_name="Unapproved Shop",
            status="Expired",
            lat=13.96,
            lng=121.11,
            business_id="BIZ-UNAPPROVED",
        )

        update_values = cursor.execute.call_args_list[-1].args[1]
        self.assertEqual(update_values[0], "Red")


class PermitExpirationSchedulerTests(unittest.TestCase):

    def test_expiration_scheduler_keeps_startup_and_midnight_jobs(self):
        from app import _start_permit_expiry_scheduler

        scheduler = MagicMock()
        with (
            patch(
                "apscheduler.schedulers.background.BackgroundScheduler",
                return_value=scheduler,
            ),
            patch("apscheduler.triggers.cron.CronTrigger") as cron_trigger,
            patch("atexit.register"),
        ):
            _start_permit_expiry_scheduler(MagicMock())

        jobs = {
            call.kwargs["id"]: call
            for call in scheduler.add_job.call_args_list
        }
        self.assertIn("permit_expiry_daily", jobs)
        self.assertIn("permit_expiry_startup", jobs)
        self.assertTrue(
            any(call.kwargs == {"hour": 0, "minute": 0}
                for call in cron_trigger.call_args_list)
        )
        daily_args = jobs["permit_expiry_daily"].args
        self.assertEqual(daily_args[1], cron_trigger.return_value)
        self.assertEqual(
            jobs["permit_expiry_startup"].args[1],
            "date",
        )
        scheduler.start.assert_called_once()

    def test_jan_1_expiration_is_eligible_once_and_preserves_verified_orange(self):
        simulated_today = {"value": datetime_module.date(2026, 12, 31)}

        class SimulatedDate(datetime_module.date):
            @classmethod
            def today(cls):
                return simulated_today["value"]

        businesses = [
            {"businessID": "B-ORANGE", "businessName": "Orange Shop", "barangayID": 1,
             "lastRenewalDate": datetime_module.date(2026, 1, 1), "applicationStatus": "Active"},
            {"businessID": "B-RED", "businessName": "Regular Shop", "barangayID": 1,
             "lastRenewalDate": datetime_module.date(2026, 1, 1), "applicationStatus": "Active"},
            {"businessID": "B-CURRENT", "businessName": "Current Shop", "barangayID": 1,
             "lastRenewalDate": datetime_module.date(2027, 1, 1), "applicationStatus": "Active"},
            {"businessID": "B-PENDING", "businessName": "Pending Shop", "barangayID": 1,
             "lastRenewalDate": datetime_module.date(2025, 1, 1), "applicationStatus": "Pending"},
            {"businessID": "B-EXPIRED", "businessName": "Expired Shop", "barangayID": 1,
             "lastRenewalDate": datetime_module.date(2025, 1, 1), "applicationStatus": "Expired"},
            {"businessID": "B-CLOSED", "businessName": "Closed Shop", "barangayID": 1,
             "lastRenewalDate": datetime_module.date(2025, 1, 1), "applicationStatus": "Closed"},
            {"businessID": "B-REVOKED", "businessName": "Revoked Shop", "barangayID": 1,
             "lastRenewalDate": datetime_module.date(2025, 1, 1), "applicationStatus": "Revoked"},
        ]
        pins = {
            "Orange Shop": "Orange",
            "Regular Shop": "Green",
            "Current Shop": "Green",
            "Pending Shop": "Yellow",
            "Expired Shop": "Red",
            "Closed Shop": "Purple",
            "Revoked Shop": "Black",
        }
        verified_orange_businesses = {"B-ORANGE"}
        cursor = MagicMock()
        connection = MagicMock()
        connection.cursor.return_value = cursor
        mysql = MagicMock(connection=connection)

        def execute(sql, params=None):
            normalized_sql = " ".join(sql.split())
            if normalized_sql.startswith("SELECT COUNT(*) AS cnt FROM official_registry"):
                year = simulated_today["value"].year
                eligible = [
                    business for business in businesses
                    if business["applicationStatus"] == "Active"
                    and business["lastRenewalDate"].year < year
                ]
                cursor.fetchone.return_value = {"cnt": len(eligible)}
            elif normalized_sql.startswith("UPDATE geospatial_logs"):
                self.assertIn(
                    "YEAR(r.lastRenewalDate) < YEAR(CURDATE()) AND r.applicationStatus = 'Active'",
                    normalized_sql,
                )
                self.assertIn("ir.verificationStatus = 'Verified'", normalized_sql)
                self.assertIn("ir.inspectionResult = 'Orange'", normalized_sql)
                for business in businesses:
                    if (
                        business["applicationStatus"] == "Active"
                        and business["lastRenewalDate"].year < simulated_today["value"].year
                    ):
                        pins[business["businessName"]] = (
                            "Orange"
                            if business["businessID"] in verified_orange_businesses
                            else "Red"
                        )
            elif normalized_sql.startswith("UPDATE official_registry"):
                self.assertIn(
                    "YEAR(lastRenewalDate) < YEAR(CURDATE()) AND applicationStatus = 'Active'",
                    normalized_sql,
                )
                for business in businesses:
                    if (
                        business["applicationStatus"] == "Active"
                        and business["lastRenewalDate"].year < simulated_today["value"].year
                    ):
                        business["applicationStatus"] = "Expired"
            elif normalized_sql.startswith("SELECT userID FROM users"):
                cursor.fetchall.return_value = []
            cursor.execute.return_value = None

        cursor.execute.side_effect = execute
        from api.registry import service
        with (
            patch.object(service, "mysql", mysql),
            patch.object(datetime_module, "date", SimulatedDate),
            patch("api.notifications.hub.publish_to_admins"),
        ):
            # Dec 31, 2026: 2026 renewals are still current-year permits.
            self.assertIsNone(service.check_and_expire_old_permits())
            self.assertEqual(
                [b["applicationStatus"] for b in businesses].count("Expired"), 1
            )
            self.assertEqual(pins["Orange Shop"], "Orange")

            # Jan 1, 2027: only the two prior-year Active records qualify.
            simulated_today["value"] = datetime_module.date(2027, 1, 1)
            result = service.check_and_expire_old_permits()
            self.assertEqual(result["count"], 2)
            self.assertEqual(result["year"], 2027)
            self.assertEqual(pins["Orange Shop"], "Orange")
            self.assertEqual(pins["Regular Shop"], "Red")

            # The same day, a repeat run finds no eligible Active records.
            repeated = service.check_and_expire_old_permits()
            self.assertIsNone(repeated)

        self.assertEqual(businesses[0]["applicationStatus"], "Expired")
        self.assertEqual(businesses[1]["applicationStatus"], "Expired")
        self.assertEqual(businesses[2]["applicationStatus"], "Active")
        self.assertEqual(
            [b["applicationStatus"] for b in businesses[3:]],
            ["Pending", "Expired", "Closed", "Revoked"],
        )
        registry_updates = [
            call for call in cursor.execute.call_args_list
            if call.args and call.args[0].lstrip().startswith("UPDATE official_registry")
        ]
        self.assertEqual(len(registry_updates), 1)


class RegistryImportHardeningTests(unittest.TestCase):

    @staticmethod
    def _fixed_import_date():
        actual_date = datetime_module.date

        class FixedDate(actual_date):
            @classmethod
            def today(cls):
                return actual_date(2026, 6, 15)

        return FixedDate

    def _run_mocked_initial_import(self, status, renewal_date, verified_orange=False):
        cursor = MagicMock()
        cursor.fetchall.return_value = []
        cursor.fetchone.return_value = {
            "logID": 7,
            "has_verified_orange": int(verified_orange),
        }
        cursor.rowcount = 1
        mysql = MagicMock()
        mysql.connection.cursor.return_value = cursor
        frame = pd.DataFrame([{
            "Business ID": "BIZ-INITIAL",
            "businessName": "Sample Business",
            "businessType": "Retail",
            "lineOfBusiness": "Pharmacy",
            "businessAddress": "1 Main Street",
            "barangay": "Barangay I",
            "applicationStatus": status,
            "lastRenewalDate": renewal_date,
            "businessSize": "Small",
            "registrationType": "Renewal",
            "latitude": "13.9667",
            "longitude": "121.1167",
        }])
        usage = {
            "text_search": {"day": 0, "month": 0},
            "details": {"day": 0, "month": 0},
            "geocoding": {"day": 0, "month": 0},
        }
        with (
            patch.object(service, "mysql", mysql),
            patch.object(service, "date", self._fixed_import_date()),
            patch.object(service.pd, "read_csv", return_value=frame),
            patch.object(service, "_load_barangay_lookup", return_value={"barangay i": 1}),
            patch.object(service, "_resolve_barangay_id", return_value=1),
            patch.object(service, "_coordinate_pair_within_municipality", return_value=True),
            patch.object(service, "is_cancelled", return_value=False),
            patch.object(service.places_resolver, "reset_run_state"),
            patch.object(service.places_resolver, "record_coord_meta"),
            patch.object(service.places_resolver, "get_places_call_usage", return_value=usage),
            patch.object(service, "insert_green_flag") as insert_flag,
            patch("api.notifications.hub.publish_to_admins"),
        ):
            summary, error = service.upload_registry(BytesIO(b"mocked csv"), ".csv")
        insert_call = next(
            call for call in cursor.execute.call_args_list
            if "INSERT IGNORE INTO official_registry" in call.args[0]
        )
        flag_update = next(
            (
                call for call in cursor.execute.call_args_list
                if "UPDATE geospatial_logs" in call.args[0]
            ),
            None,
        )
        flag_color = (
            flag_update.args[1][0]
            if flag_update
            else insert_flag.call_args.kwargs["color"]
        )
        return summary, error, insert_call, flag_color, flag_update

    def test_annual_expiration_eligibility_matches_scheduled_rule(self):
        cases = (
            ("Active", "2025-08-15", True),
            ("Active", "2026-02-10", False),
            ("Active", "2027-02-10", False),
            ("Active", None, False),
            ("Active", "not a date", False),
            ("Pending", "2025-08-15", False),
            ("Expired", "2025-08-15", False),
            ("Closed", "2025-08-15", False),
            ("Revoked", "2025-08-15", False),
        )
        for status, renewal_date, expected in cases:
            with self.subTest(status=status, renewal_date=renewal_date):
                self.assertEqual(
                    service._annual_expiration_eligible(
                        status, renewal_date, current_year=2026
                    ),
                    expected,
                )

    def test_initial_import_derives_expired_and_preserves_other_statuses(self):
        cases = (
            ("Active", "2025-08-15", "Expired", "Red"),
            ("Active", "2026-02-10", "Active", "Green"),
            ("Active", "2027-02-10", "Active", "Green"),
            ("Active", None, "Active", "Green"),
            ("Active", "not a date", "Active", "Green"),
            ("Pending", "2025-08-15", "Pending", "Yellow"),
            ("Closed", "2025-08-15", "Closed", "Purple"),
            ("Revoked", "2025-08-15", "Revoked", "Black"),
        )
        for status, renewal_date, expected_status, expected_flag in cases:
            with self.subTest(status=status, renewal_date=renewal_date):
                summary, error, insert_call, flag_color, _ = (
                    self._run_mocked_initial_import(status, renewal_date)
                )
                self.assertIsNone(error)
                self.assertEqual(summary["inserted"], 1)
                self.assertEqual(insert_call.args[1][8], expected_status)
                self.assertEqual(insert_call.args[1][9], service._parse_renewal_date(renewal_date))
                self.assertEqual(flag_color, expected_flag)

    def test_initial_import_verified_orange_survives_immediate_expiration(self):
        summary, error, insert_call, flag_color, flag_update = self._run_mocked_initial_import(
            "Active", "2025-08-15", verified_orange=True
        )

        self.assertIsNone(error)
        self.assertEqual(insert_call.args[1][8], "Expired")
        self.assertEqual(flag_color, "Orange")
        self.assertIn("UPDATE geospatial_logs", flag_update.args[0])
        self.assertEqual(summary["inserted"], 1)

    @staticmethod
    def _existing_sync_record(index):
        return {
            "businessID": f"BIZ-{index:02d}",
            "barangayID": 1,
            "businessName": f"SAMPLE BUSINESS {index}",
            "businessType": "RETAIL",
            "lineOfBusiness": "PHARMACY",
            "businessAddress": f"{index} MAIN STREET",
            "applicationStatus": "Active",
            "lastRenewalDate": pd.Timestamp("2026-01-01"),
            "businessSize": "SMALL",
            "registrationType": "RENEWAL",
            "latitude": 13.9667,
            "longitude": 121.1167,
            "coordSource": "places",
            "matchStatus": "auto",
            "resolveKey": "same-location-key",
        }

    @staticmethod
    def _sync_frame_record(index):
        return {
            "Business ID": f"BIZ-{index:02d}",
            "businessName": f"Sample Business {index}",
            "businessType": "Retail",
            "lineOfBusiness": "Pharmacy",
            "businessAddress": f"{index} Main Street",
            "barangay": "Barangay I",
            "applicationStatus": "Active",
            "lastRenewalDate": "2026-01-01",
            "businessSize": "Small",
            "registrationType": "Renewal",
        }

    def _run_mocked_sync(self, frame, existing_rows, resolve_result=None):
        cursor = MagicMock()
        cursor.fetchone.side_effect = list(existing_rows)
        cursor.rowcount = 1
        mysql = MagicMock()
        mysql.connection.cursor.return_value = cursor
        compute_resolve_key = service.places_resolver.compute_resolve_key
        for existing in existing_rows:
            if existing.get("resolveKey") == "same-location-key":
                existing["resolveKey"] = compute_resolve_key(
                    existing.get("businessName"),
                    existing.get("businessAddress"),
                    existing.get("barangayID"),
                )
        usage = {
            "text_search": {"day": 0, "month": 0},
            "details": {"day": 0, "month": 0},
            "geocoding": {"day": 0, "month": 0},
        }
        resolver = patch.object(
            service,
            "_resolve_location",
            return_value=resolve_result or (
                None, None, {"reason": "no_text_results"}
            ),
        )
        with (
            patch.object(service, "mysql", mysql),
            patch.object(service, "date", self._fixed_import_date()),
            patch.object(service.pd, "read_csv", return_value=frame),
            patch.object(service, "_load_barangay_lookup", return_value={"barangay i": 1}),
            patch.object(service, "_resolve_barangay_id", return_value=1),
            patch.object(service, "_coordinate_pair_within_municipality", return_value=True),
            patch.object(service, "is_cancelled", return_value=False),
            patch.object(service.places_resolver, "reset_run_state"),
            patch.object(
                service.places_resolver,
                "compute_resolve_key",
                side_effect=compute_resolve_key,
            ),
            patch.object(service.places_resolver, "get_places_call_usage", return_value=usage),
            patch.object(service.places_resolver, "_update_pin"),
            patch.object(service, "_sync_flag_color"),
            patch.object(service, "insert_green_flag"),
            patch("api.notifications.hub.publish_to_admins"),
            resolver as resolve_location,
        ):
            summary, error = service.sync_registry(BytesIO(b"mocked csv"), ".csv")
        return summary, error, cursor, resolve_location

    def test_sync_ten_rows_counts_only_three_business_changes(self):
        existing = [self._existing_sync_record(index) for index in range(10)]
        frame = pd.DataFrame([self._sync_frame_record(index) for index in range(10)])
        frame.loc[0, "businessName"] = "Changed Business 0"
        frame.loc[1, "lastRenewalDate"] = "2025-01-01"
        frame.loc[2, "applicationStatus"] = "Expired"

        summary, error, cursor, resolve_location = self._run_mocked_sync(frame, existing)

        self.assertIsNone(error)
        self.assertEqual(summary["inserted"], 0)
        self.assertEqual(summary["updated"], 3)
        self.assertEqual(summary["unchanged"], 7)
        self.assertEqual(summary["skipped"], 0)
        update_calls = [
            call for call in cursor.execute.call_args_list
            if "UPDATE official_registry SET" in call.args[0]
        ]
        self.assertEqual(len(update_calls), 3)
        resolve_location.assert_called_once()

    def test_sync_identical_rows_do_not_issue_registry_updates(self):
        existing = [self._existing_sync_record(index) for index in range(10)]
        frame = pd.DataFrame([self._sync_frame_record(index) for index in range(10)])

        summary, error, cursor, resolve_location = self._run_mocked_sync(frame, existing)

        self.assertIsNone(error)
        self.assertEqual(summary["updated"], 0)
        self.assertEqual(summary["unchanged"], 10)
        self.assertEqual(summary["inserted"], 0)
        self.assertEqual(summary["skipped"], 0)
        self.assertFalse(any(
            "UPDATE official_registry SET" in call.args[0]
            for call in cursor.execute.call_args_list
        ))
        resolve_location.assert_not_called()

    def test_sync_equivalent_normalized_values_are_unchanged(self):
        existing = self._existing_sync_record(1)
        existing.update({
            "barangayID": "1",
            "businessName": " SAMPLE   BUSINESS 1 ",
            "businessAddress": "1   main street",
            "applicationStatus": "Active",
            "lastRenewalDate": "2026-01-01 00:00:00",
            "businessSize": 12,
        })
        record = self._sync_frame_record(1)
        record.update({
            "businessName": " sample business 1 ",
            "businessAddress": " 1 MAIN   STREET ",
            "applicationStatus": "license issued",
            "businessSize": "12",
        })

        summary, error, cursor, _ = self._run_mocked_sync(
            pd.DataFrame([record]), [existing]
        )

        self.assertIsNone(error)
        self.assertEqual(summary["updated"], 0)
        self.assertEqual(summary["unchanged"], 1)
        self.assertFalse(any(
            "UPDATE official_registry SET" in call.args[0]
            for call in cursor.execute.call_args_list
        ))

    def test_sync_derives_expired_once_without_location_lookup(self):
        existing = self._existing_sync_record(1)
        existing["lastRenewalDate"] = pd.Timestamp("2026-01-01")
        frame_record = self._sync_frame_record(1)
        frame_record["lastRenewalDate"] = "2025-08-15"

        summary, error, cursor, resolve_location = self._run_mocked_sync(
            pd.DataFrame([frame_record]), [existing]
        )

        self.assertIsNone(error)
        self.assertEqual(summary["updated"], 1)
        self.assertEqual(summary["unchanged"], 0)
        update_calls = [
            call for call in cursor.execute.call_args_list
            if "UPDATE official_registry SET" in call.args[0]
        ]
        self.assertEqual(len(update_calls), 1)
        self.assertEqual(update_calls[0].args[1][7], "Expired")
        self.assertEqual(update_calls[0].args[1][8], "2025-08-15 00:00:00")
        resolve_location.assert_not_called()

    def test_sync_existing_expired_qualifying_row_is_idempotently_unchanged(self):
        existing = self._existing_sync_record(1)
        existing["applicationStatus"] = "Expired"
        existing["lastRenewalDate"] = pd.Timestamp("2025-08-15")
        frame_record = self._sync_frame_record(1)
        frame_record["lastRenewalDate"] = "2025-08-15"

        summary, error, cursor, resolve_location = self._run_mocked_sync(
            pd.DataFrame([frame_record]), [existing]
        )

        self.assertIsNone(error)
        self.assertEqual(summary["updated"], 0)
        self.assertEqual(summary["unchanged"], 1)
        self.assertFalse(any(
            "UPDATE official_registry SET" in call.args[0]
            for call in cursor.execute.call_args_list
        ))
        resolve_location.assert_not_called()

    def test_sync_immediately_expires_old_renewal_date_without_running_scheduler(self):
        existing = self._existing_sync_record(1)
        existing["lastRenewalDate"] = pd.Timestamp("2027-01-01")
        record = self._sync_frame_record(1)
        record["lastRenewalDate"] = "2025-01-01"

        with patch.object(service, "check_and_expire_old_permits") as expiry_job:
            summary, error, cursor, _ = self._run_mocked_sync(
                pd.DataFrame([record]), [existing]
            )

        self.assertIsNone(error)
        self.assertEqual(summary["updated"], 1)
        self.assertEqual(summary["unchanged"], 0)
        registry_update = next(
            call for call in cursor.execute.call_args_list
            if "UPDATE official_registry SET" in call.args[0]
        )
        self.assertEqual(registry_update.args[1][7], "Expired")
        self.assertEqual(registry_update.args[1][8], "2025-01-01 00:00:00")
        expiry_job.assert_not_called()

    def test_sync_keeps_manual_coordinates_and_skips_business_update_when_unchanged(self):
        existing = self._existing_sync_record(1)
        existing.update({"coordSource": "manual", "matchStatus": "approved"})
        record = self._sync_frame_record(1)
        record.update({"latitude": "14.5000", "longitude": "122.5000"})

        summary, error, cursor, resolve_location = self._run_mocked_sync(
            pd.DataFrame([record]), [existing]
        )

        self.assertIsNone(error)
        self.assertEqual(summary["updated"], 0)
        self.assertEqual(summary["unchanged"], 1)
        self.assertFalse(any(
            "UPDATE official_registry SET" in call.args[0]
            for call in cursor.execute.call_args_list
        ))
        resolve_location.assert_not_called()

    def test_sync_does_not_rewrite_identical_csv_coordinates_or_provenance(self):
        existing = self._existing_sync_record(1)
        existing.update({
            "latitude": 13.9667,
            "longitude": 121.1167,
            "coordSource": "csv",
            "resolveKey": "same-location-key",
        })
        record = self._sync_frame_record(1)
        record.update({"latitude": "13.9667", "longitude": "121.1167"})

        summary, error, cursor, resolve_location = self._run_mocked_sync(
            pd.DataFrame([record]), [existing]
        )

        self.assertIsNone(error)
        self.assertEqual(summary["updated"], 0)
        self.assertEqual(summary["unchanged"], 1)
        self.assertFalse(any(
            "UPDATE official_registry" in call.args[0]
            for call in cursor.execute.call_args_list
        ))
        resolve_location.assert_not_called()

    def test_sync_still_retries_unchanged_row_after_retryable_resolution_failure(self):
        existing = self._existing_sync_record(1)
        existing.update({
            "latitude": None,
            "longitude": None,
            "resolveKey": None,
        })
        frame = pd.DataFrame([self._sync_frame_record(1)])

        summary, error, cursor, resolve_location = self._run_mocked_sync(
            frame,
            [existing],
            resolve_result=(
                None, None, {"reason": "api_error", "api_error": "mocked failure"}
            ),
        )

        self.assertIsNone(error)
        self.assertEqual(summary["updated"], 0)
        self.assertEqual(summary["unchanged"], 1)
        self.assertEqual(summary["api_error"], 1)
        self.assertFalse(any(
            "UPDATE official_registry SET" in call.args[0]
            for call in cursor.execute.call_args_list
        ))
        resolve_location.assert_called_once()

    def test_sync_persists_successful_resolution_without_counting_business_change(self):
        existing = self._existing_sync_record(1)
        existing.update({
            "latitude": None,
            "longitude": None,
            "resolveKey": None,
        })
        frame = pd.DataFrame([self._sync_frame_record(1)])
        successful_resolution = (
            13.967, 121.117,
            {
                "coord_source": "places",
                "place_id": "mock-place",
                "place_id_kind": "poi",
                "score": 0.95,
                "match_status": "auto",
                "resolve_key": "same-location-key",
            },
        )

        summary, error, cursor, resolve_location = self._run_mocked_sync(
            frame, [existing], resolve_result=successful_resolution
        )

        self.assertIsNone(error)
        self.assertEqual(summary["updated"], 0)
        self.assertEqual(summary["unchanged"], 1)
        coordinate_updates = [
            call for call in cursor.execute.call_args_list
            if "UPDATE official_registry" in call.args[0]
        ]
        self.assertEqual(len(coordinate_updates), 2)
        self.assertIn("SET latitude=%s, longitude=%s", coordinate_updates[0].args[0])
        self.assertIn("coordSource=%s", coordinate_updates[1].args[0])
        resolve_location.assert_called_once()

    def test_600_row_import_uses_geocoding_after_registry_text_search_quota(
        self,
    ):
        from api.registry import places_resolver

        class MockResponse:
            status_code = 200
            text = ""

            def __init__(self, payload):
                self.payload = payload

            def json(self):
                return self.payload

        cursor = MagicMock()
        cursor.fetchall.return_value = []
        cursor.fetchone.return_value = None
        cursor.rowcount = 1
        mysql = MagicMock()
        mysql.connection.cursor.return_value = cursor

        frame = pd.DataFrame([{
            "Business ID": f"BIZ-{index:04d}",
            "businessName": f"BPLO Business {index:04d}",
            "businessAddress": f"{index + 1} Main Street",
            "barangay": "Barangay I",
            "applicationStatus": "Active",
        } for index in range(600)])

        text_search_reservations = 0
        text_search_requests = 0
        geocode_reservations = 0
        geocode_requests = 0

        def reserve_text_search(_prefix, *_args, **_kwargs):
            nonlocal text_search_reservations
            text_search_reservations += 1
            if text_search_reservations <= 40:
                return True
            places_resolver._api_state.quota_reason = "daily_quota_exceeded"
            return False

        def fake_post(_url, **kwargs):
            nonlocal text_search_requests
            text_search_requests += 1
            business_name = kwargs["json"]["textQuery"].split(",", 1)[0]
            return MockResponse({
                "places": [{
                    "id": f"place-{business_name}",
                    "displayName": {"text": business_name},
                    "location": {"latitude": 13.9667, "longitude": 121.1167},
                    "types": ["store"],
                }]
            })

        def reserve_geocode():
            nonlocal geocode_reservations
            geocode_reservations += 1
            return True

        def fake_get(_url, **_kwargs):
            nonlocal geocode_requests
            geocode_requests += 1
            return MockResponse({
                "status": "OK",
                "results": [{
                    "geometry": {
                        "location": {"lat": 13.9667, "lng": 121.1167},
                        "location_type": "ROOFTOP",
                    },
                    "place_id": "geocoded-place",
                }],
            })

        original_resolve_location = places_resolver.resolve_location

        def safe_resolve_location(*args, **kwargs):
            return original_resolve_location(
                *args, _post=fake_post, _get=fake_get, **kwargs
            )

        usage = {
            "text_search": {"day": 40, "month": 40},
            "text_search_workflows": {},
            "details": {"day": 0, "month": 0},
            "geocoding": {"day": 560, "month": 560},
        }
        with (
            patch.object(service, "mysql", mysql),
            patch.object(places_resolver, "mysql", mysql),
            patch.object(service, "GOOGLE_MAPS_API_KEY", "test-key"),
            patch.dict(os.environ, {"GOOGLE_MAPS_API_KEY": "test-key"}),
            patch.object(service.pd, "read_excel", return_value=frame),
            patch.object(
                service, "_load_barangay_lookup",
                return_value={"barangay i": 1},
            ),
            patch.object(service, "_resolve_barangay_id", return_value=1),
            patch.object(service, "is_cancelled", return_value=False),
            patch.object(places_resolver, "reserve_call", side_effect=reserve_text_search),
            patch.object(service, "_reserve_geocode_call", side_effect=reserve_geocode),
            patch.object(places_resolver.quota_settings, "cap", return_value=1000),
            patch.object(
                places_resolver, "resolve_location",
                side_effect=safe_resolve_location,
            ),
            patch.object(places_resolver.time, "sleep"),
            patch.object(places_resolver, "_last_places_request_at", 0),
            patch.object(
                places_resolver, "get_places_call_usage", return_value=usage
            ),
            patch.object(service, "insert_green_flag"),
            patch("api.notifications.hub.publish_to_admins"),
        ):
            summary, error = service.upload_registry(BytesIO(b"mocked xlsx"), ".xlsx")

        self.assertIsNone(error)
        self.assertEqual(summary["total_rows"], 600)
        self.assertEqual(summary["inserted"], 600)
        self.assertEqual(summary["geocoded_ok"], 600)
        self.assertEqual(summary["geocoded_failed"], 0)
        self.assertEqual(summary["skipped_quota"], 0)
        self.assertEqual(text_search_reservations, 41)
        self.assertEqual(text_search_requests, 40)
        self.assertEqual(geocode_reservations, 560)
        self.assertEqual(geocode_requests, 560)

        insert_calls = [
            call for call in cursor.execute.call_args_list
            if "INSERT IGNORE INTO official_registry" in call.args[0]
        ]
        self.assertEqual(len(insert_calls), 600)
        self.assertTrue(all(call.args[1][6:8] == (13.9667, 121.1167) for call in insert_calls))

    def test_coordinate_pair_requires_finite_in_range_values(self):
        self.assertEqual(service._parse_coordinate_pair("13.96", "121.11"), (13.96, 121.11))
        self.assertIsNone(service._parse_coordinate_pair("91", "121.11"))
        self.assertIsNone(service._parse_coordinate_pair("13.96", "inf"))
        self.assertIsNone(service._parse_coordinate_pair("13.96", None))

    def test_import_boundary_accepts_municipal_center_and_rejects_outside(self):
        self.assertTrue(
            service._coordinate_pair_within_municipality((13.9667, 121.1167))
        )
        self.assertFalse(
            service._coordinate_pair_within_municipality((13.9667, 121.2))
        )

    def test_upload_keeps_valid_business_and_ignores_out_of_bounds_coordinates(self):
        cursor = MagicMock()
        cursor.fetchall.return_value = []
        cursor.rowcount = 1
        mysql = MagicMock()
        mysql.connection.cursor.return_value = cursor
        frame = pd.DataFrame([{
            "Business ID": "BIZ-OUTSIDE",
            "businessName": "Café de Ángel",
            "businessAddress": "Main Street",
            "barangay": "Barangay I",
            "latitude": "13.9667",
            "longitude": "121.2",
            "applicationStatus": None,
        }])
        usage = {
            "text_search": {"day": 0, "month": 0},
            "details": {"day": 0, "month": 0},
            "geocoding": {"day": 0, "month": 0},
        }
        with (
            patch.object(service, "mysql", mysql),
            patch.object(service, "GOOGLE_MAPS_API_KEY", None),
            patch.object(service.pd, "read_csv", return_value=frame),
            patch.object(service, "_load_barangay_lookup", return_value={"barangay i": 1}),
            patch.object(service, "_resolve_barangay_id", return_value=1),
            patch.object(service, "is_cancelled", return_value=False),
            patch.object(service.places_resolver, "reset_run_state"),
            patch.object(service.places_resolver, "compute_resolve_key", return_value="key"),
            patch.object(
                service,
                "_resolve_location",
                return_value=(
                    None, None,
                    {"reason": "skipped_quota", "budget_exhausted": True},
                ),
            ) as resolve_location,
            patch.object(service.places_resolver, "get_places_call_usage", return_value=usage),
            patch.object(service, "insert_green_flag") as insert_flag,
            patch("api.notifications.hub.publish_to_admins"),
        ):
            summary, error = service.upload_registry(BytesIO(b"csv"), ".csv")

        self.assertIsNone(error)
        self.assertEqual(summary["inserted"], 1)
        self.assertEqual(summary["skipped_quota"], 1)
        self.assertEqual(summary["coordinates_out_of_bounds"], 1)
        self.assertIn("outside the Mataasnakahoy boundary", summary["errors"][0])
        resolve_location.assert_called_once()
        insert_flag.assert_not_called()
        insert_call = next(
            call for call in cursor.execute.call_args_list
            if "INSERT IGNORE INTO official_registry" in call.args[0]
        )
        values = insert_call.args[1]
        self.assertEqual(values[2], "CAFÉ DE ÁNGEL")
        self.assertIsNone(values[6])
        self.assertIsNone(values[7])
        self.assertEqual(values[8], "Pending")

    def test_sync_defaults_missing_status_to_pending_and_preserves_caps(self):
        cursor = MagicMock()
        cursor.fetchone.return_value = None
        cursor.rowcount = 1
        mysql = MagicMock()
        mysql.connection.cursor.return_value = cursor
        frame = pd.DataFrame([{
            "Business ID": "BIZ-NEW",
            "businessName": "Café de Ángel",
            "businessAddress": "Main Street",
            "barangay": "Barangay I",
            "latitude": "13.9667",
            "longitude": "121.1167",
            "applicationStatus": None,
        }])
        usage = {
            "text_search": {"day": 0, "month": 0},
            "details": {"day": 0, "month": 0},
            "geocoding": {"day": 0, "month": 0},
        }
        with (
            patch.object(service, "mysql", mysql),
            patch.object(service.pd, "read_csv", return_value=frame),
            patch.object(service, "_load_barangay_lookup", return_value={"barangay i": 1}),
            patch.object(service, "_resolve_barangay_id", return_value=1),
            patch.object(service, "is_cancelled", return_value=False),
            patch.object(service.places_resolver, "reset_run_state"),
            patch.object(service.places_resolver, "compute_resolve_key", return_value="key"),
            patch.object(service.places_resolver, "record_coord_meta"),
            patch.object(service.places_resolver, "get_places_call_usage", return_value=usage),
            patch.object(service, "insert_green_flag"),
            patch("api.notifications.hub.publish_to_admins"),
        ):
            summary, error = service.sync_registry(BytesIO(b"csv"), ".csv")

        self.assertIsNone(error)
        self.assertEqual(summary["inserted"], 1)
        self.assertEqual(summary["updated"], 0)
        self.assertEqual(summary["unchanged"], 0)
        insert_call = next(
            call for call in cursor.execute.call_args_list
            if "INSERT INTO official_registry" in call.args[0]
        )
        values = insert_call.args[1]
        self.assertEqual(values[2], "CAFÉ DE ÁNGEL")
        self.assertEqual(values[8], "Pending")

    def test_transient_resolver_failures_do_not_become_cache_keys(self):
        for meta in (
            {"reason": "api_error"},
            {"reason": "skipped_quota", "budget_exhausted": True},
            {"reason": "monthly_quota_exceeded"},
        ):
            with self.subTest(meta=meta):
                self.assertIsNone(service._resolution_key_for_cache("new-key", meta))
        self.assertEqual(
            service._resolution_key_for_cache("new-key", {"reason": "no_text_results"}),
            "new-key",
        )

    def test_import_preserves_authoritative_manual_and_csv_coordinates(self):
        self.assertTrue(service._preserve_import_coordinates("manual", "auto", True))
        self.assertTrue(service._preserve_import_coordinates("places", "approved", True))
        self.assertTrue(service._preserve_import_coordinates("csv", "auto", False))
        self.assertFalse(service._preserve_import_coordinates("csv", "auto", True))
        self.assertFalse(service._preserve_import_coordinates("geocode", "auto", False))

    def test_legacy_geocode_http_error_is_not_reported_as_no_match(self):
        response = MagicMock(status_code=503, text="upstream unavailable")
        service._geocode_state.outcome = None
        with (
            patch.dict(os.environ, {"GOOGLE_MAPS_API_KEY": "test-key"}),
            patch.object(service, "_reserve_geocode_call", return_value=True),
            patch.object(service.http, "get", return_value=response),
        ):
            self.assertEqual(service._geocode("Main Street", "Barangay I"), (None, None))

        self.assertEqual(service._geocode_state.outcome, "api_error")
        response.json.assert_not_called()

    def test_legacy_name_only_geocode_has_geocode_provenance_and_one_request(self):
        service._geocode_state.outcome = None
        with (
            patch.object(service.places_resolver, "enabled", return_value=False),
            patch.object(service.places_resolver, "compute_resolve_key", return_value="resolve-key"),
            patch.object(service, "_geocode", return_value=(13.96, 121.11)) as geocode,
        ):
            result = service._resolve_location(
                "Silva Pharmacy", "", "Barangay I", barangay_id=1
            )

        self.assertEqual(result[:2], (13.96, 121.11))
        self.assertEqual(result[2]["coord_source"], "geocode")
        self.assertEqual(result[2]["place_id_kind"], "address")
        geocode.assert_called_once_with("Silva Pharmacy", "Barangay I")

    def test_sync_preserves_existing_pin_and_retryability_on_api_failure(self):
        existing = {
            "businessID": "BIZ-1",
            "latitude": 13.96,
            "longitude": 121.11,
            "coordSource": "geocode",
            "matchStatus": "auto",
            "resolveKey": "old-key",
        }
        cursor = MagicMock()
        cursor.fetchone.return_value = existing
        cursor.rowcount = 1
        mysql = MagicMock()
        mysql.connection.cursor.return_value = cursor

        frame = pd.DataFrame([{
            "Business ID": "BIZ-1",
            "businessName": "Updated Pharmacy",
            "businessAddress": "New Main Street",
            "barangay": "Barangay I",
            "lineOfBusiness": "Pharmacy",
            "applicationStatus": "Active",
        }])
        usage = {
            "text_search": {"day": 3, "month": 10},
            "details": {"day": 0, "month": 0},
            "geocoding": {"day": 1, "month": 4},
        }
        with (
            patch.object(service, "mysql", mysql),
            patch.object(service.pd, "read_csv", return_value=frame),
            patch.object(service, "_load_barangay_lookup", return_value={"Barangay I": 1}),
            patch.object(service, "_resolve_barangay_id", return_value=1),
            patch.object(service, "is_cancelled", return_value=False),
            patch.object(service.places_resolver, "reset_run_state"),
            patch.object(service.places_resolver, "compute_resolve_key", return_value="new-key"),
            patch.object(
                service,
                "_resolve_location",
                return_value=(None, None, {"reason": "api_error", "api_error": "HTTP 503"}),
            ) as resolve_location,
            patch.object(service.places_resolver, "record_coord_meta") as record_coord_meta,
            patch.object(service.places_resolver, "get_places_call_usage", return_value=usage),
            patch.object(service.places_resolver, "_update_pin") as update_pin,
            patch.object(service, "_sync_flag_color") as sync_flag,
            patch.object(service, "insert_green_flag") as insert_flag,
            patch("api.notifications.hub.publish_to_admins"),
        ):
            summary, error = service.sync_registry(BytesIO(b"csv"), ".csv")

        self.assertIsNone(error)
        self.assertEqual(summary["api_error"], 1)
        self.assertEqual(summary["skipped_quota"], 0)
        resolve_location.assert_called_once()
        record_coord_meta.assert_not_called()
        update_pin.assert_not_called()
        sync_flag.assert_not_called()
        insert_flag.assert_not_called()

        update_call = next(
            call for call in cursor.execute.call_args_list
            if "UPDATE official_registry SET" in call.args[0]
        )
        self.assertIn("resolveKey = COALESCE(%s, resolveKey)", update_call.args[0])
        self.assertEqual(update_call.args[1][5:7], (13.96, 121.11))
        self.assertIsNone(update_call.args[1][11])

    def test_sync_moves_existing_pin_when_changed_business_data_resolves(self):
        existing = {
            "businessID": "BIZ-1",
            "latitude": 13.96,
            "longitude": 121.11,
            "coordSource": "geocode",
            "matchStatus": "auto",
            "resolveKey": "old-key",
        }
        cursor = MagicMock()
        cursor.fetchone.return_value = existing
        cursor.rowcount = 1
        mysql = MagicMock()
        mysql.connection.cursor.return_value = cursor
        frame = pd.DataFrame([{
            "Business ID": "BIZ-1",
            "businessName": "Updated Pharmacy",
            "businessAddress": "New Main Street",
            "barangay": "Barangay I",
            "lineOfBusiness": "Pharmacy",
            "applicationStatus": "Active",
        }])
        usage = {
            "text_search": {"day": 4, "month": 11},
            "details": {"day": 0, "month": 0},
            "geocoding": {"day": 1, "month": 4},
        }
        with (
            patch.object(service, "mysql", mysql),
            patch.object(service.pd, "read_csv", return_value=frame),
            patch.object(service, "_load_barangay_lookup", return_value={"Barangay I": 1}),
            patch.object(service, "_resolve_barangay_id", return_value=1),
            patch.object(service, "is_cancelled", return_value=False),
            patch.object(service.places_resolver, "reset_run_state"),
            patch.object(service.places_resolver, "compute_resolve_key", return_value="new-key"),
            patch.object(
                service,
                "_resolve_location",
                return_value=(
                    13.9667, 121.1167,
                    {
                        "coord_source": "places",
                        "place_id": "new-place",
                        "place_id_kind": "poi",
                        "score": 0.92,
                        "match_status": "auto",
                        "resolve_key": "new-key",
                    },
                ),
            ),
            patch.object(service.places_resolver, "record_coord_meta"),
            patch.object(service.places_resolver, "_update_pin") as update_pin,
            patch.object(service.places_resolver, "get_places_call_usage", return_value=usage),
            patch.object(service, "_sync_flag_color"),
            patch("api.notifications.hub.publish_to_admins"),
        ):
            summary, error = service.sync_registry(BytesIO(b"csv"), ".csv")

        self.assertIsNone(error)
        self.assertEqual(summary["resolved"], 1)
        update_pin.assert_called_once_with(
            cursor, 1, "UPDATED PHARMACY", 13.96, 121.11,
            13.9667, 121.1167, business_id="BIZ-1",
        )


if __name__ == "__main__":
    unittest.main()
