import test from "node:test";
import assert from "node:assert/strict";

import {
  buildWorkflowSummaryModel,
  createWorkflowOperationId,
  paginateWorkflowRecords,
} from "./workflowSummary.js";

test("Snap Pins summary counts only this run's exact updated records", () => {
  const records = Array.from({ length: 6 }, (_, index) => ({
    record_id: `B-${index + 1}`,
    outcome: "snapped",
  }));
  const summary = buildWorkflowSummaryModel("snap", { records, snapped: 6 });
  assert.deepEqual(summary.counts, [
    { label: "Updated / snapped", count: 6 },
    { label: "No match", count: 0 },
    { label: "Unchanged", count: 0 },
    { label: "Unchanged / cached", count: 0 },
    { label: "Skipped by quota", count: 0 },
    { label: "Failed", count: 0 },
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
    { label: "Reverified / updated", count: 0 },
    { label: "Sent for review", count: 0 },
    { label: "Already matched", count: 0 },
    { label: "Unchanged", count: 0 },
    { label: "No match", count: 6 },
    { label: "Skipped by quota", count: 1 },
    { label: "Not processed", count: 0 },
    { label: "Failed", count: 1 },
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
    { label: "Newly detected", count: 1 },
    { label: "Matched to registry", count: 1 },
    { label: "Already flagged", count: 1 },
    { label: "Reconciled", count: 0 },
    { label: "Failed", count: 0 },
  ]);
  assert.equal(partial.checked, 10);
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
