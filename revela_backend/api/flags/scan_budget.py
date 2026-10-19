"""Request bounds for the implemented Nearby call graph (no Google/DB access)."""

LEGACY_MAX_PAGES = 3
NEW_NEARBY_MAX_ATTEMPTS = 4  # initial attempt + at most three RPM retries
MAX_ADAPTIVE_DEPTH = 2
MAX_ADAPTIVE_QUERIES_PER_POINT = 12  # children, in addition to the root


def estimate_requests(mode, api_mode, total_points, completed_points=0):
    remaining = max(0, total_points - completed_points)
    queries_per_point = 1 if mode == "quick" else 1 + MAX_ADAPTIVE_QUERIES_PER_POINT
    pages = LEGACY_MAX_PAGES if mode == "full" and api_mode == "legacy" else 1
    attempts = NEW_NEARBY_MAX_ATTEMPTS if api_mode == "new" else 1
    return {
        "mode": mode, "nearby_api_mode": api_mode,
        "total_points": total_points, "saved_points": completed_points,
        "remaining_points": remaining,
        "minimum_requests": remaining,
        "maximum_requests": remaining * queries_per_point * pages * attempts,
        "maximum_requests_per_point": queries_per_point * pages * attempts,
        "maximum_queries_per_point": queries_per_point,
        "maximum_pages_per_query": pages,
        "maximum_attempts_per_page": attempts,
        "additional_lookup_requests": 0,
        "basis": "Only Nearby calls. Registry matching, reconciliation, and flag lookups are local SQL; no Text Search, Details, or Geocoding calls.",
    }
