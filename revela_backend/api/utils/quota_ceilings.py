"""
Google Cloud Console request quotas — the hard ceiling REVELA must never exceed.

These values are deliberately NOT editable from the admin UI. The admin settings
surface can lower an application cap freely, but an override can never raise a
cap past the verified Cloud Console quota recorded here. That is what keeps a
mis-click in the settings panel from turning a budget stop into a billable
overrun or a stream of HTTP 429s.

Provenance matters. Each entry records whether the number was confirmed in the
project's Cloud Console or is still a reported/unverified figure. Unverified
ceilings are surfaced as such in the UI so an operator does not mistake an
assumption for a measurement.

Change a value here only after re-checking it in Cloud Console, per the
operational checklist in PLACES_API_AND_PIN_ACCURACY_IMPLEMENTATION_PLAN.md.
"""

from dataclasses import dataclass
import os
from types import MappingProxyType


@dataclass(frozen=True)
class CloudMethodQuota:
    """One Google API method's request limits for this project."""

    #: Requests/day the Cloud project allows. None means "not yet verified".
    daily: int | None
    #: Requests/minute the Cloud project allows. None means "not yet verified".
    per_minute: int | None
    #: True only when the figures were read from Cloud Console.
    verified: bool
    #: Where the number came from, shown verbatim in the admin UI.
    source: str


_UNVERIFIED = "Reported by project owner; confirm in Cloud Console > Quotas"
_VERIFIED = "Read from Cloud Console"


def _env_override(name, fallback):
    """Ceilings may be raised/lowered by env for a project with different limits."""
    raw = os.getenv(name)
    if raw is None or raw == "":
        return fallback
    try:
        return int(raw)
    except (TypeError, ValueError):
        print(
            f"[quota_ceilings] Ignoring non-integer {name}; using {fallback}.")
        return fallback


def _method(daily, per_minute, verified, source, daily_env, minute_env):
    return CloudMethodQuota(
        daily=_env_override(daily_env, daily),
        per_minute=_env_override(minute_env, per_minute),
        verified=verified,
        source=source,
    )


# Text Search (New) Pro and Place Details (New) Essentials were both reported
# against this project. Nearby Search (New) Pro has not been enabled (its app
# caps default to 0), so its ceiling is recorded but unused until rollout.
# Legacy Nearby Search was never confirmed — the plan doc explicitly warns not
# to infer its limits from the New API method quotas.
CLOUD_QUOTAS = MappingProxyType({
    "text_search": _method(
        500, None, False,
        "User screenshot shows 500/day; earlier 80/day report conflicts. "
        "Confirm the API key project in Cloud Console.",
        "CLOUD_QUOTA_TEXT_SEARCH_DAILY", "CLOUD_QUOTA_TEXT_SEARCH_PER_MINUTE",
    ),
    "place_details": _method(
        95, None, False, _UNVERIFIED,
        "CLOUD_QUOTA_PLACE_DETAILS_DAILY",
        "CLOUD_QUOTA_PLACE_DETAILS_PER_MINUTE",
    ),
    "nearby_search_legacy": _method(
        None, None, False,
        "Never confirmed. Do not infer from Nearby Search (New).",
        "CLOUD_QUOTA_NEARBY_LEGACY_DAILY",
        "CLOUD_QUOTA_NEARBY_LEGACY_PER_MINUTE",
    ),
    "nearby_search_new": _method(
        None, None, False,
        "Not enabled yet; caps are 0 until the rollout gate passes.",
        "CLOUD_QUOTA_NEARBY_NEW_DAILY", "CLOUD_QUOTA_NEARBY_NEW_PER_MINUTE",
    ),
    "geocoding": _method(
        None, None, False,
        "Separate billing SKU from Places; not part of the Places counters.",
        "CLOUD_QUOTA_GEOCODING_DAILY", "CLOUD_QUOTA_GEOCODING_PER_MINUTE",
    ),
})

#: Billing SKUs and their monthly free-call allowance. Per-SKU only: free calls
#: on one SKU never offset usage on another, and there is no USD credit to fall
#: back on. Prices are estimates for the display only — confirm against the
#: current pricing page before relying on any figure.
SKU_PRICING = MappingProxyType({
    "text_search_pro": {
        "label": "Text Search (New) Pro",
        "free_monthly": 5000,
        "overage_per_1000": 32.00,
        "verified": False,
    },
    "nearby_search_pro": {
        "label": "Nearby Search (New) Pro",
        "free_monthly": 5000,
        "overage_per_1000": 32.00,
        "verified": False,
    },
    "place_details_essentials": {
        "label": "Place Details (New) Essentials",
        "free_monthly": 10000,
        "overage_per_1000": 5.00,
        "verified": False,
    },
    "geocoding": {
        "label": "Geocoding",
        "free_monthly": None,
        "overage_per_1000": 5.00,
        "verified": False,
    },
    "nearby_search_legacy": {
        "label": "Legacy Nearby Search",
        "free_monthly": None,
        "overage_per_1000": 17.00,
        "verified": False,
    },
})

#: Which billing SKU each app-side method spends.
METHOD_SKU = MappingProxyType({
    "text_search": "text_search_pro",
    "place_details": "place_details_essentials",
    "geocoding": "geocoding",
    "nearby_search_legacy": "nearby_search_legacy",
    "nearby_search_new": "nearby_search_pro",
})

#: Minimum interval REVELA itself enforces between outgoing requests, and whether
#: that pacing is actually wired up for the method. Reported separately from the
#: Cloud quota because it is a client-side politeness/latency control, not a
#: limit Google imposes.
REQUEST_PACING = MappingProxyType({
    "nearby_search_legacy": {
        "min_interval_ms": 300,
        "enforced": True,
        "note": "Shared request lock enforces at least 300 ms between "
        "legacy Nearby calls; page-token requests also retain Google's "
        "2-second wait.",
    },
    "nearby_search_new": {
        "min_interval_ms": 300,
        "enforced": True,
        "note": "Serialised behind a lock with a 300-500 ms jittered delay.",
    },
    "text_search": {
        "min_interval_ms": 0,
        "enforced": False,
        "note": "One reservation per candidate; no client pacing.",
    },
    "place_details": {
        "min_interval_ms": 0,
        "enforced": False,
        "note": "One reservation per refresh; no client pacing.",
    },
    "geocoding": {
        "min_interval_ms": 0,
        "enforced": False,
        "note": "One reservation per geocode attempt; no client pacing.",
    },
})


def cloud_quota_for(method):
    """Return the recorded Cloud quota for an app-side method key."""
    return CLOUD_QUOTAS.get(method)


def pacing_for(method):
    """Return REVELA's own request pacing for an app-side method key."""
    return REQUEST_PACING.get(method, {
        "min_interval_ms": 0,
        "enforced": False,
        "note": "No client pacing recorded for this method.",
    })


def sku_for(method):
    """Return the billing SKU key an app-side method spends."""
    return METHOD_SKU.get(method)
