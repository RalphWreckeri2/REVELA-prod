from unittest.mock import Mock

from api.registry import service


def _response(status, results=None):
    response = Mock()
    response.status_code = 200
    response.json.return_value = {
        "status": status,
        "results": results or [],
    }
    return response


def test_address_search_returns_all_valid_selectable_matches(monkeypatch):
    monkeypatch.setattr(service, "GOOGLE_MAPS_API_KEY", "test-key")
    request = Mock(return_value=_response("OK", [
        {
            "formatted_address": "12 Main Street, Barangay II, Philippines",
            "place_id": "place-1",
            "geometry": {"location": {"lat": 13.96, "lng": 121.11}},
        },
        {
            "formatted_address": "Purok 3, Barangay II, Philippines",
            "place_id": "place-2",
            "geometry": {"location": {"lat": 13.961, "lng": 121.112}},
        },
    ]))

    matches, error = service.search_address_candidates(
        "12 Main Street",
        "Barangay II",
        get=request,
        reserve=lambda: True,
    )

    assert error is None
    assert matches == [
        {
            "formattedAddress": "12 Main Street, Barangay II, Philippines",
            "latitude": 13.96,
            "longitude": 121.11,
            "placeId": "place-1",
        },
        {
            "formattedAddress": "Purok 3, Barangay II, Philippines",
            "latitude": 13.961,
            "longitude": 121.112,
            "placeId": "place-2",
        },
    ]
    params = request.call_args.kwargs["params"]
    assert params["address"] == (
        "12 Main Street, Barangay II, Mataasnakahoy, Batangas, Philippines"
    )
    assert params["components"] == "country:PH"
    assert params["region"] == "ph"


def test_address_search_returns_no_results_without_fabricating_coordinates(
    monkeypatch,
):
    monkeypatch.setattr(service, "GOOGLE_MAPS_API_KEY", "test-key")
    request = Mock(return_value=_response("ZERO_RESULTS"))

    matches, error = service.search_address_candidates(
        "Unknown Purok",
        "Barangay II",
        get=request,
        reserve=lambda: True,
    )

    assert matches == []
    assert error is None


def test_address_search_without_barangay_scopes_query_to_municipality(monkeypatch):
    monkeypatch.setattr(service, "GOOGLE_MAPS_API_KEY", "test-key")
    request = Mock(return_value=_response("ZERO_RESULTS"))

    matches, error = service.search_address_candidates(
        "115 Templo Avenue",
        get=request,
        reserve=lambda: True,
    )

    assert matches == []
    assert error is None
    assert request.call_args.kwargs["params"]["address"] == (
        "115 Templo Avenue, Mataasnakahoy, Batangas, Philippines"
    )


def test_address_search_does_not_call_provider_when_quota_is_unavailable(
    monkeypatch,
):
    monkeypatch.setattr(service, "GOOGLE_MAPS_API_KEY", "test-key")
    request = Mock()

    matches, error = service.search_address_candidates(
        "Main Street",
        "Barangay II",
        get=request,
        reserve=lambda: False,
    )

    assert matches is None
    assert error == "quota_exceeded"
    request.assert_not_called()


def test_reverse_geocoding_returns_address_for_gps_coordinates(monkeypatch):
    monkeypatch.delenv("GOOGLE_MAPS_API_KEY", raising=False)
    monkeypatch.setattr(service, "GOOGLE_MAPS_API_KEY", "test-key")
    request = Mock(return_value=_response("OK", [{
        "formatted_address": "115 Templo Avenue, Barangay II, Philippines",
    }]))

    address, error = service.reverse_geocode_coordinates(
        13.96,
        121.11,
        get=request,
        reserve=lambda: True,
    )

    assert address == "115 Templo Avenue, Barangay II, Philippines"
    assert error is None
    assert request.call_args.kwargs["params"]["latlng"] == "13.960000,121.110000"
    assert request.call_args.kwargs["params"]["key"] == "test-key"


def test_reverse_geocoding_does_not_fabricate_an_address(monkeypatch):
    monkeypatch.setattr(service, "GOOGLE_MAPS_API_KEY", "test-key")
    request = Mock(return_value=_response("ZERO_RESULTS"))

    address, error = service.reverse_geocode_coordinates(
        13.96,
        121.11,
        get=request,
        reserve=lambda: True,
    )

    assert address is None
    assert error is None


def test_reverse_geocoding_rejects_invalid_coordinates_before_provider_call(
    monkeypatch,
):
    monkeypatch.setattr(service, "GOOGLE_MAPS_API_KEY", "test-key")
    request = Mock()

    address, error = service.reverse_geocode_coordinates(
        100,
        121.11,
        get=request,
        reserve=lambda: True,
    )

    assert address is None
    assert error == "invalid_request"
    request.assert_not_called()
