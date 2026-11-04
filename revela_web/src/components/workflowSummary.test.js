import test from "node:test";
import assert from "node:assert/strict";

import {
  buildWorkflowSummaryModel,
  createWorkflowOperationId,
  filterWorkflowSummaryRecords,
  paginateWorkflowRecords,
} from "./workflowSummary.js";

test("Snap Pins summary counts only this run's exact updated records", () => {
  const records = Array.from({ length: 6 }, (_, index) => ({
    record_id: `B-${index + 1}`,
    outcome: "snapped",
  }));
  const summary = buildWorkflowSummaryModel("snap", { records, snapped: 6 });
  assert.deepEqual(summary.counts, [
    { label: "Updated / snapped", count: 6, keys: ["snapped"] },
    { label: "No match", count: 0, keys: ["no_match"] },
    { label: "Unchanged", count: 0, keys: ["unchanged"] },
    { label: "Unchanged / cached", count: 0, keys: ["cached"] },
    { label: "Skipped by quota", count: 0, keys: ["skipped_quota"] },
    { label: "Failed", count: 0, keys: ["api_error", "failed"] },
  ]);
  assert.deepEqual(summary.records.map((record) => record.record_id), [
    "B-1", "B-2", "B-3", "B-4", "B-5", "B-6",
  ]);
});

test("Re-verify keeps no-match records and failed/skipped outcomes distinct", () => {
  const summary = buildWorkflowSummaryModel("reverify", {
    records: [
      ...Array.from({ length: 6 }, (_, index) => ({
        record_id: `N-${index + 1}`,
        outcome: "no_match",
        reason: "no place",
      })),
      { record_id: "Q-1", outcome: "skipped_quota" },
      { record_id: "F-1", outcome: "failed" },
    ],
  });
  assert.deepEqual(summary.counts, [
    { label: "Reverified / updated", count: 0, keys: ["reverified"] },
    { label: "Sent for review", count: 0, keys: ["review"] },
    { label: "Already matched", count: 0, keys: ["matched"] },
    { label: "Unchanged", count: 0, keys: ["unchanged"] },
    { label: "No match", count: 6, keys: ["no_match"] },
    { label: "Skipped by quota", count: 1, keys: ["skipped_quota"] },
    { label: "Not processed", count: 0, keys: ["not_processed"] },
    { label: "Failed", count: 1, keys: ["failed"] },
  ]);
  assert.equal(summary.records.filter((row) => row.outcome === "no_match").length, 6);
});

test("detection zero-result and partial summaries stay honest", () => {
  const empty = buildWorkflowSummaryModel("detection", {
    total_checked: 24,
    records: [],
  });
  assert.equal(empty.emptyMessage, "No new businesses flagged this run.");
  assert.equal(empty.checked, 24);

  const partial = buildWorkflowSummaryModel("detection", {
    total_checked: 10,
    records: [
      { outcome: "new_detected" },
      { outcome: "matched" },
      { outcome: "already_flagged" },
    ],
  });
  assert.deepEqual(partial.counts, [
    { label: "Newly detected", count: 1, keys: ["new_detected"] },
    { label: "Matched to registry", count: 1, keys: ["matched"] },
    { label: "Already flagged", count: 1, keys: ["already_flagged"] },
    { label: "Reconciled", count: 0, keys: ["reconciled"] },
    { label: "Failed", count: 0, keys: ["failed"] },
  ]);
  assert.equal(partial.checked, 10);
});

test("detection summary shows newly detected businesses before other outcomes", () => {
  const summary = buildWorkflowSummaryModel("detection", {
    records: [
      { record_id: "RECONCILED-1", outcome: "reconciled" },
      { record_id: "MATCHED-1", outcome: "matched" },
      { record_id: "NEW-1", outcome: "new_detected" },
      { record_id: "ALREADY-1", outcome: "already_flagged" },
      { record_id: "NEW-2", outcome: "new_detected" },
      { record_id: "FAILED-1", outcome: "failed" },
    ],
  });
  assert.deepEqual(summary.records.map((record) => record.record_id), [
    "NEW-1",
    "NEW-2",
    "MATCHED-1",
    "ALREADY-1",
    "RECONCILED-1",
    "FAILED-1",
  ]);
});

test("detection summary focuses on newly detected businesses by default", () => {
  const summary = buildWorkflowSummaryModel("detection", {
    total_checked: 150,
    run_summary: { non_business: 9, closed_results: 3, duplicates: 605 },
    records: [
      { record_id: "MATCHED-1", outcome: "matched" },
      { record_id: "FLAGGED-1", outcome: "already_flagged" },
    ],
  });
  assert.deepEqual(summary.defaultOutcomeKeys, ["new_detected"]);
  assert.equal(summary.primary.label, "Newly detected");
  assert.equal(summary.primary.count, 0);
  assert.match(summary.defaultEmptyMessage, /No new businesses detected/);
  assert.equal(filterWorkflowSummaryRecords(summary.records, summary.defaultOutcomeKeys).length, 0);
  assert.deepEqual(filterWorkflowSummaryRecords(summary.records, ["matched"]).map(({ record_id }) => record_id), ["MATCHED-1"]);
  assert.deepEqual(summary.contextCounts, [
    ["Non-business Places", 9],
    ["Closed Places results", 3],
    ["Duplicate results", 605],
  ]);
});

test("workflow summary pagination bounds large record lists", () => {
  const rows = Array.from({ length: 103 }, (_, index) => ({ id: index }));
  const first = paginateWorkflowRecords(rows, 1, 20);
  const last = paginateWorkflowRecords(rows, 99, 20);
  assert.equal(first.pageCount, 6);
  assert.equal(first.records.length, 20);
  assert.equal(last.page, 6);
  assert.equal(last.records.length, 3);
  assert.deepEqual(last.records.map((row) => row.id), [100, 101, 102]);
});

test("workflow summary outcome filters select only matching captured records", () => {
  const rows = [
    { id: 1, outcome: "snapped" },
    { id: 2, outcome: "no_match" },
    { id: 3, outcome: "api_error" },
    { id: 4, outcome: "failed" },
  ];
  assert.deepEqual(filterWorkflowSummaryRecords(rows, ["snapped"]).map(({ id }) => id), [1]);
  assert.deepEqual(filterWorkflowSummaryRecords(rows, ["api_error", "failed"]).map(({ id }) => id), [3, 4]);
  assert.deepEqual(filterWorkflowSummaryRecords(rows).map(({ id }) => id), [1, 2, 3, 4]);
});

test("operation IDs are UUIDs and use secure random bytes fallback", () => {
  assert.equal(
    createWorkflowOperationId({ randomUUID: () => "secure-id" }),
    "secure-id",
  );
  const fallback = createWorkflowOperationId({
    getRandomValues: (bytes) => {
      bytes.fill(1);
      return bytes;
    },
  });
  assert.match(fallback, /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
});
