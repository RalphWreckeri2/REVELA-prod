"""Guarded drill: new, empty loopback MySQL instance only. No production mode."""
import json
import os
import re
import subprocess
import time
from pathlib import Path

import mysql.connector

from recovery.bundle import referenced_files, unpack_verified
from recovery.crypto import decrypt, sha256
from recovery.mysqltools import client_options, client_environment
from recovery import status
from recovery.locking import lock

SYSTEM_SCHEMAS = {"mysql", "sys", "information_schema", "performance_schema"}


def record_drill(report, receipt, directory):
    """Custodian-only filesystem operation; merges evidence without old-state copy.

    Inputs must be the privately transported drill report and the matching
    independently downloaded immutable receipt. This is not a public API.
    """
    from datetime import datetime, timedelta
    if (report.get("success") is not True or report.get("isolated") is not True
            or not report.get("target_server_uuid") or not report.get("source_server_uuid")
            or not re.fullmatch(r"[0-9a-f]{32}", str(report.get("id", "")))
            or not re.fullmatch(r"[0-9a-f]{64}", str(report.get("bundle_sha256", "")))
            or report.get("target_server_uuid") == report.get("source_server_uuid")
            or report.get("id") != receipt.get("id")
            or report.get("bundle_sha256") != receipt.get("object", {}).get("sha256")
            or report.get("environment") != receipt.get("environment")
            or report.get("source_server_uuid") != receipt.get("source_server_uuid")):
        raise ValueError("Drill and immutable backup receipt do not match")
    tested_at = datetime.fromisoformat(report["tested_at"])
    age = status.now() - tested_at
    if age < timedelta(minutes=-5) or age >= timedelta(days=90):
        raise ValueError("Drill evidence is future-dated or expired")
    with lock("job", directory=directory):
        state = status.load(directory)
        last = state.get("last_success") or {}
        if (last.get("environment") != report["environment"]
                or last.get("source_server_uuid") != report["source_server_uuid"]):
            raise ValueError("Drill does not match this backup status environment")
        state["last_restore_test"] = report
        status.save(state, directory)


def verify_bundle(bundle, private_key, output, password=None):
    output = Path(output)
    output.mkdir(mode=0o700, exist_ok=False)
    decrypt(bundle, output / "verified.tar.gz", private_key, password)
    return unpack_verified(output / "verified.tar.gz", output / "payload")


def restore_isolated(bundle, private_key, output, target, mysql_bin, password=None):
    # No option permits a remote target, the ordinary production port, or an
    # already-used database server. These checks run before opening any SQL file.
    if (os.getenv("RECOVERY_ISOLATED") != "1"
            or target.get("host") not in ("127.0.0.1", "::1")
            or type(target.get("port")) is not int
            or not 1024 <= target["port"] <= 65535 or target["port"] == 3306
            or target.get("database")):
        raise ValueError("A fresh isolated loopback instance on a non-production port is required")
    started = time.monotonic()
    connection = mysql.connector.connect(**target, connection_timeout=10)
    try:
        cursor = connection.cursor()
        cursor.execute("SHOW DATABASES")
        if {row[0] for row in cursor.fetchall()} - SYSTEM_SCHEMAS:
            raise ValueError("Restore target is not empty; no SQL was applied")
        cursor.execute("SELECT @@server_uuid, VERSION(), @@event_scheduler")
        target_uuid, version, events = cursor.fetchone()
        if str(events).upper() not in ("OFF", "DISABLED"):
            raise ValueError("Disable the isolated target event scheduler first")
        manifest = verify_bundle(bundle, private_key, output, password)
        if manifest.get("kind") != "database_and_evidence":
            raise ValueError("This bundle is not a database recovery point")
        if target_uuid == manifest["source_server_uuid"]:
            raise ValueError("Source server cannot be a restore-test target")
        if version.split(".")[0] != manifest["mysql"]["version"].split(".")[0]:
            raise ValueError("Use the same MySQL major version for the restore drill")
        database = manifest["database"]
        if not re.fullmatch(r"[a-zA-Z0-9_]{1,64}", database):
            raise ValueError("Unsupported database identifier")
        # Preserve the schema name, including any qualified view/routine names,
        # ONLY within the freshly initialized isolated server.
        cursor.execute(f"CREATE DATABASE `{database}` CHARACTER SET utf8mb4")
        target_config = {**target, "database": database}
        with client_options(Path(output), target_config) as defaults:
            with (Path(output) / "payload" / "database.sql").open("rb") as sql:
                result = subprocess.run([mysql_bin, defaults, "--binary-mode=1",
                                         "--default-character-set=utf8mb4", database],
                                        stdin=sql, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=1800,
                                        env=client_environment(Path(output)))
            if result.returncode:
                raise RuntimeError("isolated_mysql_import_failed")
        cursor.execute("SELECT TABLE_NAME FROM information_schema.tables WHERE table_schema=%s", (database,))
        names = sorted(row[0] for row in cursor.fetchall())
        if names != manifest["tables"]:
            raise ValueError("Restored table/view inventory differs from snapshot")
        for name in names:
            escaped = name.replace("`", "``")
            cursor.execute(f"CHECK TABLE `{database}`.`{escaped}`")
            for row in cursor.fetchall():
                if row[2] == "error" or (row[2] == "status" and row[3] != "OK"):
                    raise ValueError("Restored table check failed")
        cursor.execute(f"SELECT photoPath FROM `{database}`.inspection_reports WHERE photoPath IS NOT NULL")
        references, archived = referenced_files([row[0] for row in cursor.fetchall()])
        evidence = Path(output) / "payload" / "evidence"
        if any(not (evidence / name).is_file() for name in references):
            raise ValueError("Restored database references missing evidence")
        report = {
            "success": True, "isolated": True, "tested_at": status.stamp(),
            "id": manifest["id"], "environment": manifest["environment"],
            "source_server_uuid": manifest["source_server_uuid"],
            "target_server_uuid": target_uuid, "mysql_version": version,
            "bundle_sha256": sha256(bundle), "table_count": len(names),
            "payload_files_verified": len(manifest["files"]),
            "runtime_config_files_verified": sum(name.startswith("runtime-config/") for name in manifest["files"]),
            "referenced_live_files_verified": len(references),
            "legacy_archived_references_not_recovered": archived,
            "elapsed_seconds": round(time.monotonic() - started, 3),
            "scope": "Decrypt, authenticate, import SQL, check tables/views and evidence references. "
                     "Full application and real-size production drill remain separate acceptance checks.",
        }
        (Path(output) / "restore-report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        cursor.close()
        return report
    finally:
        connection.close()
