"""
Google Cloud Console request quotas -- the hard ceiling REVELA must never exceed.

These values are deliberately NOT editable from the admin UI. The admin settings
surface can lower an application cap freely, but an override can never raise a
cap past the verified Cloud Console quota recorded here. That is what keeps a
mis-click in the settings panel from turning a budget stop into a billable
overrun or a stream of HTTP 429s.

Provenance matters. Each entry records whether the number was confirmed in the
project's Cloud Console or is still a reported/unverified figure. Unverified
ceilings are surfaced as such in the UI so an operator does not mistake an
assumption for a measurement.

Two independent safety nets
---------------------------
* `CLOUD_QUOTAS` -- the *reported* quota per method. `verified` controls whether
  REVELA will let an operator RAISE a cap above the current baseline.
* `OBSERVED_DAILY_CEILINGS` -- an unconditional upper bound applied to every
  daily application cap regardless of `verified`. This exists so that flipping
  `verified` to True later (or correcting a recorded number) can never silently
  lift a cap above a limit Google is already enforcing. Raising a cap beyond an
  observed ceiling requires deliberately editing this table, which is a visible
  code change rather than an invisible flag flip.

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


_VERIFIED = "Read from Cloud Console"

#: Figures observed in this project's Cloud Console by the owner and reported
#: back. `verified` is still False because nobody has signed these off in code
#: yet -- but the numbers are no longer guesses, so the wording says so.
_OBSERVED = (
    "Read from this project's Cloud Console by the project owner and reported "
    "for reconciliation. Confirm the API key's project before raising a cap."
)


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


# Reported against this project by the owner from Cloud Console:
#   Text Search (New)            500/day,   600/minute
#   Place Details (New)      125,000/day,   600/minute
#   Nearby Search (New)       75,000/day,   600/minute
#   Places API (Legacy)         1,000/day,    60/minute
#   Geocoding API              1,500/day,  3,000/minute
#
# `verified` stays False across the board: nothing here has been signed off in
# code, and flipping it would let an operator raise caps. The daily figures are
# nevertheless enforced as hard ceilings via OBSERVED_DAILY_CEILINGS below.
CLOUD_QUOTAS = MappingProxyType({
    "text_search": _method(
        500, 600, False, _OBSERVED,
        "CLOUD_QUOTA_TEXT_SEARCH_DAILY", "CLOUD_QUOTA_TEXT_SEARCH_PER_MINUTE",
    ),
    "place_details": _method(
        125_000, 600, False, _OBSERVED,
        "CLOUD_QUOTA_PLACE_DETAILS_DAILY",
        "CLOUD_QUOTA_PLACE_DETAILS_PER_MINUTE",
    ),
    "nearby_search_legacy": _method(
        1_000, 60, False, _OBSERVED,
        "CLOUD_QUOTA_NEARBY_LEGACY_DAILY",
        "CLOUD_QUOTA_NEARBY_LEGACY_PER_MINUTE",
    ),
    "nearby_search_new": _method(
        75_000, 600, False, _OBSERVED,
        "CLOUD_QUOTA_NEARBY_NEW_DAILY", "CLOUD_QUOTA_NEARBY_NEW_PER_MINUTE",
    ),
    "geocoding": _method(
        1_500, 3_000, False, _OBSERVED,
        "CLOUD_QUOTA_GEOCODING_DAILY", "CLOUD_QUOTA_GEOCODING_PER_MINUTE",
    ),
})

#: Unconditional upper bound on each method's daily application cap.
#:
#: Unlike `CLOUD_QUOTAS[...].verified`, this is applied even while a quota is
#: still marked unverified, because these numbers came from the project's own
#: console: they can be too conservative, never too permissive. Without this,
#: marking a quota verified later would be enough to lift a cap past a limit
#: Google is already enforcing.
#:
#: The only way to raise a cap beyond one of these is to edit this table, which
#: shows up in review as an intentional act.
OBSERVED_DAILY_CEILINGS = MappingProxyType({
    "text_search": 500,
    "place_details": 125_000,
    "nearby_search_legacy": 1_000,
    "nearby_search_new": 75_000,
    "geocoding": 1_500,
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
        # Mirrors LEGACY_NEARBY_LIMITER's configured interval (60 / 48 requests
        # per minute). A unit test asserts the two stay equal, because the admin
        # panel reports this number to operators while
        # api/utils/places_rate_limit.py is what actually enforces it.
        "min_interval_ms": 1250,
        "enforced": True,
        "note": "A shared GCRA pacer holds the process to 48 requests/minute "
                "against Google's 60/minute Places API (Legacy) quota; no two "
                "requests, from any thread, are closer than 1.25 s. Page-token "
                "requests also retain Google's 2-second wait.",
    },
    "nearby_search_new": {
        "min_interval_ms": 300,
        "enforced": True,
        "note": "Serialised behind a lock with a 300-500 ms jittered delay; "
                "well inside the 600/minute Nearby Search (New) quota.",
    },
    "text_search": {
        "min_interval_ms": 0,
        "enforced": False,
        "note": "One reservation per candidate; no client pacing. Resolver "
                "calls share a 300-500 ms jittered lock, inside the "
                "600/minute quota.",
    },
    "place_details": {
        "min_interval_ms": 0,
        "enforced": False,
        "note": "One reservation per refresh; no client pacing. Shares the "
                "resolver's jittered lock.",
    },
    "geocoding": {
        "min_interval_ms": 0,
        "enforced": False,
        "note": "One reservation per geocode attempt; no client pacing. The "
                "3,000/minute Geocoding quota is far above what a serial "
                "registry import can send.",
    },
})


def cloud_quota_for(method):
    """Return the recorded Cloud quota for an app-side method key."""
    return CLOUD_QUOTAS.get(method)


def hard_ceiling_for(method):
    """
    Unconditional upper bound for a method's daily application cap.

    Applied whether or not the recorded quota is marked verified, so flipping
    `verified` later cannot lift a cap past a limit Google already enforces.
    Returns None when no console figure has been recorded for the method, in
    which case only the verified ceiling applies.
    """
    return OBSERVED_DAILY_CEILINGS.get(method)


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
