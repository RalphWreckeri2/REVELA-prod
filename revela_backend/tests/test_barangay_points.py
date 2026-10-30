import hashlib
import json
from pathlib import Path
import unittest

from pyproj import Transformer
from shapely.geometry import Point, shape
from shapely.ops import transform

from api.utils.barangay_points import (
    BARANGAY_POINTS,
    BARANGAY_POINTS_PATH,
    BARANGAY_POINTS_BY_ID,
)


ROOT = Path(__file__).resolve().parents[2]
CANONICAL_GEOJSON = (
    ROOT / "revela_backend" / "api" / "utils"
    / "mataasnakahoy_mpdo_compatible.json"
)
GEOJSON_COPIES = (
    ROOT / "revela_backend" / "api" / "utils" / "mataasnakahoy.json",
    ROOT / "revela_web" / "public" / "data" / "mataasnakahoy.json",
)
SHARED_MAPPING = (
    ROOT / "revela_backend" / "api" / "utils"
    / "adm4_en_barangay_ids.json"
)


class BarangayPointsTests(unittest.TestCase):
    def setUp(self):
        self.payload = json.loads(BARANGAY_POINTS_PATH.read_text(encoding="utf-8"))
        self.geojson_bytes = CANONICAL_GEOJSON.read_bytes()
        self.geojson = json.loads(self.geojson_bytes)
        self.mapping = json.loads(SHARED_MAPPING.read_text(encoding="utf-8"))

    def test_generated_points_match_all_mapped_geojson_features(self):
        self.assertEqual(len(BARANGAY_POINTS), 16)
        self.assertEqual(set(BARANGAY_POINTS_BY_ID), set(range(1, 17)))
        self.assertEqual(
            {row["name"]: row["barangayID"] for row in BARANGAY_POINTS},
            self.mapping,
        )

    def test_representative_points_are_inside_projected_polygons(self):
        forward = Transformer.from_crs(
            self.payload["sourceCrs"],
            self.payload["projectedCrs"],
            always_xy=True,
        ).transform
        features = {
            feature["properties"]["ADM4_EN"]: shape(feature["geometry"])
            for feature in self.geojson["features"]
        }
        for row in BARANGAY_POINTS:
            with self.subTest(barangay=row["name"]):
                projected_polygon = transform(forward, features[row["name"]])
                point = row["representativePoint"]
                projected_point = transform(
                    forward,
                    Point(point["lng"], point["lat"]),
                )
                self.assertTrue(projected_polygon.contains(projected_point))

    def test_generated_data_fails_stale_geojson_check(self):
        source_hash = hashlib.sha256(self.geojson_bytes).hexdigest()
        self.assertEqual(self.payload["sourceGeoJsonSha256"], source_hash)
        for path in GEOJSON_COPIES:
            with self.subTest(path=path):
                self.assertEqual(
                    hashlib.sha256(path.read_bytes()).hexdigest(),
                    source_hash,
                )

    def test_area_centroid_and_representative_point_are_both_recorded(self):
        self.assertTrue(all(row["polygonAreaM2"] > 0 for row in BARANGAY_POINTS))
        self.assertTrue(all("centroid" in row for row in BARANGAY_POINTS))
        self.assertTrue(all("representativePoint" in row for row in BARANGAY_POINTS))
        self.assertTrue(all(row["representativeClearanceM"] > 0 for row in BARANGAY_POINTS))


if __name__ == "__main__":
    unittest.main()
