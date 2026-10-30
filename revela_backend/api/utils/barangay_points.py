"""Shared generated barangay point data for frontend and backend consumers."""

import json
from pathlib import Path


BARANGAY_POINTS_PATH = Path(__file__).with_name("barangay_points.json")
_DATA = json.loads(BARANGAY_POINTS_PATH.read_text(encoding="utf-8"))
BARANGAY_POINTS = tuple(_DATA["barangays"])
BARANGAY_POINTS_BY_ID = {
    int(row["barangayID"]): row for row in BARANGAY_POINTS
}
MUNICIPALITY_CENTROID = _DATA["municipalityCentroid"]

if set(BARANGAY_POINTS_BY_ID) != set(range(1, 17)):
    raise ValueError(f"{BARANGAY_POINTS_PATH} must contain barangay IDs 1 through 16.")
if len(BARANGAY_POINTS_BY_ID) != len(BARANGAY_POINTS):
    raise ValueError(f"{BARANGAY_POINTS_PATH} contains duplicate barangay IDs.")
