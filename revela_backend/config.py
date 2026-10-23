import os
from datetime import timedelta
from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), ".env"))


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY")
    JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY")
    JWT_ACCESS_TOKEN_EXPIRES = timedelta(hours=12)

    # Web portal inactivity auto-logout.  Sessions that go this long without
    # reported user interaction are refused by the backend.  Independent of the
    # JWT expiry above, which remains the hard 12-hour ceiling.
    SESSION_IDLE_TIMEOUT = timedelta(minutes=10)
    MOBILE_SESSION_IDLE_TIMEOUT = timedelta(minutes=1)

    # API rate limits are per client IP and per application process. Keep
    # trusted proxy forwarding disabled unless the ingress count is known.
    API_RATE_LIMIT = int(os.getenv("API_RATE_LIMIT", "300"))
    API_RATE_WINDOW_SECONDS = int(os.getenv("API_RATE_WINDOW_SECONDS", "60"))
    AUTH_LOGIN_RATE_LIMIT = int(os.getenv("AUTH_LOGIN_RATE_LIMIT", "10"))
    AUTH_LOGIN_RATE_WINDOW_SECONDS = int(
        os.getenv("AUTH_LOGIN_RATE_WINDOW_SECONDS", "300"))
    AUTH_2FA_LOGIN_RATE_LIMIT = int(
        os.getenv("AUTH_2FA_LOGIN_RATE_LIMIT", "10"))
    AUTH_2FA_LOGIN_RATE_WINDOW_SECONDS = int(
        os.getenv("AUTH_2FA_LOGIN_RATE_WINDOW_SECONDS", "900"))
    AUTH_OTP_RATE_LIMIT = int(os.getenv("AUTH_OTP_RATE_LIMIT", "5"))
    AUTH_OTP_RATE_WINDOW_SECONDS = int(
        os.getenv("AUTH_OTP_RATE_WINDOW_SECONDS", "900"))
    AUTH_MANUAL_RESET_RATE_LIMIT = int(
        os.getenv("AUTH_MANUAL_RESET_RATE_LIMIT", "3"))
    AUTH_MANUAL_RESET_RATE_WINDOW_SECONDS = int(
        os.getenv("AUTH_MANUAL_RESET_RATE_WINDOW_SECONDS", "3600"))
    AUTH_PASSWORD_RESET_RATE_LIMIT = int(
        os.getenv("AUTH_PASSWORD_RESET_RATE_LIMIT", "10"))
    AUTH_PASSWORD_RESET_RATE_WINDOW_SECONDS = int(
        os.getenv("AUTH_PASSWORD_RESET_RATE_WINDOW_SECONDS", "900"))
    TRUSTED_PROXY_COUNT = int(os.getenv("TRUSTED_PROXY_COUNT", "0"))

    MYSQL_HOST = os.getenv("DB_HOST") or os.getenv("MYSQLHOST") or "localhost"
    MYSQL_PORT = int(os.getenv("DB_PORT") or os.getenv("MYSQLPORT") or 3306)
    MYSQL_USER = os.getenv("DB_USER") or os.getenv("MYSQLUSER")
    MYSQL_PASSWORD = os.getenv("DB_PASSWORD") or os.getenv("MYSQLPASSWORD")
    MYSQL_DB = os.getenv("DB_NAME") or os.getenv("MYSQLDATABASE") or "revela_db"
    MYSQL_CURSORCLASS = "DictCursor"
