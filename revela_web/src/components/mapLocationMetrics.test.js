import assert from "node:assert/strict";
import test from "node:test";
import { aggregateMapLocationMetrics, hasMapCoordinates } from "./mapLocationMetrics.js";
import { matchesMapFilters } from "./businessCompliance.js";

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
