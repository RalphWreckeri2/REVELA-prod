"""Paid request accounting and planning tests; all HTTP and database calls isolated."""
from contextlib import ExitStack
import time
from unittest import TestCase
from unittest.mock import MagicMock, patch

from api.flags import service
from api.flags.scan_budget import estimate_requests
from api.utils import quota_settings
from scripts.configure_quick_discovery_budget import quick_discovery_patch


class ScanBudgetTests(TestCase):
    def setUp(self):
        self.stack = self.enterContext(ExitStack())
        self.stack.enter_context(patch.dict(service._places_run_state.__dict__, {}, clear=True))
        self.database = self.stack.enter_context(patch.object(service, "mysql", MagicMock()))
        self.stack.enter_context(patch.object(service, "_ensure_budget_tables"))
        self.stack.enter_context(patch.object(service.test_mode, "is_enabled", return_value=False))
        self.stack.enter_context(patch.object(service, "RUN_DETECTION_NEARBY_API", "legacy"))
        self.stack.enter_context(patch.object(service, "get_detection_quota_info", return_value={
            "is_limit_reached": False, "monthly_limit": 5, "remaining_this_month": 5,
        }))
        self.used = {"month": 0, "day": 0}
        self.stack.enter_context(patch.object(service, "read_usage", side_effect=lambda *_args: dict(self.used)))
        self.caps = {key: spec["baseline"] for key, spec in quota_settings.QUOTA_FIELDS.items()}
        self.stack.enter_context(patch.object(quota_settings, "cap", side_effect=lambda key: self.caps[key]))
        self.points = [(13.96 + i * 0.0001, 121.11) for i in range(24)]
        self.done = set()
        self.stack.enter_context(patch.object(service, "_completed_points_this_cycle", side_effect=lambda: set(self.done)))
        service._places_run_state.cycle_id = None
        self.addCleanup(setattr, service._places_run_state, "cycle_id", None)

    def preflight(self, mode="quick"):
        return service.get_detection_preflight(mode, points=self.points)

    def test_supported_scope_bounds_include_pages_children_and_new_rpm_retries(self):
        self.assertEqual(estimate_requests("quick", "legacy", 24)["maximum_requests"], 24)
        self.assertEqual(estimate_requests("quick", "new", 24)["maximum_requests"], 96)
        self.assertEqual(estimate_requests("full", "legacy", 38)["maximum_requests"], 1482)
        self.assertEqual(estimate_requests("full", "new", 38)["maximum_requests"], 1976)
        self.assertEqual(estimate_requests("full", "legacy", 38)["minimum_requests"], 38)

    def test_five_request_cap_is_rejected_before_any_http_request_or_run_record(self):
        self.caps["run_detection.max_requests"] = 5
        self.database.connection.cursor.return_value.fetchone.return_value = {"total": 12}
        with patch.object(service, "_scan_plan", return_value=(None, self.points)), \
                patch.object(service.http, "get") as get, \
                patch.object(service.http, "post") as post, \
                patch.object(service, "create_detection_run") as create:
            result, error = service.run_detection(mode="quick")
        self.assertEqual(result["status"], "preflight_blocked")
        self.assertIn("per-scan request cap is 5", error)
        self.assertEqual(result["preflight"]["required_remaining_allowance"], 24)
        get.assert_not_called()
        post.assert_not_called()
        create.assert_not_called()

    def test_daily_remaining_not_nominal_cap_is_checked_and_text_search_cannot_subsidize_it(self):
        self.used["day"] = 97  # only 23 of 120 requests remain
        self.caps["quota.text_search.daily"] = 500
        result = self.preflight()
        self.assertFalse(result["can_start"])
        self.assertTrue(any("23 requests remaining" in message for message in result["blockers"]))
        self.used["day"] = 96
        self.assertTrue(self.preflight()["can_start"])

    def test_monthly_request_usage_blocks_even_though_five_completed_scans_remain(self):
        self.used["month"] = 1980
        plan = self.preflight()
        self.assertEqual(plan["remaining_this_month"], 5)
        self.assertFalse(plan["can_start"])
        self.assertEqual(plan["monthly_remaining"], 20)

    def test_resume_estimate_only_charges_remaining_centers(self):
        fingerprint = service._checkpoint_configuration_fingerprint("quick")
        self.done.update(service._checkpoint_point_key(*point, fingerprint) for point in self.points[:19])
        self.caps["run_detection.max_requests"] = 5
        plan = self.preflight()
        self.assertEqual(plan["saved_points"], 19)
        self.assertEqual(plan["required_remaining_allowance"], 5)
        self.assertTrue(plan["can_start"])

    def test_full_coverage_is_explicitly_a_slice_not_a_funded_complete_run(self):
        plan = self.preflight("full")
        self.assertTrue(plan["can_start"])
        self.assertEqual(plan["required_remaining_allowance"], 24)
        self.assertEqual(plan["planned_requests"], 120)
        self.assertFalse(plan["budget_covers_complete_run"])

    def test_full_slice_uses_headroom_left_after_a_quick_scan_without_raising_daily_cap(self):
        self.used["day"] = 24
        plan = self.preflight("full")
        self.assertTrue(plan["can_start"])
        self.assertEqual(plan["planned_requests"], 96)
        self.assertEqual(plan["daily_cap"], 120)

    def test_test_mode_effective_request_cap_is_reported_and_enforced(self):
        with patch.object(service.test_mode, "is_enabled", return_value=True), \
                patch.object(service.test_mode, "get_config", return_value={
                    "test_mode.max_requests": 5, "test_mode.enabled": True,
                    "test_mode.grid_step_degrees": 0.009, "test_mode.radius_m": 850,
                    "test_mode.fixture_policy": "cache_then_live",
                }):
            plan = self.preflight()
        self.assertEqual(plan["work_slice_requests"], 5)
        self.assertFalse(plan["can_start"])

    def test_legacy_three_page_bound_matches_estimator_without_unbounded_tokens(self):
        service._places_run_state.mode = "full"
        response = MagicMock()
        response.json.return_value = {"status": "OK", "results": [], "next_page_token": "mock-next"}
        with patch.dict("os.environ", {"GOOGLE_MAPS_API_KEY": "mock-key"}), \
                patch.object(service, "_detection_work_budget_reached", return_value=False), \
                patch.object(service, "_places_get", return_value=response) as send, \
                patch.object(service.time, "sleep"):
            service._fetch_legacy_point_results_once(13.96, 121.11, 850)
        self.assertEqual(send.call_count, 3)

    def test_historical_nine_points_can_include_four_saved_plus_five_paid_requests(self):
        fingerprint = service._checkpoint_configuration_fingerprint("quick")
        self.done.update(service._checkpoint_point_key(*point, fingerprint) for point in self.points[:4])
        paid = 0

        def fetch(*_args):
            nonlocal paid
            paid += 1
            return [], True

        state = {"done_keys": [], "skipped_points": 0, "incomplete_points": 0, "outside": 0}
        with patch.object(service, "is_cancelled", return_value=False), \
                patch.object(service, "_detection_work_budget_reached", side_effect=lambda: paid >= 5), \
                patch.object(service, "_fetch_point_results_for_mode", side_effect=fetch), \
                patch.object(service, "_mark_point_done"):
            service._scan_grid(lambda _places: True, None, state, "quick", self.points)
        self.assertEqual(state["saved_points"], 4)
        self.assertEqual(state["attempted_this_run"], 5)
        self.assertEqual(state["skipped_points"] + len(state["done_keys"]), 9)
        self.assertEqual(paid, 5)

    def test_complete_quick_scope_consumes_exactly_twenty_four_legacy_requests(self):
        service._places_run_state.mode = "quick"
        service._places_run_state.calls = {"legacy_nearby": 0, "legacy_nearby_initial": 0}
        service._places_run_state.started_at = None
        service._places_run_state.cycle_id = None
        response = MagicMock()
        response.json.return_value = {"status": "ZERO_RESULTS", "results": []}
        state = {"done_keys": [], "skipped_points": 0, "incomplete_points": 0, "outside": 0}
        with patch.dict("os.environ", {"GOOGLE_MAPS_API_KEY": "mock-key"}), \
                patch.object(service, "_reserve_places_call") as reserve, \
                patch.object(service, "is_cancelled", return_value=False), \
                patch.object(service.http, "get", return_value=response) as get, \
                patch.object(service.LEGACY_NEARBY_LIMITER, "acquire", return_value=0), \
                patch.object(service, "_mark_point_done"):
            service._scan_grid(lambda _places: True, None, state, "quick", self.points)
        self.assertEqual(len(state["done_keys"]), 24)
        self.assertEqual(get.call_count, 24)
        self.assertEqual(reserve.call_count, 24)
        self.assertEqual(service._places_run_state.calls["legacy_nearby"], 24)

    def test_saturated_full_legacy_point_uses_at_most_thirty_nine_requests(self):
        service._places_run_state.mode = "full"
        response = MagicMock()
        response.json.return_value = {"status": "OK", "results": [
            {"place_id": f"mock-{i}"} for i in range(20)
        ], "next_page_token": "mock-next"}
        with patch.dict("os.environ", {"GOOGLE_MAPS_API_KEY": "mock-key"}), \
                patch.object(service, "_detection_work_budget_reached", return_value=False), \
                patch.object(service, "_nearby_circle_intersects_municipality", return_value=True), \
                patch.object(service, "_places_get", return_value=response) as send, \
                patch.object(service.time, "sleep"):
            _results, complete = service._fetch_point_results(13.96, 121.11, 850)
        self.assertFalse(complete)  # bounded traversal, not a promise of exhaustive POIs
        self.assertEqual(send.call_count, 39)  # (1 root + 12 children) * 3 pages

    def test_new_rpm_retry_exhaustion_counts_four_attempts_and_reports_google_not_daily_app_cap(self):
        service._places_run_state.calls = {"new_nearby": 0, "new_nearby_initial": 0}
        service._places_run_state.query_kind = "initial"
        service._places_run_state.started_at = None
        response = MagicMock(status_code=429, text="RESOURCE_EXHAUSTED requests per minute")
        self.caps["quota.nearby_new.daily"] = 100
        self.caps["quota.nearby_new.monthly"] = 1000
        with patch.dict("os.environ", {"GOOGLE_MAPS_API_KEY": "mock-key"}), \
                patch.object(service, "reserve_usage_slot", return_value=(True, None)) as reserve, \
                patch.object(service.http, "post", return_value=response) as post, \
                patch.object(service.time, "sleep"):
            with self.assertRaises(service.PlacesBudgetExceeded) as raised:
                service._new_nearby_request(13.96, 121.11, 850)
        self.assertEqual(raised.exception.source, "google")
        self.assertIn("per-minute", str(raised.exception))
        self.assertEqual(post.call_count, 4)
        self.assertEqual(reserve.call_count, 4)
        self.assertEqual(service._places_run_state.calls["new_nearby"], 4)

    def test_last_point_interrupted_during_pagination_is_partial_not_a_terminal_coverage_gap(self):
        self.caps["run_detection.max_requests"] = 1
        service._places_run_state.mode = "full"
        service._places_run_state.started_at = time.monotonic()
        service._places_run_state.calls = {"legacy_nearby": 0}
        service._places_run_state.work_budget_exhausted = False
        response = MagicMock(status_code=200)
        response.json.return_value = {"status": "OK", "results": [], "next_page_token": "next"}

        def send(*_args, **_kwargs):
            service._places_run_state.calls["legacy_nearby"] += 1
            return response

        state = {"done_keys": [], "skipped_points": 0, "incomplete_points": 0, "outside": 0}
        with patch.dict("os.environ", {"GOOGLE_MAPS_API_KEY": "mock-key"}), \
                patch.object(service, "is_cancelled", return_value=False), \
                patch.object(service, "_places_get", side_effect=send) as get, \
                patch.object(service, "_mark_point_done") as mark, \
                patch.object(service.time, "sleep"):
            service._scan_grid(lambda _places: True, None, state, "full", self.points[:1])
        self.assertEqual(get.call_count, 1)
        self.assertTrue(state["work_budget_stop"])
        self.assertFalse(service._grid_scan_has_terminal_gaps(state))
        mark.assert_not_called()

    def test_safe_configuration_repair_only_changes_the_too_small_execution_cap(self):
        self.caps["run_detection.max_requests"] = 5
        plan = self.preflight()
        self.assertEqual(quick_discovery_patch(plan), {"run_detection.max_requests": 24})
        self.assertEqual(quick_discovery_patch(plan, full_slices=True), {"run_detection.max_requests": 39})
        plan["daily_cap"] = 23
        with self.assertRaisesRegex(ValueError, "Existing method budgets"):
            quick_discovery_patch(plan)

    def test_bounded_dense_cell_gap_is_saved_and_skipped_on_the_next_full_slice(self):
        self.caps["run_detection.max_requests"] = 39
        points = self.points[:2]
        saturated = MagicMock(status_code=200)
        saturated.json.return_value = {"status": "OK", "next_page_token": "next", "results": [
            {"place_id": f"synthetic-{i}"} for i in range(20)
        ]}
        empty = MagicMock(status_code=200)
        empty.json.return_value = {"status": "ZERO_RESULTS", "results": []}
        dense = True
        total_requests = 0

        def send(*_args, **_kwargs):
            nonlocal total_requests
            total_requests += 1
            service._places_run_state.calls["legacy_nearby"] += 1
            return saturated if dense else empty

        def reset():
            service._places_run_state.mode = "full"
            service._places_run_state.started_at = time.monotonic()
            service._places_run_state.calls = {"legacy_nearby": 0}
            service._places_run_state.work_budget_exhausted = False
            service._places_run_state.request_budget = None
            service._places_run_state.api_errors = 0
            return {"done_keys": [], "skipped_points": 0, "incomplete_points": 0, "outside": 0}

        with patch.dict("os.environ", {"GOOGLE_MAPS_API_KEY": "mock-key"}), \
                patch.object(service, "is_cancelled", return_value=False), \
                patch.object(service, "_mark_point_done", side_effect=self.done.add), \
                patch.object(service, "_nearby_circle_intersects_municipality", return_value=True), \
                patch.object(service, "_places_get", side_effect=send), \
                patch.object(service.time, "sleep"):
            first = reset()
            service._scan_grid(lambda _places: True, None, first, "full", points)
            self.assertEqual(total_requests, 39)
            self.assertEqual(len(first["gap_keys"]), 1)
            self.assertFalse(service._grid_scan_has_terminal_gaps(first))
            dense = False
            resumed = reset()
            service._scan_grid(lambda _places: True, None, resumed, "full", points)
        self.assertEqual(total_requests, 40)  # no repeat of the 39 completed searches
        self.assertEqual(resumed["saved_gap_points"], 1)
        self.assertEqual(resumed["attempted_this_run"], 1)
        self.assertTrue(service._grid_scan_has_terminal_gaps(resumed))

    def test_funding_validation_uses_selected_method_not_an_enabled_inactive_method(self):
        self.caps["quota.nearby_new.daily"] = 100
        self.caps["quota.nearby_new.monthly"] = 0
        with patch.object(quota_settings, "BASELINE_API_MODE", "legacy"):
            _clean, errors = quota_settings.validate_patch({"run_detection.max_requests": 24})
        self.assertEqual(errors, [])
