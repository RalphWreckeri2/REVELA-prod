import test from "node:test";
import assert from "node:assert/strict";
import {
  dashboardUpdatedLabel, inspectionColumnPreview, inspectionDeadline,
  inspectionNoticeLabel, inspectionPeriodLabel, matchesDispatchSearch,
  matchesGridSearch, workloadFilterLabel, workloadResultLabel,
} from "./inspectionPresentation.js";

for (const count of [0, 1, 5, 6, 12]) {
  test(`column preview preserves the exact five-card threshold for ${count} reports`, () => {
    const reports = Object.freeze(Array.from({ length: count }, (_, reportID) => Object.freeze({ reportID })));
    const { visibleReports, hasMore } = inspectionColumnPreview(reports);
    assert.equal(visibleReports.length, Math.min(5, count));
    assert.equal(hasMore, count > 5);
    assert.deepEqual(visibleReports.map(report => report.reportID), Array.from({ length: Math.min(5, count) }, (_, id) => id));
    assert.equal(reports.length, count);
  });
}

const reports = [
  { reportID: 123, logID: 700, detectedName: "North Market", barangayName: "Barangay II", inspectorName: "Ana", verificationStatus: "Submitted", inspectionResult: "Orange" },
  { reportID: 124, logID: 701, detectedName: "South Market", barangayName: "Barangay III", inspectorName: "Ben", verificationStatus: "Submitted", inspectionResult: "Green" },
  { reportID: 125, logID: 702, detectedName: "#123 Grocer", barangayName: "Barangay II", verificationStatus: "Verified" },
];

test("main search keeps existing fields, case-insensitive substring matching, and literal # behavior", () => {
  assert.ok(matchesDispatchSearch(reports[0], "  NORTH  "));
  assert.ok(matchesDispatchSearch(reports[0], "submitted"));
  assert.ok(matchesDispatchSearch(reports[0], "orange"));
  assert.ok(matchesDispatchSearch(reports[0], "700"));
  assert.equal(matchesDispatchSearch(reports[0], "#123"), false);
  assert.equal(matchesDispatchSearch({ ...reports[0], remarks: "unsearched notes" }, "unsearched"), false);
});

test("copied grid searches initially return the exact board results", () => {
  for (const search of ["", "market", "Submitted", "orange", "Barangay II", "Ana", "123", "#123", "unmatched"]) {
    assert.deepEqual(
      reports.filter(report => matchesGridSearch(report, search, search)),
      reports.filter(report => matchesDispatchSearch(report, search)),
      search,
    );
  }
});

test("changing and clearing a grid query is local and retains #ID matching", () => {
  const initialSearch = "North";
  assert.ok(matchesGridSearch(reports[0], "#123", initialSearch));
  assert.equal(matchesGridSearch(reports[1], "#123", initialSearch), false);
  assert.equal(reports.filter(report => matchesGridSearch(report, "", initialSearch)).length, 3);
  assert.equal(initialSearch, "North");
});

test("a grid flag filter intersects the copied search without changing ordering", () => {
  const result = reports.filter(report => report.flagColor === "Red" && matchesGridSearch(report, "market", "market"));
  assert.deepEqual(result, []);
  const withFlags = reports.map(report => ({ ...report, flagColor: "Red" }));
  assert.deepEqual(withFlags.filter(report => report.flagColor === "Red" && matchesGridSearch(report, "market", "market")).map(report => report.reportID), [123, 124]);
});

test("missing and malformed deadlines are not presented as assigned dates", () => {
  for (const value of [null, undefined, ""]) assert.deepEqual(inspectionDeadline(value), { label: "No deadline set", dateTime: null });
  assert.deepEqual(inspectionDeadline("invalid"), { label: "Deadline unavailable", dateTime: null });
  assert.equal(inspectionDeadline("2026-10-20T12:00:00Z").dateTime, "2026-10-20T12:00:00.000Z");
  assert.notEqual(inspectionDeadline("2026-10-20T12:00:00Z").label, "No deadline set");
});

test("notice labels retain existing enforcement stages", () => {
  assert.equal(inspectionNoticeLabel(0), null);
  assert.equal(inspectionNoticeLabel(1), "1st Notice");
  assert.equal(inspectionNoticeLabel(2), "2nd Notice");
  assert.equal(inspectionNoticeLabel(3), "3rd Notice");
  assert.equal(inspectionNoticeLabel(4), "Escalated");
});

test("every workload view has a plain-language banner label", () => {
  const labels = {
    all: "All inspection reports",
    open: "Open assignments",
    overdue: "Overdue assignments",
    awaiting_verification: "Reports awaiting verification",
    oldest: "Oldest open assignment",
    resolution: "Average resolution time",
    "age_0-3": "Assignments open 0–3 days",
    "age_4-7": "Assignments open 4–7 days",
    "age_8-14": "Assignments open 8–14 days",
    "age_15+": "Assignments open 15+ days",
    age_unavailable: "Assignments with unknown age",
    deadline_missing: "Assignments without a due date",
  };
  for (const [view, label] of Object.entries(labels)) {
    assert.equal(workloadFilterLabel(view), label, view);
  }
  assert.equal(workloadFilterLabel("deadline_day", "2026-10-28"), "Assignments due Oct 28");
  assert.equal(workloadFilterLabel("deadline_day"), "Assignments due that day");
  assert.equal(workloadFilterLabel("unexpected"), "All inspection reports");
});

test("workload result counts describe visible rows without inventing a total", () => {
  assert.equal(workloadResultLabel(0, 1), "Showing 0 of 0");
  assert.equal(workloadResultLabel(1, 1), "Showing 1 of 1");
  assert.equal(workloadResultLabel(3, 1), "Showing 3 of 3");
  assert.equal(workloadResultLabel(45, 1), "Showing 1–20 of 45");
  assert.equal(workloadResultLabel(45, 2), "Showing 21–40 of 45");
  assert.equal(workloadResultLabel(45, 3), "Showing 41–45 of 45");
  assert.equal(workloadResultLabel(45, 99), "Showing 41–45 of 45");
  assert.equal(workloadResultLabel(45, 2, 10), "Showing 11–20 of 45");
  assert.equal(workloadResultLabel(undefined, undefined, 0), "Showing 0 of 0");
});

test("dashboard timestamps are readable in Manila time and hide UTC strings", () => {
  assert.equal(dashboardUpdatedLabel("2026-10-27T12:00:00Z"), "Dashboard data updated Oct 27, 8:00 PM");
  assert.equal(dashboardUpdatedLabel("2026-10-27T12:00:00+08:00"), "Dashboard data updated Oct 27, 12:00 PM");
  assert.equal(dashboardUpdatedLabel("2026-10-27"), null);
  assert.equal(dashboardUpdatedLabel(null), null);
  assert.equal(inspectionPeriodLabel("2026-09-27T00:00:00Z", "2026-10-27T12:00:00Z"), "Sep 27 – Oct 27");
  assert.equal(inspectionPeriodLabel(null, "2026-10-27T12:00:00Z"), null);
});
