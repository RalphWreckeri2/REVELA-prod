import assert from "node:assert/strict";
import test from "node:test";
import {
  completeInspectionTimeline,
  groupInspectionStatuses,
  pivotCategoryCounts,
} from "./analyticsPresentation.js";

test("groups inspection statuses and excludes barangays with no reports", () => {
  const rows = groupInspectionStatuses([
    { barangayName: "A", assigned: 1, reassigned: 2, in_progress: 3, unassigned: 4, submitted: 5, verified: 6 },
    { barangayName: "B", assigned: 0, reassigned: 0, in_progress: 0, unassigned: 0, submitted: 0, verified: 0 },
  ]);
  assert.deepEqual(rows, [{
    barangayName: "A",
    assigned: 1,
    reassigned: 2,
    in_progress: 3,
    unassigned: 4,
    submitted: 5,
    verified: 6,
    pending: 10,
    awaiting_review: 5,
    total: 21,
  }]);
});

test("pivots grouped counts by barangay", () => {
  assert.deepEqual(pivotCategoryCounts([
    { barangayName: "A", size_label: "Micro", count: 2 },
    { barangayName: "A", size_label: "Small", count: 3 },
    { barangayName: "B", size_label: "Micro", count: 4 },
  ], "size_label"), [
    { barangayName: "A", Micro: 2, Small: 3 },
    { barangayName: "B", Micro: 4 },
  ]);
});

test("fills missing daily dates and switches to weekly totals above 31 days", () => {
  const daily = completeInspectionTimeline([
    { date: "2026-01-01", submitted: 1, verified: 0 },
    { date: "2026-01-03", submitted: 0, verified: 2 },
  ]);
  assert.equal(daily.interval, "day");
  assert.deepEqual(daily.rows[1], { date: "2026-01-02", submitted: 0, verified: 0 });

  const weekly = completeInspectionTimeline([
    { date: "2026-01-01", submitted: 1, verified: 0 },
    { date: "2026-02-05", submitted: 0, verified: 2 },
  ]);
  assert.equal(weekly.interval, "week");
  assert.equal(weekly.rows[0].submitted, 1);
  assert.equal(weekly.rows.at(-1).verified, 2);
  assert.ok(weekly.rows.some(row => row.submitted === 0 && row.verified === 0));
});

test("fills an explicitly selected date range even when there are no reports", () => {
  const result = completeInspectionTimeline([], "2026-03-01", "2026-03-03");
  assert.equal(result.interval, "day");
  assert.deepEqual(result.rows, [
    { date: "2026-03-01", submitted: 0, verified: 0 },
    { date: "2026-03-02", submitted: 0, verified: 0 },
    { date: "2026-03-03", submitted: 0, verified: 0 },
  ]);
});
