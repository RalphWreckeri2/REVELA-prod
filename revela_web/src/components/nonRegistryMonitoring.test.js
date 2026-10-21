import test from "node:test";
import assert from "node:assert/strict";
import Papa from "papaparse";
import { paginateRecords } from "./businessCompliance.js";
import { isNonRegistrySnapshot, NON_REGISTRY_COLUMNS, nonRegistryRows, nonRegistryCsv } from "./nonRegistryMonitoring.js";

const record = (id, extra = {}) => ({
  logID: id, detectedName: `Pin ${id}`, barangayID: 1, barangayName: "Barangay I",
  originSource: "detection", flagColor: "Green", registryLinked: false,
  verificationStatus: "Verified", verifiedGreen: true, verifiedGreenAt: "2026-10-20T14:00:00Z", ...extra,
});
const snapshot = (records = [record(1)]) => ({
  summary: { total: records.length, needs_verification: 0, under_inspection: 0, verified_green: records.length },
  by_barangay: [], records, generated_at: "2026-10-21T06:00:00Z",
});

test("missing, partial or mixed-registry snapshots cannot become fabricated zeros or exports", () => {
  for (const value of [null, {}, { records: [] }, { ...snapshot(), summary: {} },
    { ...snapshot(), generated_at: "bad date" }, { ...snapshot(), records: [] }, { ...snapshot(), by_barangay: {} },
    snapshot([record(1, { registryLinked: true })])]) {
    assert.equal(isNonRegistrySnapshot(value), false);
    assert.throws(() => nonRegistryCsv(value), /unavailable/);
  }
  assert.equal(isNonRegistrySnapshot(snapshot([])), true);
});

test("list rows show pin references, current evidence and persisted provenance without inventing a registry ID", () => {
  const [row] = nonRegistryRows([record(17, { detectedName: "Juan Store", originSource: "manual" })]);
  assert.equal(row["Pin Reference"], "17");
  assert.equal(row.Source, "Inspector Report");
  assert.equal(row["Registry Link"], "Not in Registry");
  assert.equal(row["Inspection-Verified Compliant"], "Yes");
  assert.match(row["Verified On"], /Asia\/Manila/);
  assert.equal("Business ID" in row, false);
});

test("Green colour or historical verification alone cannot produce a verified-compliant row", () => {
  const [row] = nonRegistryRows([record(1, { verifiedGreen: false, originSource: "unknown", verificationStatus: null })]);
  assert.equal(row["Current Flag"], "Green");
  assert.equal(row["Inspection-Verified Compliant"], "No");
  assert.equal(row["Verified On"], "—");
  assert.equal(row["Inspection Status"], "Not assigned");
  assert.equal(row.Source, "Unknown origin");
});

test("CSV contains every matching pin across all list pages and the same column values", () => {
  const data = snapshot(Array.from({ length: 45 }, (_, index) => record(index + 1)));
  const rows = nonRegistryRows(data.records);
  const page = paginateRecords(rows, 1, 20);
  assert.equal(page.data.length, 20);
  assert.equal(page.pages, 3);
  const csv = nonRegistryCsv(data);
  assert.equal(csv.charCodeAt(0), 0xFEFF);
  const parsed = Papa.parse(csv.slice(1), { header: true });
  assert.equal(parsed.data.length, 45);
  NON_REGISTRY_COLUMNS.forEach(column => assert.equal(parsed.data[0][column], rows[0][column]));
  assert.equal(parsed.data.at(-1)["Pin Reference"], "45");
  assert.match(parsed.data[0]["Snapshot Checked At"], /Asia\/Manila/);
});

test("empty real snapshots produce a valid headers-only CSV, not an unavailable-data export", () => {
  const csv = nonRegistryCsv(snapshot([]));
  assert.match(csv, /Pin Reference/);
  assert.equal(Papa.parse(csv.slice(1), { header: true }).data.length, 0);
});

test("CSV escapes spreadsheet formulas while retaining Unicode, commas and line breaks", () => {
  const data = snapshot([record(1, { detectedName: "=SUM(1,2)", barangayName: "ñ, Area\nTwo" }),
    record(2, { detectedName: "  +CMD()" })]);
  const parsed = Papa.parse(nonRegistryCsv(data).slice(1), { header: true });
  assert.equal(parsed.data[0]["Business Name"], "'=SUM(1,2)");
  assert.equal(parsed.data[0].Barangay, "ñ, Area\nTwo");
  assert.equal(parsed.data[1]["Business Name"], "'  +CMD()");
});
