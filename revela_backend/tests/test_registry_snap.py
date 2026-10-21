from api.registry.places_resolver import compute_places_refresh_key
from api.registry import service
import os
import sys
import unittest
from unittest.mock import MagicMock, patch
from registry_sqlite import RegistryDB

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
            "matchStatus": None,
            "resolveKey": "old-geocode-key",
            "latitude": 13.9620,
            "longitude": 121.1120,
        }
        cached_unresolved = {
            **candidate,
            "businessID": "BIZ-CACHED-UNRESOLVED",
            "coordSource": None,
            "latitude": None,
            "longitude": None,
            "resolveKey": service.places_resolver.compute_resolve_key(
                "Silva Pharmacy", "Poblacion", 1
            ),
        }
        cached_candidate = {
            **candidate,
            "businessID": "BIZ-CACHED-GEOCODE",
            "resolveKey": compute_places_refresh_key(
                "Silva Pharmacy", "Poblacion", 1
            ),
        }
        db = RegistryDB()
        self.addCleanup(db.close)
        for row in (cached_unresolved, cached_candidate, candidate):
            columns = ", ".join(row)
            placeholders = ", ".join("?" for _ in row)
            db.db.execute(f"INSERT INTO official_registry ({columns}) VALUES ({placeholders})", tuple(row.values()))
        db.db.execute("""INSERT INTO geospatial_logs
            (businessID, barangayID, detectedName, latitude, longitude, flagColor)
            VALUES (?, 1, 'Silva Pharmacy', 13.9620, 121.1120, 'Red')""", (candidate["businessID"],))
        db.commit()

        with (
            patch("api.registry.audit.ensure_registry_workflow_events"),
            patch("api.registry.audit.record_registry_workflow_event"),
            patch.object(service, "mysql", db),
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
            patch.object(service, "_log_registry_places_summary"),
            patch.object(service, "_geocode") as geocode,
            patch("api.notifications.hub.publish_to_admins"),
        ):
            summary, error = service.snap_unresolved_pins(limit=1)

        self.assertIsNone(error)
        self.assertEqual(summary["snapped"], 1)
        self.assertEqual(summary["cached"], 2)
        resolve_location.assert_called_once()
        self.assertTrue(resolve_location.call_args.kwargs["refresh_geocode"])
        geocode.assert_not_called()
        self.assertEqual(summary["skipped_black_lock"], 0)
        self.assertEqual(db.rows("SELECT latitude, longitude, flagColor FROM geospatial_logs"),
                         [{"latitude": 13.9667, "longitude": 121.1167, "flagColor": "Green"}])
        color_writes = [sql for sql, _ in db.calls
                        if "UPDATE geospatial_logs" in sql and "SET flagColor" in sql]
        self.assertEqual(len(color_writes), 1)

        select_sql = next(sql for sql, _ in db.calls if "ORDER BY businessID" in sql)
        self.assertIn("coordSource = 'geocode'", select_sql)
        self.assertNotIn("SHA1(", select_sql)
        self.assertIn("matchStatus IS NULL", select_sql)
        update_sql, update_params = next((sql, params) for sql, params in db.calls
                                         if "UPDATE official_registry SET" in sql)
        self.assertIn("coordSource = 'geocode'", update_sql)
        self.assertIn("matchStatus IS NULL", update_sql)
        self.assertEqual(update_params[-1], 1)

    def test_snap_api_error_leaves_pin_and_flags_unchanged_for_resume(self):
        candidate = {
            "businessID": "BIZ-API-ERROR",
            "barangayID": 1,
            "businessName": "Silva Pharmacy",
            "businessAddress": "Poblacion",
            "lineOfBusiness": "Pharmacy",
            "applicationStatus": "Active",
            "coordSource": None,
            "matchStatus": None,
            "resolveKey": None,
            "latitude": None,
            "longitude": None,
        }
        select_cursor = MagicMock()
        select_cursor.fetchall.return_value = [candidate]
        mock_mysql = MagicMock()
        mock_mysql.connection.cursor.return_value = select_cursor
        usage = {
            "text_search": {"day": 2, "month": 5},
            "details": {"day": 0, "month": 0},
            "geocoding": {"day": 0, "month": 0},
        }

        with (
            patch("api.registry.audit.ensure_registry_workflow_events"),
            patch("api.registry.audit.record_registry_workflow_event"),
            patch.object(service, "mysql", mock_mysql),
            patch.object(service, "GOOGLE_MAPS_API_KEY", "dummy_test_key"),
            patch.object(service.places_resolver, "reset_run_state"),
            patch.object(service.places_resolver, "enabled", return_value=True),
            patch.object(service.places_resolver, "resolve_location", return_value=(
                None, None, {"reason": "api_error", "api_error": "HTTP 503"}
            )),
            patch.object(service.places_resolver, "get_places_call_usage", return_value=usage),
            patch.object(service, "_places_usage_snapshot", return_value=usage),
            patch.object(service, "_load_barangay_lookup", return_value={"Barangay I": 1}),
            patch.object(service.places_resolver, "_update_pin") as update_pin,
            patch("api.notifications.hub.publish_to_admins"),
        ):
            summary, error = service.snap_unresolved_pins(limit=1)

        self.assertIsNone(error)
        self.assertTrue(summary["api_error"])
        self.assertEqual(summary["snapped"], 0)
        self.assertEqual(summary["skipped_quota"], 0)
        update_pin.assert_not_called()
        mock_mysql.connection.commit.assert_not_called()
        self.assertFalse([call for call in select_cursor.execute.call_args_list
                          if call.args[0].lstrip().startswith(("UPDATE", "INSERT", "DELETE"))])
        self.assertTrue(select_cursor.execute.call_args.args[0].lstrip().startswith("SELECT"))
        select_cursor.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
