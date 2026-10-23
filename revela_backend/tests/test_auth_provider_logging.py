import os
import unittest
from unittest.mock import Mock, patch

from api.auth import service


class AuthProviderLoggingTests(unittest.TestCase):
    PHONE = "639171234567"
    OTP = "731904"
    SECRET = "PROVIDER-SECRET-VALUE"

    def _send_with_response(self, response):
        with (
            patch.dict(os.environ, {"PHILSMS_API_TOKEN": "test-token"}),
            patch.object(service, "format_phone_number",
                         return_value=self.PHONE),
            patch.object(service.requests, "post", return_value=response),
            self.assertLogs(service.__name__, level="INFO") as captured,
        ):
            result = service.send_otp_via_philsms(self.PHONE, self.OTP)
        output = "\n".join(captured.output)
        for sensitive in (self.PHONE, self.OTP, self.SECRET):
            self.assertNotIn(sensitive, output)
        return result, output

    def test_http_error_does_not_log_provider_body_or_personal_data(self):
        response = Mock(
            status_code=502,
            text=f"OTP={self.OTP} phone={self.PHONE} secret={self.SECRET}",
            ok=False,
        )
        result, output = self._send_with_response(response)
        self.assertFalse(result)
        self.assertIn("status=502", output)
        self.assertNotIn(response.text, output)

    def test_provider_error_does_not_log_raw_json(self):
        raw_body = {
            "status": "failed",
            "message": f"recipient {self.PHONE}, OTP {self.OTP}",
            "metadata": {"secret": self.SECRET},
        }
        response = Mock(status_code=200, ok=True)
        response.json.return_value = raw_body
        result, output = self._send_with_response(response)
        self.assertFalse(result)
        self.assertIn("provider reported an error", output)
        self.assertNotIn(raw_body["message"], output)
        self.assertNotIn(str(raw_body["metadata"]), output)

    def test_success_does_not_log_recipient_or_otp(self):
        response = Mock(status_code=200, ok=True)
        response.json.return_value = {"status": "success"}
        result, output = self._send_with_response(response)
        self.assertTrue(result)
        self.assertIn("delivery succeeded", output)

    def test_transport_error_does_not_log_exception_text(self):
        exception = service.requests.exceptions.ConnectionError(
            f"OTP={self.OTP} phone={self.PHONE} secret={self.SECRET}")
        with (
            patch.dict(os.environ, {"PHILSMS_API_TOKEN": "test-token"}),
            patch.object(service, "format_phone_number",
                         return_value=self.PHONE),
            patch.object(service.requests, "post", side_effect=exception),
            self.assertLogs(service.__name__, level="WARNING") as captured,
        ):
            result = service.send_otp_via_philsms(self.PHONE, self.OTP)
        self.assertFalse(result)
        output = "\n".join(captured.output)
        for sensitive in (self.PHONE, self.OTP, self.SECRET, str(exception)):
            self.assertNotIn(sensitive, output)
        self.assertIn("ConnectionError", output)

    def test_email_transport_error_does_not_log_exception_text(self):
        exception = RuntimeError(
            f"OTP={self.OTP} email=person@example.com secret={self.SECRET}")
        with (
            patch.object(service.requests, "post", side_effect=exception),
            self.assertLogs(service.__name__, level="WARNING") as captured,
        ):
            result = service.send_otp_email("person@example.com", self.OTP)
        self.assertFalse(result)
        output = "\n".join(captured.output)
        for sensitive in (self.OTP, "person@example.com", self.SECRET):
            self.assertNotIn(sensitive, output)
        self.assertIn("RuntimeError", output)


if __name__ == "__main__":
    unittest.main()
