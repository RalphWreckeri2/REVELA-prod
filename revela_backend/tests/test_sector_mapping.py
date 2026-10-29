import unittest

from api.analytics.sector_mapping import (
    clean_major_type,
    decompose_registry_activity,
    display_sector_for_major,
    normalize_sector_text,
)


def master_line(line_id, line, major):
    return {
        "psic_line_id": line_id,
        "line_of_business": line,
        "normalized_line_of_business": normalize_sector_text(line),
        "major_type_clean": clean_major_type(major),
        "normalized_major_type": normalize_sector_text(clean_major_type(major)),
    }


class SectorMappingTests(unittest.TestCase):
    def setUp(self):
        self.lines = [
            master_line(1, "Cafe or coffee shops", "FOOD SERVICE ACTIVITIES"),
            master_line(2, "Retail selling in sari-sari stores", "RETAIL TRADE"),
            master_line(
                6,
                "Pawnshop operations",
                "FINANCIAL AND INSURANCE ACTIVITIE",
            ),
            master_line(3, "Foreign Exchange Dealing/ Money Changing (Money Service Businesses (MSBs)", "FINANCIAL AND INSURANCE ACTIVITIE"),
            master_line(7, "Remittance and transfer operations (MSBs)", "FINANCIAL AND INSURANCE ACTIVITIE"),
            master_line(8, "Retail sale of electronic load", "RETAIL TRADE"),
            master_line(4, "Duplicate activity", "MANUFACTURING"),
            master_line(5, "Duplicate-activity", "MANUFACTURING"),
        ]
        self.sectors = {
            normalize_sector_text("FOOD SERVICE ACTIVITIES"): {
                "display_sector_key": "food_drink",
                "display_sector_label": "Food and drink",
            },
            normalize_sector_text("RETAIL TRADE"): {
                "display_sector_key": "retail",
                "display_sector_label": "Retail",
            },
            normalize_sector_text("FINANCIAL AND INSURANCE ACTIVITIES"): {
                "display_sector_key": "finance_professional",
                "display_sector_label": "Finance and professional",
            },
            normalize_sector_text("MANUFACTURING"): {
                "display_sector_key": "manufacturing",
                "display_sector_label": "Manufacturing",
            },
        }

    def test_normalization_and_major_type_cleanup(self):
        self.assertEqual(normalize_sector_text("Cafe OR Coffee Shops"), "cafeorcoffeeshops")
        self.assertEqual(
            clean_major_type(" SECTION H. transportation and storage "),
            "TRANSPORTATION AND STORAGE",
        )
        self.assertEqual(
            clean_major_type(" financial and insurance activitie "),
            "FINANCIAL AND INSURANCE ACTIVITIES",
        )

    def test_approved_major_type_display_sector_defaults(self):
        self.assertEqual(display_sector_for_major("MINING AND QUARRYING")[:2],
                         ("agriculture_mining", "Agriculture and mining"))
        for major in (
            "ACTIVITIES OF HOUSEHOLDS AS EMPLOYERS; UNDIFFERENTIATED GOODS-AND SERVICES-PRODUCING ACTIVITIES OF HOUSEHOLDS FOR OWN USE",
            "PUBLIC ADMINISTRATION AND DEFENSE; COMPULSORY SOCIAL SECURITY",
            "ACTIVITIES OF EXTRA-TERRITORIAL ORGANIZATIONS AND BODIES",
        ):
            self.assertEqual(
                display_sector_for_major(major)[:2],
                ("education_health_other_services", "Education, health and other services"),
            )

    def test_exact_and_composite_values_match(self):
        exact = decompose_registry_activity("CAFE OR COFFEE SHOPS", self.lines, self.sectors)
        combo = decompose_registry_activity(
            "CAFE OR COFFEE SHOPS, RETAIL SELLING IN SARI-SARI STORES",
            self.lines,
            self.sectors,
        )
        self.assertEqual(exact["status"], "matched")
        self.assertEqual(combo["status"], "combo")
        self.assertEqual([row["psic_line_id"] for row in combo["lines"]], [1, 2])
        self.assertEqual(combo["primary_sector_key"], "food_drink")

    def test_unbalanced_master_description_is_matched_as_source_text(self):
        result = decompose_registry_activity(
            "PAWNSHOP OPERATIONS, FOREIGN EXCHANGE DEALING/ MONEY CHANGING "
            "(MONEY SERVICE BUSINESSES (MSBS)",
            self.lines,
            self.sectors,
        )
        self.assertEqual(result["status"], "combo")
        self.assertEqual(result["primary_sector_key"], "finance_professional")

    def test_duplicate_normalized_lines_with_same_sector_resolve_deterministically(self):
        result = decompose_registry_activity("Duplicate activity", self.lines, self.sectors)
        self.assertEqual(result["status"], "matched")
        self.assertEqual(result["candidates"], 2)
        self.assertEqual([row["psic_line_id"] for row in result["lines"]], [4])

    def test_duplicate_normalized_lines_with_different_sectors_remain_ambiguous(self):
        lines = list(self.lines)
        lines[-1] = {
            **lines[-1],
            "normalized_major_type": normalize_sector_text("RETAIL TRADE"),
        }
        result = decompose_registry_activity("Duplicate activity", lines, self.sectors)
        self.assertEqual(result["status"], "ambiguous")
        self.assertEqual(result["candidates"], 2)

    def test_leftover_text_is_unmatched(self):
        result = decompose_registry_activity("Cafe or coffee shops plus unknown", self.lines, self.sectors)
        self.assertEqual(result["status"], "unmatched")


if __name__ == "__main__":
    unittest.main()
