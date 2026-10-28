"""Private, atomic database exports on one configured persistent volume."""
import hashlib
import json
import os
import re
import shutil
import stat
import uuid
from datetime import datetime, timedelta
from pathlib import Path

from recovery import status
from recovery.db_storage import BackupNotFound, FEATURE


class VolumeDatabaseStorage:
    def __init__(self, settings):
        if settings.storage_backend != "volume" or settings.volume_directory is None:
            raise ValueError("database_backup_volume_not_configured")
        self.settings = settings
        self.mount = settings.volume_directory
        self.root = self.mount / "revela-database-backups"
        self.prefix = settings.prefix
        self.files = self.root / "files"
        self.records_dir = self.root / "records"
        self.control = self.root / "control"

    def _ensure_private_directory(self, directory):
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        if directory.is_symlink() or not directory.is_dir():
            raise ValueError("unsafe_backup_volume_path")
        if os.name != "nt":
            directory.chmod(0o700)

    def _path(self, relative):
        path = (self.root / relative).resolve()
        if not path.is_relative_to(self.root.resolve()):
            raise ValueError("invalid_backup_path")
        current = self.root
        for part in Path(relative).parts:
            current = current / part
            if current.is_symlink():
                raise ValueError("unsafe_backup_volume_path")
        return path

    def _atomic_json(self, path, value):
        temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        raw = json.dumps(value, separators=(",", ":"), sort_keys=True).encode("utf-8")
        try:
            descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
            self._fsync_directory(path.parent)
        finally:
            temporary.unlink(missing_ok=True)

    @staticmethod
    def _fsync_directory(directory):
        if os.name == "nt":
            return
        descriptor = os.open(directory, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    def preflight(self):
        if (self.mount.is_symlink() or not self.mount.is_dir()
                or (self.settings.volume_require_mount and not os.path.ismount(self.mount))):
            raise ValueError("database_backup_volume_mount_required")
        self._ensure_private_directory(self.root)
        for directory in (self.files, self.records_dir, self.control, self.settings.state, self.settings.work):
            self._ensure_private_directory(directory)
        if not os.access(self.root, os.R_OK | os.W_OK | os.X_OK):
            raise ValueError("database_backup_volume_not_writable")
        if shutil.disk_usage(self.mount).free < self.settings.volume_min_free_bytes:
            raise ValueError("database_backup_volume_capacity_below_minimum")
        return {"free_bytes": shutil.disk_usage(self.mount).free, "identity": self.settings.identity}

    def read_shared_status(self):
        path = self._path("control/status.json")
        try:
            descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
            with os.fdopen(descriptor, "rb") as stream:
                raw = stream.read(2 * 1024 * 1024 + 1)
        except FileNotFoundError:
            return None
        if len(raw) > 2 * 1024 * 1024:
            raise ValueError("invalid_shared_backup_status")
        envelope = json.loads(raw)
        if (envelope.get("feature") != FEATURE
                or envelope.get("storage_identity") != self.settings.identity
                or not isinstance(envelope.get("state"), dict)):
            raise ValueError("invalid_shared_backup_status")
        return envelope["state"]

    def write_shared_status(self, state):
        self.preflight()
        self._atomic_json(self.control / "status.json", {
            "feature": FEATURE, "storage_identity": self.settings.identity, "state": state,
        })

    def _file_digest(self, path):
        digest = hashlib.sha256()
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        with os.fdopen(descriptor, "rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
        return digest.hexdigest()

    def publish(self, archive, record, work):
        self.preflight()
        identifier = record["id"]
        if not re.fullmatch(r"[0-9a-f]{32}", identifier):
            raise ValueError("invalid_backup_receipt")
        filename = record["filename"]
        if filename != f"revela-db_{datetime.fromisoformat(record['created_at']).astimezone(status.MANILA):%Y%m%d_%H%M%S}_PHT_{identifier}.sql.gz":
            raise ValueError("invalid_backup_receipt")
        final_file = self._path(f"files/{filename}")
        temporary_file = self._path(f"files/.{identifier}.{uuid.uuid4().hex}.tmp")
        receipt_file = self._path(f"records/{identifier}.json")
        if final_file.exists() or receipt_file.exists():
            raise ValueError("backup_id_already_exists")
        digest = hashlib.sha256()
        size = 0
        try:
            descriptor = os.open(temporary_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with archive.open("rb") as source, os.fdopen(descriptor, "wb") as target:
                for block in iter(lambda: source.read(1024 * 1024), b""):
                    target.write(block)
                    digest.update(block)
                    size += len(block)
                target.flush()
                os.fsync(target.fileno())
            if size <= 0 or self._file_digest(temporary_file) != digest.hexdigest():
                raise ValueError("uploaded_export_checksum_mismatch")
            os.replace(temporary_file, final_file)
            self._fsync_directory(self.files)
        finally:
            temporary_file.unlink(missing_ok=True)

        committed = {
            **record,
            "object": {"key": self.prefix + "files/" + filename,
                       "version_id": "filesystem", "sha256": digest.hexdigest(), "bytes": size},
            "completed_at": status.stamp(),
        }
        self._atomic_json(receipt_file, committed)
        return committed

    def _load(self, identifier):
        if not re.fullmatch(r"[0-9a-f]{32}", identifier):
            raise BackupNotFound("backup_not_found")
        receipt_path = self._path(f"records/{identifier}.json")
        try:
            descriptor = os.open(receipt_path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
            with os.fdopen(descriptor, "rb") as stream:
                raw = stream.read(1024 * 1024 + 1)
        except FileNotFoundError:
            raise BackupNotFound("backup_not_found") from None
        if len(raw) > 1024 * 1024:
            raise ValueError("invalid_backup_receipt")
        record = json.loads(raw)
        expected = r"revela-db_\d{8}_\d{6}_PHT_" + identifier + r"\.sql\.gz"
        obj = record.get("object", {})
        if (record.get("feature") != FEATURE or record.get("id") != identifier
                or record.get("environment") != self.settings.environment
                or record.get("storage_identity") != self.settings.identity
                or not re.fullmatch(expected, record.get("filename", ""))
                or obj.get("key") != self.prefix + "files/" + record["filename"]
                or obj.get("version_id") != "filesystem"
                or not re.fullmatch(r"[0-9a-f]{64}", obj.get("sha256", ""))
                or type(obj.get("bytes")) is not int or obj["bytes"] <= 0):
            raise ValueError("invalid_backup_receipt")
        if datetime.fromisoformat(record["completed_at"]).tzinfo is None:
            raise ValueError("invalid_backup_timestamp")
        return record

    def _head(self, record):
        path = self._path(f"files/{record['filename']}")
        try:
            file_stat = path.lstat()
        except FileNotFoundError:
            return False
        if (not stat.S_ISREG(file_stat.st_mode) or file_stat.st_size != record["object"]["bytes"]
                or path.is_symlink()):
            return False
        return True

    def records(self, available_only=True):
        result = []
        for receipt in self.records_dir.glob("*.json"):
            if not re.fullmatch(r"[0-9a-f]{32}\.json", receipt.name):
                continue
            record = self._load(receipt.stem)
            if not available_only or self._head(record):
                result.append(record)
        return sorted(result, key=lambda row: datetime.fromisoformat(row["completed_at"]), reverse=True)

    def download(self, identifier):
        record = self._load(identifier)
        path = self._path(f"files/{record['filename']}")
        if not self._head(record) or self._file_digest(path) != record["object"]["sha256"]:
            raise BackupNotFound("backup_not_found")
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        return record, os.fdopen(descriptor, "rb")

    def prune(self, successful):
        committed = self._load(successful["id"])
        if (committed["object"] != successful["object"] or not self._head(committed)
                or self._file_digest(self.files / committed["filename"]) != committed["object"]["sha256"]):
            raise ValueError("new_success_required_before_pruning")
        records = self.records(available_only=False)
        available = [row for row in records if self._head(row)]
        source_records = [row for row in available
                          if row.get("source_server_uuid") == successful.get("source_server_uuid")]
        weekly = [row for row in source_records if row.get("scheduled") is True]
        monthly = [row for row in weekly if (
            row.get("monthly_archive") is True
            or status.is_monthly_archive(row.get("scheduled_for"))
        )]
        protected = {row["id"] for row in weekly[:4]}
        protected.update(row["id"] for row in monthly[:3])
        manual_cutoff = status.now() - timedelta(days=30)
        removed = []
        for row in records:
            completed = datetime.fromisoformat(row["completed_at"])
            if (row["id"] in protected
                    or row.get("source_server_uuid") != successful.get("source_server_uuid")
                    or completed >= datetime.fromisoformat(successful["completed_at"])):
                continue
            if row.get("scheduled") is not True and completed >= manual_cutoff:
                continue
            self._path(f"records/{row['id']}.json").unlink(missing_ok=True)
            self._path(f"files/{row['filename']}").unlink(missing_ok=True)
            removed.append(row["id"])
        return removed
