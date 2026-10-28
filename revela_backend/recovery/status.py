"""Private status cache; the authoritative backup catalog lives in storage."""
import json
import os
import re
import uuid
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from apscheduler.triggers.cron import CronTrigger

from recovery.settings import (database_enabled, database_state_directory, cleanup_enabled,
                               configuration_issues, DatabaseSettings, pc_managed,
                               schedule_enabled)

UTC = timezone.utc
MANILA = ZoneInfo("Asia/Manila")
NOTE = ("Database schema and records only. Filesystem photos, attachments and writable files are excluded. "
        "Changes since the last successful export can be lost; this is not point-in-time recovery or zero data loss.")


def now():
    return datetime.now(UTC)


def stamp():
    return now().isoformat()


def load(directory=None):
    try:
        state = json.loads(((directory or database_state_directory()) / "status.json").read_text(encoding="utf-8"))
        if not isinstance(state, dict):
            raise ValueError("invalid_status")
        return state
    except FileNotFoundError:
        return {}


def save(state, directory=None):
    directory = directory or database_state_directory()
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = directory / f".status-{uuid.uuid4().hex}.tmp"
    try:
        with temporary.open("x", encoding="utf-8") as stream:
            json.dump(state, stream, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, directory / "status.json")
    finally:
        temporary.unlink(missing_ok=True)


def triggers():
    return {"database_exports": CronTrigger(day_of_week="fri", hour=19, minute=0, second=0, timezone=MANILA)}


def latest_due(instant=None):
    local = (instant or now()).astimezone(MANILA)
    days_since_friday = (local.weekday() - 4) % 7
    latest = (local - timedelta(days=days_since_friday)).replace(
        hour=19, minute=0, second=0, microsecond=0
    )
    if latest > local:
        latest -= timedelta(days=7)
    return latest.astimezone(UTC)


def is_monthly_archive(scheduled_for):
    if not scheduled_for:
        return False
    scheduled = datetime.fromisoformat(scheduled_for).astimezone(MANILA)
    following_week = scheduled + timedelta(days=7)
    return following_week.month != scheduled.month or following_week.year != scheduled.year


def public_file(record):
    return {key: record.get(key) for key in ("id", "filename", "created_at", "completed_at", "recovery_point", "scheduled", "scheduled_for", "monthly_archive")} | {
        "bytes": record["object"]["bytes"], "sha256": record["object"]["sha256"]}


def report():
    from flask import current_app, has_app_context
    if pc_managed():
        return {"mode": "windows_pc", "enabled": False, "operational": False,
                "scheduler_running": False, "storage_verified": False, "can_backup": False,
                "phase": "pc_managed", "files": [], "last_success": None,
                "configuration_issues": [], "schedule": "Fridays at 7:00 PM Asia/Manila",
                "timezone": "Asia/Manila", "note": NOTE,
                "message": "PC-managed backups. The website cannot inspect local PC status or download its files."}
    issues = configuration_issues()
    settings = DatabaseSettings.from_env() if not issues else None
    identity = settings.identity if settings else None
    state = {}
    records = []
    if identity:
        from recovery.db_storage import DatabaseStorage
        storage = DatabaseStorage(settings)
        state = storage.read_shared_status() or {}
        records = storage.records()
        state["files"] = records
        state["last_success"] = records[0] if records else None
        scheduled_records = [row for row in records if row.get("scheduled")]
        state["last_scheduled_success"] = scheduled_records[0] if scheduled_records else None
    scheduler = current_app.extensions.get("database_backup_scheduler") if has_app_context() else None
    trigger_job = state.get("trigger_job") or {}
    running = bool(
        (scheduler and scheduler.running and scheduler.get_job("database_exports"))
        or (state.get("phase") in ("queued", "running")
            and trigger_job.get("status") in ("queued", "running"))
    )
    mode = os.getenv("DB_BACKUP_SCHEDULER_MODE", "in_process").strip().lower()
    if mode in ("railway_cron", "external_api"):
        running = False
    storage_verified = bool(identity and state.get("storage_identity") == identity and state.get("storage_verified_at"))
    last = state.get("last_success") if identity else None
    scheduled = state.get("last_scheduled_success") if identity else None
    external_trigger_configured = bool(
        os.getenv("DB_BACKUP_EXTERNAL_TRIGGER_ENABLED") == "1"
        and re.fullmatch(r"[A-Za-z0-9_-]{32,256}", os.getenv("DB_BACKUP_TRIGGER_TOKEN", ""))
    )
    scheduler_configured = bool(schedule_enabled() and running and not issues)
    monitoring_started_at = state.get("monitoring_started_at")
    current_deployment_success = bool(
        scheduled and (
            external_trigger_configured and monitoring_started_at
            and datetime.fromisoformat(scheduled["completed_at"]) >= datetime.fromisoformat(monitoring_started_at)
        )
    )
    expected = latest_due(now() - timedelta(minutes=15)).isoformat()
    # A manual export must not mask a missed scheduled export.
    missed = expected not in {row.get("scheduled_for") for row in state.get("files", []) if row.get("scheduled")}
    if state.get("monitoring_started_at") and datetime.fromisoformat(expected) < datetime.fromisoformat(state["monitoring_started_at"]):
        missed = False
    drill = state.get("last_restore_test")
    drill_valid = False
    try:
        age = now() - datetime.fromisoformat(drill["tested_at"])
        drill_valid = bool(last and drill["success"] and drill["isolated"]
                           and drill["storage_identity"] == identity
                           and drill["source_server_uuid"] == last["source_server_uuid"]
                           and timedelta(minutes=-5) <= age < timedelta(days=90))
    except (TypeError, KeyError, ValueError):
        pass
    operational = bool(schedule_enabled() and external_trigger_configured and storage_verified and scheduled
                       and current_deployment_success
                       and not missed and drill_valid and not state.get("retention_warning")
                       and state.get("phase") == "succeeded")
    next_run = triggers()["database_exports"].get_next_fire_time(None, now()).isoformat()
    return {
        "enabled": database_enabled(), "operational": operational,
        "schedule_enabled": schedule_enabled(),
        "external_trigger_configured": external_trigger_configured,
        "automatic_execution_ready": operational,
        "automatic_execution_reason": (
            "The external scheduler is not configured with its protected API trigger."
            if not external_trigger_configured else
            "Automatic execution remains disabled until runtime, restore, retention, and cost gates are approved."
        ),
        "scheduler_running": running, "scheduler_mode": mode,
        "scheduler_configured": scheduler_configured, "storage_verified": storage_verified,
        "scheduler_started_at": current_app.extensions.get("database_backup_scheduler_started_at")
        if has_app_context() else None,
        "configuration_issues": issues,
        "phase": ("disabled" if not database_enabled()
                  else ("storage_missing" if issues else state.get("phase", "pending_verification"))),
        "last_success": public_file(last) if last else None,
        "last_scheduled_success": public_file(scheduled) if scheduled else None,
        "last_restore_test": drill, "running_since": state.get("running_since"),
        "running": bool(state.get("phase") in ("queued", "running")
                        and (state.get("running_since") or trigger_job.get("status") == "queued")),
        "current_job": state.get("current_job"),
        "trigger_job": {
            key: trigger_job.get(key) for key in
            ("id", "status", "scheduled_for", "requested_at", "started_at",
             "completed_at", "backup_id", "failure_reason")
        } if trigger_job else None,
        "schedule": "Every Friday at 7:00 PM Asia/Manila; the last weekly backup of each month is archived.",
        "cron_utc": "0 11 * * 5", "timezone": "Asia/Manila",
        "next_schedule": next_run if operational else None,
        "next_planned_schedule": next_run,
        "files": [public_file(row) for row in records],
        "files_checked_at": state.get("files_checked_at"),
        "failures": state.get("failures", [])[-10:], "retention_warning": state.get("retention_warning"),
        "last_failure": (state.get("failures") or [None])[-1],
        "retention_policy": {
            "weekly_successful_copies": 4,
            "monthly_archives": 3,
            "manual_days_proposed": 30,
            "cleanup_enabled": cleanup_enabled(),
        },
        "manual_retention": (
            "Proposed retention: keep 4 successful weekly copies and 3 monthly archives; "
            "manual backups are a separate category proposed for 30 days. "
            f"Automatic cleanup is {'enabled' if cleanup_enabled() else 'disabled'}."
        ),
        "note": NOTE, "missed_schedule": bool(schedule_enabled() and missed),
        "can_backup": bool(database_enabled() and not issues),
    }
