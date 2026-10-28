import test from "node:test";
import assert from "node:assert/strict";
import {
  ADM4_EN_TO_BARANGAY_ID,
  getBarangayIdForGeoJsonName,
} from "./barangayMapMapping.js";

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
