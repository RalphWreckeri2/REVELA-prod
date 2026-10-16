"""Offline API, policy, boundary and additive-migration release contracts."""

import ast
from datetime import timedelta
from pathlib import Path
import re
import unittest
from unittest.mock import MagicMock, patch

from shapely.ops import unary_union

from flask import Flask
from flask_jwt_extended import JWTManager, create_access_token

from config import Config
from api.auth import routes as auth_routes, sessions
from api.flags import routes as flag_routes, service as flag_service
from api.models.inspection_lifecycle_events import log_inspection_event


BACKEND = Path(__file__).resolve().parents[1]


class BackendApiContractTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.config.update(
            JWT_SECRET_KEY="offline-contract-key-with-at-least-32-characters",
            JWT_ACCESS_TOKEN_EXPIRES=Config.JWT_ACCESS_TOKEN_EXPIRES,
            SESSION_IDLE_TIMEOUT=Config.SESSION_IDLE_TIMEOUT,
        )
        JWTManager(self.app)
        self.app.register_blueprint(flag_routes.flags_bp, url_prefix="/api/flags")
        self.app.register_blueprint(auth_routes.auth_bp, url_prefix="/api/auth")
        self.client = self.app.test_client()
        with self.app.app_context():
            self.headers = self.token_headers("mobile")
        self.body = {
            "businessName": "Test Shop", "lat": 13.960630, "lng": 121.113447,
            "barangayID": 2, "expectedReporterUserID": "9",
            "clientSubmissionID": "c34cc4d8-7427-42ad-9e2a-15efdd2ed854",
        }
        for target, mock in (
            ("api.middleware.decorators.find_user_by_id", MagicMock(return_value={
                "userID": 9, "userRole": "Inspector", "isActive": True,
            })),
            ("api.middleware.decorators.check_active_session", MagicMock(return_value=(True, None))),
        ):
            patcher = patch(target, mock)
            patcher.start()
            self.addCleanup(patcher.stop)

    def token_headers(self, client_type):
        token = create_access_token(identity="9", additional_claims={
            "role": "Inspector", "session_id": "offline-session", "client_type": client_type,
        })
        return {"Authorization": f"Bearer {token}"}

    @patch.object(flag_routes, "insert_yellow_flag")
    def test_yellow_api_retains_201_and_canonicalizes_uuid_for_binary_unique_key(self, insert):
        insert.return_value = ({"logID": 41, "lat": 13.960630, "lng": 121.113447,
                                "alreadyAccepted": False}, None)
        self.body["clientSubmissionID"] = self.body["clientSubmissionID"].upper()
        self.body["businessAddress"] = "Purok Makisig, behind the unnamed chapel"
        response = self.client.post("/api/flags/yellow", json=self.body, headers=self.headers)
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.get_json()["logID"], 41)
        self.assertEqual(insert.call_args.kwargs["reported_by_user_id"], 9)
        self.assertEqual(insert.call_args.kwargs["client_submission_id"], self.body["clientSubmissionID"].lower())
        self.assertEqual(insert.call_args.kwargs["business_address"], self.body["businessAddress"])
        self.assertEqual(insert.call_args.kwargs["lat"], self.body["lat"])
        self.assertEqual(insert.call_args.kwargs["lng"], self.body["lng"])

    @patch.object(flag_routes, "insert_yellow_flag")
    def test_reporter_mismatch_cannot_access_insert_service(self, insert):
        response = self.client.post("/api/flags/yellow", json=dict(self.body, expectedReporterUserID="10"),
                                    headers=self.headers)
        self.assertEqual(response.status_code, 403)
        insert.assert_not_called()

    @patch.object(flag_routes, "insert_yellow_flag")
    def test_invalid_uuid_and_reporter_identity_are_400(self, insert):
        for body in (dict(self.body, clientSubmissionID="invalid"),
                     dict(self.body, clientSubmissionID=42),
                     dict(self.body, expectedReporterUserID="not-an-id")):
            response = self.client.post("/api/flags/yellow", json=body, headers=self.headers)
            self.assertEqual(response.status_code, 400)
        insert.assert_not_called()

    @patch.object(flag_routes, "insert_yellow_flag")
    def test_authenticated_yellow_conflict_has_409_response(self, insert):
        insert.return_value = (None, flag_service.YellowFlagSubmissionConflict("Different payload"))
        response = self.client.post("/api/flags/yellow", json=self.body, headers=self.headers)
        self.assertEqual(response.status_code, 409)

    @patch.object(flag_routes.registry_service, "search_address_candidates")
    def test_location_search_route_returns_latest_flutter_contract(self, search):
        candidates = [{"formattedAddress": "Main Street", "latitude": 13.96,
                       "longitude": 121.11, "placeId": "test-place",
                       "locationType": "GEOMETRIC_CENTER", "resultTypes": ["route"],
                       "partialMatch": False, "providerResultCount": 1,
                       "addressComponents": []}]
        search.return_value = (candidates, None)
        response = self.client.post("/api/flags/location-search", json={
            "streetAddress": " Main Street ", "barangay": " Barangay II ",
        }, headers=self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"results": candidates})
        search.assert_called_once_with("Main Street", "Barangay II")

    @patch.object(flag_routes.registry_service, "search_address_candidates", return_value=([], None))
    def test_search_accepts_the_same_address_length_as_the_business_field(self, search):
        address = "x" * 255
        response = self.client.post("/api/flags/location-search", json={
            "streetAddress": address,
        }, headers=self.headers)
        self.assertEqual(response.status_code, 200)
        search.assert_called_once_with(address, None)

    @patch.object(flag_routes.registry_service, "reverse_geocode_coordinates")
    def test_reverse_route_preserves_formatted_address_and_confirmed_null(self, reverse):
        for address in ("Main Street", None):
            reverse.return_value = (address, None)
            response = self.client.post("/api/flags/reverse-geocode", json={
                "latitude": 13.96, "longitude": 121.11,
            }, headers=self.headers)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.get_json(), {"formattedAddress": address})

    def test_geocoding_routes_map_unavailability_quota_and_provider_errors(self):
        for path, function, body in (
            ("location-search", "search_address_candidates", {"streetAddress": "Main Street"}),
            ("reverse-geocode", "reverse_geocode_coordinates", {"latitude": 13.96, "longitude": 121.11}),
        ):
            for error, status in (("not_configured", 503), ("quota_exceeded", 429),
                                  ("network_error", 502), ("provider_error", 502)):
                with patch.object(flag_routes.registry_service, function, return_value=(None, error)):
                    response = self.client.post(f"/api/flags/{path}", json=body, headers=self.headers)
                self.assertEqual(response.status_code, status)
                self.assertEqual(response.get_json()["code"], error)

    def test_invalid_search_request_never_enters_provider_service(self):
        with patch.object(flag_routes.registry_service, "search_address_candidates") as search, \
                patch.object(flag_routes.registry_service, "reverse_geocode_coordinates") as reverse:
            for path, body in (("location-search", []), ("location-search", {"streetAddress": ""}),
                               ("location-search", {"streetAddress": "x" * 256}),
                               ("reverse-geocode", {"latitude": True, "longitude": 121})):
                response = self.client.post(f"/api/flags/{path}", json=body, headers=self.headers)
                self.assertEqual(response.status_code, 400)
            search.assert_not_called()
            reverse.assert_not_called()

    @patch.object(auth_routes, "record_session_activity")
    def test_mobile_heartbeat_updates_liveness_and_keeps_existing_idle_policy(self, record):
        response = self.client.post("/api/auth/heartbeat", headers=self.headers)
        self.assertEqual(response.status_code, 200)
        record.assert_called_once_with("offline-session")
        self.assertEqual(Config.SESSION_IDLE_TIMEOUT, timedelta(minutes=10))
        self.assertEqual(Config.JWT_ACCESS_TOKEN_EXPIRES, timedelta(hours=12))
        with self.app.app_context():
            self.assertEqual(sessions.idle_timeout_seconds(), 600)

    @patch.object(auth_routes, "record_session_activity")
    def test_web_heartbeat_is_rejected_without_recording_activity(self, record):
        with self.app.app_context():
            headers = self.token_headers("web")
        response = self.client.post("/api/auth/heartbeat", headers=headers)
        self.assertEqual(response.status_code, 403)
        record.assert_not_called()

    def test_new_routes_require_authentication(self):
        for path in ("/api/flags/yellow", "/api/flags/location-search",
                     "/api/flags/reverse-geocode", "/api/auth/heartbeat"):
            response = self.client.post(path, json={})
            self.assertEqual(response.status_code, 401)


class ReleaseInfrastructureContractTests(unittest.TestCase):
    def test_lifecycle_insert_uses_explicit_utc_without_changing_parameter_contract(self):
        cursor = MagicMock()
        cursor.lastrowid = 21
        self.assertEqual(log_inspection_event(cursor, 100, 20, "submitted", cycle_id=11), 21)
        query, params = cursor.execute.call_args.args
        self.assertIn("eventTimestamp", query)
        self.assertIn("UTC_TIMESTAMP(6)", query)
        self.assertEqual(len(params), 9)
        self.assertEqual(params[2], 11)

    def test_migration_definitions_match_missing_fields_and_known_schema(self):
        yellow = (BACKEND / "migrations/20261014_01_yellow_flag_idempotency.sql").read_text(encoding="utf-8")
        stamps = (BACKEND / "migrations/20261014_02_inspection_submission_timestamps.sql").read_text(encoding="utf-8")
        self.assertRegex(yellow, r"ADD COLUMN clientSubmissionID CHAR\(36\)\s+CHARACTER SET ascii COLLATE ascii_bin NULL")
        self.assertRegex(yellow, r"CREATE UNIQUE INDEX uq_geo_reporter_submission\s+ON geospatial_logs \(reportedByUserID, clientSubmissionID\)")
        for field in ("submittedAt", "submissionReceivedAt"):
            self.assertRegex(stamps, rf"ADD COLUMN {field} DATETIME\(6\) NULL DEFAULT NULL")
        self.assertIn("AFTER irTimestamp", stamps)
        self.assertIn("AFTER submittedAt", stamps)
        gps = (BACKEND / "scripts/add_inspection_verified_gps.sql").read_text(encoding="utf-8")
        self.assertRegex(gps, r"verifiedAccuracy DECIMAL\(8,\s*2\)")
        for script in (yellow, stamps):
            statements = "\n".join(line for line in script.splitlines() if not line.lstrip().startswith("--"))
            self.assertIsNone(re.search(r"\b(DROP|TRUNCATE|DELETE|UPDATE|INSERT)\b|FOREIGN_KEY_CHECKS", statements, re.I))

    def test_changed_runtime_modules_import_no_experimental_or_qa_helpers(self):
        for path in (
            "api/auth/routes.py", "api/flags/routes.py", "api/flags/service.py",
            "api/inspections/routes.py", "api/inspections/service.py",
            "api/models/inspection_lifecycle_events.py", "api/registry/service.py",
            "api/utils/barangay_scope.py",
        ):
            tree = ast.parse((BACKEND / path).read_text(encoding="utf-8"))
            modules = [node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
            self.assertFalse(any("qa_safety" in name or "nearby_barangay" in name for name in modules), path)

    def test_all_barangays_are_contained_by_the_derived_municipal_boundary(self):
        """All 16 barangays must sit inside the municipal boundary.

        The municipal polygon is now the union of these same barangay
        geometries, so containment is structural rather than a tuned
        coincidence. This replaces the earlier test, which pinned a hardcoded
        six-barangay mismatch set that was caused by an unrelated hand-entered
        outline disagreeing with the GADM barangay data.
        """
        polygons = flag_service._BARANGAY_POLYGONS
        self.assertEqual(len(polygons), 16, "All 16 barangays must load.")

        boundary = flag_service._MUNICIPALITY_WITH_TOLERANCE
        outside = {
            name
            for name, polygon in polygons.items()
            if not polygon.difference(boundary).is_empty
        }
        self.assertEqual(
            outside, set(),
            "No barangay may extend outside the municipal boundary; "
            f"offenders: {sorted(outside)}",
        )

        # The municipality must be derived from the barangays, not a literal
        # that can silently drift away from them again.
        self.assertEqual(
            boundary.geom_type, flag_service._MUNICIPALITY_BOUNDARY.geom_type
        )
        union = unary_union(list(polygons.values()))
        self.assertTrue(
            flag_service._MUNICIPALITY_BOUNDARY.equals(union.buffer(0)),
            "Municipal boundary must equal the union of the barangay polygons.",
        )

    def test_barangay_submission_is_accepted_inside_the_derived_boundary(self):
        """A coordinate inside any barangay must now pass fail-closed validation."""
        for name, polygon in flag_service._BARANGAY_POLYGONS.items():
            with self.subTest(barangay=name):
                point = polygon.representative_point()
                registry_name = flag_service._GEOJSON_BARANGAY_ALIASES.get(
                    name, name)
                cursor = MagicMock()
                cursor.fetchone.return_value = {"barangayName": registry_name}
                flag_service._validate_yellow_flag_barangay(
                    cursor, point.y, point.x, 1)
                self.assertTrue(flag_service._within_municipality(
                    point.y, point.x))
