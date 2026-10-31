import test from "node:test";
import assert from "node:assert/strict";
import {
  BARANGAY_MAP_INTERACTION_EVENTS,
  fitMapToGeoJsonFeatures,
  getGeoJsonFeaturesBounds,
  MIN_BARANGAY_MAP_ZOOM,
  shouldFitBarangayMap,
} from "./barangayMapFit.js";
import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import path from "node:path";

test("full-map bounds include the outer coordinates of all 16 barangay features", async () => {
  const geoJsonPath = path.resolve(
    path.dirname(fileURLToPath(import.meta.url)),
    "../../public/data/mataasnakahoy.json",
  );
  const geoJson = JSON.parse(await readFile(geoJsonPath, "utf8"));
  const features = geoJson.features;
  assert.equal(features.length, 16);

  const bounds = getGeoJsonFeaturesBounds(features);
  const allPositions = [];
  const collect = (coordinates) => {
    if (!Array.isArray(coordinates)) return;
    if (coordinates.length >= 2
      && Number.isFinite(Number(coordinates[0]))
      && Number.isFinite(Number(coordinates[1]))) {
      allPositions.push(coordinates);
      return;
    }
    coordinates.forEach(collect);
  };
  features.forEach((feature) => collect(feature.geometry.coordinates));

  assert.ok(bounds);
  assert.equal(bounds.west, Math.min(...allPositions.map(([longitude]) => longitude)));
  assert.equal(bounds.east, Math.max(...allPositions.map(([longitude]) => longitude)));
  assert.equal(bounds.south, Math.min(...allPositions.map(([, latitude]) => latitude)));
  assert.equal(bounds.north, Math.max(...allPositions.map(([, latitude]) => latitude)));
});

test("fit helper passes full bounds and 24px padding to the map", async () => {
  const geoJsonPath = path.resolve(
    path.dirname(fileURLToPath(import.meta.url)),
    "../../public/data/mataasnakahoy.json",
  );
  const geoJson = JSON.parse(await readFile(geoJsonPath, "utf8"));
  let fitCall;
  const map = {
    fitBounds: (...args) => {
      fitCall = args;
    },
  };

  const bounds = fitMapToGeoJsonFeatures(map, geoJson.features);

  assert.deepEqual(fitCall, [
    bounds,
    { top: 24, right: 24, bottom: 24, left: 24 },
  ]);
});

test("automatic fits stop after manual pan or zoom, while explicit fits remain available", () => {
  assert.equal(MIN_BARANGAY_MAP_ZOOM, 10);
  assert.ok(BARANGAY_MAP_INTERACTION_EVENTS.includes("dragstart"));
  assert.ok(BARANGAY_MAP_INTERACTION_EVENTS.includes("center_changed"));
  assert.ok(BARANGAY_MAP_INTERACTION_EVENTS.includes("zoom_changed"));
  assert.equal(shouldFitBarangayMap({ userInteracted: false }), true);
  assert.equal(shouldFitBarangayMap({ userInteracted: true }), false);
  assert.equal(
    shouldFitBarangayMap({ userInteracted: true, force: true }),
    true,
  );
});
