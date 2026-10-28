"""Private, durable database exports in a dedicated, feature-owned S3 prefix."""
import base64
import hashlib
import io
import json
import re
from datetime import datetime, timedelta

from botocore.exceptions import ClientError

from recovery.crypto import CHUNK, sha256
from recovery.storage import retry
from recovery import status

FEATURE = "revela-db-export-v1"


class BackupNotFound(ValueError):
    pass


class DatabaseStorage:
    def __new__(cls, settings=None):
        if cls is DatabaseStorage and settings is not None and settings.storage_backend == "volume":
            from recovery.volume_storage import VolumeDatabaseStorage
            return VolumeDatabaseStorage(settings)
        return super().__new__(cls)

    def __init__(self, settings):
        import boto3
        from botocore.config import Config
        self.settings = settings
        self.s3 = boto3.client("s3", region_name=settings.region, config=Config(
            connect_timeout=5, read_timeout=30, retries={"mode": "standard", "max_attempts": 2}))

    def _request(self, key=None, version=None):
        result = {"Bucket": self.settings.bucket, "ExpectedBucketOwner": self.settings.account}
        if key is not None:
            result["Key"] = key
        if version is not None:
            result["VersionId"] = version
        return result

    def read_shared_status(self):
        key = self.settings.prefix + "control/status.json"
        try:
            response = retry(lambda: self.s3.get_object(**self._request(key)))
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in ("NoSuchKey", "NoSuchVersion", "404"):
                return None
            raise
        body = response["Body"]
        try:
            raw = body.read(2 * 1024 * 1024 + 1)
        finally:
            body.close()
        if len(raw) > 2 * 1024 * 1024:
            raise ValueError("invalid_shared_backup_status")
        envelope = json.loads(raw)
        if (envelope.get("feature") != FEATURE
                or envelope.get("storage_identity") != self.settings.identity
                or not isinstance(envelope.get("state"), dict)):
            raise ValueError("invalid_shared_backup_status")
        return envelope["state"]

    def write_shared_status(self, state):
        key = self.settings.prefix + "control/status.json"
        envelope = {"feature": FEATURE, "storage_identity": self.settings.identity, "state": state}
        body = json.dumps(envelope, separators=(",", ":"), sort_keys=True).encode("utf-8")
        digest = hashlib.sha256(body).hexdigest()
        encryption = ({"ServerSideEncryption": "aws:kms", "SSEKMSKeyId": self.settings.kms_key}
                      if self.settings.kms_key else {"ServerSideEncryption": "AES256"})
        response = retry(lambda: self.s3.put_object(
            **self._request(key), Body=io.BytesIO(body), ContentLength=len(body),
            ChecksumSHA256=base64.b64encode(bytes.fromhex(digest)).decode(),
            Metadata={"feature": FEATURE, "kind": "shared-status", "sha256": digest},
            **encryption,
        ))
        version = response.get("VersionId")
        if not version or version == "null":
            raise ValueError("versioned_backup_storage_required")
        head = retry(lambda: self.s3.head_object(**self._request(key, version)))
        if (head.get("ContentLength") != len(body)
                or head.get("Metadata", {}).get("sha256") != digest
                or head.get("ServerSideEncryption") != encryption["ServerSideEncryption"]
                or (self.settings.kms_key and head.get("SSEKMSKeyId") != self.settings.kms_key)):
            raise ValueError("shared_backup_status_verification_failed")

    def preflight(self):
        request = self._request()
        block = retry(lambda: self.s3.get_public_access_block(**request))["PublicAccessBlockConfiguration"]
        if not all(block.get(k) for k in ("BlockPublicAcls", "IgnorePublicAcls", "BlockPublicPolicy", "RestrictPublicBuckets")):
            raise ValueError("private_bucket_required")
        if retry(lambda: self.s3.get_bucket_versioning(**request)).get("Status") != "Enabled":
            raise ValueError("versioned_backup_bucket_required")
        try:
            lock = self.s3.get_object_lock_configuration(**request).get("ObjectLockConfiguration", {})
        except ClientError as exc:
            if exc.response["Error"]["Code"] not in ("ObjectLockConfigurationNotFoundError", "NoSuchObjectLockConfiguration"):
                raise
            lock = {}
        retention = lock.get("Rule", {}).get("DefaultRetention", {})
        if retention.get("Years", 0) or retention.get("Days", 0) > 7:
            raise ValueError("bucket_retention_exceeds_seven_days_use_a_separate_bucket")
        try:
            rules = retry(lambda: self.s3.get_bucket_lifecycle_configuration(**request)).get("Rules", [])
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") != "NoSuchLifecycleConfiguration":
                raise
            rules = []
        status_key = self.settings.prefix + "control/status.json"
        status_rule = next((rule for rule in rules
                            if rule.get("Status") == "Enabled"
                            and (rule.get("Prefix") == status_key
                                 or rule.get("Filter", {}).get("Prefix") == status_key)), None)
        noncurrent_days = (status_rule or {}).get("NoncurrentVersionExpiration", {}).get("NoncurrentDays")
        if (not isinstance(noncurrent_days, int) or not 1 <= noncurrent_days <= 7
                or (status_rule or {}).get("Expiration")):
            raise ValueError("shared_status_noncurrent_lifecycle_required")
        for rule in rules:
            if rule.get("Status") != "Enabled":
                continue
            rule_prefix = rule.get("Prefix", rule.get("Filter", {}).get("Prefix", ""))
            overlaps_feature = (self.settings.prefix.startswith(rule_prefix)
                                or rule_prefix.startswith(self.settings.prefix))
            applies_to_data = (overlaps_feature and rule_prefix != status_key)
            if applies_to_data and (rule.get("Expiration") or rule.get("NoncurrentVersionExpiration")):
                raise ValueError("backup_data_lifecycle_expiration_not_allowed")
        # Checks actual prefix read/list permission without changing any bucket policy.
        retry(lambda: self.s3.list_objects_v2(**request, Prefix=self.settings.prefix + "records/", MaxKeys=1))

    def _metadata(self, identifier, digest):
        return {"feature": FEATURE, "backup-id": identifier, "sha256": digest,
                "environment": self.settings.environment}

    def _put(self, source, key, identifier):
        digest, size = sha256(source), source.stat().st_size
        if size > 5 * 1024 ** 3:
            raise ValueError("export_exceeds_five_gib_upload_limit")
        encryption = {"ServerSideEncryption": "aws:kms", "SSEKMSKeyId": self.settings.kms_key} if self.settings.kms_key else {"ServerSideEncryption": "AES256"}
        def upload():
            with source.open("rb") as stream:
                return self.s3.put_object(**self._request(key), Body=stream, ContentLength=size,
                                          ChecksumSHA256=base64.b64encode(bytes.fromhex(digest)).decode(),
                                          Metadata=self._metadata(identifier, digest), **encryption)
        result = retry(upload)
        version = result.get("VersionId")
        if not version or version == "null":
            raise ValueError("versioned_upload_required")
        request = self._request(key, version)
        head = retry(lambda: self.s3.head_object(**request))
        if (head["ContentLength"] != size or head.get("Metadata") != self._metadata(identifier, digest)
                or head.get("ServerSideEncryption") != encryption["ServerSideEncryption"]
                or (self.settings.kms_key and head.get("SSEKMSKeyId") != self.settings.kms_key)):
            raise ValueError("uploaded_export_verification_failed")
        def verify():
            response = self.s3.get_object(**request)
            actual = hashlib.sha256()
            body = response["Body"]
            try:
                for chunk in iter(lambda: body.read(CHUNK), b""):
                    actual.update(chunk)
            finally:
                body.close()
            if actual.hexdigest() != digest:
                raise ValueError("uploaded_export_checksum_mismatch")
        retry(verify)
        return {"key": key, "version_id": version, "sha256": digest, "bytes": size}

    def publish(self, archive, record, work):
        record["object"] = self._put(archive, self.settings.prefix + "files/" + record["filename"], record["id"])
        record["completed_at"] = status.stamp()
        receipt = work / "receipt.json"
        receipt.write_text(json.dumps(record, indent=2), encoding="utf-8")
        # Only this commit marker makes an export available/listable/prunable.
        self._put(receipt, self.settings.prefix + "records/" + record["id"] + ".json", record["id"])
        return record

    def _load(self, identifier):
        if not re.fullmatch(r"[0-9a-f]{32}", identifier):
            raise BackupNotFound("backup_not_found")
        request = self._request(self.settings.prefix + "records/" + identifier + ".json")
        try:
            response = retry(lambda: self.s3.get_object(**request))
        except ClientError as exc:
            if exc.response["Error"]["Code"] in ("NoSuchKey", "NoSuchVersion", "404"):
                raise BackupNotFound("backup_not_found") from None
            raise
        body = response["Body"]
        try:
            raw = body.read(1024 * 1024 + 1)
        finally:
            body.close()
        if len(raw) > 1024 * 1024:
            raise ValueError("invalid_backup_receipt")
        record = json.loads(raw)
        expected_filename = r"revela-db_\d{8}_\d{6}_PHT_" + identifier + r"\.sql\.gz"
        if (record.get("feature") != FEATURE or record.get("id") != identifier
                or record.get("environment") != self.settings.environment
                or record.get("storage_identity") != self.settings.identity
                or not re.fullmatch(expected_filename, record.get("filename", ""))
                or record.get("object", {}).get("key") != self.settings.prefix + "files/" + record["filename"]
                or not record.get("object", {}).get("version_id")
                or response.get("Metadata") != self._metadata(identifier, hashlib.sha256(raw).hexdigest())):
            raise ValueError("invalid_backup_receipt")
        # Validate age fields before retention is ever considered.
        if datetime.fromisoformat(record["completed_at"]).tzinfo is None:
            raise ValueError("invalid_backup_timestamp")
        record["receipt_version_id"] = response["VersionId"]
        return record

    def _head(self, record):
        obj = record["object"]
        try:
            head = retry(lambda: self.s3.head_object(**self._request(obj["key"], obj["version_id"])))
        except ClientError as exc:
            if exc.response["Error"]["Code"] in ("NoSuchKey", "NoSuchVersion", "404"):
                return None
            raise
        if (head.get("Metadata") != self._metadata(record["id"], obj["sha256"])
                or head.get("ContentLength") != obj["bytes"]
                or head.get("ServerSideEncryption") not in ("AES256", "aws:kms")):
            raise ValueError("backup_file_metadata_mismatch")
        return head

    def records(self, available_only=True):
        result, token = [], None
        while True:
            request = {**self._request(), "Prefix": self.settings.prefix + "records/"}
            if token:
                request["ContinuationToken"] = token
            response = retry(lambda: self.s3.list_objects_v2(**request))
            for entry in response.get("Contents", []):
                name = entry["Key"][len(request["Prefix"]):]
                if re.fullmatch(r"[0-9a-f]{32}\.json", name):
                    record = self._load(name[:-5])
                    if not available_only or self._head(record):
                        result.append(record)
            if not response.get("IsTruncated"):
                break
            token = response["NextContinuationToken"]
        return sorted(result, key=lambda row: datetime.fromisoformat(row["completed_at"]), reverse=True)

    def prune(self, successful):
        # No caller can prune on a failed/unpublished export. Verify the new
        # committed receipt and file again before considering any deletion.
        committed = self._load(successful["id"])
        if committed["object"] != successful["object"] or not self._head(committed):
            raise ValueError("new_success_required_before_pruning")
        records = self.records(available_only=False)
        available = [row for row in records if self._head(row)]
        source_records = [row for row in available
                          if row.get("source_server_uuid") == successful["source_server_uuid"]]
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
                    or row.get("source_server_uuid") != successful["source_server_uuid"]
                    or completed >= datetime.fromisoformat(successful["completed_at"])):
                continue
            if row.get("scheduled") is not True and completed >= manual_cutoff:
                continue
            obj = row["object"]
            # Exact versions only; never delete markers, broad prefixes, old
            # bundle archives, manual exports, or provider/lifecycle settings.
            if self._head(row):
                retry(lambda: self.s3.delete_object(**self._request(obj["key"], obj["version_id"])))
            retry(lambda: self.s3.delete_object(**self._request(
                self.settings.prefix + "records/" + row["id"] + ".json", row["receipt_version_id"])))
            removed.append(row["id"])
        return removed

    def download(self, identifier):
        record = self._load(identifier)
        if not self._head(record):
            raise BackupNotFound("backup_not_found")
        response = retry(lambda: self.s3.get_object(**self._request(
            record["object"]["key"], record["object"]["version_id"])))
        return record, response["Body"]
