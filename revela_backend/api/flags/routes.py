from api.utils.cancellation import set_cancel
from api.models.detection_runs import get_detection_quota_info
from api.utils.quota_config import API_QUOTA_CONFIG
import os
import uuid
from flask import Blueprint, request, jsonify, current_app
from flask_jwt_extended import get_jwt_identity
from api.flags.service import (
    run_detection,
    get_flags,
    insert_yellow_flag,
    update_flag_color,
    BlackLockedError,
    escalate_to_black,
    FlagEscalationForbidden,
    FlagEscalationConflict,
    FlagEscalationNotFound,
    delete_flag,
    reconcile_existing_flags,
    update_flag_location,
    get_places_usage_today,
    YellowFlagSubmissionConflict,
    YellowFlagValidationError,
)
from api.middleware.decorators import jwt_required, admin_required, get_current_role
from api.registry.locks import BlackBusinessDeletionForbidden
from api.registry import service as registry_service
from app import mysql
flags_bp = Blueprint("flags", __name__)


@flags_bp.route("/inspection-verified-compliant", methods=["GET"])
@admin_required()
def inspection_verified_compliant_route():
    """All eligible rows for one shared View List / PDF / CSV snapshot."""
    from api.flags.compliance_report import get_inspection_verified_compliant
    try:
        return jsonify(get_inspection_verified_compliant()), 200
    except Exception:
        current_app.logger.exception("Could not load current-compliance report")
        return jsonify({"error": "Unable to load inspection-verified compliant businesses."}), 500


# ── GET /api/flags/places-usage ───────────────────────────────────────────────


@flags_bp.route("/places-usage", methods=["GET"])
@admin_required()
def places_usage_route():
    """Return today's Places API usage and daily caps."""
    return jsonify(get_places_usage_today()), 200

# ── GET /api/flags/detection-quota ────────────────────────────────────────────


@flags_bp.route("/detection-quota", methods=["GET"])
@jwt_required()
def get_detection_quota_route():
    """Get detection scan quota and status for the current month."""
    quota = get_detection_quota_info()
    return jsonify(quota), 200

# ── POST /api/flags/reset-quota ───────────────────────────────────────────────


@flags_bp.route("/reset-quota", methods=["POST"])
@admin_required()
def reset_detection_quota_route():
    """Reset detection scan quota for testing purposes."""
    if not API_QUOTA_CONFIG.allow_quota_resets:
        return jsonify({"error": "Quota reset is disabled in production."}), 403
    from api.models.detection_runs import reset_detection_quota
    reset_detection_quota()
    updated_quota = get_detection_quota_info()
    return jsonify({"message": "Monthly detection limit reset successfully.", "quota": updated_quota}), 200

# ── POST /api/flags/cancel-detection ──────────────────────────────────────────


@flags_bp.route("/cancel-detection", methods=["POST"])
@admin_required()
def cancel_detection_route():
    """Cancel an ongoing detection task."""
    set_cancel("run_detection", True)
    return jsonify({"message": "Cancellation requested"}), 200

# ── POST /api/flags/run-detection ─────────────────────────────────────────────


@flags_bp.route("/run-detection", methods=["POST"])
@admin_required()
def run_detection_route():
    """Trigger a detection scan in either quick or full mode."""
    user_id = None
    try:
        user_id = int(get_jwt_identity())
    except Exception:
        pass

    payload = request.get_json(silent=True) or {}
    mode = str(payload.get("mode", "quick") or "quick").strip().lower()
    if mode not in {"quick", "full"}:
        mode = "quick"

    result, error = run_detection(user_id=user_id, mode=mode)
    if error:
        if error == "A detection scan is already in progress.":
            return jsonify({"error": error}), 409
        if result and result.get("status") in (
            "skipped_quota", "daily_quota_exceeded", "monthly_quota_exceeded"
        ):
            return jsonify({"error": error, **result}), 429
        if error == "Detection cancelled by user.":
            return jsonify({"message": error}), 200
        if "Monthly detection limit reached" in error or ("Places API" in error and "limit reached" in error) or "budget" in error.lower():
            return jsonify({"error": error}), 429
        if "official business registry is empty" in error.lower():
            return jsonify({"error": error}), 400
        return jsonify({"error": error}), 500
    return jsonify(result), 200


# ── POST /api/flags/reconcile ─────────────────────────────────────────────────
@flags_bp.route("/reconcile", methods=["POST"])
@admin_required()
def reconcile_flags_route():
    """Re-evaluate all existing Red flags against the official registry.
    Any Red flag whose name/location matches a registered business is
    converted to the appropriate permit-status color (Green, Orange, etc.)."""
    try:
        cursor = mysql.connection.cursor()
        cursor.execute("SELECT COUNT(*) AS total FROM official_registry")
        reg_row = cursor.fetchone()
        reg_count = (reg_row.get("total") if isinstance(
            reg_row, dict) else reg_row[0]) if reg_row else 0

        cursor.execute(
            "SELECT COUNT(*) AS total FROM geospatial_logs WHERE flagColor = 'Red' AND latitude IS NOT NULL AND longitude IS NOT NULL")
        red_row = cursor.fetchone()
        red_count = (red_row.get("total") if isinstance(
            red_row, dict) else red_row[0]) if red_row else 0
        cursor.close()

        if reg_count == 0:
            return jsonify({"error": "Cannot reconcile: The official business registry is empty. Please import business records first."}), 400

        if red_count == 0:
            return jsonify({
                "message": "No Red flags to reconcile. All existing flags are already reconciled.",
                "converted": 0,
                "reconciled_records": 0,
                "total": 0,
            }), 200

        from api.registry.audit import ensure_registry_workflow_events
        ensure_registry_workflow_events()
        cursor = mysql.connection.cursor()
        cursor.execute(
            "SELECT COALESCE(MAX(eventID), 0) AS last_event_id FROM registry_workflow_events")
        event_row = cursor.fetchone()
        last_event_id = (
            event_row.get("last_event_id")
            if isinstance(event_row, dict)
            else event_row[0]
        ) if event_row else 0
        cursor.close()

        converted = reconcile_existing_flags(force=True)

        cursor = mysql.connection.cursor()
        cursor.execute("""
            SELECT COUNT(DISTINCT businessID) AS total
            FROM registry_workflow_events
            WHERE eventType = 'reconciled' AND eventID > %s
        """, (last_event_id,))
        reconciled_row = cursor.fetchone()
        reconciled_records = (
            reconciled_row.get("total")
            if isinstance(reconciled_row, dict)
            else reconciled_row[0]
        ) if reconciled_row else 0
        cursor.close()
        return jsonify({
            "message": f"{converted} flag(s) reconciled out of {red_count} Red flag(s).",
            "converted": converted,
            "reconciled_records": int(reconciled_records),
            "total": red_count,
        }), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── GET /api/flags ────────────────────────────────────────────────────────────
@flags_bp.route("", methods=["GET"])
@flags_bp.route("/", methods=["GET"])
@jwt_required()
def get_flags_route():
    """Return all geospatial log entries, filterable by color and barangayID."""
    color = request.args.get("color")
    barangay_id = request.args.get("barangayID", type=int)
    page = request.args.get("page",  1,  type=int)
    per_page = request.args.get("limit", 50, type=int)
    reported_by_user_id = request.args.get("reportedByUserID", type=int)

    result, error = get_flags(
        color=color,
        barangay_id=barangay_id,
        page=page,
        per_page=per_page,
        reported_by_user_id=reported_by_user_id,
    )
    if error:
        return jsonify({"error": error}), 500
    return jsonify(result), 200


# ── GET /api/flags/mine ───────────────────────────────────────────────────────
@flags_bp.route("/mine", methods=["GET"])
@jwt_required()
def get_my_flags_route():
    """Return all flags reported by the currently authenticated inspector."""
    user_id = int(get_jwt_identity())
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("limit", 100, type=int)

    result, error = get_flags(
        reported_by_user_id=user_id,
        page=page,
        per_page=per_page,
    )
    if error:
        return jsonify({"error": error}), 500
    return jsonify(result), 200


@flags_bp.route("/location-search", methods=["POST"])
@jwt_required()
def yellow_flag_location_search_route():
    """Return geocoding matches and precision metadata for a Yellow Flag address."""
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "A JSON request body is required."}), 400
    street_value = data.get("streetAddress")
    barangay_value = data.get("barangay")
    street_address = street_value.strip() if isinstance(street_value, str) else ""
    barangay = barangay_value.strip() if isinstance(barangay_value, str) else ""
    if not street_address or len(street_address) > 255:
        return jsonify({
            "error": "Street / Purok / Landmark is required (maximum 255 characters).",
        }), 400
    if len(barangay) > 100:
        return jsonify({"error": "Barangay name cannot exceed 100 characters."}), 400

    candidates, error = registry_service.search_address_candidates(
        street_address, barangay or None,
    )
    if error == "not_configured":
        return jsonify({
            "code": error,
            "error": "Address search is unavailable: server geocoding is not configured.",
        }), 503
    if error == "quota_exceeded":
        return jsonify({
            "code": error,
            "error": "Address search quota is unavailable. Try again later.",
        }), 429
    if error == "network_error":
        return jsonify({
            "code": error,
            "error": "The address search provider could not be reached.",
        }), 502
    if error is not None or candidates is None:
        return jsonify({
            "code": error or "provider_error",
            "error": "The address search provider returned an error.",
        }), 502
    return jsonify({"results": candidates}), 200


@flags_bp.route("/reverse-geocode", methods=["POST"])
@jwt_required()
def yellow_flag_reverse_geocode_route():
    """Return a human-readable address for a Yellow Flag GPS location."""
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "A JSON request body is required."}), 400
    latitude = data.get("latitude")
    longitude = data.get("longitude")
    if (
        isinstance(latitude, bool)
        or isinstance(longitude, bool)
        or not isinstance(latitude, (int, float))
        or not isinstance(longitude, (int, float))
    ):
        return jsonify({"error": "Valid latitude and longitude are required."}), 400

    address, error = registry_service.reverse_geocode_coordinates(
        latitude, longitude,
    )
    if error == "not_configured":
        return jsonify({
            "code": error,
            "error": "Reverse geocoding is unavailable: server geocoding is not configured.",
        }), 503
    if error == "quota_exceeded":
        return jsonify({
            "code": error,
            "error": "Reverse geocoding quota is unavailable. Try again later.",
        }), 429
    if error == "network_error":
        return jsonify({
            "code": error,
            "error": "The reverse geocoding provider could not be reached.",
        }), 502
    if error == "invalid_request":
        return jsonify({"error": "Valid latitude and longitude are required."}), 400
    if error is not None:
        return jsonify({
            "code": error,
            "error": "The reverse geocoding provider returned an error.",
        }), 502
    return jsonify({"formattedAddress": address}), 200


# ── POST /api/flags/yellow ────────────────────────────────────────────────────
@flags_bp.route("/yellow", methods=["POST"])
@jwt_required()  # inspectors and admins both allowed
def yellow_flag_route():
    """Manually insert a Yellow Flag. Open to Inspectors and Admins."""
    data = request.get_json()

    required = ["businessName", "lat", "lng", "barangayID"]
    if not isinstance(data, dict) or not all(k in data for k in required):
        return jsonify({"error": f"Required fields: {required}"}), 400

    client_submission_id = data.get("clientSubmissionID")
    if client_submission_id is not None:
        if not isinstance(client_submission_id, str):
            return jsonify({"error": "clientSubmissionID must be a UUID."}), 400
        try:
            if str(uuid.UUID(client_submission_id)) != client_submission_id.lower():
                raise ValueError("UUID must use canonical formatting.")
        except (ValueError, AttributeError):
            return jsonify({"error": "clientSubmissionID must be a UUID."}), 400
        # The unique key uses ascii_bin: equivalent UUID casing must not create rows.
        client_submission_id = client_submission_id.lower()

    flag_color = data.get("flagColor", "Yellow")
    if flag_color != "Yellow":
        return jsonify({"error": "Only Yellow flags can be manually created"}), 400

    reporter_user_id = int(get_jwt_identity())
    expected_reporter_id = data.get("expectedReporterUserID")
    if expected_reporter_id is not None:
        try:
            expected_reporter_id = int(expected_reporter_id)
        except (TypeError, ValueError):
            return jsonify({"error": "Invalid expected reporter identity."}), 400
        if expected_reporter_id != reporter_user_id:
            return jsonify({"error": "Report owner does not match the signed-in account."}), 403

    result, error = insert_yellow_flag(
        business_name=data["businessName"],
        lat=data["lat"],
        lng=data["lng"],
        barangay_id=data["barangayID"],
        notes=data.get("notes"),
        flag_color=flag_color,
        reported_by_user_id=reporter_user_id,
        client_submission_id=client_submission_id,
        business_address=data.get("businessAddress"),
    )
    if error:
        if isinstance(error, YellowFlagValidationError):
            return jsonify({
                "error": str(error),
                "code": "invalid_yellow_flag_location",
            }), 400
        if isinstance(error, YellowFlagSubmissionConflict):
            return jsonify({"error": str(error)}), 409
        return jsonify({"error": error}), 500
    return jsonify(result), 201


# ── PATCH /api/flags/:id/black ────────────────────────────────────────────────
@flags_bp.route("/<int(signed=True):log_id>/black", methods=["PATCH"])
@admin_required()
def black_flag_route(log_id):
    """Admin: escalate a Red, Yellow or Orange flag and record the real lock."""
    success, error = escalate_to_black(
        log_id, actor_user_id=get_jwt_identity())
    if not success:
        if isinstance(error, FlagEscalationForbidden):
            return jsonify({"error": str(error), "code": "black_escalation_forbidden"}), 403
        if isinstance(error, FlagEscalationNotFound):
            return jsonify({"error": str(error), "code": "flag_not_found"}), 404
        if isinstance(error, FlagEscalationConflict):
            return jsonify({"error": str(error), "code": "black_escalation_conflict"}), 409
        return jsonify({"error": str(error)}), 500
    return jsonify({"message": f"Flag #{log_id} escalated to Black"}), 200


@flags_bp.route("/<int:log_id>/clear-warning", methods=["POST"])
@admin_required()
def clear_pin_warning_route(log_id):
    """Admin: clear a warning on an unregistered geospatial pin."""
    data = request.get_json(silent=True) or {}
    result, error = registry_service.clear_pin_warning(
        log_id, get_jwt_identity(), data.get("reason"))
    if error:
        if isinstance(error, registry_service.RegistryNotFoundError):
            return jsonify({"error": str(error)}), 404
        if isinstance(error, (registry_service.RegistryLadderConflict,
                              registry_service.RegistryLadderUnavailable)):
            return jsonify({
                "error": str(error),
                "code": "warning_clear_refused",
            }), 409
        return jsonify({"error": str(error)}), 500
    return jsonify(result), 200


# ── PUT /api/flags/:id/location ───────────────────────────────────────────────
@flags_bp.route("/<int(signed=True):log_id>/location", methods=["PUT"])
@admin_required()
def change_flag_location_route(log_id):
    """Update a flag's coordinates manually (via admin drag & drop)."""
    data = request.get_json()
    if not data or "latitude" not in data or "longitude" not in data:
        return jsonify({"error": "Missing 'latitude' or 'longitude' parameter"}), 400

    try:
        lat = float(data["latitude"])
        lng = float(data["longitude"])
    except (ValueError, TypeError):
        return jsonify({"error": "Invalid coordinates"}), 400

    identity = get_jwt_identity()
    try:
        actor_user_id = int(identity) if identity is not None else None
    except (TypeError, ValueError):
        actor_user_id = None
    success, error = update_flag_location(
        log_id, lat, lng, actor_user_id=actor_user_id)
    if not success:
        return jsonify({"error": error}), 400
    return jsonify({"message": f"Flag #{log_id} location updated successfully"}), 200


# ── PATCH /api/flags/:id/color ────────────────────────────────────────────────
@flags_bp.route("/<int(signed=True):log_id>/color", methods=["PATCH"])
@admin_required()
def change_flag_color_route(log_id):
    """Update a flag's color manually (e.g. to Purple, Orange, Yellow, Red, Black, Green)."""
    data = request.get_json()
    if not data or "color" not in data:
        return jsonify({"error": "Missing 'color' parameter"}), 400

    color = data["color"]
    valid_colors = {"Red", "Yellow", "Black", "Green", "Orange", "Purple"}
    if color not in valid_colors:
        return jsonify({"error": f"Invalid color. Must be one of {valid_colors}"}), 400

    success, error = update_flag_color(log_id, color)
    if not success:
        # Typed error, not message text: a Black locked business is a conflict
        # with the enforcement ladder, not a bad request.
        if isinstance(error, BlackLockedError):
            return jsonify({
                "error": str(error),
                "code": "black_locked",
            }), 409
        return jsonify({"error": error}), 400
    return jsonify({"message": f"Flag #{log_id} color updated to {color}"}), 200


# ── DELETE /api/flags/:id ─────────────────────────────────────────────────────
@flags_bp.route("/<int(signed=True):log_id>", methods=["DELETE"])
@admin_required()
def delete_flag_route(log_id):
    """Delete a specific flag. Also deletes associated registry records if they exist."""
    success, error = delete_flag(log_id, actor_role=get_current_role())
    if error:
        if isinstance(error, BlackBusinessDeletionForbidden):
            return jsonify({"error": str(error), "code": "black_delete_forbidden"}), 403
        status_code = 404 if error == "Flag not found" else 500
        return jsonify({"error": str(error)}), status_code
    return jsonify({"message": f"Flag #{log_id} deleted successfully"}), 200
