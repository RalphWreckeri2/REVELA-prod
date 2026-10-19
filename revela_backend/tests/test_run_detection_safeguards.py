import unittest
from unittest.mock import MagicMock, patch

from api.flags import service
from api.utils import quota_settings


class DetectionStatusTests(unittest.TestCase):
    def test_missing_and_blank_statuses_are_pending_yellow(self):
        self.assertEqual(service._detection_status_color(None), "Yellow")
        self.assertEqual(service._detection_status_color(""), "Yellow")
        self.assertEqual(service._detection_status_color("   "), "Yellow")

    def test_valid_permit_status_colors_are_unchanged(self):
        expected = {
            "Active": "Green",
            "Expired": "Red",
            "Revoked": "Black",
            "Blacklisted": "Black",
            "Closed": "Purple",
            "Pending": "Yellow",
        }
        for status, color in expected.items():
            with self.subTest(status=status):
                self.assertEqual(
                    service._detection_status_color(status), color
                )


class RejectedPlacePairTests(unittest.TestCase):
    rejected = {("BIZ-1", "PLACE-1")}

    def test_exact_place_lookup_skips_rejected_pair_and_uses_eligible_record(self):
        rejected_entry = {"businessID": "BIZ-1"}
        eligible_entry = {"businessID": "BIZ-2"}
        self.assertIsNone(
            service._registry_entry_for_place_id(
                "PLACE-1",
                {"PLACE-1": [rejected_entry]},
                self.rejected,
            )
        )
        result = service._registry_entry_for_place_id(
            "PLACE-1",
            {"PLACE-1": [rejected_entry, eligible_entry]},
            self.rejected,
        )
        self.assertIs(result, eligible_entry)

    def test_fuzzy_matching_skips_rejected_pair_but_allows_different_place(self):
        registry = [{
            "businessID": "BIZ-1",
            "businessName": "Silva Pharmacy",
            "businessLine": "Pharmacy",
            "businessType": "Pharmacy",
            "businessAddress": "Poblacion",
            "barangayID": 1,
            "latitude": 13.9667,
            "longitude": 121.1167,
        }]
        args = (
            "Silva Pharmacy",
            13.9667,
            121.1167,
            registry,
        )
        rejected_match = service._match_poi_to_registry(
            *args,
            poi_barangay_id=1,
            poi_types=("pharmacy",),
            poi_address="Poblacion",
            place_id="PLACE-1",
            rejected_place_pairs=self.rejected,
        )
        alternate_match = service._match_poi_to_registry(
            *args,
            poi_barangay_id=1,
            poi_types=("pharmacy",),
            poi_address="Poblacion",
            place_id="PLACE-2",
            rejected_place_pairs=self.rejected,
        )
        self.assertIsNone(rejected_match[0])
        self.assertIs(alternate_match[0], registry[0])

    @patch("api.flags.service.mysql")
    def test_rejected_pair_cannot_update_registry_or_geospatial_log(self, mock_mysql):
        cursor = MagicMock()
        cursor.fetchone.return_value = {
            "coordSource": None,
            "matchStatus": "rejected",
            "latitude": None,
            "longitude": None,
            "placeID": None,
        }
        mock_mysql.connection.cursor.return_value = cursor

        service._match_registry_to_google(
            "PLACE-1",
            "BIZ-1",
            "Silva Pharmacy",
            lat=13.9667,
            lng=121.1167,
            barangay_id=1,
            rejected_place_pairs=self.rejected,
        )

        executed = [call.args[0] for call in cursor.execute.call_args_list]
        self.assertFalse(any("UPDATE official_registry" in sql for sql in executed))
        self.assertFalse(any("UPDATE geospatial_logs" in sql for sql in executed))
        self.assertFalse(any("INSERT INTO geospatial_logs" in sql for sql in executed))

    @patch("api.flags.service.mysql")
    def test_approved_place_association_is_not_replaced(self, mock_mysql):
        cursor = MagicMock()
        cursor.fetchone.return_value = {
            "coordSource": "manual",
            "matchStatus": "approved",
            "latitude": 13.9667,
            "longitude": 121.1167,
            "placeID": "PLACE-APPROVED",
        }
        mock_mysql.connection.cursor.return_value = cursor

        service._match_registry_to_google(
            "PLACE-OTHER",
            "BIZ-1",
            "Silva Pharmacy",
            lat=13.968,
            lng=121.118,
            barangay_id=1,
            rejected_place_pairs=self.rejected,
        )

        executed = [call.args[0] for call in cursor.execute.call_args_list]
        self.assertFalse(any("UPDATE official_registry" in sql for sql in executed))
        self.assertFalse(any("UPDATE geospatial_logs" in sql for sql in executed))
        self.assertFalse(any("INSERT INTO geospatial_logs" in sql for sql in executed))


class CheckpointConfigurationTests(unittest.TestCase):
    points = [(13.9667, 121.1167)]

    def _scan(
        self,
        done_keys=(),
        *,
        mode="full",
        api="legacy",
        radius=850,
        grid_step=0.005,
        test_config=None,
        complete=True,
        cancelled=False,
    ):
        enabled = test_config is not None
        with patch.object(service, "RUN_DETECTION_NEARBY_API", api), \
                patch.object(service, "_detection_radius_m", return_value=radius), \
                patch.object(
                    quota_settings,
                    "cap",
                    side_effect=lambda key: (
                        grid_step
                        if key == "run_detection.grid_step_degrees"
                        else 100
                    ),
                ), \
                patch.object(service, "test_mode") as test_mode, \
                patch.object(
                    service, "_completed_points_this_cycle",
                    return_value=set(done_keys),
                ), \
                patch.object(
                    service, "_detection_work_budget_reached",
                    return_value=False,
                ), \
                patch.object(
                    service, "_fetch_point_results_for_mode",
                    return_value=([], complete),
                ) as fetch, \
                patch.object(service, "_mark_point_done") as mark, \
                patch.object(
                    service, "is_cancelled", return_value=cancelled
                ):
            test_mode.is_enabled.return_value = enabled
            test_mode.get_config.return_value = test_config or {}
            service._places_run_state.work_budget_exhausted = False
            service._places_run_state.work_budget_reason = None
            state = {
                "total_points": 0,
                "skipped_points": 0,
                "done_keys": [],
                "incomplete_points": 0,
                "outside": 0,
                "work_budget_stop": False,
                "api_error_stop": False,
            }
            service._scan_grid(
                lambda *_: None,
                None,
                state,
                detection_mode=mode,
                points=self.points,
            )
        return state, fetch, mark

    def test_same_configuration_resumes_and_skips_completed_points(self):
        first, _, _ = self._scan()
        resumed, fetch, mark = self._scan(first["done_keys"])
        self.assertEqual(resumed["skipped_points"], 1)
        fetch.assert_not_called()
        mark.assert_not_called()

    def test_method_radius_spacing_and_mode_changes_invalidate_checkpoints(self):
        original, *_ = self._scan(api="legacy", radius=850, grid_step=0.005)
        variants = (
            {"api": "new", "radius": 850, "grid_step": 0.005, "mode": "full"},
            {"api": "legacy", "radius": 900, "grid_step": 0.005, "mode": "full"},
            {"api": "legacy", "radius": 850, "grid_step": 0.006, "mode": "full"},
            {"api": "legacy", "radius": 850, "grid_step": 0.005, "mode": "quick"},
        )
        for variant in variants:
            with self.subTest(variant=variant):
                state, fetch, _ = self._scan(
                    original["done_keys"], **variant
                )
                self.assertEqual(state["skipped_points"], 0)
                fetch.assert_called_once()

    def test_test_mode_checkpoints_do_not_resume_normal_scan(self):
        test_config = {
            "test_mode.enabled": True,
            "test_mode.max_requests": 20,
            "test_mode.grid_step_degrees": 0.009,
            "test_mode.radius_m": 850,
            "test_mode.max_grid_points": 6,
            "test_mode.fixture_policy": "cache_only",
            "test_mode.fixture_ttl_days": 14,
            "test_mode.fixture_storage_enabled": False,
            "test_mode.fixture_storage_approved": False,
        }
        test_run, _, _ = self._scan(test_config=test_config)
        normal_run, fetch, _ = self._scan(test_run["done_keys"])
        self.assertEqual(normal_run["skipped_points"], 0)
        fetch.assert_called_once()

    def test_legacy_format_checkpoint_is_not_reused(self):
        old_key = {f"{self.points[0][0]:.5f},{self.points[0][1]:.5f}"}
        state, fetch, mark = self._scan(old_key)
        self.assertEqual(state["skipped_points"], 0)
        fetch.assert_called_once()
        self.assertTrue(state["done_keys"][0].startswith("v2:"))
        mark.assert_called_once_with(state["done_keys"][0])

    def test_increasing_test_request_budget_preserves_geographic_progress(self):
        config = {
            "test_mode.enabled": True, "test_mode.max_requests": 5,
            "test_mode.grid_step_degrees": 0.009, "test_mode.radius_m": 850,
            "test_mode.max_grid_points": 24,
        }
        first, _, _ = self._scan(test_config=config)
        resumed, fetch, _ = self._scan(first["done_keys"], test_config={
            **config, "test_mode.max_requests": 24,
        })
        self.assertEqual(resumed["skipped_points"], 1)
        fetch.assert_not_called()

    def test_incomplete_and_cancelled_points_remain_retryable(self):
        incomplete, _, mark = self._scan(complete=False)
        self.assertEqual(incomplete["done_keys"], [])
        self.assertEqual(incomplete["incomplete_points"], 1)
        mark.assert_not_called()

        cancelled, fetch_cancelled, mark_cancelled = self._scan(
            cancelled=True
        )
        self.assertEqual(cancelled["done_keys"], [])
        fetch_cancelled.assert_not_called()
        mark_cancelled.assert_not_called()

        retried, fetch_retry, mark_retry = self._scan()
        self.assertEqual(len(retried["done_keys"]), 1)
        fetch_retry.assert_called_once()
        mark_retry.assert_called_once()


if __name__ == "__main__":
    unittest.main()
