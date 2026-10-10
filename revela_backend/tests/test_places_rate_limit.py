"""
Tests for the Places API (Legacy) request rate limiter.

The limiter exists because the Cloud Console quota for Places API (Legacy) is
60 requests/minute and the previous flat 300 ms pacing allowed roughly 200.
These tests pin the bound with a fake clock, so they assert on admitted request
times without ever waiting or calling Google.
"""

import threading
import unittest
from unittest.mock import patch

from api.utils import places_rate_limit as prl
from api.utils.quota_ceilings import pacing_for


class FakeClock:
    """Monotonic clock that only advances when someone sleeps."""

    def __init__(self):
        self.now = 0.0
        self.sleeps = []
        self._lock = threading.Lock()

    def __call__(self):
        with self._lock:
            return self.now

    def sleep(self, seconds):
        if seconds <= 0:
            return
        self.sleeps.append(seconds)
        with self._lock:
            self.now += seconds

    def advance(self, seconds):
        with self._lock:
            self.now += seconds


class RateLimiterTests(unittest.TestCase):
    """GCRA pacing maths, driven by a fake clock."""

    def test_interval_and_window_bound_match_the_configuration(self):
        limiter = prl.RateLimiter(rate_per_minute=48, burst=3,
                                  clock=FakeClock(), sleep=lambda _s: None)
        self.assertAlmostEqual(limiter.min_interval_seconds, 1.25)
        self.assertLess(limiter.max_requests_per_minute,
                        prl.CLOUD_LEGACY_NEARBY_PER_MINUTE)

    def test_first_call_is_not_delayed(self):
        clock = FakeClock()
        limiter = prl.RateLimiter(rate_per_minute=48, burst=3,
                                  clock=clock, sleep=clock.sleep)
        self.assertEqual(limiter.acquire(), 0.0)
        self.assertEqual(clock.sleeps, [])

    def test_burst_then_steady_interval(self):
        clock = FakeClock()
        limiter = prl.RateLimiter(rate_per_minute=48, burst=3,
                                  clock=clock, sleep=clock.sleep)
        for _ in range(10):
            limiter.acquire()
        # burst + 1 calls slip through, then every later call waits exactly one
        # interval. `acquire` returns the delay the caller had to sit out.
        self.assertEqual(clock.sleeps, [1.25] * 6)

    def test_no_rolling_sixty_second_window_exceeds_the_cloud_quota(self):
        """The core safety property, asserted over a long simulated run."""
        clock = FakeClock()
        limiter = prl.RateLimiter(rate_per_minute=48, burst=3,
                                  clock=clock, sleep=clock.sleep)
        admitted = []
        for _ in range(400):
            admitted.append(clock())
            limiter.acquire()

        window = 60.0
        worst = 0
        for start in admitted:
            worst = max(worst, sum(1 for t in admitted if start <= t < start + window))
        self.assertLessEqual(
            worst, prl.CLOUD_LEGACY_NEARBY_PER_MINUTE,
            f"{worst} requests in a rolling 60s window exceeds the Cloud quota",
        )
        self.assertGreater(worst, 40, "sanity: the run should be rate limited, "
                                      "not throttled to almost nothing")

    def test_gap_lets_the_burst_rebuild(self):
        clock = FakeClock()
        limiter = prl.RateLimiter(rate_per_minute=48, burst=3,
                                  clock=clock, sleep=clock.sleep)
        for _ in range(20):
            limiter.acquire()
        clock.sleeps.clear()
        clock.advance(300)          # long idle period
        for _ in range(4):
            self.assertEqual(limiter.acquire(), 0.0)
        self.assertEqual(clock.sleeps, [])

    def test_concurrent_callers_cannot_bypass_the_bound(self):
        """
        Eight threads racing on the same limiter must still be paced, i.e. the
        whole group waits about (n - burst - 1) intervals, not zero.
        """
        clock = FakeClock()
        limiter = prl.RateLimiter(rate_per_minute=48, burst=3,
                                  clock=clock, sleep=clock.sleep)
        threads = [threading.Thread(target=limiter.acquire) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        # 8 callers, burst 3 -> 4 need to wait, one interval each.
        self.assertEqual(len(clock.sleeps), 4)
        self.assertAlmostEqual(clock.now, 5.0, places=3)

    def test_invalid_configuration_is_rejected(self):
        with self.assertRaises(ValueError):
            prl.RateLimiter(rate_per_minute=0)
        with self.assertRaises(ValueError):
            prl.RateLimiter(rate_per_minute=48, burst=0)

    def test_configured_rate_and_burst_cannot_exceed_the_cloud_quota(self):
        """
        A misconfigured env var is clamped, never honoured. Clamping only the
        rate would still admit rate + burst requests in a rolling minute.
        """
        for requested_rate, requested_burst in (
            (600, 3), (60, 3), (48, 1000), (1, 1000), (45, 45),
        ):
            with self.subTest(rate=requested_rate, burst=requested_burst):
                rate, burst = prl.clamp_to_cloud_quota(
                    requested_rate, requested_burst,
                )
                limiter = prl.RateLimiter(
                    rate_per_minute=rate, burst=burst,
                    clock=FakeClock(), sleep=lambda _s: None,
                )
                self.assertLessEqual(
                    limiter.max_requests_per_minute,
                    prl.CLOUD_LEGACY_NEARBY_PER_MINUTE,
                )

    def test_default_configuration_leaves_headroom(self):
        rate, burst = prl.clamp_to_cloud_quota(
            prl.DEFAULT_RATE_PER_MINUTE, prl.DEFAULT_BURST,
        )
        self.assertEqual((rate, burst),
                         (prl.DEFAULT_RATE_PER_MINUTE, prl.DEFAULT_BURST))
        limiter = prl.RateLimiter(rate_per_minute=rate, burst=burst,
                                  clock=FakeClock(), sleep=lambda _s: None)
        self.assertLess(limiter.max_requests_per_minute,
                        prl.CLOUD_LEGACY_NEARBY_PER_MINUTE)

    def test_non_numeric_env_value_falls_back_to_the_default(self):
        with patch.dict("os.environ", {"LEGACY_NEARBY_RATE_PER_MINUTE": "fast"}):
            self.assertEqual(
                prl._positive_int("LEGACY_NEARBY_RATE_PER_MINUTE",
                                  prl.DEFAULT_RATE_PER_MINUTE),
                prl.DEFAULT_RATE_PER_MINUTE,
            )


class SharedLimiterTests(unittest.TestCase):

    def test_module_exposes_one_shared_limiter(self):
        self.assertIsInstance(prl.LEGACY_NEARBY_LIMITER, prl.RateLimiter)
        self.assertLessEqual(
            prl.LEGACY_NEARBY_LIMITER.max_requests_per_minute,
            prl.CLOUD_LEGACY_NEARBY_PER_MINUTE,
        )

    def test_reported_pacing_matches_the_enforced_limiter(self):
        """
        `REQUEST_PACING` is what the admin panel shows operators. If it drifts
        from the limiter that is actually enforced, the panel starts lying.
        """
        recorded = pacing_for("nearby_search_legacy")["min_interval_ms"] / 1000.0
        self.assertTrue(pacing_for("nearby_search_legacy")["enforced"])
        self.assertAlmostEqual(
            recorded, prl.LEGACY_NEARBY_LIMITER.min_interval_seconds, places=3,
        )


class LegacyRequestPathTests(unittest.TestCase):
    """`_places_get` must pace before reserving, and reserve before sending."""

    def setUp(self):
        from api.flags import service

        # `_places_run_state` is a threading.local that other suites populate,
        # so pin it to a complete dict rather than depending on test ordering.
        patcher = patch.object(
            service._places_run_state, "calls",
            {
                "legacy_nearby": 0, "new_nearby": 0,
                "legacy_nearby_initial": 0, "legacy_nearby_adaptive": 0,
            },
            create=True,
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_live_legacy_request_passes_through_the_limiter(self):
        from api.flags import service

        with patch.object(service, "LEGACY_NEARBY_LIMITER") as limiter, \
                patch.object(service, "_reserve_places_call") as reserve, \
                patch.object(service.http, "get") as get:
            limiter.acquire.return_value = 0.0
            service._places_get("nearby", "https://places.test", timeout=10)

        limiter.acquire.assert_called_once()
        reserve.assert_called_once_with("nearby")
        get.assert_called_once()

    def test_limiter_runs_before_the_quota_reservation(self):
        from api.flags import service

        order = []
        with patch.object(service, "LEGACY_NEARBY_LIMITER") as limiter, \
                patch.object(service, "_reserve_places_call",
                             side_effect=lambda *_a: order.append("reserve")), \
                patch.object(service.http, "get",
                             side_effect=lambda *a, **k: order.append("send")):
            limiter.acquire.side_effect = lambda: order.append("pace") or 0.0
            service._places_get("nearby", "https://places.test", timeout=10)

        self.assertEqual(order, ["pace", "reserve", "send"])

    def test_fixture_replay_neither_paces_nor_reserves(self):
        """A replay issues no Google request, so it must not consume a slot."""
        from api.flags import service

        with patch.object(service, "LEGACY_NEARBY_LIMITER") as limiter, \
                patch.object(service, "_reserve_places_call") as reserve, \
                patch.object(service, "test_mode") as mode:
            mode.is_enabled.return_value = True
            mode.resolve_request.return_value = ({"status": "ZERO_RESULTS"}, None)
            service._places_get("nearby", "https://places.test", params={})

        limiter.acquire.assert_not_called()
        reserve.assert_not_called()


if __name__ == "__main__":
    unittest.main()