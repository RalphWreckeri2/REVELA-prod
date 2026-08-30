from flask import Blueprint, request, jsonify
from flask_jwt_extended import get_jwt_identity
from api.flags.service import (
    run_detection,
    get_flags,
    insert_yellow_flag,
    update_flag_color,
    escalate_to_black,
    delete_flag,
)
from api.middleware.decorators import jwt_required, admin_required

flags_bp = Blueprint("flags", __name__)

from api.utils.cancellation import set_cancel 
from api.models.detection_runs import get_detection_quota_info

# ── GET /api/flags/detection-quota ────────────────────────────────────────────
@flags_bp.route("/detection-quota", methods=["GET"])
@jwt_required()
def get_detection_quota_route():
    """Get detection scan quota and status for the current month."""
    quota = get_detection_quota_info()
    return jsonify(quota), 200

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
    """Trigger full Places API fetch + cross-reference + Red Flag insertion."""
    user_id = None
    try:
        user_id = int(get_jwt_identity())
    except Exception:
        pass

    result, error = run_detection(user_id=user_id)
    if error:
        if error == "Detection cancelled by user.":
            return jsonify({"message": error}), 200
        if "Monthly detection limit reached" in error:
            return jsonify({"error": error}), 429
        return jsonify({"error": error}), 500
    return jsonify(result), 200


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
    """Manually insert a Yellow or Orange Flag. Open to Inspectors and Admins."""
    data = request.get_json()

    required = ["businessName", "lat", "lng", "barangayID"]
    if not data or not all(k in data for k in required):
        return jsonify({"error": f"Required fields: {required}"}), 400

    flag_color = data.get("flagColor", "Yellow")
    if flag_color not in ("Yellow", "Orange"):
        return jsonify({"error": "Invalid flag color for manual creation"}), 400

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
@flags_bp.route("/<int:log_id>/black", methods=["PATCH"])
@admin_required()
def black_flag_route(log_id):
    """Escalate a Red or Yellow flag to Black."""
    success, error = escalate_to_black(log_id)
    if not success:
        return jsonify({"error": error}), 400
    return jsonify({"message": f"Flag #{log_id} escalated to Black"}), 200


# ── PATCH /api/flags/:id/color ────────────────────────────────────────────────
@flags_bp.route("/<int:log_id>/color", methods=["PATCH"])
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
@flags_bp.route("/<int:log_id>", methods=["DELETE"])
@admin_required()
def delete_flag_route(log_id):
    """Delete a specific flag. Also deletes associated registry records if they exist."""
    success, error = delete_flag(log_id)
    if error:
        status_code = 404 if error == "Flag not found" else 500
        return jsonify({"error": error}), status_code
    return jsonify({"message": f"Flag #{log_id} deleted successfully"}), 200
