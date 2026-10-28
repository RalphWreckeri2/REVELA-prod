import gzip
import hashlib
import os
import stat
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path

import pytest

from recovery import status
from recovery.db_export import restore_export
from recovery.db_storage import BackupNotFound, DatabaseStorage, FEATURE
from recovery.locking import LockBusy, lock
from recovery.settings import DatabaseSettings, configuration_issues
from recovery.volume_storage import VolumeDatabaseStorage


@pytest.fixture
def volume_storage(tmp_path, monkeypatch):
    mount = tmp_path / "railway-volume"
    mount.mkdir()
    root = mount / "revela-database-backups"
    monkeypatch.setattr(status, "now", lambda: datetime(2026, 10, 26, 4, 30, tzinfo=timezone.utc))
    settings = DatabaseSettings(
        root / "state", root / "work", "municipal-test", "", "", "", "",
        sys.executable, "https://alerts.invalid", "https://heartbeat.invalid",
        storage_backend="volume", volume_directory=mount, volume_min_free_bytes=1,
        volume_require_mount=False,
    )
    storage = VolumeDatabaseStorage(settings)
    storage.preflight()
    return settings, storage


def _record(settings, identifier, archive, scheduled=True, completed_at=None):
    created = completed_at or status.stamp()
    instant = datetime.fromisoformat(created)
    filename = f"revela-db_{instant.astimezone(status.MANILA):%Y%m%d_%H%M%S}_PHT_{identifier}.sql.gz"
    return {
        "feature": FEATURE, "id": identifier, "environment": settings.environment,
        "storage_identity": settings.identity, "source_server_uuid": "synthetic-source",
        "filename": filename, "created_at": created, "recovery_point": created,
        "scheduled": scheduled, "scheduled_for": created if scheduled else None,
        "monthly_archive": bool(scheduled and status.is_monthly_archive(created)),
        "database": "fixture", "mysql_version": "8.0.46",
        "tables": ["fixture"], "triggers": [], "routines": [], "events": [],
        "sql_sha256": hashlib.sha256(b"synthetic sql").hexdigest(),
    }


def _publish(settings, storage, identifier, monkeypatch, scheduled=True, completed_at=None):
    work = settings.work / identifier
    work.mkdir(parents=True)
    archive = work / "dump.sql.gz"
    archive.write_bytes(gzip.compress(b"synthetic SQL backup"))
    record = _record(settings, identifier, archive, scheduled, completed_at)
    with monkeypatch.context() as scoped:
        if completed_at:
            scoped.setattr(status, "now", lambda: datetime.fromisoformat(completed_at))
        return storage.publish(archive, record, work)


def test_volume_publish_receipt_download_integrity_and_private_permissions(volume_storage, monkeypatch):
    settings, storage = volume_storage
    record = _publish(settings, storage, "a" * 32, monkeypatch)
    receipt, body = storage.download(record["id"])
    data = body.read()
    body.close()
    assert gzip.decompress(data) == b"synthetic SQL backup"
    assert hashlib.sha256(data).hexdigest() == receipt["object"]["sha256"]
    assert storage.records() == [receipt]
    if os.name != "nt":
        assert stat.S_IMODE(storage.root.stat().st_mode) == 0o700
        assert stat.S_IMODE((storage.records_dir / f"{record['id']}.json").stat().st_mode) == 0o600


def test_incomplete_or_corrupt_volume_export_is_never_downloadable(volume_storage, monkeypatch):
    settings, storage = volume_storage
    original_write_receipt = storage._atomic_json
    monkeypatch.setattr(storage, "_atomic_json", lambda *_: (_ for _ in ()).throw(OSError("synthetic disk error")))
    with pytest.raises(OSError):
        _publish(settings, storage, "b" * 32, monkeypatch)
    assert storage.records() == []
    with pytest.raises(BackupNotFound):
        storage.download("b" * 32)

    monkeypatch.setattr(storage, "_atomic_json", original_write_receipt)
    record = _publish(settings, storage, "c" * 32, monkeypatch)
    archive = storage.files / record["filename"]
    archive.write_bytes(b"x" * record["object"]["bytes"])
    with pytest.raises(BackupNotFound):
        storage.download(record["id"])


def test_volume_preflight_requires_mount_and_capacity(volume_storage, monkeypatch):
    settings, storage = volume_storage
    settings.volume_directory.mkdir(exist_ok=True)
    storage.settings = DatabaseSettings(
        settings.state, settings.work, settings.environment, "", "", "", "",
        settings.mysqldump, settings.alert_url, settings.heartbeat_url,
        storage_backend="volume", volume_directory=settings.volume_directory,
        volume_min_free_bytes=10**30, volume_require_mount=False,
    )
    with pytest.raises(ValueError, match="database_backup_volume_capacity_below_minimum"):
        storage.preflight()


def test_volume_preflight_rejects_unmounted_production_path(volume_storage, monkeypatch):
    settings, storage = volume_storage
    storage.settings = DatabaseSettings(
        settings.state, settings.work, settings.environment, "", "", "", "",
        settings.mysqldump, settings.alert_url, settings.heartbeat_url,
        storage_backend="volume", volume_directory=settings.volume_directory,
        volume_min_free_bytes=1, volume_require_mount=True,
    )
    monkeypatch.setattr(os.path, "ismount", lambda _: False)
    with pytest.raises(ValueError, match="database_backup_volume_mount_required"):
        storage.preflight()


def test_volume_backend_is_selected_without_s3_configuration(tmp_path, monkeypatch):
    mount = tmp_path / "existing-volume"
    mount.mkdir()
    values = {
        "DB_BACKUP_STORAGE": "volume",
        "DB_BACKUP_VOLUME_DIR": str(mount),
        "DB_BACKUP_VOLUME_REQUIRE_MOUNT": "0",
        "DB_BACKUP_MIN_FREE_BYTES": "1",
        "BACKUP_ENVIRONMENT": "test",
        "BACKUP_ALERT_WEBHOOK": "https://alerts.invalid",
        "BACKUP_HEARTBEAT_URL": "https://heartbeat.invalid",
        "BACKUP_DB_HOST": "127.0.0.1",
        "BACKUP_DB_PORT": "3306",
        "BACKUP_DB_NAME": "fixture",
        "BACKUP_DB_USER": "fixture-user",
        "BACKUP_DB_PASSWORD": "synthetic-only",
        "DB_BACKUP_ROLE": "api",
        "MYSQLDUMP_BIN": sys.executable,
    }
    for key, value in values.items():
        monkeypatch.setenv(key, value)
    monkeypatch.delenv("BACKUP_S3_BUCKET", raising=False)
    monkeypatch.delenv("AWS_REGION", raising=False)
    monkeypatch.delenv("BACKUP_AWS_ACCOUNT_ID", raising=False)
    assert configuration_issues() == []
    settings = DatabaseSettings.from_env()
    assert isinstance(DatabaseStorage(settings), VolumeDatabaseStorage)


def test_heartbeat_endpoint_is_required_only_for_scheduled_backups(tmp_path, monkeypatch):
    mount = tmp_path / "existing-volume"
    mount.mkdir()
    values = {
        "DB_BACKUP_STORAGE": "volume",
        "DB_BACKUP_VOLUME_DIR": str(mount),
        "DB_BACKUP_VOLUME_REQUIRE_MOUNT": "0",
        "DB_BACKUP_MIN_FREE_BYTES": "1",
        "BACKUP_ENVIRONMENT": "test",
        "BACKUP_ALERT_WEBHOOK": "https://alerts.invalid",
        "BACKUP_DB_HOST": "127.0.0.1",
        "BACKUP_DB_PORT": "3306",
        "BACKUP_DB_NAME": "fixture",
        "BACKUP_DB_USER": "fixture-user",
        "BACKUP_DB_PASSWORD": "synthetic-only",
        "DB_BACKUP_ROLE": "api",
        "MYSQLDUMP_BIN": sys.executable,
        "DB_BACKUP_ENABLED": "1",
        "DB_BACKUP_SCHEDULE_ENABLED": "0",
    }
    for key, value in values.items():
        monkeypatch.setenv(key, value)
    monkeypatch.delenv("BACKUP_HEARTBEAT_URL", raising=False)
    assert configuration_issues() == []
    assert DatabaseSettings.from_env().heartbeat_url == ""

    monkeypatch.setenv("DB_BACKUP_SCHEDULE_ENABLED", "1")
    assert "Missing BACKUP_HEARTBEAT_URL" in configuration_issues()


def test_volume_shared_status_is_atomic_and_storage_scoped(volume_storage):
    _, storage = volume_storage
    state = {"phase": "running", "running_since": status.stamp()}
    storage.write_shared_status(state)
    assert storage.read_shared_status() == state
    envelope = storage.control.joinpath("status.json")
    envelope.write_text('{"feature":"other","state":{}}', encoding="utf-8")
    with pytest.raises(ValueError, match="invalid_shared_backup_status"):
        storage.read_shared_status()


def test_volume_retention_keeps_weekly_and_monthly_counts_and_separates_manual(volume_storage, monkeypatch):
    settings, storage = volume_storage
    weekly_dates = [
        "2026-07-31", "2026-08-07", "2026-08-14", "2026-08-21", "2026-08-28",
        "2026-09-04", "2026-09-11", "2026-09-18", "2026-09-25",
        "2026-10-02", "2026-10-09", "2026-10-16", "2026-10-23", "2026-10-30",
    ]
    weekly = [
        _publish(settings, storage, f"{index + 1:032x}", monkeypatch,
                 completed_at=f"{day}T11:00:00+00:00")
        for index, day in enumerate(weekly_dates)
    ]
    old_manual = _publish(settings, storage, "f" * 32, monkeypatch, scheduled=False,
                          completed_at="2026-08-01T11:00:00+00:00")
    recent_manual = _publish(settings, storage, "e" * 32, monkeypatch, scheduled=False,
                             completed_at="2026-10-01T11:00:00+00:00")
    latest = weekly[-1]
    removed = storage.prune(latest)
    assert old_manual["id"] in removed
    remaining = {row["id"] for row in storage.records()}
    kept_weekly_ids = {row["id"] for row in weekly[-4:]}
    monthly_records = [row for row in weekly if row["monthly_archive"]]
    kept_monthly_ids = {row["id"] for row in monthly_records[-3:]}
    assert remaining == kept_weekly_ids | kept_monthly_ids | {recent_manual["id"]}
    assert len(kept_weekly_ids) == 4 and len(kept_monthly_ids) == 3


def test_volume_retention_preserves_monthly_archive(volume_storage, monkeypatch):
    settings, storage = volume_storage
    monthly = _publish(settings, storage, "2" * 32, monkeypatch,
                       completed_at="2026-09-25T11:00:00+00:00")
    latest = _publish(settings, storage, "3" * 32, monkeypatch,
                      completed_at="2026-10-30T11:00:00+00:00")
    assert monthly["monthly_archive"] is True
    assert storage.prune(latest) == []
    assert {row["id"] for row in storage.records()} == {monthly["id"], latest["id"]}


def test_volume_lock_rejects_concurrent_job(volume_storage):
    settings, _ = volume_storage
    ready = threading.Event()
    finished = threading.Event()

    def hold():
        with lock("job", directory=settings.state, timeout=1):
            ready.set()
            finished.wait(timeout=2)

    thread = threading.Thread(target=hold)
    thread.start()
    assert ready.wait(timeout=2)
    try:
        with pytest.raises(LockBusy):
            with lock("job", directory=settings.state, timeout=0):
                pass
    finally:
        finished.set()
        thread.join(timeout=2)
    assert not thread.is_alive()


def test_restore_export_requires_isolated_target_before_any_restore(volume_storage, monkeypatch, tmp_path):
    _, _ = volume_storage
    monkeypatch.delenv("RECOVERY_ISOLATED", raising=False)
    with pytest.raises(ValueError, match="fresh_isolated_loopback_target_required"):
        restore_export(tmp_path / "not-a-backup", {}, tmp_path / "restore-output",
                       {"host": "production.example", "port": 3306}, "mysql")
    assert not (tmp_path / "restore-output").exists()
