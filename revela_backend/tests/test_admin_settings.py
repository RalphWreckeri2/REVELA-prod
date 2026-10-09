"""
Tests for the admin-only "API Usage & Testing" surface.

Covers the four areas the Phase 3 brief calls out — quota enforcement,
authentication, settings persistence, and integration with the existing
workflows — plus the property that matters most for requirement 5: a cached
fixture replay must not touch the usage ledger, while a live request must.
"""

import unittest
from unittest.mock import MagicMock, patch

from flask import Flask

from api.admin_settings import routes as admin_routes
from api.middleware import decorators
from api.utils import quota_settings, quota_ceilings, test_mode
from api.utils.quota_ceilings import CloudMethodQuota


def make_client(case, role="Admin", authenticated=True):
    """
    Build a Flask test client with the blueprint and a stubbed JWT.

    The decorator patches are started (not used as a `with` block) because the
    patches must stay active while the test issues its request, and are torn
    down via the test case's cleanup.
    """
    app = Flask(__name__)
    app.register_blueprint(
        admin_routes.admin_settings_bp, url_prefix="/api/admin-settings"
    )

    def fake_verify():
        if not authenticated:
            raise RuntimeError("Missing Authorization Header")

    for target, attribute, value in (
        (decorators, "verify_jwt_in_request", fake_verify),
        (decorators, "get_jwt_identity", lambda: 1),
        (decorators, "get_current_role", lambda: role),
        (decorators, "find_user_by_id", lambda _i: {"isActive": True}),
    ):
        patcher = patch.object(target, attribute, value)
        patcher.start()
        case.addCleanup(patcher.stop)

    app.config["TESTING"] = True
    return app.test_client()


class QuotaValidationTests(unittest.TestCase):
    """Effective cap = env baseline + overrides, clamped to Cloud ceilings."""

    def setUp(self):
        quota_settings.invalidate()

    def _patched(self, stored):
        return patch.object(
            quota_settings.app_settings, "load_all", return_value=dict(stored)
        )

    def test_baseline_used_when_nothing_overridden(self):
        with self._patched({}):
            quota_settings.invalidate()
            self.assertEqual(
                quota_settings.cap("quota.text_search.daily"),
                quota_settings.QUOTA_FIELDS[
                    "quota.text_search.daily"
                ]["baseline"],
            )

    def test_override_is_applied_and_reported_as_admin_override(self):
        # Must stay at or below the recorded Cloud ceiling for this method.
        stored = {"quota.text_search.daily": 75}
        with self._patched(stored):
            quota_settings.invalidate()
            self.assertEqual(quota_settings.cap("quota.text_search.daily"), 75)
            snapshot = quota_settings.snapshot()
            self.assertEqual(
                snapshot["quota.text_search.daily"]["source"], "admin_override"
            )
        quota_settings.invalidate()

    def test_override_above_cloud_ceiling_is_rejected(self):
        """Only a verified Cloud value is an enforceable ceiling."""
        key = "quota.text_search.daily"
        verified = CloudMethodQuota(
            daily=500, per_minute=600, verified=True, source="test fixture"
        )
        with patch.object(
            quota_settings, "cloud_quota_for", return_value=verified
        ):
            clean, errors = quota_settings.validate_patch({key: 501})
        self.assertEqual(clean, {})
        self.assertTrue(errors)
        self.assertIn("verified Google Cloud quota", errors[0])

    def test_exactly_the_cloud_ceiling_is_accepted(self):
        verified = CloudMethodQuota(
            daily=500, per_minute=600, verified=True, source="test fixture"
        )
        with patch.object(
            quota_settings, "cloud_quota_for", return_value=verified
        ):
            clean, errors = quota_settings.validate_patch({
                "quota.text_search.daily": 500,
            })
        self.assertEqual(errors, [])
        self.assertEqual(clean["quota.text_search.daily"], 500)

    def test_unverified_cloud_report_cannot_raise_above_env_baseline(self):
        key = "quota.text_search.daily"
        baseline = quota_settings.QUOTA_FIELDS[key]["baseline"]
        clean, errors = quota_settings.validate_patch({key: baseline + 1})

        self.assertEqual(clean, {})
        self.assertTrue(any(
            "until the google cloud quota is verified" in error.lower() for error in errors))

    def test_negative_value_is_rejected(self):
        clean, errors = quota_settings.validate_patch({
            "quota.text_search.daily": -5,
        })
        self.assertEqual(clean, {})
        self.assertTrue(errors)

    def test_unknown_key_is_rejected(self):
        clean, errors = quota_settings.validate_patch({
            "quota.made_up": 10,
        })
        self.assertEqual(clean, {})
        self.assertIn("Unknown setting: quota.made_up", errors)

    def test_workflow_caps_may_not_exceed_shared_daily_cap(self):
        clean, errors = quota_settings.validate_patch({
            "quota.text_search.daily": 60,
            "quota.text_search.workflow.registry_import": 40,
            "quota.text_search.workflow.snap_pins": 40,
            "quota.text_search.workflow.reverify": 40,
        })
        # Each value is individually legal; only their sum is not, and the
        # whole patch is refused rather than partially applied.
        self.assertEqual(len(clean), 4)
        self.assertTrue(any("total 120" in e for e in errors))

    def test_lowering_daily_cap_redistributes_workflow_caps(self):
        """Lowering the shared cap alone must still succeed."""
        clean, errors = quota_settings.validate_patch({
            "quota.text_search.daily": 60,
        })
        self.assertEqual(errors, [])
        self.assertEqual(clean["quota.text_search.daily"], 60)
        redistributed = sum(
            clean[key] for key in (
                "quota.text_search.workflow.registry_import",
                "quota.text_search.workflow.snap_pins",
                "quota.text_search.workflow.reverify",
            )
        )
        self.assertEqual(redistributed, 60)

    def test_workflow_caps_may_equal_shared_daily_cap(self):
        clean, errors = quota_settings.validate_patch({
            "quota.text_search.daily": 60,
            "quota.text_search.workflow.registry_import": 20,
            "quota.text_search.workflow.snap_pins": 20,
            "quota.text_search.workflow.reverify": 20,
        })
        self.assertEqual(errors, [])
        self.assertEqual(clean["quota.text_search.workflow.reverify"], 20)

    def test_scan_limit_cannot_outrun_the_nearby_budget(self):
        """A scan limit the Nearby monthly cap cannot fund is refused."""
        clean, errors = quota_settings.validate_patch({
            "quota.legacy_nearby.monthly": 200,
            "run_detection.max_requests": 120,
            "run_detection.monthly_scan_limit": 10,
        })
        self.assertTrue(any("cannot be funded" in e for e in errors))
        # Individually legal values are still returned, but `save()` refuses the
        # patch outright while `errors` is non-empty.
        self.assertEqual(clean["run_detection.monthly_scan_limit"], 10)

    def test_scan_limit_within_the_budget_is_accepted(self):
        clean, errors = quota_settings.validate_patch({
            "quota.legacy_nearby.monthly": 2000,
            "run_detection.max_requests": 120,
            "run_detection.monthly_scan_limit": 10,
        })
        self.assertEqual(errors, [])
        self.assertEqual(clean["run_detection.monthly_scan_limit"], 10)

    def test_stored_override_that_became_invalid_falls_back_to_baseline(self):
        """Lowering a Cloud ceiling in code must neutralise stale overrides."""
        key = "quota.text_search.daily"
        baseline = quota_settings.QUOTA_FIELDS[key]["baseline"]
        with self._patched({key: baseline + 5000}):
            quota_settings.invalidate()
            self.assertEqual(quota_settings.cap(key), baseline)
        quota_settings.invalidate()

    def test_patch_is_atomic_on_failure(self):
        with patch.object(
            quota_settings.app_settings, "save_many"
        ) as save:
            result, error = quota_settings.save({
                "quota.text_search.daily": -1,
            })
        self.assertIsNone(result)
        self.assertTrue(error)
        save.assert_not_called()


class QuotaEnforcementTests(unittest.TestCase):
    """The live reservation path must use the effective cap, not a constant."""

    def test_legacy_reservation_uses_effective_caps(self):
        from api.flags import service

        fake_mysql = MagicMock()
        with patch.object(service, "mysql", fake_mysql), \
                patch.object(service, "_ensure_budget_tables"), \
                patch.object(
                    service, "reserve_usage_slot",
                    return_value=(False, "daily_quota_exceeded"),
        ) as reserve, \
                patch.object(quota_settings, "cap", side_effect=lambda key: {
                    "quota.legacy_nearby.monthly": 4242,
                    "quota.legacy_nearby.daily": 7,
                }.get(key, 0)):
            with self.assertRaises(service.PlacesBudgetExceeded) as raised:
                service._reserve_places_call("nearby")

        reserve.assert_called_once()
        self.assertEqual(reserve.call_args.args[3], 4242)
        self.assertEqual(reserve.call_args.args[4], 7)
        self.assertIn("daily 7", str(raised.exception))

    def test_nearby_new_stays_disabled_at_zero_caps(self):
        from api.flags import service

        with patch.dict("os.environ", {"GOOGLE_MAPS_API_KEY": "server-key"}), \
                patch.object(service, "RUN_DETECTION_NEARBY_API", "new"), \
                patch.object(quota_settings, "cap", side_effect=lambda key: 0):
            with self.assertRaises(service.PlacesBudgetExceeded) as raised:
                service._new_nearby_request(13.9667, 121.1167, 850)
        self.assertIn("disabled", str(raised.exception))

    def test_work_slice_respects_effective_request_cap(self):
        from api.flags import service

        service._places_run_state.started_at = service.time.monotonic()
        service._places_run_state.calls = {
            "legacy_nearby": 5, "new_nearby": 0,
        }
        with patch.object(quota_settings, "cap", side_effect=lambda key: {
            "run_detection.max_seconds": 90,
            "run_detection.max_requests": 5,
        }.get(key, 0)), patch.object(test_mode, "is_enabled", return_value=False):
            self.assertTrue(service._detection_work_budget_reached())


class AuthenticationTests(unittest.TestCase):
    """Every settings route is admin-only."""

    ROUTES = (
        ("get", "/api/admin-settings/usage"),
        ("get", "/api/admin-settings/quota"),
        ("put", "/api/admin-settings/quota"),
        ("post", "/api/admin-settings/quota/reset"),
        ("get", "/api/admin-settings/test-mode"),
        ("put", "/api/admin-settings/test-mode"),
        ("post", "/api/admin-settings/test-mode/reset"),
        ("post", "/api/admin-settings/test-mode/fixtures/purge"),
        ("post", "/api/admin-settings/matching-dry-run"),
    )

    def test_unauthenticated_is_rejected_with_401(self):
        client = make_client(self, authenticated=False)
        for method, path in self.ROUTES:
            with self.subTest(path=path):
                response = getattr(client, method)(
                    path, json={}
                )
                self.assertEqual(response.status_code, 401)

    def test_non_admin_is_rejected_with_403(self):
        client = make_client(self, role="Inspector")
        for method, path in self.ROUTES:
            with self.subTest(path=path):
                response = getattr(client, method)(path, json={})
                self.assertEqual(response.status_code, 403)

    def test_admin_reaches_read_routes(self):
        client = make_client(self, role="Admin")
        with patch.object(
            quota_settings.app_settings, "load_all", return_value={}
        ):
            response = client.get("/api/admin-settings/quota")
        self.assertEqual(response.status_code, 200)
        self.assertIn("fields", response.get_json())

    def test_super_admin_reaches_read_routes(self):
        client = make_client(self, role="SUPER_ADMIN")
        with patch.object(
            quota_settings.app_settings, "load_all", return_value={}
        ):
            response = client.get("/api/admin-settings/quota")
        self.assertEqual(response.status_code, 200)

    def test_admin_request_fails_closed_when_account_lookup_errors(self):
        client = make_client(self, role="Admin")
        with patch.object(
            decorators, "find_user_by_id", side_effect=RuntimeError("db offline")
        ):
            response = client.post("/api/admin-settings/test-mode/reset")

        self.assertEqual(response.status_code, 503)
        self.assertEqual(
            response.get_json(),
            {"error": "Authorization could not be verified."},
        )

    def test_stale_admin_role_claim_is_rejected(self):
        client = make_client(self, role="Admin")
        with patch.object(
            decorators,
            "find_user_by_id",
            return_value={"isActive": True, "userRole": "Inspector"},
        ):
            response = client.get("/api/admin-settings/quota")

        self.assertEqual(response.status_code, 401)
        self.assertEqual(
            response.get_json()["message"],
            "Account permissions changed. Sign in again.",
        )

    def test_empty_body_is_rejected_for_write_routes(self):
        client = make_client(self, role="Admin")
        for method, path in (
            ("put", "/api/admin-settings/quota"),
            ("put", "/api/admin-settings/test-mode"),
        ):
            with self.subTest(path=path):
                response = getattr(client, method)(path, json={})
                self.assertEqual(response.status_code, 400)


class SettingsPersistenceTests(unittest.TestCase):

    def setUp(self):
        quota_settings.invalidate()
        self.store = {}

        def fake_load():
            return dict(self.store)

        def fake_save(entries, user_id=None):
            self.store.update(entries)
            return len(entries), None

        def fake_delete(keys):
            removed = 0
            for key in keys:
                if key in self.store:
                    del self.store[key]
                    removed += 1
            return removed, None

        patches = [
            patch.object(quota_settings.app_settings, "load_all", fake_load),
            patch.object(quota_settings.app_settings, "save_many", fake_save),
            patch.object(quota_settings.app_settings,
                         "delete_many", fake_delete),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        quota_settings.invalidate()

    def test_saved_setting_survives_a_cache_expiry(self):
        result, error = quota_settings.save({"quota.geocoding.daily": 250})
        self.assertIsNone(error)
        self.assertEqual(result["saved"], 1)

        quota_settings.invalidate()  # simulate the TTL expiring
        self.assertEqual(quota_settings.cap("quota.geocoding.daily"), 250)

    def test_actor_id_is_recorded_on_write(self):
        client = make_client(self, role="Admin")
        with patch.object(
            quota_settings.app_settings, "save_many",
            return_value=(1, None),
        ) as save, patch.object(
            admin_routes, "get_jwt_identity", lambda: 1
        ):
            response = client.put(
                "/api/admin-settings/quota",
                json={"quota.geocoding.daily": 300},
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(save.call_args.kwargs["user_id"], 1)

    def test_reset_restores_the_environment_baseline(self):
        quota_settings.save({"quota.geocoding.daily": 250})
        quota_settings.invalidate()
        self.assertEqual(quota_settings.cap("quota.geocoding.daily"), 250)

        result, error = quota_settings.clear_overrides()
        self.assertIsNone(error)
        self.assertEqual(result["removed"], 1)
        quota_settings.invalidate()
        self.assertEqual(
            quota_settings.cap("quota.geocoding.daily"),
            quota_settings.QUOTA_FIELDS["quota.geocoding.daily"]["baseline"],
        )

    def test_invalid_write_leaves_stored_settings_untouched(self):
        quota_settings.save({"quota.geocoding.daily": 250})
        quota_settings.invalidate()
        _, error = quota_settings.save({"quota.geocoding.daily": -1})
        self.assertTrue(error)
        quota_settings.invalidate()
        self.assertEqual(quota_settings.cap("quota.geocoding.daily"), 250)


class TestModeTests(unittest.TestCase):
    """Test Mode bounds scope and replays fixtures without spending quota."""

    def setUp(self):
        self.config = {}
        patches = [
            patch.object(
                test_mode.app_settings, "load_all", lambda: dict(self.config)
            ),
            patch.object(
                test_mode.app_settings, "save_many",
                side_effect=lambda entries, user_id=None: (
                    self.config.update(entries) or (len(entries), None)
                ),
            ),
            patch.object(test_mode, "is_enabled", lambda: test_mode._read_bool(
                self.config.get("test_mode.enabled"), False
            )),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def test_disabled_by_default(self):
        self.assertFalse(test_mode.is_enabled())
        self.assertEqual(
            test_mode.get_config()["test_mode.fixture_policy"],
            "cache_then_live",
        )

    def test_enable_round_trips(self):
        result, error = test_mode.save_config({"test_mode.enabled": True})
        self.assertIsNone(error)
        self.assertTrue(result["config"]["test_mode.enabled"])
        self.assertTrue(test_mode.is_enabled())

    def test_out_of_range_value_is_rejected(self):
        _, error = test_mode.save_config({"test_mode.max_requests": 9999})
        self.assertIn("between 1 and 120", error)
        self.assertEqual(
            self.config.get("test_mode.max_requests"), None
        )

    def test_unknown_policy_is_rejected(self):
        _, error = test_mode.save_config({"test_mode.fixture_policy": "yolo"})
        self.assertIn("cache_then_live", error)

    def test_google_fixture_storage_requires_server_approval(self):
        _, error = test_mode.save_config({
            "test_mode.fixture_storage_enabled": True,
        })
        self.assertIn(
            "GOOGLE_PLACES_TEST_FIXTURE_STORAGE_APPROVED=1", error
        )

    def test_fixture_ttl_cannot_exceed_thirty_days(self):
        _, error = test_mode.save_config({
            "test_mode.fixture_ttl_days": 31,
        })
        self.assertIn("between 1 and 30", error)

    def test_fixture_key_changes_with_request_parameters(self):
        a = test_mode.fixture_key("nearby", "https://x", {"radius": 850})
        b = test_mode.fixture_key("nearby", "https://x", {"radius": 400})
        c = test_mode.fixture_key("nearby", "https://x", {"radius": 850})
        self.assertNotEqual(a, b)
        self.assertEqual(a, c)

    def test_fixture_key_is_independent_of_param_order(self):
        a = test_mode.fixture_key("n", "https://x", {"a": 1, "b": 2})
        b = test_mode.fixture_key("n", "https://x", {"b": 2, "a": 1})
        self.assertEqual(a, b)

    def test_cache_only_policy_raises_on_a_miss(self):
        self.config["test_mode.enabled"] = True
        self.config["test_mode.fixture_policy"] = "cache_only"
        with patch.object(test_mode, "lookup_fixture", return_value=None):
            with self.assertRaises(test_mode.TestModeCacheMiss):
                test_mode.resolve_request("nearby", "https://x")

    def test_cache_then_live_falls_through_to_a_real_call(self):
        self.config["test_mode.enabled"] = True
        with patch.object(test_mode, "lookup_fixture", return_value=None):
            cached, _ = test_mode.resolve_request("nearby", "https://x")
        self.assertIsNone(cached)

    def test_fixture_storage_off_never_reads_existing_cache(self):
        self.config["test_mode.enabled"] = True
        with patch.object(test_mode, "lookup_fixture") as lookup:
            cached, _ = test_mode.resolve_request("nearby", "https://x")
        self.assertIsNone(cached)
        lookup.assert_not_called()

    def test_fixture_sanitizer_drops_unneeded_google_fields(self):
        payload = {
            "status": "OK",
            "next_page_token": None,
            "results": [{
                "place_id": "pid",
                "name": "Test Store",
                "rating": 4.8,
                "photos": [{"photo_reference": "private"}],
                "geometry": {"location": {"lat": 13.9, "lng": 121.1}},
                "types": ["store"],
                "business_status": "OPERATIONAL",
                "vicinity": "Poblacion",
            }],
        }

        sanitized = test_mode._minimal_fixture_payload("nearby", payload)

        self.assertEqual(set(sanitized["results"][0]), {
            "place_id", "name", "geometry", "types",
            "business_status", "vicinity",
        })
        self.assertNotIn("rating", sanitized["results"][0])
        self.assertIsNone(test_mode._minimal_fixture_payload(
            "nearby", {**payload, "next_page_token": "next"}
        ))

    @patch("api.utils.test_mode._ensure_table")
    @patch("api.utils.test_mode.mysql")
    @patch("api.utils.test_mode.get_config")
    def test_fixture_lookup_rejects_rows_older_than_configured_ttl(
        self, get_config, mysql, _ensure
    ):
        get_config.return_value = {"test_mode.fixture_ttl_days": 14}
        mysql.connection.cursor.return_value.fetchone.return_value = None

        self.assertIsNone(test_mode.lookup_fixture("nearby:key"))

        query, params = mysql.connection.cursor.return_value.execute.call_args.args
        self.assertIn("createdAt >= DATE_SUB(NOW(), INTERVAL %s DAY)", query)
        self.assertEqual(params, ("nearby:key", 14))

    def test_cached_hit_returns_a_response_shim(self):
        self.config["test_mode.enabled"] = True
        self.config["test_mode.fixture_storage_enabled"] = True
        payload = {"status": "OK", "results": [{"name": "Cached Shop"}]}
        with patch.dict("os.environ", {
            "GOOGLE_PLACES_TEST_FIXTURE_STORAGE_APPROVED": "1",
        }), patch.object(test_mode, "_cleanup_expired_fixtures"), \
                patch.object(test_mode, "lookup_fixture", return_value=payload):
            cached, _ = test_mode.resolve_request("nearby", "https://x")
        self.assertIsNotNone(cached)
        self.assertEqual(cached.status_code, 200)
        self.assertTrue(cached.from_cache)
        self.assertEqual(cached.json()["results"][0]["name"], "Cached Shop")

    def test_disabled_test_mode_never_consults_the_cache(self):
        with patch.object(test_mode, "lookup_fixture") as lookup:
            cached, _ = test_mode.resolve_request("nearby", "https://x")
        lookup.assert_not_called()
        self.assertIsNone(cached)


class FixtureAccountingTests(unittest.TestCase):
    """
    Requirement 5: a replay costs nothing, a live call is always reserved.

    This is what removes the need to truncate usage tables during testing.
    """

    def test_fixture_hit_skips_the_usage_reservation(self):
        from api.flags import service

        payload = {"status": "OK", "results": [{"name": "Cached"}]}
        with patch.object(service, "test_mode") as mode:
            mode.is_enabled.return_value = True
            mode.resolve_request.return_value = (
                test_mode.FixtureResponse(payload), None,
            )
            with patch.object(
                service, "_reserve_places_call"
            ) as reserve, patch.object(service.http, "get") as get:
                response = service._places_get(
                    "nearby", "https://x", params={})

        reserve.assert_not_called()
        get.assert_not_called()
        self.assertEqual(response.json()["results"][0]["name"], "Cached")

    def test_live_request_still_reserves_even_with_test_mode_on(self):
        from api.flags import service

        live = MagicMock(status_code=200)
        live.json.return_value = {"status": "OK", "results": []}
        with patch.object(service, "test_mode") as mode:
            mode.is_enabled.return_value = True
            mode.resolve_request.return_value = (None, None)
            mode.remember_response.return_value = True
            with patch.object(
                service, "_reserve_places_call"
            ) as reserve, patch.object(
                service.http, "get", return_value=live
            ) as get:
                response = service._places_get(
                    "nearby", "https://x", params={})

        reserve.assert_called_once()
        get.assert_called_once()
        self.assertEqual(response.status_code, 200)
        mode.remember_response.assert_called_once()

    def test_fixture_replay_is_counted_separately_from_real_requests(self):
        from api.flags import service

        service._places_run_state.calls = {
            "legacy_nearby": 0, "new_nearby": 0,
            "legacy_nearby_initial": 0, "legacy_nearby_adaptive": 0,
        }
        service._places_run_state.query_kind = "initial"
        payload = {"status": "OK", "results": []}
        with patch.object(service, "test_mode") as mode:
            mode.is_enabled.return_value = True
            mode.resolve_request.return_value = (
                test_mode.FixtureResponse(payload), None,
            )
            with patch.object(service, "_reserve_places_call"):
                service._places_get("nearby", "https://x", params={})

        calls = service._places_run_state.calls
        self.assertEqual(calls["legacy_nearby"], 0)
        self.assertEqual(calls.get("legacy_nearby_fixture"), 1)


class TestModeScopeTests(unittest.TestCase):
    """Test Mode narrows the geographic scope of a run."""

    def test_grid_is_capped_to_the_configured_point_count(self):
        from api.flags import service

        with patch.object(test_mode, "is_enabled", return_value=True), \
                patch.object(test_mode, "get_config", return_value={
                    "test_mode.enabled": True,
                    "test_mode.grid_step_degrees": 0.009,
                    "test_mode.radius_m": 850,
                    "test_mode.max_grid_points": 4,
                    "test_mode.max_requests": 20,
                    "test_mode.fixture_policy": "cache_then_live",
                    "test_mode.fixture_ttl_days": 14,
                }):
            points = service._grid_points()

        self.assertEqual(len(points), 4)

    def test_radius_reflects_test_mode(self):
        from api.flags import service

        self.assertEqual(service._detection_radius_m(), 850)
        with patch.object(test_mode, "is_enabled", return_value=True), \
                patch.object(test_mode, "get_config", return_value={
                    "test_mode.enabled": True,
                    "test_mode.radius_m": 300,
                    "test_mode.grid_step_degrees": 0.009,
                    "test_mode.max_grid_points": 4,
                    "test_mode.max_requests": 20,
                    "test_mode.fixture_policy": "cache_then_live",
                    "test_mode.fixture_ttl_days": 14,
                }):
            self.assertEqual(service._detection_radius_m(), 300)

    def test_full_grid_when_test_mode_is_off(self):
        from api.flags import service

        with patch.object(test_mode, "is_enabled", return_value=False), \
                patch.object(quota_settings, "cap", side_effect=lambda key: 0.009):
            points = service._grid_points()
        self.assertEqual(len(points), 70)


class UsageReportTests(unittest.TestCase):
    """The report must keep the three limit concepts apart."""

    def setUp(self):
        self.report = None
        with patch.object(quota_settings.app_settings, "load_all", return_value={}), \
                patch("api.utils.usage_report.read_usage", return_value={
                    "month": 100, "day": 10,
                }), patch(
                    "api.utils.usage_report.read_daily_usage", return_value=5
        ):
            quota_settings.invalidate()
            from api.utils import usage_report
            with patch.object(usage_report, "mysql", MagicMock()):
                self.report = usage_report.build_usage_report()

    def test_every_method_reports_all_three_limit_concepts(self):
        self.assertTrue(self.report["methods"])
        for method in self.report["methods"]:
            with self.subTest(method=method["method"]):
                for key in (
                    "google_cloud_quota", "revela_app_cap", "request_pacing",
                ):
                    self.assertIn(key, method)
                    self.assertIsNotNone(method[key])

    def test_unverified_cloud_quota_is_flagged_not_asserted(self):
        text_search = next(
            m for m in self.report["methods"] if m["method"] == "text_search"
        )
        cloud = text_search["google_cloud_quota"]
        self.assertFalse(cloud["verified"])
        self.assertIn(
            "confirm", cloud["source"].lower() + cloud["note"].lower())

    def test_app_cap_records_its_source(self):
        text_search = next(
            m for m in self.report["methods"] if m["method"] == "text_search"
        )
        self.assertIn(
            text_search["revela_app_cap"]["daily_cap_source"],
            ("env", "admin_override"),
        )

    def test_legacy_nearby_pacing_is_reported_as_enforced(self):
        legacy = next(
            m for m in self.report["methods"]
            if m["method"] == "nearby_search_legacy"
        )
        self.assertTrue(legacy["request_pacing"]["enforced"])
        self.assertGreaterEqual(
            legacy["request_pacing"]["min_interval_ms"], 300)

    def test_workflow_allocations_are_reported(self):
        self.assertEqual(
            set(self.report["text_search_workflows"]),
            {"registry_import", "snap_pins", "reverify"},
        )

    def test_totals_are_labelled_as_estimates(self):
        self.assertTrue(self.report["totals"]["pricing_is_estimate"])


class MatchingDryRunTests(unittest.TestCase):

    def setUp(self):
        self.client = make_client(self, role="Admin")

    def test_rejects_empty_candidates(self):
        response = self.client.post(
            "/api/admin-settings/matching-dry-run", json={"candidates": []}
        )
        self.assertEqual(response.status_code, 400)

    def test_rejects_oversized_batch(self):
        response = self.client.post(
            "/api/admin-settings/matching-dry-run",
            json={"candidates": [{} for _ in range(501)]},
        )
        self.assertEqual(response.status_code, 400)

    def test_dry_run_makes_no_google_request_and_writes_no_usage(self):
        registry = [{
            "businessID": 1, "barangayID": 1,
            "businessName": "Mabini Store",
            "applicationStatus": "Active",
            "businessLine": "Retail", "businessType": "Retail",
            "businessAddress": "Poblacion",
            "latitude": 13.9667, "longitude": 121.1167,
        }]
        with patch.object(
            admin_routes, "_load_registry", return_value=registry
        ), patch("api.flags.service.http.get") as get, \
                patch("api.flags.service.reserve_usage_slot") as reserve:
            response = self.client.post(
                "/api/admin-settings/matching-dry-run",
                json={"candidates": [
                    {"name": "Mabini Store", "lat": 13.9667, "lng": 121.1167,
                     "types": ["store"], "address": "Poblacion"},
                    {"name": "Totally Different", "lat": 13.97, "lng": 121.12},
                ]},
            )

        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertEqual(body["google_requests_made"], 0)
        self.assertEqual(body["usage_rows_written"], 0)
        self.assertEqual(body["candidates_evaluated"], 2)
        get.assert_not_called()
        reserve.assert_not_called()

    def test_bad_coordinates_are_reported_per_candidate(self):
        with patch.object(admin_routes, "_load_registry", return_value=[]):
            response = self.client.post(
                "/api/admin-settings/matching-dry-run",
                json={"candidates": [{"name": "X", "lat": "abc", "lng": 1}]},
            )
        self.assertEqual(response.status_code, 200)
        self.assertIn("error", response.get_json()["results"][0])


if __name__ == "__main__":
    unittest.main()
