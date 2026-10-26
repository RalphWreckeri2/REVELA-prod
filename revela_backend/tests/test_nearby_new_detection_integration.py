import unittest
from contextlib import ExitStack
from unittest.mock import MagicMock, patch

from api.flags import service


class StatefulDetectionDatabase:
    """Minimal in-memory MySQL substitute for the detection workflow."""

    def __init__(self, registry, barangays):
        self.registry = [dict(row) for row in registry]
        self.barangays = list(barangays)
        self.flags = []
        self.checkpoints = set()
        self.rejected_pairs = set()
        self.next_log_id = 1
        self.connection = self

    def cursor(self):
        return StatefulDetectionCursor(self)

    def commit(self):
        pass

    def rollback(self):
        pass

    def begin(self):
        pass


class StatefulDetectionCursor:
    def __init__(self, database):
        self.database = database
        self._rows = []
        self._row = None
        self.lastrowid = None

    def execute(self, query, params=()):
        sql = " ".join(query.lower().split())
        self._rows = []
        self._row = None
        self.lastrowid = None

        if "information_schema.columns" in sql:
            # Schema probe. This fake database has not had
            # migrations/20261017_01_geospatial_source.sql applied, so answer
            # "the column is absent" and the INSERTs omit `source`.
            self._row = None
        elif "select count(*) as total from official_registry" in sql:
            self._row = {"total": len(self.database.registry)}
        elif "select barangayid, barangayname from barangays" in sql:
            self._rows = list(self.database.barangays)
        elif "select businessid, placeid from registry_rejected_places" in sql:
            self._rows = [
                {"businessID": business_id, "placeID": place_id}
                for business_id, place_id in self.database.rejected_pairs
            ]
        elif "select pointkey from scan_point_log" in sql:
            self._rows = [
                {"pointKey": point_key}
                for point_key in sorted(self.database.checkpoints)
            ]
        elif "from geospatial_logs g where g.placeid in" in sql:
            place_ids = set(params)
            self._rows = [
                {
                    "logID": flag["logID"],
                    "placeID": flag.get("placeID"),
                    "flagColor": flag["flagColor"],
                    "has_verified_orange": False,
                }
                for flag in self.database.flags
                if flag.get("placeID") in place_ids
            ]
        elif (
            "select coordsource, matchstatus, latitude, longitude, placeid "
            "from official_registry" in sql
        ):
            business_id = params[0]
            self._row = next(
                (
                    {
                        "coordSource": row.get("coordSource"),
                        "matchStatus": row.get("matchStatus"),
                        "latitude": row.get("latitude"),
                        "longitude": row.get("longitude"),
                        "placeID": row.get("placeID"),
                    }
                    for row in self.database.registry
                    if row.get("businessID") == business_id
                ),
                None,
            )
        elif "from geospatial_logs g where (g.businessid is not null" in sql:
            business_id, place_id, name, barangay_id = params[:4]
            self._rows = [
                {
                    "logID": flag["logID"],
                    "businessID": flag.get("businessID"),
                    "placeID": flag.get("placeID"),
                    "flagColor": flag["flagColor"],
                    "latitude": flag.get("latitude"),
                    "longitude": flag.get("longitude"),
                    "has_verified_orange": False,
                }
                for flag in self.database.flags
                if (
                    flag.get("businessID") == business_id
                    or flag.get("placeID") == place_id
                    or (
                        flag.get("businessID") is None
                        and flag.get("detectedName") == name
                        and flag.get("barangayID") == barangay_id
                    )
                )
            ]
        elif sql.startswith("update official_registry"):
            latitude, longitude, place_id, match_score, business_id = params
            row = next(
                item for item in self.database.registry
                if item.get("businessID") == business_id
            )
            row.update({
                "latitude": latitude,
                "longitude": longitude,
                "placeID": place_id,
                "placeIDKind": "poi",
                "coordSource": "places",
                "matchScore": match_score,
                "matchStatus": "auto" if "matchstatus = 'auto'" in sql else "review",
            })
        elif sql.startswith("insert into geospatial_logs"):
            if "(barangayid, reportid," in sql:
                barangay_id, name, latitude, longitude, place_id, address, types = params
                flag = {
                    "barangayID": barangay_id,
                    "businessID": None,
                    "detectedName": name,
                    "latitude": latitude,
                    "longitude": longitude,
                    "flagColor": "Red",
                    "placeID": place_id,
                    "nearestLandmark": address,
                    "placeTypes": types,
                }
            elif "(barangayid, businessid," in sql:
                (
                    barangay_id, business_id, name, latitude, longitude,
                    color, place_id, address, types,
                ) = params
                flag = {
                    "barangayID": barangay_id,
                    "businessID": business_id,
                    "detectedName": name,
                    "latitude": latitude,
                    "longitude": longitude,
                    "flagColor": color,
                    "placeID": place_id,
                    "nearestLandmark": address,
                    "placeTypes": types,
                }
            else:
                raise AssertionError(f"Unexpected geospatial_logs insert: {query}")
            flag["logID"] = self.database.next_log_id
            self.database.next_log_id += 1
            self.database.flags.append(flag)
            self.lastrowid = flag["logID"]
        elif sql.startswith("update geospatial_logs set businessid"):
            (
                business_id, place_id, color, name, latitude, longitude,
                address, types, barangay_id, log_id,
            ) = params
            flag = next(
                item for item in self.database.flags
                if item["logID"] == log_id
            )
            flag.update({
                "businessID": business_id,
                "placeID": place_id,
                "flagColor": color,
                "detectedName": name,
                "latitude": latitude,
                "longitude": longitude,
                "nearestLandmark": address or flag.get("nearestLandmark"),
                "placeTypes": types or flag.get("placeTypes"),
                "barangayID": barangay_id or flag.get("barangayID"),
            })
        elif sql.startswith("insert into scan_point_log"):
            self.database.checkpoints.add(params[0])
        else:
            raise AssertionError(f"Unexpected fake database SQL: {query}")

    def fetchone(self):
        return self._row

    def fetchall(self):
        return list(self._rows)

    def close(self):
        pass


from api.models.geospatial import reset_source_column_cache


class NearbyNewDetectionIntegrationTests(unittest.TestCase):
    def setUp(self):
        # geospatial_source_column_exists caches for the life of the process,
        # so a test that answered the probe would decide it for every later
        # test in the run.
        reset_source_column_cache()
        self.addCleanup(reset_source_column_cache)

    def test_detection_matches_filters_flags_and_resumes_offline(self):
        point_a = (13.9667, 121.1167)
        point_b = (13.9750, 121.1167)
        points = [point_a, point_b]
        registry = [{
            "businessID": "BIZ-SILVA",
            "businessName": "Silva Pharmacy",
            "businessLine": "Pharmacy",
            "businessType": "Pharmacy",
            "businessAddress": "Poblacion, Mataasnakahoy",
            "applicationStatus": "Active",
            "placeID": None,
            "coordSource": "csv",
            "matchStatus": None,
            "barangayID": 1,
            "latitude": point_a[0],
            "longitude": point_a[1],
        }]
        database = StatefulDetectionDatabase(
            registry,
            [{"barangayID": 1, "barangayName": "Barangay I"}],
        )
        registered = {
            "id": "place-silva",
            "displayName": {"text": "Silva Pharmacy"},
            "location": {
                "latitude": point_a[0],
                "longitude": point_a[1],
            },
            "formattedAddress": "Poblacion, Mataasnakahoy",
            "primaryType": "pharmacy",
            "businessStatus": "OPERATIONAL",
        }
        unregistered = {
            "id": "place-unregistered",
            "displayName": {"text": "Lakeside Variety Store"},
            "location": {
                "latitude": point_a[0],
                "longitude": point_a[1],
            },
            "formattedAddress": "Poblacion, Mataasnakahoy",
            "primaryType": "store",
            "businessStatus": "OPERATIONAL",
        }
        library = {
            "id": "place-library",
            "displayName": {"text": "Community Library"},
            "location": {
                "latitude": point_a[0],
                "longitude": point_a[1],
            },
            "primaryType": "library",
            "businessStatus": "OPERATIONAL",
        }
        barangay_hall = {
            "id": "place-hall",
            "displayName": {"text": "Barangay Hall"},
            "location": {
                "latitude": point_a[0],
                "longitude": point_a[1],
            },
            "primaryType": "government_office",
            "businessStatus": "OPERATIONAL",
        }
        successful_response = {
            "places": [registered, unregistered, library, barangay_hall]
        }
        calls_by_point = {point_a: 0, point_b: 0}
        phase = {"name": "first"}

        def mocked_post(_url, **kwargs):
            center = kwargs["json"]["locationRestriction"]["circle"]["center"]
            point = (center["latitude"], center["longitude"])
            calls_by_point[point] += 1
            response = MagicMock()
            if point == point_b and phase["name"] == "first":
                response.status_code = 503
                response.text = "offline simulated failure"
                response.json.return_value = {}
            else:
                response.status_code = 200
                response.text = ""
                response.json.return_value = successful_response
            return response

        quota_info = {
            "is_limit_reached": False,
            "monthly_limit": 10,
            "registry_count": len(registry),
            "remaining_this_month": 10,
        }
        cap_values = {
            "quota.nearby_new.daily": 5,
            "quota.nearby_new.monthly": 20,
            "run_detection.max_seconds": 90,
            "run_detection.max_requests": 10,
            "run_detection.grid_step_degrees": 0.009,
        }

        with (
            patch.dict("os.environ", {"GOOGLE_MAPS_API_KEY": "offline-test-key"}),
            patch.object(service, "RUN_DETECTION_NEARBY_API", "new"),
            patch.object(service, "mysql", database),
            patch.object(service, "get_detection_quota_info", return_value=quota_info),
            patch.object(service, "_ensure_place_types_column"),
            patch.object(service, "_load_registry", side_effect=lambda: database.registry),
            patch.object(service, "reconcile_existing_flags"),
            patch.object(service, "create_detection_run", side_effect=lambda *_args: 1),
            patch.object(service, "update_detection_run_status"),
            patch.object(service, "_log_detection_summary", return_value={}),
            patch.object(service, "_detection_points_for_mode", return_value=points),
            patch.object(service, "_within_municipality", return_value=True),
            patch.object(service, "_get_barangay_id_by_coords", return_value=1),
            patch.object(
                service.quota_settings,
                "cap",
                side_effect=lambda key: cap_values.get(key, 100),
            ),
            patch.object(service.test_mode, "is_enabled", return_value=False),
            patch.object(service, "reserve_usage_slot", return_value=(True, None)) as reserve,
            patch.object(service.http, "post", side_effect=mocked_post) as post,
            patch.object(service, "_nearby_last_request_at", 0),
            patch.object(service.time, "sleep"),
            patch.object(service.hub, "publish_to_admins"),
        ):
            first_result, first_error = service.run_detection(mode="full")

            self.assertIsNone(first_error)
            self.assertEqual(first_result["status"], "partial")
            self.assertEqual(first_result["completed_points"], 1)
            self.assertEqual(first_result["incomplete_points"], 1)
            self.assertEqual(first_result["run_summary"]["api_requests_consumed"], 2)
            self.assertEqual(first_result["quota"]["remaining_this_month"], 10)
            self.assertEqual(first_result["run_summary"]["matched"], 1)
            self.assertEqual(first_result["run_summary"]["new_flags"], 1)
            self.assertEqual(first_result["run_summary"]["non_business"], 2)

            registered_flags = [
                flag for flag in database.flags
                if flag["placeID"] == "place-silva"
            ]
            red_flags = [
                flag for flag in database.flags
                if flag["placeID"] == "place-unregistered"
            ]
            self.assertEqual(len(registered_flags), 1)
            self.assertEqual(registered_flags[0]["businessID"], "BIZ-SILVA")
            self.assertEqual(registered_flags[0]["flagColor"], "Green")
            self.assertEqual(len(red_flags), 1)
            self.assertEqual(red_flags[0]["flagColor"], "Red")
            self.assertFalse(any(
                flag.get("placeID") in {"place-library", "place-hall"}
                for flag in database.flags
            ))
            self.assertEqual(calls_by_point, {point_a: 1, point_b: 1})
            fingerprint = service._checkpoint_configuration_fingerprint("full")
            point_a_key = service._checkpoint_point_key(*point_a, fingerprint)
            point_b_key = service._checkpoint_point_key(*point_b, fingerprint)
            self.assertEqual(database.checkpoints, {point_a_key})
            self.assertNotIn(point_b_key, database.checkpoints)

            phase["name"] = "resume"
            second_result, second_error = service.run_detection(mode="full")

        self.assertIsNone(second_error)
        self.assertEqual(second_result["status"], "completed")
        self.assertEqual(second_result["completed_points"], 2)
        self.assertEqual(second_result["attempted_points"], 2)
        self.assertEqual(second_result["run_summary"]["api_requests_consumed"], 1)
        self.assertEqual(second_result["run_summary"]["new_flags"], 0)
        self.assertEqual(second_result["run_summary"]["non_business"], 2)
        self.assertEqual(calls_by_point, {point_a: 1, point_b: 2})
        self.assertEqual(database.checkpoints, {point_a_key, point_b_key})
        self.assertEqual(len([
            flag for flag in database.flags
            if flag.get("placeID") == "place-unregistered"
            and flag["flagColor"] == "Red"
        ]), 1)
        self.assertEqual(post.call_count, 3)
        self.assertEqual(reserve.call_count, 3)
        self.assertNotIn("place-library", {f.get("placeID") for f in database.flags})
        self.assertNotIn("place-hall", {f.get("placeID") for f in database.flags})

class DetectionBudgetRollbackTests(unittest.TestCase):
    """Exercise the restored runner with paid calls and storage isolated."""

    def setUp(self):
        stack = self.enterContext(ExitStack())
        stack.enter_context(patch.dict(service._places_run_state.__dict__, {}, clear=True))
        self.points = [(13.96 + i * 0.0001, 121.11) for i in range(24)]
        self.database = StatefulDetectionDatabase(
            [{"businessID": "SAVED", "businessName": "Existing Store"}], []
        )
        self.caps = {
            key: spec["baseline"] for key, spec in service.quota_settings.QUOTA_FIELDS.items()
        }
        self.caps["run_detection.max_requests"] = 5
        self.quota = {"is_limit_reached": False, "monthly_limit": 5, "remaining_this_month": 5}
        response = MagicMock(status_code=200)
        response.json.return_value = {"status": "ZERO_RESULTS", "results": [], "places": []}
        self.reserve = MagicMock(return_value=(True, None))
        self.get = MagicMock(return_value=response)
        self.post = MagicMock(return_value=response)
        self.create = MagicMock(return_value=1)
        self.update = MagicMock()
        for context in (
            patch.dict("os.environ", {"GOOGLE_MAPS_API_KEY": "offline-rollback-test-key"}),
            patch.object(service, "mysql", self.database),
            patch.object(service, "RUN_DETECTION_NEARBY_API", "legacy"),
            patch.object(service, "get_detection_quota_info", side_effect=lambda: dict(self.quota)),
            patch.object(service, "create_detection_run", self.create),
            patch.object(service, "update_detection_run_status", self.update),
            patch.object(service, "_ensure_budget_tables"),
            patch.object(service, "_ensure_place_types_column"),
            patch.object(service, "_load_registry", return_value=self.database.registry),
            patch.object(service, "_load_rejected_place_pairs", return_value=set()),
            patch.object(service, "reconcile_existing_flags"),
            patch.object(service, "_detection_points_for_mode", return_value=self.points),
            patch.object(service, "_log_detection_summary", return_value={}),
            patch.object(service, "reserve_usage_slot", self.reserve),
            patch.object(service.http, "get", self.get),
            patch.object(service.http, "post", self.post),
            patch.object(service.LEGACY_NEARBY_LIMITER, "acquire", return_value=0),
            patch.object(service.time, "sleep"),
            patch.object(service.hub, "publish_to_admins"),
            patch.object(service.test_mode, "is_enabled", return_value=False),
            patch.object(service.quota_settings, "cap", side_effect=self.caps.__getitem__),
        ):
            stack.enter_context(context)

    def test_five_request_quick_slice_starts_pauses_and_keeps_saved_progress(self):
        fingerprint = service._checkpoint_configuration_fingerprint("quick")
        original_keys = {
            service._checkpoint_point_key(*point, fingerprint) for point in self.points[:4]
        }
        self.database.checkpoints.update(original_keys)

        result, error = service.run_detection(mode="quick")

        self.assertIsNone(error)
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["completed_points"], 9)
        self.assertEqual(result["attempted_points"], 9)  # Previous counter includes the four saved cells.
        self.assertEqual(result["run_summary"]["api_requests_consumed"], 5)
        self.assertEqual(result["run_summary"]["work_budget_reason"], "request_limit")
        self.assertEqual(
            result["run_summary"]["work_budget_max_requests"], 5
        )
        self.assertEqual(result["quota"]["remaining_this_month"], 5)
        self.assertEqual(self.get.call_count, 5)
        self.assertEqual(self.reserve.call_count, 5)
        self.post.assert_not_called()
        self.create.assert_called_once()
        self.update.assert_called_once_with(1, "partial", new_flags=0, total_checked=0)
        self.assertTrue(original_keys.issubset(self.database.checkpoints))
        self.assertEqual(len(self.database.checkpoints), 9)

        resumed, error = service.run_detection(mode="quick")

        self.assertIsNone(error)
        self.assertEqual(resumed["status"], "partial")
        self.assertEqual(resumed["completed_points"], 14)
        self.assertEqual(len(self.database.checkpoints), 14)
        self.assertEqual(self.get.call_count, 10)
        self.assertEqual(len({
            (call.kwargs["params"]["location"]) for call in self.get.call_args_list
        }), 10)  # Already checkpointed cells are not requested again.

    def test_daily_and_monthly_denials_still_stop_before_the_next_paid_request(self):
        for reason in ("daily_quota_exceeded", "monthly_quota_exceeded"):
            with self.subTest(reason=reason):
                self.database.checkpoints.clear()
                self.get.reset_mock()
                self.update.reset_mock()
                self.reserve.reset_mock()
                self.reserve.side_effect = [(True, None), (True, None), (False, reason)]

                result, error = service.run_detection(mode="quick")

                self.assertEqual(result["status"], reason)
                self.assertIn("Progress is saved", error)
                self.assertEqual(self.get.call_count, 2)
                self.assertEqual(self.reserve.call_count, 3)
                self.assertEqual(result["run_summary"]["api_requests_consumed"], 2)
                self.assertEqual(len(self.database.checkpoints), 2)
                self.update.assert_called_once_with(1, "partial", new_flags=0, total_checked=0)
                self.assertEqual(
                    self.reserve.call_args.args[1:],
                    ("month", "day", self.caps["quota.legacy_nearby.monthly"], self.caps["quota.legacy_nearby.daily"]),
                )

    def test_monthly_completed_scan_limit_still_rejects_before_starting(self):
        self.quota["is_limit_reached"] = True

        result, error = service.run_detection(mode="quick")

        self.assertIsNone(result)
        self.assertIn("Monthly detection limit reached", error)
        self.create.assert_not_called()
        self.reserve.assert_not_called()
        self.get.assert_not_called()
        self.post.assert_not_called()


if __name__ == "__main__":
    unittest.main()
