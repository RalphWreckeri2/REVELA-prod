"""Actual routing/auth/CORS regressions. Run with run_isolated_unit_tests.py."""
from unittest.mock import patch

import pytest
from flask_jwt_extended import create_access_token

from api.inspections import routes
from api.registry.inspection_link import GreenRegistryLinkError
from tests.green_link_http import ORIGIN, create_http_app


REVIEW = "/api/inspections/7/green-registry-link?businessID=A-0401018-00078"
VERIFY = "/api/inspections/7/verify"


@pytest.fixture
def app():
    return create_http_app()


def token(app, role="Admin"):
    with app.app_context():
        return create_access_token(identity="9", additional_claims={"role": role})


def auth(app, role="Admin"):
    return {"Origin": ORIGIN, "Authorization": f"Bearer {token(app, role)}"}


def assert_origin(response):
    assert response.headers["Access-Control-Allow-Origin"] == ORIGIN
    assert response.headers["Access-Control-Allow-Credentials"] == "true"
    assert "Origin" in response.headers["Vary"]
    assert "Location" not in response.headers


@pytest.mark.parametrize("path,method,headers", [
    (REVIEW, "GET", "authorization"),
    (REVIEW, "GET", "authorization,content-type"),
    (VERIFY, "POST", "authorization,content-type"),
])
def test_real_frontend_preflights_need_no_token_session_or_database(app, path, method, headers):
    with (
        patch("api.middleware.decorators.verify_jwt_in_request", side_effect=AssertionError("Preflight must not authenticate")),
        patch("api.middleware.decorators._verify_user_and_session", side_effect=AssertionError("Preflight must not inspect sessions")),
        patch.object(routes, "preview_green_registry_link", side_effect=AssertionError("Preflight must not inspect schema or records")),
        patch.object(routes, "verify_inspection", side_effect=AssertionError("Preflight must not verify anything")),
    ):
        response = app.test_client().options(path, headers={
            "Origin": ORIGIN, "Access-Control-Request-Method": method,
            "Access-Control-Request-Headers": headers,
        })
    assert response.status_code == 204
    assert response.data == b""
    assert_origin(response)
    allowed = {part.strip().lower() for part in response.headers["Access-Control-Allow-Headers"].split(",")}
    assert set(headers.split(",")).issubset(allowed)
    assert method in response.headers["Access-Control-Allow-Methods"]


@pytest.mark.parametrize("origin", ["https://evil.example", "https://www.revelasys.site.evil.example", "http://www.revelasys.site"])
def test_preflight_does_not_widen_the_allowed_origins(app, origin):
    response = app.test_client().options(REVIEW, headers={
        "Origin": origin, "Access-Control-Request-Method": "GET",
        "Access-Control-Request-Headers": "authorization",
    })
    assert response.status_code == 204
    assert "Access-Control-Allow-Origin" not in response.headers


def test_existing_apex_only_configuration_explicitly_allows_www():
    app = create_http_app("https://revelasys.site")
    response = app.test_client().options(REVIEW, headers={
        "Origin": ORIGIN, "Access-Control-Request-Method": "GET",
        "Access-Control-Request-Headers": "authorization",
    })
    assert response.status_code == 204
    assert_origin(response)


@pytest.mark.parametrize("path,method", [(REVIEW, "get"), (VERIFY, "post")])
@pytest.mark.parametrize("authorization", [None, "Bearer invalid-token"])
def test_actual_requests_still_require_a_valid_jwt(app, path, method, authorization):
    headers = {"Origin": ORIGIN}
    if authorization:
        headers["Authorization"] = authorization
    with patch.object(routes, "preview_green_registry_link") as review, patch.object(routes, "verify_inspection") as verify:
        response = getattr(app.test_client(), method)(path, headers=headers)
    assert response.status_code == 401
    assert response.json["error"] == "Unauthorized"
    assert_origin(response)
    review.assert_not_called()
    verify.assert_not_called()


@pytest.mark.parametrize("path,method", [(REVIEW, "get"), (VERIFY, "post")])
def test_actual_requests_require_an_admin_and_an_active_session(app, path, method):
    with (
        patch("api.middleware.decorators._verify_user_and_session", return_value=None) as session,
        patch.object(routes, "preview_green_registry_link") as review,
        patch.object(routes, "verify_inspection") as verify,
    ):
        response = getattr(app.test_client(), method)(path, headers=auth(app, "Inspector"))
    assert response.status_code == 403
    assert_origin(response)
    assert session.call_args.kwargs["require_admin"] is True
    review.assert_not_called()
    verify.assert_not_called()


@pytest.mark.parametrize("path,method", [(REVIEW, "get"), (VERIFY, "post")])
def test_deactivated_admin_cannot_use_actual_endpoints(app, path, method):
    with (
        patch("api.middleware.decorators.find_user_by_id", return_value={"isActive": 0}),
        patch.object(routes, "preview_green_registry_link") as review,
        patch.object(routes, "verify_inspection") as verify,
    ):
        response = getattr(app.test_client(), method)(path, headers=auth(app))
    assert response.status_code == 401
    assert "deactivated" in response.json["message"]
    assert_origin(response)
    review.assert_not_called()
    verify.assert_not_called()


@pytest.mark.parametrize("path,method", [(REVIEW, "get"), (VERIFY, "post")])
def test_ended_admin_session_cannot_use_actual_endpoints(app, path, method):
    with (
        patch("api.middleware.decorators.find_user_by_id", return_value={"isActive": 1, "userRole": "Admin"}),
        patch("api.middleware.decorators.check_active_session", return_value=(False, "session_idle")),
        patch.object(routes, "preview_green_registry_link") as review,
        patch.object(routes, "verify_inspection") as verify,
    ):
        response = getattr(app.test_client(), method)(path, headers=auth(app))
    assert response.status_code == 401
    assert response.json["code"] == "session_idle"
    assert_origin(response)
    review.assert_not_called()
    verify.assert_not_called()


@pytest.mark.parametrize("error,status", [
    (GreenRegistryLinkError("An official Business ID is required."), 400),
    (GreenRegistryLinkError("This Business ID is already confirmed against a different pin.", conflict=True), 409),
    (GreenRegistryLinkError("Apply the confirmed registry pin migration before verifying Green results.", conflict=True), 409),
])
def test_backend_validation_and_migration_errors_are_readable_json_with_cors(app, error, status):
    with patch("api.middleware.decorators._verify_user_and_session", return_value=None), patch.object(routes, "preview_green_registry_link", return_value=(None, error)):
        response = app.test_client().get(REVIEW, headers=auth(app))
    assert response.status_code == status
    assert response.json["error"] == str(error)
    assert_origin(response)


def test_exceptions_do_not_hide_behind_a_cors_failure(app):
    with patch("api.middleware.decorators._verify_user_and_session", return_value=None), patch.object(routes, "preview_green_registry_link", side_effect=RuntimeError("isolated backend failure")):
        response = app.test_client().get(REVIEW, headers=auth(app))
    assert response.status_code == 500
    assert response.json == {"error": "Internal Server Error"}
    assert_origin(response)


def test_missing_route_is_still_a_404_even_with_valid_cors_headers(app):
    response = app.test_client().options("/api/inspections/7/missing-review-route", headers={
        "Origin": ORIGIN, "Access-Control-Request-Method": "GET",
        "Access-Control-Request-Headers": "authorization",
    })
    assert response.status_code == 404
    assert_origin(response)
