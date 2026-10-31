"""
Admin-only settings and read-only operational status endpoints.

Two authorization tiers, and the split is deliberate:

  * `@admin_required()`   -- read-only monitoring. Every admin needs to see how
    much of the shared Google request budget is spent.
  * `@super_admin_required()` -- anything that CHANGES how REVELA spends quota
    or stores Google-derived data: application quota edits and resets, Test Mode
    configuration and resets, and fixture purge.

The Super Admin tier exists because the frontend gate is cosmetic. Hiding the
Advanced Settings block is not an authorization boundary; a client that calls
`PUT /api/admin-settings/quota` directly must be refused by the server too.

Deliberately absent: any global quota bypass, any way to reset or truncate
production usage counters, and any Google Cloud Console control. Caps can only
be lowered or raised up to a recorded Cloud ceiling, and clearing an override
returns to the environment baseline rather than granting unlimited usage.
"""

import hashlib
import hmac
import os
import re
from functools import wraps
from datetime import timedelta

from flask import Blueprint, Response, current_app, jsonify, request
from flask_jwt_extended import get_jwt_identity

from api.flags.service import _load_registry, _match_poi_to_registry
from api.middleware.decorators import admin_required, super_admin_required
from api.utils import quota_settings, test_mode, usage_report


admin_settings_bp = Blueprint("admin_settings", __name__)


def _backup_trigger_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        expected = os.getenv("DB_BACKUP_TRIGGER_TOKEN", "")
        if (os.getenv("DB_BACKUP_EXTERNAL_TRIGGER_ENABLED") != "1"
                or not re.fullmatch(r"[A-Za-z0-9_-]{32,256}", expected)):
            return jsonify({"error": "External database backup trigger is not enabled."}), 503
        authorization = request.headers.get("Authorization", "")
        scheme, separator, supplied = authorization.partition(" ")
        if (not separator or scheme.lower() != "bearer"
                or not re.fullmatch(r"[A-Za-z0-9_-]{32,256}", supplied)
                or not hmac.compare_digest(supplied, expected)):
            return jsonify({"error": "Unauthorized."}), 401
        return fn(*args, **kwargs)
    return wrapper


def _actor_id():
    try:
        return int(get_jwt_identity())
    except Exception:
        return None


# ── GET /api/admin-settings/usage ─────────────────────────────────────────────
#
# Read-only and admin-accessible on purpose: usage monitoring is something
# every administrator needs, including Super Admin.


@admin_settings_bp.route("/usage", methods=["GET"])
@admin_required()
def usage_route():
    """
    Unified usage/limits/cost report.

    200 on success, 500 if the usage ledger cannot be read. Never mutates.
    """
    try:
        return jsonify(usage_report.build_usage_report()), 200
    except Exception as exc:
        print(f"[admin_settings] usage report failed ({type(exc).__name__})")
        return jsonify({"error": "Could not build the usage report."}), 500


@admin_settings_bp.route("/database-backup/status", methods=["GET"])
@admin_required()
def database_backup_status_route():
    """Return admin-only durable database backup status without starting work."""
    from recovery.status import report
    try:
        result = report()
    except Exception as exc:
        current_app.logger.error("Database backup status unavailable (%s)", type(exc).__name__)
        return jsonify({"error": "Private database backup status is temporarily unavailable."}), 503

    issues = result.get("configuration_issues", [])
    records = [_panel_backup_record(row) for row in result.get("files", [])]
    current = result.get("current_job") or {}
    if result.get("running"):
        records.insert(0, {
            "id": current.get("id", "running-backup"),
            "trigger": "automatic" if current.get("scheduled") else "manual",
            "status": "running",
            "startedAt": result.get("running_since"),
            "completedAt": None,
            "sizeBytes": None,
        })
    for index, failure in enumerate(result.get("failures", [])):
        failed_at = failure.get("at")
        if not failed_at:
            continue
        records.append({
            "id": str(failure.get("id") or f"failure-{failed_at}-{index}"),
            "trigger": "automatic" if failure.get("scheduled") else "manual",
            "status": "failed",
            "startedAt": failed_at,
            "completedAt": None,
            "sizeBytes": None,
        })

    configured = not issues and result.get("mode") != "windows_pc"
    can_backup = bool(result.get("can_backup"))
    automatic_enabled = bool(result.get("automatic_execution_ready")
                              and result.get("external_trigger_configured"))
    schedule_enabled = bool(result.get("schedule_enabled"))
    schedule_summary = (
        "Every Friday at 7:00 PM Asia/Manila; automatic execution is not ready "
        "until a reliable external trigger is integrated."
    )
    reason = None
    if issues:
        reason = "Database backup runtime configuration is incomplete."
    elif not result.get("enabled"):
        reason = "Database backup execution is disabled by the runtime kill switch."

    records.sort(key=lambda row: row.get("startedAt") or row.get("completedAt") or "", reverse=True)
    history = None if issues else records
    phase = result.get("phase")
    if issues:
        status_name = "not_configured"
    elif result.get("running"):
        status_name = "running"
    elif phase in ("failed", "configuration_failed", "storage_preflight_failed"):
        status_name = "failed"
    else:
        status_name = "ready"

    payload = {
        "status": status_name,
        "configured": configured,
        "reason": reason,
        "lastSuccessfulBackup": _panel_backup_record(result.get("last_success"))
        if result.get("last_success") else None,
        "schedule": {
            "configured": configured,
            "enabled": schedule_enabled,
            "nextRunAt": result.get("next_schedule") if automatic_enabled else None,
            "summary": schedule_summary if configured else None,
            "executionReady": automatic_enabled,
        },
        "retention": {
            "configured": configured,
            "summary": result.get("manual_retention") if configured else None,
            "cleanupEnabled": result.get("retention_policy", {}).get("cleanup_enabled", False),
            "policy": result.get("retention_policy"),
        },
        "history": history,
        "historyUnavailableReason": (
            "Backup history is unavailable until backup storage configuration is complete."
            if issues else None
        ),
        "manualBackupDisabledReason": (
            None if can_backup else reason or "Manual database backups are not enabled."
        ),
        "downloadDisabledReason": (
            None if configured else "Authenticated backup downloads require configured private storage."
        ),
        "canManualBackup": can_backup,
        "canDownload": configured,
        "configurationIssues": issues,
        "automaticExecutionEnabled": automatic_enabled,
        "automaticExecutionStatus": "ready" if automatic_enabled else "not_ready",
        "automaticExecutionReason": result.get("automatic_execution_reason"),
        "externalTriggerConfigured": result.get("external_trigger_configured", False),
    }
    response = jsonify(payload)
    response.headers["Cache-Control"] = "private, no-store"
    return response, 200


@admin_settings_bp.route("/database-backup/trigger", methods=["POST"])
@_backup_trigger_required
def database_backup_trigger_route():
    """Wake the API and enqueue one idempotent weekly backup from an external scheduler."""
    from recovery import status
    from recovery.locking import LockBusy
    from recovery.runner import (DatabaseBackupDisabled, ScheduledBackupAlreadyCompleted,
                                 start_scheduled)
    from recovery.settings import configuration_issues, schedule_enabled

    if not schedule_enabled():
        return jsonify({"error": "Automatic database backups are disabled."}), 409
    issues = configuration_issues()
    if issues:
        return jsonify({"error": "Database backup runtime configuration is incomplete."}), 503
    idempotency_key = request.headers.get("Idempotency-Key", "")
    if not re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", idempotency_key):
        return jsonify({"error": "A valid Idempotency-Key header is required."}), 400

    now = status.now()
    scheduled_for = status.latest_due(now)
    # latest_due keeps the current weekly slot eligible until the next Friday
    # slot, allowing GitHub's delayed schedule delivery to catch up safely.
    # start_scheduled rejects a second export for an already completed slot.
    if not scheduled_for <= now < scheduled_for + timedelta(days=7):
        return jsonify({"error": "The scheduled backup trigger is outside its weekly catch-up window."}), 409
    try:
        job = start_scheduled(
            current_app._get_current_object(), scheduled_for.isoformat(), idempotency_key,
        )
    except LockBusy:
        response = jsonify({"error": "A database backup is already queued or running.", "status": "busy"})
        response.headers["Retry-After"] = "30"
        return response, 409
    except ScheduledBackupAlreadyCompleted as exc:
        return jsonify({
            "error": "A successful backup already exists for this weekly slot.",
            "status": "already_completed",
            "backup_id": exc.backup_id,
        }), 409
    except DatabaseBackupDisabled:
        return jsonify({"error": "Automatic database backups are disabled."}), 409
    except ValueError:
        return jsonify({"error": "The external backup trigger request is invalid."}), 400
    except Exception as exc:
        current_app.logger.error("Could not queue scheduled database backup (%s)", type(exc).__name__)
        return jsonify({"error": "Could not queue the scheduled database backup."}), 503

    response = jsonify({
        "job_id": job["id"],
        "status": job["status"],
        "scheduled_for": job["scheduled_for"],
        "status_url": f"/api/admin-settings/database-backup/trigger/{job['id']}",
    })
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["Retry-After"] = "15"
    return response, 202


@admin_settings_bp.route("/database-backup/trigger/<identifier>", methods=["GET"])
@_backup_trigger_required
def database_backup_trigger_status_route(identifier):
    """Return one durable trigger job result; callers should poll with a finite deadline."""
    from recovery.settings import DatabaseSettings
    from recovery import status

    if not re.fullmatch(r"[0-9a-f]{32}", identifier):
        return jsonify({"error": "Backup trigger job not found."}), 404
    try:
        settings = DatabaseSettings.from_env()
        job = (status.load(settings.state).get("trigger_job") or {})
    except Exception as exc:
        current_app.logger.error("Scheduled backup job status unavailable (%s)", type(exc).__name__)
        return jsonify({"error": "Scheduled backup job status is temporarily unavailable."}), 503
    if job.get("id") != identifier:
        return jsonify({"error": "Backup trigger job not found."}), 404

    response = jsonify({
        "job_id": identifier,
        "status": job.get("status", "unknown"),
        "scheduled_for": job.get("scheduled_for"),
        "requested_at": job.get("requested_at"),
        "started_at": job.get("started_at"),
        "completed_at": job.get("completed_at"),
        "backup_id": job.get("backup_id"),
        "failure_reason": job.get("failure_reason"),
    })
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["Retry-After"] = "15"
    return response, 200


def _panel_backup_record(record):
    from recovery.status import is_monthly_archive
    return {
        "id": record.get("id"),
        "trigger": "automatic" if record.get("scheduled") else "manual",
        "status": "completed",
        "startedAt": record.get("created_at") or record.get("completed_at"),
        "completedAt": record.get("completed_at"),
        "sizeBytes": record.get("bytes"),
        "sha256": record.get("sha256"),
        "mysqlVersion": record.get("mysql_version"),
        "sourceServerUuid": record.get("source_server_uuid"),
        "tableCount": len(record.get("tables", [])),
        "monthlyArchive": (
            record.get("monthly_archive") is True
            or is_monthly_archive(record.get("scheduled_for"))
        ),
    }


@admin_settings_bp.route("/backups", methods=["GET"])
@admin_required()
def backup_status_route():
    """Compatibility status endpoint for the server-side backup catalog."""
    from recovery.status import report
    try:
        result = report()
    except Exception as exc:
        current_app.logger.error("Database backup status unavailable (%s)", type(exc).__name__)
        return jsonify({"error": "Private database backup status is temporarily unavailable."}), 503
    response = jsonify(result)
    response.headers["Cache-Control"] = "private, no-store"
    return response, 200


@admin_settings_bp.route("/backups/run", methods=["POST"])
@admin_required()
def backup_now_route():
    from recovery.settings import pc_managed, database_enabled, configuration_issues
    if pc_managed():
        return jsonify({"error": "Backups are managed on the municipal Windows PC. Start and check them there."}), 409
    if not database_enabled():
        return jsonify({"error": "Database backups are disabled.", "status": "disabled",
                        "reason": "database_backups_disabled"}), 409
    issues = configuration_issues()
    if issues:
        return jsonify({"error": "Backup storage/client configuration is incomplete.",
                        "configuration_issues": issues}), 503
    from recovery.runner import start_manual
    from recovery.locking import LockBusy
    try:
        start_manual(current_app._get_current_object(), _actor_id())
    except LockBusy:
        return jsonify({"error": "A database backup is already running."}), 409, {"Retry-After": "30"}
    except Exception as exc:
        current_app.logger.error("Could not start database backup (%s)", type(exc).__name__)
        return jsonify({"error": "Could not start the database backup. Check administrator backup status."}), 503
    return jsonify({"message": "Database backup started. It continues on the server.", "status": "running"}), 202


@admin_settings_bp.route("/backups/<identifier>/download", methods=["GET"])
@admin_required()
def download_backup_route(identifier):
    from recovery.settings import pc_managed, DatabaseSettings
    from recovery.db_storage import DatabaseStorage, BackupNotFound
    if pc_managed() or not re.fullmatch(r"[0-9a-f]{32}", identifier):
        return jsonify({"error": "Backup not found."}), 404
    try:
        record, body = DatabaseStorage(DatabaseSettings.from_env()).download(identifier)
    except BackupNotFound:
        return jsonify({"error": "Backup not found."}), 404
    except Exception as exc:
        current_app.logger.error("Private database backup download unavailable (%s)", type(exc).__name__)
        return jsonify({"error": "The private backup file is unavailable. Check backup storage configuration."}), 503

    expected_hash = record["object"]["sha256"]
    expected_size = record["object"]["bytes"]

    def content():
        digest = hashlib.sha256()
        try:
            pending = body.read(1024 * 1024)
            size = 0
            if not pending and (expected_size != 0 or digest.hexdigest() != expected_hash):
                raise OSError("backup_download_checksum_mismatch")
            while pending:
                digest.update(pending)
                size += len(pending)
                following = body.read(1024 * 1024)
                if not following and (digest.hexdigest() != expected_hash or size != expected_size):
                    raise OSError("backup_download_checksum_mismatch")
                yield pending
                pending = following
        finally:
            body.close()

    response = Response(content(), mimetype="application/gzip")
    response.headers.update({
        "Content-Disposition": f'attachment; filename="{record["filename"]}"',
        "Content-Length": str(expected_size),
        "Cache-Control": "private, no-store",
        "X-Content-Type-Options": "nosniff",
        "X-Backup-SHA256": expected_hash,
    })
    response.call_on_close(body.close)
    return response


# ── GET/PUT /api/admin-settings/quota ─────────────────────────────────────────
#
# Super Admin only. This payload exists solely for the Advanced Settings block
# and directly changes how many Google requests REVELA is willing to spend.


@admin_settings_bp.route("/quota", methods=["GET"])
@super_admin_required()
def get_quota_route():
    """Effective quota settings with baseline, source, and Cloud ceiling."""
    return jsonify({
        "fields": quota_settings.snapshot(),
        "note": "An admin override can never raise a cap above the recorded "
                "Google Cloud quota.",
    }), 200


@admin_settings_bp.route("/quota", methods=["PUT"])
@super_admin_required()
def update_quota_route():
    """
    Persist quota overrides.

    The patch is validated as a unit: if any field is rejected nothing is
    written, so a bad value cannot leave a half-applied budget change.

    200 on success, 400 with every validation message on failure.
    """
    patch = request.get_json(silent=True)
    if not isinstance(patch, dict) or not patch:
        return jsonify({"error": "Request body must be a JSON object of settings."}), 400
    if any(not isinstance(k, str) for k in patch):
        return jsonify({"error": "Setting keys must be strings."}), 400

    result, error = quota_settings.save(patch, user_id=_actor_id())
    if error:
        return jsonify({"error": error}), 400
    return jsonify(result), 200


@admin_settings_bp.route("/quota/reset", methods=["POST"])
@super_admin_required()
def reset_quota_route():
    """
    Discard admin overrides so the environment baseline applies again.

    This restores configured behaviour; it does not grant extra quota and does
    not touch usage counters.
    """
    result, error = quota_settings.clear_overrides(user_id=_actor_id())
    if error:
        return jsonify({"error": error}), 500
    return jsonify(result), 200


# ── GET/PUT /api/admin-settings/test-mode ─────────────────────────────────────
#
# Super Admin only. Test Mode changes live request behaviour and fixture
# storage persists Google-derived payloads on the server.


@admin_settings_bp.route("/test-mode", methods=["GET"])
@super_admin_required()
def get_test_mode_route():
    """Test Mode configuration plus fixture cache statistics."""
    return jsonify({
        "config": test_mode.get_config(),
        "fixtures": test_mode.fixture_stats(),
        "note": "Replaying a stored fixture issues no Google request and is "
                "not charged to the usage ledger, so testing never requires "
                "clearing usage rows.",
    }), 200


@admin_settings_bp.route("/test-mode", methods=["PUT"])
@super_admin_required()
def update_test_mode_route():
    """
    Persist Test Mode settings. 200 on success, 400 on any validation error.
    """
    patch = request.get_json(silent=True)
    if not isinstance(patch, dict) or not patch:
        return jsonify({"error": "Request body must be a JSON object of settings."}), 400

    result, error = test_mode.save_config(patch, user_id=_actor_id())
    if error:
        return jsonify({"error": error}), 400
    return jsonify(result), 200


@admin_settings_bp.route("/test-mode/reset", methods=["POST"])
@super_admin_required()
def reset_test_mode_route():
    """Restore Test Mode defaults. Never touches usage counters."""
    result, error = test_mode.reset_config(user_id=_actor_id())
    if error:
        return jsonify({"error": error}), 500
    return jsonify(result), 200


@admin_settings_bp.route("/test-mode/fixtures/purge", methods=["POST"])
@super_admin_required()
def purge_fixtures_route():
    """
    Delete cached request payloads.

    `older_than_days` defaults to the configured retention window; pass 0 to
    delete every fixture. Usage counters are untouched.
    """
    body = request.get_json(silent=True) or {}
    older = body.get("older_than_days")
    removed, error = test_mode.purge_fixtures(older_than_days=older)
    if error:
        return jsonify({"error": error}), 400
    return jsonify({
        "removed": removed,
        "fixtures": test_mode.fixture_stats(),
    }), 200


# ── POST /api/admin-settings/matching-dry-run ─────────────────────────────────
#
# Stays on the plain admin tier: it is a pure, read-only matcher replay. It
# reserves no quota, writes no usage row, creates no flag, and stores nothing,
# so it neither spends Google budget nor exposes a Google-derived dataset.


@admin_settings_bp.route("/matching-dry-run", methods=["POST"])
@admin_required()
def matching_dry_run_route():
    """
    Replay POI candidates through the matcher with no Google traffic at all.

    This is the cheapest way to iterate on matching rules: it reads the
    registry, runs `_match_poi_to_registry`, and returns the decision for each
    supplied candidate. No request is reserved, no ledger row is written, and
    no flag is created — the matcher is pure, but the caller must not be
    allowed to mistake this for a scan.

    Body: {"candidates": [{"name", "lat", "lng", "types", "address", ...}]}
    """
    body = request.get_json(silent=True) or {}
    candidates = body.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        return jsonify({"error": "'candidates' must be a non-empty array."}), 400
    if len(candidates) > 500:
        return jsonify({"error": "At most 500 candidates per dry run."}), 400

    try:
        registry = _load_registry()
    except Exception as exc:
        print(f"[admin_settings] dry run could not load registry ({exc})")
        return jsonify({"error": "Could not load the official registry."}), 500

    results = []
    for index, candidate in enumerate(candidates):
        if not isinstance(candidate, dict):
            results.append({"index": index, "error": "Candidate must be an object."})
            continue
        name = candidate.get("name")
        try:
            lat = float(candidate.get("lat"))
            lng = float(candidate.get("lng"))
        except (TypeError, ValueError):
            results.append({
                "index": index, "error": "Candidate needs numeric lat/lng.",
            })
            continue
        types = candidate.get("types") or ()
        if isinstance(types, str):
            types = (types,)
        try:
            entry, distance, score, status = _match_poi_to_registry(
                name, lat, lng, registry,
                poi_barangay_id=candidate.get("barangay_id"),
                poi_types=tuple(types),
                poi_address=candidate.get("address") or "",
            )
        except Exception as exc:
            print(f"[admin_settings] dry run matcher error ({exc})")
            results.append({"index": index, "error": "Matcher failed."})
            continue
        results.append({
            "index": index,
            "name": name,
            "match_status": status,
            "score": round(float(score or 0.0), 4),
            "distance_m": (
                round(float(distance), 1)
                if distance is not None and distance != float("inf") else None
            ),
            "matched_business_id": entry.get("businessID") if entry else None,
            "matched_business_name": entry.get("businessName") if entry else None,
            "matched_application_status": (
                entry.get("applicationStatus") if entry else None
            ),
        })

    return jsonify({
        "registry_size": len(registry),
        "candidates_evaluated": len(results),
        "google_requests_made": 0,
        "usage_rows_written": 0,
        "results": results,
    }), 200
