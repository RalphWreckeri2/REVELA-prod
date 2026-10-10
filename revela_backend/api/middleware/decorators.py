from functools import wraps
from flask import current_app, jsonify, request
from flask_jwt_extended import verify_jwt_in_request, get_jwt, get_jwt_identity
from api.models.user import find_user_by_id
from api.auth.sessions import check_active_session, IDLE_SESSION_MESSAGE


def _verify_user_and_session(identity, claims, require_admin=False):
    if identity is None:
        return None
    try:
        user = find_user_by_id(int(identity))
        if not user or not user.get("isActive", user.get("is_active", True)):
            return jsonify({
                "error": "Unauthorized",
                "message": "Account has been deactivated or removed.",
            }), 401
        if claims.get("2fa_pending"):
            if request.endpoint != "auth.verify_2fa_login":
                return jsonify({
                    "error": "Unauthorized",
                    "message": "Complete two-factor authentication first.",
                }), 401
            return None
        session_active, session_code = check_active_session(
            identity, claims.get("session_id")
        )
        if not session_active:
            if session_code == "session_idle":
                return jsonify({
                    "code": "session_idle",
                    "error": "Unauthorized",
                    "message": IDLE_SESSION_MESSAGE,
                }), 401
            return jsonify({
                "error": "Unauthorized",
                "message": (
                    "This session ended because the account signed in on another "
                    "device or logged out."
                ),
            }), 401
        if require_admin:
            current_role = user.get("userRole") or user.get("role")
            if current_role and current_role != claims.get("role"):
                return jsonify({
                    "error": "Unauthorized",
                    "message": "Account permissions changed. Sign in again.",
                }), 401
    except Exception:
        current_app.logger.exception("Could not verify authenticated session.")
        return jsonify({"error": "Authorization could not be verified."}), 503
    return None


def jwt_required():
    """
    Decorator for ANY protected route.
    Validates JWT signature AND verifies the user is still active in MySQL DB.
    Usage: @jwt_required()
    """
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            if request.method == "OPTIONS":
                return "", 204

            try:
                verify_jwt_in_request()  # validates the Bearer token
            except Exception as e:
                return jsonify({"error": "Unauthorized", "message": str(e)}), 401

            identity = get_jwt_identity()
            error = _verify_user_and_session(identity, get_jwt())
            if error:
                return error

            return fn(*args, **kwargs)
        return wrapper
    return decorator


def get_current_role():
    """Helper — call inside any protected route to get the role string."""
    claims = get_jwt()
    return claims.get("role")


def admin_required():
    """
    Decorator for ADMIN-only routes.
    Returns 403 if role != 'Admin' and role != 'SUPER_ADMIN'.
    Usage: @admin_required()
    """
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            if request.method == "OPTIONS":
                return "", 204

            try:
                verify_jwt_in_request()
            except Exception as e:
                return jsonify({"error": "Unauthorized", "message": str(e)}), 401

            identity = get_jwt_identity()
            role = get_current_role()
            error = _verify_user_and_session(
                identity, get_jwt(), require_admin=True
            )
            if error:
                return error

            if role not in ("Admin", "SUPER_ADMIN", "System Administrator"):
                return jsonify({"error": "Forbidden", "message": "Admins only"}), 403

            return fn(*args, **kwargs)
        return wrapper
    return decorator
