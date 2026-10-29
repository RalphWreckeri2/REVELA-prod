import os
import re
import stat
import subprocess
from contextlib import contextmanager
from pathlib import Path

import mysql.connector

from recovery.audit import database_config


def strict_tls_preflight():
    """Verify a remote MySQL TLS connection without acquiring locks or reading rows."""
    config = source_config()
    _require_remote_tls(config)
    connection = mysql.connector.connect(**config)
    try:
        cursor = connection.cursor()
        try:
            cursor.execute("SELECT VERSION()")
            version = cursor.fetchone()[0]
            cursor.execute("SHOW SESSION STATUS LIKE 'Ssl_cipher'")
            cipher = cursor.fetchone()[1]
            if not cipher:
                raise ValueError("mysql_tls_not_negotiated")
            return {"mysql_version": version, "tls_cipher": cipher,
                    "certificate_verified": True, "hostname_verified": True}
        finally:
            cursor.close()
    finally:
        connection.close()


def source_config():
    config = database_config()
    for key, environment in (("host", "BACKUP_DB_HOST"), ("port", "BACKUP_DB_PORT"),
                             ("database", "BACKUP_DB_NAME"), ("user", "BACKUP_DB_USER"),
                             ("password", "BACKUP_DB_PASSWORD")):
        if environment in os.environ:
            config[key] = int(os.environ[environment]) if key == "port" else os.environ[environment]
    if config["host"] not in ("localhost", "127.0.0.1", "::1"):
        if not os.getenv("BACKUP_DB_USER") or not os.getenv("BACKUP_DB_PASSWORD"):
            raise ValueError("A dedicated least-privilege backup database identity is required")
        config.update(
            ssl_ca=os.getenv("BACKUP_DB_SSL_CA_FILE", ""),
            ssl_cert=os.getenv("BACKUP_DB_SSL_CERT_FILE", ""),
            ssl_key=os.getenv("BACKUP_DB_SSL_KEY_FILE", ""),
            ssl_verify_cert=True,
            ssl_verify_identity=True,
        )
        _require_remote_tls(config)
    return config


def _require_remote_tls(config):
    if (config.get("host") in ("localhost", "127.0.0.1", "::1")
            or not config.get("ssl_ca")
            or not config.get("ssl_cert")
            or not config.get("ssl_key")
            or config.get("ssl_verify_cert") is not True
            or config.get("ssl_verify_identity") is not True):
        raise ValueError("strict_tls_configuration_required")
    ca_path = Path(config["ssl_ca"])
    cert_path = Path(config["ssl_cert"])
    key_path = Path(config["ssl_key"])
    if not ca_path.is_file() or not cert_path.is_file() or not key_path.is_file():
        raise ValueError("backup_tls_material_unavailable")
    if os.name != "nt" and stat.S_IMODE(key_path.stat().st_mode) & 0o077:
        raise ValueError("backup_client_key_permissions_invalid")


@contextmanager
def client_options(directory, config):
    """Do not expose the password in argv, logs, archives or process environment."""
    path = directory / ".mysql-client.cnf"
    def escape(value):
        return str(value).replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\r", "\\r")
    entries = {"host": config["host"], "port": config["port"],
               "user": config["user"], "password": config["password"]}
    remote = config.get("host") not in ("localhost", "127.0.0.1", "::1")
    if remote:
        _require_remote_tls(config)
        entries.update({
            "ssl-ca": config["ssl_ca"],
            "ssl-cert": config["ssl_cert"],
            "ssl-key": config["ssl_key"],
            "ssl-mode": "VERIFY_IDENTITY",
        })
    else:
        entries["ssl-mode"] = "PREFERRED"
    try:
        with path.open("x", encoding="utf-8") as stream:
            os.chmod(path, 0o600)
            stream.write("[client]\n" + "".join(f'{k}="{escape(v)}"\n' for k, v in entries.items()))
        yield f"--defaults-file={path}"
    finally:
        path.unlink(missing_ok=True)


def check_dump_client(executable, server_version):
    version = subprocess.run([executable, "--version"], capture_output=True, timeout=15, check=True)
    text = version.stdout.decode(errors="replace")
    match = re.search(r"(?:Ver|Distrib)\s+(\d+)\.", text)
    if "mariadb" in text.lower() or not match or match[1] != server_version.split(".")[0]:
        raise RuntimeError("matching_oracle_mysql_client_required")


def client_environment(directory):
    """Ignore saved MySQL login paths and password env overrides for this child only.

    Oracle's login-file override works on the supported Windows 8.0 clients too,
    where --no-login-paths is not available. No password enters the environment.
    """
    import uuid
    environment = os.environ.copy()
    for name in ("MYSQL_PWD", "MYSQL_HOST", "MYSQL_TCP_PORT", "MYSQL_UNIX_PORT", "MYSQL_GROUP_SUFFIX"):
        environment.pop(name, None)
    environment["MYSQL_TEST_LOGIN_FILE"] = str(directory / (".unused-login-" + uuid.uuid4().hex + ".cnf"))
    return environment


def run_dump(executable, config, destination, server_version, timeout=600):
    check_dump_client(executable, server_version)
    created = False
    try:
        with client_options(destination.parent, config) as defaults:
            descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            created = True
            with os.fdopen(descriptor, "wb") as output:
                result = subprocess.run([
                    executable, defaults, "--single-transaction", "--quick", "--skip-lock-tables",
                    "--routines", "--events", "--triggers", "--hex-blob", "--no-tablespaces",
                    "--set-gtid-purged=OFF", "--column-statistics=0", "--default-character-set=utf8mb4",
                    config["database"],
                ], stdout=output, stderr=subprocess.PIPE, timeout=timeout,
                    env=client_environment(destination.parent))
                output.flush()
                os.fsync(output.fileno())
        if result.returncode or not destination.stat().st_size:
            raise RuntimeError("database_dump_failed")
    except Exception:
        if created:
            destination.unlink(missing_ok=True)
        raise
