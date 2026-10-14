"""Offline tests for the isolated Nearby Search (New) pilot safety gate."""

import unittest

from api.utils.nearby_barangay_pilot import (
    PILOT_ENABLED_ENV,
    PILOT_HARD_MAX_REQUESTS,
    PILOT_MAX_REQUESTS_ENV,
    load_pilot_config,
    validate_pilot_authorization,
)
from api.utils.quota_config import load_api_quota_config


class NearbyBarangayPilotConfigTests(unittest.TestCase):

    def test_default_configuration_refuses_activation(self):
        config = load_pilot_config({})

        self.assertFalse(config.enabled)
        self.assertIsNone(config.max_requests)
        self.assertIsNone(config.configuration_error)
        self.assertFalse(validate_pilot_authorization(
            config, True, True, 1, 1,
        )[0])

    def test_enabled_gate_requires_request_limit(self):
        config = load_pilot_config({PILOT_ENABLED_ENV: "1"})

        self.assertFalse(config.enabled)
        self.assertIsNone(config.max_requests)
        self.assertIn(PILOT_MAX_REQUESTS_ENV, config.configuration_error)

    def test_invalid_gate_value_fails_closed(self):
        config = load_pilot_config({
            PILOT_ENABLED_ENV: "true",
            PILOT_MAX_REQUESTS_ENV: "1",
        })

        self.assertFalse(config.enabled)
        self.assertIsNotNone(config.configuration_error)

    def test_missing_zero_invalid_and_oversized_limits_fail_closed(self):
        for raw_limit in (
            None, "", "not-an-integer", "0", "-1", "6", "1.5", " 1 ",
        ):
            with self.subTest(raw_limit=raw_limit):
                config = load_pilot_config({
                    PILOT_ENABLED_ENV: "1",
                    PILOT_MAX_REQUESTS_ENV: raw_limit,
                })
                self.assertFalse(config.enabled)
                self.assertIsNone(config.max_requests)
                self.assertIsNotNone(config.configuration_error)

        self.assertEqual(PILOT_HARD_MAX_REQUESTS, 5)

    def test_all_authorization_gates_must_be_satisfied(self):
        config = load_pilot_config({
            PILOT_ENABLED_ENV: "1",
            PILOT_MAX_REQUESTS_ENV: "3",
        })
        valid = (config, True, True, 42, 2)

        self.assertEqual(validate_pilot_authorization(*valid), (True, None))
        for index, rejected_value in (
            (1, False),
            (1, None),
            (2, False),
            (2, None),
            (3, 0),
            (3, -1),
            (3, "42"),
            (3, True),
            (4, 0),
            (4, -1),
            (4, "2"),
            (4, True),
        ):
            with self.subTest(argument=index, value=rejected_value):
                args = list(valid)
                args[index] = rejected_value
                self.assertFalse(validate_pilot_authorization(*args)[0])

    def test_requested_budget_cannot_exceed_configured_or_hard_limit(self):
        config = load_pilot_config({
            PILOT_ENABLED_ENV: "1",
            PILOT_MAX_REQUESTS_ENV: "2",
        })
        self.assertFalse(
            validate_pilot_authorization(config, True, True, 42, 3)[0]
        )

        hard_limited_config = load_pilot_config({
            PILOT_ENABLED_ENV: "1",
            PILOT_MAX_REQUESTS_ENV: str(PILOT_HARD_MAX_REQUESTS),
        })
        self.assertFalse(
            validate_pilot_authorization(
                hard_limited_config, True, True, 42,
                PILOT_HARD_MAX_REQUESTS + 1,
            )[0]
        )

    def test_existing_nearby_quota_defaults_are_unchanged(self):
        quota_config = load_api_quota_config({})

        self.assertEqual(quota_config.legacy_nearby.daily, 120)
        self.assertEqual(quota_config.legacy_nearby.monthly, 2000)
        self.assertEqual(quota_config.nearby_new.daily, 0)
        self.assertEqual(quota_config.nearby_new.monthly, 0)


if __name__ == "__main__":
    unittest.main()
