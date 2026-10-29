"""Progressive reads must share the full pipeline, not multiply expensive SQL."""
import threading
import time
from concurrent.futures import Future
from datetime import datetime, timezone
from contextlib import ExitStack
from unittest import TestCase
from unittest.mock import MagicMock, patch

from flask import Blueprint, Flask
from api.analytics import routes
from api.analytics.filters import parse_analytics_filters


class AnalyticsSectionTests(TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.stack = self.enterContext(ExitStack())
        for name in ("_analytics_cache", "_analytics_sections", "_analytics_failures", "_analytics_refreshes"):
            self.stack.enter_context(patch.object(routes, name, {}))
        self.stack.enter_context(patch.object(routes, "_analytics_background_slot", threading.BoundedSemaphore(1)))
        self.filters = parse_analytics_filters({})

    def get(self, section):
        with self.app.app_context():
            return routes._get_analytics_section(self.filters, section)

    def test_descriptive_is_available_while_rankings_are_blocked_and_requests_coalesce(self):
        published, release = threading.Event(), threading.Event()
        pending_threads = []
        thread_class = threading.Thread

        def launch(**kwargs):
            thread = thread_class(**kwargs)
            pending_threads.append(thread)
            return thread

        def compute(_filters):
            routes._publish_analytics_section("descriptive", {"kpis": {"active_count": 17}})
            published.set()
            self.assertTrue(release.wait(3))
            return {"descriptive": {"kpis": {"active_count": 17}}, "prescriptive": {"rankings": []}}, 200

        with patch.object(routes, "_get_all_analytics_inner", side_effect=compute) as inner, \
                patch.object(routes.threading, "Thread", side_effect=launch):
            try:
                self.assertIn(self.get("descriptive")[1], (200, 202))
                self.assertTrue(published.wait(3))
                for _ in range(8):
                    self.assertEqual(self.get("descriptive")[0]["descriptive"]["kpis"]["active_count"], 17)
                    self.assertEqual(self.get("prescriptive")[1], 202)
                self.assertFalse(routes._analytics_cache)
                inner.assert_called_once()
                self.assertEqual(len(pending_threads), 1)
            finally:
                release.set()
                for thread in pending_threads:
                    thread.join(3)
        self.assertEqual(self.get("prescriptive")[1], 200)

    def test_generation_invalidation_rejects_late_section_publication(self):
        with self.app.app_context():
            from flask import g
            key = routes._analytics_cache_key(self.filters)
            g._analytics_section_context = (key, routes._analytics_cache_generation)
            routes.invalidate_analytics_cache()
            routes._publish_analytics_section("descriptive", {"kpis": {"active_count": 99}})
        self.assertEqual(routes._analytics_sections, {})

    def test_real_pipeline_publishes_registry_summary_before_map_reconciliation(self):
        """Publish registry aggregates before the slower map-location count."""
        cursor = MagicMock()
        cursor.fetchone.return_value = {"n": 7, "reporting_year": 2031}
        mysql = MagicMock()
        mysql.connection.cursor.return_value = cursor
        labels = []

        class StopAfterKpis(Exception):
            pass

        def execute(cur, label, sql, params):
            if label == "kpi.total_flagged":
                key = routes._analytics_cache_key(self.filters)
                summary = routes._analytics_sections[key]["summary"]["data"]["summary"]
                kpis = summary["kpis"]
                self.assertEqual(kpis["total_businesses"], 7)
                self.assertEqual(kpis["compliance_rate"], 100)
                self.assertEqual(kpis["reporting_year"], 2031)
                self.assertNotIn("total_flagged", kpis)
            if label == "descriptive.enforcement_progress":
                key = routes._analytics_cache_key(self.filters)
                summary = routes._analytics_sections[key]["summary"]["data"]["summary"]
                self.assertEqual(summary["kpis"]["total_businesses"], 7)
                self.assertEqual(summary["kpis"]["compliance_rate"], 100)
                self.assertEqual(summary["kpis"]["total_flagged"], 7)
                self.assertEqual(summary["kpis"]["reporting_year"], 2031)
                raise StopAfterKpis()
            labels.append(label)
            cur.execute(sql, params)

        with self.app.app_context():
            from flask import g
            g._analytics_section_context = (routes._analytics_cache_key(self.filters), routes._analytics_cache_generation)
            with patch.object(routes, "mysql", mysql), \
                    patch.object(routes, "_registry_has_registration_type", return_value=True), \
                    patch.object(routes, "ladder_columns_available", return_value=False), \
                    patch.object(routes, "get_wlc_config", return_value={}), \
                    patch.object(routes, "_execute", side_effect=execute):
                with self.assertRaises(StopAfterKpis):
                    routes._get_all_analytics_inner(self.filters)
        self.assertEqual(len(labels), 11)
        self.assertTrue(all(label.startswith("kpi.") for label in labels))
        self.assertEqual(len(labels), len(set(labels)), "no duplicated KPI queries")

    def test_summary_and_full_read_share_one_flight_and_projection(self):
        published, release = threading.Event(), threading.Event()
        threads = []
        thread_class = threading.Thread
        kpis = {"total_businesses": 17, "total_flagged": 3}

        def launch(**kwargs):
            thread = thread_class(**kwargs)
            threads.append(thread)
            return thread

        def compute(_filters):
            routes._publish_analytics_section("summary", {"kpis": kpis})
            published.set()
            self.assertTrue(release.wait(3))
            return {"descriptive": {"kpis": kpis}, "prescriptive": {"rankings": []}}, 200

        with patch.object(routes, "_get_all_analytics_inner", side_effect=compute) as inner, \
                patch.object(routes.threading, "Thread", side_effect=launch):
            try:
                self.get("summary")
                self.assertTrue(published.wait(3))
                for _ in range(5):
                    self.assertEqual(self.get("summary")[0]["summary"]["kpis"], kpis)
                    self.assertEqual(self.get("prescriptive")[1], 202)
                    self.assertEqual(self.get("descriptive")[1], 202)
                inner.assert_called_once()
            finally:
                release.set()
                for thread in threads:
                    thread.join(3)
        with self.app.app_context():
            full, status = routes._get_cached_analytics(self.filters)
        self.assertEqual(status, 200)
        self.assertEqual(full["descriptive"]["kpis"], self.get("summary")[0]["summary"]["kpis"])

    def test_summary_rollover_is_user_scoped_without_mutating_cached_metrics(self):
        key = routes._analytics_cache_key(self.filters)
        cached = {"kpis": {"total_businesses": 17}}
        routes._analytics_sections[key] = {"summary": {
            "data": {"summary": cached}, "status_code": 200, "ts": time.time(),
        }}
        for notification in (None, {"detected": True, "notification_id": 42}):
            with self.app.test_request_context("/api/analytics/all?section=summary"), \
                    patch.object(routes, "_new_year_rollover_info", return_value=notification):
                response, status = routes.get_all_analytics.__wrapped__()
                self.assertEqual(status, 200)
                self.assertEqual(response.get_json()["summary"]["new_year_rollover"], notification)
                self.assertNotIn("new_year_rollover", cached)

    def test_summary_invalidation_removes_cached_counts_and_rejects_late_results(self):
        key = routes._analytics_cache_key(self.filters)
        with self.app.app_context():
            from flask import g
            g._analytics_section_context = (key, routes._analytics_cache_generation)
            routes._publish_analytics_section("summary", {"kpis": {"total_businesses": 17}})
            self.assertIn("summary", routes._analytics_sections[key])
            routes.invalidate_analytics_cache()
            routes._publish_analytics_section("summary", {"kpis": {"total_businesses": 99}})
        self.assertNotIn(key, routes._analytics_sections)

    def test_summary_deadline_is_not_extended_by_slow_rankings_finishing(self):
        key = routes._analytics_cache_key(self.filters)
        flight = (Future(), routes._analytics_cache_generation)
        computed_at = datetime.fromtimestamp(time.time() - 901, timezone.utc).isoformat()
        routes._analytics_sections[key] = {"summary": {
            "data": {"summary": {"kpis": {"total_businesses": 17}}}, "status_code": 200,
            "ts": time.time() - 901, "computed_at": computed_at, "flight": flight,
        }}
        routes._finish_analytics_refresh(key, flight, {
            "data": {"descriptive": {"kpis": {"total_businesses": 17}}}, "status_code": 200, "ts": time.time(),
        })
        entry = routes._analytics_sections[key]["summary"]
        self.assertEqual(entry["computed_at"], computed_at)
        self.assertTrue(routes._analytics_snapshot_metadata(entry)["expired"])

    def test_finishing_other_sections_cannot_extend_an_earlier_sections_display_deadline(self):
        key = routes._analytics_cache_key(self.filters)
        flight = (Future(), routes._analytics_cache_generation)
        computed_at = datetime.fromtimestamp(time.time() - 901, timezone.utc).isoformat()
        routes._analytics_sections[key] = {"descriptive": {
            "data": {"descriptive": {"kpis": {}}}, "status_code": 200,
            "ts": time.time() - 901, "computed_at": computed_at, "flight": flight,
        }}
        routes._finish_analytics_refresh(key, flight, {
            "data": {"descriptive": {"kpis": {}}}, "status_code": 200, "ts": time.time(),
        })
        entry = routes._analytics_sections[key]["descriptive"]
        self.assertEqual(entry["computed_at"], computed_at)
        self.assertTrue(routes._analytics_snapshot_metadata(entry)["expired"])

    def test_cache_timestamp_rounding_does_not_spuriously_expire_an_immediate_read(self):
        with patch.object(routes.time, "time", return_value=1.0000008):
            metadata = routes._analytics_snapshot_metadata({"data": {}, "ts": 1.0000008})
        self.assertEqual(metadata["age_seconds"], 0)
        self.assertFalse(metadata["expired"])

    def test_failed_cold_refresh_returns_retryable_error_and_honors_backoff(self):
        class InlineThread:
            def __init__(self, *, target, args, **_kwargs):
                self.target, self.args = target, args
            def start(self):
                self.target(*self.args)

        with patch.object(routes, "_get_all_analytics_inner", side_effect=RuntimeError("mock DB unavailable")) as inner, \
                patch.object(routes.threading, "Thread", InlineThread):
            self.assertEqual(self.get("diagnostic")[1], 503)
            data, status = self.get("diagnostic")
            self.assertEqual(status, 503)
            self.assertTrue(data["analytics_cache"]["refresh_failed"])
            inner.assert_called_once()

    def test_mutations_invalidate_but_reads_searches_and_rejected_writes_do_not(self):
        for name in ("registry", "flags", "analytics"):
            blueprint = Blueprint(name, __name__)
            blueprint.add_url_rule("/write", "write", lambda: ({"ok": True}, 200), methods=["GET", "POST"])
            blueprint.add_url_rule("/rejected", "rejected", lambda: ({"error": "rejected"}, 400), methods=["POST"])
            blueprint.add_url_rule("/location-search", "search", lambda: ({"results": []}, 200), methods=["POST"])
            blueprint.add_url_rule("/run-detection", "scan", lambda: ({"status": "partial"}, 429), methods=["POST"])
            blueprint.add_url_rule("/wlc-config", "config", lambda: ({"ok": True}, 200), methods=["POST"])
            blueprint.add_url_rule("/sector-policy", "sector_policy", lambda: ({"ok": True}, 200), methods=["PUT"])
            blueprint.add_url_rule("/sector-policy/reset", "sector_policy_reset", lambda: ({"ok": True}, 200), methods=["POST"])
            self.app.register_blueprint(blueprint, url_prefix=f"/api/{name}")
        routes.init_analytics_cache_invalidation(self.app)
        client = self.app.test_client()
        for path, method, invalidates in (
            ("/api/registry/write", "GET", False),
            ("/api/registry/rejected", "POST", False),
            ("/api/flags/location-search", "POST", False),
            ("/api/analytics/write", "POST", False),
            ("/api/registry/write", "POST", True),
            ("/api/flags/run-detection", "POST", True),
            ("/api/analytics/wlc-config", "POST", True),
            ("/api/analytics/sector-policy", "PUT", True),
            ("/api/analytics/sector-policy/reset", "POST", True),
        ):
            with self.subTest(path=path, method=method):
                routes._analytics_cache["fixture"] = {"data": {}}
                routes._analytics_sections["fixture"] = {}
                client.open(path, method=method)
                self.assertEqual("fixture" not in routes._analytics_cache, invalidates)
