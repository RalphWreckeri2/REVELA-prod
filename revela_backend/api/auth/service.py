import random
import bcrypt
import os
import requests
from api.models.user import find_user_by_email, find_user_by_id, update_last_login, update_password
from api.models.otp import create_otp, get_valid_otp, delete_otp, invalidate_user_otps
from flask_jwt_extended import create_access_token
import pyotp


def login_user(email, password):
    """
    1. Find user by email
    2. Verify password with bcrypt
    3. Return JWT with {userID, role} in payload
    """
    user = find_user_by_email(email)

    if not user:
        return None, "Invalid email or password"

    # The USERS table uses isActive.  Retain the old spelling as a fallback for
    # deployments whose schema has not yet been migrated.
    if not user.get("isActive", user.get("is_active", True)):
        return None, "Account is disabled. Please contact the administrator."

    # A NULL, plaintext, or otherwise invalid stored hash raises from bcrypt.
    # Let the route log it and return a safe 500 instead of hiding corruption as
    # a bad-password response.
    stored_hash = user.get("userPassword")
    if not isinstance(stored_hash, (str, bytes)):
        raise RuntimeError("User password hash is missing or invalid")

    raw_hash = stored_hash.encode("utf-8") if isinstance(stored_hash, str) else stored_hash
    password_matches = bcrypt.checkpw(password.encode("utf-8"), raw_hash)

    if not password_matches:
        return None, "Invalid email or password"

    # Stamp last login
    update_last_login(user["userID"])

    # Create JWT — additional_claims carries role and application-specific states
    token = create_access_token(
        identity=str(user["userID"]),
        additional_claims={
            "role": user["userRole"],
            "mustChangePassword": bool(user.get("mustChangePassword", False))
        }
    )

    return token, None


def request_otp(identifier):
    """
    identifier can be email or phone number.
    1. Find user
    2. Generate 5-digit OTP
    3. Store in DB
    4. Send via SMS or Email
    """
    if "@" in identifier:
        user = find_user_by_email(identifier)
    else:
        from api.models.user import find_user_by_phone
        user = find_user_by_phone(identifier)
        if not user:
            try:
                from api.users.routes import _normalize_phone
                norm = _normalize_phone(identifier)
                if norm and norm != identifier:
                    user = find_user_by_phone(norm)
            except Exception:
                pass

    if not user:
        return False, "No account found with this email or phone number."

    # Only allow Admin / SUPER_ADMIN on this portal
    if user.get("userRole") not in ("Admin", "SUPER_ADMIN"):
        return False, "This account is not authorized for password reset on this portal."

    # Invalidate any existing OTPs for this user
    invalidate_user_otps(user["userID"])

    otp_code = str(random.randint(10000, 99999))  # 5-digit

    create_otp(user["userID"], otp_code)

    # Decide channel based on identifier format
    if "@" in identifier:
        sent = send_otp_email(identifier, otp_code)
    else:
        sent = send_otp_via_philsms(identifier, otp_code)

    if not sent:
        return False, "Failed to send OTP. Please verify your contact information or try again later."

    return True, None


def send_otp_via_philsms(phone_number, otp_code):
    """Send OTP via PhilSMS API gateway."""
    try:
        # Format phone number to PhilSMS format (639XXXXXXXXX)
        formatted_phone = format_phone_number(phone_number)

        if not formatted_phone:
            print(f"SMS error: Invalid phone number format: {phone_number}")
            return False

        token = os.getenv("PHILSMS_API_TOKEN") or os.getenv("PHILSMS_TOKEN") or os.getenv("PHILSMS_API_KEY")
        if not token:
            print("SMS error: PHILSMS_API_TOKEN is not configured in environment variables.")
            return False

        url = "https://dashboard.philsms.com/api/v3/sms/send"
        sender_id = os.getenv("PHILSMS_SENDER_ID", "PhilSMS")
        message_content = f"Your REVELA OTP is {otp_code}. Do not share this code with anyone. It expires in 15 minutes."

        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json"
        }

        payload = {
            "recipient": formatted_phone,
            "sender_id": sender_id,
            "type": "plain",
            "message": message_content
        }

        response = requests.post(url, headers=headers, json=payload, timeout=10)

        # Check HTTP status
        if response.status_code not in (200, 201):
            print(f"PhilSMS error: HTTP {response.status_code} - {response.text}")
            return False

        # Parse JSON response and check API status
        try:
            api_response = response.json()
            status_val = api_response.get("status")
            if status_val in ("success", "Success", 1, True) or "data" in api_response:
                print(f"SMS sent successfully via PhilSMS to {formatted_phone}")
                return True
            elif status_val in ("error", "failed", 0, False):
                print(f"PhilSMS API error: {api_response}")
                return False
            else:
                print(f"PhilSMS response: {api_response}")
                return True
        except Exception:
            return response.ok

    except requests.exceptions.RequestException as e:
        print(f"OTP Dispatch Failed: {e}")
        return False
    except Exception as e:
        print(f"SMS error: {type(e).__name__} - {e}")
        return False


# Backward compatibility alias
send_otp_sms = send_otp_via_philsms


def format_phone_number(phone):
    """
    Convert phone number to PhilSMS format (639XXXXXXXXX).
    Handles:
        09123456789   → 639123456789
        +639123456789 → 639123456789
        639123456789  → 639123456789
        9123456789    → 639123456789
    """
    if not phone:
        return None

    # Remove all non-digit characters
    clean_phone = "".join(filter(str.isdigit, str(phone).strip()))

    # Handle Philippine number formats
    if clean_phone.startswith("09") and len(clean_phone) == 11:
        clean_phone = "63" + clean_phone[1:]
    elif clean_phone.startswith("9") and len(clean_phone) == 10:
        clean_phone = "63" + clean_phone
    elif clean_phone.startswith("6309") and len(clean_phone) == 13:
        clean_phone = "63" + clean_phone[3:]
    elif clean_phone.startswith("639") and len(clean_phone) == 12:
        pass
    else:
        if clean_phone.startswith("0"):
            clean_phone = "63" + clean_phone[1:]
        elif not clean_phone.startswith("63"):
            clean_phone = "63" + clean_phone

    return clean_phone if len(clean_phone) == 12 and clean_phone.startswith("639") else None


def send_otp_email(email, otp_code):
    """Send OTP via Resend email API."""
    try:
        response = requests.post(
            "https://api.resend.com/emails",
            headers={
                "Authorization": f"Bearer {os.getenv('RESEND_API_KEY')}",
                "Content-Type": "application/json",
            },
            json={
                "from": os.getenv("RESEND_FROM"),
                "to": [email],
                "subject": "REVELA Password Reset OTP",
                "text": f"Your REVELA password reset code is: {otp_code}. Valid for 15 minutes. Do not share this code.",
            }
        )
        return response.status_code == 200
    except Exception as e:
        print(f"Email error: {e}")
        return False


def reset_password(identifier, otp_code, new_password):
    """
    1. Find user
    2. Validate OTP
    3. bcrypt hash new password
    4. UPDATE USERS
    5. DELETE OTP record
    """
    if "@" in identifier:
        user = find_user_by_email(identifier)
    else:
        from api.models.user import find_user_by_phone
        user = find_user_by_phone(identifier)
        if not user:
            try:
                from api.users.routes import _normalize_phone
                norm = _normalize_phone(identifier)
                if norm and norm != identifier:
                    user = find_user_by_phone(norm)
            except Exception:
                pass

    if not user:
        return False, "No account found with this email or phone number."

    # Guard: Only allow password reset for Admins on this portal
    if user.get("userRole") not in ("Admin", "SUPER_ADMIN"):
        return False, "This account is not authorized for password reset on this portal."

    otp_record = get_valid_otp(user["userID"], otp_code)

    if not otp_record:
        return False, "OTP is invalid or has expired."

    hashed = bcrypt.hashpw(new_password.encode(
        "utf-8"), bcrypt.gensalt()).decode("utf-8")
    update_password(user["userID"], hashed)
    delete_otp(otp_record["uprID"])

    return True, None


# Change password feature in settings
def update_user_password(user_id, old_password, new_password):
    # 1. Fetch user
    user = find_user_by_id(user_id)
    if not user:
        return {"error": "User not found", "status": 404}

    # 2. Verify old password
    if not bcrypt.checkpw(old_password.encode("utf-8"), user["userPassword"].encode("utf-8")):
        return {"error": "Incorrect current password", "status": 400}

    # 3. Prevent same password reuse (optional)
    if old_password == new_password:
        return {"error": "New password cannot be the same as old", "status": 400}

    # 4. Hash and Update
    hashed = bcrypt.hashpw(new_password.encode(
        "utf-8"), bcrypt.gensalt()).decode("utf-8")
    update_password(user_id, hashed)

    return {"message": "Password updated successfully", "status": 200}


# 2FA feature in settings
def generate_2fa_setup(user_email):
    # Create a random base32 secret
    secret = pyotp.random_base32()

    # Create an otpauth:// URI for the QR code
    # 'Project REVELA' can be your app name
    otp_uri = pyotp.TOTP(secret).provisioning_uri(
        name=user_email,
        issuer_name="Project REVELA"
    )

    return secret, otp_uri


def verify_totp_code(secret, code):
    totp = pyotp.TOTP(secret)
    return totp.verify(code, valid_window=10)
