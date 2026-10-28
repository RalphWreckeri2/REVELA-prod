import test from "node:test";
import assert from "node:assert/strict";
import {
  buildBarangayOverviewFilters,
  getBarangayTopTotals,
  getMapPinBuckets,
  getNotInRegistryPinTotal,
  quantileBreaks,
  quantileClass,
  quantileRangeLabels,
  registryCategoryColor,
  sortRegistryBreakdownRows,
  visibleRegistryDimensions,
} from "./barangayOverviewPresentation.js";

test("date presets apply to pin and inspection dates while preserving stricter filters", () => {
  const filters = {
    barangay_ids: [3],
    detected_from: "2026-10-25",
    inspection_to: "2026-10-27",
  };
  const result = buildBarangayOverviewFilters(
    filters,
    "7days",
    new Date(2026, 9, 28, 12),
  );
  assert.deepEqual(result, {
    barangay_ids: [3],
    detected_from: "2026-10-25",
    detected_to: "2026-10-28",
    inspection_from: "2026-10-22",
    inspection_to: "2026-10-27",
  });
  assert.deepEqual(buildBarangayOverviewFilters(filters, "all"), filters);
});

test("single-value registry dimensions are hidden", () => {
  const visible = visibleRegistryDimensions({
    business_size: [{ value: "Micro", count: 10 }],
    business_type: [
      { value: "Sole Proprietorship", count: 7 },
      { value: "Corporation", count: 3 },
    ],
    registration_type: [{ value: "New", count: 10 }],
    line_of_business: [
      { value: "Retail", count: 8 },
      { value: "Services", count: 2 },
    ],
  });
  assert.deepEqual(visible.map((dimension) => dimension.key), [
    "business_type",
    "line_of_business",
  ]);
});

test("quantile choropleth creates five numeric ranges and separates low and high counts", () => {
  const breaks = quantileBreaks([
    4, 8, 12, 16, 20, 24, 28, 32, 36, 40, 44, 48, 52, 60, 80, 119,
  ]);
  const labels = quantileRangeLabels(breaks);

  assert.equal(breaks.length, 5);
  assert.equal(labels.length, 5);
  assert.match(labels[0], /^1–/);
  assert.match(labels[4], /^>/);
  assert.equal(quantileClass(4, breaks), 0);
  assert.equal(quantileClass(119, breaks), 4);
  assert.equal(quantileClass(0, breaks), -1);
});

test("quantile ranges are integer-only and use one class per value when there are five or fewer", () => {
  const sparseCounts = [0, 1, 1.4, 2, 2.2, 3];
  const sparseBreaks = quantileBreaks(sparseCounts);
  assert.deepEqual(sparseBreaks, [1, 2, 3]);
  assert.deepEqual(quantileRangeLabels(sparseBreaks, sparseCounts), ["1", "2", "3"]);

  const denseBreaks = quantileBreaks([1.2, 4.8, 8.3, 12.6, 18.1, 25.9, 41.2, 65.7]);
  assert.ok(denseBreaks.every(Number.isInteger));
  assert.ok(quantileRangeLabels(denseBreaks, [1, 4, 8, 12, 18, 25, 41, 65])
    .every((label) => !label.includes(".")));
});

test("not-in-registry headline excludes linked detections and Card B buckets reconcile", () => {
  const overallPins = {
    registered_on_map: 210,
    detected_not_in_registry: 200,
    detection_with_business_id: 46,
    added_by_inspector: 39,
    other_source: 0,
    total: 495,
  };
  assert.equal(getNotInRegistryPinTotal(overallPins), 239);
  assert.equal(
    getMapPinBuckets(overallPins).reduce((sum, bucket) => sum + bucket.count, 0),
    495,
  );

  const santolPins = {
    registered_on_map: 14,
    detected_not_in_registry: 18,
    detection_with_business_id: 1,
    added_by_inspector: 0,
    other_source: 0,
    total: 33,
  };
  const buckets = getMapPinBuckets(santolPins);
  assert.deepEqual(buckets.map(({ key, count }) => [key, count]), [
    ["registered_on_map", 15],
    ["detected_not_in_registry", 18],
    ["added_by_inspector", 0],
    ["other_source", 0],
  ]);
  assert.equal(buckets.reduce((sum, bucket) => sum + bucket.count, 0), santolPins.total);
  assert.equal(getNotInRegistryPinTotal(santolPins), 18);
});

test("selected barangay top totals use the selected row and exclude linked detections", () => {
  const brgyTwo = {
    registry_total: 111,
    pins: {
      detected_not_in_registry: 40,
      added_by_inspector: 3,
      detection_with_business_id: 5,
    },
    inspections: { pending: 2, waiting_for_review: 1 },
  };
  assert.deepEqual(getBarangayTopTotals(brgyTwo), {
    registered: 111,
    notInRegistry: 43,
    beingInspected: 3,
  });
});

test("registry category colors stay fixed across scopes and row order", () => {
  assert.equal(registryCategoryColor("business_size", "Micro"), "#2563eb");
  assert.equal(registryCategoryColor("business_size", "Small"), "#0f9f8f");
  assert.equal(registryCategoryColor("business_size", "Medium"), "#7c3aed");
  assert.equal(registryCategoryColor("business_size", "Large"), "#f59e0b");
  assert.equal(
    registryCategoryColor("business_type", "Corporation"),
    registryCategoryColor("business_type", "Corporation"),
  );
  assert.equal(
    registryCategoryColor("registration_type", "Renewal"),
    registryCategoryColor("registration_type", "Renewal"),
  );
  assert.notEqual(
    registryCategoryColor("business_type", "Corporation"),
    registryCategoryColor("business_type", "Sole Proprietorship"),
  );
});

test("registry size rows use fixed category order and other dimensions sort by count with Others last", () => {
  const sizeRows = sortRegistryBreakdownRows("business_size", [
    { value: "Large", count: 40 },
    { value: "Unknown", count: 25 },
    { value: "Small", count: 10 },
    { value: "Medium", count: 20 },
    { value: "Micro", count: 5 },
    { value: "Others", count: 100 },
  ]);
  assert.deepEqual(sizeRows.map((row) => row.value), [
    "Micro", "Small", "Medium", "Large", "Unknown", "Others",
  ]);

  const otherRows = sortRegistryBreakdownRows("business_type", [
    { value: "Others", count: 50 },
    { value: "Retail", count: 10 },
    { value: "Services", count: 20 },
    { value: "Wholesale", count: 20 },
  ]);
  assert.deepEqual(otherRows.map((row) => row.value), [
    "Services", "Wholesale", "Retail", "Others",
  ]);
});
