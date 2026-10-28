"""Transactional database-only SQL exports; no filesystem evidence capture."""
import gzip
import hashlib
import os
import shutil
import subprocess
import time
from contextlib import contextmanager
from pathlib import Path

import mysql.connector

from recovery.mysqltools import run_dump, client_options, client_environment
from recovery.crypto import sha256
from recovery import status


@contextmanager
def source_lease(config):
    # An advisory lock coordinates different processes/replicas as well as the
    # local file lock. It never locks business rows or changes their contents.
    connection = mysql.connector.connect(**config)
    cursor = connection.cursor()
    name = "revela-db-export:" + hashlib.sha256(config["database"].encode()).hexdigest()[:40]
    acquired = False
    try:
        cursor.execute("SELECT GET_LOCK(%s, 0)", (name,))
        if cursor.fetchone()[0] != 1:
            from recovery.locking import LockBusy
            raise LockBusy("backup_busy")
        acquired = True
        yield connection
        cursor.execute("SELECT IS_USED_LOCK(%s) = CONNECTION_ID()", (name,))
        if cursor.fetchone()[0] != 1:
            raise RuntimeError("database_backup_lock_lost")
    finally:
        if acquired and connection.is_connected():
            cursor.execute("SELECT RELEASE_LOCK(%s)", (name,))
            cursor.fetchone()
        cursor.close()
        connection.close()


@contextmanager
def job_lease(config):
    """Serialize scheduled/manual runs through upload, status publication and pruning."""
    connection = mysql.connector.connect(**config)
    cursor = connection.cursor()
    name = "revela-db-job:" + hashlib.sha256(config["database"].encode()).hexdigest()[:40]
    acquired = False
    try:
        cursor.execute("SELECT GET_LOCK(%s, 0)", (name,))
        if cursor.fetchone()[0] != 1:
            from recovery.locking import LockBusy
            raise LockBusy("backup_busy")
        acquired = True
        yield connection
        cursor.execute("SELECT IS_USED_LOCK(%s) = CONNECTION_ID()", (name,))
        if cursor.fetchone()[0] != 1:
            raise RuntimeError("database_job_lock_lost")
    finally:
        if acquired and connection.is_connected():
            cursor.execute("SELECT RELEASE_LOCK(%s)", (name,))
            cursor.fetchone()
        cursor.close()
        connection.close()


def inventory(connection):
    cursor = connection.cursor()
    try:
        cursor.execute("SELECT VERSION(), @@server_uuid")
        version, server_uuid = cursor.fetchone()
        cursor.execute("SELECT TABLE_NAME, ENGINE FROM information_schema.tables WHERE table_schema=DATABASE()")
        tables = cursor.fetchall()
        if not tables or any(engine not in (None, "InnoDB") for _, engine in tables):
            raise ValueError("database_requires_innodb_tables")
        result = {"mysql_version": version, "source_server_uuid": server_uuid,
                  "tables": sorted(name for name, _ in tables)}
        for key, query in {
            "triggers": "SELECT TRIGGER_NAME FROM information_schema.triggers WHERE trigger_schema=DATABASE()",
            "routines": "SELECT ROUTINE_NAME FROM information_schema.routines WHERE routine_schema=DATABASE()",
            "events": "SELECT EVENT_NAME FROM information_schema.events WHERE event_schema=DATABASE()",
        }.items():
            cursor.execute(query)
            result[key] = sorted(row[0] for row in cursor.fetchall())
        return result
    finally:
        cursor.close()


def export(settings, config, work, connection):
    metadata = inventory(connection)
    # Conservative lower bound: the dump's actual transaction begins later.
    metadata["recovery_point"] = status.stamp()
    sql = work / "database.sql"
    run_dump(settings.mysqldump, config, sql, metadata["mysql_version"])
    compressed = work / "database.sql.gz"
    with sql.open("rb") as source, compressed.open("xb") as output:
        with gzip.GzipFile(filename="", mode="wb", fileobj=output, mtime=0) as gz:
            shutil.copyfileobj(source, gz, length=1024 * 1024)
        output.flush()
        os.fsync(output.fileno())
    # Verify both decompression/CRC and exact SQL bytes, not merely gzip presence.
    digest = hashlib.sha256()
    with gzip.open(compressed, "rb") as verified:
        for chunk in iter(lambda: verified.read(1024 * 1024), b""):
            digest.update(chunk)
    if digest.hexdigest() != sha256(sql):
        raise ValueError("gzip_verification_failed")
    metadata.update(database=config["database"], sql_sha256=digest.hexdigest(), sql_bytes=sql.stat().st_size)
    return compressed, metadata


def restore_export(archive, receipt, output, target, mysql_bin):
    """Restore only into a fresh isolated server, never an existing application DB."""
    import re
    import json
    from recovery.restore import SYSTEM_SCHEMAS
    if (os.getenv("RECOVERY_ISOLATED") != "1" or target.get("host") not in ("127.0.0.1", "::1")
            or type(target.get("port")) is not int or not 1024 <= target["port"] <= 65535
            or target["port"] == 3306 or target.get("database")):
        raise ValueError("fresh_isolated_loopback_target_required")
    if receipt.get("feature") != "revela-db-export-v1" or sha256(archive) != receipt["object"]["sha256"]:
        raise ValueError("export_receipt_checksum_mismatch")
    started = time.monotonic()
    with mysql.connector.connect(**target, connection_timeout=10) as connection:
        cursor = connection.cursor()
        cursor.execute("SHOW DATABASES")
        if {row[0] for row in cursor.fetchall()} - SYSTEM_SCHEMAS:
            raise ValueError("restore_target_not_empty")
        cursor.execute("SELECT @@server_uuid, VERSION(), @@event_scheduler")
        target_uuid, version, events = cursor.fetchone()
        if (target_uuid == receipt["source_server_uuid"] or str(events).upper() not in ("OFF", "DISABLED")
                or version.split(".")[0] != receipt["mysql_version"].split(".")[0]):
            raise ValueError("isolated_target_identity_version_or_events_invalid")
        cursor.execute("SELECT @@bind_address")
        if not set(str(cursor.fetchone()[0]).split(",")).issubset({"127.0.0.1", "::1", "localhost"}):
            raise ValueError("isolated_target_must_bind_loopback_only")
        database = receipt["database"]
        if not re.fullmatch(r"[A-Za-z0-9_]{1,64}", database):
            raise ValueError("invalid_schema_name")
        output = Path(output)
        output.mkdir(mode=0o700, exist_ok=False)
        sql = output / "database.sql"
        with gzip.open(archive, "rb") as source, sql.open("xb") as restored:
            shutil.copyfileobj(source, restored)
        if sha256(sql) != receipt["sql_sha256"]:
            raise ValueError("sql_checksum_mismatch")
        cursor.execute(f"CREATE DATABASE `{database}` CHARACTER SET utf8mb4")
        with client_options(output, target) as defaults, sql.open("rb") as source:
            result = subprocess.run([mysql_bin, defaults, "--binary-mode=1", database], stdin=source,
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=1800,
                                    env=client_environment(output))
        if result.returncode:
            raise RuntimeError("isolated_import_failed")
        connection.database = database
        restored_inventory = inventory(connection)
        for key in ("tables", "triggers", "routines", "events"):
            if restored_inventory[key] != receipt[key]:
                raise ValueError("restored_schema_inventory_mismatch")
        for table in restored_inventory["tables"]:
            cursor.execute(f"CHECK TABLE `{table.replace('`', '``')}`")
            if any(row[2] == "error" or (row[2] == "status" and row[3] != "OK") for row in cursor.fetchall()):
                raise ValueError("restored_table_check_failed")
        cursor.close()
    report = {"success": True, "isolated": True, "feature": receipt["feature"], "id": receipt["id"],
              "environment": receipt["environment"], "storage_identity": receipt["storage_identity"],
              "source_server_uuid": receipt["source_server_uuid"], "target_server_uuid": target_uuid,
              "bundle_sha256": sha256(archive), "tested_at": status.stamp(),
              "table_count": len(receipt["tables"]), "elapsed_seconds": round(time.monotonic() - started, 3),
              "filesystem_files_restored": False}
    (output / "restore-report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report
