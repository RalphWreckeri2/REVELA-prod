from flask import Blueprint, request, jsonify
from app import mysql
from api.registry.service import (
    upload_registry,
    sync_registry,
    get_all_businesses,
    get_business_by_id,
    update_business,
    delete_business,
)
from api.middleware.decorators import jwt_required, admin_required

registry_bp = Blueprint("registry", __name__)

from api.utils.cancellation import set_cancel

# ── POST /api/registry/cancel ─────────────────────────────────────────────────
@registry_bp.route("/cancel", methods=["POST"])
@admin_required()
def cancel_import():
    """Cancel an ongoing registry import/sync task."""
    set_cancel("registry_import", True)
    return jsonify({"message": "Cancellation requested"}), 200

# ── POST /api/registry/upload ─────────────────────────────────────────────────
@registry_bp.route("/upload", methods=["POST"])
@admin_required()
def upload():
    """Accept a CSV or Excel file and seed OFFICIAL_REGISTRY."""
    if "file" not in request.files:
        return jsonify({"error": "No file provided"}), 400

    file = request.files["file"]

    if file.filename == "":
        return jsonify({"error": "No file selected"}), 400

    allowed = {".csv", ".xlsx", ".xls"}
    ext = "." + \
        file.filename.rsplit(
            ".", 1)[-1].lower() if "." in file.filename else ""

    if ext not in allowed:
        return jsonify({"error": "Only CSV and Excel files are accepted (.csv, .xlsx, .xls)"}), 400

    summary, error = upload_registry(file, ext)

    if error:
        if "cancelled by user" in error:
            return jsonify({"message": error}), 200
        return jsonify({"error": error}), 500

    return jsonify(summary), 201


# ── POST /api/registry/sync ───────────────────────────────────────────────────
@registry_bp.route("/sync", methods=["POST"])
@jwt_required()
def sync():
    """Merge a CSV/Excel file into OFFICIAL_REGISTRY (update matches, insert new)."""
    if "file" not in request.files:
        return jsonify({"error": "No file provided"}), 400

    file = request.files["file"]

    if file.filename == "":
        return jsonify({"error": "No file selected"}), 400

    allowed = {".csv", ".xlsx", ".xls"}
    ext = "." + \
        file.filename.rsplit(
            ".", 1)[-1].lower() if "." in file.filename else ""

    if ext not in allowed:
        return jsonify({"error": "Only CSV and Excel files are accepted (.csv, .xlsx, .xls)"}), 400

    summary, error = sync_registry(file, ext)

    if error:
        if "cancelled by user" in error:
            return jsonify({"message": error}), 200
        return jsonify({"error": error}), 500

    return jsonify(summary), 200


# ── GET /api/registry ─────────────────────────────────────────────────────────
@registry_bp.route("/", methods=["GET"])
@jwt_required()
def get_registry():
    """Return all businesses with optional filters."""
    barangay_id = request.args.get("barangayID",  type=int)
    # Active | Expired | Revoked | Pending
    status = request.args.get("status")
    search = request.args.get("search", "").strip()
    page = request.args.get("page",  1,    type=int)
    per_page = request.args.get("limit", 10,   type=int)

    result, error = get_all_businesses(
        barangay_id=barangay_id,
        status=status,
        search=search,
        page=page,
        per_page=per_page,
    )

    if error:
        return jsonify({"error": error}), 500

    return jsonify(result), 200


# ── GET /api/registry/<id> ────────────────────────────────────────────────────
@registry_bp.route("/<int:business_id>", methods=["GET"])
@jwt_required()
def get_business(business_id):
    """Return a single business record by ID."""
    business, error = get_business_by_id(business_id)

    if error:
        return jsonify({"error": error}), 500
    if not business:
        return jsonify({"error": "Business not found"}), 404

    return jsonify(business), 200


# ── PUT /api/registry/<id> ────────────────────────────────────────────────────
@registry_bp.route("/<int:business_id>", methods=["PUT"])
@admin_required()
def edit_business(business_id):
    """Update a single business record by ID."""
    data = request.get_json()
    if not data:
        return jsonify({"error": "No data provided"}), 400

    success, error = update_business(business_id, data)

    if error:
        status_code = 404 if error == "Business not found" else 500
        return jsonify({"error": error}), status_code

    return jsonify({"message": "Business updated successfully"}), 200


# ── DELETE /api/registry/<id> ─────────────────────────────────────────────────
@registry_bp.route("/<int:business_id>", methods=["DELETE"])
@admin_required()
def delete_business_route(business_id):
    """Delete a single business record by ID."""
    success, error = delete_business(business_id)

    if error:
        status_code = 404 if error == "Business not found" else 500
        return jsonify({"error": error}), status_code

    return jsonify({"message": "Business deleted successfully"}), 200


@registry_bp.route("/barangays", methods=["GET"])
@jwt_required()
def get_barangays():
    cursor = mysql.connection.cursor()
    cursor.execute(
        "SELECT barangayID, barangayName FROM barangays ORDER BY barangayName")
    rows = cursor.fetchall()
    cursor.close()
    # Convert cursor results to list of dicts
    data = [dict(row) for row in rows] if rows else []
    return jsonify({"data": data}), 200
