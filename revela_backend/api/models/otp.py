from app import mysql


def create_otp(user_id, token):
    """Store OTP with 15min expiry."""
    cur = mysql.connection.cursor()
    cur.execute("""
        INSERT INTO USER_PASSWORD_RESETS (userID, pwToken, expiresAt)
        VALUES (%s, %s, DATE_ADD(NOW(), INTERVAL 15 MINUTE))
    """, (user_id, token))
    mysql.connection.commit()
    cur.close()


def get_valid_otp(user_id, token):
    """Fetch OTP only if not expired and not used."""
    cur = mysql.connection.cursor()
    cur.execute("""
        SELECT * FROM USER_PASSWORD_RESETS
        WHERE userID = %s
          AND pwToken = %s
          AND isUsed = FALSE
          AND expiresAt > NOW()
        ORDER BY createdAt DESC
        LIMIT 1
    """, (user_id, token))
    otp = cur.fetchone()
    cur.close()
    return otp


def mark_otp_used(upr_id):
    """Mark OTP as used after successful reset."""
    cur = mysql.connection.cursor()
    cur.execute("""
        UPDATE USER_PASSWORD_RESETS
        SET isUsed = TRUE
        WHERE uprID = %s
    """, (upr_id,))
    mysql.connection.commit()
    cur.close()


def delete_otp(upr_id):
    """Delete OTP record after use."""
    cur = mysql.connection.cursor()
    cur.execute("DELETE FROM USER_PASSWORD_RESETS WHERE uprID = %s", (upr_id,))
    mysql.connection.commit()
    cur.close()


def invalidate_user_otps(user_id):
    """Mark all existing OTPs for the user as used (invalidate them)."""
    cur = mysql.connection.cursor()
    cur.execute("""
        UPDATE USER_PASSWORD_RESETS
        SET isUsed = TRUE
        WHERE userID = %s AND isUsed = FALSE
    """, (user_id,))
    mysql.connection.commit()
    cur.close()
