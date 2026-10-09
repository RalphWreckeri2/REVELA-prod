"""
Regression tests for the production CORS failure.

Symptom under test: the browser could not call https://api.revelasys.site from
https://www.revelasys.site and reported "No 'Access-Control-Allow-Origin'
header is present". Two configuration mistakes produced it -- `CORS_ORIGINS`
unset, and `CORS_ORIGINS` naming only the apex host without `www` -- so both
are pinned here along with OPTIONS preflight handling.

Security properties asserted alongside the fix:
  * a wildcard is never emitted (illegal with credentials),
  * an unlisted origin still receives no CORS headers.
"""

import sys
import types
import unittest
from unittest.mock import patch

from api.utils import cors_config


PRODUCTION_WWW = "https://www.revelasys.site"
PRODUCTION_APEX = "https://revelasys.site"
EVIL = "https://evil.example"


class OriginParsingTests(unittest.TestCase):
    """Pure parsing rules - no app boot required."""

    def test_blank_entries_and_whitespace_are_dropped(self):
        self.assertEqual(
            cors_config.parse_origins("  https://a.test , ,https://b.test ,"),
            ["https://a.test", "https://www.a.test",
             "https://b.test", "https://www.b.test"],
        )

    def test_trailing_slash_is_normalised(self):
        """`https://site/` never matches what a browser sends, so strip it."""
        self.assertEqual(
            cors_config.parse_origins("https://www.revelasys.site/"),
            [PRODUCTION_WWW, PRODUCTION_APEX],
        )

    def test_scheme_and_host_are_lowercased(self):
        self.assertEqual(
            cors_config.parse_origins("HTTPS://WWW.RevelaSys.Site"),
            [PRODUCTION_WWW, PRODUCTION_APEX],
        )

    def test_www_mirrors_to_apex_and_back(self):
        self.assertEqual(cors_config.mirror_www(PRODUCTION_WWW), PRODUCTION_APEX)
        self.assertEqual(cors_config.mirror_www(PRODUCTION_APEX), PRODUCTION_WWW)

    def test_mirroring_does_not_touch_non_https_or_hosted_values(self):
        self.assertEqual(cors_config.mirror_www("http://localhost:5173"),
                         "http://localhost:5173")
        self.assertEqual(cors_config.mirror_www("http://10.0.2.2:5000"),
                         "http://10.0.2.2:5000")
        self.assertIsNone(cors_config.mirror_www(None))

    def test_apex_only_config_also_allows_www(self):
        """The exact production misconfiguration must now be self-correcting."""
        self.assertIn(PRODUCTION_WWW, cors_config.parse_origins(PRODUCTION_APEX))

    def test_www_only_config_also_allows_apex(self):
        self.assertIn(PRODUCTION_APEX, cors_config.parse_origins(PRODUCTION_WWW))

    def test_duplicates_are_collapsed(self):
        parsed = cors_config.parse_origins(
            f"{PRODUCTION_WWW},{PRODUCTION_APEX},{PRODUCTION_WWW}/"
        )
        self.assertEqual(sorted(parsed), sorted([PRODUCTION_WWW, PRODUCTION_APEX]))

    def test_unset_env_defaults_to_production_hosts(self):
        allowed = cors_config.build_allowed_origins(None)
        self.assertIn(PRODUCTION_WWW, allowed)
        self.assertIn(PRODUCTION_APEX, allowed)

    def test_empty_env_defaults_to_production_hosts(self):
        self.assertIn(PRODUCTION_WWW, cors_config.build_allowed_origins(""))

    def test_env_value_overrides_production_defaults(self):
        allowed = cors_config.build_allowed_origins("https://staging.revelasys.site")
        self.assertNotIn(PRODUCTION_WWW, allowed)
        self.assertIn("https://staging.revelasys.site", allowed)
        self.assertIn("https://www.staging.revelasys.site", allowed)

    def test_development_loopback_always_available(self):
        allowed = cors_config.build_allowed_origins(PRODUCTION_WWW)
        self.assertTrue(
            any(getattr(o, "pattern", "").startswith(r"http://localhost")
                for o in allowed)
        )

    def test_never_emits_a_wildcard(self):
        """`*` is illegal alongside Access-Control-Allow-Credentials."""
        for raw in (None, "", PRODUCTION_APEX, "https://a.test"):
            with self.subTest(raw=raw):
                self.assertNotIn("*", cors_config.build_allowed_origins(raw))

    def test_wildcard_in_config_is_replaced_by_production_defaults(self):
        """A stray `*` must not silently disable CORS protection."""
        allowed = cors_config.build_allowed_origins("*")
        self.assertNotIn("*", allowed)
        self.assertIn(PRODUCTION_WWW, allowed)


def _build_app(cors_env):
    """Boot the real application factory with a given CORS_ORIGINS value."""
    # `google-genai` is pinned in requirements.txt but absent from some local
    # virtualenvs; stub it so importing the analytics blueprint succeeds. This
    # is unrelated to CORS.
    if "google.genai" not in sys.modules:
        stub = types.ModuleType("google.genai")
        stub.Client = object
        stub.types = types.SimpleNamespace(
            GenerateContentConfig=object, Part=object
        )
        sys.modules["google.genai"] = stub
        import google

        google.genai = stub

    import importlib
    import os as _os

    import config

    importlib.reload(config)
    import app as app_module

    importlib.reload(app_module)

    previous = _os.environ.pop("CORS_ORIGINS", None)
    try:
        if cors_env is not None:
            _os.environ["CORS_ORIGINS"] = cors_env
        return app_module.create_app()
    finally:
        _os.environ.pop("CORS_ORIGINS", None)
        if previous is not None:
            _os.environ["CORS_ORIGINS"] = previous


class LoginCorsIntegrationTests(unittest.TestCase):
    """
    End-to-end against the real factory: the reported failing request and its
    preflight, for the allowed and disallowed cases.
    """

    @classmethod
    def setUpClass(cls):
        cls.app = _build_app("https://www.revelasys.site,https://revelasys.site")
        cls.client = cls.app.test_client()

    def _post_login(self, origin):
        return self.client.post(
            "/api/auth/login",
            headers={"Origin": origin, "Content-Type": "application/json"},
            json={"email": "nobody@example.com", "password": "wrong"},
        )

    def _preflight_login(self, origin):
        return self.client.options(
            "/api/auth/login",
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type",
            },
        )

    # ── allowed origins ──────────────────────────────────────────────────────
    def test_login_from_www_origin_returns_allow_origin(self):
        response = self._post_login(PRODUCTION_WWW)
        self.assertEqual(
            response.headers.get("Access-Control-Allow-Origin"), PRODUCTION_WWW
        )
        self.assertEqual(
            response.headers.get("Access-Control-Allow-Credentials"), "true"
        )

    def test_login_from_apex_origin_returns_allow_origin(self):
        response = self._post_login(PRODUCTION_APEX)
        self.assertEqual(
            response.headers.get("Access-Control-Allow-Origin"), PRODUCTION_APEX
        )

    def test_login_response_varies_on_origin(self):
        """Shared caches must not serve one origin's header to another."""
        self.assertIn("Origin", self._post_login(PRODUCTION_WWW).headers.get("Vary", ""))

    def test_login_reaches_the_route_rather_than_being_blocked(self):
        """A CORS failure hides the real status; assert the route actually ran."""
        response = self._post_login(PRODUCTION_WWW)
        self.assertIn(response.status_code, (400, 401))
        self.assertIn("error", response.get_json())

    # ── OPTIONS preflight ────────────────────────────────────────────────────
    def test_preflight_from_allowed_origin_is_answered(self):
        response = self._preflight_login(PRODUCTION_WWW)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.headers.get("Access-Control-Allow-Origin"), PRODUCTION_WWW
        )
        methods = response.headers.get("Access-Control-Allow-Methods", "")
        self.assertIn("POST", methods)

    def test_preflight_advertises_the_authorization_header(self):
        """The frontend sends Bearer tokens, so it must be preflight-allowed."""
        response = self.client.options(
            "/api/auth/login",
            headers={
                "Origin": PRODUCTION_WWW,
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "authorization,content-type",
            },
        )
        allowed = response.headers.get("Access-Control-Allow-Headers", "").lower()
        self.assertIn("authorization", allowed)
        self.assertIn("content-type", allowed)

    # ── disallowed origins ───────────────────────────────────────────────────
    def test_disallowed_origin_gets_no_cors_headers(self):
        response = self._post_login(EVIL)
        self.assertIsNone(response.headers.get("Access-Control-Allow-Origin"))
        self.assertIsNone(response.headers.get("Access-Control-Allow-Credentials"))

    def test_disallowed_origin_preflight_gets_no_cors_headers(self):
        response = self._preflight_login(EVIL)
        self.assertIsNone(response.headers.get("Access-Control-Allow-Origin"))

    def test_http_origin_is_not_confused_with_https(self):
        """Scheme is part of the origin; http must not inherit https's grant."""
        response = self._post_login("http://www.revelasys.site")
        self.assertIsNone(response.headers.get("Access-Control-Allow-Origin"))

    def test_lookalike_host_is_rejected(self):
        for origin in (
            "https://www.revelasys.site.evil.example",
            "https://evil.example/https://www.revelasys.site",
            "https://revelasys.site.evil.example",
        ):
            with self.subTest(origin=origin):
                response = self._post_login(origin)
                self.assertIsNone(
                    response.headers.get("Access-Control-Allow-Origin")
                )


class CorsHeadersSurviveErrorResponsesTests(unittest.TestCase):
    """
    Guards against a server-side failure being misreported as a CORS problem:
    the browser cannot distinguish "no header" from "request never ran", so
    every status the app can return must still carry the header.
    """

    @classmethod
    def setUpClass(cls):
        cls.app = _build_app(PRODUCTION_WWW)
        cls.client = cls.app.test_client()

        @cls.app.route("/api/_cors_probe_boom")
        def boom():
            raise RuntimeError("probe")

    def test_500_still_carries_cors_headers(self):
        response = self.client.get(
            "/api/_cors_probe_boom", headers={"Origin": PRODUCTION_WWW}
        )
        self.assertEqual(response.status_code, 500)
        self.assertEqual(
            response.headers.get("Access-Control-Allow-Origin"), PRODUCTION_WWW
        )

    def test_404_still_carries_cors_headers(self):
        response = self.client.get(
            "/api/no-such-route", headers={"Origin": PRODUCTION_WWW}
        )
        self.assertEqual(response.status_code, 404)
        self.assertEqual(
            response.headers.get("Access-Control-Allow-Origin"), PRODUCTION_WWW
        )

    def test_401_still_carries_cors_headers(self):
        response = self.client.get(
            "/api/flags/places-usage", headers={"Origin": PRODUCTION_WWW}
        )
        self.assertEqual(response.status_code, 401)
        self.assertEqual(
            response.headers.get("Access-Control-Allow-Origin"), PRODUCTION_WWW
        )


class MissingEnvironmentVariableTests(unittest.TestCase):
    """The original failure: no CORS_ORIGINS set at all."""

    def test_production_frontend_still_works_without_the_variable(self):
        app = _build_app(None)
        client = app.test_client()
        response = client.post(
            "/api/auth/login",
            headers={"Origin": PRODUCTION_WWW, "Content-Type": "application/json"},
            json={"email": "nobody@example.com", "password": "wrong"},
        )
        self.assertEqual(
            response.headers.get("Access-Control-Allow-Origin"), PRODUCTION_WWW
        )


class ApexOnlyConfigurationTests(unittest.TestCase):
    """The other original failure: only the apex host was configured."""

    def test_apex_only_config_still_allows_www(self):
        app = _build_app(PRODUCTION_APEX)
        client = app.test_client()
        response = client.post(
            "/api/auth/login",
            headers={"Origin": PRODUCTION_WWW, "Content-Type": "application/json"},
            json={"email": "nobody@example.com", "password": "wrong"},
        )
        self.assertEqual(
            response.headers.get("Access-Control-Allow-Origin"), PRODUCTION_WWW
        )


if __name__ == "__main__":
    unittest.main()
