import unittest
from datetime import timedelta
from unittest.mock import patch

from flask import Flask
from flask_jwt_extended import JWTManager

from api.middleware import request_rate_limit


class RequestRateLimitTests(unittest.TestCase):
    def setUp(self):
        app = Flask(__name__)
        app.config.update(
            JWT_SECRET_KEY="test-secret",
            JWT_ACCESS_TOKEN_EXPIRES=timedelta(hours=1),
            API_RATE_LIMIT=100,
            API_RATE_WINDOW_SECONDS=60,
            AUTH_LOGIN_RATE_LIMIT=2,
            AUTH_LOGIN_RATE_WINDOW_SECONDS=300,
            AUTH_2FA_LOGIN_RATE_LIMIT=1,
            AUTH_2FA_LOGIN_RATE_WINDOW_SECONDS=900,
            AUTH_OTP_RATE_LIMIT=1,
            AUTH_OTP_RATE_WINDOW_SECONDS=900,
            AUTH_MANUAL_RESET_RATE_LIMIT=1,
            AUTH_MANUAL_RESET_RATE_WINDOW_SECONDS=3600,
            AUTH_PASSWORD_RESET_RATE_LIMIT=1,
            AUTH_PASSWORD_RESET_RATE_WINDOW_SECONDS=900,
        )
        JWTManager(app)
        app.add_url_rule(
            "/api/auth/login", endpoint="auth.login",
            view_func=lambda: ("ok", 200), methods=["POST"])
        app.add_url_rule(
            "/api/auth/verify-2fa-login", endpoint="auth.verify_2fa_login",
            view_func=lambda: ("ok", 200), methods=["POST"])
        app.add_url_rule(
            "/api/auth/request-otp", endpoint="auth.request_otp_route",
            view_func=lambda: ("ok", 200), methods=["POST"])
        app.add_url_rule(
            "/api/auth/request-manual-reset",
            endpoint="auth.request_manual_reset",
            view_func=lambda: ("ok", 200), methods=["POST"])
        app.add_url_rule(
            "/api/auth/reset-password", endpoint="auth.reset_password_route",
            view_func=lambda: ("ok", 200), methods=["POST"])
        app.add_url_rule(
            "/api/resource", endpoint="resource",
            view_func=lambda: ("ok", 200), methods=["GET"])
        request_rate_limit.init_app(app)
        self.app = app
        self.client = app.test_client()

    def test_auth_endpoints_receive_route_specific_limits_and_retry_after(self):
        with patch.object(request_rate_limit.time, "monotonic", return_value=10):
            self.assertEqual(
                self.client.post("/api/auth/login").status_code, 200)
            self.assertEqual(
                self.client.post("/api/auth/login").status_code, 200)
            response = self.client.post("/api/auth/login")
        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.headers["Retry-After"], "300")
        self.assertEqual(response.get_json()["error"],
                         "Too many requests. Please try again later.")

    def test_otp_manual_reset_and_password_reset_are_independently_limited(self):
        with patch.object(request_rate_limit.time, "monotonic", return_value=20):
            for path in (
                "/api/auth/request-otp",
                "/api/auth/request-manual-reset",
                "/api/auth/reset-password",
            ):
                self.assertEqual(self.client.post(path).status_code, 200)
                self.assertEqual(self.client.post(path).status_code, 429)

    def test_two_factor_login_verification_is_rate_limited(self):
        with patch.object(request_rate_limit.time, "monotonic", return_value=25):
            self.assertEqual(
                self.client.post("/api/auth/verify-2fa-login").status_code, 200)
            response = self.client.post("/api/auth/verify-2fa-login")
        self.assertEqual(response.status_code, 429)

    def test_global_api_limit_applies_to_non_auth_api_endpoints(self):
        self.app.config["API_RATE_LIMIT"] = 1
        with patch.object(request_rate_limit.time, "monotonic", return_value=30):
            self.assertEqual(self.client.get("/api/resource").status_code, 200)
            response = self.client.get("/api/resource")
        self.assertEqual(response.status_code, 429)

    def test_options_preflight_does_not_consume_api_limit(self):
        self.app.config["API_RATE_LIMIT"] = 1
        with patch.object(request_rate_limit.time, "monotonic", return_value=40):
            self.assertEqual(
                self.client.options("/api/resource").status_code, 200)
            self.assertEqual(self.client.get("/api/resource").status_code, 200)
            self.assertEqual(self.client.get("/api/resource").status_code, 429)

    def test_expired_window_allows_requests_again(self):
        with patch.object(request_rate_limit.time, "monotonic", side_effect=[10, 911]):
            self.assertEqual(
                self.client.post("/api/auth/request-otp").status_code, 200)
            self.assertEqual(
                self.client.post("/api/auth/request-otp").status_code, 200)

    def test_untrusted_forwarded_header_cannot_change_rate_limit_identity(self):
        with patch.object(request_rate_limit.time, "monotonic", return_value=50):
            first = self.client.post(
                "/api/auth/request-otp",
                environ_base={"REMOTE_ADDR": "192.0.2.10"},
                headers={"X-Forwarded-For": "198.51.100.10"},
            )
            second = self.client.post(
                "/api/auth/request-otp",
                environ_base={"REMOTE_ADDR": "192.0.2.10"},
                headers={"X-Forwarded-For": "203.0.113.10"},
            )
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 429)

    def test_invalid_nonpositive_limit_configuration_is_rejected(self):
        self.app.config["API_RATE_LIMIT"] = 0
        with self.assertRaisesRegex(ValueError, "API_RATE_LIMIT"):
            request_rate_limit.init_app(self.app)
