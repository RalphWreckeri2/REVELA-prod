"""WLC configuration service tests.

These lock the two properties the OPS/WLC settings flow depends on:

  1. The interview-derived preset is 68% risk / 7% sector / 25% proximity.
  2. Saving weights must not erase already-persisted sector overrides. The
     Settings UI no longer sends the ``sectors`` field, so ``update_wlc_config``
     has to merge into the stored config rather than replace it.

Every test runs against a throwaway config file; the repository's real
``wlc_config.json`` is never touched.
"""

import json
import os
import tempfile
import unittest
from copy import deepcopy

from api.analytics import service as wlc


class WlcConfigServiceTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._original_config_file = wlc.CONFIG_FILE
        wlc.CONFIG_FILE = os.path.join(self._tmp.name, "wlc_config.json")
        self._original_cache = wlc._wlc_config_cache
        wlc._wlc_config_cache = None

    def tearDown(self):
        wlc.CONFIG_FILE = self._original_config_file
        wlc._wlc_config_cache = self._original_cache
        self._tmp.cleanup()

    def _persist(self, payload):
        with open(wlc.CONFIG_FILE, "w") as handle:
            json.dump(payload, handle)
        wlc._wlc_config_cache = None  # force the next read to hit the file

    def test_default_config_is_the_interview_68_7_25_preset(self):
        self.assertEqual(wlc.DEFAULT_CONFIG["w1_risk"], 68)
        self.assertEqual(wlc.DEFAULT_CONFIG["w2_sector"], 7)
        self.assertEqual(wlc.DEFAULT_CONFIG["w3_distance"], 25)
        self.assertEqual(wlc.DEFAULT_CONFIG["sectors"], {})

    def test_update_without_sectors_preserves_saved_sectors(self):
        saved_sectors = {"Poblacion": 80, "San Miguel": 40}
        self._persist({
            "w1_risk": 68, "w2_sector": 7, "w3_distance": 25,
            "bplo_lat": 13.960413, "bplo_lng": 121.114547,
            "sectors": saved_sectors,
        })

        # The Settings UI now sends weights only; `sectors` is omitted.
        updated, error = wlc.update_wlc_config({
            "w1_risk": 50, "w2_sector": 20, "w3_distance": 30,
        })

        self.assertIsNone(error)
        self.assertEqual(updated["w1_risk"], 50)
        self.assertEqual(updated["sectors"], saved_sectors)

        # It must survive the write to disk, not just the in-memory cache.
        wlc._wlc_config_cache = None
        self.assertEqual(wlc.get_wlc_config()["sectors"], saved_sectors)

    def test_invalid_updates_do_not_change_disk_or_cached_policy(self):
        self._persist(deepcopy(wlc.DEFAULT_CONFIG))
        original = deepcopy(wlc.get_wlc_config())
        with open(wlc.CONFIG_FILE) as handle:
            original_text = handle.read()
        invalid = [
            {"w1_risk": -1}, {"w1_risk": 101}, {"w1_risk": "68"},
            {"w1_risk": True}, {"w1_risk": float("nan")}, {"w3_distance": float("inf")},
            {"w1_risk": 50},
            {"bplo_lat": 91}, {"bplo_lng": -181}, {"bplo_lat": None},
            {"sectors": []}, {"sectors": {"Brgy": -1}}, {"sectors": {"Brgy": float("nan")}},
            {"sectors": {"Brgy": True}}, {"sectors": {"": 50}}, {"typo": 1}, [],
        ]
        for update in invalid:
            with self.subTest(update=update):
                with self.assertRaises(ValueError):
                    wlc.update_wlc_config(update)
                self.assertEqual(wlc.get_wlc_config(), original)
                with open(wlc.CONFIG_FILE) as handle:
                    self.assertEqual(handle.read(), original_text)

    def test_decimal_weights_are_accepted_without_silent_renormalization(self):
        updated, error = wlc.update_wlc_config({"w1_risk": 68.1, "w2_sector": 7, "w3_distance": 24.9})
        self.assertIsNone(error)
        self.assertEqual(updated["w1_risk"], 68.1)

    def test_invalid_persisted_weights_fall_back_to_safe_defaults(self):
        self._persist({**deepcopy(wlc.DEFAULT_CONFIG), "w1_risk": -2})
        with self.assertLogs("revela.analytics", level="WARNING"):
            self.assertEqual(wlc.get_wlc_config(), wlc.DEFAULT_CONFIG)

    def test_reset_does_not_share_mutable_sector_defaults(self):
        reset, error = wlc.reset_wlc_config()
        self.assertIsNone(error)
        self.assertEqual([reset[key] for key in ("w1_risk", "w2_sector", "w3_distance")], [68, 7, 25])
        reset["sectors"]["Changed"] = 70
        self.assertEqual(wlc.DEFAULT_CONFIG["sectors"], {})


if __name__ == "__main__":
    unittest.main()
