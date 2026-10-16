"""Registry-only Map rows must use the frontend's canonical source word."""
from unittest.mock import patch

import pytest

from api.flags import service as flags
from registry_sqlite import RegistryDB


@pytest.mark.parametrize("has_source", [True, False])
def test_registry_only_map_response_uses_registry_source(has_source):
    db = RegistryDB()
    try:
        db.seed(report=False)
        db.db.execute("DELETE FROM geospatial_logs")
        db.db.execute("UPDATE official_registry SET businessID = '5'")
        if not has_source:
            db.db.execute("ALTER TABLE geospatial_logs DROP COLUMN source")
        db.commit()
        with patch.object(flags, "mysql", db):
            payload, error = flags.get_flags()
        assert error is None
        assert payload["total"] == 1
        assert payload["data"][0]["logID"] == - \
            (flags.VIRTUAL_REGISTRY_LOG_ID_OFFSET + 1)
        assert payload["data"][0]["flagSource"] == "registry"
        assert payload["data"][0]["flagSource"] != "registry_only"
    finally:
        db.close()
