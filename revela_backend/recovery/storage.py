"""Append-only S3 writer. No deletion, pruning, retention shortening or bypass."""
import base64
import hashlib
import time
from datetime import timedelta

from recovery.crypto import CHUNK, sha256
from recovery.status import now


def retry(operation, attempts=3, sleep=time.sleep):
    for attempt in range(attempts):
        try:
            return operation()
        except Exception:
            if attempt == attempts - 1:
                raise
            sleep(2 ** (attempt + 1))


class S3Storage:
    def __init__(self, settings):
        import boto3
        from botocore.config import Config
        self.settings = settings
        self.s3 = boto3.client("s3", region_name=settings.region,
                               config=Config(connect_timeout=10, read_timeout=120,
                                             retries={"mode": "standard", "max_attempts": 3}))

    def preflight(self):
        cfg = self.settings
        owner = {"Bucket": cfg.bucket, "ExpectedBucketOwner": cfg.account}
        if self.s3.get_bucket_versioning(**owner).get("Status") != "Enabled":
            raise RuntimeError("bucket_versioning_required")
        lock = self.s3.get_object_lock_configuration(**owner)["ObjectLockConfiguration"]
        if lock.get("ObjectLockEnabled") != "Enabled":
            raise RuntimeError("bucket_object_lock_required")
        block = self.s3.get_public_access_block(**owner)["PublicAccessBlockConfiguration"]
        if not all(block.get(k) for k in ("BlockPublicAcls", "IgnorePublicAcls",
                                         "BlockPublicPolicy", "RestrictPublicBuckets")):
            raise RuntimeError("bucket_public_access_block_required")
        if not 1 <= cfg.lock_days <= 36500 or len(cfg.account) != 12:
            raise ValueError("invalid_storage_configuration")

    def put_verified(self, source, key):
        cfg = self.settings
        digest = sha256(source)
        size = source.stat().st_size
        if size > 5 * 1024 ** 3:
            raise RuntimeError("bundle_exceeds_single_put_limit")
        # S3 validates the SHA256 in transit. Re-open the stream on each retry.
        def upload():
            with source.open("rb") as stream:
                return self.s3.put_object(
                    Bucket=cfg.bucket, Key=key, Body=stream, ContentLength=size,
                    ExpectedBucketOwner=cfg.account, ServerSideEncryption="aws:kms",
                    SSEKMSKeyId=cfg.kms_key, ObjectLockMode="GOVERNANCE",
                    ObjectLockRetainUntilDate=now() + timedelta(days=cfg.lock_days),
                    ChecksumSHA256=base64.b64encode(bytes.fromhex(digest)).decode(),
                    Metadata={"sha256": digest},
                )
        uploaded = retry(upload)
        version = uploaded.get("VersionId")
        if not version or version == "null":
            raise RuntimeError("versioned_upload_required")
        request = dict(Bucket=cfg.bucket, Key=key, VersionId=version,
                       ExpectedBucketOwner=cfg.account)
        head = retry(lambda: self.s3.head_object(**request))
        if (head["ContentLength"] != size or head.get("Metadata", {}).get("sha256") != digest
                or head.get("ServerSideEncryption") != "aws:kms"
                or head.get("SSEKMSKeyId") != cfg.kms_key
                or head.get("ObjectLockMode") != "GOVERNANCE"
                or head.get("ObjectLockRetainUntilDate", now()) < now() + timedelta(days=cfg.lock_days, minutes=-5)):
            raise RuntimeError("remote_object_protection_verification_failed")

        def readback():
            body = self.s3.get_object(**request)["Body"]
            actual = hashlib.sha256()
            try:
                for chunk in iter(lambda: body.read(CHUNK), b""):
                    actual.update(chunk)
            finally:
                body.close()
            if actual.hexdigest() != digest:
                raise RuntimeError("remote_checksum_mismatch")
        retry(readback)
        return {"key": key, "version_id": version, "sha256": digest, "bytes": size}
