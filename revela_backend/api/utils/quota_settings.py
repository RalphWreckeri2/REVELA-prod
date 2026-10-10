"""
Effective application quota = env baseline + persisted admin overrides,
clamped so an override can never exceed the recorded Google Cloud quota.

`API_QUOTA_CONFIG` is frozen at import time from environment variables, so it is
the *baseline*, not the live value. Every place that reserves a Google request
must ask this module for the current numbers instead of reading a module global,
otherwise an admin override would appear to save but change nothing.

Three separate limit concepts are kept apart on purpose (see the Phase 3
requirement to distinguish them in the UI):

  * `CLOUD_QUOTAS` in `quota_ceilings` — Google Cloud Console request limits.
    Read-only from the app's perspective.
  * the caps resolved here — REVELA's own budget, which must stay at or below
    the Cloud quota.
  * `REQUEST_PACING` in `quota_ceilings` — client-side politeness, unrelated to
    either of the above.

There is deliberately no bypass. `resolve()` clamps instead of raising the
value, and the only way a cap becomes zero is an explicit operator setting, not
a special flag.
"""

import threading
import time

from api.models import app_settings
from api.utils.quota_config import API_QUOTA_CONFIG
from api.utils.quota_ceilings import cloud_quota_for, hard_ceiling_for


# Re-read persisted overrides at most this often. Long enough that a 101-cell
# scan does not issue a settings SELECT per reservation, short enough that an
# admin change feels immediate.
_OVERRIDE_TTL_SECONDS = 5.0

_override_lock = threading.Lock()
_override_cache = None
_override_cached_at = 0.0


def _text_search_workflow_baseline():
    return dict(API_QUOTA_CONFIG.text_search_workflow_daily)


# key -> (kind, baseline, minimum, ceiling_method, ceiling_field, help)
#
# `kind` is "int" or "float" or "choice". `ceiling_method`/`ceiling_field` name
# the Cloud Console limit that bounds the value; None means the field is not
# bounded by a Cloud quota (it is bounded by a workflow invariant instead).
QUOTA_FIELDS = {
    "quota.text_search.daily": {
        "label": "Text Search — daily",
        "kind": "int", "baseline": API_QUOTA_CONFIG.text_search.daily,
        "minimum": 0, "ceiling_method": "text_search", "ceiling_field": "daily",
        "help": "Shared across registry import, Snap Pins, and Re-verify.",
    },
    "quota.text_search.monthly": {
        "label": "Text Search — monthly",
        "kind": "int", "baseline": API_QUOTA_CONFIG.text_search.monthly,
        "minimum": 0, "ceiling_method": None, "ceiling_field": None,
        "help": "App budget only. Google's Text Search monthly free calls are "
                "a billing allowance, not a request cap.",
    },
    "quota.text_search.workflow.registry_import": {
        "label": "Text Search — registry import / day",
        "kind": "int",
        "baseline": _text_search_workflow_baseline().get("registry_import", 0),
        "minimum": 0, "ceiling_method": None, "ceiling_field": None,
        "help": "Sub-budget. All three workflow caps must sum to no more than "
                "the Text Search daily cap.",
    },
    "quota.text_search.workflow.snap_pins": {
        "label": "Text Search — Snap Pins / day",
        "kind": "int",
        "baseline": _text_search_workflow_baseline().get("snap_pins", 0),
        "minimum": 0, "ceiling_method": None, "ceiling_field": None,
        "help": "Sub-budget. All three workflow caps must sum to no more than "
                "the Text Search daily cap.",
    },
    "quota.text_search.workflow.reverify": {
        "label": "Text Search — Re-verify / day",
        "kind": "int",
        "baseline": _text_search_workflow_baseline().get("reverify", 0),
        "minimum": 0, "ceiling_method": None, "ceiling_field": None,
        "help": "Sub-budget. All three workflow caps must sum to no more than "
                "the Text Search daily cap.",
    },
    "quota.place_details.daily": {
        "label": "Place Details — daily",
        "kind": "int", "baseline": API_QUOTA_CONFIG.place_details.daily,
        "minimum": 0, "ceiling_method": "place_details", "ceiling_field": "daily",
        "help": "Coordinate refresh only.",
    },
    "quota.place_details.monthly": {
        "label": "Place Details — monthly",
        "kind": "int", "baseline": API_QUOTA_CONFIG.place_details.monthly,
        "minimum": 0, "ceiling_method": None, "ceiling_field": None,
        "help": "App budget only.",
    },
    "quota.geocoding.daily": {
        "label": "Geocoding — daily",
        "kind": "int", "baseline": API_QUOTA_CONFIG.geocoding.daily,
        "minimum": 0, "ceiling_method": "geocoding", "ceiling_field": "daily",
        "help": "Fallback only. Separate billing SKU from Places.",
    },
    "quota.geocoding.monthly": {
        "label": "Geocoding — monthly",
        "kind": "int", "baseline": API_QUOTA_CONFIG.geocoding.monthly,
        "minimum": 0, "ceiling_method": None, "ceiling_field": None,
        "help": "App budget only.",
    },
    "quota.legacy_nearby.daily": {
        "label": "Nearby Search (legacy) — daily",
        "kind": "int", "baseline": API_QUOTA_CONFIG.legacy_nearby.daily,
        "minimum": 0, "ceiling_method": "nearby_search_legacy",
        "ceiling_field": "daily",
        "help": "Run Detection's active method. Cloud quota for this method "
                "has never been confirmed — confirm before raising.",
    },
    "quota.legacy_nearby.monthly": {
        "label": "Nearby Search (legacy) — monthly",
        "kind": "int", "baseline": API_QUOTA_CONFIG.legacy_nearby.monthly,
        "minimum": 0, "ceiling_method": None, "ceiling_field": None,
        "help": "App budget only.",
    },
    "quota.nearby_new.daily": {
        "label": "Nearby Search (New) — daily",
        "kind": "int", "baseline": API_QUOTA_CONFIG.nearby_new.daily,
        "minimum": 0, "ceiling_method": "nearby_search_new",
        "ceiling_field": "daily",
        "help": "Zero keeps Nearby Search (New) disabled until its rollout "
                "gate passes.",
    },
    "quota.nearby_new.monthly": {
        "label": "Nearby Search (New) — monthly",
        "kind": "int", "baseline": API_QUOTA_CONFIG.nearby_new.monthly,
        "minimum": 0, "ceiling_method": None, "ceiling_field": None,
        "help": "Zero keeps Nearby Search (New) disabled.",
    },
    "run_detection.monthly_scan_limit": {
        "label": "Run Detection — monthly scans",
        "kind": "int", "baseline": API_QUOTA_CONFIG.run_detection_monthly_scans,
        "minimum": 1, "ceiling_method": None, "ceiling_field": None,
        "help": "Also bounded by active Nearby monthly cap / per-run request "
                "cap, whichever is smaller.",
    },
    "run_detection.max_seconds": {
        "label": "Run Detection — work slice (seconds)",
        "kind": "int", "baseline": API_QUOTA_CONFIG.run_detection_max_seconds,
        "minimum": 5, "maximum": 600, "ceiling_method": None,
        "ceiling_field": None,
        "help": "Grid-traversal budget. Must stay under the hosting request "
                "deadline; pre-scan reconciliation is outside this slice.",
    },
    "run_detection.max_requests": {
        "label": "Run Detection — requests per slice",
        "kind": "int", "baseline": API_QUOTA_CONFIG.run_detection_max_requests,
        "minimum": 1, "maximum": 1000, "ceiling_method": None,
        "ceiling_field": None,
        "help": "Includes retries and adaptive child queries.",
    },
    "run_detection.grid_step_degrees": {
        "label": "Run Detection — grid step (degrees)",
        "kind": "float", "baseline": 0.009,
        "minimum": 0.001, "maximum": 0.011,
        "ceiling_method": None, "ceiling_field": None,
        "help": "Coverage is NOT monotonic in this value — 0.0105 opens a "
                "gap that 0.0100 and 0.0109 both cover. Re-run the grid "
                "coverage test for any change.",
    },
}

_TEXT_SEARCH_WORKFLOW_KEYS = (
    "quota.text_search.workflow.registry_import",
    "quota.text_search.workflow.snap_pins",
    "quota.text_search.workflow.reverify",
)

#: Which Nearby endpoint Run Detection uses. Switched only by redeploy, like the
#: original env var — deliberately NOT an admin-editable setting, because the
#: two methods bill different SKUs and have different Cloud quotas.
BASELINE_API_MODE = API_QUOTA_CONFIG.run_detection_nearby_api


def _baseline_for(key):
    return QUOTA_FIELDS[key]["baseline"]


def _coerce(key, raw):
    """Parse and range-check one submitted value. Raises ValueError."""
    spec = QUOTA_FIELDS[key]
    if spec["kind"] == "float":
        try:
            value = float(raw)
        except (TypeError, ValueError):
            raise ValueError(f"{spec['label']} must be a number.") from None
    elif spec["kind"] == "int":
        if isinstance(raw, bool):
            raise ValueError(f"{spec['label']} must be a whole number.")
        try:
            value = int(raw)
        except (TypeError, ValueError):
            raise ValueError(
                f"{spec['label']} must be a whole number.") from None
        if float(raw) != float(value):
            raise ValueError(f"{spec['label']} must be a whole number.")
    else:  # pragma: no cover - no choice fields today
        value = raw

    if value < spec["minimum"]:
        raise ValueError(
            f"{spec['label']} must be at least {spec['minimum']}."
        )
    if "maximum" in spec and value > spec["maximum"]:
        raise ValueError(
            f"{spec['label']} must be no more than {spec['maximum']}."
        )

    cloud = _ceiling_for(key)
    if cloud is not None and value > cloud:
        raise ValueError(
            f"{spec['label']} cannot exceed the Google Cloud quota of "
            f"{cloud} requests/day. Lower the Cloud-side limit in Cloud "
            f"Console first, then update the ceiling in "
            f"api/utils/quota_ceilings.py."
        )
    cloud_method = spec.get("ceiling_method")
    cloud_quota = cloud_quota_for(cloud_method) if cloud_method else None
    if (
        cloud_quota is not None
        and not cloud_quota.verified
        and value > spec["baseline"]
    ):
        raise ValueError(
            f"{spec['label']} cannot be raised above its current environment "
            "baseline until the Google Cloud quota is verified."
        )
    return value


def _ceiling_for(key):
    """
    Hard upper bound for one field, or None when nothing bounds it.

    Two sources, combined by taking the stricter:
      * the recorded Cloud quota, but only once it is marked verified; and
      * `hard_ceiling_for()`, the unconditional per-method bound read off this
        project's Cloud Console, which applies even while the quota is still
        unverified.

    That second source is what makes it impossible for a future
    quota-verification edit to quietly raise an application cap above a limit
    Google is already enforcing.
    """
    spec = QUOTA_FIELDS[key]
    method = spec.get("ceiling_method")
    if not method:
        return None
    quota = cloud_quota_for(method)
    verified_ceiling = None
    if quota is not None and quota.verified:
        verified_ceiling = getattr(quota, spec["ceiling_field"], None)

    hard_ceiling = None
    if spec["ceiling_field"] == "daily":
        hard_ceiling = hard_ceiling_for(method)

    ceilings = [c for c in (verified_ceiling, hard_ceiling) if c is not None]
    if not ceilings:
        return None
    return min(ceilings)


# Resolve every ceiling once so validation, the snapshot, and the admin UI all
# read the same number instead of each re-deriving it.
for _key, _spec in QUOTA_FIELDS.items():
    _spec["cloud_ceiling"] = _ceiling_for(_key)


def _overrides(force_reload=False):
    global _override_cache, _override_cached_at
    now = time.monotonic()
    with _override_lock:
        fresh = (
            _override_cache is not None
            and not force_reload
            and (now - _override_cached_at) < _OVERRIDE_TTL_SECONDS
        )
        if fresh:
            return _override_cache
        stored = app_settings.load_all()
        relevant = {
            key: stored[key] for key in QUOTA_FIELDS if key in stored
        }
        _override_cache = relevant
        _override_cached_at = now
        return relevant


def invalidate():
    """Drop the override cache so the next read hits the database."""
    global _override_cache, _override_cached_at
    with _override_lock:
        _override_cache = None
        _override_cached_at = 0.0


def cap(key):
    """Current effective value for one cap. Used by every reservation site."""
    stored = _overrides()
    if key not in stored:
        return _baseline_for(key)
    try:
        # Re-validate on read: a value that was legal when written could become
        # illegal if the Cloud ceiling in code is later lowered.
        return _coerce(key, stored[key])
    except ValueError:
        print(
            f"[quota_settings] Stored override for '{key}' is no longer "
            f"valid; using the env baseline instead."
        )
        return _baseline_for(key)


def validate_patch(patch):
    """
    Validate a whole submitted settings patch atomically.

    Returns (clean_values, errors). Nothing is written unless errors is empty,
    so a bad field cannot leave a half-applied quota change behind.
    """
    errors = []
    clean = {}

    for key, raw in patch.items():
        if key not in QUOTA_FIELDS:
            errors.append(f"Unknown setting: {key}")
            continue
        try:
            clean[key] = _coerce(key, raw)
        except ValueError as exc:
            errors.append(str(exc))

    # Workflow sub-budgets must not exceed the shared Text Search daily cap.
    # When the admin lowers the shared cap without naming individual workflows,
    # redistribute it across the three in proportion to their current values —
    # the same thing `load_api_quota_config` does for environment variables.
    # Without this, lowering the daily cap alone could never succeed, because
    # the defaults still add up to the old cap.
    if not errors and "quota.text_search.daily" in clean:
        explicit = [k for k in _TEXT_SEARCH_WORKFLOW_KEYS if k in clean]
        if len(explicit) < len(_TEXT_SEARCH_WORKFLOW_KEYS):
            daily = clean["quota.text_search.daily"]
            current = {
                k: clean.get(k, cap(k)) for k in _TEXT_SEARCH_WORKFLOW_KEYS
            }
            weight_total = sum(current.values())
            if weight_total > 0:
                allocated = 0
                targets = [
                    k for k in _TEXT_SEARCH_WORKFLOW_KEYS if k not in clean
                ]
                for key in targets[:-1]:
                    share = daily * current[key] // weight_total
                    clean[key] = share
                    allocated += share
                if targets:
                    clean[targets[-1]] = daily - allocated

    if not errors:
        daily = clean.get(
            "quota.text_search.daily", cap("quota.text_search.daily")
        )
        total = sum(
            clean.get(key, cap(key)) for key in _TEXT_SEARCH_WORKFLOW_KEYS
        )
        if total > daily:
            errors.append(
                f"Text Search workflow caps total {total}, which exceeds the "
                f"Text Search daily cap of {daily}."
            )

    # A scan limit the Nearby monthly budget cannot fund would advertise scans
    # that can never complete.
    if not errors:
        scans = clean.get(
            "run_detection.monthly_scan_limit",
            cap("run_detection.monthly_scan_limit"),
        )
        max_requests = clean.get(
            "run_detection.max_requests", cap("run_detection.max_requests")
        )
        if cap("quota.nearby_new.daily") > 0:
            nearby_monthly = clean.get(
                "quota.nearby_new.monthly", cap("quota.nearby_new.monthly")
            )
        else:
            nearby_monthly = clean.get(
                "quota.legacy_nearby.monthly",
                cap("quota.legacy_nearby.monthly"),
            )
        fundable = nearby_monthly // max_requests if max_requests else 0
        if scans > fundable:
            errors.append(
                f"Monthly scan limit {scans} cannot be funded: the active "
                f"Nearby monthly cap is {nearby_monthly} and each slice may "
                f"use {max_requests} requests, allowing at most {fundable} "
                f"full slices."
            )

    return clean, errors


def snapshot():
    """Full picture for the admin UI: value, baseline, source, ceiling."""
    stored = _overrides()
    fields = {}
    for key, spec in QUOTA_FIELDS.items():
        effective = cap(key)
        cloud = _ceiling_for(key)
        overridden = key in stored and effective != spec["baseline"]
        fields[key] = {
            "label": spec["label"],
            "kind": spec["kind"],
            "value": effective,
            "baseline": spec["baseline"],
            "source": "admin_override" if overridden else "env",
            "minimum": spec["minimum"],
            "maximum": spec.get("maximum"),
            "cloud_ceiling": cloud,
            "cloud_quota_reported": (
                getattr(cloud_quota_for(spec.get("ceiling_method")),
                        spec.get("ceiling_field"), None)
                if spec.get("ceiling_method") else None
            ),
            "cloud_quota_verified": bool(
                (quota := cloud_quota_for(spec.get("ceiling_method")))
                and quota.verified
            ),
            "cloud_quota_source": (
                quota.source if spec.get("ceiling_method")
                and (quota := cloud_quota_for(spec.get("ceiling_method")))
                else "No method-specific Cloud quota recorded."
            ),
            "help": spec["help"],
        }
    return fields


def save(patch, user_id=None):
    """Validate then persist a patch. Returns (result, error)."""
    clean, errors = validate_patch(patch)
    if errors:
        return None, "; ".join(errors)
    saved, error = app_settings.save_many(clean, user_id=user_id)
    if error:
        return None, error
    invalidate()
    return {"saved": saved, "fields": snapshot()}, None


def clear_overrides(user_id=None):
    """Discard admin overrides so the environment baseline applies again."""
    removed, error = app_settings.delete_many(list(QUOTA_FIELDS))
    if error:
        return None, error
    invalidate()
    return {"removed": removed, "fields": snapshot()}, None
