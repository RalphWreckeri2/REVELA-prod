import json
import queue

from flask import Blueprint, Response, request, jsonify
from flask_jwt_extended import decode_token, get_jwt_identity
from flask_jwt_extended.exceptions import JWTDecodeError

from api.middleware.decorators import jwt_required, get_current_role
from api.notifications import service as notif_service
from api.notifications import hub

notifications_bp = Blueprint("notifications", __name__)


def _admin_roles():
    return ("Admin", "SUPER_ADMIN", "System Administrator")


# ── GET /api/notifications ──────────────────────────────────────────────────────
@notifications_bp.route("", methods=["GET"])
@notifications_bp.route("/", methods=["GET"])
@jwt_required()
def list_notifications_route():
    uid = int(get_jwt_identity())
    result, err = notif_service.list_notifications(uid)
    if err:
        return jsonify({"error": err}), 500
    return jsonify(result), 200


# ── GET /api/notifications/unread-count ───────────────────────────────────────
@notifications_bp.route("/unread-count", methods=["GET"])
@jwt_required()
def unread_count_route():
    uid = int(get_jwt_identity())
    result, err = notif_service.unread_count(uid)
    if err:
        return jsonify({"error": err}), 500
    return jsonify(result), 200


# ── PATCH /api/notifications/read ─────────────────────────────────────────────
@notifications_bp.route("/read", methods=["PATCH", "OPTIONS"])
@jwt_required()
def mark_read_route():
    if request.method == "OPTIONS":
        return "", 204
    uid = int(get_jwt_identity())
    data = request.get_json(silent=True) or {}
    ids = data.get("ids")
    if ids is not None and not isinstance(ids, list):
        return jsonify({"error": "ids must be an array"}), 400
    result, err = notif_service.mark_notifications_read(uid, ids)
    if err:
        return jsonify({"error": err}), 500
    return jsonify(result), 200


# ── DELETE /api/notifications ─────────────────────────────────────────────────
@notifications_bp.route("", methods=["DELETE", "OPTIONS"])
@notifications_bp.route("/", methods=["DELETE", "OPTIONS"])
@jwt_required()
def delete_notifications_route():
    if request.method == "OPTIONS":
        return "", 204
    uid = int(get_jwt_identity())
    data = request.get_json(silent=True) or {}
    ids = data.get("ids")
    if ids is not None and not isinstance(ids, list):
        return jsonify({"error": "ids must be an array"}), 400
    result, err = notif_service.delete_notifications(uid, ids)
    if err:
        return jsonify({"error": err}), 500
    return jsonify(result), 200


# ── GET /api/notifications/stream?token=JWT ───────────────────────────────────
# EventSource cannot set Authorization header in all browsers.
@notifications_bp.route("/stream", methods=["GET"])
def stream_notifications():
    token = request.args.get("token")
    if not token:
        return jsonify({"error": "token query parameter required"}), 401
    try:
        decoded = decode_token(token)
    except JWTDecodeError as e:
        return jsonify({"error": "invalid token", "details": str(e)}), 401

    role = decoded.get("role") or decoded.get("userRole")
    if role not in _admin_roles():
        return jsonify({"error": "Admins only"}), 403

    user_id = str(decoded.get("sub"))

    def event_stream():
        q = hub.subscribe(user_id)
        try:
            # Initial ping + unread baseline for client
            yield f"data: {json.dumps({'type': 'connected'})}\n\n"
            while True:
                try:
                    msg = q.get(timeout=25)
                    yield f"data: {json.dumps(msg)}\n\n"
                except queue.Empty:
                    yield f"data: {json.dumps({'type': 'heartbeat'})}\n\n"
        finally:
            hub.unsubscribe(user_id, q)

    headers = {
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",
    }
    return Response(
        event_stream(),
        mimetype="text/event-stream",
        headers=headers,
    )
