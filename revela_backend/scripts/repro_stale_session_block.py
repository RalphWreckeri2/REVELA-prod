"""Reproduce the false 'account already logged in' report."""
import sys
import threading
import time

from flask import Flask
from flask_jwt_extended import JWTManager, decode_token
from unittest.mock import patch

sys.path.insert(0, ".")
from api.auth import sessions
from tests.test_auth_sessions import InMemorySessionMySQL, InMemorySessionStore

IDLE_SECONDS = 10 * 60

app = Flask(__name__)
app.config.update(JWT_SECRET_KEY="s", JWT_ACCESS_TOKEN_EXPIRES=__import__("datetime").timedelta(hours=12))
JWTManager(app)


def scenario(title, registry_aware, age_minutes):
    store = InMemorySessionStore()
    user = {"userID": 12, "userRole": "Admin"}
    mysql = InMemorySessionMySQL(store)

    with patch.object(sessions, "mysql", mysql), patch.object(
        sessions, "_session_table_ready", True
    ):
        with app.app_context():
            jwt = sessions.issue_session_token(user, "web")
            sid = decode_token(jwt)["session_id"]

            if registry_aware:
                # Server kept running: the row's activity is tracked in-process.
                with sessions._activity_lock:
                    sessions._last_activity[sid] = time.monotonic() - (age_minutes * 60)
            else:
                # Server restarted: in-process activity map is empty.
                with sessions._activity_lock:
                    sessions._last_activity.clear()
                store.rows[12] = (sid, "web", age_minutes)

            try:
                sessions.issue_session_token({"userID": 12, "userRole": "Admin"}, "web")
                outcome = "LOGIN ALLOWED"
            except sessions.ActiveSessionConflict:
                outcome = "LOGIN BLOCKED"

    with sessions._activity_lock:
        sessions._last_activity.clear()
    print(f"{title:<62} -> {outcome}")


print("Device A's session is 40 minutes old with no user interaction.\n")
scenario("A) server never restarted (registry knows the session)", True, 40)
scenario("B) server restarted, empty activity map        <-- BUG", False, 40)
print()
scenario("C) server never restarted, session 5 min old   ", True, 5)
scenario("D) server restarted, session 5 min old         ", False, 5)