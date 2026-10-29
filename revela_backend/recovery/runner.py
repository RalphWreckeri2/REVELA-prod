"""Server-side database exports. Retired bundles never run here."""
import atexit
import hashlib
import logging
import os
import re
import tempfile
import threading
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

from apscheduler.schedulers.background import BackgroundScheduler

from recovery import status
from recovery.alerts import signal, failure_delivery
from recovery.db_export import export, source_lease, job_lease, inventory
from recovery.db_storage import DatabaseStorage, FEATURE
from recovery.locking import lock, LockBusy
from recovery.mysqltools import source_config, check_dump_client
from recovery.storage import retry
from recovery.settings import (DatabaseSettings, database_enabled, configuration_issues,
                               database_state_directory, pc_managed, scheduler_mode,
                               backup_role, schedule_enabled, cleanup_enabled)

log = logging.getLogger("revela.recovery")
_manual_reservation = threading.Lock()


class DatabaseBackupDisabled(RuntimeError):
    pass


class ScheduledBackupAlreadyCompleted(RuntimeError):
    def __init__(self, backup_id=None):
        super().__init__("scheduled_backup_already_completed")
        self.backup_id = backup_id


def _error_details(exc):
    # Only known diagnostics are shown. Driver messages can contain credentials,
    # DSNs, webhook tokens or SQL; never serialize those messages verbatim.
    known = {
        "private_bucket_required", "versioned_backup_bucket_required",
        "bucket_retention_exceeds_seven_days_use_a_separate_bucket",
        "matching_oracle_mysql_client_required", "database_requires_innodb_tables",
        "uploaded_export_verification_failed", "uploaded_export_checksum_mismatch",
        "export_exceeds_five_gib_upload_limit", "database_dump_failed",
        "gzip_verification_failed", "database_inventory_changed_during_export",
        "invalid_backup_receipt", "backup_file_metadata_mismatch",
        "shared_status_noncurrent_lifecycle_required", "backup_data_lifecycle_expiration_not_allowed",
    }
    result = {"error_type": type(exc).__name__}
    if isinstance(exc, (ValueError, RuntimeError)) and str(exc) in known:
        result["reason"] = str(exc)
    elif type(exc).__name__ in ("NoCredentialsError", "PartialCredentialsError"):
        result["reason"] = "aws_credentials_missing"
    elif hasattr(exc, "response") and isinstance(exc.response, dict):
        code = exc.response.get("Error", {}).get("Code")
        result["reason"] = {"AccessDenied": "storage_access_denied", "NoSuchBucket": "backup_bucket_not_found",
                            "InvalidAccessKeyId": "aws_credentials_invalid"}.get(code, "storage_request_failed")
    elif isinstance(exc, KeyError) and exc.args and exc.args[0] in ("BACKUP_DB_SSL_CA_FILE", "BACKUP_DB_USER", "BACKUP_DB_PASSWORD"):
        result["reason"] = "missing_" + exc.args[0].lower()
    return result


def _catalog(state, storage):
    records = storage.records()
    state["files"] = records
    state["files_checked_at"] = status.stamp()
    state["storage_identity"] = storage.settings.identity
    state["last_success"] = records[0] if records else None
    scheduled = [row for row in records if row["scheduled"]]
    state["last_scheduled_success"] = scheduled[0] if scheduled else None


def _failure(state, settings, code, deliver, storage=None, **details):
    event = {"at": status.stamp(), "code": code, **details}
    event.update(deliver(settings, event))
    state["failures"] = (state.get("failures", []) + [event])[-50:]
    status.save(state, settings.state)
    if storage:
        storage.write_shared_status(state)
    log.error("Database backup alert: %s", code)


def _perform_locked(settings, config, storage, scheduled=False, scheduled_for=None,
            actor=None, notify=signal, deliver=failure_delivery, job_id=None):
    """One job holds a local OS lock and a source-server advisory lock."""
    with lock("job", directory=settings.state, timeout=0):
        state = storage.read_shared_status() or status.load(settings.state)
        identifier = job_id or uuid.uuid4().hex
        trigger_job = state.get("trigger_job")
        if trigger_job and trigger_job.get("id") == identifier:
            trigger_job.update(status="running", started_at=status.stamp())
            state["trigger_job"] = trigger_job
        state.update(phase="running", running_since=status.stamp(),
                     current_job={"id": identifier, "scheduled": scheduled,
                                  "scheduled_for": scheduled_for if scheduled else None})
        if scheduled and not state.get("monitoring_started_at"):
            state["monitoring_started_at"] = scheduled_for
        status.save(state, settings.state)
        storage.write_shared_status(state)
        started = time.monotonic()
        stage = "storage_preflight"
        try:
            storage.preflight()
            state.update(storage_verified_at=status.stamp(), storage_identity=settings.identity)
            filename = f"revela-db_{status.now().astimezone(status.MANILA):%Y%m%d_%H%M%S}_PHT_{identifier}.sql.gz"
            def capture_and_upload():
                nonlocal stage
                # A fresh connection/workspace on each bounded attempt also
                # handles interrupted SQL dumps without reusing partial files.
                with source_lease(config) as connection:
                    with tempfile.TemporaryDirectory(prefix="revela-db-export-", dir=settings.work) as temporary:
                        work = Path(temporary)
                        stage = "transactional_sql_export"
                        archive, metadata = export(settings, config, work, connection)
                        record = {**metadata, "feature": FEATURE, "id": identifier, "filename": filename,
                                  "environment": settings.environment, "storage_identity": settings.identity,
                                  "scheduled": scheduled, "scheduled_for": scheduled_for if scheduled else None,
                                  "monthly_archive": bool(scheduled and status.is_monthly_archive(scheduled_for)),
                                  "requested_by": actor, "created_at": status.stamp()}
                        stage = "upload_and_readback"
                        storage.publish(archive, record, work)
                return record
            record = retry(capture_and_upload)
            state.update(last_success=record, phase="running", retention_warning=None)
            if scheduled:
                state["last_scheduled_success"] = record
            status.save(state, settings.state)
            storage.write_shared_status(state)
            if cleanup_enabled():
                try:
                    storage.prune(record)
                except Exception as exc:
                    state["retention_warning"] = "Backup retention cleanup needs attention. Existing backups were preserved where cleanup failed."
                    _failure(state, settings, "backup_retention_failed", deliver, storage=storage,
                             id=identifier, scheduled=scheduled, **_error_details(exc))
            _catalog(state, storage)
            state.update(phase="succeeded", running_since=None, current_job=None,
                         elapsed_seconds=round(time.monotonic() - started, 3))
            if trigger_job and trigger_job.get("id") == identifier:
                trigger_job.update(status="completed", completed_at=status.stamp(),
                                   backup_id=record["id"])
                state["trigger_job"] = trigger_job
            status.save(state, settings.state)
            storage.write_shared_status(state)
            # Manual exports must not satisfy the independent cron monitor.
            if scheduled:
                stage = "monitor_delivery"
                notify(settings.heartbeat_url, {"event": "scheduled_database_backup_success", "id": identifier,
                                                "scheduled_for": scheduled_for})
            return record
        except LockBusy:
            state.update(phase="blocked", running_since=None, current_job=None)
            _failure(state, settings, "backup_busy", deliver, storage=storage, scheduled=scheduled)
            raise
        except Exception as exc:
            state.update(phase="failed", running_since=None, current_job=None)
            if trigger_job and trigger_job.get("id") == identifier:
                trigger_job.update(status="failed", completed_at=status.stamp(),
                                   failure_reason=_error_details(exc).get("reason", "database_backup_failed"))
                state["trigger_job"] = trigger_job
            _failure(state, settings, "database_backup_failed", deliver, storage=storage, stage=stage,
                     id=identifier, scheduled=scheduled, **_error_details(exc))
            raise RuntimeError("database_backup_failed") from None


def perform(settings, config, storage, scheduled=False, scheduled_for=None,
            actor=None, notify=signal, deliver=failure_delivery, job_id=None):
    if not database_enabled():
        reason = "cloud_backup_disabled_pc_mode" if pc_managed() else "database_backups_disabled"
        raise DatabaseBackupDisabled(reason)
    if scheduled and not schedule_enabled():
        raise DatabaseBackupDisabled("automatic_database_backups_disabled")
    try:
        with job_lease(config):
            return _perform_locked(settings, config, storage, scheduled, scheduled_for,
                                   actor, notify=notify, deliver=deliver, job_id=job_id)
    except LockBusy:
        event = {"at": status.stamp(), "code": "backup_busy", "scheduled": scheduled}
        failure_delivery(settings, event)
        log.error("Database backup was not started because another service owns the database job lock")
        raise


def run(scheduled=False, scheduled_for=None, actor=None, job_id=None):
    if not database_enabled():
        reason = "cloud_backup_disabled_pc_mode" if pc_managed() else "database_backups_disabled"
        raise DatabaseBackupDisabled(reason)
    if scheduled and not schedule_enabled():
        raise DatabaseBackupDisabled("automatic_database_backups_disabled")
    if pc_managed():
        raise RuntimeError("cloud_backup_disabled_pc_mode")
    settings = DatabaseSettings.from_env()
    storage = DatabaseStorage(settings)
    try:
        config = source_config()
    except Exception as exc:
        with lock("job", directory=settings.state, timeout=0):
            state = storage.read_shared_status() or status.load(settings.state)
            state.update(phase="configuration_failed", running_since=None)
            _failure(state, settings, "database_backup_configuration_failed", failure_delivery,
                     storage=storage, **_error_details(exc))
        raise RuntimeError("database_backup_configuration_failed") from None
    return perform(settings, config, storage, scheduled, scheduled_for, actor, job_id=job_id)


def _finalize_trigger_job(settings, storage, job_id, result=None, failure=None):
    with lock("job", directory=settings.state, timeout=10):
        state = status.load(settings.state)
        job = state.get("trigger_job") or {}
        if job.get("id") != job_id:
            return
        if failure is None:
            job.update(status="completed", completed_at=status.stamp(),
                       backup_id=(result or {}).get("id"))
        else:
            job.update(status="failed", completed_at=status.stamp(),
                       failure_reason=failure)
            state.update(phase="failed", running_since=None, current_job=None)
        state["trigger_job"] = job
        status.save(state, settings.state)
        storage.write_shared_status(state)


def start_scheduled(app, scheduled_for, idempotency_key):
    """Queue one external weekly trigger and persist its pollable job receipt."""
    if not database_enabled():
        raise DatabaseBackupDisabled("database_backups_disabled")
    if not schedule_enabled():
        raise DatabaseBackupDisabled("automatic_database_backups_disabled")
    if (os.getenv("DB_BACKUP_EXTERNAL_TRIGGER_ENABLED") != "1"
            or not re.fullmatch(r"[A-Za-z0-9_-]{32,256}", os.getenv("DB_BACKUP_TRIGGER_TOKEN", ""))):
        raise DatabaseBackupDisabled("external_database_backup_trigger_not_configured")
    if not isinstance(idempotency_key, str) or not re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", idempotency_key):
        raise ValueError("invalid_backup_trigger_idempotency_key")
    settings = DatabaseSettings.from_env()
    storage = DatabaseStorage(settings)
    key_digest = hashlib.sha256(idempotency_key.encode("ascii")).hexdigest()
    previous = status.load(settings.state).get("trigger_job") or {}
    if previous.get("request_key_sha256") == key_digest:
        return previous
    if not _manual_reservation.acquire(blocking=False):
        raise LockBusy("backup_busy")

    try:
        with lock("job", directory=settings.state, timeout=0):
            state = status.load(settings.state)
            current = state.get("trigger_job") or {}
            if current.get("request_key_sha256") == key_digest:
                _manual_reservation.release()
                return current
            if (current.get("status") == "completed"
                    and current.get("scheduled_for") == scheduled_for):
                _manual_reservation.release()
                return current
            scheduled_records = [
                row for row in state.get("files", [])
                if row.get("scheduled") and row.get("scheduled_for") == scheduled_for
            ]
            last_scheduled = state.get("last_scheduled_success") or {}
            if (scheduled_records or last_scheduled.get("scheduled_for") == scheduled_for):
                backup_id = (scheduled_records[0].get("id") if scheduled_records
                             else last_scheduled.get("id"))
                raise ScheduledBackupAlreadyCompleted(backup_id)
            if state.get("phase") == "running":
                current.update(status="failed", completed_at=status.stamp(),
                               failure_reason="interrupted_before_completion")
                state.update(trigger_job=current, phase="failed", running_since=None, current_job=None)
            elif state.get("phase") == "queued":
                try:
                    queued_at = datetime.fromisoformat(current["requested_at"])
                    if status.now() - queued_at < timedelta(minutes=2):
                        raise LockBusy("backup_busy")
                except (KeyError, TypeError, ValueError):
                    raise LockBusy("backup_busy") from None
                current.update(status="failed", completed_at=status.stamp(),
                               failure_reason="interrupted_before_start")
                state.update(trigger_job=current, phase="failed", current_job=None)
            identifier = uuid.uuid4().hex
            job = {
                "id": identifier,
                "status": "queued",
                "scheduled_for": scheduled_for,
                "requested_at": status.stamp(),
                "request_key_sha256": key_digest,
            }
            state.update(
                phase="queued",
                running_since=None,
                current_job={"id": identifier, "scheduled": True, "scheduled_for": scheduled_for},
                trigger_job=job,
            )
            status.save(state, settings.state)
            storage.write_shared_status(state)

        def execute():
            try:
                with app.app_context():
                    result = run(scheduled=True, scheduled_for=scheduled_for, job_id=identifier)
                    _finalize_trigger_job(settings, storage, identifier, result=result)
            except Exception:
                log.error("Externally triggered database backup failed; status records the outcome")
                try:
                    with app.app_context():
                        _finalize_trigger_job(settings, storage, identifier,
                                              failure="database_backup_failed")
                except Exception:
                    log.exception("Could not finalize externally triggered database backup status")
            finally:
                _manual_reservation.release()

        try:
            threading.Thread(target=execute, name="database-backup-external-trigger", daemon=True).start()
        except Exception:
            _finalize_trigger_job(settings, storage, identifier, failure="worker_start_failed")
            raise
        return job
    except Exception:
        if _manual_reservation.locked():
            _manual_reservation.release()
        raise


def start_manual(app, actor):
    """Start a manual job; all OS and database locks are acquired in its worker thread."""
    if not database_enabled():
        reason = "cloud_backup_disabled_pc_mode" if pc_managed() else "database_backups_disabled"
        raise DatabaseBackupDisabled(reason)
    if not _manual_reservation.acquire(blocking=False):
        raise LockBusy("backup_busy")

    def execute():
        try:
            with app.app_context():
                run(actor=actor)
        except Exception:
            log.error("Manual database backup failed; see administrator status")
        finally:
            # threading.Lock is intentionally used as a cross-thread reservation;
            # connection/file-lock context managers are created and released by run().
            _manual_reservation.release()

    try:
        thread = threading.Thread(target=execute, name="database-backup-manual", daemon=True)
        thread.start()
    except Exception:
        _manual_reservation.release()
        raise


def check_missed(settings, storage=None, deliver=failure_delivery):
    with lock("job", directory=settings.state, timeout=0):
        state = status.load(settings.state)
        # Check both slots in the past 24 hours, including outages/restarts. A
        # later successful backup must not conceal the earlier missed slot.
        due = status.latest_due(status.now() - timedelta(minutes=15))
        previous = status.latest_due(due - timedelta(seconds=1))
        completed = {row["scheduled_for"] for row in state.get("files", []) if row.get("scheduled")}
        alerted = state.get("alerted_slots", [])
        for slot in (previous, due):
            value = slot.isoformat()
            if state.get("monitoring_started_at") and slot < datetime.fromisoformat(state["monitoring_started_at"]):
                continue  # Do not call pre-activation slots missed on first setup.
            if value not in completed and value not in alerted:
                alerted.append(value)
                state["alerted_slots"] = alerted[-10:]
                _failure(state, settings, "scheduled_database_backup_missed", deliver, scheduled_for=value)


def start_scheduler(app):
    # The legacy bundle flag cannot start the retired 15-minute jobs.
    if pc_managed() or backup_role() == "worker":
        return  # Windows PC or one-shot worker owns exports, not this API process.
    if scheduler_mode() in ("railway_cron", "external_api"):
        return
    if not schedule_enabled():
        return
    issues = configuration_issues()
    if issues:
        if schedule_enabled():
            log.error("Database backup schedule NOT started: %s", "; ".join(issues))
            def report_configuration_failure():
                with app.app_context():
                    try:
                        directory = database_state_directory()
                        with lock("job", directory=directory, timeout=0):
                            state = status.load(directory)
                            state.update(phase="configuration_missing", running_since=None)
                            pending = SimpleNamespace(state=directory, alert_url=os.getenv("BACKUP_ALERT_WEBHOOK", ""))
                            _failure(state, pending, "database_backup_configuration_missing", failure_delivery,
                                     configuration_issues=issues)
                    except LockBusy:
                        pass
            reporter = threading.Thread(target=report_configuration_failure, daemon=True)
            app.extensions["database_backup_config_reporter"] = reporter
            reporter.start()
        return
    settings = DatabaseSettings.from_env()
    scheduler = BackgroundScheduler(timezone="Asia/Manila", daemon=True)
    app.extensions["database_backup_scheduler"] = scheduler

    def scheduled():
        with app.app_context():
            try:
                run(scheduled=True, scheduled_for=status.latest_due().isoformat())
            except Exception:
                log.error("Scheduled database export failed; admin alert/status records the failure")

    def watchdog():
        with app.app_context():
            try:
                check_missed(settings)
            except LockBusy:
                pass  # In-progress job owns the ledger; retry on the next check.

    def bootstrap():
        with app.app_context():
            try:
                with lock("job", directory=settings.state, timeout=0):
                    storage = DatabaseStorage(settings)
                    storage.preflight()
                    with source_lease(source_config()) as connection:
                        source = inventory(connection)
                        check_dump_client(settings.mysqldump, source["mysql_version"])
                    state = status.load(settings.state)
                    interrupted = state.get("phase") == "running" and state.get("running_since")
                    _catalog(state, storage)
                    if schedule_enabled() and not state.get("monitoring_started_at"):
                        existing = [row["scheduled_for"] for row in state["files"] if row.get("scheduled_for")]
                        state["monitoring_started_at"] = min(existing) if existing else status.stamp()
                    state.update(storage_verified_at=status.stamp(), running_since=None,
                                 phase="succeeded" if state.get("last_success") else "pending_verification")
                    status.save(state, settings.state)
                    if interrupted:
                        _failure(state, settings, "database_backup_interrupted", failure_delivery,
                                 running_since=interrupted)
                if schedule_enabled():
                    app.extensions["database_backup_scheduler_started_at"] = status.stamp()
                    scheduler.add_job(scheduled, status.triggers()["database_exports"], id="database_exports",
                                      max_instances=1, coalesce=True, misfire_grace_time=900)
                    scheduler.add_job(watchdog, "interval", minutes=5, id="database_backup_watchdog", max_instances=1)
                    watchdog()
            except LockBusy:
                scheduler.add_job(bootstrap, "date", run_date=status.now() + timedelta(seconds=30),
                                  id="database_backup_preflight", replace_existing=True)
            except Exception as exc:
                try:
                    with lock("job", directory=settings.state, timeout=0):
                        state = status.load(settings.state)
                        state.update(phase="storage_preflight_failed", running_since=None)
                        _failure(state, settings, "backup_storage_preflight_failed", failure_delivery, **_error_details(exc))
                except LockBusy:
                    # Never overwrite the ledger of a newly started backup.
                    failure_delivery(settings, {"code": "backup_storage_preflight_failed", "at": status.stamp()})
                log.error("Database export schedule NOT enabled: storage preflight failed")

    scheduler.add_job(bootstrap, "date", id="database_backup_preflight")
    scheduler.start()
    atexit.register(lambda: scheduler.shutdown(wait=False) if scheduler.running else None)
