import gzip
import hashlib
import io
import json
import sys
import subprocess
import types
import threading
import time
from contextlib import nullcontext
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from flask import Flask

from recovery import runner, status, db_storage, db_export, mysqltools
from recovery.db_storage import DatabaseStorage, FEATURE
from recovery.settings import DatabaseSettings
from recovery.storage import retry
from recovery.testing import FixtureS3
from recovery.locking import LockBusy


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setattr(status, "now", lambda: datetime(2026, 10, 26, 4, 30, tzinfo=timezone.utc))
    cfg = DatabaseSettings(tmp_path / "state", tmp_path, "municipal-test", "test-private-bucket",
                           "ap-southeast-1", "000000000000", "", sys.executable,
                           "https://monitor.invalid/alert", "https://monitor.invalid/cron")
    store = DatabaseStorage.__new__(DatabaseStorage)
    store.settings, store.s3 = cfg, FixtureS3(tmp_path / "storage")
    no_wait = lambda operation: retry(operation, sleep=lambda _: None)
    monkeypatch.setattr(db_storage, "retry", no_wait)
    monkeypatch.setattr(runner, "retry", no_wait)
    for key, value in {
        "BACKUP_ENVIRONMENT": cfg.environment, "BACKUP_S3_BUCKET": cfg.bucket, "AWS_REGION": cfg.region,
        "BACKUP_AWS_ACCOUNT_ID": cfg.account, "BACKUP_WORK_DIR": str(tmp_path),
        "DB_BACKUP_STATE_DIR": str(cfg.state), "MYSQLDUMP_BIN": sys.executable,
        "BACKUP_ALERT_WEBHOOK": cfg.alert_url, "BACKUP_HEARTBEAT_URL": cfg.heartbeat_url,
        "BACKUP_DB_HOST": "127.0.0.1", "BACKUP_DB_PORT": "3306",
        "BACKUP_DB_NAME": "fixture", "BACKUP_DB_USER": "backup",
        "BACKUP_DB_PASSWORD": "synthetic-only", "DB_BACKUP_ROLE": "api",
        "DB_BACKUP_SCHEDULER_MODE": "in_process",
        "DB_BACKUP_ENABLED": "1",
        "DB_BACKUP_SCHEDULE_ENABLED": "1",
    }.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(runner, "source_lease", lambda _: nullcontext(object()))
    monkeypatch.setattr(runner, "job_lease", lambda _: nullcontext(object()))
    monkeypatch.setattr(runner, "DatabaseStorage", lambda _: store)
    monkeypatch.setattr(db_storage, "DatabaseStorage", lambda _: store)
    return cfg, store


def record_at(cfg, identifier, instant, scheduled=True):
    return {"feature": FEATURE, "id": identifier, "environment": cfg.environment,
            "storage_identity": cfg.identity, "source_server_uuid": "fixture-source",
            "filename": f"revela-db_{instant.astimezone(status.MANILA):%Y%m%d_%H%M%S}_PHT_{identifier}.sql.gz",
            "completed_at": instant.isoformat(), "recovery_point": instant.isoformat(),
            "scheduled": scheduled, "scheduled_for": status.latest_due(instant).isoformat() if scheduled else None,
            "monthly_archive": bool(scheduled and status.is_monthly_archive(status.latest_due(instant).isoformat())),
            "database": "fixture", "mysql_version": "8.0.46", "tables": ["inspection_reports"],
            "triggers": [], "routines": [], "events": [], "sql_sha256": "f" * 64}


def publish_at(cfg, store, identifier, instant, monkeypatch, scheduled=True):
    work = cfg.work / identifier
    work.mkdir()
    archive = work / "database.sql.gz"
    archive.write_bytes(gzip.compress(b"CREATE TABLE fixture(id INT); INSERT INTO fixture VALUES(1);"))
    record = record_at(cfg, identifier, instant, scheduled)
    with monkeypatch.context() as scoped:
        scoped.setattr(status, "now", lambda: instant)
        store.publish(archive, record, work)
    return record


def test_retention_keeps_four_weekly_and_three_monthly_and_separates_manual(setup, monkeypatch):
    cfg, store = setup
    weekly_dates = [
        "2026-07-31", "2026-08-07", "2026-08-14", "2026-08-21", "2026-08-28",
        "2026-09-04", "2026-09-11", "2026-09-18", "2026-09-25",
        "2026-10-02", "2026-10-09", "2026-10-16", "2026-10-23", "2026-10-30",
    ]
    weekly = []
    for index, day in enumerate(weekly_dates):
        instant = datetime.fromisoformat(day + "T11:00:00+00:00")
        weekly.append(publish_at(cfg, store, f"{index + 1:032x}", instant, monkeypatch))
    old_manual = publish_at(
        cfg, store, "f" * 32, datetime.fromisoformat("2026-08-01T11:00:00+00:00"),
        monkeypatch, scheduled=False,
    )
    recent_manual = publish_at(
        cfg, store, "e" * 32, datetime.fromisoformat("2026-10-01T11:00:00+00:00"),
        monkeypatch, scheduled=False,
    )
    newest = weekly[-1]
    other = store.s3.put_object(Key="municipal-test/runs/old-official-archive.rvl", Body=io.BytesIO(b"keep"),
                                Metadata={}, ServerSideEncryption="AES256")
    removed = store.prune(newest)
    assert old_manual["id"] in removed
    remaining = {row["id"] for row in store.records()}
    kept_weekly_ids = {row["id"] for row in weekly[-4:]}
    monthly_records = [row for row in weekly if row["monthly_archive"]]
    kept_monthly_ids = {row["id"] for row in monthly_records[-3:]}
    assert remaining == kept_weekly_ids | kept_monthly_ids | {recent_manual["id"]}
    assert len(kept_weekly_ids) == 4 and len(kept_monthly_ids) == 3
    assert all(key.startswith(cfg.prefix) for key, _ in store.s3.deleted)
    assert store.s3._entry("municipal-test/runs/old-official-archive.rvl")["VersionId"] == other["VersionId"]
    receipt, body = store.download(newest["id"])
    assert hashlib.sha256(body.read()).hexdigest() == receipt["object"]["sha256"]
    body.close()


def test_last_success_is_preserved_even_when_older_than_retention(setup, monkeypatch):
    cfg, store = setup
    only = publish_at(cfg, store, "a" * 32, status.now() - timedelta(days=40), monkeypatch)
    assert store.prune(only) == []
    assert len(store.records()) == 1
    assert not store.s3.deleted


def test_monthly_archive_is_preserved_when_weekly_retention_prunes(setup, monkeypatch):
    cfg, store = setup
    monthly = publish_at(cfg, store, "e" * 32,
                         datetime(2026, 9, 25, 11, 0, tzinfo=timezone.utc), monkeypatch)
    latest = publish_at(cfg, store, "d" * 32, status.now(), monkeypatch)
    assert monthly["monthly_archive"] is True
    assert store.prune(latest) == []
    assert {row["id"] for row in store.records()} == {monthly["id"], latest["id"]}


def test_unpublished_or_tampered_receipt_cannot_prune_anything(setup, monkeypatch):
    cfg, store = setup
    old = publish_at(cfg, store, "a" * 32, status.now() - timedelta(days=20), monkeypatch)
    with pytest.raises(ValueError):
        store.prune({**old, "object": {**old["object"], "sha256": "tampered"}})
    assert not store.s3.deleted
    # A receipt cannot redirect cleanup/download to another feature's archive.
    entry = store.s3._entry(cfg.prefix + "records/" + old["id"] + ".json")
    raw = json.loads(entry["path"].read_bytes())
    raw["object"]["key"] = "unrelated/official-record.sql.gz"
    entry["path"].write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(ValueError):
        store.download(old["id"])
    assert not store.s3.deleted


@pytest.mark.parametrize("condition", ["public", "unversioned", "locked_too_long", "missing_status_lifecycle"])
def test_storage_preflight_refuses_unsuitable_storage(setup, monkeypatch, condition):
    _, store = setup
    if condition == "public":
        monkeypatch.setattr(store.s3, "get_public_access_block", lambda **_: {"PublicAccessBlockConfiguration": {}})
    elif condition == "unversioned":
        monkeypatch.setattr(store.s3, "get_bucket_versioning", lambda **_: {"Status": "Suspended"})
    elif condition == "missing_status_lifecycle":
        monkeypatch.setattr(store.s3, "get_bucket_lifecycle_configuration", lambda **_: {"Rules": []})
    else:
        monkeypatch.setattr(store.s3, "get_object_lock_configuration", lambda **_: {
            "ObjectLockConfiguration": {"Rule": {"DefaultRetention": {"Days": 35}}}})
    with pytest.raises(ValueError):
        store.preflight()


def test_failure_diagnostics_expose_configuration_reason_without_secret_messages():
    assert runner._error_details(ValueError("private_bucket_required"))["reason"] == "private_bucket_required"
    assert "sensitive-password" not in json.dumps(runner._error_details(OSError("sensitive-password")))


def test_remote_mysql_client_refuses_unverified_tls(tmp_path):
    config = {
        "host": "mysql.example.invalid",
        "port": 3306,
        "user": "backup",
        "password": "synthetic-only",
        "database": "fixture",
        "ssl_ca": str(tmp_path / "ca.pem"),
        "ssl_verify_cert": True,
        "ssl_verify_identity": False,
    }

    with pytest.raises(ValueError, match="strict_tls_configuration_required"):
        with mysqltools.client_options(tmp_path, config):
            pytest.fail("unverified remote TLS must not produce client options")

    assert not (tmp_path / ".mysql-client.cnf").exists()


def test_remote_mysql_client_uses_identity_verification(tmp_path):
    ca = tmp_path / "ca.pem"
    cert = tmp_path / "client-cert.pem"
    key = tmp_path / "client-key.pem"
    ca.write_text("synthetic public CA", encoding="utf-8")
    cert.write_text("synthetic client certificate", encoding="utf-8")
    key.write_text("synthetic client key", encoding="utf-8")
    key.chmod(0o600)
    config = {
        "host": "mysql.example.invalid",
        "port": 3306,
        "user": "backup",
        "password": "synthetic-only",
        "database": "fixture",
        "ssl_ca": str(ca),
        "ssl_cert": str(cert),
        "ssl_key": str(key),
        "ssl_verify_cert": True,
        "ssl_verify_identity": True,
    }

    with mysqltools.client_options(tmp_path, config) as defaults:
        options = (tmp_path / ".mysql-client.cnf").read_text(encoding="utf-8")
        assert defaults.startswith("--defaults-file=")
        assert 'ssl-mode="VERIFY_IDENTITY"' in options
        assert f'ssl-ca="{str(ca).replace(chr(92), chr(92) * 2)}"' in options
        assert f'ssl-cert="{str(cert).replace(chr(92), chr(92) * 2)}"' in options
        assert f'ssl-key="{str(key).replace(chr(92), chr(92) * 2)}"' in options
    assert not (tmp_path / ".mysql-client.cnf").exists()


def test_failed_mysql_dump_removes_partial_plaintext(tmp_path, monkeypatch):
    destination = tmp_path / "database.sql"
    monkeypatch.setattr(mysqltools, "check_dump_client", lambda *_: None)

    def partial_timeout(*_args, **kwargs):
        kwargs["stdout"].write(b"partial SQL")
        raise subprocess.TimeoutExpired("mysqldump", 1)

    monkeypatch.setattr(mysqltools.subprocess, "run", partial_timeout)
    config = {
        "host": "127.0.0.1",
        "port": 3306,
        "user": "backup",
        "password": "synthetic-only",
        "database": "fixture",
    }

    with pytest.raises(subprocess.TimeoutExpired):
        mysqltools.run_dump("mysqldump", config, destination, "8.0.46")

    assert not destination.exists()
    assert not (tmp_path / ".mysql-client.cnf").exists()


def test_export_aborts_when_database_inventory_changes_during_dump(setup, tmp_path, monkeypatch):
    cfg, _ = setup
    before = {
        "mysql_version": "9.7.4",
        "source_server_uuid": "source-uuid",
        "tables": ["inspection_reports"],
        "triggers": [],
        "routines": [],
        "events": [],
    }
    after = {**before, "tables": ["inspection_reports", "new_table"]}
    inventories = iter((before, after))
    monkeypatch.setattr(db_export, "inventory", lambda _: next(inventories))
    monkeypatch.setattr(
        db_export, "run_dump",
        lambda _executable, _config, destination, _version: destination.write_bytes(b"synthetic SQL"),
    )
    connection = MagicMock()

    with pytest.raises(ValueError, match="database_inventory_changed_during_export"):
        db_export.export(cfg, {"database": "fixture"}, tmp_path, connection)

    connection.commit.assert_called_once_with()
    assert not (tmp_path / "database.sql.gz").exists()


def test_existing_admin_inbox_can_report_failure_without_external_webhook(setup, monkeypatch):
    from recovery import alerts
    _ = setup
    settings = SimpleNamespace(alert_url="")
    monkeypatch.delenv("BACKUP_ALERT_WEBHOOK")
    monkeypatch.setattr(alerts, "admin_alert", lambda _: True)
    monkeypatch.setattr(alerts, "signal", lambda *_: pytest.fail("No webhook should be called"))

    result = alerts.failure_delivery(settings, {"code": "database_dump_failed"})

    assert result == {
        "admin_inbox": True,
        "external_alert": "not_configured; admin inbox is the only notification channel",
    }


def test_missing_admin_inbox_is_explicit_when_no_external_webhook(setup, monkeypatch, caplog):
    from recovery import alerts
    _ = setup
    settings = SimpleNamespace(alert_url="")
    monkeypatch.delenv("BACKUP_ALERT_WEBHOOK")
    monkeypatch.setattr(alerts, "admin_alert", lambda _: False)

    result = alerts.failure_delivery(settings, {"code": "database_dump_failed"})

    assert result["admin_inbox"] is False
    assert result["external_alert"].startswith("not_configured;")
    assert "no HTTPS endpoint and admin inbox delivery failed" in caplog.text


def test_external_webhook_is_optional_but_still_validated(setup, monkeypatch):
    from recovery.settings import configuration_issues
    monkeypatch.delenv("BACKUP_ALERT_WEBHOOK")
    assert not any("BACKUP_ALERT_WEBHOOK" in issue for issue in configuration_issues())
    monkeypatch.setenv("BACKUP_ALERT_WEBHOOK", "http://insecure.invalid")
    assert "BACKUP_ALERT_WEBHOOK must use HTTPS" in configuration_issues()


def fake_export(cfg, _config, work, _connection):
    archive = work / "database.sql.gz"
    archive.write_bytes(gzip.compress(b"consistent synthetic SQL"))
    record = record_at(cfg, "a" * 32, status.now())
    return archive, {key: record[key] for key in ("source_server_uuid", "recovery_point", "database",
                                                "mysql_version", "tables", "triggers", "routines", "events", "sql_sha256")}


def test_failed_export_retries_are_bounded_keep_previous_success_and_alert(setup, monkeypatch):
    cfg, store = setup
    monkeypatch.setattr(runner, "export", fake_export)
    notifications = MagicMock()
    deliver = MagicMock(return_value={"admin_inbox": True, "external_alert": "accepted_by_endpoint"})
    successful = runner.perform(cfg, {}, store, scheduled=True,
                                scheduled_for=status.latest_due().isoformat(), notify=notifications, deliver=deliver)
    prior_deletions = list(store.s3.deleted)
    failed = MagicMock(side_effect=OSError("private credential must not appear"))
    monkeypatch.setattr(runner, "export", failed)
    with pytest.raises(RuntimeError):
        runner.perform(cfg, {}, store, deliver=deliver)
    assert failed.call_count == 3
    saved = status.load(cfg.state)
    assert saved["last_success"]["id"] == successful["id"]
    assert saved["phase"] == "failed" and saved["failures"][-1]["admin_inbox"]
    assert "private credential" not in json.dumps(saved)
    shared = store.read_shared_status()
    assert shared["phase"] == "failed"
    assert shared["last_success"]["id"] == successful["id"]
    assert store.s3.deleted == prior_deletions
    assert notifications.call_count == 1


def test_manual_backup_does_not_mask_missed_slots_and_alerts_are_deduplicated(setup, monkeypatch):
    cfg, store = setup
    monkeypatch.setattr(runner, "export", fake_export)
    notify = MagicMock()
    runner.perform(cfg, {}, store, notify=notify, deliver=lambda *_: {})
    notify.assert_not_called()
    alert = MagicMock(return_value={"admin_inbox": True})
    runner.check_missed(cfg, deliver=alert)
    assert alert.call_count == 2
    assert all(call.args[1]["code"] == "scheduled_database_backup_missed" for call in alert.call_args_list)
    runner.check_missed(cfg, deliver=alert)
    assert alert.call_count == 2


def test_new_monitor_does_not_alert_for_slots_before_it_was_enabled(setup, monkeypatch):
    cfg, _ = setup
    started = status.now()
    status.save({"monitoring_started_at": started.isoformat()}, cfg.state)
    alert = MagicMock(return_value={"admin_inbox": True})
    runner.check_missed(cfg, deliver=alert)
    alert.assert_not_called()
    monkeypatch.setattr(status, "now", lambda: started + timedelta(days=7))
    runner.check_missed(cfg, deliver=alert)
    assert alert.call_count == 1
    runner.check_missed(cfg, deliver=alert)
    assert alert.call_count == 1


def test_source_advisory_lock_blocks_a_second_process(monkeypatch):
    # Unit-level proof of the remote lock path, in addition to real SQL drill.
    connection = MagicMock()
    connection.cursor.return_value.fetchone.return_value = (0,)
    monkeypatch.setattr(db_export.mysql.connector, "connect", lambda **_: connection)
    with pytest.raises(LockBusy):
        with db_export.source_lease({"database": "fixture"}):
            pytest.fail("overlapping source lease was granted")
    connection.close.assert_called_once()


def test_global_job_advisory_lock_spans_worker_activity(monkeypatch):
    connection = MagicMock()
    connection.cursor.return_value.fetchone.side_effect = [(1,), (1,), (1,)]
    monkeypatch.setattr(db_export.mysql.connector, "connect", lambda **_: connection)
    with db_export.job_lease({"database": "fixture"}):
        assert connection.cursor.return_value.execute.call_args_list[0].args[0] == "SELECT GET_LOCK(%s, 0)"
    assert connection.cursor.return_value.execute.call_args_list[-1].args[0] == "SELECT RELEASE_LOCK(%s)"
    connection.close.assert_called_once()


def test_global_job_advisory_lock_rejects_another_service(monkeypatch):
    connection = MagicMock()
    connection.cursor.return_value.fetchone.return_value = (0,)
    monkeypatch.setattr(db_export.mysql.connector, "connect", lambda **_: connection)
    with pytest.raises(LockBusy):
        with db_export.job_lease({"database": "fixture"}):
            pytest.fail("overlapping job lease was granted")
    connection.close.assert_called_once()


def test_shared_status_round_trip_is_versioned_and_identity_bound(setup):
    cfg, store = setup
    state = {"phase": "failed", "failures": [{"code": "database_backup_failed"}]}
    store.write_shared_status(state)
    assert store.read_shared_status() == state
    assert store.s3._entry(cfg.prefix + "control/status.json")["ServerSideEncryption"] == "AES256"


def test_admin_status_reads_worker_failure_from_shared_store(setup, monkeypatch):
    cfg, store = setup
    state = {"phase": "failed", "storage_identity": cfg.identity,
             "storage_verified_at": status.stamp(),
             "failures": [{"at": status.stamp(), "code": "database_backup_failed"}]}
    store.write_shared_status(state)
    monkeypatch.setenv("DB_BACKUP_ENABLED", "1")
    monkeypatch.setenv("DB_BACKUP_SCHEDULER_MODE", "railway_cron")
    report = status.report()
    assert report["phase"] == "failed"
    assert report["last_failure"]["code"] == "database_backup_failed"
    assert report["next_schedule"] is None
    assert report["external_trigger_configured"] is False
    assert report["automatic_execution_ready"] is False


@pytest.mark.parametrize(("local", "expected_utc"), [
    ("2026-10-23T18:59:59+08:00", "2026-10-16T11:00:00+00:00"),
    ("2026-10-23T19:00:00+08:00", "2026-10-23T11:00:00+00:00"),
    ("2026-10-24T12:00:00+08:00", "2026-10-23T11:00:00+00:00"),
    ("2026-10-29T18:59:59+08:00", "2026-10-23T11:00:00+00:00"),
])
def test_weekly_manila_slots_map_to_utc_cron(local, expected_utc):
    from datetime import datetime
    assert status.latest_due(datetime.fromisoformat(local)).isoformat() == expected_utc


@pytest.mark.parametrize(("instant", "expected_slot"), [
    ("2026-10-23T11:16:00+00:00", "2026-10-23T11:00:00+00:00"),
    ("2026-10-30T10:59:00+00:00", "2026-10-23T11:00:00+00:00"),
    ("2026-10-30T11:00:00+00:00", "2026-10-30T11:00:00+00:00"),
])
def test_external_trigger_catches_up_until_the_next_weekly_slot(
    monkeypatch, instant, expected_slot,
):
    from api.admin_settings import routes
    from recovery import settings as backup_settings

    monkeypatch.setenv("DB_BACKUP_EXTERNAL_TRIGGER_ENABLED", "1")
    monkeypatch.setenv("DB_BACKUP_TRIGGER_TOKEN", "t" * 40)
    monkeypatch.setattr(status, "now", lambda: datetime.fromisoformat(instant))
    monkeypatch.setattr(backup_settings, "configuration_issues", lambda: [])
    monkeypatch.setattr(backup_settings, "schedule_enabled", lambda: True)
    queued = []
    monkeypatch.setattr(
        runner, "start_scheduled",
        lambda _app, scheduled_for, _key: (
            queued.append(scheduled_for) or {
                "id": "a" * 32, "status": "queued", "scheduled_for": scheduled_for,
            }
        ),
    )
    app = Flask(__name__)
    with app.test_request_context(
        "/api/admin-settings/database-backup/trigger",
        method="POST",
        headers={
            "Authorization": "Bearer " + "t" * 40,
            "Idempotency-Key": "gha-delayed-run",
        },
    ):
        response, code = routes.database_backup_trigger_route()

    assert code == 202
    assert response.get_json()["scheduled_for"] == expected_slot
    assert queued == [expected_slot]


def test_scheduled_cli_runs_only_for_worker_during_slot_grace(setup, monkeypatch, capsys):
    from recovery import cli
    monkeypatch.setitem(sys.modules, "config", types.ModuleType("config"))
    monkeypatch.setenv("DB_BACKUP_ENABLED", "1")
    monkeypatch.setenv("DB_BACKUP_MODE", "cloud")
    monkeypatch.setenv("DB_BACKUP_ROLE", "worker")
    monkeypatch.setenv("DB_BACKUP_SCHEDULER_MODE", "railway_cron")
    monkeypatch.setattr(status, "now", lambda: datetime(2026, 10, 23, 11, 10, tzinfo=timezone.utc))
    run = MagicMock(return_value={"id": "a" * 32})
    monkeypatch.setattr(runner, "run", run)
    monkeypatch.setattr(sys, "argv", ["recovery.cli", "scheduled-run"])
    cli.main()
    run.assert_called_once_with(scheduled=True, scheduled_for="2026-10-23T11:00:00+00:00")
    assert json.loads(capsys.readouterr().out)["id"] == "a" * 32

    run.reset_mock()
    monkeypatch.setattr(status, "now", lambda: datetime(2026, 10, 23, 11, 16, tzinfo=timezone.utc))
    with pytest.raises(SystemExit):
        cli.main()
    run.assert_not_called()


def test_strict_tls_preflight_is_read_only_and_requires_identity_verification(monkeypatch, tmp_path):
    from recovery import mysqltools

    calls = []
    ca = tmp_path / "ca.pem"
    cert = tmp_path / "client-cert.pem"
    key = tmp_path / "client-key.pem"
    ca.write_text("synthetic CA", encoding="utf-8")
    cert.write_text("synthetic client certificate", encoding="utf-8")
    key.write_text("synthetic client key", encoding="utf-8")
    key.chmod(0o600)

    class Cursor:
        def execute(self, query):
            calls.append(query)

        def fetchone(self):
            return ("9.7.2",) if calls[-1] == "SELECT VERSION()" else ("Ssl_cipher", "TLS_AES_256_GCM_SHA384")

        def close(self):
            calls.append("cursor_closed")

    class Connection:
        def cursor(self):
            return Cursor()

        def close(self):
            calls.append("connection_closed")

    config = {
        "host": "mysql.internal",
        "ssl_ca": str(ca),
        "ssl_cert": str(cert),
        "ssl_key": str(key),
        "ssl_verify_cert": True,
        "ssl_verify_identity": True,
    }
    monkeypatch.setattr(mysqltools, "source_config", lambda: config)
    monkeypatch.setattr(mysqltools.mysql.connector, "connect",
                        lambda **options: (calls.append(options) or Connection()))

    result = mysqltools.strict_tls_preflight()

    assert calls[0]["ssl_verify_cert"] is True
    assert calls[0]["ssl_verify_identity"] is True
    assert calls[0]["ssl_cert"] == str(cert)
    assert calls[0]["ssl_key"] == str(key)
    assert calls[1:] == [
        "SELECT VERSION()",
        "SHOW SESSION STATUS LIKE 'Ssl_cipher'",
        "cursor_closed",
        "connection_closed",
    ]
    assert result == {
        "mysql_version": "9.7.2",
        "tls_cipher": "TLS_AES_256_GCM_SHA384",
        "certificate_verified": True,
        "hostname_verified": True,
    }


@pytest.mark.parametrize("changes", [
    {"host": "127.0.0.1"},
    {"ssl_ca": ""},
    {"ssl_cert": ""},
    {"ssl_key": ""},
    {"ssl_verify_cert": False},
    {"ssl_verify_identity": False},
])
def test_strict_tls_preflight_refuses_unverified_connections(monkeypatch, changes):
    from recovery import mysqltools

    config = {
        "host": "mysql.internal",
        "ssl_ca": "synthetic-ca.pem",
        "ssl_cert": "synthetic-client-cert.pem",
        "ssl_key": "synthetic-client-key.pem",
        "ssl_verify_cert": True,
        "ssl_verify_identity": True,
    }
    config.update(changes)
    connected = []
    monkeypatch.setattr(mysqltools, "source_config", lambda: config)
    monkeypatch.setattr(mysqltools.mysql.connector, "connect",
                        lambda **options: connected.append(options))

    with pytest.raises(ValueError, match="strict_tls_configuration_required"):
        mysqltools.strict_tls_preflight()

    assert connected == []


def test_remote_tls_rejects_group_or_world_readable_client_key(tmp_path):
    ca = tmp_path / "ca.pem"
    cert = tmp_path / "client-cert.pem"
    key = tmp_path / "client-key.pem"
    for path in (ca, cert, key):
        path.write_text("synthetic TLS material", encoding="utf-8")
    key.chmod(0o644)
    config = {
        "host": "mysql.internal",
        "ssl_ca": str(ca),
        "ssl_cert": str(cert),
        "ssl_key": str(key),
        "ssl_verify_cert": True,
        "ssl_verify_identity": True,
    }

    if mysqltools.os.name == "nt":
        pytest.skip("POSIX mode bits are enforced by the deployed Linux runtime")

    with pytest.raises(ValueError, match="backup_client_key_permissions_invalid"):
        mysqltools._require_remote_tls(config)


def test_tls_preflight_cli_does_not_print_exception_text(monkeypatch, capsys):
    from recovery import cli, mysqltools

    monkeypatch.setattr(sys, "argv", ["recovery.cli", "tls-preflight"])
    monkeypatch.setattr(mysqltools, "strict_tls_preflight",
                        lambda: (_ for _ in ()).throw(RuntimeError("synthetic-secret-text")))

    assert cli.main() == 1
    output = capsys.readouterr().out
    assert json.loads(output) == {"success": False, "error_type": "RuntimeError"}
    assert "synthetic-secret-text" not in output


@pytest.mark.parametrize("command", ["run", "scheduled-run"])
def test_cli_disabled_mode_never_starts_manual_or_scheduled_job(setup, monkeypatch, capsys, command):
    from recovery import cli
    monkeypatch.setitem(sys.modules, "config", types.ModuleType("config"))
    monkeypatch.setenv("DB_BACKUP_ENABLED", "0")
    monkeypatch.setenv("DB_BACKUP_ROLE", "worker")
    monkeypatch.setenv("DB_BACKUP_SCHEDULER_MODE", "railway_cron")
    run = MagicMock(side_effect=AssertionError("disabled CLI must not invoke the runner"))
    monkeypatch.setattr(runner, "run", run)
    monkeypatch.setattr(sys, "argv", ["recovery.cli", command])
    assert cli.main() == 1
    assert json.loads(capsys.readouterr().out) == {
        "success": False, "status": "disabled", "reason": "database_backups_disabled"}
    run.assert_not_called()


def test_runner_disabled_mode_blocks_direct_manual_and_scheduled_calls(setup, monkeypatch):
    monkeypatch.setenv("DB_BACKUP_ENABLED", "0")
    source = MagicMock(side_effect=AssertionError("disabled runner must not inspect source configuration"))
    storage = MagicMock(side_effect=AssertionError("disabled runner must not access storage"))
    monkeypatch.setattr(runner, "source_config", source)
    monkeypatch.setattr(runner, "DatabaseStorage", storage)
    with pytest.raises(runner.DatabaseBackupDisabled, match="database_backups_disabled"):
        runner.run()
    with pytest.raises(runner.DatabaseBackupDisabled, match="database_backups_disabled"):
        runner.run(scheduled=True, scheduled_for="2026-10-25T23:00:00+00:00")
    source.assert_not_called()
    storage.assert_not_called()


def test_scheduled_cli_failure_is_nonzero_and_does_not_print_exception_text(setup, monkeypatch, capsys):
    from recovery import cli
    monkeypatch.setitem(sys.modules, "config", types.ModuleType("config"))
    monkeypatch.setenv("DB_BACKUP_ENABLED", "1")
    monkeypatch.setenv("DB_BACKUP_MODE", "cloud")
    monkeypatch.setenv("DB_BACKUP_ROLE", "worker")
    monkeypatch.setenv("DB_BACKUP_SCHEDULER_MODE", "railway_cron")
    monkeypatch.setattr(status, "now", lambda: datetime(2026, 10, 23, 11, 10, tzinfo=timezone.utc))
    monkeypatch.setattr(runner, "run", MagicMock(side_effect=RuntimeError("credential-bearing error")))
    monkeypatch.setattr(sys, "argv", ["recovery.cli", "scheduled-run"])
    assert cli.main() == 1
    output = capsys.readouterr().out
    assert "RuntimeError" in output
    assert "credential-bearing error" not in output


def test_manual_job_reservation_rejects_overlap_without_transferring_locks(setup, monkeypatch):
    _, _ = setup
    app = Flask(__name__)
    entered, release, finished = threading.Event(), threading.Event(), threading.Event()
    caller_thread = threading.get_ident()
    worker_threads = []
    def held(actor):
        worker_threads.append(threading.get_ident())
        assert actor == 7
        entered.set()
        assert release.wait(5)
        finished.set()
    monkeypatch.setattr(runner, "run", held)
    runner.start_manual(app, actor=7)
    assert entered.wait(3)
    try:
        with pytest.raises(LockBusy):
            runner.start_manual(app, actor=7)
    finally:
        release.set()
        assert finished.wait(3)
    assert worker_threads and worker_threads[0] != caller_thread
    assert not runner._manual_reservation.locked()


def test_manual_reservation_releases_after_worker_failure(setup, monkeypatch):
    app = Flask(__name__)
    entered, finished = threading.Event(), threading.Event()
    calls = []

    def fail_then_succeed(actor):
        calls.append((actor, threading.get_ident()))
        if len(calls) == 1:
            entered.set()
            raise RuntimeError("synthetic worker failure")
        finished.set()

    monkeypatch.setattr(runner, "run", fail_then_succeed)
    runner.start_manual(app, actor=7)
    assert entered.wait(3)
    deadline = time.monotonic() + 3
    while runner._manual_reservation.locked() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert not runner._manual_reservation.locked()
    runner.start_manual(app, actor=8)
    assert finished.wait(3)
    assert [actor for actor, _ in calls] == [7, 8]


def test_external_scheduled_trigger_is_durable_idempotent_and_releases_reservation(setup, monkeypatch):
    cfg, store = setup
    monkeypatch.setenv("DB_BACKUP_EXTERNAL_TRIGGER_ENABLED", "1")
    monkeypatch.setenv("DB_BACKUP_TRIGGER_TOKEN", "t" * 40)
    monkeypatch.setattr(runner.DatabaseSettings, "from_env", classmethod(lambda _cls: cfg))
    monkeypatch.setattr(runner, "DatabaseStorage", lambda _settings: store)
    started = []

    class DeferredThread:
        def __init__(self, target, **_kwargs):
            self.target = target

        def start(self):
            started.append(self.target)

    monkeypatch.setattr(runner.threading, "Thread", DeferredThread)
    monkeypatch.setattr(runner, "run", lambda **_kwargs: {"id": "a" * 32})
    app = Flask(__name__)
    scheduled_for = "2026-10-30T11:00:00+00:00"

    job = runner.start_scheduled(app, scheduled_for, "gh-run-123-1")
    assert job["status"] == "queued"
    assert status.load(cfg.state)["trigger_job"]["id"] == job["id"]
    assert store.read_shared_status()["trigger_job"]["id"] == job["id"]

    duplicate = runner.start_scheduled(app, scheduled_for, "gh-run-123-1")
    assert duplicate["id"] == job["id"]
    assert len(started) == 1
    with pytest.raises(LockBusy):
        runner.start_scheduled(app, scheduled_for, "gh-run-124-1")

    started[0]()
    completed = status.load(cfg.state)["trigger_job"]
    assert completed["status"] == "completed"
    assert completed["backup_id"] == "a" * 32
    assert not runner._manual_reservation.locked()
    same_slot_retry = runner.start_scheduled(app, scheduled_for, "gh-run-124-1")
    assert same_slot_retry["id"] == job["id"]
    assert len(started) == 1


def test_external_scheduled_trigger_stays_disabled_without_all_gates(setup, monkeypatch):
    monkeypatch.setenv("DB_BACKUP_ENABLED", "0")
    monkeypatch.setenv("DB_BACKUP_SCHEDULE_ENABLED", "0")
    with pytest.raises(runner.DatabaseBackupDisabled, match="database_backups_disabled"):
        runner.start_scheduled(Flask(__name__), "2026-10-30T11:00:00+00:00", "run-1")
    assert not runner._manual_reservation.locked()


class ThreadBoundConnection:
    def __init__(self):
        self.owner = threading.get_ident()
        self.operations = []
        self.db_cursor = ThreadBoundCursor(self)
        self.closed = False

    def _record(self, operation):
        assert threading.get_ident() == self.owner
        self.operations.append(operation)

    def cursor(self):
        self._record("cursor")
        return self.db_cursor

    def is_connected(self):
        self._record("is_connected")
        return not self.closed

    def close(self):
        self._record("connection_close")
        self.closed = True


class ThreadBoundCursor:
    def __init__(self, connection):
        self.connection = connection

    def execute(self, query, _params=None):
        self.connection._record(query)

    def fetchone(self):
        self.connection._record("fetchone")
        return (1,)

    def close(self):
        self.connection._record("cursor_close")


@pytest.mark.parametrize("export_fails", [False, True])
def test_manual_job_acquires_executes_and_releases_db_lock_in_worker_thread(
        setup, monkeypatch, export_fails):
    cfg, store = setup
    connections = []
    def connect(**_):
        connection = ThreadBoundConnection()
        connections.append(connection)
        return connection
    finished = threading.Event()
    errors = []
    monkeypatch.setattr(db_export.mysql.connector, "connect", connect)
    monkeypatch.setattr(runner, "job_lease", db_export.job_lease)
    monkeypatch.setattr(runner, "source_config", lambda: {"database": "fixture"})
    monkeypatch.setattr(runner, "failure_delivery", lambda *_: {"admin_inbox": False})
    original_perform = runner.perform
    monkeypatch.setattr(
        runner, "perform",
        lambda *args, **kwargs: original_perform(*args, **kwargs, deliver=lambda *_: {}))
    if export_fails:
        monkeypatch.setattr(runner, "export", MagicMock(side_effect=RuntimeError("synthetic export failure")))
    else:
        monkeypatch.setattr(runner, "export", fake_export)
    original_run = runner.run

    def observed_run(actor):
        try:
            return original_run(actor=actor)
        except Exception as exc:
            errors.append(exc)
        finally:
            finished.set()

    monkeypatch.setattr(runner, "run", observed_run)
    runner.start_manual(Flask(__name__), actor=7)
    assert finished.wait(5)
    if export_fails:
        assert len(errors) == 1
        assert str(errors[0]) == "database_backup_failed"
    else:
        assert errors == []
    assert len(connections) == 1
    connection = connections[0]
    assert connection.closed
    assert "SELECT GET_LOCK(%s, 0)" in connection.operations
    assert "SELECT RELEASE_LOCK(%s)" in connection.operations
    assert not runner._manual_reservation.locked()
    if not export_fails:
        assert store.read_shared_status()["phase"] == "succeeded"
    else:
        assert store.read_shared_status()["phase"] == "failed"


def auth_client(monkeypatch, role="Admin", authenticated=True):
    from api.admin_settings import routes
    from api.admin_settings.routes import admin_settings_bp
    from api.middleware import decorators
    app = Flask(__name__)
    app.register_blueprint(admin_settings_bp, url_prefix="/api/admin-settings")
    def verify():
        if not authenticated:
            raise RuntimeError("unauthenticated")
    monkeypatch.setattr(decorators, "verify_jwt_in_request", verify)
    monkeypatch.setattr(decorators, "get_jwt_identity", lambda: "7")
    monkeypatch.setattr(routes, "get_jwt_identity", lambda: "7")
    monkeypatch.setattr(decorators, "get_jwt", lambda: {"role": role})
    monkeypatch.setattr(decorators, "find_user_by_id", lambda _: {"isActive": True})
    monkeypatch.setattr(decorators, "check_active_session", lambda *_: (True, None))
    return app.test_client()


@pytest.mark.parametrize("role,authenticated,expected", [("Inspector", True, 403), ("Admin", False, 401)])
def test_all_backup_actions_are_server_authorized(setup, monkeypatch, role, authenticated, expected):
    client = auth_client(monkeypatch, role, authenticated)
    start, download = MagicMock(), MagicMock()
    monkeypatch.setattr(runner, "start_manual", start)
    monkeypatch.setattr(DatabaseStorage, "download", download)
    assert client.get("/api/admin-settings/backups").status_code == expected
    assert client.get("/api/admin-settings/database-backup/status").status_code == expected
    assert client.post("/api/admin-settings/backups/run").status_code == expected
    assert client.get("/api/admin-settings/backups/" + "a" * 32 + "/download").status_code == expected
    start.assert_not_called()
    download.assert_not_called()


def test_admin_manual_and_private_stream_download(setup, monkeypatch):
    cfg, store = setup
    client = auth_client(monkeypatch)
    start = MagicMock()
    monkeypatch.setattr(runner, "start_manual", start)
    assert client.post("/api/admin-settings/backups/run").status_code == 202
    assert start.call_args.args[1] == 7
    record = publish_at(cfg, store, "a" * 32, status.now(), monkeypatch)
    download = store.download
    monkeypatch.setattr(DatabaseStorage, "download", lambda _self, identifier: download(identifier))
    response = client.get(f"/api/admin-settings/backups/{record['id']}/download")
    assert response.status_code == 200
    assert gzip.decompress(response.data).startswith(b"CREATE TABLE")
    assert response.headers["Cache-Control"] == "private, no-store"
    assert response.headers["X-Backup-SHA256"] == hashlib.sha256(response.data).hexdigest()
    assert record["filename"] in response.headers["Content-Disposition"]
    assert client.get("/api/admin-settings/backups/not-an-id/download").status_code == 404


def test_external_trigger_and_bounded_poll_endpoints_require_bearer_auth(setup, monkeypatch):
    cfg, _store = setup
    client = auth_client(monkeypatch)
    token = "trigger-token-fixture-" + ("x" * 24)
    monkeypatch.setenv("DB_BACKUP_ENABLED", "1")
    monkeypatch.setenv("DB_BACKUP_SCHEDULE_ENABLED", "1")
    monkeypatch.setenv("DB_BACKUP_EXTERNAL_TRIGGER_ENABLED", "1")
    monkeypatch.setenv("DB_BACKUP_TRIGGER_TOKEN", token)
    monkeypatch.setattr(status, "now", lambda: datetime(2026, 10, 30, 11, 3, tzinfo=timezone.utc))
    monkeypatch.setattr("recovery.settings.configuration_issues", lambda: [])
    job = {
        "id": "a" * 32,
        "status": "queued",
        "scheduled_for": "2026-10-30T11:00:00+00:00",
        "requested_at": "2026-10-30T11:03:00+00:00",
    }
    start = MagicMock(return_value=job)
    monkeypatch.setattr(runner, "start_scheduled", start)
    path = "/api/admin-settings/database-backup/trigger"

    assert client.post(path).status_code == 401
    assert client.post(path, headers={"Authorization": "Bearer wrong-token"}).status_code == 401
    assert client.post(path, headers={"Authorization": f"Bearer {token}"}).status_code == 400
    response = client.post(path, headers={
        "Authorization": f"Bearer {token}",
        "Idempotency-Key": "gha-42-1",
    })
    assert response.status_code == 202
    assert response.headers["Cache-Control"] == "private, no-store"
    assert response.json["job_id"] == job["id"]
    assert isinstance(start.call_args.args[0], Flask)
    assert start.call_args.args[1:] == ("2026-10-30T11:00:00+00:00", "gha-42-1")

    monkeypatch.setattr(runner.DatabaseSettings, "from_env", classmethod(lambda _cls: cfg))
    status.save({"trigger_job": job}, cfg.state)
    poll_path = path + "/" + job["id"]
    assert client.get(poll_path).status_code == 401
    polled = client.get(poll_path, headers={"Authorization": f"Bearer {token}"})
    assert polled.status_code == 200
    assert polled.headers["Cache-Control"] == "private, no-store"
    assert polled.json["status"] == "queued"
    assert client.get(path + "/not-an-id", headers={"Authorization": f"Bearer {token}"}).status_code == 404


def test_panel_status_exposes_history_and_keeps_automatic_schedule_disabled(setup, monkeypatch):
    client = auth_client(monkeypatch)
    monkeypatch.setenv("DB_BACKUP_ENABLED", "1")
    monkeypatch.setenv("DB_BACKUP_SCHEDULE_ENABLED", "0")
    response = client.get("/api/admin-settings/database-backup/status")
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "private, no-store"
    assert response.json["status"] == "ready"
    assert response.json["configured"] is True
    assert response.json["canManualBackup"] is True
    assert response.json["schedule"]["configured"] is True
    assert response.json["schedule"]["enabled"] is False
    assert response.json["schedule"]["nextRunAt"] is None
    assert response.json["history"] == []


def test_panel_status_reports_enabled_schedule_separately_from_readiness(setup, monkeypatch):
    client = auth_client(monkeypatch)
    monkeypatch.setenv("DB_BACKUP_ENABLED", "1")
    monkeypatch.setenv("DB_BACKUP_SCHEDULE_ENABLED", "1")
    monkeypatch.setenv("DB_BACKUP_EXTERNAL_TRIGGER_ENABLED", "0")

    response = client.get("/api/admin-settings/database-backup/status")

    assert response.status_code == 200
    assert response.json["schedule"]["enabled"] is True
    assert response.json["schedule"]["executionReady"] is False
    assert response.json["automaticExecutionStatus"] == "not_ready"
    assert response.json["externalTriggerConfigured"] is False
    assert response.json["schedule"]["nextRunAt"] is None


def test_admin_manual_backup_is_blocked_when_global_switch_is_disabled(setup, monkeypatch):
    client = auth_client(monkeypatch)
    monkeypatch.setenv("DB_BACKUP_ENABLED", "0")
    start = MagicMock(side_effect=AssertionError("disabled API must not start a job"))
    monkeypatch.setattr(runner, "start_manual", start)
    response = client.post("/api/admin-settings/backups/run")
    assert response.status_code == 409
    assert response.json == {
        "error": "Database backups are disabled.",
        "status": "disabled",
        "reason": "database_backups_disabled",
    }
    start.assert_not_called()


def test_missing_configuration_blocks_manual_and_scheduler(setup, monkeypatch):
    client = auth_client(monkeypatch)
    monkeypatch.delenv("BACKUP_S3_BUCKET")
    monkeypatch.setenv("DB_BACKUP_ENABLED", "1")
    response = client.post("/api/admin-settings/backups/run")
    assert response.status_code == 503
    assert "Missing BACKUP_S3_BUCKET" in response.json["configuration_issues"]
    scheduler = MagicMock()
    monkeypatch.setattr(runner, "BackgroundScheduler", scheduler)
    monkeypatch.setattr(runner, "failure_delivery", lambda *_: {"admin_inbox": True})
    runner.start_scheduler(client.application)
    reporter = client.application.extensions.get("database_backup_config_reporter")
    if reporter:
        reporter.join(timeout=3)
        assert not reporter.is_alive()
    scheduler.assert_not_called()
    assert not client.get("/api/admin-settings/backups").json["operational"]


@pytest.mark.parametrize("storage_ok", [True, False])
def test_deployed_scheduler_is_registered_only_after_storage_preflight(setup, monkeypatch, storage_ok):
    cfg, store = setup
    monkeypatch.setenv("DB_BACKUP_ENABLED", "1")
    monkeypatch.setattr(runner, "DatabaseStorage", lambda _: store)
    monkeypatch.setattr(runner, "inventory", lambda _: {"mysql_version": "8.0.46"})
    monkeypatch.setattr(runner, "check_dump_client", lambda *_: None)
    monkeypatch.setattr(runner, "check_missed", lambda *_: None)
    monkeypatch.setattr(runner, "run", lambda **_: None)
    alerts = MagicMock(return_value={"admin_inbox": True})
    monkeypatch.setattr(runner, "failure_delivery", alerts)
    if not storage_ok:
        monkeypatch.setattr(store, "preflight", MagicMock(side_effect=OSError("fixture storage unavailable")))
    app = Flask(__name__)
    runner.start_scheduler(app)
    scheduler = app.extensions["database_backup_scheduler"]
    try:
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            state = status.load(cfg.state)
            if (storage_ok and scheduler.get_job("database_exports")) or state.get("phase") == "storage_preflight_failed":
                break
            time.sleep(0.02)
        if storage_ok:
            assert {job.id for job in scheduler.get_jobs()} == {"database_exports", "database_backup_watchdog"}
            assert "day_of_week='fri'" in str(scheduler.get_job("database_exports").trigger)
            assert "hour='19'" in str(scheduler.get_job("database_exports").trigger)
            assert status.load(cfg.state)["storage_verified_at"]
        else:
            assert scheduler.get_job("database_exports") is None
            assert alerts.call_args.args[1]["code"] == "backup_storage_preflight_failed"
    finally:
        scheduler.shutdown(wait=True)


@pytest.mark.parametrize(("role", "mode"), [
    ("api", "railway_cron"), ("api", "external_api"), ("worker", "in_process"),
])
def test_execution_roles_never_start_duplicate_schedulers(setup, monkeypatch, role, mode):
    monkeypatch.setenv("DB_BACKUP_ENABLED", "1")
    monkeypatch.setenv("DB_BACKUP_SCHEDULER_MODE", mode)
    monkeypatch.setenv("DB_BACKUP_ROLE", role)
    scheduler_factory = MagicMock(side_effect=AssertionError("API must not schedule duplicate runs"))
    monkeypatch.setattr(runner, "BackgroundScheduler", scheduler_factory)
    app = Flask(__name__)
    runner.start_scheduler(app)
    assert "database_backup_scheduler" not in app.extensions


def test_cleanup_stays_disabled_unless_explicitly_enabled(setup, monkeypatch):
    _, store = setup
    monkeypatch.setenv("DB_BACKUP_CLEANUP_ENABLED", "0")
    prune = MagicMock(wraps=store.prune)
    monkeypatch.setattr(store, "prune", prune)
    monkeypatch.setattr(runner, "export", fake_export)
    runner.perform(
        store.settings, {}, store, scheduled=True,
        scheduled_for="2026-10-23T11:00:00+00:00",
        notify=MagicMock(), deliver=MagicMock(return_value={}),
    )
    prune.assert_not_called()


def test_cleanup_runs_only_when_explicitly_enabled(setup, monkeypatch):
    _, store = setup
    monkeypatch.setenv("DB_BACKUP_CLEANUP_ENABLED", "1")
    prune = MagicMock(wraps=store.prune)
    monkeypatch.setattr(store, "prune", prune)
    monkeypatch.setattr(runner, "export", fake_export)

    record = runner.perform(
        store.settings, {}, store, scheduled=True,
        scheduled_for="2026-10-23T11:00:00+00:00",
        notify=MagicMock(), deliver=MagicMock(return_value={}),
    )

    prune.assert_called_once_with(record)


def test_disabled_mode_does_not_bootstrap_or_schedule_backup(setup, monkeypatch):
    monkeypatch.setenv("DB_BACKUP_ENABLED", "0")
    scheduler_factory = MagicMock(side_effect=AssertionError("disabled mode must not create a scheduler"))
    storage_factory = MagicMock(side_effect=AssertionError("disabled mode must not preflight storage"))
    monkeypatch.setattr(runner, "BackgroundScheduler", scheduler_factory)
    monkeypatch.setattr(runner, "DatabaseStorage", storage_factory)
    app = Flask(__name__)
    runner.start_scheduler(app)
    scheduler_factory.assert_not_called()
    storage_factory.assert_not_called()


def test_manual_execution_switch_does_not_enable_automatic_schedule(setup, monkeypatch):
    monkeypatch.setenv("DB_BACKUP_ENABLED", "1")
    monkeypatch.setenv("DB_BACKUP_SCHEDULE_ENABLED", "0")
    scheduler_factory = MagicMock(side_effect=AssertionError("automatic schedule must remain disabled"))
    monkeypatch.setattr(runner, "BackgroundScheduler", scheduler_factory)
    app = Flask(__name__)
    runner.start_scheduler(app)
    scheduler_factory.assert_not_called()
    assert "database_backup_scheduler" not in app.extensions


def test_scheduled_run_is_blocked_when_manual_only_switch_is_enabled(setup, monkeypatch):
    monkeypatch.setenv("DB_BACKUP_ENABLED", "1")
    monkeypatch.setenv("DB_BACKUP_SCHEDULE_ENABLED", "0")
    source = MagicMock(side_effect=AssertionError("automatic export must remain blocked"))
    storage = MagicMock(side_effect=AssertionError("automatic export must remain blocked"))
    monkeypatch.setattr(runner, "source_config", source)
    monkeypatch.setattr(runner, "DatabaseStorage", storage)
    with pytest.raises(runner.DatabaseBackupDisabled, match="automatic_database_backups_disabled"):
        runner.run(scheduled=True, scheduled_for="2026-10-30T11:00:00+00:00")
    source.assert_not_called()
    storage.assert_not_called()


def test_in_process_scheduler_is_not_reported_ready_for_automatic_backups(setup, monkeypatch):
    cfg, store = setup
    monkeypatch.setenv("DB_BACKUP_ENABLED", "1")
    scheduled = publish_at(cfg, store, "a" * 32, status.now(), monkeypatch)
    state = {"storage_identity": cfg.identity, "storage_verified_at": status.stamp(),
             "phase": "succeeded", "last_success": scheduled, "last_scheduled_success": scheduled,
             "files": [scheduled]}
    status.save(state, cfg.state)
    store.write_shared_status(state)
    assert not status.report()["operational"]  # a cached ledger is not a running scheduler
    app = Flask(__name__)
    app.extensions["database_backup_scheduler"] = SimpleNamespace(running=True, get_job=lambda _: object())
    app.extensions["database_backup_scheduler_started_at"] = (status.now() - timedelta(minutes=1)).isoformat()
    with app.app_context():
        assert not status.report()["operational"]
        state["last_restore_test"] = {"success": True, "isolated": True, "tested_at": status.stamp(),
                                      "storage_identity": cfg.identity, "source_server_uuid": "fixture-source"}
        status.save(state, cfg.state)
        store.write_shared_status(state)
        report = status.report()
        assert report["scheduler_running"] is True
        assert report["external_trigger_configured"] is False
        assert report["automatic_execution_ready"] is False
        assert report["operational"] is False
        committed = store.records()[0]
        store.s3.delete_object(Key=committed["object"]["key"], VersionId=committed["object"]["version_id"])
        store.s3.delete_object(
            Key=cfg.prefix + "records/" + committed["id"] + ".json",
            VersionId=committed["receipt_version_id"],
        )
        assert not status.report()["operational"]


@pytest.mark.parametrize("target", [
    {"host": "production.invalid", "port": 33079}, {"host": "127.0.0.1", "port": 3306},
    {"host": "127.0.0.1", "port": 33079, "database": "production"},
])
def test_sql_gzip_restore_refuses_production_or_existing_targets(setup, monkeypatch, target):
    cfg, _ = setup
    monkeypatch.setenv("RECOVERY_ISOLATED", "1")
    connect = MagicMock()
    monkeypatch.setattr(db_export.mysql.connector, "connect", connect)
    with pytest.raises(ValueError):
        db_export.restore_export(cfg.work / "does-not-exist.sql.gz", {}, cfg.work / "out", target, "mysql")
    connect.assert_not_called()


@pytest.mark.parametrize("different", ["data_directory", "port"])
def test_synthetic_mysql_shutdown_refuses_a_different_instance(tmp_path, monkeypatch, different):
    from recovery.drill_fixture import shutdown_mysql
    connection = MagicMock()
    connection.__enter__.return_value = connection
    cursor = connection.cursor.return_value
    data = tmp_path / "owned-synthetic-data"
    actual_data = tmp_path / "another-instance" if different == "data_directory" else data
    cursor.fetchone.return_value = (str(actual_data), 33080 if different == "port" else 33079)
    monkeypatch.setattr(db_export.mysql.connector, "connect", lambda **_: connection)
    with pytest.raises(RuntimeError, match="instance identity differs"):
        shutdown_mysql({"host": "127.0.0.1", "port": 33079}, data)
    assert [call.args[0] for call in cursor.execute.call_args_list] == ["SELECT @@datadir, @@port"]


def test_admin_inbox_alert_uses_existing_notification_table(monkeypatch):
    from recovery.alerts import admin_alert
    import app as backend
    from api.notifications import service, hub
    cursor = MagicMock()
    cursor.fetchall.return_value = [{"userID": 1}, {"userID": 2}]
    connection = MagicMock()
    connection.cursor.return_value = cursor
    monkeypatch.setattr(backend, "mysql", SimpleNamespace(connection=connection))
    monkeypatch.setattr(service, "_ensure_tables", lambda: None)
    monkeypatch.setattr(hub, "publish_to_admins", MagicMock())
    with Flask(__name__).app_context():
        assert admin_alert({"code": "scheduled_database_backup_missed"})
    inserts = [call for call in cursor.execute.call_args_list if call.args[0].startswith("INSERT")]
    assert len(inserts) == 2
    assert all("revela_notifications" in call.args[0] for call in inserts)
    connection.commit.assert_called_once()
