import unittest

from api.registry.history_schema import (
    ADDED_HISTORY_COLUMNS,
    ALL_HISTORY_COLUMNS,
    BASELINE_HISTORY_COLUMNS,
)
from scripts.migrate_registry_pin_history import (
    MigrationPreflightError,
    apply_migration,
)


def _metadata_row(definition):
    name, column_type, nullable, default, extra = definition
    return {
        "COLUMN_NAME": name,
        "COLUMN_TYPE": column_type,
        "IS_NULLABLE": nullable,
        "COLUMN_DEFAULT": default,
        "EXTRA": extra,
    }


class FakeMigrationCursor:
    def __init__(self, database="railway", engine="InnoDB", columns=None):
        self.database = database
        self.engine = engine
        self.columns = list(columns if columns is not None else (
            _metadata_row(column) for column in BASELINE_HISTORY_COLUMNS
        ))
        self.fetchone_result = None
        self.fetchall_result = []
        self.alter_statements = []
        self.closed = False

    def execute(self, sql, params=None):
        normalized = " ".join(sql.split())
        if normalized.startswith("SELECT DATABASE()"):
            self.fetchone_result = {"selected_database": self.database}
        elif "information_schema.TABLES" in normalized:
            self.fetchone_result = (
                {"TABLE_NAME": "registry_pin_history", "ENGINE": self.engine}
                if self.engine is not None else None
            )
        elif "information_schema.COLUMNS" in normalized:
            self.fetchall_result = list(self.columns)
        elif normalized.startswith("ALTER TABLE"):
            self.alter_statements.append(normalized)
            for name, column_type, nullable, default, extra in ADDED_HISTORY_COLUMNS:
                if f"ADD COLUMN `{name}`" in normalized and not any(
                    column["COLUMN_NAME"] == name for column in self.columns
                ):
                    self.columns.append(_metadata_row(
                        (name, column_type, nullable, default, extra)))
        else:
            raise AssertionError(f"Unexpected SQL in mock: {normalized}")

    def fetchone(self):
        return self.fetchone_result

    def fetchall(self):
        return self.fetchall_result

    def close(self):
        self.closed = True


class FakeMigrationConnection:
    def __init__(self, cursor):
        self.fake_cursor = cursor

    def cursor(self, dictionary=False):
        if dictionary is not True:
            raise AssertionError("Migration must use dictionary metadata rows")
        return self.fake_cursor


class RegistryHistoryMigrationTests(unittest.TestCase):
    def test_clean_baseline_is_planned_without_runtime_ddl(self):
        cursor = FakeMigrationCursor()

        result = apply_migration(FakeMigrationConnection(cursor))

        self.assertEqual(result["added"], tuple(
            definition[0] for definition in ADDED_HISTORY_COLUMNS))
        self.assertFalse(result["verified"])
        self.assertEqual(cursor.alter_statements, [])
        self.assertIn("ADD COLUMN `reviewType` VARCHAR(24) NULL",
                      result["statement"])
        self.assertNotIn("IF NOT EXISTS", result["statement"])

    def test_fully_migrated_schema_is_a_repeat_safe_noop(self):
        cursor = FakeMigrationCursor(columns=(
            _metadata_row(column) for column in ALL_HISTORY_COLUMNS
        ))

        result = apply_migration(FakeMigrationConnection(cursor), apply=True)

        self.assertEqual(
            result, {"added": (), "statement": None, "verified": True})
        self.assertEqual(cursor.alter_statements, [])

    def test_partial_migration_adds_only_missing_columns_and_repeats_cleanly(self):
        existing_additions = ADDED_HISTORY_COLUMNS[:4]
        cursor = FakeMigrationCursor(columns=[
            *(_metadata_row(column) for column in BASELINE_HISTORY_COLUMNS),
            *(_metadata_row(column) for column in existing_additions),
        ])
        connection = FakeMigrationConnection(cursor)

        first = apply_migration(connection, apply=True)
        second = apply_migration(connection, apply=True)

        expected_added = tuple(
            definition[0] for definition in ADDED_HISTORY_COLUMNS[4:])
        self.assertEqual(first["added"], expected_added)
        self.assertTrue(first["verified"])
        self.assertTrue(second["verified"])
        self.assertEqual(len(cursor.alter_statements), 1)
        self.assertNotIn("reviewType", cursor.alter_statements[0])
        self.assertEqual(len(cursor.columns), 30)

    def test_wrong_type_or_nullability_blocks_alter(self):
        for incorrect in (
            ("reviewType", "varchar(8)", "YES", None, ""),
            ("reviewType", "varchar(24)", "NO", None, ""),
        ):
            with self.subTest(definition=incorrect):
                cursor = FakeMigrationCursor(columns=[
                    *(_metadata_row(column)
                      for column in BASELINE_HISTORY_COLUMNS),
                    _metadata_row(incorrect),
                ])

                with self.assertRaises(MigrationPreflightError):
                    apply_migration(
                        FakeMigrationConnection(cursor), apply=True)

                self.assertEqual(cursor.alter_statements, [])

    def test_wrong_database_blocks_all_schema_work(self):
        cursor = FakeMigrationCursor(database="other_database")

        with self.assertRaisesRegex(MigrationPreflightError, "Wrong selected database"):
            apply_migration(FakeMigrationConnection(cursor), apply=True)

        self.assertEqual(cursor.alter_statements, [])

    def test_missing_table_or_wrong_engine_blocks_alter(self):
        for engine in (None, "MyISAM"):
            with self.subTest(engine=engine):
                cursor = FakeMigrationCursor(engine=engine)

                with self.assertRaises(MigrationPreflightError):
                    apply_migration(
                        FakeMigrationConnection(cursor), apply=True)

                self.assertEqual(cursor.alter_statements, [])

    def test_missing_baseline_column_blocks_alter(self):
        cursor = FakeMigrationCursor(columns=(
            _metadata_row(column)
            for column in BASELINE_HISTORY_COLUMNS
            if column[0] != "businessID"
        ))

        with self.assertRaisesRegex(MigrationPreflightError, "missing baseline column"):
            apply_migration(FakeMigrationConnection(cursor), apply=True)

        self.assertEqual(cursor.alter_statements, [])


if __name__ == "__main__":
    unittest.main()
