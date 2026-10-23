"""Recoverable filesystem changes around the evidence metadata transaction."""

import filecmp
import json
import logging
import os
import shutil
import tempfile
from datetime import datetime, timedelta
from threading import Lock


logger = logging.getLogger(__name__)
_LOCK = Lock()
_PREFIX = ".cleanup-backup-"
_FILTER_DAYS = {
    "older_365d": 365, "older_180d": 180, "older_90d": 90,
    "older_30d": 30, "all_verified": 0,
}


def recovery_storage_stats(evidence_dir):
    pending, size, files = False, 0, 0
    if os.path.isdir(evidence_dir):
        with os.scandir(evidence_dir) as entries:
            directories = list(entries)
        for entry in directories:
            if entry.name.startswith(_PREFIX) and entry.is_dir(follow_symlinks=False):
                pending = True
                try:
                    with os.scandir(entry.path) as backups:
                        for backup in backups:
                            try:
                                if backup.is_file(follow_symlinks=False):
                                    size += backup.stat().st_size
                                    files += int(backup.name.endswith(".bak"))
                            except FileNotFoundError:
                                pass  # A concurrent cleanup disposed of it.
                except FileNotFoundError:
                    pass
    return {"cleanupPending": pending, "recoveryBytes": size, "recoveryFiles": files}


def _photo_plan(raw):
    if not raw:
        return "archived://none", []
    try:
        parsed = json.loads(raw) if isinstance(raw, str) else raw
    except (ValueError, TypeError):
        parsed = raw
    is_array = isinstance(parsed, list)
    items = parsed if is_array else [parsed]
    updated, filenames = [], []
    for item in items:
        if not isinstance(item, str) or not item.strip():
            updated.append(item)
            continue
        item = item.strip()
        if item.startswith("archived://"):
            updated.append(item)
            continue
        name = os.path.basename(item)
        if name in ("", ".", ".."):
            raise ValueError("Invalid evidence filename")
        filenames.append(name)
        updated.append(f"archived://{name}")
    if not filenames:
        return raw, []
    return json.dumps(updated) if is_array else updated[0], filenames


def _write_manifest(directory, manifest):
    temporary = os.path.join(directory, "manifest.tmp")
    with open(temporary, "w", encoding="utf-8") as handle:
        json.dump(manifest, handle)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, os.path.join(directory, "manifest.json"))


def _restore(directory, evidence_dir, manifest):
    if not manifest.get("ready", False):
        # Deletion starts only after the ready journal was persisted. An
        # interrupted/failed copy must not replace an intact original.
        if not all(os.path.isfile(os.path.join(evidence_dir, item["name"])) for item in manifest["files"]):
            raise OSError("Original evidence is unavailable during backup preparation")
        return
    for item in manifest["files"]:
        original = os.path.join(evidence_dir, item["name"])
        backup = os.path.join(directory, item["backup"])
        if os.path.exists(original):
            # Never overwrite a newer upload or discard a differing backup.
            if os.path.exists(backup) and not filecmp.cmp(original, backup, shallow=False):
                raise OSError("Evidence changed during recovery")
        elif os.path.isfile(backup):
            os.replace(backup, original)
        else:
            raise OSError("Evidence recovery copy is unavailable")


def _purge(directory, manifest):
    for item in manifest["files"]:
        backup = os.path.join(directory, item["backup"])
        if os.path.exists(backup):
            os.remove(backup)
    for name in ("manifest.tmp", "manifest.json"):
        path = os.path.join(directory, name)
        if os.path.exists(path):
            os.remove(path)
    os.rmdir(directory)


def _transaction_state(cursor, manifest):
    rows = manifest["reports"]
    if not rows:
        raise ValueError("Invalid evidence recovery journal")
    placeholders = ",".join(["%s"] * len(rows))
    cursor.execute(
        f"SELECT reportID, photoPath FROM inspection_reports "
        f"WHERE reportID IN ({placeholders}) FOR UPDATE",
        tuple(row["id"] for row in rows),
    )
    current = {row["reportID"]: row["photoPath"] for row in cursor.fetchall()}
    if all(row["id"] in current and current[row["id"]] == row["old"] for row in rows):
        return "original"
    if all(row["id"] in current and current[row["id"]] == row["new"] for row in rows):
        return "archived"
    return "unknown"


def _recover(cursor, evidence_dir):
    """Resolve interrupted runs only after checking their locked DB rows."""
    with os.scandir(evidence_dir) as entries:
        directories = list(entries)
    for entry in directories:
        if not entry.name.startswith(_PREFIX) or not entry.is_dir(follow_symlinks=False):
            continue
        directory = entry.path
        manifest_path = os.path.join(directory, "manifest.json")
        if not os.path.exists(manifest_path):
            # Creation was interrupted before any original could be removed.
            if not os.listdir(directory):
                os.rmdir(directory)
                continue
            raise OSError("An evidence recovery journal needs administrator review")
        with open(manifest_path, encoding="utf-8") as handle:
            manifest = json.load(handle)
        # Journals are private server files. Still reject unsafe paths/corruption.
        for item in manifest["files"]:
            for key in ("name", "backup"):
                name = item[key]
                if not isinstance(name, str) or name in ("", ".", "..") or os.path.basename(name) != name:
                    raise ValueError("Invalid evidence recovery journal")
        state = _transaction_state(cursor, manifest)
        if state == "original":
            _restore(directory, evidence_dir, manifest)
        elif state != "archived":
            raise OSError("Evidence recovery metadata needs administrator review")
        # A committed run needs only backup disposal; an uncommitted run was
        # restored above. Unknown/mixed states are never purged automatically.
        _purge(directory, manifest)


def cleanup_evidence(connection, evidence_dir, filter_type):
    """Delete only with recovery copies; roll back the whole batch on failure.

    MySQL must use transactional tables. Backups/journals live on the evidence
    volume so a worker crash does not discard the only remaining photo copy.
    """
    if not isinstance(filter_type, str) or filter_type not in _FILTER_DAYS:
        return None, "Invalid evidence age filter."
    with _LOCK:
        cursor = None
        directory = None
        manifest = None
        committed = False
        try:
            connection.begin()
            cursor = connection.cursor()
            _recover(cursor, evidence_dir)
            days = _FILTER_DAYS[filter_type]
            query = """
                SELECT reportID, photoPath, irTimestamp
                FROM inspection_reports
                WHERE verificationStatus = 'Verified'
                  AND (photoPath IS NULL OR (photoPath NOT LIKE 'archived://%%'
                       AND photoPath NOT LIKE '["archived://%%'))
            """
            params = ()
            if days:
                query += " AND irTimestamp <= %s"
                params = ((datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S"),)
            query += " ORDER BY reportID FOR UPDATE"
            cursor.execute(query, params)
            reports, filenames = [], set()
            for row in cursor.fetchall():
                updated, names = _photo_plan(row["photoPath"])
                if updated != row["photoPath"]:
                    reports.append({"id": row["reportID"], "old": row["photoPath"], "new": updated})
                    filenames.update(names)

            files = []
            for name in sorted(filenames):
                path = os.path.join(evidence_dir, name)
                if os.path.islink(path):
                    raise OSError("Symbolic-link evidence cannot be cleaned automatically")
                if os.path.isfile(path):
                    files.append({"name": name, "backup": f"{len(files)}.bak", "bytes": os.path.getsize(path)})
            manifest = {"reports": reports, "files": files, "ready": False}
            if files:
                directory = tempfile.mkdtemp(prefix=_PREFIX, dir=evidence_dir)
                _write_manifest(directory, manifest)
                for item in files:
                    source = os.path.join(evidence_dir, item["name"])
                    backup = os.path.join(directory, item["backup"])
                    shutil.copy2(source, backup)
                    with open(backup, "rb+") as handle:
                        handle.flush()
                        os.fsync(handle.fileno())
                    if not filecmp.cmp(source, backup, shallow=False):
                        raise OSError("Evidence backup verification failed")
                manifest["ready"] = True
                _write_manifest(directory, manifest)
                # All recovery copies exist before the first destructive action.
                for item in files:
                    os.remove(os.path.join(evidence_dir, item["name"]))
            for row in reports:
                cursor.execute(
                    "UPDATE inspection_reports SET photoPath = %s WHERE reportID = %s",
                    (row["new"], row["id"]),
                )
            connection.commit()
            committed = True

            pending_bytes = 0
            warning = None
            if directory:
                try:
                    _purge(directory, manifest)
                except OSError:
                    pending_bytes = sum(
                        os.path.getsize(os.path.join(directory, item["backup"]))
                        for item in files if os.path.isfile(os.path.join(directory, item["backup"]))
                    )
                    warning = ("Evidence metadata was archived, but recovery backup disposal is pending. "
                               "Not all disk space has been freed. Retry cleanup to finish disposal.")
            freed_bytes = max(0, sum(item["bytes"] for item in files) - pending_bytes)
            freed_mb = round(freed_bytes / (1024 * 1024), 2)
            return {
                "deletedFiles": len(files), "updatedReports": len(reports),
                "freedBytes": freed_bytes, "freedMB": freed_mb,
                "recoveryPending": warning is not None, "warning": warning,
                "message": f"Cleared {len(files)} photo file(s) and archived {len(reports)} report(s), freeing {freed_mb} MB.",
            }, None
        except Exception as exc:
            logger.warning("Evidence cleanup stopped (%s)", type(exc).__name__)
            if not committed:
                rolled_back = False
                try:
                    connection.rollback()
                    rolled_back = True
                except Exception:
                    logger.error("Evidence cleanup database rollback could not be confirmed")
                if directory and manifest:
                    try:
                        # A network error can be raised *after* MySQL commits.
                        # Verify persisted state before restoring or discarding
                        # anything, rather than assuming the commit failed.
                        if not rolled_back:
                            raise OSError("Database outcome is uncertain")
                        connection.begin()
                        if _transaction_state(cursor, manifest) != "original":
                            raise OSError("Database outcome needs recovery verification")
                        _restore(directory, evidence_dir, manifest)
                        _purge(directory, manifest)
                    except Exception:
                        logger.error("Evidence recovery copies retained for a later recovery attempt")
                        return None, "Cleanup stopped. Evidence recovery copies are retained; contact an administrator before retrying."
                    finally:
                        try:
                            connection.rollback()
                        except Exception:
                            logger.error("Evidence recovery verification transaction could not be closed")
            return None, "Cleanup stopped safely. No cleanup success was confirmed; retry or contact an administrator."
        finally:
            if cursor is not None:
                try:
                    cursor.close()
                except Exception:
                    logger.warning("Evidence cleanup cursor could not be closed")
