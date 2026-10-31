"""Filesystem S3 double used ONLY by the isolated drill and tests, never deployment."""
import io
import uuid
from pathlib import Path

from botocore.exceptions import ClientError


class FixtureS3:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.objects = {}
        self.deleted = []
        self.fail_uploads = False

    def get_public_access_block(self, **_):
        return {"PublicAccessBlockConfiguration": dict.fromkeys(
            ("BlockPublicAcls", "IgnorePublicAcls", "BlockPublicPolicy", "RestrictPublicBuckets"), True)}

    def get_bucket_versioning(self, **_):
        return {"Status": "Enabled"}

    def get_object_lock_configuration(self, **_):
        return {"ObjectLockConfiguration": {"ObjectLockEnabled": "Disabled"}}

    def get_bucket_lifecycle_configuration(self, **_):
        return {"Rules": [{
            "Status": "Enabled",
            "Filter": {"Prefix": "municipal-test/database-exports-v1/control/status.json"},
            "NoncurrentVersionExpiration": {"NoncurrentDays": 7},
        }]}

    def put_object(self, Key, Body, Metadata, ServerSideEncryption, **kwargs):
        if self.fail_uploads:
            raise OSError("synthetic storage outage")
        version = uuid.uuid4().hex
        destination = self.directory / "versions" / version
        destination.parent.mkdir(exist_ok=True)
        destination.write_bytes(Body.read())
        entry = {"VersionId": version, "Metadata": Metadata, "path": destination,
                 "ServerSideEncryption": ServerSideEncryption}
        if "SSEKMSKeyId" in kwargs:
            entry["SSEKMSKeyId"] = kwargs["SSEKMSKeyId"]
        self.objects.setdefault(Key, []).append(entry)
        return {"VersionId": version}

    def _entry(self, Key, VersionId=None):
        entries = self.objects.get(Key, [])
        matching = [entry for entry in entries if VersionId is None or entry["VersionId"] == VersionId]
        if not matching:
            raise ClientError({"Error": {"Code": "NoSuchKey"}}, "GetObject")
        return matching[-1]

    def head_object(self, Key, VersionId=None, **_):
        entry = self._entry(Key, VersionId)
        return {**entry, "ContentLength": entry["path"].stat().st_size}

    def get_object(self, Key, VersionId=None, **_):
        entry = self._entry(Key, VersionId)
        return {**self.head_object(Key, VersionId), "Body": io.BytesIO(entry["path"].read_bytes())}

    def list_objects_v2(self, Prefix, **_):
        return {"Contents": [{"Key": key} for key, versions in self.objects.items() if versions and key.startswith(Prefix)],
                "IsTruncated": False}

    def delete_object(self, Key, VersionId, **_):
        entry = self._entry(Key, VersionId)
        self.objects[Key].remove(entry)
        self.deleted.append((Key, VersionId))
        # Keep physical synthetic evidence for audit of the test itself.
        return {}
