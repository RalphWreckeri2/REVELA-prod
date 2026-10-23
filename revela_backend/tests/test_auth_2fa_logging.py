import io
import logging
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

from flask import Flask

from api.auth import routes


class TwoFactorSetupLoggingTests(unittest.TestCase):
    def _run_setup(self, *, code, secret, valid=True, save_success=True):
        app = Flask(__name__)
        with app.test_request_context(
                "/api/auth/verify-2fa-setup", method="POST",
                json={} if code is None else {"code": code}):
            with (
                patch.object(routes, "get_jwt_identity", return_value="17"),
                patch.object(routes, "get_user_2fa_secret", return_value=secret),
                patch.object(routes, "verify_totp_code", return_value=valid) as verify,
                patch.object(routes, "enable_user_2fa",
                             return_value=save_success) as enable,
            ):
                stdout = io.StringIO()
                stderr = io.StringIO()
                log_output = io.StringIO()
                handler = logging.StreamHandler(log_output)
                root_logger = logging.getLogger()
                root_logger.addHandler(handler)
                try:
                    with redirect_stdout(stdout), redirect_stderr(stderr):
                        response, status = routes.verify_2fa_setup.__wrapped__()
                finally:
                    root_logger.removeHandler(handler)
                    handler.close()

        return (response, status, stdout.getvalue(), stderr.getvalue(),
                log_output.getvalue(), verify, enable)

    def _assert_no_sensitive_output(self, result, secret, code):
        response, status, stdout, stderr, logs, _verify, _enable = result
        combined_output = stdout + stderr + logs
        self.assertNotIn(secret, combined_output)
        if code:
            self.assertNotIn(code, combined_output)
        self.assertEqual(combined_output, "")
        return response, status

    def test_successful_setup_verification_does_not_log_secret_or_codes(self):
        secret, code = "TOPSECRETBASE32VALUE", "123456"
        result = self._run_setup(code=code, secret=secret)
        response, status = self._assert_no_sensitive_output(
            result, secret, code)
        self.assertEqual(status, 200)
        self.assertEqual(response.get_json(), {
            "message": "2FA enabled successfully",
        })
        self.assertTrue(result[-1].called)

    def test_invalid_code_does_not_log_secret_or_code(self):
        secret, code = "TOPSECRETBASE32VALUE", "654321"
        result = self._run_setup(code=code, secret=secret, valid=False)
        response, status = self._assert_no_sensitive_output(
            result, secret, code)
        self.assertEqual(status, 400)
        self.assertEqual(response.get_json(), {"error": "Invalid 2FA code"})
        self.assertFalse(result[-1].called)

    def test_missing_code_does_not_log_secret_or_attempt_verification(self):
        secret = "TOPSECRETBASE32VALUE"
        result = self._run_setup(code=None, secret=secret)
        response, status = self._assert_no_sensitive_output(
            result, secret, None)
        self.assertEqual(status, 400)
        self.assertEqual(response.get_json(), {"error": "Missing 2FA code"})
        self.assertFalse(result[-2].called)
        self.assertFalse(result[-1].called)

    def test_missing_secret_does_not_log_code_or_attempt_verification(self):
        code = "123456"
        result = self._run_setup(code=code, secret=None)
        response, status = self._assert_no_sensitive_output(
            result, "TOPSECRETBASE32VALUE", code)
        self.assertEqual(status, 400)
        self.assertEqual(response.get_json(), {
            "error": "No 2FA setup found for user",
        })
        self.assertFalse(result[-2].called)
        self.assertFalse(result[-1].called)

    def test_save_failure_does_not_log_secret_or_valid_code(self):
        secret, code = "TOPSECRETBASE32VALUE", "123456"
        result = self._run_setup(
            code=code, secret=secret, valid=True, save_success=False)
        response, status = self._assert_no_sensitive_output(
            result, secret, code)
        self.assertEqual(status, 500)
        self.assertEqual(response.get_json(), {
            "error": "Failed to save 2FA settings",
        })
        self.assertTrue(result[-1].called)
