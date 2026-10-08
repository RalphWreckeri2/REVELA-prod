from api.registry.places_resolver import compute_places_refresh_key
from api.registry import service
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..")))


class RegistrySnapTests(unittest.TestCase):

    def test_snap_rechecks_and_updates_existing_geocode_pin(self):
        candidate = {
            "businessID": "BIZ-GEOCODE-01",
            "barangayID": 1,
            "businessName": "Silva Pharmacy",
            "businessAddress": "Poblacion",
            "lineOfBusiness": "Pharmacy",
            "applicationStatus": "Active",
            "coordSource": "geocode",
            "matchStatus": "auto",
            "resolveKey": "old-geocode-key",
            "latitude": 13.9620,
            "longitude": 121.1120,
        }
        select_cursor = MagicMock()
        select_cursor.fetchall.return_value = [candidate]
        update_cursor = MagicMock()
        update_cursor.rowcount = 1
        mock_mysql = MagicMock()
        mock_mysql.connection.cursor.side_effect = [
            select_cursor, update_cursor]

        with (
            patch.object(service, "mysql", mock_mysql),
            patch.object(service, "GOOGLE_MAPS_API_KEY", "dummy_test_key"),
            patch.object(service.places_resolver,
                         "enabled", return_value=True),
            patch.object(service.places_resolver, "resolve_location", return_value=(
                13.9667,
                121.1167,
                {
                    "coord_source": "places",
                    "place_id": "place_silva_pharmacy",
                    "place_id_kind": "poi",
                    "score": 1.0,
                    "match_status": "auto",
                    "resolve_key": compute_places_refresh_key(
                        "Silva Pharmacy", "Poblacion", 1
                    ),
                },
            )) as resolve_location,
            patch.object(service, "_load_barangay_lookup",
                         return_value={"Barangay I": 1}),
            patch.object(service, "_sync_flag_color") as sync_flag,
            patch.object(service, "_geocode") as geocode,
            patch("api.notifications.hub.publish_to_admins"),
        ):
            summary, error = service.snap_unresolved_pins()

        self.assertIsNone(error)
        self.assertEqual(summary["snapped"], 1)
        resolve_location.assert_called_once()
        self.assertTrue(resolve_location.call_args.kwargs["refresh_geocode"])
        geocode.assert_not_called()
        sync_flag.assert_called_once()

        select_sql = select_cursor.execute.call_args.args[0]
        self.assertIn("coordSource = 'geocode'", select_sql)
        update_sql = update_cursor.execute.call_args.args[0]
        self.assertIn("coordSource = 'geocode'", update_sql)
        self.assertEqual(update_cursor.execute.call_args.args[1][-1], 1)


if __name__ == "__main__":
    unittest.main()
