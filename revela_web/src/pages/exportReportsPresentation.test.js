import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const page = readFileSync(new URL("./ExportReportsPage.jsx", import.meta.url), "utf8");
const compliance = readFileSync(new URL("../components/ComplianceReportCard.jsx", import.meta.url), "utf8");
const styles = readFileSync(new URL("../styles/ExportReportsPage.css", import.meta.url), "utf8");

test("exports separate demographic charts from field reports without the title pill", () => {
  assert.doesNotMatch(page, /BPLO Official/);
  assert.match(page, /aria-label="Report categories"/);
  assert.match(page, /activeSection === "profile" && <section/);
  assert.match(page, /activeSection === "operations" && <section/);
  assert.match(page, /Demographics spreadsheet \(CSV\)/);
  assert.match(page, /Complete dossier \(PDF\)/);
  assert.match(styles, /\.export-report-view-nav\s*\{[^}]*grid-template-columns:\s*repeat\(2, minmax\(0, 1fr\)\)/);
});

test("each chart keeps its PNG and PDF handlers behind one export menu", () => {
  for (const id of ["size", "type", "reg-type", "sector", "barangay", "compliance_size", "timeline"]) {
    assert.equal((page.match(new RegExp(`<ChartExportMenu chartId="${id}"`, "g")) || []).length, 1);
    assert.match(page, new RegExp(`onPng=\\{\\(\\) => exportChartAsImage\\("${id}"\\)\\}`));
    assert.match(page, new RegExp(`onPdf=\\{\\(\\) => exportChartAsPdf\\("${id}"`));
  }
  assert.match(page, /<ExportActionsMenu className="no-export"/);
  assert.match(page, /querySelectorAll\("\.no-export"\)/);
  assert.match(compliance, /<details className="operational-report-details">/);
});
