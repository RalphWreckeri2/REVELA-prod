import test from "node:test";
import assert from "node:assert/strict";
import Papa from "papaparse";
import {
  STATUS_OPTIONS, BUSINESS_SOURCE_OPTIONS, MAP_REGISTRY_LINK_OPTIONS,
  businessDetailsInfo, businessSourceLabel, hasUnlinkedCompliance, matchesMapFilters,
  paginateRecords, buildComplianceReport, complianceCsv, compliancePrintReport,
  formatManilaDate, UNLINKED_COMPLIANCE_TEXT,
} from "./businessCompliance.js";

const verified = (overrides = {}) => ({
  id: 17, logID: 17, name: "L & U Bigasan", source: "detection", originSource: "detection",
  color: "Green", flagColor: "Green", registryLinked: false, inspectionVerifiedCompliant: true,
  barangayID: 1, barangay: "Barangay I", address: "Main Street", ...overrides,
});

test("Map dropdowns have the requested defaults and exact option order", () => {
  assert.deepEqual(STATUS_OPTIONS.map(option => option.value),
    ["all", "in_inspection", "Green", "Yellow", "Yellow_Inspector", "Orange", "Red", "Black", "Purple"]);
  assert.deepEqual(BUSINESS_SOURCE_OPTIONS.map(option => option.label),
    ["All Sources", "Business Detection", "Inspector Report", "Linked to Official BPLO Registry", "Unclassified Origin"]);
  assert.deepEqual(MAP_REGISTRY_LINK_OPTIONS.map(option => option.label),
    ["All", "Linked to Registry", "Not in Registry", "Inspection-verified compliant · Not in Registry"]);
});

test("unlinked verified Green displays one source line and the exact neutral indicator", () => {
  assert.deepEqual(businessDetailsInfo(verified()), {
    source: "Origin: Business Detection · Not in Registry", compliance: UNLINKED_COMPLIANCE_TEXT,
  });
});

test("linking removes the Not yet indicator while preserving detection origin", () => {
  assert.deepEqual(businessDetailsInfo(verified({ registryLinked: true })), {
    source: "Origin: Business Detection · Linked to Registry", compliance: null,
  });
});

test("Green without evidence, superseded Green and active Orange cannot show the indicator", () => {
  for (const row of [verified({ inspectionVerifiedCompliant: false }),
    verified({ color: "Orange", flagColor: "Orange" }),
    verified({ color: "Red", flagColor: "Red", inspectionVerifiedCompliant: false })]) {
    assert.equal(hasUnlinkedCompliance(row), false);
  }
});

test("unknown sources and missing link projections are never guessed from labels or IDs", () => {
  assert.equal(businessSourceLabel("manual"), "Inspector Report");
  assert.equal(businessSourceLabel("registry_detected"), "Registry + Maps detection");
  assert.equal(businessSourceLabel("unexpected"), "Unknown origin");
  assert.equal(matchesMapFilters(verified({ originSource: "unknown" }), { source: "detection" }), false);
  assert.equal(matchesMapFilters(verified({ registryLinked: false, businessID: "guessed" }), { registryLink: "linked" }), false);
  assert.equal(matchesMapFilters(verified({ originSource: "registry_detected" }), { source: "detection" }), false);
  assert.equal(matchesMapFilters(verified({ originSource: "registry_detected", registryLinked: true }), { source: "registry" }), true);
});

test("Map source filters use exact populations for detection, manual, registry and unclassified origins", () => {
  const detection = verified({ id: 1, originSource: "detection", source: "detection" });
  const manual = verified({ id: 2, originSource: "manual", source: "manual" });
  const registry = verified({ id: 3, originSource: "registry", source: "registry", registryLinked: true });
  const registryDetected = verified({ id: 4, originSource: "registry_detected", source: "registry_detected", registryLinked: true });
  const unknown = verified({ id: 5, originSource: "unknown", source: "unknown" });
  const rows = [detection, manual, registry, registryDetected, unknown];

  assert.deepEqual(rows.filter(row => matchesMapFilters(row, { source: "detection" })).map(row => row.id), [1]);
  assert.deepEqual(rows.filter(row => matchesMapFilters(row, { source: "manual" })).map(row => row.id), [2]);
  assert.deepEqual(rows.filter(row => matchesMapFilters(row, { source: "registry" })).map(row => row.id), [3, 4]);
  const linkedDetection = verified({ id: 6, originSource: "detection", source: "detection", registryLinked: true });
  assert.equal(matchesMapFilters(linkedDetection, { source: "detection" }), false);
  assert.equal(matchesMapFilters(linkedDetection, { source: "registry" }), true);
  assert.deepEqual(rows.filter(row => matchesMapFilters(row, { source: "unclassified" })).map(row => row.id), [5]);
  assert.equal(rows.filter(row => matchesMapFilters(row, { source: "unclassified" })).some(row => row.id === 3 || row.id === 4), false);
});
test("status, source, registry link, search and barangay use AND logic", () => {
  const rows = [verified(), verified({ id: 18, registryLinked: true }),
    verified({ id: 19, originSource: "manual", source: "manual" }),
    verified({ id: 20, color: "Red", flagColor: "Red", inspectionVerifiedCompliant: false }),
    verified({ id: 21, barangayID: 2 })];
  const filters = { status: "Green", source: "detection", registryLink: "compliant_unlinked", search: "bigasan", barangayID: "1" };
  assert.deepEqual(rows.filter(row => matchesMapFilters(row, filters)).map(row => row.id), [17]);
  assert.equal(rows.filter(row => matchesMapFilters(row)).length, 5);
  assert.equal(matchesMapFilters(verified(), { search: "#17" }), true);
  assert.equal(matchesMapFilters(verified(), { search: "Barangay I" }), true);
});

test("Currently Being Inspected is a workflow predicate across colours", () => {
  for (const color of ["Green", "Orange", "Red", "Purple"]) {
    assert.equal(matchesMapFilters(verified({ color, verificationStatus: "Submitted" }), { status: "in_inspection" }), true);
    assert.equal(matchesMapFilters(verified({ color, verificationStatus: "Verified" }), { status: "in_inspection" }), false);
  }
});

test("Yellow and inspector Yellow preserve the existing overlapping status meanings", () => {
  const row = verified({ color: "Yellow", reportedByUserID: 9, source: "manual", originSource: "manual" });
  assert.equal(matchesMapFilters(row, { status: "Yellow" }), true);
  assert.equal(matchesMapFilters(row, { status: "Yellow_Inspector", source: "manual", registryLink: "unlinked" }), true);
  assert.equal(matchesMapFilters({ ...row, reportedByUserID: null }, { status: "Yellow_Inspector" }), false);
});

const reportRecords = Array.from({ length: 35 }, (_, index) => ({
  detectionReference: index + 1, businessName: `Detected Shop ${index + 1}`,
  barangayID: index < 30 ? 1 : 2, barangayName: index < 30 ? "Barangay I" : "Barangay II",
  address: "Main Street", originSource: "detection",
  verifiedOn: "2026-10-16T01:02:03.123456Z", registryLinked: index % 2 === 0,
}));

test("View List, CSV and PDF share all filtered records, including beyond page one", () => {
  const report = buildComplianceReport(reportRecords, { search: "Shop", barangayID: "1", registryLink: "unlinked" }, "2026-10-16T04:00:00Z");
  assert.equal(report.count, 15);
  const pageOne = paginateRecords(report.rows, 1, 10);
  const pageTwo = paginateRecords(report.rows, 2, 10);
  assert.equal(pageOne.data.length, 10);
  assert.equal(pageTwo.data.length, 5);
  const csv = Papa.parse(complianceCsv(report), { header: true });
  assert.deepEqual(csv.errors, []);
  assert.deepEqual(csv.data, report.rows);
  const pdf = compliancePrintReport(report, { fullName: "Test Admin" });
  assert.deepEqual(pdf.data.rows, [...pageOne.data, ...pageTwo.data]);
  assert.equal(pdf.data.rows.at(-1)["Pin Reference"], "30");
  assert.equal(pdf.data.rows.at(-1).Origin, "Business Detection");
  assert.equal(pdf.data.count, csv.data.length);
  assert.match(pdf.title, /Inspection-Verified Compliant Businesses/);
  assert.match(pdf.subtitle, /current admin-verification evidence/);
  assert.match(pdf.date, /Asia\/Manila/);
  assert.match(pdf.data.filtersLabel, /Barangay I.*Not in Registry/);
  assert.ok(!report.columns.includes("Business ID"));
});

test("report search finds a pin reference and pagination clamps after filtering", () => {
  const report = buildComplianceReport(reportRecords, { search: "#35" });
  assert.equal(report.count, 1);
  assert.equal(report.rows[0]["Pin Reference"], "35");
  assert.equal(paginateRecords(report.rows, 5).page, 1);
  assert.equal(buildComplianceReport(reportRecords, {}).count, 35);
});

test("an empty registry-independent dataset yields a clear zero count and spreadsheet headers", () => {
  const report = buildComplianceReport([], {});
  assert.equal(report.count, 0);
  assert.deepEqual(paginateRecords(report.rows).data, []);
  const csv = Papa.parse(complianceCsv(report), { header: true });
  assert.deepEqual(csv.meta.fields, report.columns);
  assert.equal(csv.data.length, 0);
  assert.equal(compliancePrintReport(report).data.count, 0);
});

test("CSV escapes formulas, quotes, commas and multiline spreadsheet fields safely", () => {
  const values = ['=1+1', ' +SUM(1,2)', '@HYPERLINK("x")', 'A, "quoted"\nshop'];
  const report = buildComplianceReport(values.map((businessName, index) => ({ ...reportRecords[index], businessName })));
  const parsed = Papa.parse(complianceCsv(report), { header: true });
  assert.deepEqual(parsed.errors, []);
  assert.equal(parsed.data[0]["Business Name"], "'=1+1");
  assert.equal(parsed.data[1]["Business Name"], "' +SUM(1,2)");
  assert.equal(parsed.data[2]["Business Name"], '\'@HYPERLINK("x")');
  assert.equal(parsed.data[3]["Business Name"], values[3]);
});

test("verification and generation timestamps are displayed in Asia/Manila, including rollover", () => {
  assert.match(formatManilaDate("2026-10-16T01:02:03.123456Z"), /09:02:03/);
  const rollover = formatManilaDate("2026-10-16T20:00:00Z");
  assert.match(rollover, /17/);
  assert.match(rollover, /04:00:00/);
  assert.match(rollover, /Asia\/Manila/);
  assert.equal(formatManilaDate(null), "—");
});
