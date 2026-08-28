from functools import wraps
from flask import jsonify, request
from flask_jwt_extended import verify_jwt_in_request, get_jwt


def jwt_required():
    """
    Decorator for ANY protected route.
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

            role = get_current_role()
            if role not in ("Admin", "SUPER_ADMIN", "System Administrator"):
                return jsonify({"error": "Forbidden", "message": "Admins only"}), 403

            return fn(*args, **kwargs)
        return wrapper
    return decorator
