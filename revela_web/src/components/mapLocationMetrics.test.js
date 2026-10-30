import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import {
  aggregateMapLocationMetrics,
  createCentroidPreviewFlags,
  formatBarangayLocationMismatch,
  featureContainsPoint,
  getMapPositionBarangayIDs,
  findStoredBarangayLocationMismatches,
  hasMapCoordinates,
  MAP_LOCATION_METRIC_DEFINITIONS,
  matchesMapBarangayFilter,
} from "./mapLocationMetrics.js";
import { matchesMapFilters } from "./businessCompliance.js";
import {
  BARANGAY_POINT_DATA,
  getApproximateBarangayDisplayPoint,
  getKnownBarangayCentroid,
} from "../utils/barangayCentroids.js";
import sharedPointData from "../../../revela_backend/api/utils/barangay_points.json" with { type: "json" };
import boundaryData from "../../public/data/mataasnakahoy.json" with { type: "json" };
import { ADM4_EN_TO_BARANGAY_ID } from "./barangayMapMapping.js";

const mapPageSource = readFileSync(
  new URL("../pages/MapPage.jsx", import.meta.url),
  "utf8",
);

test("frontend centroid helpers use the same generated JSON as the backend", () => {
  assert.deepEqual(BARANGAY_POINT_DATA, sharedPointData);
  assert.equal(BARANGAY_POINT_DATA.barangays.length, 16);
  assert.deepEqual(
    BARANGAY_POINT_DATA.barangays.map((row) => row.barangayID).sort((a, b) => a - b),
    Array.from({ length: 16 }, (_, index) => index + 1),
  );
});

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
    properties: { ADM4_EN: "District I (Pob.)" },
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
    { id: 1, barangayID: 1, barangayName: "Barangay I", latitude: null, longitude: null, registryLinked: true },
    { id: 2, barangayID: 10, barangayName: "Barangay Lumanglipa", latitude: null, longitude: null, registryMatched: 1 },
    { id: 3, barangayID: null, latitude: null, longitude: null },
    { id: 4, barangayID: 1, latitude: 13.95, longitude: 121.11 },
    { id: 5, barangayID: 11, barangayName: "Unknown Barangay", latitude: null, longitude: null, originSource: "registry" },
    { id: 6, barangayID: 1, latitude: null, longitude: null, color: "Red", businessID: "B-6", registryMatched: true },
    { id: 7, barangayID: 1, latitude: null, longitude: null, color: "Red" },
  ];
  const preview = createCentroidPreviewFlags(
    rows,
    getApproximateBarangayDisplayPoint,
  );

  assert.deepEqual(preview.map((flag) => flag.id), [1, 6, 2, 5]);
  assert.notDeepEqual(
    preview[0].mapPreviewPosition,
    getKnownBarangayCentroid("Barangay I"),
  );
  assert.equal(preview[0].hasExactCoords, false);
  assert.equal(preview[0].latitude, null);
  assert.equal(preview[0].barangayID, 1);
  assert.equal(hasMapCoordinates(preview[0]), false);
  assert.deepEqual(
    getKnownBarangayCentroid("Barangay Lumanglipa"),
    BARANGAY_POINT_DATA.barangays.find((row) => row.barangayID === 10).representativePoint,
  );
  const metrics = aggregateMapLocationMetrics([...rows, ...preview]);
  assert.equal(metrics.matchingLocations, 1);
  assert.equal(metrics.colors.Red, 0);
  assert.equal(metrics.registeredBusinesses, 1);
});

test("approximate display positions are deterministic and remain inside every recorded barangay", () => {
  const rows = Array.from({ length: 16 * 20 }, (_, index) => ({
    id: 16 * 20 - index,
    barangayID: Math.floor(index / 20) + 1,
    latitude: null,
    longitude: null,
    registryMatched: true,
  }));
  const first = createCentroidPreviewFlags(rows, getApproximateBarangayDisplayPoint);
  const second = createCentroidPreviewFlags(rows.slice().reverse(), getApproximateBarangayDisplayPoint);

  assert.deepEqual(
    new Map(first.map((flag) => [flag.id, flag.mapPreviewPosition])),
    new Map(second.map((flag) => [flag.id, flag.mapPreviewPosition])),
  );
  const featuresByID = new Map(boundaryData.features.map((feature) => [
    ADM4_EN_TO_BARANGAY_ID[feature.properties.ADM4_EN],
    feature,
  ]));
  const pointsByBarangay = new Map();
  for (const flag of first) {
    const feature = featuresByID.get(flag.barangayID);
    assert.equal(
      featureContainsPoint(
        feature,
        flag.mapPreviewPosition.lat,
        flag.mapPreviewPosition.lng,
      ),
      true,
    );
    const points = pointsByBarangay.get(flag.barangayID) || new Set();
    points.add(`${flag.mapPreviewPosition.lat},${flag.mapPreviewPosition.lng}`);
    pointsByBarangay.set(flag.barangayID, points);
    assert.ok(featuresByID.has(flag.barangayID));
    assert.equal(flag.latitude, null);
  }
  for (const points of pointsByBarangay.values()) {
    assert.equal(points.size, 20);
  }
});

test("polygon mismatches are review-only and never change stored barangay grouping", () => {
  const districtOnePolygon = {
    properties: { ADM4_EN: "District I (Pob.)" },
    geometry: {
      type: "Polygon",
      coordinates: [[
        [121, 13], [122, 13], [122, 14], [121, 14], [121, 13],
      ]],
    },
  };
  const flag = {
    id: 42,
    barangayID: 2,
    latitude: 13.5,
    longitude: 121.5,
    color: "Red",
  };
  const mismatches = findStoredBarangayLocationMismatches(
    [flag],
    [districtOnePolygon],
  );
  const metrics = aggregateMapLocationMetrics(
    [flag],
    [districtOnePolygon],
  );

  assert.deepEqual(mismatches, [{
    flagId: 42,
    storedBarangayID: 2,
    polygonBarangayID: 1,
  }]);
  assert.equal(metrics.byBarangay[2].matchingLocations, 1);
  assert.equal(metrics.byBarangay[1], undefined);
  assert.equal(flag.barangayID, 2);
});

test("all 16 polygon assignments, Lumang Lipa mismatches, and municipality totals reconcile", () => {
  const pointsByID = new Map(BARANGAY_POINT_DATA.barangays.map((row) => [
    Number(row.barangayID),
    row.representativePoint,
  ]));
  const rows = Array.from({ length: 16 }, (_, index) => {
    const barangayID = index + 1;
    const point = pointsByID.get(barangayID);
    return {
      id: barangayID === 10 ? 36 : 100 + barangayID,
      businessID: barangayID === 10 ? "DULO-PRIVATE-RESORT" : `B-${barangayID}`,
      name: barangayID === 10 ? "DULO' PRIVATE RESORT" : `Business ${barangayID}`,
      barangayID,
      recordedBarangayID: barangayID,
      latitude: point.lat,
      longitude: point.lng,
      color: "Green",
      registryMatched: true,
    };
  });
  const mismatches = [
    {
      id: 487,
      businessID: "M-0401018-00130",
      name: "LA VIRGINIA LEISURE PARK AND AMUSEMENT RESORT INC.",
      barangayID: 12,
      recordedBarangayID: 12,
      latitude: 13.96511614,
      longitude: 121.09128964,
      color: "Green",
      registryMatched: true,
    },
    {
      id: 496,
      businessID: "G-0401018-00049",
      name: "HIGHLIGHT LAKE VIEW RESORT",
      barangayID: 12,
      recordedBarangayID: 12,
      latitude: 13.96469787,
      longitude: 121.09397622,
      color: "Green",
      registryMatched: true,
    },
  ];
  const approximateRows = Array.from({ length: 3 }, (_, index) => ({
    id: -index - 1,
    businessID: `UNLOCATED-${index + 1}`,
    barangayID: 10,
    recordedBarangayID: 10,
    latitude: null,
    longitude: null,
    color: "Green",
    registryMatched: true,
  }));
  const assignedToIVButInsideLumangLipa = {
    id: 401,
    barangayID: 5,
    recordedBarangayID: 5,
    latitude: 13.96511614,
    longitude: 121.09128964,
    color: "Green",
  };
  const inferredLumangLipa = {
    id: 402,
    barangayID: null,
    recordedBarangayID: null,
    latitude: pointsByID.get(10).lat,
    longitude: pointsByID.get(10).lng,
    color: "Green",
  };
  const allRows = [...rows, ...mismatches, ...approximateRows];

  for (const row of rows) {
    assert.deepEqual(getMapPositionBarangayIDs(row, boundaryData.features), [
      row.barangayID,
    ]);
  }
  for (const row of mismatches) {
    assert.equal(matchesMapBarangayFilter(row, "10", boundaryData.features), true);
    assert.equal(matchesMapBarangayFilter(row, "12", boundaryData.features), true);
    assert.equal(getMapPositionBarangayIDs(row, boundaryData.features)[0], 10);
  }
  assert.equal(
    matchesMapBarangayFilter(assignedToIVButInsideLumangLipa, "5", boundaryData.features),
    true,
  );
  assert.equal(
    matchesMapBarangayFilter(assignedToIVButInsideLumangLipa, "10", boundaryData.features),
    false,
  );
  assert.equal(
    matchesMapBarangayFilter(inferredLumangLipa, "10", boundaryData.features),
    true,
  );
  assert.equal(
    matchesMapBarangayFilter(inferredLumangLipa, "5", boundaryData.features),
    false,
  );
  assert.deepEqual(
    findStoredBarangayLocationMismatches(
      [inferredLumangLipa],
      boundaryData.features,
    ),
    [],
  );
  assert.equal(
    formatBarangayLocationMismatch("Manggahan", "Lumanglipa"),
    "Recorded in Manggahan; map position in Lumanglipa",
  );
  assert.equal(
    formatBarangayLocationMismatch(null, "Lumanglipa"),
    "No recorded barangay; map position in Lumanglipa",
  );
  for (const row of approximateRows) {
    assert.equal(matchesMapBarangayFilter(row, "10", boundaryData.features), true);
    assert.equal(matchesMapBarangayFilter(row, "12", boundaryData.features), false);
  }

  const lumangLipaRows = allRows.filter((row) => (
    matchesMapFilters(row, { barangayID: "all" }) &&
    matchesMapBarangayFilter(row, "10", boundaryData.features)
  ));
  const manggahanRows = allRows.filter((row) => (
    matchesMapFilters(row, { barangayID: "all" }) &&
    matchesMapBarangayFilter(row, "12", boundaryData.features)
  ));
  assert.deepEqual(
    lumangLipaRows.filter(hasMapCoordinates).map((row) => row.id).sort((a, b) => a - b),
    [36, 487, 496],
  );
  assert.equal(lumangLipaRows.length, 6);
  assert.deepEqual(
    manggahanRows.filter(hasMapCoordinates).map((row) => row.id).sort((a, b) => a - b),
    [112, 487, 496],
  );
  assert.equal(new Set(lumangLipaRows.map((row) => row.id)).size, lumangLipaRows.length);
  assert.equal(new Set(manggahanRows.map((row) => row.id)).size, manggahanRows.length);
  const lumangLipaMetrics = aggregateMapLocationMetrics(
    lumangLipaRows,
    boundaryData.features,
  );
  const manggahanMetrics = aggregateMapLocationMetrics(
    manggahanRows,
    boundaryData.features,
  );
  assert.equal(lumangLipaMetrics.matchingLocations, 3);
  assert.equal(lumangLipaMetrics.activeBusinesses, 6);
  assert.equal(manggahanMetrics.matchingLocations, 3);
  assert.equal(manggahanMetrics.activeBusinesses, 3);

  const metrics = aggregateMapLocationMetrics(allRows, boundaryData.features);
  assert.equal(metrics.matchingLocations, 18);
  assert.equal(metrics.withoutCoordinates, 3);
  assert.equal(metrics.registeredBusinesses, 21);
  assert.equal(metrics.activeBusinesses, 21);
  assert.deepEqual(metrics.colors, {
    Green: 18,
    Orange: 0,
    Red: 0,
    Yellow: 0,
    Purple: 0,
    Black: 0,
  });
  assert.equal(metrics.byBarangay[10].matchingLocations, 1);
  assert.equal(metrics.byBarangay[12].matchingLocations, 3);
  assert.equal(metrics.byMapPositionBarangay[10].matchingLocations, 3);
  assert.equal(metrics.byMapPositionBarangay[10].registeredBusinesses, 3);
  assert.equal(metrics.byMapPositionBarangay[10].activeBusinesses, 3);
  assert.equal(
    Object.values(metrics.byMapPositionBarangay).reduce(
      (total, scope) => total + scope.matchingLocations,
      0,
    ),
    metrics.matchingLocations,
  );
  assert.match(MAP_LOCATION_METRIC_DEFINITIONS.activeBusinesses, /may include records without exact coordinates/);
});

test("boundary points matching multiple polygons are reported, not silently attributed", () => {
  const adjacentFeatures = [
    {
      properties: { ADM4_EN: "District I (Pob.)" },
      geometry: {
        type: "Polygon",
        coordinates: [[
          [121, 13], [121.5, 13], [121.5, 14], [121, 14], [121, 13],
        ]],
      },
    },
    {
      properties: { ADM4_EN: "District II (Pob.)" },
      geometry: {
        type: "Polygon",
        coordinates: [[
          [121.5, 13], [122, 13], [122, 14], [121.5, 14], [121.5, 13],
        ]],
      },
    },
  ];
  const flag = {
    id: 99,
    barangayID: 3,
    latitude: 13.5,
    longitude: 121.5,
    color: "Red",
  };
  const metrics = aggregateMapLocationMetrics([flag], adjacentFeatures);

  assert.deepEqual(getMapPositionBarangayIDs(flag, adjacentFeatures), [1, 2]);
  assert.equal(matchesMapBarangayFilter(flag, "1", adjacentFeatures), false);
  assert.equal(matchesMapBarangayFilter(flag, "2", adjacentFeatures), false);
  assert.equal(metrics.matchingLocations, 1);
  assert.equal(metrics.outsideBoundaryLocations, 0);
  assert.equal(metrics.ambiguousBoundaryLocations, 1);
  assert.deepEqual(metrics.byMapPositionBarangay, {});
});

test("map KPIs use exact-location totals and explain the effective Red population", () => {
  assert.match(
    mapPageSource,
    /label: "Matching Locations", value: filteredMapMetrics\.matchingLocations/,
  );
  assert.match(
    mapPageSource,
    /recordedBarangayID: flag\.recordedBarangayID \?\? flag\.barangayID/,
  );
  assert.match(mapPageSource, /label: "Expired \/ Unregistered \(Red\)"/);
  assert.match(mapPageSource, /Approx\. \(\{centroidPreviewFlags\.length\}\)/);
  assert.match(mapPageSource, /locationReview\?\.kind === "inferred"/);
  assert.match(
    MAP_LOCATION_METRIC_DEFINITIONS.flagColorLocations,
    /Red includes expired registered businesses and unregistered detections/,
  );
});
