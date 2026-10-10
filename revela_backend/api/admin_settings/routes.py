"""
Admin-only "API Usage & Testing" endpoints.

Two authorization tiers, and the split is deliberate:

  * `@admin_required()`   -- read-only monitoring. Every admin needs to see how
    much of the shared Google request budget is spent.
  * `@super_admin_required()` -- anything that CHANGES how REVELA spends quota
    or stores Google-derived data: application quota edits and resets, Test Mode
    configuration and resets, and fixture purge.

The Super Admin tier exists because the frontend gate is cosmetic. Hiding the
Advanced Settings block is not an authorization boundary; a client that calls
`PUT /api/admin-settings/quota` directly must be refused by the server too.

Deliberately absent: any global quota bypass, any way to reset or truncate
production usage counters, and any Google Cloud Console control. Caps can only
be lowered or raised up to a recorded Cloud ceiling, and clearing an override
returns to the environment baseline rather than granting unlimited usage.
"""

from flask import Blueprint, jsonify, request
from flask_jwt_extended import get_jwt_identity

from api.flags.service import _load_registry, _match_poi_to_registry
from api.middleware.decorators import admin_required, super_admin_required
from api.utils import quota_settings, test_mode, usage_report


admin_settings_bp = Blueprint("admin_settings", __name__)


def _actor_id():
    try:
        return int(get_jwt_identity())
    except Exception:
        return None


# ── GET /api/admin-settings/usage ─────────────────────────────────────────────
#
# Read-only and admin-accessible on purpose: usage monitoring is something
# every administrator needs, including Super Admin.


@admin_settings_bp.route("/usage", methods=["GET"])
@admin_required()
def usage_route():
    """
    Unified usage/limits/cost report.

    200 on success, 500 if the usage ledger cannot be read. Never mutates.
    """
    try:
        return jsonify(usage_report.build_usage_report()), 200
    except Exception as exc:
        print(f"[admin_settings] usage report failed ({type(exc).__name__})")
        return jsonify({"error": "Could not build the usage report."}), 500


# ── GET/PUT /api/admin-settings/quota ─────────────────────────────────────────
#
# Super Admin only. This payload exists solely for the Advanced Settings block
# and directly changes how many Google requests REVELA is willing to spend.


@admin_settings_bp.route("/quota", methods=["GET"])
@super_admin_required()
def get_quota_route():
    """Effective quota settings with baseline, source, and Cloud ceiling."""
    return jsonify({
        "fields": quota_settings.snapshot(),
        "note": "An admin override can never raise a cap above the recorded "
                "Google Cloud quota.",
    }), 200


@admin_settings_bp.route("/quota", methods=["PUT"])
@super_admin_required()
def update_quota_route():
    """
    Persist quota overrides.

    The patch is validated as a unit: if any field is rejected nothing is
    written, so a bad value cannot leave a half-applied budget change.

    200 on success, 400 with every validation message on failure.
    """
    patch = request.get_json(silent=True)
    if not isinstance(patch, dict) or not patch:
        return jsonify({"error": "Request body must be a JSON object of settings."}), 400
    if any(not isinstance(k, str) for k in patch):
        return jsonify({"error": "Setting keys must be strings."}), 400

    result, error = quota_settings.save(patch, user_id=_actor_id())
    if error:
        return jsonify({"error": error}), 400
    return jsonify(result), 200


@admin_settings_bp.route("/quota/reset", methods=["POST"])
@super_admin_required()
def reset_quota_route():
    """
    Discard admin overrides so the environment baseline applies again.

    This restores configured behaviour; it does not grant extra quota and does
    not touch usage counters.
    """
    result, error = quota_settings.clear_overrides(user_id=_actor_id())
    if error:
        return jsonify({"error": error}), 500
    return jsonify(result), 200


# ── GET/PUT /api/admin-settings/test-mode ─────────────────────────────────────
#
# Super Admin only. Test Mode changes live request behaviour and fixture
# storage persists Google-derived payloads on the server.


@admin_settings_bp.route("/test-mode", methods=["GET"])
@super_admin_required()
def get_test_mode_route():
    """Test Mode configuration plus fixture cache statistics."""
    return jsonify({
        "config": test_mode.get_config(),
        "fixtures": test_mode.fixture_stats(),
        "note": "Replaying a stored fixture issues no Google request and is "
                "not charged to the usage ledger, so testing never requires "
                "clearing usage rows.",
    }), 200


@admin_settings_bp.route("/test-mode", methods=["PUT"])
@super_admin_required()
def update_test_mode_route():
    """
    Persist Test Mode settings. 200 on success, 400 on any validation error.
    """
    patch = request.get_json(silent=True)
    if not isinstance(patch, dict) or not patch:
        return jsonify({"error": "Request body must be a JSON object of settings."}), 400

    result, error = test_mode.save_config(patch, user_id=_actor_id())
    if error:
        return jsonify({"error": error}), 400
    return jsonify(result), 200


@admin_settings_bp.route("/test-mode/reset", methods=["POST"])
@super_admin_required()
def reset_test_mode_route():
    """Restore Test Mode defaults. Never touches usage counters."""
    result, error = test_mode.reset_config(user_id=_actor_id())
    if error:
        return jsonify({"error": error}), 500
    return jsonify(result), 200


@admin_settings_bp.route("/test-mode/fixtures/purge", methods=["POST"])
@super_admin_required()
def purge_fixtures_route():
    """
    Delete cached request payloads.

    `older_than_days` defaults to the configured retention window; pass 0 to
    delete every fixture. Usage counters are untouched.
    """
    body = request.get_json(silent=True) or {}
    older = body.get("older_than_days")
    removed, error = test_mode.purge_fixtures(older_than_days=older)
    if error:
        return jsonify({"error": error}), 400
    return jsonify({
        "removed": removed,
        "fixtures": test_mode.fixture_stats(),
    }), 200


# ── POST /api/admin-settings/matching-dry-run ─────────────────────────────────
#
# Stays on the plain admin tier: it is a pure, read-only matcher replay. It
# reserves no quota, writes no usage row, creates no flag, and stores nothing,
# so it neither spends Google budget nor exposes a Google-derived dataset.


@admin_settings_bp.route("/matching-dry-run", methods=["POST"])
@admin_required()
def matching_dry_run_route():
    """
    Replay POI candidates through the matcher with no Google traffic at all.

    This is the cheapest way to iterate on matching rules: it reads the
    registry, runs `_match_poi_to_registry`, and returns the decision for each
    supplied candidate. No request is reserved, no ledger row is written, and
    no flag is created — the matcher is pure, but the caller must not be
    allowed to mistake this for a scan.

    Body: {"candidates": [{"name", "lat", "lng", "types", "address", ...}]}
    """
    body = request.get_json(silent=True) or {}
    candidates = body.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        return jsonify({"error": "'candidates' must be a non-empty array."}), 400
    if len(candidates) > 500:
        return jsonify({"error": "At most 500 candidates per dry run."}), 400

    try:
        registry = _load_registry()
    except Exception as exc:
        print(f"[admin_settings] dry run could not load registry ({exc})")
        return jsonify({"error": "Could not load the official registry."}), 500

    results = []
    for index, candidate in enumerate(candidates):
        if not isinstance(candidate, dict):
            results.append({"index": index, "error": "Candidate must be an object."})
            continue
        name = candidate.get("name")
        try:
            lat = float(candidate.get("lat"))
            lng = float(candidate.get("lng"))
        except (TypeError, ValueError):
            results.append({
                "index": index, "error": "Candidate needs numeric lat/lng.",
            })
            continue
        types = candidate.get("types") or ()
        if isinstance(types, str):
            types = (types,)
        try:
            entry, distance, score, status = _match_poi_to_registry(
                name, lat, lng, registry,
                poi_barangay_id=candidate.get("barangay_id"),
                poi_types=tuple(types),
                poi_address=candidate.get("address") or "",
            )
        except Exception as exc:
            print(f"[admin_settings] dry run matcher error ({exc})")
            results.append({"index": index, "error": "Matcher failed."})
            continue
        results.append({
            "index": index,
            "name": name,
            "match_status": status,
            "score": round(float(score or 0.0), 4),
            "distance_m": (
                round(float(distance), 1)
                if distance is not None and distance != float("inf") else None
            ),
            "matched_business_id": entry.get("businessID") if entry else None,
            "matched_business_name": entry.get("businessName") if entry else None,
            "matched_application_status": (
                entry.get("applicationStatus") if entry else None
            ),
        })

    return jsonify({
        "registry_size": len(registry),
        "candidates_evaluated": len(results),
        "google_requests_made": 0,
        "usage_rows_written": 0,
        "results": results,
    }), 200
