"""
Process-wide request rate limiting for the Google Places API (Legacy).

Why this exists
---------------
The Google Cloud Console quota for Places API (Legacy) on this project is
60 requests/minute. REVELA previously paced legacy Nearby Search with a flat
300 ms sleep, which allows roughly 200 requests/minute in a steady stream --
comfortably above Google's limit. A single Run Detection scan can issue up to
`run_detection.max_requests` (120) calls, so a scan could trip a 429 mid-run.

Google's Places API usage-and-billing documentation states that the Places API
(Legacy) per-minute limit is *the sum of client-side and server-side requests
for all applications using the credentials of the same project*. REVELA is only
one consumer, so the limiter below can bound REVELA's own contribution; it
cannot bound anybody else.

How it works
------------
A GCRA (generic cell rate algorithm) pacer. Each caller atomically reserves the
next admissible slot under a lock and then sleeps outside that lock, so waiting
callers are never serialised behind one another while still being guaranteed
non-overlapping send times. `burst` allows a short idle-period burst (used when
a scan starts after the previous one has finished); the sustained rate is
always `rate_per_minute`.

With `burst` and interval `i`, no rolling 60-second window can contain more than
`floor(60 / i) + burst` requests. The defaults below give
`floor(60 / 1.25) + 3 = 51`, i.e. roughly 15% headroom under 60/minute.

Scope and limitations -- read before relying on this
----------------------------------------------------
1. This is an *in-process* limiter. It covers every thread in this Python
   process, which is what Run Detection, Snap Pins, Re-verify, and any other
   legacy Places traffic inside REVELA uses (they all funnel through
   `api.flags.service._places_get`).
2. It does NOT coordinate across multiple processes, gunicorn workers,
   containers, or any other REVELA instance. N processes would each get their
   own full allowance, so the aggregate could reach N x the configured rate.
   The shipped container runs `gunicorn --workers 1 --threads 16`
   (see `Dockerfile`), where this limiter is complete. A warning is printed at
   import time when the process environment advertises more than one worker.
   If the deployment is ever scaled out, divide the configured rate by the
   worker count, or move the pacer to shared state (Redis / MySQL).
3. It does NOT protect against any other application or operator using the same
   Google Cloud project credentials, because Google's Legacy Places quota is a
   shared, project-wide pool. See point 2's reference to Google's own docs.
4. Daily and monthly budgets are unaffected. Those are enforced separately and
   fail closed in `api/utils/places_quota.py`; this module only governs the
   short-term send rate.
"""

import os
import threading
import time


#: Google's Places API (Legacy) per-minute quota for this project, as read from
#: Cloud Console. Nothing here may be configured above this.
CLOUD_LEGACY_NEARBY_PER_MINUTE = 60

#: Sustained rate REVELA sends legacy Nearby Search at. 48/min leaves room for
#: the burst below while staying under the Cloud quota.
DEFAULT_RATE_PER_MINUTE = 48

#: Short burst permitted after an idle period, in requests.
DEFAULT_BURST = 3


def _positive_int(name, fallback, minimum=1):
    raw = os.getenv(name)
    if raw is None or raw == "":
        return fallback
    try:
        value = int(raw)
    except (TypeError, ValueError):
        print(
            f"[places_rate_limit] Ignoring non-integer {name}; using {fallback}.")
        return fallback
    if value < minimum:
        print(
            f"[places_rate_limit] {name} must be at least {minimum}; "
            f"using {minimum}."
        )
        return minimum
    return value


def _warn_if_multiple_workers():
    """Best-effort notice when the environment hints at >1 worker process."""
    concurrency = os.getenv("WEB_CONCURRENCY") or ""
    if concurrency.strip().isdigit() and int(concurrency.strip()) > 1:
        print(
            "[places_rate_limit] WARNING: WEB_CONCURRENCY > 1. The legacy "
            "Nearby Search rate limiter is per-process, so the aggregate rate "
            "will be N x the configured value. Divide "
            "LEGACY_NEARBY_RATE_PER_MINUTE by the worker count."
        )
    gunicorn_args = os.getenv("GUNICORN_CMD_ARGS") or ""
    if "--workers" in gunicorn_args:
        for token in gunicorn_args.split():
            if token.startswith("--workers="):
                count = token.split("=", 1)[1]
                if count.isdigit() and int(count) > 1:
                    print(
                        "[places_rate_limit] WARNING: GUNICORN_CMD_ARGS "
                        f"requests {count} workers. The legacy Nearby Search "
                        "rate limiter is per-process; see this module's "
                        "docstring."
                    )


def clamp_to_cloud_quota(
    rate_per_minute,
    burst,
    cloud_limit=CLOUD_LEGACY_NEARBY_PER_MINUTE,
):
    """
    Shrink (rate, burst) until their worst case fits inside `cloud_limit`.

    The worst case is `rate + burst`, because the burst is exactly what an
    idle period lets through at once. Clamping only the rate is not enough: a
    rate of 60 with a burst of 3 still admits 63 requests in a rolling minute.
    """
    limit = int(cloud_limit)
    burst = max(1, min(int(burst), limit - 1))
    rate = min(float(rate_per_minute), float(limit - burst))
    return rate, burst


class RateLimiter:
    """
    Concurrency-safe GCRA pacer.

    `acquire()` blocks until this caller may send its request. The rate bound
    holds for every thread in the process because the slot reservation is a
    single critical-section update; sleeping happens outside the lock.

    `clock` and `sleep` are injectable so tests can drive time deterministically
    instead of actually waiting.
    """

    def __init__(
        self,
        rate_per_minute=DEFAULT_RATE_PER_MINUTE,
        burst=DEFAULT_BURST,
        clock=None,
        sleep=None,
    ):
        if rate_per_minute <= 0:
            raise ValueError("rate_per_minute must be positive")
        if burst < 1:
            raise ValueError("burst must be at least 1")
        self.rate_per_minute = float(rate_per_minute)
        self.burst = int(burst)
        self._interval = 60.0 / self.rate_per_minute
        self._tolerance = self.burst * self._interval
        self._lock = threading.Lock()
        # Theoretical arrival time of the next conforming request. None until
        # first use, which lets the first `burst + 1` calls through immediately.
        self._tat = None
        self._clock = clock or time.monotonic
        self._sleep = sleep or time.sleep

    @property
    def min_interval_seconds(self):
        """Minimum spacing between two admitted requests."""
        return self._interval

    @property
    def max_requests_per_minute(self):
        """Upper bound on requests in any rolling 60-second window."""
        return (60.0 / self._interval) + self.burst

    def acquire(self):
        """Block until this caller may send a request. Returns seconds waited."""
        with self._lock:
            now = self._clock()
            tat = now if self._tat is None else self._tat
            # The request is admissible `tolerance` before the theoretical
            # arrival time; anything earlier must wait.
            delay = (tat - self._tolerance) - now
            self._tat = max(tat, now) + self._interval
            scheduled = now + (delay if delay > 0 else 0.0)

        # Outside the lock: each thread already owns its slot, so concurrent
        # callers sleep in parallel instead of queueing behind one another.
        # The loop guards against a short/early sleep returning early.
        while True:
            remaining = scheduled - self._clock()
            if remaining <= 0:
                break
            self._sleep(remaining)
        return delay if delay > 0 else 0.0


_warn_if_multiple_workers()

_configured_rate = _positive_int(
    "LEGACY_NEARBY_RATE_PER_MINUTE", DEFAULT_RATE_PER_MINUTE,
)
_configured_burst = _positive_int("LEGACY_NEARBY_RATE_BURST", DEFAULT_BURST)

_clamped_rate, _clamped_burst = clamp_to_cloud_quota(
    _configured_rate, _configured_burst,
)
if (_clamped_rate, _clamped_burst) != (float(_configured_rate), _configured_burst):
    print(
        f"[places_rate_limit] Legacy Nearby pacing "
        f"{_configured_rate}/minute burst {_configured_burst} would admit "
        f"{_configured_rate + _configured_burst} requests per minute, above "
        f"the Cloud quota of {CLOUD_LEGACY_NEARBY_PER_MINUTE}/minute; using "
        f"{_clamped_rate:g}/minute burst {_clamped_burst}."
    )


#: Single shared instance. Import it; do not construct a second one per call
#: site, or the pacing will not be coordinated at all.
LEGACY_NEARBY_LIMITER = RateLimiter(
    rate_per_minute=_clamped_rate,
    burst=_clamped_burst,
)