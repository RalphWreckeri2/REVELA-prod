"""Sector-risk persistence and migration checks against disposable MySQL 8.

Run with scripts/run_registry_sync_audit.py --test tests.test_sector_risk_policy_mysql.
"""
import json
from pathlib import Path
import unittest

from api.analytics.sector_risk import (
    DEFAULT_SECTOR_RISK_POLICY,
    load_persisted_sector_risk_policy,
    load_sector_risk_policy_audit,
    save_persisted_sector_risk_policy,
)


connect_to_disposable_mysql = None


class SectorRiskPolicyMySQLTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if connect_to_disposable_mysql is None:
            raise unittest.SkipTest("Disposable MySQL runner required; never use application credentials")
        cls.db = connect_to_disposable_mysql()
        with cls.db.cursor() as cursor:
            cursor.execute(
                "CREATE TABLE users (userID INT PRIMARY KEY, fullName VARCHAR(120)) ENGINE=InnoDB"
            )
            cursor.execute(
                "INSERT INTO users (userID, fullName) VALUES (7, 'Policy Admin')"
            )
            migration = (
                Path(__file__).parents[1]
                / "migrations"
                / "20261030_01_sector_risk_policy.sql"
            )
            for statement in migration.read_text(encoding="utf-8").split(";"):
                if statement.strip():
                    cursor.execute(statement)
        cls.db.commit()

    @classmethod
    def tearDownClass(cls):
        cls.db.close()

    def setUp(self):
        self.db.rollback()
        with self.db.cursor() as cursor:
            cursor.execute("DELETE FROM sector_risk_policy_audit")
            cursor.execute(
                """UPDATE sector_risk_policy
                   SET version = 1, fallback_score = 50, categories = %s,
                       updated_by = NULL
                   WHERE policy_id = 1""",
                (json.dumps(DEFAULT_SECTOR_RISK_POLICY["categories"]),),
            )
        self.db.commit()

    def test_migration_seeds_versioned_policy_and_save_writes_audit_atomically(self):
        with self.db.cursor() as cursor:
            current = load_persisted_sector_risk_policy(cursor)
        self.assertEqual(current, DEFAULT_SECTOR_RISK_POLICY)

        updated_categories = {
            **current["categories"],
            "Retail": 83,
        }
        with self.db.cursor() as cursor:
            updated = save_persisted_sector_risk_policy(
                cursor, updated_categories, actor_user_id=7
            )
        self.db.commit()

        with self.db.cursor() as cursor:
            saved = load_persisted_sector_risk_policy(cursor)
            audit = load_sector_risk_policy_audit(cursor, limit=10)
        self.assertEqual(saved, updated)
        self.assertEqual(updated["version"], 2)
        self.assertEqual(updated["categories"]["Retail"], 83)
        self.assertEqual(len(audit), 1)
        self.assertEqual(audit[0]["version"], 2)
        self.assertEqual(audit[0]["actor_user_id"], 7)
        self.assertEqual(audit[0]["actor_name"], "Policy Admin")
        self.assertEqual(audit[0]["old_values"], current)
        self.assertEqual(audit[0]["new_values"], updated)
        self.assertIsNotNone(audit[0]["created_at"])

    def test_rolled_back_update_leaves_policy_and_audit_unchanged(self):
        with self.db.cursor() as cursor:
            save_persisted_sector_risk_policy(
                cursor,
                {**DEFAULT_SECTOR_RISK_POLICY["categories"], "Retail": 81},
                actor_user_id=7,
            )
        self.db.rollback()
        with self.db.cursor() as cursor:
            current = load_persisted_sector_risk_policy(cursor)
            audit = load_sector_risk_policy_audit(cursor, limit=10)
        self.assertEqual(current, DEFAULT_SECTOR_RISK_POLICY)
        self.assertEqual(audit, [])
