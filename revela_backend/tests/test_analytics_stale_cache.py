"""Only cache policy/concurrency; the pipeline and all database access are mocked."""
import os
import sys
import threading
import unittest
from concurrent.futures import Future
from contextlib import ExitStack
from datetime import datetime, timezone
from threading import Event, Thread
from unittest.mock import MagicMock, PropertyMock, patch

from flask import Flask, g, has_request_context

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from api.analytics import routes  # noqa: E402
from api.analytics.filters import parse_analytics_filters  # noqa: E402


class AnalyticsStaleCacheTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.now = datetime(2026, 10, 19, 1, 30, tzinfo=timezone.utc).timestamp()
        stack = self.enterContext(ExitStack())
        for name, value in (
            ("_analytics_cache", {}), ("_analytics_refreshes", {}),
            ("_analytics_cache_generation", 0), ("_analytics_inflight", 0),
            ("_analytics_metrics", {"hits": 0, "misses": 0}),
            ("_analytics_background_slot", threading.BoundedSemaphore(1)),
        ):
            stack.enter_context(patch.object(routes, name, value))
        stack.enter_context(patch.object(routes.time, "time", side_effect=lambda: self.now))
        stack.enter_context(patch.object(routes, "_phases_enabled", return_value=False))
        stack.enter_context(patch.object(routes._analytics_log, "exception"))
        self.inner = stack.enter_context(patch.object(
            routes, "_get_all_analytics_inner", side_effect=lambda _F: (self.payload(2), 200)))
        self.pending = []

    def payload(self, value, age=0):
        return {"prescriptive": {
            "rankings": [{"barangayID": value}],
            "rankings_computed_at": datetime.fromtimestamp(self.now - age, timezone.utc).isoformat(),
        }}

    def seed(self, raw=None, *, value=1, computed_age=60, cache_age=61):
        F = parse_analytics_filters(raw or {})
        key = routes._analytics_cache_key(F)
        entry = {"data": self.payload(value, computed_age),
                 "ts": self.now - cache_age, "status_code": 200}
        routes._analytics_cache[key] = entry
        return key, entry

    def get(self, raw=None, *, stale=True):
        with self.app.app_context():
            return routes._get_cached_analytics(
                parse_analytics_filters(raw or {}), allow_stale=stale)

    def defer(self):
        pending = self.pending

        class DeferredThread:
            def __init__(self, *, target, args, daemon):
                self.target, self.args = target, args

            def start(self):
                pending.append(self)

            def run(self):
                self.target(*self.args)

        return patch.object(routes.threading, "Thread", DeferredThread)

    def test_fresh_snapshot_is_returned_without_query_or_timestamp_reset(self):
        key, entry = self.seed(cache_age=1)
        data, status = self.get()
        self.assertEqual(status, 200)
        self.assertEqual(data["analytics_cache"]["age_seconds"], 60)
        self.assertEqual(data["analytics_cache"]["computed_at"],
                         entry["data"]["prescriptive"]["rankings_computed_at"])
        self.assertFalse(data["analytics_cache"]["expired"])
        self.assertNotIn("analytics_cache", routes._analytics_cache[key]["data"])
        self.inner.assert_not_called()

    def test_stale_within_limit_returns_immediately_and_single_flights(self):
        self.seed({"flag_color": "Red"}, computed_age=899)
        with self.defer():
            for _ in range(8):
                data, status = self.get({"flag_color": "Red"})
                self.assertEqual(status, 200)
                self.assertTrue(data["analytics_cache"]["refreshing"])
                self.assertEqual(data["prescriptive"]["rankings"], [{"barangayID": 1}])
            self.assertEqual(len(self.pending), 1)
            self.inner.assert_not_called()
            self.pending[0].run()
        data, status = self.get({"flag_color": "Red"})
        self.assertEqual(status, 200)
        self.assertEqual(data["analytics_cache"]["age_seconds"], 0)
        self.assertEqual(data["prescriptive"]["rankings"], [{"barangayID": 2}])
        self.inner.assert_called_once()

    def test_exactly_fifteen_minutes_is_allowed_but_one_second_later_is_hidden(self):
        self.seed(computed_age=900)
        with self.defer():
            data, status = self.get()
            self.assertEqual(status, 200)
            self.assertEqual(data["analytics_cache"]["age_seconds"], 900)
            self.assertEqual(data["analytics_cache"]["max_stale_seconds"], 900)
            self.now += 1
            data, status = self.get()
        self.assertEqual(status, 503)
        self.assertTrue(data["analytics_cache"]["expired"])
        self.assertIn("15 minutes", data["error"])
        self.assertEqual(set(data), {"error", "analytics_cache"})
        self.assertEqual(len(self.pending), 1)

    def test_recent_cache_write_cannot_extend_old_computed_at(self):
        _, entry = self.seed(computed_age=901, cache_age=0)
        with self.defer():
            data, status = self.get()
        self.assertEqual(status, 503)
        self.assertTrue(data["analytics_cache"]["expired"])
        self.assertEqual(data["analytics_cache"]["computed_at"],
                         entry["data"]["prescriptive"]["rankings_computed_at"])
        self.assertNotIn("prescriptive", data)
        self.assertEqual(len(self.pending), 1)

    def test_failure_keeps_snapshot_only_until_original_deadline(self):
        key, original = self.seed(computed_age=899)
        self.inner.side_effect = RuntimeError("fixture refresh failure")
        with self.defer():
            self.get()
            self.pending[0].run()
            data, status = self.get()
            self.assertEqual(status, 200)
            self.assertTrue(data["analytics_cache"]["refresh_failed"])
            self.now += 2
            data, status = self.get()
            self.assertEqual(len(self.pending), 1)  # backoff is still active
        self.assertEqual(status, 503)
        self.assertTrue(data["analytics_cache"]["refresh_failed"])
        self.assertNotIn("prescriptive", data)
        self.assertEqual(routes._analytics_cache[key]["ts"], original["ts"])

    def test_failed_refresh_of_already_expired_snapshot_never_serves_rows(self):
        self.seed(computed_age=1800)
        self.inner.side_effect = RuntimeError("fixture refresh failure")
        with self.defer():
            self.assertEqual(self.get()[1], 503)
            self.pending[0].run()
            for _ in range(3):
                data, status = self.get()
                self.assertEqual(status, 503)
                self.assertNotIn("prescriptive", data)
                self.assertTrue(data["analytics_cache"]["refresh_failed"])
            self.assertEqual(len(self.pending), 1)

    def test_success_after_expiry_restores_visible_results(self):
        self.seed(computed_age=901)
        with self.defer():
            self.assertEqual(self.get()[1], 503)
            self.pending[0].run()
        data, status = self.get()
        self.assertEqual(status, 200)
        self.assertFalse(data["analytics_cache"]["expired"])
        self.assertEqual(data["prescriptive"]["rankings"], [{"barangayID": 2}])

    def test_invalid_naive_or_future_computation_time_fails_closed(self):
        _, entry = self.seed()
        for timestamp in ("invalid", "2026-10-19T01:30:00", "2026-10-19T02:00:00+00:00"):
            with self.subTest(timestamp=timestamp):
                entry["data"]["prescriptive"]["rankings_computed_at"] = timestamp
                self.assertTrue(routes._analytics_snapshot_metadata(entry)["expired"])

    def test_background_work_is_bounded_and_filter_snapshots_are_separate(self):
        self.seed({"flag_color": "Red"}, value=1)
        self.seed({"flag_color": "Green"}, value=3)
        with self.defer():
            red, _ = self.get({"flag_color": "Red"})
            green, _ = self.get({"flag_color": "Green"})
            self.assertEqual(red["prescriptive"]["rankings"], [{"barangayID": 1}])
            self.assertEqual(green["prescriptive"]["rankings"], [{"barangayID": 3}])
            self.assertTrue(green["analytics_cache"]["refresh_deferred"])
            self.assertEqual(len(self.pending), 1)

    def test_cold_concurrent_requests_share_one_pipeline(self):
        entered, release, joined = Event(), Event(), Event()
        future = Future()
        original_result = future.result
        waiting = 0
        lock = threading.Lock()
        results, errors = [], []

        def result():
            nonlocal waiting
            with lock:
                waiting += 1
                if waiting >= 3:
                    joined.set()
            return original_result(timeout=2)

        def compute(_F):
            entered.set()
            self.assertTrue(release.wait(2))
            return self.payload(2), 200

        def request():
            try:
                results.append(self.get())
            except Exception as exc:
                errors.append(exc)

        self.inner.side_effect = compute
        threads = [Thread(target=request) for _ in range(4)]
        with patch.object(routes, "Future", return_value=future), \
                patch.object(future, "result", side_effect=result):
            try:
                threads[0].start()
                self.assertTrue(entered.wait(2))
                for thread in threads[1:]:
                    thread.start()
                self.assertTrue(joined.wait(2))
                self.inner.assert_called_once()
            finally:
                release.set()
                for thread in threads:
                    if thread.ident is not None:
                        thread.join(2)
        self.assertFalse(any(thread.is_alive() for thread in threads))
        self.assertEqual(errors, [])
        self.assertEqual(len(results), 4)
        self.assertEqual(routes._analytics_refreshes, {})

    def test_invalidation_discards_old_flight_and_default_reads_stay_fresh(self):
        key, _ = self.seed()
        with self.defer():
            self.get()
            flight = routes._analytics_refreshes[key]
            routes.invalidate_analytics_cache()
            self.assertIs(routes._analytics_refreshes[key], flight)
            self.pending[0].run()
        self.assertEqual(routes._analytics_cache, {})
        self.assertEqual(self.get(stale=False)[1], 200)
        self.assertEqual(self.inner.call_count, 2)

    def test_thread_start_failure_cleans_up_and_does_not_show_expired_rows(self):
        self.seed(computed_age=901)
        thread = MagicMock()
        thread.start.side_effect = RuntimeError("fixture thread failure")
        with patch.object(routes.threading, "Thread", return_value=thread):
            data, status = self.get()
        self.assertEqual(status, 503)
        self.assertTrue(data["analytics_cache"]["refresh_failed"])
        self.assertNotIn("prescriptive", data)
        self.assertEqual(routes._analytics_refreshes, {})
        self.assertTrue(routes._analytics_background_slot.acquire(blocking=False))
        routes._analytics_background_slot.release()

    def test_background_context_does_not_copy_request_and_is_torn_down(self):
        self.seed()
        contexts = []

        @self.app.teardown_appcontext
        def teardown(_error):
            contexts.append(getattr(g, "worker", False))

        def compute(_F):
            self.assertFalse(has_request_context())
            self.assertFalse(hasattr(g, "request_only"))
            g.worker = True
            return self.payload(2), 200

        self.inner.side_effect = compute
        with self.defer():
            with self.app.test_request_context("/"):
                g.request_only = True
                routes._get_cached_analytics(parse_analytics_filters({}), allow_stale=True)
            self.pending[0].run()
        self.assertIn(True, contexts)

    def test_rollover_stays_per_user_and_option_is_not_a_filter(self):
        key, _ = self.seed(cache_age=1)
        mysql = MagicMock()
        cursor = mysql.connection.cursor.return_value
        cursor.fetchone.side_effect = [None, {"id": 9, "body": "2026 renewal"}]
        results = []
        with patch.object(routes, "mysql", mysql), \
                patch.object(routes, "get_jwt_identity", side_effect=["1", "2"]):
            for _ in range(2):
                with self.app.test_request_context("/api/analytics/all?stale_while_revalidate=1"):
                    response, status = routes.get_all_analytics.__wrapped__()
                    self.assertEqual(status, 200)
                    results.append(response.get_json())
        self.assertIsNone(results[0]["new_year_rollover"])
        self.assertEqual(results[1]["new_year_rollover"]["notification_id"], 9)
        self.assertNotIn("new_year_rollover", routes._analytics_cache[key]["data"])
        self.assertEqual(parse_analytics_filters({}),
                         parse_analytics_filters({"stale_while_revalidate": "1"}))

    def test_factory_schedules_default_before_any_page_without_waiting(self):
        import app as app_module

        with patch.object(app_module.Config, "JWT_SECRET_KEY", "startup-cache-test-secret-32-chars"), \
                patch.object(app_module, "_start_permit_expiry_scheduler"), \
                patch("api.middleware.request_telemetry.init_app"), \
                patch.object(type(app_module.mysql), "connection", new_callable=PropertyMock,
                             side_effect=AssertionError("unexpected database access")), \
                self.defer():
            app = app_module.create_app()
            self.assertEqual(len(self.pending), 1)
            self.inner.assert_not_called()
            self.assertEqual(app.test_client().get("/api/health").status_code, 200)
            self.pending[0].run()
        F = parse_analytics_filters({})
        self.inner.assert_called_once_with(F)
        self.assertIn(routes._analytics_cache_key(F), routes._analytics_cache)
        self.assertNotEqual(routes._analytics_cache_key(F), routes._analytics_cache_key({}))

    def test_startup_warmup_is_single_flight_and_skips_a_fresh_default(self):
        with self.defer():
            self.assertTrue(routes.start_analytics_cache_warmup(self.app))
            self.assertFalse(routes.start_analytics_cache_warmup(self.app))
            self.assertEqual(len(self.pending), 1)
            self.inner.assert_not_called()
            self.pending[0].run()
            self.assertFalse(routes.start_analytics_cache_warmup(self.app))
            self.assertEqual(len(self.pending), 1)
        data, status = self.get()
        self.assertEqual(status, 200)
        self.assertEqual(data["prescriptive"]["rankings"], [{"barangayID": 2}])
        self.inner.assert_called_once()

    def test_page_arriving_during_startup_joins_the_same_computation(self):
        joined = Event()
        results, errors = [], []

        def request():
            try:
                results.append(self.get())
            except Exception as exc:
                errors.append(exc)

        with self.defer():
            routes.start_analytics_cache_warmup(self.app)
            key = routes._analytics_cache_key(parse_analytics_filters({}))
            future = routes._analytics_refreshes[key][0]
            original_result = future.result

            def result():
                joined.set()
                return original_result(timeout=2)

            with patch.object(future, "result", side_effect=result):
                waiter = Thread(target=request)
                try:
                    waiter.start()
                    self.assertTrue(joined.wait(2))
                    self.inner.assert_not_called()
                    self.assertEqual(len(self.pending), 1)
                    self.pending[0].run()
                finally:
                    waiter.join(2)
        self.assertFalse(waiter.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(results[0][1], 200)
        self.inner.assert_called_once()

    def test_request_winning_the_race_prevents_a_second_startup_query(self):
        entered, release = Event(), Event()
        results, errors = [], []

        def compute(_F):
            entered.set()
            self.assertTrue(release.wait(2))
            return self.payload(2), 200

        def request():
            try:
                results.append(self.get())
            except Exception as exc:
                errors.append(exc)

        self.inner.side_effect = compute
        waiter = Thread(target=request)
        try:
            waiter.start()
            self.assertTrue(entered.wait(2))
            self.assertFalse(routes.start_analytics_cache_warmup(self.app))
        finally:
            release.set()
            waiter.join(2)
        self.assertFalse(waiter.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(results[0][1], 200)
        self.inner.assert_called_once()

    def test_failed_startup_refresh_keeps_last_success_but_not_beyond_age_cap(self):
        _, entry = self.seed(computed_age=899)
        computed_at = entry["data"]["prescriptive"]["rankings_computed_at"]
        self.inner.side_effect = RuntimeError("fixture warm-up failure")
        with self.defer():
            self.assertTrue(routes.start_analytics_cache_warmup(self.app))
            data, status = self.get()
            self.assertEqual(status, 200)
            self.assertEqual(data["prescriptive"]["rankings"], [{"barangayID": 1}])
            self.pending[0].run()
            data, status = self.get()
            self.assertEqual(status, 200)
            self.assertEqual(data["analytics_cache"]["computed_at"], computed_at)
            self.assertTrue(data["analytics_cache"]["refresh_failed"])
            self.now += 2
            data, status = self.get()
        self.assertEqual(status, 503)
        self.assertTrue(data["analytics_cache"]["expired"])
        self.assertNotIn("prescriptive", data)

    def test_warmup_does_not_trust_a_recent_write_of_an_expired_snapshot(self):
        self.seed(computed_age=901, cache_age=0)
        with self.defer():
            self.assertTrue(routes.start_analytics_cache_warmup(self.app))
            data, status = self.get()
            self.assertEqual(status, 503)
            self.assertTrue(data["analytics_cache"]["expired"])
            self.assertEqual(len(self.pending), 1)
            self.pending[0].run()
        data, status = self.get()
        self.assertEqual(status, 200)
        self.assertEqual(data["analytics_cache"]["age_seconds"], 0)

    def test_warmup_only_populates_default_and_leaves_filtered_snapshot_alone(self):
        filtered_key, filtered_entry = self.seed({"flag_color": "Green"}, value=3, cache_age=1)
        with self.defer():
            self.assertTrue(routes.start_analytics_cache_warmup(self.app))
            self.pending[0].run()
        default_key = routes._analytics_cache_key(parse_analytics_filters({}))
        self.assertEqual(set(routes._analytics_cache), {default_key, filtered_key})
        self.assertIs(routes._analytics_cache[filtered_key], filtered_entry)
        data, status = self.get({"flag_color": "Green"})
        self.assertEqual(status, 200)
        self.assertEqual(data["prescriptive"]["rankings"], [{"barangayID": 3}])
        self.inner.assert_called_once_with(parse_analytics_filters({}))

    def test_warmup_respects_backoff_and_the_shared_background_slot(self):
        key, entry = self.seed()
        entry["retry_after"] = self.now + 15
        with self.defer():
            self.assertFalse(routes.start_analytics_cache_warmup(self.app))
            self.assertEqual(routes._analytics_refreshes, {})
            self.now += 15
            self.assertTrue(routes._analytics_background_slot.acquire(blocking=False))
            try:
                self.assertFalse(routes.start_analytics_cache_warmup(self.app))
                self.assertNotIn(key, routes._analytics_refreshes)
            finally:
                routes._analytics_background_slot.release()
            self.assertTrue(routes.start_analytics_cache_warmup(self.app))
            self.assertEqual(len(self.pending), 1)
            self.pending[0].run()

    def test_warmup_thread_start_failure_is_nonfatal_and_allows_later_requests(self):
        thread = MagicMock()
        thread.start.side_effect = RuntimeError("fixture warm-up thread failure")
        with patch.object(routes.threading, "Thread", return_value=thread):
            self.assertFalse(routes.start_analytics_cache_warmup(self.app))
        self.assertEqual(routes._analytics_refreshes, {})
        self.assertTrue(routes._analytics_background_slot.acquire(blocking=False))
        routes._analytics_background_slot.release()
        self.inner.assert_not_called()
        self.assertEqual(self.get()[1], 200)
        self.inner.assert_called_once()


if __name__ == "__main__":
    unittest.main()
