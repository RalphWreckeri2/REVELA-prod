import assert from "node:assert/strict";
import test from "node:test";
import {
  aggregateMapLocationMetrics,
  createCentroidPreviewFlags,
  hasMapCoordinates,
} from "./mapLocationMetrics.js";
import { matchesMapFilters } from "./businessCompliance.js";
import {
  DEFAULT_MAP_CENTER,
  getKnownBarangayCentroid,
} from "../utils/barangayCentroids.js";

test("exact centroid lookup resolves all barangay labels without partial-name matches", () => {
  const names = [
    "District I (Pob.)", "District II (Pob.)", "Barangay II-A (Pob.)",
    "District III (Pob.)", "District IV (Pob.)", "Bayorbor", "Bubuyan",
    "Calingatan", "Loob", "Lumang Lipa", "Kinalaglagan", "Manggahan",
    "Nangkaan", "San Sebastian", "Santol", "Upa",
  ];
  assert.equal(names.every((name) => getKnownBarangayCentroid(name) !== null), true);
  assert.deepEqual(getKnownBarangayCentroid("Barangay I"), getKnownBarangayCentroid("District I (Pob.)"));
  assert.equal(getKnownBarangayCentroid("Unknown Barangay"), null);
});

test("map metrics count only actual coordinates and deduplicate registered businesses", () => {
  const metrics = aggregateMapLocationMetrics([
    { barangayID: 1, latitude: 13.9, longitude: 121.1, color: "Green", businessID: "A", registryMatched: true },
    { barangayID: "1", latitude: 13.91, longitude: 121.11, color: "Green", businessID: "A", registryMatched: true },
    { barangayID: 1, latitude: null, longitude: null, color: "Red", businessID: "B", registryLinked: true },
    { barangayID: 1, latitude: null, longitude: null, color: "Green", businessID: "C", registryMatched: true },
    { barangayID: 2, latitude: 13.92, longitude: 121.12, color: "Red", businessID: null },
    { barangayID: null, latitude: 13.93, longitude: 121.13, color: "Black" },
  ]);

  assert.equal(metrics.matchingLocations, 4);
  assert.equal(metrics.withoutCoordinates, 2);
  assert.equal(metrics.registeredBusinesses, 3);
  assert.equal(metrics.activeBusinesses, 2);
  assert.equal(metrics.registeredBusinessesWithCoordinates, 1);
  assert.equal(metrics.activeBusinessesWithCoordinates, 1);
  assert.equal(metrics.colors.Green, 2);
  assert.equal(metrics.colors.Red, 1);
  assert.equal(metrics.colors.Black, 1);
  assert.equal(metrics.unassignedLocations, 1);
  assert.equal(metrics.unassignedWithCoordinates, 1);
  assert.equal(metrics.byBarangay[1].matchingLocations, 2);
  assert.equal(metrics.byBarangay[1].withoutCoordinates, 2);
  assert.equal(metrics.byBarangay[1].registeredBusinesses, 3);
  assert.equal(metrics.byBarangay[1].activeBusinesses, 2);
  assert.equal(metrics.byBarangay[1].activeBusinessesWithCoordinates, 1);
  assert.equal(metrics.byBarangay[2].colors.Red, 1);
});

test("coordinates must be finite, in range, and present rather than centroid fallbacks", () => {
  assert.equal(hasMapCoordinates({ latitude: 13.9, longitude: 121.1 }), true);
  assert.equal(hasMapCoordinates({ latitude: null, longitude: 121.1 }), false);
  assert.equal(hasMapCoordinates({ latitude: 91, longitude: 121.1 }), false);
  assert.equal(hasMapCoordinates({ latitude: 13.9, longitude: Infinity }), false);
  assert.equal(hasMapCoordinates({ hasExactCoords: false, latitude: 13.9, longitude: 121.1 }), false);
});

test("barangay-filtered KPI metrics are derived from the same canonical IDs as map rows", () => {
  const rows = [
    { barangayID: 1, latitude: 13.9, longitude: 121.1, color: "Red" },
    { barangayID: "2", latitude: 13.91, longitude: 121.11, color: "Green", businessID: "B-2", registryMatched: true },
  ];
  const selected = rows.filter((row) => matchesMapFilters(row, { barangayID: "2" }));

  assert.deepEqual(aggregateMapLocationMetrics(selected).byBarangay[2], {
    matchingLocations: 1,
    withoutCoordinates: 0,
    outsideBoundaryLocations: null,
    colors: { Green: 1, Orange: 0, Red: 0, Yellow: 0, Purple: 0, Black: 0 },
    registeredBusinesses: 1,
    activeBusinesses: 1,
    registeredBusinessesWithCoordinates: 1,
    activeBusinessesWithCoordinates: 1,
  });
});

test("blank barangay IDs are reported as unassigned instead of creating barangay zero", () => {
  const metrics = aggregateMapLocationMetrics([
    { barangayID: "", latitude: 13.9, longitude: 121.1, color: "Red" },
  ]);
  assert.equal(metrics.unassignedLocations, 1);
  assert.equal(metrics.unassignedWithCoordinates, 1);
  assert.equal(metrics.byBarangay[0], undefined);
});

test("valid map coordinates outside every municipal polygon are counted separately", () => {
  const boundaryFeatures = [{
    geometry: {
      type: "Polygon",
      coordinates: [[
        [121, 13], [122, 13], [122, 14], [121, 14], [121, 13],
      ]],
    },
  }];
  const metrics = aggregateMapLocationMetrics([
    { barangayID: 1, latitude: 13.5, longitude: 121.5, color: "Red" },
    { barangayID: 2, latitude: 14.5, longitude: 121.5, color: "Red" },
  ], boundaryFeatures);

  assert.equal(metrics.outsideBoundaryLocations, 1);
  assert.equal(metrics.byBarangay[1].outsideBoundaryLocations, 0);
  assert.equal(metrics.byBarangay[2].outsideBoundaryLocations, 1);
});

test("centroid-only preview pins are opt-in data and keep their saved coordinates missing", () => {
  const rows = [
    { id: 1, barangayID: 1, barangayName: "Barangay I", latitude: null, longitude: null },
    { id: 2, barangayID: 10, barangayName: "Barangay Lumanglipa", latitude: null, longitude: null },
    { id: 3, barangayID: null, latitude: null, longitude: null },
    { id: 4, barangayID: 1, latitude: 13.95, longitude: 121.11 },
    { id: 5, barangayID: 11, barangayName: "Unknown Barangay", latitude: null, longitude: null },
  ];
  const preview = createCentroidPreviewFlags(
    rows,
    [{ barangayID: 1, barangayName: "Barangay I" }],
    getKnownBarangayCentroid,
    DEFAULT_MAP_CENTER,
  );

  assert.deepEqual(preview.map((flag) => flag.id), [1, 2]);
  assert.deepEqual(preview[0].mapPreviewPosition, getKnownBarangayCentroid("Barangay I"));
  assert.equal(preview[0].latitude, null);
  assert.equal(hasMapCoordinates(preview[0]), false);
  assert.deepEqual(getKnownBarangayCentroid("Barangay Lumanglipa"), { lat: 13.974504, lng: 121.087937 });
  assert.equal(aggregateMapLocationMetrics([...rows, ...preview]).matchingLocations, 1);
});
