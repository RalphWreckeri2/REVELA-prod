import os
import uuid
import threading

from flask import Blueprint, request, jsonify, send_from_directory, current_app
from flask_jwt_extended import get_jwt_identity
from werkzeug.utils import secure_filename

from api.inspections.service import (
    get_inspector_tasks,
    get_inspector_reports_history,
    assign_inspection,
    submit_inspection,
    reassign_submitted_report,
    verify_inspection,
    get_all_inspections,
)
from api.middleware.decorators import jwt_required, admin_required
from api.notifications.service import (
    notify_inspection_assigned,
    notify_inspection_submitted,
)

inspections_bp = Blueprint("inspections", __name__)

_EVIDENCE_DIR = os.path.abspath(
    os.path.join(
        os.path.dirname(
            __file__), "..", "..", "instance", "inspection_evidence"
    )
)


def _ensure_evidence_dir():
    os.makedirs(_EVIDENCE_DIR, exist_ok=True)
    return _EVIDENCE_DIR


# ── GET /api/inspections/tasks ────────────────────────────────────────────────
@inspections_bp.route("/tasks", methods=["GET"])
@jwt_required()
def get_tasks():
    """Return flags assigned to the current inspector (Assigned or Reassigned)."""
    user_id = get_jwt_identity()
    result, error = get_inspector_tasks(user_id=user_id)
    if error:
        return jsonify({"error": error}), 500
    return jsonify(result), 200


# ── GET /api/inspections/my-reports ───────────────────────────────────────────
@inspections_bp.route("/my-reports", methods=["GET"])
@jwt_required()
def my_reports():
    """Inspector: full history of their reports (all statuses)."""
    user_id = get_jwt_identity()
    result, error = get_inspector_reports_history(user_id=user_id)
    if error:
        return jsonify({"error": error}), 500
    return jsonify(result), 200


# ── POST /api/inspections/evidence ────────────────────────────────────────────
@inspections_bp.route("/evidence", methods=["POST"])
@jwt_required()
def upload_evidence():
    """Inspector: upload a photo; returns a relative photoURL for submit."""
    if "file" not in request.files:
        return jsonify({"error": "Missing file field"}), 400
    file = request.files["file"]
    if not file or file.filename == "":
        return jsonify({"error": "Empty file"}), 400

    orig = secure_filename(file.filename) or "evidence.jpg"
    ext = os.path.splitext(orig)[1].lower()
    if ext not in (".jpg", ".jpeg", ".png", ".webp"):
        ext = ".jpg"
    name = f"{uuid.uuid4().hex}{ext}"

    folder = _ensure_evidence_dir()
    path = os.path.join(folder, name)
    file.save(path)

    rel = f"/api/inspections/public-evidence/{name}"
    return jsonify({"photoURL": rel}), 201


# ── GET /api/inspections/public-evidence/<name> ───────────────────────────────
@inspections_bp.route("/public-evidence/<filename>", methods=["GET"])
def download_public_evidence(filename):
    """Serve inspection images (unguessable filenames). No auth for <img> tags."""
    if not filename or ".." in filename or "/" in filename or "\\" in filename:
        return jsonify({"error": "Invalid filename"}), 400
    folder = _ensure_evidence_dir()
    path = os.path.join(folder, filename)
    if not os.path.isfile(path):
        return jsonify({"error": "Not found"}), 404
    return send_from_directory(folder, filename)


# ── POST /api/inspections/assign ──────────────────────────────────────────────
@inspections_bp.route("/assign", methods=["POST"])
@admin_required()
def assign():
    """Admin: assign a geospatial flag to an inspector."""
    assigned_by = get_jwt_identity()
    data = request.get_json()

    required = ["logID", "userID"]
    if not data or not all(k in data for k in required):
        return jsonify({"error": f"Required fields: {required}"}), 400

    deadline = data.get("deadline")
    if not deadline:
        deadline = None

    result, error = assign_inspection(
        log_id=data["logID"],
        inspector_user_id=data["userID"],
        deadline=deadline,
        assigned_by=assigned_by,
    )
    if error:
        return jsonify({"error": error}), 500
    try:
        notify_inspection_assigned(
            report_id=result["reportID"],
            log_id=result["logID"],
            inspector_user_id=result["inspectorID"],
            status=result.get("status", "Assigned"),
        )
    except (TypeError, ValueError, KeyError) as exc:
        print(f"notify_inspection_assigned skipped: {exc}")
    return jsonify(result), 201


# ── POST /api/inspections/submit ──────────────────────────────────────────────
@inspections_bp.route("/submit", methods=["POST"])
@jwt_required()
def submit():
    """Inspector submits a completed inspection report."""
    user_id = get_jwt_identity()
    data = request.get_json()

    required = ["logID", "inspectionResult"]
    if not data or not all(k in data for k in required):
        return jsonify({"error": f"Required fields: {required}"}), 400

    valid_results = ("Red", "Yellow", "Green", "Orange", "Black", "Purple")
    if data["inspectionResult"] not in valid_results:
        return jsonify({"error": f"inspectionResult must be one of {valid_results}"}), 400

    notice_level = data.get("noticeLevel", 0)

    result, error = submit_inspection(
        log_id=data["logID"],
        user_id=user_id,
        inspection_result=data["inspectionResult"],
        notice_level=notice_level,
        verified_lat=data.get("verifiedLat"),
        verified_lng=data.get("verifiedLng"),
        notes=data.get("notes"),
        photo_url=data.get("photoURL"),
    )
    if error:
        return jsonify({"error": error}), 500

    has_photo = bool(data.get("photoURL"))

    # Fire notification in background so the inspector gets an immediate response
    app_instance = current_app._get_current_object()
    notif_args = {
        "report_id": result["reportID"],
        "log_id": data["logID"],
        "inspector_user_id": int(user_id),
        "inspection_result": data["inspectionResult"],
        "has_evidence_photo": has_photo,
    }

    def _bg_notify(app, kwargs):
        with app.app_context():
            try:
                notify_inspection_submitted(**kwargs)
            except Exception as exc:
                print(f"notify_inspection_submitted bg error: {exc}")

    threading.Thread(
        target=_bg_notify,
        args=(app_instance, notif_args),
        daemon=True,
    ).start()

    return jsonify(result), 200


# ── POST /api/inspections/<id>/reassign ───────────────────────────────────────
@inspections_bp.route("/<int:report_id>/reassign", methods=["POST", "OPTIONS"])
@admin_required()
def reassign_submitted(report_id):
    if request.method == "OPTIONS":
        return "", 204
    """Admin: send a submitted report back to an inspector for redo."""
    data = request.get_json()
    if not data or "userID" not in data:
        return jsonify({"error": "userID is required"}), 400

    deadline = data.get("deadline")
    if not deadline:
        deadline = None

    result, error = reassign_submitted_report(
        report_id=report_id,
        inspector_user_id=data["userID"],
        deadline=deadline,
        assigned_by=get_jwt_identity(),
    )
    if error:
        status = 400 if "only Submitted" in error or "not found" in error else 500
        return jsonify({"error": error}), status
    try:
        notify_inspection_assigned(
            report_id=result["reportID"],
            log_id=result["logID"],
            inspector_user_id=result["inspectorID"],
            status="Reassigned",
        )
    except (TypeError, ValueError, KeyError) as exc:
        print(f"notify_inspection_assigned skipped: {exc}")
    return jsonify(result), 200


# ── POST /api/inspections/<id>/verify ─────────────────────────────────────────
@inspections_bp.route("/<int:report_id>/verify", methods=["POST", "OPTIONS"])
@admin_required()
def verify(report_id):
    if request.method == "OPTIONS":
        return "", 204
    """Admin confirms inspection result → updates geospatial_logs flagColor."""
    result, error = verify_inspection(report_id=report_id)
    if error:
        return jsonify({"error": error}), 400
    return jsonify(result), 200


# ── GET /api/inspections ──────────────────────────────────────────────────────
@inspections_bp.route("", methods=["GET"])
@inspections_bp.route("/", methods=["GET"])
@admin_required()
def get_inspections():
    """Admin: all inspection reports, filterable by status and barangayID."""
    status = request.args.get("status")
    barangay_id = request.args.get("barangayID", type=int)
    page = request.args.get("page",  1,  type=int)
    per_page = request.args.get("limit", 20, type=int)

    result, error = get_all_inspections(
        status=status,
        barangay_id=barangay_id,
        page=page,
        per_page=per_page,
    )
    if error:
        return jsonify({"error": error}), 500
    return jsonify(result), 200
