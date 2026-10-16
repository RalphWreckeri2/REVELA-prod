import unittest
from unittest.mock import MagicMock, patch

from flask import Flask
from shapely.geometry import Polygon

from api.flags import routes, service


class YellowFlagValidationTests(unittest.TestCase):
    @patch("api.flags.service.mysql")
    def test_invalid_coordinates_fail_before_database_access(self, mysql):
        for lat, lng in ((None, 121), (14, None), ("14", 121), (True, 121),
                         (float("nan"), 121), (14, float("inf")), (91, 121),
                         (14, 181), (10 ** 10000, 121), (0, 0)):
            result, error = service.insert_yellow_flag("Shop", lat, lng, 2)
            self.assertIsNone(result)
            self.assertIsInstance(error, service.YellowFlagValidationError)
        mysql.connection.cursor.assert_not_called()

    @patch("api.flags.service.mysql")
    def test_invalid_details_fail_before_database_access(self, mysql):
        for name, barangay in (("", 2), (None, 2), ("x" * 256, 2), ("Shop", None),
                               ("Shop", True), ("Shop", 0), ("Shop", "2"), ("Shop", 2.5)):
            _, error = service.insert_yellow_flag(name, 13.960630, 121.113447, barangay)
            self.assertIsInstance(error, service.YellowFlagValidationError)
        mysql.connection.cursor.assert_not_called()

    @patch("api.flags.service.mysql")
    def test_supplied_address_is_validated_without_geocoding(self, mysql):
        for address in ("", "  ", True, 42, {}, "x" * 256):
            _, error = service.insert_yellow_flag(
                "Shop", 13.960630, 121.113447, 2, business_address=address,
            )
            self.assertIsInstance(error, service.YellowFlagValidationError)
        mysql.connection.cursor.assert_not_called()

    def test_offsite_business_coordinate_matches_exact_registry_barangay(self):
        cursor = MagicMock()
        cursor.fetchone.return_value = {"barangayName": "Barangay II"}
        service._validate_yellow_flag_barangay(cursor, 13.960630, 121.113447, 2)
        cursor.fetchone.return_value = {"barangayName": "Barangay II-A"}
        with self.assertRaises(service.YellowFlagValidationError):
            service._validate_yellow_flag_barangay(cursor, 13.960630, 121.113447, 3)

    def test_polygon_holes_and_outside_points_are_rejected_without_buffer(self):
        cursor = MagicMock()
        cursor.fetchone.return_value = {"barangayName": "Barangay Test"}
        polygon = Polygon([(121, 13), (122, 13), (122, 14), (121, 14)],
                          holes=[[(121.4, 13.4), (121.6, 13.4), (121.6, 13.6), (121.4, 13.6)]])
        with patch.dict(service._BARANGAY_POLYGONS, {"Test": polygon}, clear=True):
            service._validate_yellow_flag_barangay(cursor, 13.2, 121.2, 2)
            for lat, lng in ((13.5, 121.5), (13.2, 120.999999)):
                with self.assertRaises(service.YellowFlagValidationError):
                    service._validate_yellow_flag_barangay(cursor, lat, lng, 2)

    def test_missing_or_ambiguous_boundary_is_a_server_failure(self):
        cursor = MagicMock()
        cursor.fetchone.return_value = {"barangayName": "Barangay II"}
        polygon = Polygon([(121, 13), (122, 13), (122, 14), (121, 14)])
        for polygons in ({}, {"District II (Pob.)": polygon, "Barangay II": polygon}):
            with patch.dict(service._BARANGAY_POLYGONS, polygons, clear=True):
                with self.assertRaises(RuntimeError):
                    service._validate_yellow_flag_barangay(cursor, 13.2, 121.2, 2)

    def test_unknown_registry_barangay_is_a_validation_failure(self):
        cursor = MagicMock()
        cursor.fetchone.return_value = None
        with self.assertRaises(service.YellowFlagValidationError):
            service._validate_yellow_flag_barangay(cursor, 13.960630, 121.113447, 999)

    @patch("api.notifications.service.notify_yellow_flag_reported")
    @patch("api.flags.service.mysql")
    def test_valid_offsite_business_needs_no_inspector_gps(self, mysql, notify):
        cursor = mysql.connection.cursor.return_value
        cursor.fetchone.return_value = {"barangayName": "Barangay II"}
        cursor.lastrowid = 41
        result, error = service.insert_yellow_flag(
            "Offsite Shop", 13.960630, 121.113447, 2, reported_by_user_id=9,
            business_address="Purok Makisig, behind the unnamed chapel",
        )
        self.assertIsNone(error)
        self.assertEqual(result["logID"], 41)
        # Barangay lookup, uncached source-column probe, then one INSERT.
        self.assertEqual(cursor.execute.call_count, 3)
        self.assertIn("information_schema.COLUMNS", cursor.execute.call_args_list[1].args[0])
        insert_sql, params = cursor.execute.call_args.args
        self.assertIn("nearestLandmark", insert_sql)
        self.assertIn("Purok Makisig, behind the unnamed chapel", params)
        self.assertEqual(params[2:4], (13.960630, 121.113447))
        self.assertEqual(result["businessAddress"], "Purok Makisig, behind the unnamed chapel")
        mysql.connection.commit.assert_called_once()
        notify.assert_called_once()

    @patch("api.flags.service.mysql")
    def test_manual_address_does_not_bypass_municipal_boundary(self, mysql):
        result, error = service.insert_yellow_flag(
            "Shop", 14.6, 121.0, 2, business_address="Unsearchable landmark",
        )
        self.assertIsNone(result)
        self.assertIsInstance(error, service.YellowFlagValidationError)
        mysql.connection.cursor.assert_not_called()

    @patch("api.flags.service.mysql")
    def test_barangay_failure_rolls_back_before_insert(self, mysql):
        cursor = mysql.connection.cursor.return_value
        cursor.fetchone.return_value = {"barangayName": "Barangay II-A"}
        result, error = service.insert_yellow_flag("Shop", 13.960630, 121.113447, 3)
        self.assertIsNone(result)
        self.assertIsInstance(error, service.YellowFlagValidationError)
        self.assertEqual(cursor.execute.call_count, 1)
        mysql.connection.commit.assert_not_called()
        mysql.connection.rollback.assert_called_once()

    @patch("api.flags.routes.get_jwt_identity", return_value="9")
    @patch("api.flags.routes.insert_yellow_flag")
    def test_route_distinguishes_validation_conflict_and_server_failure(self, insert, identity):
        for error, expected in ((service.YellowFlagValidationError("Wrong barangay"), 400),
                                (service.YellowFlagSubmissionConflict("Different payload"), 409),
                                ("Database unavailable", 500)):
            insert.return_value = (None, error)
            with Flask(__name__).test_request_context("/api/flags/yellow", method="POST", json={
                "businessName": "Shop", "lat": 13.960630, "lng": 121.113447, "barangayID": 2,
            }):
                response, status = routes.yellow_flag_route.__wrapped__()
            self.assertEqual(status, expected)
            self.assertEqual(response.get_json()["error"], str(error))
