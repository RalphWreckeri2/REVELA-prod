"""
Run Detection behaviour under the Legacy Nearby rate limiter.

The limiter (api/utils/places_rate_limit.py) admits ~48 legacy Nearby requests
per minute instead of the ~200 the old 300 ms pacing allowed. That makes runs
stop on the 90-second work slice sooner, so the questions that matter are:

  * is the 90 s / 120-request envelope still exactly what it was?
  * is every completed grid point still checkpointed?
  * does an interrupted scan still resume from its checkpoints, or restart?
  * do the 429 / OVER_QUERY_LIMIT retry paths still fire?

Every Google call in this file is mocked. Nothing here reaches Google, MySQL,
or the real limiter clock.
"""

import unittest
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

from api.flags import service
from api.utils import quota_settings
from api.utils.places_rate_limit import LEGACY_NEARBY_LIMITER, RateLimiter


class FakeClock:
    """Monotonic clock that only advances when the limiter sleeps."""

    def __init__(self):
        self.now = 0.0
        self.sleeps = []

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        if seconds > 0:
            self.sleeps.append(seconds)
            self.now += seconds


def quota_overrides(**values):
    """Point `quota_settings.cap` at in-memory values for one test."""
    original = quota_settings.cap

    def fake_cap(key):
        return values.get(key, original(key))

    return patch.object(quota_settings, "cap", side_effect=fake_cap)


def fresh_run_state():
    service._places_run_state.calls = {
        "legacy_nearby": 0,
        "legacy_nearby_initial": 0,
        "legacy_nearby_adaptive": 0,
        "new_nearby": 0,
        "new_nearby_initial": 0,
        "new_nearby_adaptive": 0,
    }
    service._places_run_state.started_at = None
    service._places_run_state.work_budget_exhausted = False
    service._places_run_state.work_budget_reason = None
    service._places_run_state.api_errors = 0


def empty_state(total_points=0):
    return {
        "total_points": total_points,
        "skipped_points": 0,
        "done_keys": [],
        "incomplete_points": 0,
        "outside": 0,
        "work_budget_stop": False,
        "api_error_stop": False,
        "detection_mode": "quick",
    }


class FakeCheckpointCursor:
    def __init__(self, connection):
        self.connection = connection
        self.result = []
        self.rowcount = 0
        self.closed = False

    def execute(self, sql, params=None):
        normalized = " ".join(sql.split())
        self.connection.statements.append((normalized, params))
        self.result = []
        self.rowcount = 0

        if normalized.startswith("CREATE TABLE IF NOT EXISTS"):
            return

        if normalized.startswith("INSERT INTO scan_point_log"):
            self.assert_upsert_sql(normalized)
            self.connection.checkpoints[params[0]] = self.connection.now
            self.rowcount = 1
            return

        if normalized.startswith("SELECT pointKey FROM scan_point_log"):
            self.assert_resume_sql(normalized)
            terminal_times = [
                run["completedAt"]
                for run in self.connection.detection_runs
                if run["status"] in service.RESUME_RESET_STATUSES
            ]
            watermark = max(
                terminal_times, default=datetime(1970, 1, 1))
            cutoff = self.connection.now - timedelta(days=30)
            self.result = [
                (point_key,)
                for point_key, completed_at in self.connection.checkpoints.items()
                if completed_at > watermark and completed_at > cutoff
            ]
            return

        if normalized.startswith("DELETE FROM scan_point_log WHERE pointKey IN"):
            if self.connection.fail_on_statement == "delete_checkpoints":
                raise RuntimeError("synthetic checkpoint delete failure")
            for point_key in params:
                if point_key in self.connection.checkpoints:
                    del self.connection.checkpoints[point_key]
                    self.rowcount += 1
            return

        if normalized.startswith("DELETE FROM geospatial_logs WHERE logID IN"):
            for flag_id in params:
                if flag_id in self.connection.flags:
                    self.connection.flags.remove(flag_id)
                    self.rowcount += 1
            return

        raise AssertionError(f"Unexpected checkpoint SQL: {normalized}")

    @staticmethod
    def assert_upsert_sql(sql):
        assert "INSERT INTO scan_point_log (pointKey, completedAt)" in sql
        assert "ON DUPLICATE KEY UPDATE completedAt = NOW()" in sql

    @staticmethod
    def assert_resume_sql(sql):
        assert "completedAt > COALESCE(" in sql
        assert "NOW() - INTERVAL 30 DAY" in sql
        for status in service.RESUME_RESET_STATUSES:
            assert f"'{status}'" in sql
        assert "'partial'" not in sql

    def fetchall(self):
        return list(self.result)

    def close(self):
        self.closed = True


class FakeCheckpointConnection:
    def __init__(self, now):
        self.now = now
        self.checkpoints = {}
        self.flags = set()
        self.detection_runs = []
        self.statements = []
        self.commits = 0
        self.begins = 0
        self.rollbacks = 0
        self.fail_on_statement = None
        self._transaction_snapshot = None

    def cursor(self):
        return FakeCheckpointCursor(self)

    def commit(self):
        self.commits += 1
        self._transaction_snapshot = None

    def begin(self):
        if self._transaction_snapshot is not None:
            raise AssertionError("Nested fake DB transaction")
        self.begins += 1
        self._transaction_snapshot = (
            dict(self.checkpoints), set(self.flags))

    def rollback(self):
        self.rollbacks += 1
        if self._transaction_snapshot is None:
            raise AssertionError("Rollback without an active fake transaction")
        checkpoints, flags = self._transaction_snapshot
        self.checkpoints = checkpoints
        self.flags = flags
        self._transaction_snapshot = None


class WorkEnvelopeTests(unittest.TestCase):
    """The time slice and request maximum must be untouched."""

    def setUp(self):
        fresh_run_state()

    def test_default_envelope_is_still_ninety_seconds_and_120_requests(self):
        with quota_overrides(
            **{"run_detection.max_seconds": 90, "run_detection.max_requests": 120}
        ):
            seconds, requests = service._detection_work_limits()

        self.assertEqual((seconds, requests), (90, 120))

    def test_env_baseline_envelope_is_unchanged(self):
        """Guard against the limiter work accidentally retuning the slice."""
        self.assertEqual(service.RUN_DETECTION_MAX_SECONDS, 90)
        self.assertEqual(service.RUN_DETECTION_MAX_REQUESTS, 120)

    def test_limiter_slows_completion_but_does_not_change_the_envelope(self):
        """
        At 1.25 s between requests a 90 s slice completes roughly 72 legacy
        points, so the time slice binds before the 120-request maximum. That is
        the expected trade-off; it must show up as fewer points per run, never
        as a changed limit.
        """
        per_minute = LEGACY_NEARBY_LIMITER.rate_per_minute
        requests_in_90s = 90 / 60.0 * per_minute + LEGACY_NEARBY_LIMITER.burst
        self.assertLess(requests_in_90s, 120)
        self.assertGreater(requests_in_90s, 60)
        # The configured ceilings are still the stricter of the two.
        self.assertEqual(service._detection_work_limits(), (90, 120))


class CheckpointTests(unittest.TestCase):
    """Completed points must be checkpointed even when a run stops early."""

    def setUp(self):
        fresh_run_state()

    def _points(self, count):
        return [(13.90 + i * 0.01, 121.10) for i in range(count)]

    def test_every_completed_point_is_checkpointed(self):
        points = self._points(5)
        with patch.object(service, "_completed_points_this_cycle",
                          return_value=set()), \
                patch.object(service, "_mark_point_done") as mark, \
                patch.object(service, "_detection_work_budget_reached",
                             return_value=False), \
                patch.object(service, "_fetch_point_results_for_mode",
                             return_value=([], True)):
            state = empty_state(len(points))
            service._scan_grid(
                lambda _places: None, None, state, "quick", points=points,
            )

        self.assertEqual(len(state["done_keys"]), 5)
        self.assertEqual(mark.call_count, 5)
        self.assertFalse(state["work_budget_stop"])

    def test_incomplete_point_is_not_checkpointed(self):
        """A point cut short by the work budget must be retried next scan."""
        points = self._points(3)
        with patch.object(service, "_completed_points_this_cycle",
                          return_value=set()), \
                patch.object(service, "_mark_point_done") as mark, \
                patch.object(service, "_detection_work_budget_reached",
                             return_value=False), \
                patch.object(service, "_fetch_point_results_for_mode",
                             return_value=([], False)):
            state = empty_state(len(points))
            service._scan_grid(
                lambda _places: None, None, state, "quick", points=points,
            )

        mark.assert_not_called()
        self.assertEqual(state["incomplete_points"], 3)
        self.assertEqual(state["done_keys"], [])

    def test_work_budget_stop_halts_the_walk(self):
        points = self._points(10)
        with patch.object(service, "_completed_points_this_cycle",
                          return_value=set()), \
                patch.object(service, "_mark_point_done"), \
                patch.object(service, "_detection_work_budget_reached",
                             side_effect=[False, True]), \
                patch.object(service, "_fetch_point_results_for_mode",
                             return_value=([], True)) as fetch_point:
            state = empty_state(len(points))
            service._scan_grid(
                lambda _places: None, None, state, "quick", points=points,
            )

        self.assertTrue(state["work_budget_stop"])
        self.assertEqual(len(state["done_keys"]), 1)
        fetch_point.assert_called_once()


class ContinuationTests(unittest.TestCase):
    """The limiter makes partial runs common; they must resume, not restart."""

    def setUp(self):
        fresh_run_state()

    def test_work_budget_stop_is_not_a_terminal_gap(self):
        state = empty_state(total_points=70)
        state["done_keys"] = ["a", "b"]
        state["incomplete_points"] = 1
        state["work_budget_stop"] = True

        self.assertFalse(service._grid_scan_has_terminal_gaps(state))

    def test_partial_run_status_does_not_reset_the_resume_watermark(self):
        """
        The watermark query only advances on RESUME_RESET_STATUSES. A run that
        stops on the work budget is recorded as "partial", which must not be in
        that list, or its checkpoints would be discarded and the next scan would
        redo the whole grid.
        """
        self.assertNotIn("partial", service.RESUME_RESET_STATUSES)
        self.assertEqual(
            set(service.RESUME_RESET_STATUSES),
            {"completed", "completed_with_gaps", "reset"},
        )

    def test_resume_watermark_query_uses_the_shared_status_list(self):
        """The SQL and the constant cannot drift apart."""
        cursor = MagicMock()
        cursor.fetchall.return_value = []
        fake_mysql = MagicMock()
        fake_mysql.connection.cursor.return_value = cursor

        with patch.object(service, "mysql", fake_mysql):
            service._completed_points_this_cycle()

        sql = cursor.execute.call_args.args[0]
        for status in service.RESUME_RESET_STATUSES:
            self.assertIn(f"'{status}'", sql)
        self.assertNotIn("'partial'", sql)

    def test_checkpoint_database_round_trip_and_nearby_mode_isolation(self):
        now = datetime(2026, 10, 12, 12, 0, 0)
        connection = FakeCheckpointConnection(now)
        point = (13.9667, 121.1167)
        expired_key = "expired-checkpoint"
        before_watermark_key = "before-terminal-watermark"
        connection.checkpoints[expired_key] = now - timedelta(days=31)

        with (
            patch.object(service, "mysql", MagicMock(connection=connection)),
            patch.object(service, "_budget_tables_ready", False),
            patch.object(service.test_mode, "is_enabled", return_value=False),
            patch.object(service.test_mode, "get_config", return_value={}),
            patch.object(quota_settings, "cap", return_value=0.009),
        ):
            service._ensure_budget_tables()
            scan_table_ddl = next(
                sql for sql, _ in connection.statements
                if "CREATE TABLE IF NOT EXISTS scan_point_log" in sql
            )
            self.assertIn(
                "pointKey VARCHAR(64) NOT NULL PRIMARY KEY", scan_table_ddl)
            self.assertIn("completedAt DATETIME NOT NULL", scan_table_ddl)

            with patch.object(service, "RUN_DETECTION_NEARBY_API", "legacy"):
                legacy_fingerprint = service._checkpoint_configuration_fingerprint(
                    "full")
            legacy_key = service._checkpoint_point_key(
                *point, legacy_fingerprint)

            connection.now = now - timedelta(minutes=6)
            service._mark_point_done(legacy_key)
            first_timestamp = connection.checkpoints[legacy_key]
            connection.now = now - timedelta(minutes=5)
            service._mark_point_done(legacy_key)
            self.assertGreater(
                connection.checkpoints[legacy_key], first_timestamp)
            self.assertEqual(connection.commits, 3)

            # Without a terminal-run watermark, the 30-day horizon still applies.
            current_checkpoints = service._completed_points_this_cycle()
            self.assertEqual(current_checkpoints, {legacy_key})
            self.assertNotIn(expired_key, current_checkpoints)

            connection.checkpoints[before_watermark_key] = (
                now - timedelta(days=11))
            connection.detection_runs = [
                {"status": "completed",
                    "completedAt": now - timedelta(days=10)},
                {"status": "partial", "completedAt": now -
                    timedelta(minutes=1)},
                {"status": "failed", "completedAt": now},
            ]
            self.assertEqual(
                service._completed_points_this_cycle(), {legacy_key})

            with patch.object(service, "RUN_DETECTION_NEARBY_API", "new"):
                new_fingerprint = service._checkpoint_configuration_fingerprint(
                    "full")
            new_key = service._checkpoint_point_key(*point, new_fingerprint)
            self.assertNotEqual(legacy_key, new_key)

            with (
                patch.object(service, "RUN_DETECTION_NEARBY_API", "new"),
                patch.object(
                    service, "_fetch_point_results_for_mode",
                    return_value=([], True),
                ) as fetch,
                patch.object(
                    service, "_detection_work_budget_reached", return_value=False),
                patch.object(service, "is_cancelled", return_value=False),
            ):
                state = empty_state(total_points=1)
                service._scan_grid(
                    lambda _places: True, None, state,
                    detection_mode="full", points=[point],
                )

            fetch.assert_called_once_with(*point, 850, "full")
            self.assertEqual(state["done_keys"], [new_key])
            self.assertEqual(
                service._completed_points_this_cycle(), {legacy_key, new_key})

            service._unmark_points([new_key])
            self.assertEqual(connection.commits, 5)
            self.assertNotIn(new_key, connection.checkpoints)
            self.assertEqual(
                service._completed_points_this_cycle(), {legacy_key})

    def test_cancel_cleanup_commits_flag_and_checkpoint_deletes_once(self):
        connection = FakeCheckpointConnection(datetime(2026, 10, 12, 12))
        connection.flags = {101, 102}
        connection.checkpoints = {"cancelled-key": connection.now}

        with patch.object(service, "mysql", MagicMock(connection=connection)):
            service._cleanup_cancelled_detection([101], ["cancelled-key"])

        self.assertEqual(connection.begins, 1)
        self.assertEqual(connection.commits, 1)
        self.assertEqual(connection.rollbacks, 0)
        self.assertEqual(connection.flags, {102})
        self.assertEqual(connection.checkpoints, {})

    def test_cancel_cleanup_rolls_back_both_deletes_on_checkpoint_failure(self):
        connection = FakeCheckpointConnection(datetime(2026, 10, 12, 12))
        connection.flags = {101, 102}
        connection.checkpoints = {"cancelled-key": connection.now}
        connection.fail_on_statement = "delete_checkpoints"

        with patch.object(service, "mysql", MagicMock(connection=connection)):
            with self.assertRaisesRegex(
                    RuntimeError, "synthetic checkpoint delete failure"):
                service._cleanup_cancelled_detection([101], ["cancelled-key"])

        self.assertEqual(connection.begins, 1)
        self.assertEqual(connection.commits, 0)
        self.assertEqual(connection.rollbacks, 1)
        self.assertEqual(connection.flags, {101, 102})
        self.assertEqual(connection.checkpoints, {
                         "cancelled-key": connection.now})

    def test_cancel_cleanup_makes_checkpoint_retryable_on_resume(self):
        now = datetime(2026, 10, 12, 12)
        connection = FakeCheckpointConnection(now)
        point = (13.9667, 121.1167)
        connection.flags = {101}

        with (
            patch.object(service, "mysql", MagicMock(connection=connection)),
            patch.object(service, "RUN_DETECTION_NEARBY_API", "new"),
            patch.object(service.test_mode, "is_enabled", return_value=False),
            patch.object(service.test_mode, "get_config", return_value={}),
            patch.object(quota_settings, "cap", return_value=0.009),
        ):
            fingerprint = service._checkpoint_configuration_fingerprint("full")
            point_key = service._checkpoint_point_key(*point, fingerprint)
            connection.checkpoints[point_key] = now
            service._cleanup_cancelled_detection([101], [point_key])
            self.assertEqual(service._completed_points_this_cycle(), set())

            with (
                patch.object(
                    service, "_detection_work_budget_reached", return_value=False),
                patch.object(service, "is_cancelled", return_value=False),
                patch.object(
                    service, "_fetch_point_results_for_mode",
                    return_value=([], True),
                ) as fetch,
            ):
                state = empty_state(total_points=1)
                service._scan_grid(
                    lambda _places: True, None, state,
                    detection_mode="full", points=[point],
                )

            fetch.assert_called_once_with(*point, 850, "full")
            self.assertEqual(state["done_keys"], [point_key])
            self.assertIn(point_key, connection.checkpoints)
            self.assertEqual(connection.flags, set())

    def test_second_scan_skips_points_checkpointed_by_the_first(self):
        points = [(13.90 + i * 0.01, 121.10) for i in range(6)]
        fingerprint = service._checkpoint_configuration_fingerprint("quick")
        first_run = {
            service._checkpoint_point_key(lat, lng, fingerprint)
            for lat, lng in points[:4]
        }
        fetched = []

        def fake_fetch(lat, lng, radius, mode):
            fetched.append((lat, lng))
            return ([], True)

        with patch.object(service, "_completed_points_this_cycle",
                          return_value=first_run), \
                patch.object(service, "_mark_point_done"), \
                patch.object(service, "_detection_work_budget_reached",
                             return_value=False), \
                patch.object(service, "_fetch_point_results_for_mode",
                             side_effect=fake_fetch):
            state = empty_state(len(points))
            service._scan_grid(
                lambda _places: None, None, state, "quick", points=points,
            )

        self.assertEqual(state["skipped_points"], 4)
        self.assertEqual(len(state["done_keys"]), 2)
        self.assertEqual(fetched, points[4:])


class RetryPathTests(unittest.TestCase):
    """Throttling responses must still stop the scan instead of looping."""

    def setUp(self):
        fresh_run_state()

    @patch("api.flags.service.time.sleep")
    @patch("api.flags.service._places_get")
    def test_legacy_over_query_limit_still_raises_budget_exceeded(
        self, places_get, _sleep
    ):
        response = MagicMock()
        response.json.return_value = {
            "status": "OVER_QUERY_LIMIT", "results": [],
        }
        places_get.return_value = response

        with patch.dict("os.environ", {"GOOGLE_MAPS_API_KEY": "test-key"}), \
                patch.object(service, "RUN_DETECTION_NEARBY_API", "legacy"):
            with self.assertRaises(service.PlacesBudgetExceeded) as raised:
                service._fetch_point_results_once(13.9667, 121.1167, 850)

        self.assertIn("budget", str(raised.exception).lower())

    def test_legacy_request_denied_is_still_distinguished_from_quota(self):
        response = MagicMock()
        response.json.return_value = {
            "status": "REQUEST_DENIED", "error_message": "bad key", "results": [],
        }
        with patch.dict("os.environ", {"GOOGLE_MAPS_API_KEY": "test-key"}), \
                patch.object(service, "_places_get", return_value=response), \
                patch.object(service, "RUN_DETECTION_NEARBY_API", "legacy"):
            with self.assertRaises(RuntimeError) as raised:
                service._fetch_point_results_once(13.9667, 121.1167, 850)

        self.assertIn("not a daily quota limit", str(raised.exception))

    @patch("api.flags.service.time.sleep")
    @patch("api.flags.service.test_mode")
    def test_new_nearby_per_minute_429_still_retries_with_backoff(
        self, mode, sleep
    ):
        """The New endpoint keeps its bounded 429 retry; it is not paced by
        the legacy limiter, but the retry path must remain intact."""
        mode.is_enabled.return_value = False
        throttled = MagicMock(
            status_code=429, text="RESOURCE_EXHAUSTED per minute")
        recovered = MagicMock(status_code=200)
        recovered.json.return_value = {"places": []}
        service._places_run_state.calls = {
            "new_nearby": 0, "new_nearby_initial": 0}

        with patch.dict("os.environ", {"GOOGLE_MAPS_API_KEY": "test-key"}), \
                patch.object(service, "mysql", MagicMock()), \
                patch.object(service, "_nearby_last_request_at", 0), \
                patch.object(service.http, "post",
                             side_effect=[throttled, recovered]) as post, \
                patch.object(service, "reserve_usage_slot",
                             return_value=(True, None)), \
                patch.object(quota_settings, "cap", side_effect=lambda _k: 100):
            results, ok = service._new_nearby_request(13.9667, 121.1167, 850)

        self.assertTrue(ok)
        self.assertEqual(results, [])
        self.assertEqual(post.call_count, 2,
                         "one throttled attempt then a retry")
        sleep.assert_called()

    def test_new_nearby_daily_quota_429_still_stops_the_run(self):
        """A daily-limit 429 must not be retried into a longer stall."""
        mode = MagicMock()
        mode.is_enabled.return_value = False
        exhausted = MagicMock(
            status_code=429, text="RESOURCE_EXHAUSTED quota exceeded")
        service._places_run_state.calls = {
            "new_nearby": 0, "new_nearby_initial": 0}

        with patch.dict("os.environ", {"GOOGLE_MAPS_API_KEY": "test-key"}), \
                patch.object(service, "test_mode", mode), \
                patch.object(service, "mysql", MagicMock()), \
                patch.object(service, "_nearby_last_request_at", 0), \
                patch.object(service.http, "post", return_value=exhausted) as post, \
                patch.object(service, "reserve_usage_slot",
                             return_value=(True, None)), \
                patch.object(quota_settings, "cap", side_effect=lambda _k: 100):
            with self.assertRaises(service.PlacesBudgetExceeded) as raised:
                service._new_nearby_request(13.9667, 121.1167, 850)

        self.assertEqual(post.call_count, 1,
                         "a daily quota error is not retried")
        self.assertEqual(raised.exception.reason, "daily_quota_exceeded")


class EndToEndPacedScanTests(unittest.TestCase):
    """
    Whole-chain proof: real limiter -> _places_get -> reservation -> response
    -> checkpoint, with only Google HTTP and MySQL mocked and the limiter on a
    fake clock so the test runs instantly.
    """

    def setUp(self):
        fresh_run_state()
        self.clock = FakeClock()
        self.limiter = RateLimiter(
            rate_per_minute=48, burst=3,
            clock=self.clock, sleep=self.clock.sleep,
        )
        self.response = MagicMock(status_code=200)
        self.response.json.return_value = {
            "status": "ZERO_RESULTS", "results": [], "next_page_token": None,
        }
        service._places_run_state.query_kind = "initial"

    def _run_scan(self, points, done_keys):
        with patch.object(service, "LEGACY_NEARBY_LIMITER", self.limiter), \
                patch.object(service, "_reserve_places_call") as reserve, \
                patch.object(service, "mysql", MagicMock()), \
                patch.dict("os.environ", {"GOOGLE_MAPS_API_KEY": "test-key"}), \
                patch.object(service, "test_mode") as mode, \
                patch.object(service, "_completed_points_this_cycle",
                             return_value=set(done_keys)), \
                patch.object(service, "_mark_point_done") as mark, \
                patch.object(service, "RUN_DETECTION_NEARBY_API", "legacy"), \
                patch.object(service, "_detection_radius_m", return_value=850):
            mode.is_enabled.return_value = False
            with patch.object(service.http, "get", return_value=self.response):
                state = empty_state(len(points))
                service._scan_grid(
                    lambda _places: None, None, state, "quick", points=points,
                )
        return state, reserve, mark

    def test_paced_scan_checkpoints_every_point_and_resumes_cleanly(self):
        points = [(13.90 + i * 0.01, 121.10) for i in range(10)]

        state, reserve, mark = self._run_scan(points, set())

        self.assertEqual(reserve.call_count, 10)
        self.assertEqual(mark.call_count, 10)
        self.assertEqual(len(state["done_keys"]), 10)
        self.assertEqual(state["skipped_points"], 0)
        self.assertFalse(state["work_budget_stop"])
        # burst + 1 immediate, then one interval per remaining request
        self.assertAlmostEqual(self.clock.now, 6 * 1.25, places=3)

        # A second scan over the same grid spends nothing and fetches nothing.
        second_clock = FakeClock()
        self.clock, self.limiter = second_clock, RateLimiter(
            rate_per_minute=48, burst=3,
            clock=second_clock, sleep=second_clock.sleep,
        )
        resume_state, reserve2, mark2 = self._run_scan(
            points, set(state["done_keys"]),
        )

        self.assertEqual(resume_state["skipped_points"], 10)
        reserve2.assert_not_called()
        mark2.assert_not_called()
        self.assertEqual(second_clock.now, 0.0)


class ReservationAccountingTests(unittest.TestCase):
    """Pacing must not be mistaken for quota consumption."""

    def setUp(self):
        fresh_run_state()

    def test_waiting_for_the_limiter_does_not_count_a_request(self):
        with patch.object(service, "LEGACY_NEARBY_LIMITER") as limiter, \
                patch.object(service, "_reserve_places_call") as reserve, \
                patch.object(service.http, "get") as get, \
                patch.object(service, "test_mode") as mode:
            mode.is_enabled.return_value = False
            limiter.acquire.return_value = 30.0     # a long wait, no quota spent
            get.return_value = MagicMock(status_code=200)

            service._places_get("nearby", "https://places.test", timeout=10)

        limiter.acquire.assert_called_once()
        reserve.assert_called_once_with("nearby")

    def test_budget_check_still_runs_before_each_paced_call(self):
        """
        The limiter sleeps inside the request path, so the walk must consult
        the work budget first -- otherwise every scan would overshoot its slice
        by one queued request.
        """
        order = []
        with patch.object(service, "_detection_work_budget_reached",
                          side_effect=lambda: order.append("budget") or False), \
                patch.object(service, "_places_get") as places_get, \
                patch.dict("os.environ", {"GOOGLE_MAPS_API_KEY": "test-key"}), \
                patch.object(service, "RUN_DETECTION_NEARBY_API", "legacy"):
            places_get.return_value = MagicMock()
            places_get.return_value.json.return_value = {
                "status": "ZERO_RESULTS", "results": [],
            }
            service._fetch_point_results_once(13.9667, 121.1167, 850)

        self.assertEqual(order[0], "budget")


if __name__ == "__main__":
    unittest.main()
