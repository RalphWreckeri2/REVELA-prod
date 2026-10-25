"""Guarded migration preflight is pure metadata inspection; never runs DDL."""
from unittest.mock import MagicMock

import pytest

from scripts.migrate_inspection_lifecycle_precision import inspect


def cursor_for(database, column):
    cursor = MagicMock()
    cursor.fetchone.side_effect = [{"selected_database": database}, column]
    return cursor


def test_expected_unmigrated_column_and_already_migrated_column():
    assert inspect(cursor_for("disposable", {"COLUMN_TYPE": "datetime", "IS_NULLABLE": "NO",
        "COLUMN_DEFAULT": "CURRENT_TIMESTAMP"}), "disposable") == "datetime"
    assert inspect(cursor_for("disposable", {"COLUMN_TYPE": "datetime(6)", "IS_NULLABLE": "NO",
        "COLUMN_DEFAULT": "CURRENT_TIMESTAMP(6)"}), "disposable") == "datetime(6)"


def test_wrong_database_or_incompatible_definition_refused():
    with pytest.raises(RuntimeError, match="Selected database"):
        inspect(cursor_for("wrong", None), "disposable")
    with pytest.raises(RuntimeError, match="Unexpected eventTimestamp"):
        inspect(cursor_for("disposable", {"COLUMN_TYPE": "timestamp", "IS_NULLABLE": "NO",
            "COLUMN_DEFAULT": "CURRENT_TIMESTAMP"}), "disposable")
