import test from "node:test";
import assert from "node:assert/strict";
import {
  buildBarangayOverviewFilters,
  quantileBreaks,
  quantileClass,
  quantileRangeLabels,
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

  assert.equal(breaks.length, 4);
  assert.equal(labels.length, 5);
  assert.match(labels[0], /^1–/);
  assert.match(labels[4], /^>/);
  assert.equal(quantileClass(4, breaks), 0);
  assert.equal(quantileClass(119, breaks), 4);
  assert.equal(quantileClass(0, breaks), -1);
});
