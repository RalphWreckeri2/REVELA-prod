#!/usr/bin/env python3
"""One-shot local Nearby Search (New) smoke test; no REVELA imports or DB use."""

import argparse
import os
import re
import sys

import requests


NEARBY_SEARCH_URL = "https://places.googleapis.com/v1/places:searchNearby"
FIELD_MASK = (
    "places.id,places.displayName,places.location,"
    "places.primaryType,places.businessStatus,places.formattedAddress"
)
EXCLUDED_TYPES = (
    "school", "primary_school", "secondary_school",
    "university", "local_government_office", "city_hall", "courthouse",
    "fire_station", "police", "post_office", "library", "cemetery",
    "park", "transit_station", "bus_station", "subway_station",
    "train_station", "light_rail_station",
)
CONFIRMATION_TEXT = "SEND ONE NEARBY REQUEST"
MAX_RADIUS_METERS = 50_000

_SECRET_PATTERNS = (
    (re.compile(r"AIza[0-9A-Za-z_-]{20,}"), "[REDACTED_API_KEY]"),
    (re.compile(
        r"(?i)\b(api[-_ ]?key|authorization|bearer|password|secret|token)\b"
        r"\s*[:=]\s*[^\s,;]+"
    ), r"\1=[REDACTED]"),
    (re.compile(r"(?i)\b(key|token|password|secret)=([^\s&]+)"),
     r"\1=[REDACTED]"),
)


def build_request(latitude, longitude, radius_meters):
    return {
        "excludedTypes": list(EXCLUDED_TYPES),
        "maxResultCount": 1,
        "locationRestriction": {
            "circle": {
                "center": {
                    "latitude": latitude,
                    "longitude": longitude,
                },
                "radius": radius_meters,
            }
        },
    }


def _parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description=(
            "Prepare a read-only preview, or explicitly send one Nearby Search "
            "(New) request. This tool never connects to REVELA or MySQL."
        )
    )
    parser.add_argument("--latitude", type=float, required=True)
    parser.add_argument("--longitude", type=float, required=True)
    parser.add_argument("--radius-meters", type=float, default=100.0)
    parser.add_argument(
        "--send",
        action="store_true",
        help="ask for typed confirmation, then send at most one HTTP POST",
    )
    return parser.parse_args(argv)


def _validate_coordinates(latitude, longitude, radius_meters):
    if not -90 <= latitude <= 90:
        raise ValueError("Latitude must be between -90 and 90.")
    if not -180 <= longitude <= 180:
        raise ValueError("Longitude must be between -180 and 180.")
    if not 0 < radius_meters <= MAX_RADIUS_METERS:
        raise ValueError(
            f"Radius must be greater than zero and at most {MAX_RADIUS_METERS:g} meters."
        )


def _sanitize_error_text(value):
    text = str(value or "").replace("\r", " ").replace("\n", " ")
    for pattern, replacement in _SECRET_PATTERNS:
        text = pattern.sub(replacement, text)
    return text[:500] or "No error message provided."


def _sanitized_error(response):
    try:
        body = response.json()
    except (ValueError, TypeError):
        return "UNKNOWN", "Error response was not valid JSON."
    error = body.get("error") if isinstance(body, dict) else None
    if not isinstance(error, dict):
        return "UNKNOWN", "Error response had no structured error object."
    return (
        _sanitize_error_text(error.get("status")) or "UNKNOWN",
        _sanitize_error_text(error.get("message")),
    )


def main(argv=None):
    args = _parse_args(argv)
    try:
        _validate_coordinates(
            args.latitude, args.longitude, args.radius_meters)
    except ValueError as exc:
        print(f"Invalid request parameters: {exc}", file=sys.stderr)
        return 2

    payload = build_request(args.latitude, args.longitude, args.radius_meters)
    if not args.send:
        print("Dry run only; no HTTP request sent.")
        print(f"Endpoint: POST {NEARBY_SEARCH_URL}")
        print(f"Field mask: {FIELD_MASK}")
        print(
            "Request: maxResultCount=1, "
            f"center=({args.latitude}, {args.longitude}), "
            f"radius={args.radius_meters:g}m, excludedTypes={len(EXCLUDED_TYPES)}"
        )
        print("Use --send only after reviewing and approving this request.")
        return 0

    api_key = os.environ.get("GOOGLE_MAPS_API_KEY") or os.environ.get(
        "GOOGLE_PLACES_API_KEY"
    )
    if not api_key:
        print(
            "Set GOOGLE_MAPS_API_KEY or GOOGLE_PLACES_API_KEY in the local "
            "process environment; the value will not be displayed.",
            file=sys.stderr,
        )
        return 2

    print(f"This will send one request to {NEARBY_SEARCH_URL}.")
    try:
        confirmation = input(
            f"Type exactly {CONFIRMATION_TEXT!r} to continue: ")
    except EOFError:
        print("No confirmation received; no request sent.", file=sys.stderr)
        return 2
    if confirmation != CONFIRMATION_TEXT:
        print("Confirmation did not match; no request sent.", file=sys.stderr)
        return 2

    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": api_key,
        "X-Goog-FieldMask": FIELD_MASK,
    }
    try:
        response = requests.post(
            NEARBY_SEARCH_URL,
            headers=headers,
            json=payload,
            timeout=10,
            allow_redirects=False,
        )
    except requests.RequestException as exc:
        print(
            f"Request failed ({type(exc).__name__}); no retry was attempted.",
            file=sys.stderr,
        )
        return 1

    print(f"HTTP status: {response.status_code}")
    if not 200 <= response.status_code < 300:
        error_status, error_message = _sanitized_error(response)
        print(f"Google error status: {error_status}", file=sys.stderr)
        print(f"Google error message: {error_message}", file=sys.stderr)
        print(
            "Request was not successful; raw response and request headers "
            "withheld; no retry was attempted.",
            file=sys.stderr,
        )
        return 1

    try:
        body = response.json()
    except (ValueError, TypeError):
        print("Response was not valid JSON; body withheld.", file=sys.stderr)
        return 1
    places = body.get("places", []) if isinstance(body, dict) else []
    if not isinstance(places, list):
        print("Response had an unexpected shape; body withheld.", file=sys.stderr)
        return 1
    print(f"Returned place count: {len(places)}; place details withheld.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
