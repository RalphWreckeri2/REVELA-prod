import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def evidence_directory():
    return Path(os.getenv("EVIDENCE_DIR", str(ROOT / "instance" / "inspection_evidence"))).resolve()


def state_directory():
    return Path(os.getenv("BACKUP_STATE_DIR", str(ROOT / "instance" / "recovery"))).resolve()


def enabled():
    # Retired bundle/file-capture path. BACKUP_ENABLED can never restart it.
    return False


def database_enabled():
    return os.getenv("DB_BACKUP_ENABLED", "0") == "1" and not pc_managed()


def schedule_enabled():
    return database_enabled() and os.getenv("DB_BACKUP_SCHEDULE_ENABLED", "0") == "1"


def cleanup_enabled():
    return database_enabled() and os.getenv("DB_BACKUP_CLEANUP_ENABLED", "0") == "1"


def pc_managed():
    return os.getenv("DB_BACKUP_MODE", "cloud").strip().lower() == "windows_pc"


def scheduler_mode():
    return os.getenv("DB_BACKUP_SCHEDULER_MODE", "in_process").strip().lower()


def backup_role():
    return os.getenv("DB_BACKUP_ROLE", "api").strip().lower()


def database_state_directory():
    # Separate ledger: never interpret/prune the old bundle backup history.
    return Path(os.getenv("DB_BACKUP_STATE_DIR", str(ROOT / "instance" / "database-backups"))).resolve()


def configuration_issues():
    backend = os.getenv("DB_BACKUP_STORAGE", "s3").strip().lower()
    required = ("BACKUP_ENVIRONMENT",
                "BACKUP_ALERT_WEBHOOK", "BACKUP_HEARTBEAT_URL",
                "BACKUP_DB_HOST", "BACKUP_DB_PORT", "BACKUP_DB_NAME",
                "BACKUP_DB_USER", "BACKUP_DB_PASSWORD", "DB_BACKUP_ROLE")
    if backend == "s3":
        required += ("BACKUP_S3_BUCKET", "AWS_REGION", "BACKUP_AWS_ACCOUNT_ID", "BACKUP_WORK_DIR")
    elif backend == "volume":
        required += ("DB_BACKUP_VOLUME_DIR", "DB_BACKUP_MIN_FREE_BYTES")
    else:
        return [f"DB_BACKUP_STORAGE must be s3 or volume (got {backend or 'empty'})"]
    issues = [f"Missing {name}" for name in required if not os.getenv(name, "").strip()]
    if os.getenv("BACKUP_ENVIRONMENT") and not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", os.environ["BACKUP_ENVIRONMENT"]):
        issues.append("BACKUP_ENVIRONMENT must contain only letters, numbers, underscores and hyphens")
    if backend == "s3" and os.getenv("BACKUP_AWS_ACCOUNT_ID") and not re.fullmatch(r"\d{12}", os.environ["BACKUP_AWS_ACCOUNT_ID"]):
        issues.append("BACKUP_AWS_ACCOUNT_ID must be 12 digits")
    if backend == "volume" and os.getenv("DB_BACKUP_VOLUME_DIR"):
        volume = Path(os.environ["DB_BACKUP_VOLUME_DIR"])
        require_mount = os.getenv("DB_BACKUP_VOLUME_REQUIRE_MOUNT", "1")
        if require_mount not in ("0", "1"):
            issues.append("DB_BACKUP_VOLUME_REQUIRE_MOUNT must be 0 or 1")
        if ("production" in os.getenv("BACKUP_ENVIRONMENT", "").lower() and require_mount != "1"):
            issues.append("DB_BACKUP_VOLUME_REQUIRE_MOUNT must be 1 for production")
        if not volume.is_dir():
            issues.append("DB_BACKUP_VOLUME_DIR must identify the configured Railway volume mount")
        elif require_mount == "1" and not os.path.ismount(volume):
            issues.append("DB_BACKUP_VOLUME_DIR is not a mounted volume")
        try:
            if int(os.environ.get("DB_BACKUP_MIN_FREE_BYTES", "0")) <= 0:
                raise ValueError
        except ValueError:
            issues.append("DB_BACKUP_MIN_FREE_BYTES must be a positive integer")
    if os.getenv("BACKUP_DB_PORT"):
        try:
            if not 1 <= int(os.environ["BACKUP_DB_PORT"]) <= 65535:
                raise ValueError
        except ValueError:
            issues.append("BACKUP_DB_PORT must be a valid TCP port")
    if os.getenv("BACKUP_DB_HOST") and os.environ["BACKUP_DB_HOST"] not in ("localhost", "127.0.0.1", "::1"):
        ca = os.getenv("BACKUP_DB_SSL_CA_FILE", "").strip()
        if not ca:
            issues.append("Missing BACKUP_DB_SSL_CA_FILE for remote database TLS verification")
        elif not Path(ca).is_file():
            issues.append("BACKUP_DB_SSL_CA_FILE must identify an installed CA file")
    if backend == "s3" and os.getenv("BACKUP_WORK_DIR") and not Path(os.environ["BACKUP_WORK_DIR"]).is_dir():
        issues.append("BACKUP_WORK_DIR must be an existing private workspace")
    for name in ("BACKUP_ALERT_WEBHOOK", "BACKUP_HEARTBEAT_URL"):
        if os.getenv(name) and not os.environ[name].startswith("https://"):
            issues.append(f"{name} must use HTTPS")
    if not shutil.which(os.getenv("MYSQLDUMP_BIN", "mysqldump")):
        issues.append("MYSQLDUMP_BIN must identify an installed matching Oracle MySQL client")
    if scheduler_mode() not in ("in_process", "railway_cron", "external_api"):
        issues.append("DB_BACKUP_SCHEDULER_MODE must be in_process, railway_cron, or external_api")
    if backup_role() not in ("api", "worker"):
        issues.append("DB_BACKUP_ROLE must be api or worker")
    if os.getenv("DB_BACKUP_SCHEDULE_ENABLED", "0") not in ("0", "1"):
        issues.append("DB_BACKUP_SCHEDULE_ENABLED must be 0 or 1")
    if os.getenv("DB_BACKUP_CLEANUP_ENABLED", "0") not in ("0", "1"):
        issues.append("DB_BACKUP_CLEANUP_ENABLED must be 0 or 1")
    if os.getenv("DB_BACKUP_EXTERNAL_TRIGGER_ENABLED", "0") not in ("0", "1"):
        issues.append("DB_BACKUP_EXTERNAL_TRIGGER_ENABLED must be 0 or 1")
    if (os.getenv("DB_BACKUP_EXTERNAL_TRIGGER_ENABLED") == "1"
            and not re.fullmatch(r"[A-Za-z0-9_-]{32,256}", os.getenv("DB_BACKUP_TRIGGER_TOKEN", ""))):
        issues.append("DB_BACKUP_TRIGGER_TOKEN must be 32-256 URL-safe characters when the external trigger is enabled")
    return issues


@dataclass(frozen=True)
class DatabaseSettings:
    state: Path
    work: Path
    environment: str
    bucket: str
    region: str
    account: str
    kms_key: str
    mysqldump: str
    alert_url: str
    heartbeat_url: str
    storage_backend: str = "s3"
    volume_directory: Path | None = None
    volume_min_free_bytes: int = 0
    volume_require_mount: bool = True

    @property
    def prefix(self):
        return f"{self.environment}/database-exports-v1/"

    @property
    def identity(self):
        import hashlib
        if self.storage_backend == "volume":
            return hashlib.sha256(f"{self.volume_directory}/{self.prefix}".encode()).hexdigest()
        return hashlib.sha256(f"{self.bucket}/{self.prefix}".encode()).hexdigest()

    @classmethod
    def from_env(cls):
        issues = configuration_issues()
        if issues:
            raise ValueError("database_backup_configuration_missing")
        backend = os.getenv("DB_BACKUP_STORAGE", "s3").strip().lower()
        volume = Path(os.environ["DB_BACKUP_VOLUME_DIR"]).absolute() if backend == "volume" else None
        root = volume / "revela-database-backups" if volume else None
        return cls(
            state=(root / "state" if root else database_state_directory()),
            work=(root / "work" if root else Path(os.environ["BACKUP_WORK_DIR"]).resolve()),
            environment=os.environ["BACKUP_ENVIRONMENT"],
            bucket=os.getenv("BACKUP_S3_BUCKET", ""),
            region=os.getenv("AWS_REGION", ""),
            account=os.getenv("BACKUP_AWS_ACCOUNT_ID", ""),
            kms_key=os.getenv("BACKUP_KMS_KEY_ARN", ""),
            mysqldump=os.getenv("MYSQLDUMP_BIN", "mysqldump"),
            alert_url=os.environ["BACKUP_ALERT_WEBHOOK"],
            heartbeat_url=os.environ["BACKUP_HEARTBEAT_URL"],
            storage_backend=backend,
            volume_directory=volume,
            volume_min_free_bytes=int(os.environ.get("DB_BACKUP_MIN_FREE_BYTES", "0")),
            volume_require_mount=os.getenv("DB_BACKUP_VOLUME_REQUIRE_MOUNT", "1") == "1",
        )


@dataclass(frozen=True)
class Settings:
    evidence: Path
    state: Path
    work: Path
    public_key: Path
    environment: str
    bucket: str
    region: str
    account: str
    kms_key: str
    lock_days: int
    mysqldump: str
    alert_url: str
    heartbeat_url: str
    daily_heartbeat_url: str

    @classmethod
    def from_env(cls):
        return cls(
            evidence_directory(), state_directory(),
            Path(os.environ["BACKUP_WORK_DIR"]).resolve(),
            Path(os.environ["BACKUP_PUBLIC_KEY_FILE"]).resolve(),
            os.environ["BACKUP_ENVIRONMENT"], os.environ["BACKUP_S3_BUCKET"],
            os.environ["AWS_REGION"], os.environ["BACKUP_AWS_ACCOUNT_ID"],
            os.environ["BACKUP_KMS_KEY_ARN"], int(os.environ["BACKUP_MIN_LOCK_DAYS"]),
            os.getenv("MYSQLDUMP_BIN", "mysqldump"),
            os.environ["BACKUP_ALERT_WEBHOOK"], os.environ["BACKUP_HEARTBEAT_URL"],
            os.environ["BACKUP_DAILY_HEARTBEAT_URL"],
        )
