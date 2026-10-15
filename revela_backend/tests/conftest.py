"""Keep database column probes independent between backend tests."""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from api.models.geospatial import reset_source_column_cache
from api.registry.colors import reset_ladder_column_cache
from api.registry.locks import reset_lock_column_cache


@pytest.fixture(autouse=True)
def reset_column_probes():
    reset_ladder_column_cache()
    reset_lock_column_cache()
    reset_source_column_cache()
    yield
    reset_ladder_column_cache()
    reset_lock_column_cache()
    reset_source_column_cache()
