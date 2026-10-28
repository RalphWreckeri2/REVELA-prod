import json
import os
import re
import shutil
import tarfile
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit

import mysql.connector

from recovery.audit import inspect_database
from recovery.crypto import sha256
from recovery.locking import lock
from recovery.mysqltools import run_dump
from recovery.status import stamp
from recovery.settings import ROOT


def referenced_files(values):
    names, archived = set(), 0
    for raw in values:
        if not raw:
            continue
        try:
            paths = json.loads(raw)
        except (ValueError, TypeError):
            paths = raw
        if not isinstance(paths, list):
            paths = [paths]
        for value in paths:
            if value in (None, "", "none", "no-photo"):
                continue
            if not isinstance(value, str):
                raise ValueError("unsupported_file_reference")
            if value.startswith("archived://"):
                archived += 1
                continue
            path = urlsplit(value).path
            name = path.rsplit("/", 1)[-1]
            if ("/api/inspections/public-evidence/" not in path
                    or not re.fullmatch(r"[0-9a-f]{32}\.(?:jpg|jpeg|png|webp)", name)):
                raise ValueError("unsupported_file_reference")
            names.add(name)
    return names, archived


def file_inventory(directory):
    result = {}
    for path in sorted(directory.rglob("*")):
        if path.is_symlink():
            raise ValueError("symlinks_are_not_backup_payloads")
        if path.is_file():
            result[path.relative_to(directory).as_posix()] = {
                "bytes": path.stat().st_size, "sha256": sha256(path)}
    return result


def pack(payload, archive, metadata):
    manifest = {**metadata, "format": 1, "files": file_inventory(payload)}
    (payload / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    with tarfile.open(archive, "w:gz") as tar:
        for path in sorted(payload.rglob("*")):
            if path.is_file():
                tar.add(path, arcname=path.relative_to(payload).as_posix(), recursive=False)
    return manifest


def capture(settings, config, payload, run_id):
    payload.mkdir(mode=0o700)
    # Only the dump/copy phase holds the fence. Compression, encryption and S3
    # retries do not block inspectors. Other database writes continue normally.
    with lock("evidence", directory=settings.state, timeout=30):
        if not settings.evidence.is_dir():
            raise RuntimeError("evidence_directory_missing")
        recovery_point = stamp()  # conservative lower bound, BEFORE the dump snapshot
        with mysql.connector.connect(**config) as connection:
            audit = inspect_database(connection)
            if any(row["engine"] not in (None, "InnoDB") for row in audit["tables"]):
                raise RuntimeError("non_transactional_tables_require_different_backup_method")
            names, archived = referenced_files(audit.pop("evidence_metadata"))
            cursor = connection.cursor()
            cursor.execute("SELECT @@server_uuid")
            source_uuid = cursor.fetchone()[0]
            cursor.execute("SELECT TABLE_NAME FROM information_schema.tables WHERE table_schema=DATABASE()")
            table_names = sorted(row[0] for row in cursor.fetchall())
            cursor.close()
        for name in names:
            if not (settings.evidence / name).is_file():
                raise RuntimeError("referenced_evidence_missing")
        run_dump(settings.mysqldump, config, payload / "database.sql", audit["server"]["version"])
        evidence = payload / "evidence"
        evidence.mkdir()
        for source in sorted(settings.evidence.rglob("*")):
            if source.is_symlink():
                raise RuntimeError("evidence_symlink_not_supported")
            destination = evidence / source.relative_to(settings.evidence)
            if source.is_dir():
                destination.mkdir(exist_ok=True)
            elif source.is_file():
                shutil.copy2(source, destination)
            else:
                raise RuntimeError("unsupported_evidence_file")
        policy = Path(os.getenv("WLC_CONFIG_FILE", str(ROOT / "api" / "analytics" / "wlc_config.json")))
        policy_coverage = "built-in default; no writable policy file present"
        if policy.is_symlink():
            raise RuntimeError("policy_symlink_not_supported")
        if policy.is_file():
            directory = payload / "runtime-config"
            directory.mkdir()
            shutil.copy2(policy, directory / "wlc_config.json")
            policy_coverage = "runtime-config/wlc_config.json (live writable policy)"
        # Includes unreferenced uploads and cleanup journals, so a complete file
        # set exists for the dump even if a non-file-writing transaction commits.
        metadata = {
            "kind": "database_and_evidence", "id": run_id, "environment": settings.environment,
            "recovery_point": recovery_point, "capture_completed_at": stamp(),
            "database": config["database"], "source_server_uuid": source_uuid,
            "mysql": audit["server"], "tables": table_names,
            "binary_log_position_advisory_only": audit.get("binary_log_position"),
            "coverage": {"database": "all tables, views, triggers, routines and events",
                         "files": "entire evidence directory, including unattached uploads and cleanup journals",
                         "referenced_live_files": len(names), "legacy_archived_references": archived,
                         "source_and_releases": "separate release escrow job",
                         "mobile_pending": "device-local; not yet server data",
                         "pitr": "not configured"},
        }
        metadata["coverage"]["runtime_policy"] = policy_coverage
        metadata["coverage"]["registry_originals"] = "future uploads under .registry-imports when BACKUP_ENABLED=1; pre-existing originals unavailable"
    return metadata


def unpack_verified(archive, destination):
    """Extract only a new private directory; reject traversal, links and extras."""
    destination = Path(destination)
    destination.mkdir(mode=0o700, exist_ok=False)
    with tarfile.open(archive, "r:gz") as tar:
        seen = set()
        for member in tar:
            path = PurePosixPath(member.name)
            if (not member.isfile() or path.is_absolute() or ".." in path.parts
                    or "\\" in member.name or ":" in member.name or member.name in seen):
                raise ValueError("unsafe_archive_member")
            seen.add(member.name)
            target = destination.joinpath(*path.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            with tar.extractfile(member) as source, target.open("xb") as output:
                shutil.copyfileobj(source, output)
    manifest = json.loads((destination / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("format") != 1:
        raise ValueError("unsupported_manifest")
    actual = file_inventory(destination)
    actual.pop("manifest.json", None)
    if actual != manifest["files"]:
        raise ValueError("payload_checksum_mismatch")
    return manifest
