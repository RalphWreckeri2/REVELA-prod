from api.models.geospatial import insert_green_flag
from api.flags.service import _load_registry, _match_registry_to_google
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..")))


class RelationalJoinsTests(unittest.TestCase):

    @patch("api.flags.service.mysql")
    def test_load_registry_joins_on_business_id_first(self, mock_mysql):
        """_load_registry must query with businessID relational match before falling back to name."""
        mock_cursor = MagicMock()
        mock_mysql.connection.cursor.return_value = mock_cursor
        mock_cursor.fetchall.return_value = []

        _load_registry()

        sql = mock_cursor.execute.call_args[0][0]
        self.assertIn("businessID = r.businessID", sql)
        self.assertIn("ORDER BY (businessID = r.businessID) DESC", sql)

    @patch("api.flags.service.mysql")
    def test_match_registry_stamps_business_id(self, mock_mysql):
        """_match_registry_to_google must stamp businessID into geospatial_logs."""
        mock_cursor = MagicMock()
        mock_mysql.connection.cursor.return_value = mock_cursor

        mock_cursor.fetchone.return_value = {
            "coordSource": None,
            "matchStatus": "auto",
            "latitude": None,
            "longitude": None
        }
        mock_cursor.fetchall.return_value = [
            {
                "logID": 501,
                "businessID": None,
                "placeID": "place_google_abc",
                "flagColor": "Green",
                "latitude": None,
                "longitude": None
            }
        ]

        _match_registry_to_google(
            place_id="place_google_abc",
            business_id="BIZ-REL-01",
            detected_name="Silva Pharmacy",
            target_color="Green",
            lat=13.965,
            lng=121.115,
            barangay_id=1,
            match_score=0.95
        )

        update_calls = [
            c for c in mock_cursor.execute.call_args_list if "UPDATE geospatial_logs" in c[0][0]]
        self.assertEqual(len(update_calls), 1)
        sql, params = update_calls[0][0][0], update_calls[0][0][1]
        self.assertIn("SET businessID = %s", sql)
        self.assertEqual(params[0], "BIZ-REL-01")

    @patch("api.models.geospatial.mysql")
    def test_insert_green_flag_sets_business_id(self, mock_mysql):
        """insert_green_flag must include businessID in INSERT INTO geospatial_logs."""
        mock_cursor = MagicMock()
        mock_mysql.connection.cursor.return_value = mock_cursor

        insert_green_flag(
            barangay_id=2,
            business_name="7-Eleven Branch A",
            lat=13.961,
            lng=121.111,
            address="Poblacion",
            color="Green",
            business_id="BIZ-7E-01"
        )

        sql, params = mock_cursor.execute.call_args[0][0], mock_cursor.execute.call_args[0][1]
        self.assertIn("businessID", sql)
        self.assertEqual(params[1], "BIZ-7E-01")

    @patch("api.flags.service.mysql")
    def test_get_flags_queries_prioritize_business_id(self, mock_mysql):
        """get_flags WHERE fragments must prioritize businessID over detectedName matching."""
        from api.flags.service import get_flags

        mock_cursor = MagicMock()
        mock_mysql.connection.cursor.return_value = mock_cursor
        mock_cursor.fetchone.return_value = {"total": 0}
        mock_cursor.fetchall.return_value = []

        res, err = get_flags(color="Green")
        self.assertIsNone(err)

        # get_flags issues an information_schema probe for
        # ladder_columns_available() before its own queries, so pick them by
        # content rather than by position in the call list.
        calls = mock_cursor.execute.call_args_list
        count_sql = next(c[0][0] for c in calls if "AS total" in c[0][0])
        fetch_sql = next(c[0][0] for c in calls if "AS combined" in c[0][0]
                         and "ORDER BY detectedDate" in c[0][0])

        # Registry-only dedup must still match on businessID first.
        self.assertIn(
            "g2.businessID IS NOT NULL AND g2.businessID = r.businessID", count_sql)
        self.assertIn(
            "g2.placeID IS NOT NULL AND g2.placeID = r.placeID", count_sql)

        # The pin's colour comes from the shared builder, whose registry match
        # tries businessID, then placeID, then name - and the name fallback
        # only applies when the pin has no businessID at all.
        self.assertIn("r_chk.businessID = g.businessID", count_sql)
        self.assertIn("g.placeID IS NOT NULL AND r_chk.placeID = g.placeID",
                      count_sql)
        self.assertIn(
            "g.businessID IS NULL", count_sql)
        self.assertIn("r_chk.barangayID = g.barangayID", count_sql)
        self.assertIn("r_chk.businessName = g.detectedName", count_sql)
        # ...and the businessID match outranks the others when picking a row.
        self.assertIn(
            "ORDER BY (r_chk.businessID = g.businessID) DESC", count_sql)

        self.assertIn(
            "g.placeID IS NOT NULL AND placeID = g.placeID", fetch_sql)
        self.assertIn("r.matchStatus", fetch_sql)

    @patch("api.flags.service._match_registry_to_google")
    @patch("api.flags.service._load_registry")
    @patch("api.flags.service.mysql")
    @patch("api.registry.audit.mysql")
    def test_reconcile_matches_directly_by_business_id(
        self, _mock_audit_mysql, mock_mysql, mock_load, mock_match
    ):
        """reconcile_existing_flags must match red flag directly by businessID."""
        from api.flags.service import reconcile_existing_flags

        mock_cursor = MagicMock()
        mock_mysql.connection.cursor.return_value = mock_cursor
        mock_cursor.fetchall.return_value = [
            {
                "logID": 101,
                "businessID": "BIZ-MATCH-99",
                "placeID": None,
                "detectedName": "Discrepant Name",
                "latitude": 13.96,
                "longitude": 121.11,
                "barangayID": 1
            }
        ]
        mock_cursor.fetchone.return_value = {"total": 1}
        mock_load.return_value = [
            {
                "businessID": "BIZ-MATCH-99",
                "businessName": "Official Registry Store",
                "barangayID": 1,
                "applicationStatus": "Active"
            }
        ]

        converted = reconcile_existing_flags(force=True, silent=True)
        self.assertEqual(converted, 1)
        mock_match.assert_called_once_with(
            None,
            "BIZ-MATCH-99",
            "Official Registry Store",
            target_color="Green",
            lat=13.96,
            lng=121.11,
            barangay_id=1,
            match_score=1.0,
            poi_types=(),
            poi_address=None,
            operation_type="reconciled",
            rejected_place_pairs=set(),
        )

    @patch("api.flags.service._match_registry_to_google")
    @patch("api.flags.service._load_registry")
    @patch("api.flags.service.mysql")
    @patch("api.registry.audit.mysql")
    def test_reconcile_maps_expired_registry_match_to_red(
        self, _mock_audit_mysql, mock_mysql, mock_load, mock_match
    ):
        from api.flags.service import reconcile_existing_flags

        mock_cursor = MagicMock()
        mock_mysql.connection.cursor.return_value = mock_cursor
        mock_cursor.fetchall.return_value = [{
            "logID": 102,
            "businessID": "BIZ-EXPIRED",
            "placeID": None,
            "detectedName": "Expired Shop",
            "latitude": 13.96,
            "longitude": 121.11,
            "barangayID": 1,
        }]
        mock_cursor.fetchone.return_value = {"total": 1}
        mock_load.return_value = [{
            "businessID": "BIZ-EXPIRED",
            "businessName": "Expired Shop",
            "barangayID": 1,
            "applicationStatus": "Expired",
        }]

        converted = reconcile_existing_flags(force=True, silent=True)

        self.assertEqual(converted, 1)
        self.assertEqual(
            mock_match.call_args.kwargs["target_color"], "Red"
        )

    @patch("api.flags.service._match_registry_to_google")
    @patch("api.flags.service._load_registry")
    @patch("api.flags.service.mysql")
    @patch("api.registry.audit.mysql")
    def test_reconcile_preserves_verified_orange_for_expired_business(
        self, _mock_audit_mysql, mock_mysql, mock_load, mock_match
    ):
        from api.flags.service import reconcile_existing_flags

        mock_cursor = MagicMock()
        mock_mysql.connection.cursor.return_value = mock_cursor
        mock_cursor.fetchall.return_value = [{
            "logID": 103,
            "businessID": "BIZ-EXPIRED-ORANGE",
            "placeID": None,
            "detectedName": "Warned Expired Shop",
            "latitude": 13.96,
            "longitude": 121.11,
            "barangayID": 1,
            "has_verified_orange": 1,
        }]
        mock_cursor.fetchone.return_value = {"total": 1}
        mock_load.return_value = [{
            "businessID": "BIZ-EXPIRED-ORANGE",
            "businessName": "Warned Expired Shop",
            "barangayID": 1,
            "applicationStatus": "Expired",
        }]

        converted = reconcile_existing_flags(force=True, silent=True)

        self.assertEqual(converted, 1)
        self.assertEqual(
            mock_match.call_args.kwargs["target_color"], "Orange"
        )


if __name__ == "__main__":
    unittest.main()
