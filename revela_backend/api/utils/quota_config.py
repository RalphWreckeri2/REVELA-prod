"""Central application-side Google API quota configuration."""

from dataclasses import dataclass
import os
from types import MappingProxyType
from typing import Mapping

from api.utils.quota_ceilings import cloud_quota_for, hard_ceiling_for


@dataclass(frozen=True)
class MethodQuota:
    daily: int
    monthly: int


@dataclass(frozen=True)
class ApiQuotaConfig:
    text_search: MethodQuota
    text_search_workflow_daily: Mapping[str, int]
    place_details: MethodQuota
    geocoding: MethodQuota
    legacy_nearby: MethodQuota
    nearby_new: MethodQuota
    run_detection_nearby_api: str
    run_detection_monthly_scans: int
    run_detection_max_seconds: int
    run_detection_max_requests: int
    allow_quota_resets: bool


def _int_setting(environ, name, default, aliases=(), minimum=0):
    for setting_name in (name, *aliases):
        if setting_name in environ:
            try:
                value = int(environ[setting_name])
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    f"{setting_name} must be an integer."
                ) from exc
            if value < minimum:
                raise ValueError(
                    f"{setting_name} must be at least {minimum}."
                )
            return value
    return default


def _daily_cap(environ, name, default, method, aliases=()):
    """
    Resolve one daily cap: min(configured value, whatever ceiling applies).

    Three ceilings, in order of strictness:

    1. `default` -- while the method's Cloud quota is still unverified, a cap
       may not be raised above the shipped default at all.
    2. The recorded Cloud quota -- used once it is marked verified.
    3. `hard_ceiling_for(method)` -- the unconditional bound taken from this
       project's Cloud Console. Applied in both cases, so marking a quota
       verified later can never lift a cap above a limit Google is already
       enforcing. See `quota_ceilings.OBSERVED_DAILY_CEILINGS`.

    The configured value is only ever clamped, never raised: a stale or
    over-optimistic environment variable can make REVELA more conservative, and
    the clamp is logged so the mismatch is visible instead of silent.
    """
    requested = _int_setting(environ, name, default, aliases=aliases)
    cloud_quota = cloud_quota_for(method)
    recorded = getattr(cloud_quota, "daily", None) if cloud_quota else None
    if recorded is None:
        ceiling = default
    elif cloud_quota.verified:
        ceiling = recorded
    else:
        ceiling = min(default, recorded)
    hard_ceiling = hard_ceiling_for(method)
    if hard_ceiling is not None:
        ceiling = min(ceiling, hard_ceiling)
    clamped = min(requested, max(0, ceiling))
    if requested != clamped:
        # Name the setting that actually matched, which may be a legacy alias,
        # so the operator edits the right line in .env.
        matched = next(
            (n for n in (name, *aliases) if n in environ), name,
        )
        print(
            f"[quota_config] {matched}={requested} clamped to {clamped} "
            f"requests/day; Google Cloud allows {ceiling}/day for {method}."
        )
    return clamped


def load_api_quota_config(environ=None):
    environ = os.environ if environ is None else environ
    text_search_daily = _daily_cap(
        environ, "TEXT_SEARCH_DAILY_CAP", 80,
        "text_search", aliases=("TS_DAILY_CAP",),
    )
    text_search_monthly = _int_setting(
        environ, "TEXT_SEARCH_MONTHLY_CAP", 2500,
        aliases=("TS_MONTHLY_CAP",),
    )

    workflow_setting_names = {
        "registry_import": "TEXT_SEARCH_REGISTRY_IMPORT_DAILY_CAP",
        "snap_pins": "TEXT_SEARCH_SNAP_PINS_DAILY_CAP",
        "reverify": "TEXT_SEARCH_REVERIFY_DAILY_CAP",
    }
    workflow_defaults = {
        "registry_import": 200,
        "snap_pins": 100,
        "reverify": 100,
    }
    workflow_caps = {}
    explicit_workflow_total = 0
    unspecified_workflows = []
    for scope, name in workflow_setting_names.items():
        if name in environ:
            cap = _int_setting(environ, name, workflow_defaults[scope])
            workflow_caps[scope] = cap
            explicit_workflow_total += cap
        else:
            unspecified_workflows.append(scope)

    if explicit_workflow_total > text_search_daily:
        raise ValueError(
            "Text Search workflow daily caps must sum to no more than "
            "TEXT_SEARCH_DAILY_CAP."
        )
    remaining_workflow_budget = text_search_daily - explicit_workflow_total
    unspecified_default_total = sum(
        workflow_defaults[scope] for scope in unspecified_workflows
    )
    if unspecified_default_total:
        allocated = 0
        for scope in unspecified_workflows[:-1]:
            cap = (
                remaining_workflow_budget
                * workflow_defaults[scope]
                // unspecified_default_total
            )
            workflow_caps[scope] = cap
            allocated += cap
        if unspecified_workflows:
            workflow_caps[unspecified_workflows[-1]] = (
                remaining_workflow_budget - allocated
            )
    for scope in workflow_setting_names:
        workflow_caps.setdefault(scope, 0)

    place_details = MethodQuota(
        daily=_daily_cap(
            environ, "PLACE_DETAILS_DAILY_CAP", 90, "place_details",
            aliases=("PD_DAILY_CAP",),
        ),
        monthly=_int_setting(
            environ, "PLACE_DETAILS_MONTHLY_CAP", 3000,
            aliases=("PD_MONTHLY_CAP",),
        ),
    )
    geocoding = MethodQuota(
        daily=_daily_cap(
            environ, "GEOCODING_DAILY_CAP", 1500, "geocoding",
            aliases=("GEOCODE_DAILY_CAP",),
        ),
        monthly=_int_setting(
            environ, "GEOCODING_MONTHLY_CAP", 8000,
            aliases=("GEOCODE_MONTHLY_CAP",),
        ),
    )
    legacy_nearby = MethodQuota(
        daily=_daily_cap(
            environ, "LEGACY_NEARBY_DAILY_CAP", 120, "nearby_search_legacy",
            aliases=("PLACES_DAILY_CAP",),
        ),
        monthly=_int_setting(
            environ, "LEGACY_NEARBY_MONTHLY_CAP", 2000,
            aliases=("PLACES_MONTHLY_CAP",),
        ),
    )
    nearby_new = MethodQuota(
        daily=_daily_cap(
            environ, "NEARBY_NEW_DAILY_CAP", 0, "nearby_search_new",
            aliases=("NEW_NEARBY_DAILY_CAP",),
        ),
        monthly=_int_setting(
            environ, "NEARBY_NEW_MONTHLY_CAP", 0,
            aliases=("NEW_NEARBY_MONTHLY_CAP",),
        ),
    )
    nearby_api_mode = environ.get(
        "RUN_DETECTION_NEARBY_API", "legacy"
    ).strip().lower()
    if nearby_api_mode not in ("legacy", "new"):
        raise ValueError(
            "RUN_DETECTION_NEARBY_API must be either 'legacy' or 'new'."
        )
    max_seconds = _int_setting(
        environ, "RUN_DETECTION_MAX_SECONDS", 90, minimum=1
    )
    max_requests = _int_setting(
        environ, "RUN_DETECTION_MAX_REQUESTS", 120, minimum=1
    )
    requested_scan_limit = _int_setting(
        environ, "RUN_DETECTION_MONTHLY_SCAN_LIMIT", 10
    )
    active_nearby_quota = (
        nearby_new if nearby_api_mode == "new" else legacy_nearby
    )
    max_scans_from_nearby_budget = (
        active_nearby_quota.monthly // max_requests
    )

    return ApiQuotaConfig(
        text_search=MethodQuota(
            daily=text_search_daily,
            monthly=text_search_monthly,
        ),
        text_search_workflow_daily=MappingProxyType(workflow_caps),
        place_details=place_details,
        geocoding=geocoding,
        legacy_nearby=legacy_nearby,
        nearby_new=nearby_new,
        run_detection_nearby_api=nearby_api_mode,
        run_detection_monthly_scans=min(
            requested_scan_limit, max_scans_from_nearby_budget
        ),
        run_detection_max_seconds=max_seconds,
        run_detection_max_requests=max_requests,
        allow_quota_resets=environ.get("ALLOW_QUOTA_RESET") == "1",
    )


API_QUOTA_CONFIG = load_api_quota_config()
