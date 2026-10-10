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
    SESSION_IDLE_TIMEOUT = timedelta(minutes=30)

    MYSQL_HOST = os.getenv("DB_HOST") or os.getenv("MYSQLHOST") or "localhost"
    MYSQL_PORT = int(os.getenv("DB_PORT") or os.getenv("MYSQLPORT") or 3306)
    MYSQL_USER = os.getenv("DB_USER") or os.getenv("MYSQLUSER")
    MYSQL_PASSWORD = os.getenv("DB_PASSWORD") or os.getenv("MYSQLPASSWORD")
    MYSQL_DB = os.getenv("DB_NAME") or os.getenv("MYSQLDATABASE") or "revela_db"
    MYSQL_CURSORCLASS = "DictCursor"
