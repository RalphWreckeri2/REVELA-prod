"""
Unified API usage, quota, and cost report for the admin panel.

Assembles one payload that keeps the three limit concepts separate, which is
the whole point of the Phase 3 requirement:

  * `google_cloud_quota` — Google Cloud Console request limits. Reported only.
  * `revela_app_cap`     — REVELA's own budget, resolved from env + overrides.
  * `request_pacing`     — REVELA's client-side inter-request delay.

Every number is labelled with where it came from, and anything not confirmed in
Cloud Console is flagged `verified: false` rather than presented as fact.

Cost figures are estimates computed from a static per-SKU table. Google removed
the USD monthly credit in March 2025 and replaced it with per-SKU free call
allowances, so free usage does not offset another SKU and exceeding an allowance
is billable rather than blocked.
"""

from datetime import datetime

from api.utils import quota_settings, test_mode
from api.utils.places_quota import read_daily_usage, read_usage
from api.utils.quota_ceilings import (
    SKU_PRICING,
    cloud_quota_for,
    pacing_for,
    sku_for,
)
from app import mysql


#: method key -> (monthly ledger kind, daily ledger kind)
_LEDGER_KINDS = {
    "text_search": ("imp_ts_month", "imp_ts_day"),
    "place_details": ("imp_pd_month", "imp_pd_day"),
    "nearby_search_legacy": ("month", "day"),
    "nearby_search_new": ("new_nearby_month", "new_nearby_day"),
    "geocoding": ("geo_month", "geo_day"),
}

METHOD_LABELS = {
    "text_search": "Text Search (New)",
    "place_details": "Place Details (New)",
    "nearby_search_legacy": "Nearby Search (legacy)",
    "nearby_search_new": "Nearby Search (New)",
    "geocoding": "Geocoding",
}

#: Which app cap key bounds each method's daily/monthly budget.
_CAP_KEYS = {
    "text_search": ("quota.text_search.daily", "quota.text_search.monthly"),
    "place_details": ("quota.place_details.daily", "quota.place_details.monthly"),
    "nearby_search_legacy": (
        "quota.legacy_nearby.daily", "quota.legacy_nearby.monthly",
    ),
    "nearby_search_new": (
        "quota.nearby_new.daily", "quota.nearby_new.monthly",
    ),
    "geocoding": ("quota.geocoding.daily", "quota.geocoding.monthly"),
}

WORKFLOW_LABELS = {
    "registry_import": "Registry import",
    "snap_pins": "Snap Pins",
    "reverify": "Re-verify",
}
_WORKFLOW_LEDGER = {
    "registry_import": "ts_import_day",
    "snap_pins": "ts_snap_day",
    "reverify": "ts_reverify_day",
}


def _estimate_cost(method, used_month):
    """
    Estimated monthly cost for one method.

    Returns None when no pricing is recorded, so the UI can say "pricing not
    available" instead of showing a fabricated zero.
    """
    sku_key = sku_for(method)
    pricing = SKU_PRICING.get(sku_key)
    if not pricing:
        return None
    free = pricing.get("free_monthly")
    rate = pricing.get("overage_per_1000")
    billable = 0 if free is None else max(0, used_month - free)
    cost = (billable / 1000.0) * rate
    return {
        "sku": sku_key,
        "sku_label": pricing["label"],
        "free_monthly_calls": free,
        "billable_calls": billable,
        "overage_per_1000": rate,
        "estimated_cost_usd": round(cost, 2),
        "pricing_verified": pricing.get("verified", False),
        "note": (
            "Estimate only. Free usage is per SKU and does not offset other "
            "SKUs; there is no USD monthly credit to fall back on."
        ),
    }


def _method_report(method):
    daily_key, monthly_key = _CAP_KEYS[method]
    daily_cap = quota_settings.cap(daily_key)
    monthly_cap = quota_settings.cap(monthly_key)

    usage = read_usage(mysql.connection, *_LEDGER_KINDS[method])
    used_month, used_day = usage["month"], usage["day"]

    cloud = cloud_quota_for(method)
    pacing = pacing_for(method)
    snapshot = quota_settings.snapshot()
    daily_field = snapshot[daily_key]
    monthly_field = snapshot[monthly_key]

    return {
        "method": method,
        "label": METHOD_LABELS[method],
        "google_cloud_quota": {
            "daily_requests": getattr(cloud, "daily", None) if cloud else None,
            "per_minute_requests": (
                getattr(cloud, "per_minute", None) if cloud else None
            ),
            "verified": bool(cloud and cloud.verified),
            "source": cloud.source if cloud else "Not recorded.",
            "note": "Google Cloud Console limit. Read-only here; REVELA's app "
                    "cap must stay at or below it.",
        },
        "revela_app_cap": {
            "daily_cap": daily_cap,
            "daily_cap_source": daily_field["source"],
            "daily_cloud_ceiling": daily_field["cloud_ceiling"],
            "monthly_cap": monthly_cap,
            "monthly_cap_source": monthly_field["source"],
            "used_today": used_day,
            "used_month": used_month,
            "daily_remaining": max(0, daily_cap - used_day),
            "monthly_remaining": max(0, monthly_cap - used_month),
            "daily_quota_exceeded": daily_cap > 0 and used_day >= daily_cap,
            "monthly_quota_exceeded": monthly_cap > 0 and used_month >= monthly_cap,
            "disabled": daily_cap <= 0 and monthly_cap <= 0,
            "over_cloud_ceiling": bool(
                daily_field["cloud_quota_verified"]
                and daily_field["cloud_ceiling"] is not None
                and daily_cap > daily_field["cloud_ceiling"]
            ),
            "over_unverified_cloud_report": bool(
                not daily_field["cloud_quota_verified"]
                and daily_field["cloud_quota_reported"] is not None
                and daily_cap > daily_field["cloud_quota_reported"]
            ),
        },
        "request_pacing": {
            "min_interval_ms": pacing["min_interval_ms"],
            "enforced": pacing["enforced"],
            "note": pacing["note"],
        },
        "cost_estimate": _estimate_cost(method, used_month),
    }


def build_usage_report():
    """Full usage + limits + cost payload for the admin panel."""
    methods = [_method_report(name) for name in _LEDGER_KINDS]

    workflow_usage = {}
    for scope, ledger_kind in _WORKFLOW_LEDGER.items():
        used = read_daily_usage(mysql.connection, ledger_kind)
        cap_key = f"quota.text_search.workflow.{scope}"
        cap = quota_settings.cap(cap_key)
        field = quota_settings.snapshot()[cap_key]
        workflow_usage[scope] = {
            "label": WORKFLOW_LABELS[scope],
            "used_today": used,
            "daily_cap": cap,
            "daily_remaining": max(0, cap - used),
            "daily_quota_exceeded": cap > 0 and used >= cap,
            "source": field["source"],
        }

    run_detection = {
        "monthly_scan_limit": quota_settings.cap("run_detection.monthly_scan_limit"),
        "work_slice_seconds": quota_settings.cap("run_detection.max_seconds"),
        "work_slice_requests": quota_settings.cap("run_detection.max_requests"),
        "grid_step_degrees": quota_settings.cap("run_detection.grid_step_degrees"),
        "nearby_api_mode": quota_settings.BASELINE_API_MODE,
        "note": "The work slice bounds grid traversal only. Pre-scan "
                "reconciliation runs before it and counts toward total "
                "request time.",
    }

    total_estimate = 0.0
    priced = 0
    for report in methods:
        estimate = report["cost_estimate"]
        if estimate:
            total_estimate += estimate["estimated_cost_usd"]
            priced += 1

    return {
        "generated_at": datetime.now().isoformat(sep=" ", timespec="seconds"),
        "methods": methods,
        "text_search_workflows": workflow_usage,
        "run_detection": run_detection,
        "test_mode": {
            "enabled": test_mode.is_enabled(),
            "policy": test_mode.get_config()["test_mode.fixture_policy"],
            "note": "While enabled, repeated requests replay stored fixtures "
                    "and are not charged to the usage ledger. Real calls are "
                    "still reserved and counted normally.",
        },
        "totals": {
            "methods_reported": len(methods),
            "methods_with_pricing": priced,
            "estimated_monthly_cost_usd": round(total_estimate, 2),
            "pricing_is_estimate": True,
        },
        "legend": {
            "google_cloud_quota": "Limit Google imposes. Not editable here.",
            "revela_app_cap": "REVELA's own budget. Editable, but clamped to "
                              "the Cloud quota above.",
            "request_pacing": "REVELA's client-side delay between requests. "
                              "Unrelated to either limit.",
        },
    }
