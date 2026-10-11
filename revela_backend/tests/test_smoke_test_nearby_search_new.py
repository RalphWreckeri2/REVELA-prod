import importlib.util
import io
import os
from pathlib import Path
import unittest
from unittest.mock import MagicMock, patch


SCRIPT_PATH = Path(__file__).parents[1] / \
    "scripts" / "smoke_test_nearby_search_new.py"


def load_smoke_script():
    spec = importlib.util.spec_from_file_location(
        "nearby_smoke_test", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class NearbySmokePayloadTests(unittest.TestCase):
    def test_payload_uses_only_table_a_exclusions_and_one_result(self):
        smoke = load_smoke_script()
        payload = smoke.build_request(13.9667, 121.1167, 100)

        self.assertNotIn("place_of_worship", payload["excludedTypes"])
        self.assertNotIn("police_station", payload["excludedTypes"])
        self.assertIn("police", payload["excludedTypes"])
        self.assertEqual(payload["maxResultCount"], 1)
        self.assertEqual(
            payload["locationRestriction"]["circle"]["radius"], 100)
        self.assertIn("places.formattedAddress", smoke.FIELD_MASK)

    def test_http_error_reports_sanitized_status_and_message_only(self):
        smoke = load_smoke_script()
        response = MagicMock(status_code=400)
        response.json.return_value = {
            "error": {
                "status": "INVALID_ARGUMENT",
                "message": (
                    "bad request key=AIzaSyTestSecretValue1234567890 "
                    "password=super-secret"
                ),
            }
        }

        with (
            patch.dict(os.environ, {"GOOGLE_MAPS_API_KEY": "offline-key"}),
            patch.object(smoke.requests, "post", return_value=response) as post,
            patch("builtins.input", return_value=smoke.CONFIRMATION_TEXT),
            patch("sys.stdout", new_callable=io.StringIO) as stdout,
            patch("sys.stderr", new_callable=io.StringIO) as stderr,
        ):
            result = smoke.main([
                "--send", "--latitude", "13.9667",
                "--longitude", "121.1167", "--radius-meters", "100",
            ])

        self.assertEqual(result, 1)
        post.assert_called_once()
        output = stdout.getvalue() + stderr.getvalue()
        self.assertIn("HTTP status: 400", output)
        self.assertIn("Google error status: INVALID_ARGUMENT", output)
        self.assertIn("Google error message: bad request", output)
        self.assertIn("key=[REDACTED]", output)
        self.assertIn("password=[REDACTED]", output)
        self.assertNotIn("AIzaSyTestSecretValue1234567890", output)
        self.assertNotIn("super-secret", output)
        self.assertNotIn("X-Goog-Api-Key", output)
        self.assertNotIn("offline-key", output)


if __name__ == "__main__":
    unittest.main()
