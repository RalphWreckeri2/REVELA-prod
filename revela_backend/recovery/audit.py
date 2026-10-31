"""Read-only database/storage audit. Never print credentials or business rows.

Run from revela_backend: python -m recovery.audit
"""
import json
import os
from pathlib import Path

import mysql.connector


def database_config():
    from config import Config
    return dict(host=Config.MYSQL_HOST, port=Config.MYSQL_PORT,
                user=Config.MYSQL_USER, password=Config.MYSQL_PASSWORD,
                database=Config.MYSQL_DB, connection_timeout=10)


def inspect_database(connection):
    cursor = connection.cursor(dictionary=True)
    try:
        cursor.execute("SELECT VERSION() AS version, @@log_bin AS log_bin, "
                       "@@binlog_format AS binlog_format, "
                       "@@binlog_expire_logs_seconds AS binlog_expire_logs_seconds, "
                       "@@gtid_mode AS gtid_mode")
        result = {"server": cursor.fetchone()}
        cursor.execute("SELECT ENGINE AS engine, COUNT(*) AS table_count, "
                       "SUM(DATA_LENGTH+INDEX_LENGTH) AS estimated_bytes "
                       "FROM information_schema.tables "
                       "WHERE table_schema=DATABASE() GROUP BY ENGINE")
        result["tables"] = cursor.fetchall()
        cursor.execute("SELECT photoPath FROM inspection_reports "
                       "WHERE photoPath IS NOT NULL")
        paths = [row["photoPath"] for row in cursor.fetchall() if row["photoPath"]]
        result["reports_with_evidence"] = len(paths)
        result["evidence_metadata"] = paths
        # These probes do not rotate, flush, change retention, or change logging.
        for statement in ("SHOW BINARY LOG STATUS", "SHOW MASTER STATUS"):
            try:
                cursor.execute(statement)
                result["binary_log_position"] = cursor.fetchone()
                break
            except mysql.connector.Error:
                result["binary_log_position"] = "unavailable (privilege/version)"
        return result
    finally:
        cursor.close()


def main():
    cfg = database_config()
    report = {"target_class": "loopback" if cfg["host"] in
              ("localhost", "127.0.0.1", "::1") else "remote"}
    try:
        with mysql.connector.connect(**cfg) as connection:
            report.update(inspect_database(connection))
        report.pop("evidence_metadata", None)
    except mysql.connector.Error as exc:
        # Driver messages can contain host names/users. Emit only the error code.
        report["database_audit"] = f"unavailable; connector error {exc.errno}"
    evidence = Path(os.getenv("EVIDENCE_DIR", str(
        Path(__file__).resolve().parents[1] / "instance" / "inspection_evidence")))
    report["local_evidence"] = {
        "directory_exists": evidence.is_dir(),
        "file_count": sum(1 for p in evidence.rglob("*") if p.is_file()) if evidence.is_dir() else 0,
        "bytes": sum(p.stat().st_size for p in evidence.rglob("*") if p.is_file()) if evidence.is_dir() else 0,
    }
    mobile = Path(__file__).resolve().parents[2] / "revela_mobile"
    signing = mobile / "android" / "key.properties"
    report["mobile_release"] = {
        "signing_properties_present": signing.is_file(),
        "keystore_present": False,
        "local_apk_count": len(list((mobile / "build" / "app" / "outputs" / "flutter-apk").glob("*.apk"))),
        "independent_key_or_artifact_backup": "not verified",
    }
    if signing.is_file():
        # Inspect existence only; never print passwords, aliases, key material,
        # signing-property contents, or the private keystore path.
        for line in signing.read_text(encoding="utf-8").splitlines():
            name, separator, value = line.partition("=")
            if separator and name.strip() == "storeFile":
                value = value.strip().replace("\\:", ":").replace("\\\\", "\\")
                path = Path(value)
                if not path.is_absolute():
                    path = mobile / "android" / "app" / path
                report["mobile_release"]["keystore_present"] = path.is_file()
    print(json.dumps(report, indent=2, default=str))


if __name__ == "__main__":
    main()
