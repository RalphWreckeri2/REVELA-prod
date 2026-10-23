import copy
import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from api.inspections import evidence_cleanup as cleanup


class TransactionStore:
    """Small transactional fake: failed writes cannot change committed rows."""
    def __init__(self, rows):
        self.rows = copy.deepcopy(rows)
        self.pending = None
        self.queries = []
        self.commits = 0
        self.rollbacks = 0
        self.closed = 0
        self.fail_commit = False
        self.fail_update = False
        self.interrupt_commit = False
        self.commit_then_error = False

    def cursor(self):
        self.pending = copy.deepcopy(self.rows)
        return Cursor(self)

    def begin(self):
        self.pending = copy.deepcopy(self.rows)

    def commit(self):
        if self.interrupt_commit:
            raise KeyboardInterrupt("Synthetic worker interruption")
        if self.fail_commit:
            raise RuntimeError("Synthetic database commit failure")
        self.rows = copy.deepcopy(self.pending)
        self.commits += 1
        if self.commit_then_error:
            raise RuntimeError("Synthetic lost commit acknowledgement")

    def rollback(self):
        self.pending = copy.deepcopy(self.rows)
        self.rollbacks += 1


class Cursor:
    def __init__(self, store):
        self.store = store
        self.result = []

    def execute(self, query, params=()):
        self.store.queries.append((query, params))
        if query.startswith("UPDATE"):
            if self.store.fail_update:
                raise RuntimeError("Synthetic metadata write failure")
            value, report_id = params
            self.store.pending[report_id]["photoPath"] = value
        elif "reportID IN" in query:
            self.result = [copy.deepcopy(self.store.pending[i]) for i in params if i in self.store.pending]
        else:
            self.result = [copy.deepcopy(row) for row in self.store.pending.values()
                           if row["verificationStatus"] == "Verified"
                           and not (row["photoPath"] or "").startswith(("archived://", '["archived://'))
                           and (not params or row["irTimestamp"] <= datetime.fromisoformat(params[0]))]

    def fetchall(self):
        return self.result

    def close(self):
        self.store.closed += 1


class EvidenceCleanupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="revela-evidence-test-")
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.rows = {1: {"reportID": 1, "photoPath": "first.jpg", "verificationStatus": "Verified",
                         "irTimestamp": datetime.now() - timedelta(days=400)}}
        self.first = self.directory / "first.jpg"
        self.first.write_bytes(b"original first photo")
        self.store = TransactionStore(self.rows)

    def run_cleanup(self, filter_type="all_verified"):
        return cleanup.cleanup_evidence(self.store, str(self.directory), filter_type)

    def assert_original(self):
        self.assertEqual(self.first.read_bytes(), b"original first photo")
        self.assertEqual(self.store.rows[1]["photoPath"], "first.jpg")

    def http_client(self):
        from flask import Flask
        from api.inspections import routes, service
        from api.middleware import decorators

        app = Flask(__name__)
        app.config["TESTING"] = True
        app.register_blueprint(routes.inspections_bp, url_prefix="/api/inspections")
        values = [
            (decorators, "verify_jwt_in_request", lambda: None),
            (decorators, "get_jwt_identity", lambda: "17"),
            (decorators, "get_jwt", lambda: {"role": "Admin", "session_id": "synthetic"}),
            (decorators, "find_user_by_id", lambda _id: {"isActive": True, "userRole": "Admin"}),
            (decorators, "check_active_session", lambda *_args: (True, None)),
            (routes, "_ensure_evidence_dir", lambda: str(self.directory)),
            (service, "mysql", SimpleNamespace(connection=self.store)),
        ]
        for target, name, value in values:
            patcher = patch.object(target, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        return app.test_client()

    def test_success_deletes_photos_only_with_locked_rows_and_recovery_copies(self):
        result, error = self.run_cleanup()
        self.assertIsNone(error)
        self.assertEqual(result["deletedFiles"], 1)
        self.assertEqual(result["freedBytes"], len(b"original first photo"))
        self.assertFalse(result["recoveryPending"])
        self.assertFalse(self.first.exists())
        self.assertEqual(self.store.rows[1]["photoPath"], "archived://first.jpg")
        self.assertIn("FOR UPDATE", self.store.queries[0][0])
        self.assertEqual(list(self.directory.iterdir()), [])

    def test_invalid_filter_does_not_touch_database_or_files(self):
        result, error = self.run_cleanup("invalid")
        self.assertIsNone(result)
        self.assertTrue(error)
        self.assertEqual(self.store.queries, [])
        self.assert_original()

    def test_deletion_failure_does_not_archive_the_reference(self):
        remove = os.remove
        def fail_original(path):
            if Path(path) == self.first:
                raise PermissionError("Synthetic deletion denied")
            return remove(path)
        with patch.object(cleanup.os, "remove", side_effect=fail_original):
            result, error = self.run_cleanup()
        self.assertIsNone(result)
        self.assertTrue(error)
        self.assert_original()
        self.assertGreaterEqual(self.store.rollbacks, 1)
        self.assertFalse(any(query.lstrip().startswith("UPDATE ") for query, _ in self.store.queries))

    def test_later_deletion_failure_restores_already_deleted_photos(self):
        second = self.directory / "second.jpg"
        second.write_bytes(b"original second photo")
        self.store.rows[1]["photoPath"] = json.dumps(["first.jpg", "second.jpg"])
        remove = os.remove
        def fail_second(path):
            if Path(path) == second:
                raise PermissionError("Synthetic deletion denied")
            return remove(path)
        with patch.object(cleanup.os, "remove", side_effect=fail_second):
            result, error = self.run_cleanup()
        self.assertIsNone(result)
        self.assertTrue(error)
        self.assertEqual(self.first.read_bytes(), b"original first photo")
        self.assertEqual(second.read_bytes(), b"original second photo")
        self.assertEqual(json.loads(self.store.rows[1]["photoPath"]), ["first.jpg", "second.jpg"])

    def test_update_failure_restores_files_and_rolls_back(self):
        self.store.fail_update = True
        result, error = self.run_cleanup()
        self.assertIsNone(result)
        self.assertTrue(error)
        self.assert_original()
        self.assertEqual(self.store.closed, 1)

    def test_commit_failure_restores_files_and_rolls_back(self):
        self.store.fail_commit = True
        result, error = self.run_cleanup()
        self.assertIsNone(result)
        self.assertTrue(error)
        self.assert_original()
        self.assertEqual(list(self.directory.iterdir()), [self.first])

    def test_insufficient_backup_space_never_removes_an_original(self):
        with patch.object(cleanup.shutil, "copy2", side_effect=OSError("Synthetic disk full")):
            result, error = self.run_cleanup()
        self.assertIsNone(result)
        self.assertTrue(error)
        self.assert_original()
        self.assertEqual(list(self.directory.iterdir()), [self.first])

    def test_lost_commit_acknowledgement_retains_copies_until_db_state_is_verified(self):
        self.store.commit_then_error = True
        result, error = self.run_cleanup()
        self.assertIsNone(result)
        self.assertIn("recovery copies", error)
        self.assertEqual(self.store.rows[1]["photoPath"], "archived://first.jpg")
        backups = list(self.directory.glob(".cleanup-backup-*/*.bak"))
        self.assertEqual(backups[0].read_bytes(), b"original first photo")
        self.store.commit_then_error = False
        result, error = self.run_cleanup()
        self.assertIsNone(error)
        self.assertFalse(cleanup.recovery_storage_stats(str(self.directory))["cleanupPending"])

    def test_partial_backup_copy_is_discarded_without_replacing_original(self):
        def incomplete_copy(_source, backup):
            Path(backup).write_bytes(b"partial")
            raise OSError("Synthetic interrupted backup")
        with patch.object(cleanup.shutil, "copy2", side_effect=incomplete_copy):
            result, error = self.run_cleanup()
        self.assertIsNone(result)
        self.assertTrue(error)
        self.assert_original()
        self.assertEqual(list(self.directory.iterdir()), [self.first])

    def test_pending_backup_disposal_is_reported_and_retryable(self):
        remove = os.remove
        def fail_backup(path):
            if str(path).endswith(".bak"):
                raise PermissionError("Synthetic backup disposal denied")
            return remove(path)
        with patch.object(cleanup.os, "remove", side_effect=fail_backup):
            result, error = self.run_cleanup()
        self.assertIsNone(error)
        self.assertTrue(result["recoveryPending"])
        self.assertTrue(result["warning"])
        self.assertEqual(result["freedBytes"], 0)
        self.assertEqual(self.store.rows[1]["photoPath"], "archived://first.jpg")
        stats = cleanup.recovery_storage_stats(str(self.directory))
        self.assertTrue(stats["cleanupPending"])
        self.assertEqual(stats["recoveryFiles"], 1)
        result, error = self.run_cleanup()
        self.assertIsNone(error)
        self.assertFalse(result["recoveryPending"])
        self.assertFalse(cleanup.recovery_storage_stats(str(self.directory))["cleanupPending"])

    def test_interrupted_worker_is_recovered_before_further_cleanup(self):
        self.store.interrupt_commit = True
        with self.assertRaises(KeyboardInterrupt):
            self.run_cleanup()
        self.assertFalse(self.first.exists())
        self.store.rollback()  # MySQL rolls back a disconnected worker's transaction.
        self.store.interrupt_commit = False
        self.store.rows[1]["verificationStatus"] = "Submitted"
        result, error = self.run_cleanup()
        self.assertIsNone(error)
        self.assertEqual(result["deletedFiles"], 0)
        self.assert_original()
        self.assertFalse(cleanup.recovery_storage_stats(str(self.directory))["cleanupPending"])

    def test_failed_restore_keeps_backup_and_can_recover_later(self):
        self.store.fail_commit = True
        replace = os.replace
        def fail_restore(source, destination):
            if str(source).endswith(".bak"):
                raise PermissionError("Synthetic restore denied")
            return replace(source, destination)
        with patch.object(cleanup.os, "replace", side_effect=fail_restore):
            result, error = self.run_cleanup()
        self.assertIsNone(result)
        self.assertIn("recovery copies", error)
        self.assertEqual(len(list(self.directory.glob(".cleanup-backup-*/*.bak"))), 1)
        self.store.fail_commit = False
        self.store.rows[1]["verificationStatus"] = "Submitted"
        result, error = self.run_cleanup()
        self.assertIsNone(error)
        self.assert_original()

    def test_changed_metadata_blocks_automatic_backup_disposal(self):
        self.store.interrupt_commit = True
        with self.assertRaises(KeyboardInterrupt):
            self.run_cleanup()
        self.store.rollback()
        self.store.interrupt_commit = False
        self.store.rows[1]["photoPath"] = "a-new-upload.jpg"
        result, error = self.run_cleanup()
        self.assertIsNone(result)
        self.assertTrue(error)
        backups = list(self.directory.glob(".cleanup-backup-*/*.bak"))
        self.assertEqual(backups[0].read_bytes(), b"original first photo")
        self.assertEqual(self.store.rows[1]["photoPath"], "a-new-upload.jpg")

    def test_missing_and_absent_photos_do_not_invent_freed_space(self):
        self.first.unlink()
        self.store.rows[2] = {**self.rows[1], "reportID": 2, "photoPath": None}
        result, error = self.run_cleanup()
        self.assertIsNone(error)
        self.assertEqual(result["deletedFiles"], 0)
        self.assertEqual(result["freedBytes"], 0)
        self.assertEqual(self.store.rows[2]["photoPath"], "archived://none")

    def test_array_references_are_preserved_and_physical_files_deduplicated(self):
        self.store.rows[1]["photoPath"] = json.dumps(["first.jpg", "first.jpg", "archived://old.jpg"])
        result, error = self.run_cleanup()
        self.assertIsNone(error)
        self.assertEqual(result["deletedFiles"], 1)
        self.assertEqual(json.loads(self.store.rows[1]["photoPath"]), ["archived://first.jpg", "archived://first.jpg", "archived://old.jpg"])

    def test_age_filter_does_not_remove_recent_evidence(self):
        self.store.rows[1]["irTimestamp"] = datetime.now() - timedelta(days=5)
        result, error = self.run_cleanup("older_180d")
        self.assertIsNone(error)
        self.assertEqual(result["deletedFiles"], 0)
        self.assert_original()

    def test_http_cleanup_still_requires_confirmation(self):
        response = self.http_client().post("/api/inspections/archive-evidence/cleanup", json={"filter": "all_verified"})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.store.queries, [])
        self.assert_original()

    def test_http_commit_failure_returns_error_and_preserves_photos(self):
        self.store.fail_commit = True
        response = self.http_client().post("/api/inspections/archive-evidence/cleanup", json={"filter": "all_verified", "confirm": True})
        self.assertEqual(response.status_code, 500)
        self.assertIn("error", response.get_json())
        self.assert_original()

    def test_http_pending_disposal_is_visible_in_usage_statistics(self):
        client = self.http_client()
        remove = os.remove
        def fail_backup(path):
            if str(path).endswith(".bak"):
                raise PermissionError("Synthetic backup disposal denied")
            return remove(path)
        with patch.object(cleanup.os, "remove", side_effect=fail_backup):
            response = client.post("/api/inspections/archive-evidence/cleanup", json={"filter": "all_verified", "confirm": True})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["warning"])
        usage = client.get("/api/inspections/evidence-storage-stats")
        self.assertEqual(usage.status_code, 200)
        self.assertTrue(usage.get_json()["cleanupPending"])
        self.assertGreaterEqual(usage.get_json()["totalDiskBytes"], len(b"original first photo"))


if __name__ == "__main__":
    unittest.main()
