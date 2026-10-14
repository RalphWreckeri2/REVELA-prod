"""Offline static checks for the unexecuted pilot schema draft."""

from pathlib import Path
import re
import unittest


MIGRATION_PATH = (
    Path(__file__).resolve().parents[1]
    / "migrations"
    / "20261012_02_nearby_barangay_pilot_draft.sql"
)


class NearbyBarangayPilotMigrationDraftTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.sql = MIGRATION_PATH.read_text(encoding="utf-8")
        cls.normalized = re.sub(r"\s+", " ", cls.sql).casefold()

    def test_file_identifies_as_unexecuted_draft(self):
        self.assertIn("draft only", self.sql.casefold())
        self.assertIn("do not execute", self.sql.casefold())

    def test_creates_only_the_five_additive_pilot_tables(self):
        created = re.findall(
            r"create\s+table\s+`?([a-z0-9_]+)`?",
            self.sql,
            flags=re.IGNORECASE,
        )
        self.assertCountEqual(created, [
            "nearby_barangay_pilot_runs",
            "nearby_barangay_pilot_attempts",
            "nearby_barangay_pilot_cells",
            "nearby_barangay_pilot_places",
            "nearby_barangay_pilot_created_flags",
        ])
        self.assertNotRegex(
            self.sql,
            re.compile(r"\b(ALTER|DROP|TRUNCATE|RENAME)\s+TABLE\b", re.I),
        )

    def test_runs_table_captures_scope_authorization_lifecycle_and_lease(self):
        required_columns = (
            "`runID` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT",
            "`barangayID` INT UNSIGNED NOT NULL",
            "`authorizationSnapshot` JSON NOT NULL",
            "`scopeFingerprint` CHAR(64)",
            "`status` ENUM(",
            "`requestBudget` TINYINT UNSIGNED NOT NULL",
            "`attemptsReserved` TINYINT UNSIGNED NOT NULL DEFAULT 0",
            "`cancelRequestedAt` DATETIME(6)",
            "`leaseOwner` VARCHAR(128)",
            "`fencingToken` BIGINT UNSIGNED NOT NULL DEFAULT 0",
            "`leaseExpiresAt` DATETIME(6)",
            "`createdAt` DATETIME(6)",
            "`startedAt` DATETIME(6)",
            "`updatedAt` DATETIME(6)",
            "`completedAt` DATETIME(6)",
        )
        for column in required_columns:
            with self.subTest(column=column):
                self.assertIn(column.casefold(), self.normalized)

    def test_database_constraints_bound_budgets_and_single_active_run(self):
        self.assertIn("check (`requestbudget` between 1 and 5)", self.normalized)
        self.assertIn(
            "check (`attemptsreserved` <= `requestbudget`)",
            self.normalized,
        )
        self.assertIn("generated always as", self.normalized)
        self.assertIn(
            "unique key `uq_nearby_pilot_active_slot` (`activerunslot`)",
            self.normalized,
        )
        self.assertIn(
            "when `status` in ('pending', 'running', 'cancel_requested')",
            self.normalized,
        )

    def test_attempts_are_idempotent_typed_and_linked_to_run(self):
        self.assertIn("primary key (`runid`, `attemptnumber`)", self.normalized)
        self.assertIn(
            "unique key `uq_nearby_pilot_attempt_idempotency` "
            "(`idempotencykey`)",
            self.normalized,
        )
        self.assertIn(
            "`attempttype` enum('initial', 'retry', 'adaptive')",
            self.normalized,
        )
        self.assertIn("`reservedat` datetime(6)", self.normalized)
        self.assertIn("`outcome` enum(", self.normalized)
        self.assertIn("`completedat` datetime(6)", self.normalized)
        self.assertIn(
            "foreign key (`runid`) references "
            "`nearby_barangay_pilot_runs` (`runid`)",
            self.normalized,
        )
        self.assertIn("on delete restrict", self.normalized)

    def test_both_tables_use_innodb_and_document_application_guarantees(self):
        self.assertEqual(self.normalized.count("engine=innodb"), 5)
        self.assertIn("mysql 8.0.16+", self.normalized)
        self.assertIn("atomic request reservation", self.normalized)
        self.assertIn("distributed lease", self.normalized)
        self.assertIn("ownership/fencing", self.normalized)
        self.assertIn("google quota", self.normalized)
        self.assertNotRegex(
            self.sql,
            re.compile(r"\b(CREATE|DROP)\s+(TRIGGER|PROCEDURE)\b", re.I),
        )

    def test_cells_are_run_owned_scoped_and_have_retryable_checkpoints(self):
        self.assertIn(
            "primary key (`runid`, `scopefingerprint`, `cellkey`)",
            self.normalized,
        )
        self.assertIn(
            "`status` enum('pending', 'in_progress', 'completed', 'failed')",
            self.normalized,
        )
        self.assertIn("`latitude` decimal(10, 7) not null", self.normalized)
        self.assertIn("`longitude` decimal(10, 7) not null", self.normalized)
        self.assertIn("`completedat` datetime(6)", self.normalized)
        self.assertIn(
            "constraint `fk_nearby_pilot_cell_run` foreign key (`runid`)",
            self.normalized,
        )
        self.assertIn(
            "check (`latitude` between -90 and 90)",
            self.normalized,
        )
        self.assertIn(
            "check (`longitude` between -180 and 180)",
            self.normalized,
        )

    def test_places_are_deduplicated_per_run_and_record_processing_decision(self):
        self.assertIn("primary key (`runid`, `placeid`)", self.normalized)
        self.assertIn(
            "`placeid` varchar(255) character set ascii collate ascii_bin",
            self.normalized,
        )
        self.assertIn("`barangayid` int unsigned not null", self.normalized)
        self.assertIn("`processingdecision` enum(", self.normalized)
        self.assertIn("'rejected_out_of_scope'", self.normalized)
        self.assertIn("`decisionat` datetime(6)", self.normalized)
        self.assertIn("`processedat` datetime(6)", self.normalized)
        self.assertIn(
            "constraint `fk_nearby_pilot_place_run` foreign key (`runid`)",
            self.normalized,
        )

    def test_flag_ledger_enforces_single_owner_and_documents_cleanup_scope(self):
        self.assertIn("`flaglogid` bigint not null", self.normalized)
        self.assertIn("primary key (`runid`, `flaglogid`)", self.normalized)
        self.assertIn(
            "unique key `uq_nearby_pilot_flag_single_owner` (`flaglogid`)",
            self.normalized,
        )
        self.assertRegex(
            self.normalized,
            r"cleanup must\s*-- verify runid \+ flaglogid \+ barangayid",
        )
        self.assertIn(
            "nullable geospatial_logs.pilotrunid bigint unsigned",
            self.normalized,
        )
        self.assertNotRegex(
            self.sql,
            re.compile(r"\bALTER\s+TABLE\s+`?geospatial_logs`?\b", re.I),
        )
        self.assertIn(
            "constraint `fk_nearby_pilot_created_flag_run` "
            "foreign key (`runid`)",
            self.normalized,
        )


if __name__ == "__main__":
    unittest.main()
