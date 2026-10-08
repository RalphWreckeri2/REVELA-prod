import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from api.registry.service import (
    normalize_business_address,
    _clean_upper,
    _normalise_registration_type,
)


class NormalizeBusinessAddressTests(unittest.TestCase):
    def test_keeps_vague_local_descriptors_without_blank_out(self):
        self.assertIsNotNone(normalize_business_address(
            "District IV Mataasnakahoy Batangas"))
        self.assertIsNotNone(normalize_business_address(
            "PUROK 5 Kinalaglagan Mataasnakahoy Batangas"))
        self.assertIsNotNone(normalize_business_address(
            "Barangay II-A Mataasnakahoy Batangas"))

    def test_normalize_keeps_real_street_addresses_but_removes_location_noise(self):
        self.assertEqual(
            normalize_business_address(
                "V. Templo St. District IV Mataasnakahoy Batangas"),
            "V. TEMPLO STREET",
        )
        self.assertEqual(
            normalize_business_address(
                "Rizal St. District III Mataasnakahoy Batangas"),
            "RIZAL STREET",
        )

    def test_clean_upper_transforms_to_uppercase(self):
        self.assertEqual(_clean_upper("sari-sari store"), "SARI-SARI STORE")
        self.assertEqual(_clean_upper("Single Proprietorship"), "SINGLE PROPRIETORSHIP")
        self.assertEqual(_clean_upper("Retail of goods"), "RETAIL OF GOODS")
        self.assertEqual(_clean_upper("micro"), "MICRO")
        self.assertIsNone(_clean_upper(None))
        self.assertIsNone(_clean_upper(""))
        self.assertIsNone(_clean_upper("   "))

    def test_normalise_registration_type_returns_uppercase(self):
        self.assertEqual(_normalise_registration_type("New"), "NEW")
        self.assertEqual(_normalise_registration_type("new"), "NEW")
        self.assertEqual(_normalise_registration_type("NEW"), "NEW")
        self.assertEqual(_normalise_registration_type("Renewal"), "RENEWAL")
        self.assertEqual(_normalise_registration_type("renew"), "RENEWAL")
        self.assertEqual(_normalise_registration_type("RENEWAL"), "RENEWAL")
        self.assertIsNone(_normalise_registration_type(None))
        self.assertIsNone(_normalise_registration_type(""))


if __name__ == "__main__":
    unittest.main()

