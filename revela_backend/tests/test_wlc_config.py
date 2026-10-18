"""WLC configuration service tests.

These lock the two properties the OPS/WLC settings flow depends on:

  1. The single shipped preset is 68% risk / 7% sector / 25% distance.
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

    def test_default_config_is_the_68_7_25_preset(self):
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


if __name__ == "__main__":
    unittest.main()
