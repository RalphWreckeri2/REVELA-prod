import test from "node:test";
import assert from "node:assert/strict";
import {
  ADM4_EN_TO_BARANGAY_ID,
  getGeoJsonCentroid,
  getBarangayIdForGeoJsonName,
  normalizeGeoJsonWinding,
} from "./barangayMapMapping.js";
import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import path from "node:path";

test("GeoJSON barangay names map to all 16 numeric barangay IDs", () => {
  assert.deepEqual(ADM4_EN_TO_BARANGAY_ID, {
    "District I (Pob.)": 1,
    "District II (Pob.)": 2,
    "Barangay II-A (Pob.)": 3,
    "District III (Pob.)": 4,
    "District IV (Pob.)": 5,
    Bayorbor: 6,
    Bubuyan: 7,
    Calingatan: 8,
    Kinalaglagan: 9,
    "Lumang Lipa": 10,
    Loob: 11,
    Manggahan: 12,
    Nangkaan: 13,
    "San Sebastian": 14,
    Santol: 15,
    Upa: 16,
  });
  assert.equal(getBarangayIdForGeoJsonName("District I (Pob.)"), 1);
  assert.equal(getBarangayIdForGeoJsonName("District II (Pob.)"), 2);
  assert.equal(getBarangayIdForGeoJsonName("Barangay II-A (Pob.)"), 3);
  assert.equal(getBarangayIdForGeoJsonName("Lumang Lipa"), 10);
  assert.equal(getBarangayIdForGeoJsonName("Unmapped barangay"), null);
});

test("canonical GeoJSON features map one-to-one and exterior rings are normalized", async () => {
  const geoJsonPath = path.resolve(
    path.dirname(fileURLToPath(import.meta.url)),
    "../../public/data/mataasnakahoy.json",
  );
  const geoJson = JSON.parse(await readFile(geoJsonPath, "utf8"));
  const normalized = normalizeGeoJsonWinding(geoJson);
  const featureNames = geoJson.features.map((feature) => feature.properties.ADM4_EN);
  const mappedIds = featureNames.map(getBarangayIdForGeoJsonName);

  assert.equal(featureNames.length, 16);
  assert.equal(new Set(featureNames).size, 16);
  assert.deepEqual(mappedIds.slice().sort((a, b) => a - b),
    Array.from({ length: 16 }, (_, index) => index + 1));
  assert.equal(new Set(mappedIds).size, 16);

  const ringArea = (ring) => ring.reduce((area, point, index) => {
    const next = ring[(index + 1) % ring.length];
    return area + point[0] * next[1] - next[0] * point[1];
  }, 0);
  normalized.features.forEach((feature) => {
    const polygons = feature.geometry.type === "Polygon"
      ? [feature.geometry.coordinates]
      : feature.geometry.coordinates;
    polygons.forEach((rings) => {
      assert.ok(ringArea(rings[0]) > 0, `${feature.properties.ADM4_EN} exterior is counter-clockwise`);
      rings.slice(1).forEach((hole) => {
        assert.ok(ringArea(hole) < 0, `${feature.properties.ADM4_EN} hole is clockwise`);
      });
    });
    const centroid = getGeoJsonCentroid(feature);
    assert.ok(centroid?.lat >= 13.9 && centroid?.lat <= 14.1);
    assert.ok(centroid?.lng >= 121 && centroid?.lng <= 121.2);
  });
});
