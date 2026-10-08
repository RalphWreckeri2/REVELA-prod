import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from api.utils.name_match import name_match, parse_name
from api.flags.service import _match_poi_to_registry, _within_municipality
from api.registry.places_resolver import _is_within_municipal_bounds


class GroundTruthAcceptanceGateTests(unittest.TestCase):
    """
    TICKET-08: 100-Record Ground Truth Acceptance Gate & Verification Suite.
    Validates all 100 benchmark commercial cases representing Mataasnakahoy establishments.
    
    CARDINAL RULE: Confident-but-wrong pins must equal ZERO (0).
    Any ambiguity must downgrade to 'review' or 'no_match'.
    """

    # ─────────────────────────────────────────────────────────────────────────────
    # GROUP 1: Category-Conflicting & Sibling-Owner Pairs (30 Cases)
    # Failure Mode Prevented: Same family surname/compound with conflicting sectors.
    # Expected: Score <= 0.45, Match Status == 'no_match' / Never 'auto'.
    # ─────────────────────────────────────────────────────────────────────────────
    def test_group1_category_conflicting_pairs_score_under_cutoff(self):
        conflicting_pairs = [
            # (Reg Name, POI Name, Reg Line, POI Types)
            ("Silva's Pharmacy", "Silva's Apartment", "Pharmacy", ("lodging", "apartment")),
            ("Jose Store", "Jose Bakery", "General Merchandise", ("bakery",)),
            ("Maria's Bakeshop", "Maria's Laundry Shop", "Bakery", ("laundry",)),
            ("Santos Hardware", "Santos Auto Repair", "Hardware", ("car_repair",)),
            ("Dimaano Water Refilling", "Dimaano Funeral Services", "Water Refilling", ("funeral_home",)),
            ("Hernandez Dental Clinic", "Hernandez Meat Shop", "Dental Clinic", ("butcher_shop", "grocery_store")),
            ("Reyes Car Wash", "Reyes Tailoring", "Car Wash", ("tailor", "clothing_store")),
            ("Garcia Barber Shop", "Garcia Auto Supply", "Barber Shop", ("car_repair",)),
            ("Mendoza Veterinary Clinic", "Mendoza Eatery", "Veterinary Clinic", ("restaurant", "food")),
            ("Dela Cruz Optical", "Dela Cruz Internet Cafe", "Optical Clinic", ("internet_cafe",)),
            ("Bautista Rice Dealer", "Bautista Motor Parts", "Rice Dealer", ("auto_parts_store",)),
            ("Aquino Pharmacy", "Aquino Dormitory", "Pharmacy", ("lodging", "boarding_house")),
            ("Ramos Bakery", "Ramos Construction Supplies", "Bakery", ("hardware_store",)),
            ("Castillo Water Station", "Castillo Memorial Chapel", "Water Station", ("funeral_home",)),
            ("Flores Beauty Salon", "Flores Meat Market", "Beauty Salon", ("meat_market",)),
            ("Villanueva Clinic", "Villanueva Auto Supply", "Medical Clinic", ("auto_parts_store",)),
            ("Tolentino Diagnostic Lab", "Tolentino Eatery", "Medical Laboratory", ("restaurant",)),
            ("Morales Pawnshop", "Morales Car Wash", "Pawnshop", ("car_wash",)),
            ("Ocampo Drugstore", "Ocampo Boarding House", "Drugstore", ("lodging",)),
            ("Naval Bakeshop", "Naval Welding Shop", "Bakeshop", ("welding", "repair")),
            ("Perez Grocery", "Perez Tailoring Shop", "Grocery", ("tailor",)),
            ("Mercado Farm Supply", "Mercado Optical Clinic", "Agricultural Supply", ("optician",)),
            ("De Leon Veterinary Clinic", "De Leon Restaurant", "Veterinary Clinic", ("restaurant",)),
            ("Rivera Dental Clinic", "Rivera Hardware", "Dental Clinic", ("hardware_store",)),
            ("Cruz Purified Water", "Cruz Memorial Park", "Water Station", ("cemetery",)),
            ("Manalo Store", "Manalo Vulcanizing Shop", "Sari-sari store", ("tire_repair",)),
            ("Ilagan Bakeshop", "Ilagan Furniture", "Bakery", ("furniture_store",)),
            ("Dimaculangan Rice Mill", "Dimaculangan Hair Salon", "Rice Mill", ("hair_care",)),
            ("Recto Pharmacy", "Recto Apartments", "Pharmacy", ("apartment", "lodging")),
            ("Laurel Drugstore", "Laurel Lodging", "Drugstore", ("hotel", "lodging")),
        ]

        self.assertEqual(len(conflicting_pairs), 30, "Group 1 must contain exactly 30 test records.")

        confident_wrong_count = 0
        for reg_name, poi_name, reg_line, poi_types in conflicting_pairs:
            score, reason = name_match(reg_name, poi_name, reg_line=reg_line, poi_types=poi_types)
            self.assertLessEqual(
                score, 0.45,
                f"False match risk: {reg_name} vs {poi_name} scored {score:.3f} > 0.45 ({reason})"
            )

            # Test through detection matcher
            registry_entry = {
                "businessID": "BIZ-GRP1",
                "businessName": reg_name,
                "businessLine": reg_line,
                "barangayID": 1,
                "latitude": 13.9667,
                "longitude": 121.1167
            }
            # POI 15m away (same compound)
            matched, dist, sim, status = _match_poi_to_registry(
                poi_name, 13.96671, 121.11671, [registry_entry], poi_barangay_id=1
            )
            if status == "auto":
                confident_wrong_count += 1

        self.assertEqual(confident_wrong_count, 0, "FATAL: Confident-wrong pins must be strictly 0.")

    # ─────────────────────────────────────────────────────────────────────────────
    # GROUP 2: Synonym & Trade Name Elaboration Pairs (25 Cases)
    # Failure Mode Prevented: False rejection on valid trade elaborations & synonyms.
    # Expected: Score >= 0.80, Match Status == 'auto'.
    # ─────────────────────────────────────────────────────────────────────────────
    def test_group2_synonym_and_elaboration_pairs_auto_snap(self):
        valid_pairs = [
            ("Silva's Pharmacy", "Silva Drugstore", "Pharmacy", ("pharmacy", "drugstore")),
            ("Mercedes Hardware", "Mercedes Hardware & Construction Supply", "Hardware", ("hardware_store",)),
            ("Mataasnakahoy Bakeshop", "Mataasnakahoy Bakery", "Bakery", ("bakery",)),
            ("Aling Nena Carinderia", "Aling Nena Eatery", "Food", ("restaurant",)),
            ("Batangas Water Station", "Batangas Water Refilling", "Water", ("water_refilling",)),
            ("San Jose Medical Clinic", "San Jose Health Clinic", "Clinic", ("doctor", "health")),
            ("Poblacion Meat Shop", "Poblacion Butchery", "Meat", ("butcher_shop",)),
            ("Calingatan Sari-Sari Store", "Calingatan Retail Store", "Retail", ("store",)),
            ("Bayorbor Vulcanizing", "Bayorbor Tire Repair", "Auto", ("car_repair",)),
            ("Kinalaglagan Coffee Shop", "Kinalaglagan Cafe", "Coffee", ("cafe",)),
            ("Loob Mini Mart", "Loob Convenience Store", "Retail", ("convenience_store",)),
            ("Lumanglipa Agri Supply", "Lumanglipa Agricultural Supplies", "Agri", ("farm_supply",)),
            ("Nangkaan Food House", "Nangkaan Restaurant", "Food", ("restaurant",)),
            ("San Sebastian Poultry Supply", "San Sebastian Feeds Supply", "Poultry", ("feed_store",)),
            ("Santol Rice Trading", "Santol Rice Dealer", "Rice", ("grocery_store",)),
            ("Bubuyan Hair Salon", "Bubuyan Barber Shop", "Personal Care", ("hair_care",)),
            ("Upa Motor Parts", "Upa Motorcycle Supplies", "Auto", ("auto_parts_store",)),
            ("Manggahan Dental Center", "Manggahan Dental Clinic", "Dental", ("dentist",)),
            ("Barako Coffee Roasters", "Barako Roastery", "Coffee", ("cafe",)),
            ("Golden Bakeshop", "Golden Bakery Shop", "Bakery", ("bakery",)),
            ("Central Drugstore", "Central Pharmacy", "Pharmacy", ("pharmacy",)),
            ("Express Logistics", "Express Delivery Services", "Courier", ("courier",)),
            ("Premier Auto Care", "Premier Car Care Center", "Auto", ("car_repair",)),
            ("Pure Water Refilling", "Pure Drinking Water Station", "Water", ("water_station",)),
            ("Top Grade Hardware", "Top Grade Construction Supply", "Hardware", ("hardware_store",)),
        ]

        self.assertEqual(len(valid_pairs), 25, "Group 2 must contain exactly 25 test records.")

        auto_snap_count = 0
        for reg_name, poi_name, reg_line, poi_types in valid_pairs:
            score, _ = name_match(reg_name, poi_name, reg_line=reg_line, poi_types=poi_types)
            self.assertGreaterEqual(
                score, 0.80,
                f"Valid pair rejected: {reg_name} vs {poi_name} scored {score:.3f} < 0.80"
            )

            registry_entry = {
                "businessID": "BIZ-GRP2",
                "businessName": reg_name,
                "businessLine": reg_line,
                "barangayID": 1,
                "latitude": 13.9667,
                "longitude": 121.1167
            }
            # POI 35m away in same barangay
            matched, dist, sim, status = _match_poi_to_registry(
                poi_name, 13.9670, 121.1168, [registry_entry], poi_barangay_id=1
            )
            self.assertEqual(status, "auto")
            auto_snap_count += 1

        self.assertEqual(auto_snap_count, 25, "All 25 legitimate synonym pairs must auto-snap.")

    # ─────────────────────────────────────────────────────────────────────────────
    # GROUP 3: Out-of-Bounds & Geographic Conflict Pairs (15 Cases)
    # Failure Mode Prevented: Snapping candidates outside municipality or distant branches.
    # Expected: Out-of-bounds rejected; distant candidates (>300m) downgraded to 'review'.
    # ─────────────────────────────────────────────────────────────────────────────
    def test_group3_geographic_boundary_and_distance_screening(self):
        # 10 out-of-municipality candidates (e.g. Lipa, Calaca, Batangas City, Manila)
        out_of_bounds_pois = [
            ("Batangas Best Coffee", 13.9200, 120.8100, "Calaca"),
            ("Mataasnakahoy Rural Bank", 13.9400, 121.1600, "Lipa City"),
            ("Jollibee Mataasnakahoy", 13.9450, 121.1650, "Lipa City"),
            ("7-Eleven Pob. I", 14.0200, 121.0900, "Balete"),
            ("Generika Drugstore", 14.0800, 121.1500, "Tanauan"),
            ("Mercury Drug Mataasnakahoy", 13.9000, 121.0500, "Cuenca"),
            ("Alfamart Brgy II", 13.8600, 121.0000, "Alitagtag"),
            ("Andok's Litson Mataasnakahoy", 13.9550, 121.1700, "Lipa City"),
            ("Cebuana Lhuillier Brgy I", 13.8800, 121.1000, "San Jose"),
            ("Palawan Pawnshop Mataasnakahoy", 13.7500, 121.0500, "Batangas City"),
        ]

        confident_wrong_oob = 0
        for name, lat, lng, city in out_of_bounds_pois:
            is_inside_poly = _within_municipality(lat, lng)
            is_inside_center = _is_within_municipal_bounds(lat, lng)
            if is_inside_poly or is_inside_center:
                confident_wrong_oob += 1

        self.assertEqual(confident_wrong_oob, 0, "Out-of-bounds POIs must be screened out.")

        # 5 distant same-name candidates inside municipality but across distant barangays (>300m)
        distant_pairs = [
            ("Silva Pharmacy", 1, 13.9667, 121.1167, 4, 13.9780, 121.1250),     # ~1.5km
            ("Santos Hardware", 2, 13.9650, 121.1150, 5, 13.9820, 121.1280),    # ~2.2km
            ("Dimaano Water", 3, 13.9640, 121.1140, 6, 13.9800, 121.1290),      # ~2.3km
            ("Jose Store", 1, 13.9660, 121.1160, 7, 13.9850, 121.1300),         # ~2.5km
            ("Reyes Eatery", 2, 13.9655, 121.1155, 8, 13.9900, 121.1350),       # ~3.4km
        ]

        self.assertEqual(len(out_of_bounds_pois) + len(distant_pairs), 15, "Group 3 must contain 15 cases.")

        for name, reg_bid, rlat, rlng, poi_bid, plat, plng in distant_pairs:
            reg_entry = {
                "businessID": "BIZ-DIST",
                "businessName": name,
                "barangayID": reg_bid,
                "latitude": rlat,
                "longitude": rlng
            }
            matched, dist, sim, status = _match_poi_to_registry(
                name, plat, plng, [reg_entry], poi_barangay_id=poi_bid
            )
            # High name similarity, but distant (>300m) and different barangay -> MUST be 'review', NEVER 'auto'!
            self.assertEqual(status, "review", f"Distant branch {name} must downgrade to review queue.")
            self.assertGreater(dist, 300.0)

    # ─────────────────────────────────────────────────────────────────────────────
    # GROUP 4: Substring & Token Ambiguity Traps (15 Cases)
    # Failure Mode Prevented: 'ana' in 'banana' substring shortcut false positives.
    # Expected: Score <= 0.60, Match Status != 'auto'.
    # ─────────────────────────────────────────────────────────────────────────────
    def test_group4_substring_traps_never_auto_snap(self):
        substring_pairs = [
            ("Ana's", "Banana Store"),
            ("Joy", "Enjoy Sari-Sari Store"),
            ("J&M Trading", "JM Enterprises"),
            ("Leo Store", "Leonardo Store"),
            ("Rey Bakery", "Reynaldo Bakery"),
            ("Dan Eatery", "Daniel Food House"),
            ("Ali Barber", "Aling Nena Parlor"),
            ("Bea Salon", "Beatriz Beauty Lounge"),
            ("Ken Auto", "Kenneth Motors"),
            ("Ron Hardware", "Ronald Construction Supply"),
            ("Sam Bakeshop", "Samantha Pastries"),
            ("Vic Meat Shop", "Victoria Butchery"),
            ("Art Tailoring", "Arthur Apparel"),
            ("Eva Flowers", "Evangelical Church"),
            ("Don Water Station", "Donna Purified Drinking Water"),
        ]

        self.assertEqual(len(substring_pairs), 15, "Group 4 must contain exactly 15 test records.")

        confident_wrong_substring = 0
        for reg_name, poi_name in substring_pairs:
            score, _ = name_match(reg_name, poi_name)
            self.assertLessEqual(
                score, 0.60,
                f"Substring trap trigger: {reg_name} vs {poi_name} scored {score:.3f} > 0.60"
            )

            reg_entry = {
                "businessID": "BIZ-SUB",
                "businessName": reg_name,
                "barangayID": 1,
                "latitude": 13.9667,
                "longitude": 121.1167
            }
            matched, dist, sim, status = _match_poi_to_registry(
                poi_name, 13.9668, 121.1168, [reg_entry], poi_barangay_id=1
            )
            if status == "auto":
                confident_wrong_substring += 1

        self.assertEqual(confident_wrong_substring, 0, "FATAL: Substring traps must never auto-snap.")

    # ─────────────────────────────────────────────────────────────────────────────
    # GROUP 5: Provenance & Lock Shield Preservation (10 Cases)
    # Failure Mode Prevented: Sweep overwriting human-approved / manual coordinates.
    # Expected: Zero coordinate drift; locked records strictly preserved.
    # ─────────────────────────────────────────────────────────────────────────────
    @patch("api.flags.service.mysql")
    def test_group5_lock_shield_preserves_verified_coordinates(self, mock_mysql):
        locked_cases = [
            ("BIZ-LOCK-01", "Silva Pharmacy", 13.9661, 121.1161, "manual", "approved"),
            ("BIZ-LOCK-02", "Mercedes Hardware", 13.9662, 121.1162, "manual", "approved"),
            ("BIZ-LOCK-03", "Aling Nena Eatery", 13.9663, 121.1163, "places", "approved"),
            ("BIZ-LOCK-04", "Golden Bakeshop", 13.9664, 121.1164, "places", "approved"),
            ("BIZ-LOCK-05", "San Jose Medical Clinic", 13.9665, 121.1165, "manual", "approved"),
            ("BIZ-LOCK-06", "Pure Water Refilling", 13.9666, 121.1166, "manual", "approved"),
            ("BIZ-LOCK-07", "Loob Mini Mart", 13.9667, 121.1167, "places", "approved"),
            ("BIZ-LOCK-08", "Premier Auto Care", 13.9668, 121.1168, "manual", "approved"),
            ("BIZ-LOCK-09", "Bubuyan Hair Salon", 13.9669, 121.1169, "places", "approved"),
            ("BIZ-LOCK-10", "Poblacion Meat Shop", 13.9670, 121.1170, "manual", "approved"),
        ]

        self.assertEqual(len(locked_cases), 10, "Group 5 must contain exactly 10 test records.")

        from api.flags.service import _match_registry_to_google

        for biz_id, name, lat, lng, src, stat in locked_cases:
            mock_cursor = MagicMock()
            mock_mysql.connection.cursor.return_value = mock_cursor

            # Mock existing locked row in official_registry
            mock_cursor.fetchone.return_value = {
                "coordSource": src,
                "matchStatus": stat,
                "latitude": lat,
                "longitude": lng
            }
            mock_cursor.fetchall.return_value = []

            # Simulate detection sweep finding a candidate POI with different coordinates
            _match_registry_to_google(
                place_id="google_cand_sweep",
                business_id=biz_id,
                detected_name=name,
                target_color="Green",
                lat=13.9999,   # Drifting candidate
                lng=121.1999,
                barangay_id=1,
                match_score=0.99
            )

            # Assert official_registry was NOT updated with candidate coords
            update_calls = [
                call for call in mock_cursor.execute.call_args_list
                if "UPDATE official_registry" in call[0][0]
            ]
            self.assertEqual(
                len(update_calls), 0,
                f"Lock shield breached! Locked record {biz_id} was overwritten by automated sweep."
            )

    # ─────────────────────────────────────────────────────────────────────────────
    # GROUP 6: Multi-Branch & Sibling Candidate Single-Assignment (5 Cases)
    # Failure Mode Prevented: Greedy double-assignment of one POI to multiple branches.
    # Expected: 1-to-1 candidate assignment; zero cascade deletions.
    # ─────────────────────────────────────────────────────────────────────────────
    @patch("api.registry.service.mysql")
    def test_group6_multi_branch_isolation_and_delete_safety(self, mock_mysql):
        from api.registry.service import delete_business

        mock_cursor = MagicMock()
        mock_mysql.connection.cursor.return_value = mock_cursor

        # Case 96-99: Two 7-Eleven branches in same barangay
        branch_1 = {"businessID": "BIZ-711-BR1", "businessName": "7-Eleven", "barangayID": 1, "latitude": 13.9660, "longitude": 121.1160}
        branch_2 = {"businessID": "BIZ-711-BR2", "businessName": "7-Eleven", "barangayID": 1, "latitude": 13.9680, "longitude": 121.1180}

        # POI candidate located near Branch 1
        poi_near_b1 = (13.9661, 121.1161)
        matched_b1, dist_b1, sim_b1, status_b1 = _match_poi_to_registry(
            "7-Eleven", poi_near_b1[0], poi_near_b1[1], [branch_1, branch_2], poi_barangay_id=1
        )
        self.assertEqual(matched_b1["businessID"], "BIZ-711-BR1")
        self.assertLess(dist_b1, 50.0)

        # POI candidate located near Branch 2
        poi_near_b2 = (13.9681, 121.1181)
        matched_b2, dist_b2, sim_b2, status_b2 = _match_poi_to_registry(
            "7-Eleven", poi_near_b2[0], poi_near_b2[1], [branch_1, branch_2], poi_barangay_id=1
        )
        self.assertEqual(matched_b2["businessID"], "BIZ-711-BR2")
        self.assertLess(dist_b2, 50.0)

        # Case 100: Deleting Branch 1 must never delete Branch 2
        mock_cursor.fetchone.return_value = {
            "businessID": "BIZ-711-BR1",
            "businessName": "7-Eleven",
            "barangayID": 1
        }
        mock_cursor.fetchall.return_value = [{"logID": 1001, "businessID": "BIZ-711-BR1"}]

        delete_business("BIZ-711-BR1")

        # Verify deletion is strictly bound to businessID='BIZ-711-BR1'
        del_calls = [
            call for call in mock_cursor.execute.call_args_list
            if "DELETE FROM official_registry WHERE businessID = %s" in call[0][0]
        ]
        self.assertEqual(len(del_calls), 1)
        self.assertEqual(del_calls[0][0][1], ("BIZ-711-BR1",))

        # Verify no delete-by-name query executed
        name_del_calls = [
            call for call in mock_cursor.execute.call_args_list
            if "WHERE LOWER(detectedName) = LOWER(%s)" in call[0][0]
        ]
        self.assertEqual(len(name_del_calls), 0, "Catastrophic delete-by-name query must not exist.")


if __name__ == "__main__":
    unittest.main()
