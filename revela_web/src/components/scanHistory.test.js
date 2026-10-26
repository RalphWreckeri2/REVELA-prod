import assert from "node:assert/strict";
import test from "node:test";
import { formatScanHistoryTimestamp } from "./scanHistory.js";

test("formats UTC scan history timestamps in Philippine time", () => {
  assert.equal(
    formatScanHistoryTimestamp("2026-10-26T03:39:00Z"),
    "Oct 26, 2026, 11:39 AM",
  );
});

test("treats legacy timezone-less scan timestamps as UTC", () => {
  assert.equal(
    formatScanHistoryTimestamp("2026-10-26 03:39"),
    "Oct 26, 2026, 11:39 AM",
  );
});

test("preserves invalid values and handles missing timestamps", () => {
  assert.equal(formatScanHistoryTimestamp("not-a-date"), "not-a-date");
  assert.equal(formatScanHistoryTimestamp(null), "—");
});
