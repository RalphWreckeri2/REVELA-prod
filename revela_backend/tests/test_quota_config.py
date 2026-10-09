import unittest
from unittest.mock import patch

from api.utils.quota_config import load_api_quota_config
from api.utils.quota_ceilings import CloudMethodQuota


class ApiQuotaConfigTests(unittest.TestCase):

    def test_defaults_include_shared_text_search_allocation(self):
        config = load_api_quota_config({})

        self.assertEqual(config.text_search.daily, 80)
        self.assertEqual(config.text_search.monthly, 2500)
        self.assertEqual(
            dict(config.text_search_workflow_daily),
            {"registry_import": 40, "snap_pins": 20, "reverify": 20},
        )
        self.assertEqual(config.place_details.daily, 90)
        self.assertEqual(config.place_details.monthly, 3000)
        self.assertEqual(config.geocoding.daily, 1500)
        self.assertEqual(config.geocoding.monthly, 8000)
        self.assertEqual(config.legacy_nearby.daily, 120)
        self.assertEqual(config.legacy_nearby.monthly, 2000)
        self.assertEqual(config.nearby_new.daily, 0)
        self.assertEqual(config.nearby_new.monthly, 0)
        self.assertEqual(config.run_detection_monthly_scans, 10)

    def test_unverified_text_search_daily_overrides_are_clamped(self):
        config = load_api_quota_config({
            "TS_DAILY_CAP": "1000",
        })

        self.assertEqual(config.text_search.daily, 80)
        self.assertEqual(
            sum(config.text_search_workflow_daily.values()), 80
        )

    def test_canonical_daily_cap_precedes_legacy_alias(self):
        config = load_api_quota_config({
            "TS_DAILY_CAP": "75",
            "TEXT_SEARCH_DAILY_CAP": "60",
        })

        self.assertEqual(config.text_search.daily, 60)
        self.assertEqual(
            sum(config.text_search_workflow_daily.values()), 60
        )

    def test_verified_cloud_daily_quota_bounds_configured_cap(self):
        verified_quota = CloudMethodQuota(
            daily=250, per_minute=100, verified=True, source="test quota",
        )
        with patch(
            "api.utils.quota_config.cloud_quota_for",
            return_value=verified_quota,
        ):
            config = load_api_quota_config({
                "TEXT_SEARCH_DAILY_CAP": "400",
            })

        self.assertEqual(config.text_search.daily, 250)

    def test_legacy_environment_names_remain_supported(self):
        config = load_api_quota_config({
            "TS_DAILY_CAP": "75",
            "TS_MONTHLY_CAP": "1800",
            "PD_DAILY_CAP": "80",
            "PD_MONTHLY_CAP": "2200",
            "GEOCODE_DAILY_CAP": "700",
            "GEOCODE_MONTHLY_CAP": "4000",
            "PLACES_DAILY_CAP": "500",
            "PLACES_MONTHLY_CAP": "1000",
            "NEW_NEARBY_DAILY_CAP": "35",
            "NEW_NEARBY_MONTHLY_CAP": "600",
        })

        self.assertEqual(config.text_search.daily, 75)
        self.assertEqual(config.text_search.monthly, 1800)
        self.assertEqual(
            sum(config.text_search_workflow_daily.values()), 75
        )
        self.assertEqual(config.place_details.daily, 80)
        self.assertEqual(config.geocoding.monthly, 4000)
        self.assertEqual(config.legacy_nearby.daily, 120)
        self.assertEqual(config.nearby_new.monthly, 600)

    def test_lower_legacy_nearby_daily_override_is_honored(self):
        config = load_api_quota_config({"PLACES_DAILY_CAP": "60"})

        self.assertEqual(config.legacy_nearby.daily, 60)

    def test_workflow_caps_cannot_exceed_shared_text_search_cap(self):
        with self.assertRaisesRegex(ValueError, "must sum to no more than"):
            load_api_quota_config({
                "TEXT_SEARCH_DAILY_CAP": "300",
                "TEXT_SEARCH_REGISTRY_IMPORT_DAILY_CAP": "200",
                "TEXT_SEARCH_SNAP_PINS_DAILY_CAP": "100",
                "TEXT_SEARCH_REVERIFY_DAILY_CAP": "100",
            })

    def test_partial_workflow_overrides_share_remaining_daily_budget(self):
        config = load_api_quota_config({
            "TEXT_SEARCH_DAILY_CAP": "80",
            "TEXT_SEARCH_REGISTRY_IMPORT_DAILY_CAP": "40",
        })

        self.assertEqual(
            dict(config.text_search_workflow_daily),
            {"registry_import": 40, "snap_pins": 20, "reverify": 20},
        )

    def test_monthly_scan_allowance_is_bounded_by_nearby_budget(self):
        config = load_api_quota_config({
            "PLACES_MONTHLY_CAP": "600",
            "RUN_DETECTION_MAX_REQUESTS": "100",
            "RUN_DETECTION_MONTHLY_SCAN_LIMIT": "20",
        })

        self.assertEqual(config.run_detection_monthly_scans, 6)

    def test_monthly_scan_allowance_uses_selected_nearby_method(self):
        config = load_api_quota_config({
            "RUN_DETECTION_NEARBY_API": "new",
            "NEARBY_NEW_MONTHLY_CAP": "360",
            "RUN_DETECTION_MAX_REQUESTS": "120",
            "RUN_DETECTION_MONTHLY_SCAN_LIMIT": "10",
        })

        self.assertEqual(config.run_detection_monthly_scans, 3)

    def test_quota_resets_are_opt_in(self):
        self.assertFalse(load_api_quota_config({}).allow_quota_resets)
        self.assertTrue(
            load_api_quota_config(
                {"ALLOW_QUOTA_RESET": "1"}).allow_quota_resets
        )


if __name__ == "__main__":
    unittest.main()
