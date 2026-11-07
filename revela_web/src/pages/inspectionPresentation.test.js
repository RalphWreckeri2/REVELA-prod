import test from "node:test";
import assert from "node:assert/strict";
import {
  dashboardUpdatedLabel, filteredWorkloadResultLabel, inferredDispatchBarangayID, inferredDispatchDeadline,
  inferredDispatchResult, inspectionColumnPreview, inspectionDeadline,
  inspectionNoticeLabel, inspectionPeriodLabel, inspectionResultOptions, matchesDispatchFilters, matchesDispatchSearch,
  matchesGridSearch, workloadFilterLabel, workloadResultLabel,
} from "./inspectionPresentation.js";
import { readFileSync } from "node:fs";

const inspectionPage = readFileSync(new URL("./InspectionPage.jsx", import.meta.url), "utf8");
const inspectionStyles = readFileSync(new URL("../styles/InspectionPage.css", import.meta.url), "utf8");

test("submitted reports grid provides local search and barangay, result, and deadline filters", () => {
  assert.match(inspectionPage, /const isSubmittedGrid = status === "Submitted";/);
  assert.match(inspectionPage, /aria-label="Search submitted reports"/);
  assert.match(inspectionPage, /aria-label="Filter submitted reports by barangay"/);
  assert.match(inspectionPage, /aria-label="Filter submitted reports by result"/);
  assert.match(inspectionPage, /aria-label="Filter submitted reports by deadline"/);
  assert.match(inspectionPage, /matchesDispatchFilters\(report, \{ barangay: filterBarangay, flag: filterResult, deadline: filterDeadline \}\)/);
  assert.match(inspectionStyles, /\.dispatch-grid-filter-toolbar\s*\{[^}]*grid-template-columns:\s*minmax\(200px, 1\.35fr\) 42px repeat\(3, minmax\(130px, \.8fr\)\)/);
  assert.match(inspectionStyles, /\.dispatch-grid-filter-toolbar \{\s*grid-template-columns: minmax\(0, 1fr\);\s*\}/);
});

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

test("dispatch filters combine search, barangay, flag, and deadline criteria", () => {
  const now = new Date("2026-10-31T12:00:00");
  const rows = [
    { detectedName: "North Market", barangayName: "Barangay II", flagColor: "Orange", inspectionResult: "Orange", deadline: "2026-10-30T12:00:00" },
    { detectedName: "South Market", barangayName: "Barangay II", flagColor: "Green", inspectionResult: "Green", deadline: "2026-10-31T18:00:00" },
    { detectedName: "East Market", barangayName: "Barangay III", flagColor: "Orange", inspectionResult: "Orange", deadline: "2026-11-02T12:00:00" },
    { detectedName: "West Market", barangayName: "Barangay III", flagColor: "Orange", inspectionResult: "Orange", deadline: null },
  ];

  assert.deepEqual(rows.filter(row => matchesDispatchFilters(row, {
    search: "market", barangay: "Barangay II", flag: "Orange", deadline: "overdue", now,
  })), [rows[0]]);
  assert.deepEqual(rows.filter(row => matchesDispatchFilters(row, { deadline: "today", now })), [rows[1]]);
  assert.deepEqual(rows.filter(row => matchesDispatchFilters(row, { deadline: "upcoming", now })), [rows[2]]);
  assert.deepEqual(rows.filter(row => matchesDispatchFilters(row, { deadline: "missing", now })), [rows[3]]);
  assert.equal(matchesDispatchFilters(rows[0], { flag: "Red", now }), false);
});

test("dispatch result filter uses submitted result rather than current flag color", () => {
  const report = {
    flagColor: "Green",
    inspectionResult: "Red",
  };
  assert.equal(matchesDispatchFilters(report, { flag: "Red" }), true);
  assert.equal(matchesDispatchFilters(report, { flag: "Green" }), false);
});

test("inspection result options follow known result order and include unknown submitted results", () => {
  const rows = [
    { inspectionResult: "Purple" },
    { inspectionResult: "Red" },
    { inspectionResult: "Other result" },
    { inspectionResult: "Green" },
    { inspectionResult: null },
  ];
  assert.deepEqual(
    inspectionResultOptions(rows),
    ["Red", "Yellow", "Green", "Orange", "Black", "Purple", "Other result"],
  );
});

test("dispatch search matches deadline values as well as business and report fields", () => {
  assert.equal(matchesDispatchSearch({ deadline: "2026-11-14T15:39:00" }, "2026-11-14"), true);
});

test("search results move the visible filters to their shared values", () => {
  const options = [
    { id: "10", name: "Lumanglipa" },
    { id: "5", name: "Barangay II" },
  ];
  const match = {
    barangayName: "lumanglipa", inspectionResult: "Green", deadline: "2026-11-21T18:07:00",
  };
  const now = new Date("2026-11-07T12:00:00");

  assert.equal(inferredDispatchBarangayID([match], options), "10");
  assert.equal(inferredDispatchResult([match]), "Green");
  assert.equal(inferredDispatchDeadline([match], now), "upcoming");

  const sameBarangay = [
    { barangayName: "Lumanglipa", inspectionResult: "Green", deadline: "2026-11-21T18:07:00" },
    { barangayName: "Lumanglipa", inspectionResult: "Green", deadline: "2026-11-25T09:00:00" },
  ];
  assert.equal(inferredDispatchBarangayID(sameBarangay, options), "10");
  assert.equal(inferredDispatchResult(sameBarangay), "Green");
  assert.equal(inferredDispatchDeadline(sameBarangay, now), "upcoming");
});

test("visible filters stay untouched when matches disagree or the query is empty", () => {
  const options = [{ id: "10", name: "Lumanglipa" }, { id: "5", name: "Barangay II" }];
  const rows = [
    { barangayName: "Lumanglipa", inspectionResult: "Green", deadline: "2026-11-21T18:07:00" },
    { barangayName: "Barangay II", inspectionResult: "Red", deadline: null },
  ];
  const now = new Date("2026-11-07T12:00:00");

  assert.equal(inferredDispatchBarangayID(rows, options), "");
  assert.equal(inferredDispatchResult(rows), "");
  assert.equal(inferredDispatchDeadline(rows, now), "");
  assert.equal(inferredDispatchBarangayID([], options), "");
  assert.equal(inferredDispatchResult([]), "");
  assert.equal(inferredDispatchDeadline([], now), "");
});

test("an explicit barangay ID wins over the name lookup", () => {
  const rows = [{ barangayID: 3, barangayName: "Lumanglipa" }];
  assert.equal(inferredDispatchBarangayID(rows, [{ id: "10", name: "Lumanglipa" }]), "3");
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

test("a submitted-result filter intersects the copied search without changing ordering", () => {
  const result = reports.filter(report => report.inspectionResult === "Red" && matchesGridSearch(report, "market", "market"));
  assert.deepEqual(result, []);
  const withResults = reports.map(report => ({ ...report, inspectionResult: "Red" }));
  assert.deepEqual(withResults.filter(report => report.inspectionResult === "Red" && matchesGridSearch(report, "market", "market")).map(report => report.reportID), [123, 124]);
});

test("missing and malformed deadlines are not presented as assigned dates", () => {
  for (const value of [null, undefined, ""]) assert.deepEqual(inspectionDeadline(value), { label: "No deadline", dateTime: null });
  assert.deepEqual(inspectionDeadline("invalid"), { label: "Deadline unavailable", dateTime: null });
  assert.equal(inspectionDeadline("2026-10-20T12:00:00Z").dateTime, "2026-10-20T12:00:00.000Z");
  assert.notEqual(inspectionDeadline("2026-10-20T12:00:00Z").label, "No deadline");
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

test("local dispatch filters update visible counts and identify paginated counts", () => {
  assert.equal(filteredWorkloadResultLabel(3, 14, 14), "Showing 3 of 14");
  assert.equal(filteredWorkloadResultLabel(3, 20, 45), "Showing 3 of 20 on this page");
  assert.equal(filteredWorkloadResultLabel(undefined, undefined, undefined), "Showing 0 of 0");
});

test("dashboard timestamps are readable in Manila time and hide UTC strings", () => {
  assert.equal(dashboardUpdatedLabel("2026-10-27T12:00:00Z"), "Dashboard data updated Oct 27, 8:00 PM");
  assert.equal(dashboardUpdatedLabel("2026-10-27T12:00:00+08:00"), "Dashboard data updated Oct 27, 12:00 PM");
  assert.equal(dashboardUpdatedLabel("2026-10-27"), null);
  assert.equal(dashboardUpdatedLabel(null), null);
  assert.equal(inspectionPeriodLabel("2026-09-27T00:00:00Z", "2026-10-27T12:00:00Z"), "Sep 27 – Oct 27");
  assert.equal(inspectionPeriodLabel(null, "2026-10-27T12:00:00Z"), null);
});
