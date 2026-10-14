import unittest

from shapely.geometry import GeometryCollection, MultiPolygon, Point, Polygon, mapping

from api.utils.barangay_scope import validate_barangay_scope


class BarangayScopeTests(unittest.TestCase):
    def setUp(self):
        self.polygon = Polygon([(121, 13), (122, 13), (122, 14), (121, 14)])

    def test_accepts_polygon_and_geojson_geometry_without_modifying_boundary(self):
        for geometry in (self.polygon, mapping(self.polygon)):
            scope = validate_barangay_scope(2, geometry)
            self.assertEqual(scope.barangay_id, 2)
            self.assertTrue(scope.polygon.equals(self.polygon))
            self.assertTrue(scope.contains_coordinate(13.5, 121.5))

    def test_boundary_is_covered_but_no_outside_tolerance_is_added(self):
        scope = validate_barangay_scope(2, self.polygon)
        self.assertTrue(scope.contains_coordinate(13.5, 121))
        self.assertFalse(scope.contains_coordinate(13.5, 120.999999))

    def test_polygon_hole_is_excluded(self):
        polygon = Polygon(self.polygon.exterior.coords, holes=[
            [(121.4, 13.4), (121.6, 13.4), (121.6, 13.6), (121.4, 13.6)],
        ])
        self.assertFalse(validate_barangay_scope(2, polygon).contains_coordinate(13.5, 121.5))

    def test_multipolygon_is_supported(self):
        second = Polygon([(123, 13), (124, 13), (124, 14), (123, 14)])
        scope = validate_barangay_scope(2, MultiPolygon([self.polygon, second]))
        self.assertTrue(scope.contains_coordinate(13.5, 123.5))
        self.assertFalse(scope.contains_coordinate(13.5, 122.5))

    def test_invalid_identifiers_are_rejected(self):
        for identifier in (None, True, False, 0, -1, "2", 2.5):
            with self.assertRaises(ValueError):
                validate_barangay_scope(identifier, self.polygon)

    def test_empty_invalid_and_non_polygon_geometries_are_rejected(self):
        invalid = Polygon([(121, 13), (122, 14), (122, 13), (121, 14)])
        for geometry in (None, {}, Polygon(), invalid, Point(121, 13),
                         GeometryCollection([self.polygon]),
                         {"type": "FeatureCollection", "features": []}):
            with self.assertRaises(ValueError):
                validate_barangay_scope(2, geometry)

    def test_geometry_outside_wgs84_is_rejected(self):
        with self.assertRaises(ValueError):
            validate_barangay_scope(2, Polygon([(181, 13), (182, 13), (182, 14), (181, 14)]))

    def test_invalid_coordinates_fail_closed(self):
        scope = validate_barangay_scope(2, self.polygon)
        for lat, lng in ((None, 121), (True, 121), ("13.5", 121),
                         (float("nan"), 121), (14, float("inf")),
                         (91, 121), (14, 181), (10 ** 10000, 121)):
            self.assertFalse(scope.contains_coordinate(lat, lng))
