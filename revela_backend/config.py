import os
import hmac
import ipaddress
import socket
from datetime import timedelta
from dotenv import load_dotenv

_dotenv_name = (
    ".env.qa"
    if os.getenv("REVELA_QA_MODE", "").strip().lower()
    not in ("", "0", "false", "off", "no")
    else ".env"
)
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), _dotenv_name))


_QA_DATABASE_NAME = "revela_test_mobile_phase72"
_DB_ENV_ALIASES = (
    "DB_HOST",
    "MYSQLHOST",
    "DB_PORT",
    "MYSQLPORT",
    "DB_USER",
    "MYSQLUSER",
    "DB_PASSWORD",
    "MYSQLPASSWORD",
    "DB_NAME",
    "MYSQLDATABASE",
)


def _qa_enabled(environ):
    value = environ.get("REVELA_QA_MODE", "").strip().lower()
    if value in ("", "0", "false", "off", "no"):
        return False
    if value == "1":
        return True
    raise RuntimeError("REVELA_QA_MODE must be set to exactly 1 or 0.")


def _resolved_loopback_addresses(host, port):
    normalized = host.strip().lower()
    try:
        address = ipaddress.ip_address(normalized.split("%", 1)[0])
        if not address.is_loopback:
            raise RuntimeError("QA database host must resolve only to loopback.")
        return {address.compressed}
    except ValueError:
        if normalized != "localhost":
            raise RuntimeError(
                "QA database host must be localhost, 127.0.0.1, or ::1."
            )

    try:
        results = socket.getaddrinfo(
            normalized, port, family=socket.AF_UNSPEC, type=socket.SOCK_STREAM
        )
    except OSError as exc:
        raise RuntimeError("QA localhost name resolution failed.") from exc
    addresses = {
        ipaddress.ip_address(result[4][0].split("%", 1)[0]).compressed
        for result in results
    }
    if not addresses or any(
        not ipaddress.ip_address(address).is_loopback for address in addresses
    ):
        raise RuntimeError(
            "QA localhost must resolve exclusively to loopback addresses."
        )
    return addresses


def _resolve_qa_database_settings(environ):
    required = {
        "REVELA_QA_DB_HOST": environ.get("REVELA_QA_DB_HOST", "").strip(),
        "REVELA_QA_DB_PORT": environ.get("REVELA_QA_DB_PORT", "").strip(),
        "REVELA_QA_DB_NAME": environ.get("REVELA_QA_DB_NAME", "").strip(),
        "REVELA_QA_DB_USER": environ.get("REVELA_QA_DB_USER", "").strip(),
        "REVELA_QA_DB_PASSWORD": environ.get("REVELA_QA_DB_PASSWORD", ""),
    }
    if any(not value for value in required.values()):
        raise RuntimeError(
            "QA mode requires REVELA_QA_DB_HOST, REVELA_QA_DB_PORT, "
            "REVELA_QA_DB_NAME, REVELA_QA_DB_USER, and "
            "REVELA_QA_DB_PASSWORD."
        )
    if required["REVELA_QA_DB_NAME"] != _QA_DATABASE_NAME:
        raise RuntimeError(
            f"QA mode permits only database {_QA_DATABASE_NAME!r}."
        )
    if not required["REVELA_QA_DB_USER"].lower().endswith("_qa"):
        raise RuntimeError(
            "QA mode requires a dedicated database username ending in '_qa'."
        )
    try:
        port = int(required["REVELA_QA_DB_PORT"])
    except ValueError as exc:
        raise RuntimeError("REVELA_QA_DB_PORT must be an integer.") from exc
    if not 1 <= port <= 65535:
        raise RuntimeError("REVELA_QA_DB_PORT must be between 1 and 65535.")

    host = required["REVELA_QA_DB_HOST"]
    _resolved_loopback_addresses(host, port)

    # Generic connector aliases are never used in QA. If inherited, require
    # them to describe the same approved local target and dedicated account.
    expected_aliases = {
        "DB_HOST": host,
        "MYSQLHOST": host,
        "DB_PORT": str(port),
        "MYSQLPORT": str(port),
        "DB_USER": required["REVELA_QA_DB_USER"],
        "MYSQLUSER": required["REVELA_QA_DB_USER"],
        "DB_NAME": _QA_DATABASE_NAME,
        "MYSQLDATABASE": _QA_DATABASE_NAME,
    }
    for alias in _DB_ENV_ALIASES:
        value = environ.get(alias)
        if value is None or value == "":
            continue
        if alias in ("DB_HOST", "MYSQLHOST"):
            try:
                _resolved_loopback_addresses(value, port)
            except RuntimeError as exc:
                raise RuntimeError(
                    f"Inherited {alias} is unsafe in QA mode."
                ) from exc
            if value.strip().lower() != host.strip().lower():
                raise RuntimeError(
                    f"Inherited {alias} conflicts with the explicit QA host."
                )
        elif alias in ("DB_PASSWORD", "MYSQLPASSWORD"):
            if not hmac.compare_digest(value, required["REVELA_QA_DB_PASSWORD"]):
                raise RuntimeError(
                    f"Inherited {alias} conflicts with the explicit QA credentials."
                )
        elif value.strip() != expected_aliases[alias]:
            raise RuntimeError(
                f"Inherited {alias} conflicts with the explicit QA database settings."
            )

    return {
        "REVELA_QA_MODE": True,
        "MYSQL_HOST": host,
        "MYSQL_PORT": port,
        "MYSQL_DB": _QA_DATABASE_NAME,
        "MYSQL_USER": required["REVELA_QA_DB_USER"],
        "MYSQL_PASSWORD": required["REVELA_QA_DB_PASSWORD"],
    }


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY")
    JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY")
    JWT_ACCESS_TOKEN_EXPIRES = timedelta(hours=12)

    # Web portal inactivity auto-logout.  Sessions that go this long without
    # reported user interaction are refused by the backend.  Independent of the
    # JWT expiry above, which remains the hard 12-hour ceiling.
    SESSION_IDLE_TIMEOUT = timedelta(minutes=10)
    MOBILE_SESSION_IDLE_TIMEOUT = timedelta(minutes=1)

    MYSQL_HOST = os.getenv("DB_HOST") or os.getenv("MYSQLHOST") or "localhost"
    MYSQL_PORT = int(os.getenv("DB_PORT") or os.getenv("MYSQLPORT") or 3306)
    MYSQL_USER = os.getenv("DB_USER") or os.getenv("MYSQLUSER")
    MYSQL_PASSWORD = os.getenv("DB_PASSWORD") or os.getenv("MYSQLPASSWORD")
    MYSQL_DB = os.getenv("DB_NAME") or os.getenv("MYSQLDATABASE") or "revela_db"
    MYSQL_CURSORCLASS = "DictCursor"

    @classmethod
    def resolve_database_settings(cls, environ=None):
        """Return the normal settings or validate an isolated QA target."""
        source = os.environ if environ is None else environ
        if _qa_enabled(source):
            return _resolve_qa_database_settings(source)
        return {
            "REVELA_QA_MODE": False,
            "MYSQL_HOST": cls.MYSQL_HOST,
            "MYSQL_PORT": cls.MYSQL_PORT,
            "MYSQL_USER": cls.MYSQL_USER,
            "MYSQL_PASSWORD": cls.MYSQL_PASSWORD,
            "MYSQL_DB": cls.MYSQL_DB,
        }
