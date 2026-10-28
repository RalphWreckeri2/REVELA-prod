"""Reproducible LOCAL synthetic drill using two NEW MySQL instances.

Never reads DB_* credentials or uses an existing database service. The only
source schema is the checked-in schema reference plus synthetic rows.
"""
import argparse
import json
import os
import socket
import subprocess
import tempfile
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

import mysql.connector
from apscheduler.schedulers.background import BackgroundScheduler

from recovery.crypto import sha256
from recovery.mysqltools import client_options, client_environment
from recovery.db_export import restore_export
from recovery.db_storage import DatabaseStorage
from recovery.runner import perform
from recovery.settings import ROOT, DatabaseSettings
from recovery.testing import FixtureS3
from recovery import status


def free_port():
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


def shutdown_mysql(config, data):
    """Stop only the newly initialized instance whose data directory we own."""
    with mysql.connector.connect(**config, connection_timeout=5) as connection:
        cursor = connection.cursor()
        try:
            cursor.execute("SELECT @@datadir, @@port")
            actual_data, actual_port = cursor.fetchone()
            if Path(actual_data).resolve() != data.resolve() or actual_port != config["port"]:
                raise RuntimeError("Synthetic MySQL shutdown refused: instance identity differs")
            cursor.execute("SHUTDOWN")
        finally:
            cursor.close()


@contextmanager
def fresh_mysql(binaries, directory):
    directory.mkdir(mode=0o700)
    data = directory / "data"
    data.mkdir()
    server = binaries / ("mysqld.exe" if os.name == "nt" else "mysqld")
    initialize = subprocess.run([str(server), "--no-defaults", "--initialize-insecure",
                                 f"--datadir={data}"], capture_output=True, timeout=120)
    if initialize.returncode:
        raise RuntimeError("Synthetic MySQL initialization failed: " + initialize.stderr.decode(errors="replace"))
    port = free_port()
    log = (directory / "server.log").open("wb")
    process = subprocess.Popen([
        str(server), "--no-defaults", f"--datadir={data}", f"--port={port}",
        "--bind-address=127.0.0.1", "--mysqlx=OFF", "--skip-log-bin", "--event-scheduler=OFF",
        "--local-infile=OFF", "--secure-file-priv=NULL", "--innodb-buffer-pool-size=64M", "--console",
    ], stdout=log, stderr=log)
    config = {"host": "127.0.0.1", "port": port, "user": "root", "password": ""}
    try:
        deadline = time.monotonic() + 60
        while True:
            if process.poll() is not None:
                raise RuntimeError(f"Synthetic MySQL stopped; inspect {directory / 'server.log'}")
            try:
                with mysql.connector.connect(**config, connection_timeout=1):
                    break
            except mysql.connector.Error:
                if time.monotonic() > deadline:
                    raise RuntimeError("Synthetic MySQL did not start") from None
                time.sleep(0.25)
        yield config
    finally:
        try:
            # On Windows mysqld starts a monitor parent and a server child.
            # Terminating only Popen's PID leaves the child listening. A guarded
            # SQL shutdown reaches the exact temporary server, not a DB service.
            shutdown_mysql(config, data)
        except mysql.connector.Error:
            pass  # Startup may have failed; fall back to our own process tree.
        finally:
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                if os.name == "nt":
                    subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                                   capture_output=True, timeout=15, check=True)
                else:
                    process.kill()
                process.wait(timeout=10)
            finally:
                log.close()
            # A monitor exiting does not itself prove its server child stopped.
            deadline = time.monotonic() + 10
            while True:
                try:
                    with socket.create_connection((config["host"], config["port"]), timeout=1):
                        pass
                except OSError:
                    break
                if time.monotonic() >= deadline:
                    raise RuntimeError("Synthetic MySQL cleanup failed: temporary server still listening")
                time.sleep(0.1)


def seed(binaries, config, directory, evidence):
    database = "revela_synthetic_drill"
    with mysql.connector.connect(**config) as connection:
        cursor = connection.cursor()
        cursor.execute(f"CREATE DATABASE {database}")
        cursor.close()
    config = {**config, "database": database}
    client = binaries / ("mysql.exe" if os.name == "nt" else "mysql")
    with client_options(directory, config) as defaults:
        with (ROOT / "docs" / "schema-reference" / "current_database_structure.sql").open("rb") as sql:
            result = subprocess.run([str(client), defaults, database], stdin=sql,
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60,
                                    env=client_environment(directory))
        if result.returncode:
            raise RuntimeError("Synthetic schema import failed: " + result.stderr.decode(errors="replace"))
    name = "a" * 32 + ".jpg"
    (evidence / name).write_bytes(b"synthetic photo fixture; no municipal records")
    (evidence / ("b" * 32 + ".png")).write_bytes(b"unattached upload fixture")
    imports = evidence / ".registry-imports"
    imports.mkdir()
    (imports / "fixture.csv").write_text("businessID,businessName\nDRILL-1,Synthetic Municipal Test Shop\n", encoding="utf-8")
    with mysql.connector.connect(**config) as connection:
        cursor = connection.cursor()
        cursor.execute("INSERT INTO barangays (barangayID,barangayName) VALUES (1,'Synthetic Barangay')")
        cursor.execute("INSERT INTO users (userID,fullName,email,userRole,userPassword) "
                       "VALUES (1,'Fixture Inspector','fixture@example.invalid','Inspector','not-a-login-hash')")
        cursor.execute("INSERT INTO official_registry (businessID,businessName,barangayID) "
                       "VALUES ('DRILL-1','Synthetic Municipal Test Shop',1)")
        cursor.execute("INSERT INTO geospatial_logs (logID,barangayID,businessID,detectedName) "
                       "VALUES (1,1,'DRILL-1','Synthetic Municipal Test Shop')")
        cursor.execute("INSERT INTO inspection_reports (reportID,userID,targetID,targetType,photoPath,remarks) "
                       "VALUES (1,1,1,'geospatial',%s,'Recovery fixture record')",
                       (json.dumps([f"/api/inspections/public-evidence/{name}"]),))
        cursor.execute("CREATE VIEW drill_view AS SELECT businessID,businessName FROM official_registry")
        cursor.execute("CREATE PROCEDURE drill_record_count() SELECT COUNT(*) FROM official_registry")
        cursor.execute("CREATE TRIGGER drill_trigger BEFORE INSERT ON barangays FOR EACH ROW SET NEW.barangayName=TRIM(NEW.barangayName)")
        cursor.execute("CREATE EVENT drill_event ON SCHEDULE EVERY 1 DAY DISABLE DO SELECT 1")
        connection.commit()
        cursor.close()
    return config


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mysql-bin-dir", type=Path, required=True)
    parser.add_argument("--work-root", type=Path, required=True, help="Existing private temporary parent")
    args = parser.parse_args()
    if not args.work_root.is_dir():
        parser.error("--work-root must already exist")
    root = Path(tempfile.mkdtemp(prefix="revela-db-export-drill-", dir=args.work_root))
    evidence = root / "evidence"
    evidence.mkdir()
    extension = ".exe" if os.name == "nt" else ""
    settings = DatabaseSettings(root / "state", root, "synthetic-db-export-drill", "fixture-only",
                                "ap-southeast-1", "000000000000", "",
                                str(args.mysql_bin_dir / f"mysqldump{extension}"), "fixture-alert", "fixture-heartbeat")
    store = DatabaseStorage.__new__(DatabaseStorage)
    store.settings = settings
    store.s3 = FixtureS3(root / "test-object-store")
    signals, results, errors = [], [], []
    with fresh_mysql(args.mysql_bin_dir, root / "source-mysql") as source:
        source = seed(args.mysql_bin_dir, source, root, evidence)
        complete = threading.Event()
        def scheduled():
            try:
                results.append(perform(settings, source, store, scheduled=True,
                                       scheduled_for=status.latest_due().isoformat(),
                                       notify=lambda url, event: signals.append(event),
                                       deliver=lambda _cfg, event: {"fixture_alert": True}))
            except Exception as exc:
                errors.append(repr(exc))
            finally:
                complete.set()
        scheduler = BackgroundScheduler(timezone="Asia/Manila")
        scheduler.add_job(scheduled, "date", run_date=datetime.now(timezone.utc) + timedelta(seconds=1))
        scheduler.start()
        try:
            if not complete.wait(180) or errors:
                raise RuntimeError(f"Scheduled synthetic backup failed: {errors}")
        finally:
            scheduler.shutdown()
        receipt = results[0]
        downloaded, body = store.download(receipt["id"])
        archive = root / downloaded["filename"]
        try:
            archive.write_bytes(body.read())
        finally:
            body.close()
        assert sha256(archive) == receipt["object"]["sha256"]
        import gzip
        with gzip.open(archive, "rb") as sql:
            assert b"synthetic photo fixture; no municipal records" not in sql.read()
        (root / "receipt.json").write_text(json.dumps(receipt, indent=2), encoding="utf-8")
        with fresh_mysql(args.mysql_bin_dir, root / "restore-mysql") as target:
            os.environ["RECOVERY_ISOLATED"] = "1"
            report = restore_export(archive, receipt, root / "restored", target,
                                    str(args.mysql_bin_dir / f"mysql{extension}"))
            with mysql.connector.connect(**target, database=source["database"]) as connection:
                cursor = connection.cursor()
                cursor.execute("SELECT businessName, remarks FROM official_registry r "
                               "JOIN geospatial_logs g ON g.businessID=r.businessID "
                               "JOIN inspection_reports i ON i.targetID=g.logID")
                assert cursor.fetchone() == ("Synthetic Municipal Test Shop", "Recovery fixture record")
                for statement in ("SHOW TRIGGERS", "SHOW PROCEDURE STATUS WHERE Db=DATABASE()", "SHOW EVENTS"):
                    cursor.execute(statement)
                    assert len(cursor.fetchall()) == 1
                cursor.close()
            state = status.load(settings.state)
            state["last_restore_test"] = report
            status.save(state, settings.state)
            result = {"scheduled_fixture_backup": "passed", "isolated_mysql_restore": report,
                      "relationship_and_programmable_object_checks": "passed",
                      "backup_elapsed_seconds": state["elapsed_seconds"], "export_bytes": receipt["object"]["bytes"],
                      "export_filename": receipt["filename"], "photos_and_attachments_excluded": True,
                      "signals_recorded": len(signals), "evidence_directory": str(root),
                      "production_operational": False,
                      "limitations": "Synthetic, same-host storage and monitor doubles. AWS, Railway, real network alerts and production-size RPO/RTO not tested."}
    # Publish successful drill evidence only after both server cleanups pass.
    result["temporary_servers_stopped"] = True
    (root / "drill-summary.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
