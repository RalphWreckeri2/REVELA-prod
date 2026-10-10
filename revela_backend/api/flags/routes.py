from api.utils.cancellation import set_cancel
from api.models.detection_runs import get_detection_quota_info
from api.utils.quota_config import API_QUOTA_CONFIG
import os
from flask import Blueprint, request, jsonify
from flask_jwt_extended import get_jwt_identity
from api.flags.service import (
    run_detection,
    get_flags,
    insert_yellow_flag,
    update_flag_color,
    escalate_to_black,
    delete_flag,
    reconcile_existing_flags,
    update_flag_location,
    get_places_usage_today,
)
from api.middleware.decorators import jwt_required, admin_required
from app import mysql
flags_bp = Blueprint("flags", __name__)


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
        cursor.execute("SELECT COALESCE(MAX(eventID), 0) AS last_event_id FROM registry_workflow_events")
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


# ── POST /api/flags/yellow ────────────────────────────────────────────────────
@flags_bp.route("/yellow", methods=["POST"])
@jwt_required()  # inspectors and admins both allowed
def yellow_flag_route():
    """Manually insert a Yellow Flag. Open to Inspectors and Admins."""
    data = request.get_json()

    required = ["businessName", "lat", "lng", "barangayID"]
    if not data or not all(k in data for k in required):
        return jsonify({"error": f"Required fields: {required}"}), 400

    flag_color = data.get("flagColor", "Yellow")
    if flag_color != "Yellow":
        return jsonify({"error": "Only Yellow flags can be manually created"}), 400

    reporter_user_id = int(get_jwt_identity())

    result, error = insert_yellow_flag(
        business_name=data["businessName"],
        lat=data["lat"],
        lng=data["lng"],
        barangay_id=data["barangayID"],
        notes=data.get("notes"),
        flag_color=flag_color,
        reported_by_user_id=reporter_user_id,
    )
    if error:
        return jsonify({"error": error}), 500
    return jsonify(result), 201


# ── PATCH /api/flags/:id/black ────────────────────────────────────────────────
@flags_bp.route("/<int(signed=True):log_id>/black", methods=["PATCH"])
@admin_required()
def black_flag_route(log_id):
    """Escalate a Red or Yellow flag to Black."""
    success, error = escalate_to_black(log_id)
    if not success:
        return jsonify({"error": error}), 400
    return jsonify({"message": f"Flag #{log_id} escalated to Black"}), 200


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

    success, error = update_flag_location(log_id, lat, lng)
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
        return jsonify({"error": error}), 400
    return jsonify({"message": f"Flag #{log_id} color updated to {color}"}), 200


# ── DELETE /api/flags/:id ─────────────────────────────────────────────────────
@flags_bp.route("/<int(signed=True):log_id>", methods=["DELETE"])
@admin_required()
def delete_flag_route(log_id):
    """Delete a specific flag. Also deletes associated registry records if they exist."""
    success, error = delete_flag(log_id)
    if error:
        status_code = 404 if error == "Flag not found" else 500
        return jsonify({"error": error}), status_code
    return jsonify({"message": f"Flag #{log_id} deleted successfully"}), 200
