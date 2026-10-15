from flask import Blueprint, current_app, request, jsonify
from flask_jwt_extended import get_jwt_identity
from api.middleware.decorators import admin_required
from api.models.user import (get_all_users, get_users_by_role, find_user_by_email,
                             find_user_by_id, create_user, update_user,
                             delete_user, update_password, set_reset_requested)
import bcrypt
import re
import secrets

users_bp = Blueprint("users", __name__)

# The complete set of roles this application understands. Anything else is
# rejected with 400 rather than written verbatim into users.userRole.
VALID_ROLES = ("Inspector", "Admin", "SUPER_ADMIN", "System Administrator")
SUPER_ADMIN_ROLE = "SUPER_ADMIN"


def _validate_role(role):
    """Return (ok, normalised_role_or_error)."""
    if not isinstance(role, str):
        return False, f"role must be one of {list(VALID_ROLES)}"
    # Tolerate casing/whitespace differences from clients, but nothing else.
    match = next((r for r in VALID_ROLES if r.casefold() == role.strip().casefold()),
                 None)
    if match is None:
        return False, f"role must be one of {list(VALID_ROLES)}"
    return True, match


def _caller_is_super_admin():
    """True when the authenticated caller holds the exact SUPER_ADMIN role.

    Note System Administrator is NOT accepted: super_admin_required() matches
    the exact string, and this guard must agree with it.
    """
    try:
        actor = find_user_by_id(int(get_jwt_identity()))
    except (TypeError, ValueError):
        return False
    return bool(actor) and actor.get("userRole") == SUPER_ADMIN_ROLE


def _no_super_admin_exists():
    """Bootstrap escape hatch.

    There is no seed script for the first SUPER_ADMIN in this repository, so
    a deployment whose SUPER_ADMIN rows were removed would otherwise have no
    way to mint a replacement. Allow creating the very first one.
    """
    try:
        return len(get_users_by_role(SUPER_ADMIN_ROLE)) == 0
    except Exception:
        # If the check itself fails, do not open the door.
        return False


def _guard_super_admin_write(actor_is_super_admin):
    """Authorise a write that would create or assign SUPER_ADMIN.

    Returns an error tuple to return from the view, or None if allowed.
    """
    if _no_super_admin_exists():
        return None
    if actor_is_super_admin:
        return None
    return (
        {"error": "Only a SUPER_ADMIN can create or promote a SUPER_ADMIN."},
        403,
    )


def _normalize_phone(phone):
    """
    Accepts: 09XXXXXXXXX, +639XXXXXXXXX, 639XXXXXXXXX
    Always stores as: 09XXXXXXXXX
    Returns None if invalid.
    """
    if not phone:
        return None

    # Strip spaces, dashes, parentheses
    cleaned = re.sub(r"[\s\-\(\)]", "", phone)

    # +639XXXXXXXXX → 09XXXXXXXXX
    if cleaned.startswith("+63"):
        cleaned = "0" + cleaned[3:]

    # 639XXXXXXXXX → 09XXXXXXXXX
    elif cleaned.startswith("63") and len(cleaned) == 12:
        cleaned = "0" + cleaned[2:]

    # Validate final format: 09XXXXXXXXX (11 digits)
    if re.match(r"^09\d{9}$", cleaned):
        return cleaned

    return None  # invalid

# ── GET /api/users/ ───────────────────────────────────────────────────────────


@users_bp.route("/", methods=["GET"])
@admin_required()
def list_users():
    """Return all users or filter by role. SUPER_ADMIN only."""
    role = request.args.get("role")
    if role:
        users = get_users_by_role(role)
    else:
        users = get_all_users()
    return jsonify(users), 200


# ── GET /api/users/generate-password ──────────────────────────────────────────
@users_bp.route("/generate-password", methods=["GET"])
@admin_required()
def generate_password_route():
    """Generates a new random password for the user creation form."""
    temp_password = secrets.token_urlsafe(10)
    return jsonify({"tempPassword": temp_password}), 200


# ── POST /api/users/ ──────────────────────────────────────────────────────────
@users_bp.route("/", methods=["POST"])
@admin_required()
def create_user_route():
    data = request.get_json()

    required = ["fullName", "email", "role"]
    if not data or not all(k in data for k in required):
        return jsonify({"error": f"Required fields: {required}"}), 400

    if find_user_by_email(data["email"]):
        return jsonify({"error": "Email already in use"}), 409

    role_ok, role_or_error = _validate_role(data["role"])
    if not role_ok:
        return jsonify({"error": role_or_error}), 400

    if role_or_error == SUPER_ADMIN_ROLE:
        blocked = _guard_super_admin_write(_caller_is_super_admin())
        if blocked:
            return jsonify(blocked[0]), blocked[1]

    # Phone validation — must happen before create_user call
    raw_phone = data.get("phone", "").strip()
    phone = _normalize_phone(raw_phone) if raw_phone else None
    if raw_phone and phone is None:
        return jsonify({"error": "Invalid phone number. Use format: 09XXXXXXXXX"}), 400

    # Generate a secure, temporary password
    temp_password = data.get("password", secrets.token_urlsafe(10))
    hashed = bcrypt.hashpw(
        temp_password.encode("utf-8"),
        bcrypt.gensalt()
    ).decode("utf-8")

    user_id = create_user(
        full_name=data["fullName"],
        email=data["email"],
        hashed_password=hashed,
        role=role_or_error,
        phone=phone,
        must_change_password=True,  # Force change on first login
    )

    try:
        from api.notifications import hub
        hub.publish_to_admins({"type": "user_updated", "userID": user_id})
    except Exception:
        pass

    return jsonify({
        "message":      "User created successfully",
        "userID":       user_id,
        "tempPassword": temp_password,
    }), 201


# ── PATCH /api/users/:id ──────────────────────────────────────────────────────
@users_bp.route("/<int:user_id>", methods=["PATCH"])
@admin_required()
def update_user_route(user_id):
    data = request.get_json()

    if not data:
        return jsonify({"error": "No data provided"}), 400

    user = find_user_by_id(user_id)
    if not user:
        return jsonify({"error": "User not found"}), 404

    # If email is being changed, ensure it's not already taken
    if "email" in data and data["email"].lower() != user["email"].lower():
        if find_user_by_email(data["email"]):
            return jsonify({"error": "Email already in use by another account"}), 409

    if user["userRole"] == "SUPER_ADMIN":
        data.pop("role", None)
    elif "role" in data:
        # An existing SUPER_ADMIN cannot be re-roled, so this branch only
        # covers promotions or a change to some other role.
        role_ok, role_or_error = _validate_role(data["role"])
        if not role_ok:
            return jsonify({"error": role_or_error}), 400
        if role_or_error == SUPER_ADMIN_ROLE:
            blocked = _guard_super_admin_write(_caller_is_super_admin())
            if blocked:
                return jsonify(blocked[0]), blocked[1]
        data["role"] = role_or_error

    # Phone validation — must happen before update_user call
    raw_phone = data.get("phone", "").strip()
    if raw_phone:
        phone = _normalize_phone(raw_phone)
        if phone is None:
            return jsonify({"error": "Invalid phone number. Use format: 09XXXXXXXXX"}), 400
    else:
        phone = user.get("phone")

    update_user(
        user_id=user_id,
        full_name=data.get("fullName", user["fullName"]),
        email=data.get("email",    user["email"]),
        role=data.get("role",     user["userRole"]),
        phone=phone,
    )

    try:
        from api.notifications import hub
        hub.publish_to_admins({"type": "user_updated", "userID": user_id})
    except Exception:
        pass

    return jsonify({"message": "User updated successfully"}), 200


# ── POST /api/users/:id/reset-password ────────────────────────────────────────
@users_bp.route("/<int:user_id>/reset-password", methods=["POST"])
@admin_required()
def reset_user_password_route(user_id):
    """Admin-initiated password reset for a user."""
    try:
        admin_id = int(get_jwt_identity())

        # Prevent admin from resetting their own password via this route
        if user_id == admin_id:
            return jsonify({"error": "Use the 'Change Password' feature in your settings."}), 403

        user_to_reset = find_user_by_id(user_id)
        if not user_to_reset:
            return jsonify({"error": "User not found"}), 404

        # Prevent a regular Admin from resetting a SUPER_ADMIN's password
        admin_user = find_user_by_id(admin_id)
        if user_to_reset["userRole"] == "SUPER_ADMIN" and admin_user.get("userRole") != "SUPER_ADMIN":
            return jsonify({"error": "Only a SUPER_ADMIN can reset another SUPER_ADMIN's password."}), 403

        # Generate new random password
        new_password = secrets.token_urlsafe(10)
        hashed = bcrypt.hashpw(
            new_password.encode("utf-8"),
            bcrypt.gensalt()
        ).decode("utf-8")

        # Update password and force change on next login
        # NOTE: These two operations should ideally be in a single transaction
        # in the model layer to ensure atomicity.
        update_password(user_id, hashed, must_change_password=True)
        set_reset_requested(user_id, False)

        try:
            from api.notifications import hub
            hub.publish_to_admins({"type": "user_updated", "userID": user_id})
        except Exception:
            pass

        return jsonify({
            "message": f"Password for user {user_to_reset['fullName']} has been reset.",
            "tempPassword": new_password
        }), 200
    except Exception:
        current_app.logger.exception("Failed to reset user password")
        return jsonify({"error": "Internal server error"}), 500


# ── DELETE /api/users/:id ─────────────────────────────────────────────────────
@users_bp.route("/<int:user_id>", methods=["DELETE"])
@admin_required()
def delete_user_route(user_id):
    """Delete a user. SUPER_ADMIN cannot delete themselves."""
    current_user_id = int(get_jwt_identity())

    if user_id == current_user_id:
        return jsonify({"error": "You cannot delete your own account"}), 403

    user = find_user_by_id(user_id)
    if not user:
        return jsonify({"error": "User not found"}), 404

    from app import mysql
    cursor = mysql.connection.cursor()

    # 1. Check for ACTIVE inspections (Assigned or In Progress)
    cursor.execute(
        "SELECT COUNT(*) AS count FROM inspection_reports WHERE userID = %s AND verificationStatus IN ('Assigned', 'In Progress')",
        (user_id,)
    )
    active_count = cursor.fetchone()["count"]

    if active_count > 0:
        cursor.close()
        return jsonify({"error": "You cannot delete an inspector with assigned task - reassign first"}), 409

    # 2. Check for HISTORICAL inspections (Submitted or Verified)
    cursor.execute(
        "SELECT COUNT(*) AS count FROM inspection_reports WHERE userID = %s AND verificationStatus IN ('Submitted', 'Verified')",
        (user_id,)
    )
    historical_count = cursor.fetchone()["count"]

    if historical_count > 0:
        # SOFT DELETE: Keep the history intact, but deactivate the account
        cursor.execute(
            "UPDATE users SET isActive = FALSE WHERE userID = %s", (user_id,))
        mysql.connection.commit()
        cursor.close()

        try:
            from api.notifications import hub
            hub.publish_to_admins({"type": "user_updated", "userID": user_id})
        except Exception:
            pass

        return jsonify({"message": "User deactivated successfully (soft delete) to preserve inspection history."}), 200

    cursor.close()

    # 3. HARD DELETE: Safe to obliterate since they have absolutely zero history
    delete_user(user_id)

    try:
        from api.notifications import hub
        hub.publish_to_admins({"type": "user_updated", "userID": user_id})
    except Exception:
        pass

    return jsonify({"message": "User deleted successfully"}), 200
