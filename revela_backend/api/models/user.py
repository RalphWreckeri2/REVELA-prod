from app import mysql


def find_user_by_email(email):
    """Fetch a single user row by email."""
    cur = mysql.connection.cursor()
    cur.execute("SELECT * FROM users WHERE email = %s", (email,))
    user = cur.fetchone()  # returns dict because of DictCursor
    cur.close()
    return user


def find_user_by_id(user_id):
    cur = mysql.connection.cursor()
    cur.execute("SELECT * FROM users WHERE userID = %s", (user_id,))
    user = cur.fetchone()
    cur.close()
    return user


def find_user_by_phone(phone):
    cur = mysql.connection.cursor()
    cur.execute("SELECT * FROM users WHERE phone = %s", (phone,))
    user = cur.fetchone()
    cur.close()
    return user


def update_password(user_id, hashed_password, must_change_password=False):
    cur = mysql.connection.cursor()
    cur.execute("""
        UPDATE users SET userPassword = %s, mustChangePassword = %s, updatedAt = NOW()
        WHERE userID = %s
    """, (hashed_password, must_change_password, user_id))
    mysql.connection.commit()
    cur.close()


def update_last_login(user_id):
    """Stamp lastLoginAt on successful login."""
    cur = mysql.connection.cursor()
    cur.execute(
        "UPDATE users SET lastLoginAt = NOW() WHERE userID = %s",
        (user_id,)
    )
    mysql.connection.commit()
    cur.close()

def set_reset_requested(user_id, value):
    """Set the resetRequested flag for a user."""
    cur = mysql.connection.cursor()
    cur.execute(
        "UPDATE users SET resetRequested = %s WHERE userID = %s",
        (1 if value else 0, user_id)
    )
    mysql.connection.commit()
    cur.close()


def get_all_users():
    """Fetch all users except passwords."""
    cur = mysql.connection.cursor()
    cur.execute("""
        SELECT userID, fullName, email, phone, userRole, 
               createdAt, lastLoginAt, mustChangePassword, resetRequested, isActive
        FROM users
        ORDER BY createdAt DESC
    """)
    users = cur.fetchall()
    cur.close()
    # Serialise datetimes
    for u in users:
        for field in ("createdAt", "lastLoginAt"):
            if u.get(field):
                u[field] = str(u[field])
    return users


def get_users_by_role(role):
    """Fetch all users by role (case-insensitive), excluding passwords."""
    cur = mysql.connection.cursor()
    cur.execute("""
        SELECT userID, fullName, email, phone, userRole, 
               createdAt, lastLoginAt, mustChangePassword, resetRequested, isActive
        FROM users
        WHERE LOWER(userRole) = LOWER(%s)
        ORDER BY createdAt DESC
    """, (role,))
    users = cur.fetchall()
    cur.close()
    # Serialise datetimes
    for u in users:
        for field in ("createdAt", "lastLoginAt"):
            if u.get(field):
                u[field] = str(u[field])
    return users



def create_user(full_name, email, hashed_password, role, phone=None, must_change_password=True):
    """Insert a new user."""
    cur = mysql.connection.cursor()
    cur.execute("""
        INSERT INTO users 
            (fullName, email, userPassword, userRole, phone, mustChangePassword)
        VALUES (%s, %s, %s, %s, %s, %s)
    """, (full_name, email, hashed_password, role, phone, must_change_password))
    mysql.connection.commit()
    user_id = cur.lastrowid
    cur.close()
    return user_id


def update_user(user_id, full_name, email, role, phone=None):
    """Update user profile fields."""
    cur = mysql.connection.cursor()
    cur.execute("""
        UPDATE users
        SET fullName = %s, email = %s, userRole = %s, phone = %s, updatedAt = NOW()
        WHERE userID = %s
    """, (full_name, email, role, phone, user_id))
    mysql.connection.commit()
    cur.close()


def delete_user(user_id):
    """Delete a user by ID."""
    cur = mysql.connection.cursor()
    cur.execute("DELETE FROM users WHERE userID = %s", (user_id,))
    mysql.connection.commit()
    cur.close()


def enable_user_2fa(user_id, is_enabled):
    """Enable or disable 2FA for a user."""
    cur = mysql.connection.cursor()
    cur.execute(
        "UPDATE users SET is_2fa_enabled = %s, updatedAt = NOW() WHERE userID = %s",  # ← fixed
        (is_enabled, user_id))
    mysql.connection.commit()
    cur.close()
    return True


def update_user_2fa_secret(user_id, secret):
    """Store the 2FA secret for a user."""
    cur = mysql.connection.cursor()
    cur.execute(
        "UPDATE users SET two_factor_secret = %s, updatedAt = NOW() WHERE userID = %s", (secret, user_id))
    mysql.connection.commit()
    cur.close()


def get_user_2fa_secret(user_id):
    """Retrieve the 2FA secret for a user."""
    cur = mysql.connection.cursor()
    cur.execute(
        "SELECT two_factor_secret FROM users WHERE userID = %s", (user_id,))
    user = cur.fetchone()
    cur.close()
    return user['two_factor_secret'] if user else None
