import unittest

from api.registry.service import normalize_business_address


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
            "V. Templo Street",
        )
        self.assertEqual(
            normalize_business_address(
                "Rizal St. District III Mataasnakahoy Batangas"),
            "Rizal Street",
        )


if __name__ == "__main__":
    unittest.main()
