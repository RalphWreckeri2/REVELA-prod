from functools import wraps
from flask import jsonify, request
from flask_jwt_extended import verify_jwt_in_request, get_jwt, get_jwt_identity
from api.models.user import find_user_by_id


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
            if identity is not None:
                try:
                    user = find_user_by_id(int(identity))
                    if not user:
                        return jsonify({
                            "error": "Unauthorized",
                            "message": "Account has been removed by an administrator."
                        }), 401

                    if not user.get("isActive", user.get("is_active", True)):
                        return jsonify({
                            "error": "Unauthorized",
                            "message": "Account has been deactivated by an administrator."
                        }), 401
                except Exception as e:
                    # In case of DB error during check, pass through to route handler
                    pass

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
            if identity is not None:
                try:
                    user = find_user_by_id(int(identity))
                    if not user or not user.get("isActive", user.get("is_active", True)):
                        return jsonify({
                            "error": "Unauthorized",
                            "message": "Account has been deactivated or removed."
                        }), 401
                except Exception as e:
                    pass

            role = get_current_role()
            if role not in ("Admin", "SUPER_ADMIN", "System Administrator"):
                return jsonify({"error": "Forbidden", "message": "Admins only"}), 403

            return fn(*args, **kwargs)
        return wrapper
    return decorator
