from api.utils.cancellation import set_cancel
import os
import threading
from flask import Blueprint, request, jsonify, current_app
from app import mysql
from api.registry.service import (
    upload_registry,
    sync_registry,
    get_all_businesses,
    get_business_by_id,
    update_business,
    delete_business,
    snap_unresolved_pins,
)
from api.middleware.decorators import jwt_required, admin_required
from api.registry import places_resolver

registry_bp = Blueprint("registry", __name__)


# ── POST /api/registry/cancel ─────────────────────────────────────────────────

@registry_bp.route("/cancel", methods=["POST"])
@admin_required()
def cancel_import():
    """Cancel an ongoing registry import/sync task."""
    set_cancel("registry_import", True)
    return jsonify({"message": "Cancellation requested"}), 200

# ── POST /api/registry/reset-quota ────────────────────────────────────────────


@registry_bp.route("/reset-quota", methods=["POST"])
@admin_required()
def reset_quota():
    """Reset daily geocoding quota counters for today."""
    from api.registry.service import reset_geocode_daily_quota
    success = reset_geocode_daily_quota()
    if success:
        return jsonify({"message": "Daily geocoding quota has been reset for today."}), 200
    return jsonify({"error": "Failed to reset quota"}), 500


# ── POST /api/registry/snap-unresolved ───────────────────────────────────────
@registry_bp.route("/snap-unresolved", methods=["POST"])
@admin_required()
def snap_unresolved():
    """
    Cost-optimized batch pin snapping.
    Resolves eligible entries using Places Text Search first, then Geocoding
    fallbacks. Existing Geocoding pins are rechecked against Places once.
    Accepts optional JSON body: { "limit": 200 }  (default 200 per run).
    Runs asynchronously — progress is streamed via SSE (type: 'snap_progress').
    """
    if not os.getenv("GOOGLE_MAPS_API_KEY"):
        return jsonify({"error": "GOOGLE_MAPS_API_KEY is not configured on the server."}), 400

    body = request.get_json(silent=True) or {}
    # hard cap at 1000/run
    limit = max(1, min(int(body.get("limit", 200)), 1000))

    app_instance = current_app._get_current_object()

    def _run():
        with app_instance.app_context():
            try:
                snap_unresolved_pins(limit=limit)
            except Exception as e:
                import traceback
                print(f"[snap_unresolved] background thread error: {e}")
                traceback.print_exc()

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    return jsonify({"message": f"Snap started for up to {limit} businesses. Watch SSE for progress."}), 202


# ── GET /api/registry/reverify-preview ───────────────────────────────────────
@registry_bp.route("/reverify-preview", methods=["GET"])
@admin_required()
def reverify_preview():
    """Free dry run: which existing pins look wrong (no Google calls)."""
    from api.registry import reverify
    try:
        return jsonify(reverify.preview()), 200
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


# ── POST /api/registry/reverify  body: {"limit": 200} ────────────────────────
@registry_bp.route("/reverify", methods=["POST"])
@admin_required()
def reverify_run():
    """Re-check pins that already have coordinates against Google Places (background job)."""
    from api.registry import reverify
    if not os.getenv("GOOGLE_MAPS_API_KEY"):
        return jsonify({"error": "GOOGLE_MAPS_API_KEY is not configured on the server."}), 400
    if reverify.is_running():
        return jsonify({"error": "A re-verify run is already in progress."}), 409

    body = request.get_json(silent=True) or {}
    limit = max(1, min(int(body.get("limit", 200)), 500))
    app_instance = current_app._get_current_object()

    def _go():
        with app_instance.app_context():
            try:
                reverify.run(limit=limit)
            except Exception:
                import traceback
                traceback.print_exc()

    threading.Thread(target=_go, daemon=True).start()
    return jsonify({"message": f"Re-verify started for up to {limit} pins. Watch the progress window."}), 202


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
        if "quota reached" in error or "Remaining geocoding quota" in error:
            return jsonify({"error": error}), 429
        if "Maximum" in error and "imported per batch" in error:
            return jsonify({"error": error}), 400
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
        if "quota reached" in error or "Remaining geocoding quota" in error:
            return jsonify({"error": error}), 429
        if "Maximum" in error and "synced per batch" in error:
            return jsonify({"error": error}), 400
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
    registration_type = request.args.get("registrationType")
    search = request.args.get("search", "").strip()
    page = request.args.get("page",  1,    type=int)
    per_page = request.args.get("limit", 10,   type=int)

    result, error = get_all_businesses(
        barangay_id=barangay_id,
        status=status,
        registration_type=registration_type,
        search=search,
        page=page,
        per_page=per_page,
    )

    if error:
        return jsonify({"error": error}), 500

    return jsonify(result), 200


# ── GET /api/registry/barangays ───────────────────────────────────────────────
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


# ── GET /api/registry/review ──────────────────────────────────────────────────
@registry_bp.route("/review", methods=["GET"])
@admin_required()
def review_queue():
    """Businesses whose map pin was matched with low confidence and awaits admin review."""
    page = request.args.get("page", 1, type=int)
    per_page = min(request.args.get("limit", 20, type=int), 100)
    result, error = places_resolver.list_review_queue(
        page=page, per_page=per_page)
    if error:
        return jsonify({"error": error}), 500
    return jsonify(result), 200


# ── POST /api/registry/review/accept ──────────────────────────────────────────
@registry_bp.route("/review/accept", methods=["POST"])
@admin_required()
def review_accept():
    """Admin endpoint to approve low-confidence map pin candidate."""
    data = request.get_json(silent=True) or {}
    business_id = data.get("businessID") or data.get("business_id")
    if not business_id:
        return jsonify({"error": "businessID is required"}), 400
    ok, error = places_resolver.decide_review(business_id, approve=True)
    if not ok:
        return jsonify({"error": error}), 404 if error and error.startswith("Not found") else 500
    return jsonify({"message": "Pin approved", "businessID": business_id, "matchStatus": "approved"}), 200


# ── POST /api/registry/review/reject ──────────────────────────────────────────
@registry_bp.route("/review/reject", methods=["POST"])
@admin_required()
def review_reject():
    """Admin endpoint to reject candidate, insert into registry_rejected_places, and detach coords."""
    data = request.get_json(silent=True) or {}
    business_id = data.get("businessID") or data.get("business_id")
    if not business_id:
        return jsonify({"error": "businessID is required"}), 400
    ok, error = places_resolver.decide_review(business_id, approve=False)
    if not ok:
        return jsonify({"error": error}), 404 if error and error.startswith("Not found") else 500
    return jsonify({"message": "Pin rejected and candidate place discarded", "businessID": business_id, "matchStatus": "rejected"}), 200


# ── POST /api/registry/<id>/review  body: {"action": "approve" | "reject"} ────
@registry_bp.route("/<path:business_id>/review", methods=["POST"])
@admin_required()
def review_decide(business_id):
    data = request.get_json(silent=True) or {}
    action = data.get("action")
    if action not in ("approve", "reject"):
        return jsonify({"error": "action must be 'approve' or 'reject'"}), 400
    ok, error = places_resolver.decide_review(
        business_id, approve=(action == "approve"))
    if not ok:
        return jsonify({"error": error}), 404 if error and error.startswith("Not found") else 500
    return jsonify({"message": f"Pin {action}d"}), 200


# ── GET /api/registry/<id> ────────────────────────────────────────────────────
@registry_bp.route("/<path:business_id>", methods=["GET"])
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
@registry_bp.route("/<path:business_id>", methods=["PUT"])
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
@registry_bp.route("/<path:business_id>", methods=["DELETE"])
@admin_required()
def delete_business_route(business_id):
    """Delete a single business record by ID."""
    success, error = delete_business(business_id)

    if error:
        status_code = 404 if error == "Business not found" else 500
        return jsonify({"error": error}), status_code

    return jsonify({"message": "Business deleted successfully"}), 200
