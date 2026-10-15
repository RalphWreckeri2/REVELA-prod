"""Real registry writes and the shared color SQL, using an isolated SQLite DB."""
from io import BytesIO
from unittest.mock import patch

import pytest

from api.inspections import service as inspections
from api.models import geospatial
from api.registry import service as registry
from api.registry.colors import _effective_flag_color_sql
from registry_sqlite import RegistryDB


def color(db):
    cursor = db.cursor()
    cursor.execute(f"SELECT {_effective_flag_color_sql('g', ladder=True)} AS color FROM geospatial_logs g")
    return cursor.fetchone()["color"]


def test_clear_warning_restores_pending_color_and_mobile_pin_count():
    db = RegistryDB()
    try:
        db.seed()
        assert color(db) == "Orange"
        with patch.object(registry, "mysql", db), patch.object(inspections, "mysql", db), patch("api.notifications.hub.publish_to_admins"):
            summary, error = registry.clear_warning("B-1", 2, "resolved")
            assert error is None
            assert summary["warningLevel"] == 0
            assert db.rows("SELECT applicationStatus FROM official_registry")[0]["applicationStatus"] == "Pending"
            assert color(db) == "Yellow"  # The old Verified Orange report is still present.
            assert db.rows("SELECT flagColor, noticeLevel FROM geospatial_logs") == [{"flagColor": "Yellow", "noticeLevel": 0}]
            assigned, error = inspections.assign_inspection(1, 9, None, 2)
            assert error is None
            assert assigned["status"] == "Reassigned"
            tasks, error = inspections.get_inspector_tasks(9)
            assert error is None
            assert tasks["data"][0]["currentNoticeLevel"] == 0
    finally:
        db.close()


def test_sync_color_does_not_resurrect_a_cleared_warning():
    db = RegistryDB()
    try:
        db.seed(status="Expired", level=0)
        registry._sync_flag_color(db.cursor(), 1, "ACME", "Expired", business_id="B-1")
        assert color(db) == "Red"
        assert db.rows("SELECT flagColor FROM geospatial_logs")[0]["flagColor"] == "Red"
    finally:
        db.close()


@pytest.mark.parametrize("level,expected", [(0, "Red"), (1, "Orange")])
def test_expiry_uses_current_warning_level_not_old_history(level, expected):
    db = RegistryDB()
    try:
        db.seed(status="Active", level=level)
        with patch.object(registry, "mysql", db), patch("api.notifications.hub.publish_to_admins"):
            result = registry.check_and_expire_old_permits()
        assert result["count"] == 1
        assert db.rows("SELECT applicationStatus FROM official_registry")[0]["applicationStatus"] == "Expired"
        assert db.rows("SELECT flagColor FROM geospatial_logs")[0]["flagColor"] == expected
        assert color(db) == expected
    finally:
        db.close()


@pytest.mark.parametrize("migrated", [True, False])
def test_revoked_csv_is_imported_once_then_frozen(migrated):
    db = RegistryDB(ladder=migrated)
    csv = b"Business ID,businessName,barangay,Status\nB-1,ACME,Barangay I,Revoked\n"
    try:
        with patch.object(registry, "mysql", db), patch.object(geospatial, "mysql", db), patch.object(registry, "_resolve_location", return_value=(None, None, {"reason": "no_match"})), patch.object(registry, "_log_registry_places_summary"), patch("api.notifications.hub.publish_to_admins"):
            first, error = registry.sync_registry(BytesIO(csv), ".csv")
            assert error is None
            assert first["inserted"] == 1
            before = db.rows("SELECT * FROM official_registry")
            second, error = registry.sync_registry(BytesIO(csv.replace(b"Revoked", b"Active")), ".csv")
            assert error is None
            assert second["skipped_black_lock"] == 1
            assert db.rows("SELECT * FROM official_registry") == before
            assert db.rows("SELECT flagColor FROM geospatial_logs")[0]["flagColor"] == "Black"
    finally:
        db.close()
