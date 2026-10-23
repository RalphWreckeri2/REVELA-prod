"""Bounded, process-local request limits for API and public auth routes."""

from collections import OrderedDict, deque
from math import ceil
from threading import Lock
import time

from flask import jsonify, request


_MAX_TRACKED_WINDOWS = 20000
_CLEANUP_INTERVAL = 256
_AUTH_RULES = {
    "auth.login": ("auth-login", "AUTH_LOGIN_RATE_LIMIT",
                  "AUTH_LOGIN_RATE_WINDOW_SECONDS"),
    "auth.verify_2fa_login": (
        "auth-2fa-login", "AUTH_2FA_LOGIN_RATE_LIMIT",
        "AUTH_2FA_LOGIN_RATE_WINDOW_SECONDS"),
    "auth.request_otp_route": ("auth-otp", "AUTH_OTP_RATE_LIMIT",
                               "AUTH_OTP_RATE_WINDOW_SECONDS"),
    "auth.request_manual_reset": (
        "auth-manual-reset", "AUTH_MANUAL_RESET_RATE_LIMIT",
        "AUTH_MANUAL_RESET_RATE_WINDOW_SECONDS"),
    "auth.reset_password_route": (
        "auth-password-reset", "AUTH_PASSWORD_RESET_RATE_LIMIT",
        "AUTH_PASSWORD_RESET_RATE_WINDOW_SECONDS"),
}


class _RateLimitState:
    def __init__(self):
        self.lock = Lock()
        self.windows = OrderedDict()
        self.request_count = 0

    def check(self, client_id, rules):
        now = time.monotonic()
        with self.lock:
            self.request_count += 1
            if self.request_count % _CLEANUP_INTERVAL == 0:
                self._remove_expired(now)

            entries = []
            retry_after = 0
            for scope, limit, period in rules:
                key = (scope, client_id)
                stored = self.windows.get(key)
                if stored is None:
                    timestamps = deque()
                else:
                    timestamps, previous_period = stored
                    if previous_period != period:
                        timestamps.clear()
                    self.windows.move_to_end(key)
                    while timestamps and timestamps[0] <= now - period:
                        timestamps.popleft()
                if len(timestamps) >= limit:
                    retry_after = max(
                        retry_after,
                        ceil(timestamps[0] + period - now),
                    )
                entries.append((key, timestamps, limit, period))

            if retry_after:
                return False, max(1, retry_after)

            missing_windows = sum(
                key not in self.windows for key, *_rest in entries)
            if len(self.windows) + missing_windows > _MAX_TRACKED_WINDOWS:
                self._remove_expired(now)
                missing_windows = sum(
                    key not in self.windows for key, *_rest in entries)
            if len(self.windows) + missing_windows > _MAX_TRACKED_WINDOWS:
                return False, 60

            for key, timestamps, _limit, period in entries:
                timestamps.append(now)
                self.windows[key] = (timestamps, period)
                self.windows.move_to_end(key)
            return True, 0

    def _remove_expired(self, now):
        for key, (timestamps, period) in list(self.windows.items()):
            if not timestamps:
                del self.windows[key]
                continue
            while timestamps and timestamps[0] <= now - period:
                timestamps.popleft()
            if not timestamps:
                del self.windows[key]


def init_app(app):
    """Limit API traffic by client address; auth routes have stricter limits."""
    config_keys = (
        "API_RATE_LIMIT", "API_RATE_WINDOW_SECONDS",
        "AUTH_LOGIN_RATE_LIMIT", "AUTH_LOGIN_RATE_WINDOW_SECONDS",
        "AUTH_2FA_LOGIN_RATE_LIMIT", "AUTH_2FA_LOGIN_RATE_WINDOW_SECONDS",
        "AUTH_OTP_RATE_LIMIT", "AUTH_OTP_RATE_WINDOW_SECONDS",
        "AUTH_MANUAL_RESET_RATE_LIMIT",
        "AUTH_MANUAL_RESET_RATE_WINDOW_SECONDS",
        "AUTH_PASSWORD_RESET_RATE_LIMIT",
        "AUTH_PASSWORD_RESET_RATE_WINDOW_SECONDS",
    )
    for key in config_keys:
        value = int(app.config[key])
        if value < 1:
            raise ValueError(f"{key} must be a positive integer")

    state = _RateLimitState()
    app.extensions["revela_request_rate_limit"] = state

    @app.before_request
    def _enforce_request_rate_limit():
        if not request.path.startswith("/api/") or request.method == "OPTIONS":
            return None

        client_id = request.remote_addr or "unknown"
        rules = [
            ("api", int(app.config["API_RATE_LIMIT"]),
             int(app.config["API_RATE_WINDOW_SECONDS"])),
        ]
        auth_rule = _AUTH_RULES.get(request.endpoint)
        if auth_rule:
            scope, limit_key, period_key = auth_rule
            rules.append((
                scope,
                int(app.config[limit_key]),
                int(app.config[period_key]),
            ))

        allowed, retry_after = state.check(client_id, rules)
        if allowed:
            return None
        response = jsonify({
            "error": "Too many requests. Please try again later.",
        })
        response.status_code = 429
        response.headers["Retry-After"] = str(retry_after)
        return response
