"""Offline polygon-containment tests for the future barangay pilot."""

import unittest

from shapely.geometry import MultiPolygon, Polygon

from api.utils.nearby_barangay_scope import validate_barangay_scope


def square(min_lng=121.0, min_lat=13.0, max_lng=121.01, max_lat=13.01):
    return Polygon([
        (min_lng, min_lat),
        (max_lng, min_lat),
        (max_lng, max_lat),
        (min_lng, max_lat),
        (min_lng, min_lat),
    ])


class NearbyBarangayScopeTests(unittest.TestCase):

    def setUp(self):
        self.scope = validate_barangay_scope(7, square())

    def test_inside_coordinates_are_in_scope(self):
        self.assertTrue(self.scope.contains_scan_point(13.005, 121.005))
        self.assertTrue(
            self.scope.contains_place_coordinate(13.004, 121.006)
        )

    def test_polygon_boundary_coordinates_are_in_scope(self):
        self.assertTrue(self.scope.contains_scan_point(13.005, 121.0))
        self.assertTrue(
            self.scope.contains_place_coordinate(13.01, 121.005)
        )

    def test_point_inside_bounding_box_but_outside_polygon_is_rejected(self):
        triangle = Polygon([
            (121.0, 13.0),
            (121.01, 13.0),
            (121.0, 13.01),
            (121.0, 13.0),
        ])
        scope = validate_barangay_scope(7, triangle)

        self.assertFalse(scope.contains_scan_point(13.009, 121.009))

    def test_missing_invalid_or_ambiguous_geometry_is_rejected(self):
        with self.assertRaises(ValueError):
            validate_barangay_scope(7, None)
        with self.assertRaises(ValueError):
            validate_barangay_scope(7, {"type": "Polygon", "coordinates": []})
        with self.assertRaises(ValueError):
            validate_barangay_scope(
                7,
                Polygon([
                    (121.0, 13.0),
                    (121.01, 13.01),
                    (121.0, 13.01),
                    (121.01, 13.0),
                    (121.0, 13.0),
                ]),
            )
        with self.assertRaises(ValueError):
            validate_barangay_scope(
                7,
                {
                    "type": "GeometryCollection",
                    "geometries": [],
                },
            )
        with self.assertRaises(ValueError):
            validate_barangay_scope(0, square())
        with self.assertRaises(ValueError):
            validate_barangay_scope(True, square())

    def test_missing_malformed_and_out_of_range_coordinates_fail_closed(self):
        invalid_coordinates = (
            (None, 121.005),
            (13.005, None),
            ("13.005", 121.005),
            (13.005, "121.005"),
            (True, 121.005),
            (13.005, float("nan")),
            (float("inf"), 121.005),
            (91, 121.005),
            (13.005, 181),
            (10**10000, 121.005),
        )
        for latitude, longitude in invalid_coordinates:
            with self.subTest(latitude=latitude, longitude=longitude):
                self.assertFalse(
                    self.scope.contains_scan_point(latitude, longitude)
                )
                self.assertFalse(
                    self.scope.contains_place_coordinate(
                        latitude, longitude
                    )
                )

    def test_valid_multipolygon_accepts_each_component_only(self):
        islands = MultiPolygon([
            square(121.0, 13.0, 121.01, 13.01),
            square(121.02, 13.0, 121.03, 13.01),
        ])
        scope = validate_barangay_scope(9, islands)

        self.assertTrue(scope.contains_scan_point(13.005, 121.005))
        self.assertTrue(scope.contains_place_coordinate(13.005, 121.025))
        self.assertFalse(scope.contains_place_coordinate(13.005, 121.015))


if __name__ == "__main__":
    unittest.main()
