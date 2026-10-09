import unittest
from unittest.mock import MagicMock, patch

from api.registry import places_resolver, reverify
from api.registry.reverify import prioritize_candidates


class ReverifyPriorityTests(unittest.TestCase):

    def test_prefers_unchecked_businesses_already_linked_to_google_poi(self):
        suspects = [
            {"businessID": "stacked", "stackSize": 20},
            {"businessID": "known-poi", "stackSize": 2},
            {"businessID": "attempted-poi", "stackSize": 10},
            {"businessID": "recent-poi", "stackSize": 30},
        ]

        ordered = prioritize_candidates(
            suspects,
            recent={"recent-poi"},
            attempted={"attempted-poi"},
            known_google_poi_ids={"known-poi", "attempted-poi", "recent-poi"},
        )

        self.assertEqual(
            [s["businessID"] for s in ordered],
            ["known-poi", "stacked", "attempted-poi"],
        )

    def test_ambiguous_candidate_is_recorded_without_coordinate_updates(self):
        cursor = MagicMock()
        cursor.rowcount = 1
        business = {"businessID": "BIZ-1"}

        self.assertEqual(
            reverify._record_review_candidate(cursor, business, {"score": 0.68}),
            1,
        )
        sql, params = cursor.execute.call_args.args
        self.assertIn("matchStatus = 'review'", sql)
        self.assertNotIn("latitude =", sql)
        self.assertNotIn("longitude =", sql)
        self.assertEqual(params, (0.68, "BIZ-1"))

    @patch.object(places_resolver, "_is_within_municipal_bounds", return_value=True)
    @patch.object(places_resolver, "_text_search")
    @patch.object(places_resolver, "reserve_call", return_value=True)
    def test_existing_place_id_wins_over_name_similarity(self, _reserve, text_search, _in_bounds):
        text_search.return_value = {
            "places": [
                {
                    "id": "better-name-match",
                    "displayName": {"text": "Silva Pharmacy"},
                    "location": {"latitude": 13.96, "longitude": 121.11},
                },
                {
                    "id": "known-place-id",
                    "displayName": {"text": "Different Branch Name"},
                    "location": {"latitude": 13.97, "longitude": 121.12},
                },
            ]
        }
        with patch.dict("os.environ", {"GOOGLE_MAPS_API_KEY": "test-key"}):
            lat, lng, meta = places_resolver.resolve_location(
                "Silva Pharmacy", "Poblacion", "Barangay I",
                preferred_place_id="known-place-id",
            )

        self.assertEqual((lat, lng), (13.97, 121.12))
        self.assertEqual(meta["place_id"], "known-place-id")
        self.assertEqual(meta["score"], 1.0)


if __name__ == "__main__":
    unittest.main()
