import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const page = readFileSync(new URL("./ExportReportsPage.jsx", import.meta.url), "utf8");
const compliance = readFileSync(new URL("../components/ComplianceReportCard.jsx", import.meta.url), "utf8");
const styles = readFileSync(new URL("../styles/ExportReportsPage.css", import.meta.url), "utf8");
const loader = readFileSync(new URL("../components/RevelaLoader.jsx", import.meta.url), "utf8");
const loaderStyles = readFileSync(new URL("../styles/RevelaLoader.css", import.meta.url), "utf8");
const pdfDownload = readFileSync(new URL("../components/reportPdfDownload.js", import.meta.url), "utf8");

test("exports separate demographic charts from field reports without the title pill", () => {
  assert.doesNotMatch(page, /BPLO Official/);
  assert.match(page, /aria-label="Report categories"/);
  assert.match(page, /activeSection === "profile" && <section/);
  assert.match(page, /activeSection === "operations" && <section/);
  assert.match(page, /Demographics spreadsheet \(CSV\)/);
  assert.match(page, /Complete dossier \(PDF\)/);
  assert.match(styles, /\.export-report-view-nav\s*\{[^}]*grid-template-columns:\s*repeat\(2, minmax\(0, 1fr\)\)/);
});

test("report loading overlay is limited to refresh and export work and respects reduced motion", () => {
  assert.match(page, /const REPORT_LOADING_MESSAGE = "Refreshing report data and preparing export\.\.\.";/);
  assert.match(page, /import RevelaLoader from "\.\.\/components\/RevelaLoader";/);
  assert.match(page, /preparingExport && <RevelaLoader message=\{REPORT_LOADING_MESSAGE\} \/>/);
  assert.doesNotMatch(page, /\(refreshingReports \|\| preparingExport\) && <RevelaLoader/);
  assert.match(page, /const refreshView = useAppDataRefresh\("reports", async \(\) => \{\s*if \(exportInProgress\.current\) await exportFinished\.current;/);
  assert.doesNotMatch(page, /refreshingReports|setRefreshingReports/);
  assert.match(page, /finally \{\s*exportInProgress\.current = false;\s*setPreparingExport\(false\);/);
  assert.match(page, /const showExportNotice = async options => \{\s*flushSync\(\(\) => setPreparingExport\(false\)\);[\s\S]*?return Swal\.fire\(options\);/);
  assert.match(page, /const blob = await new Promise\(\(resolve, reject\) => \{\s*canvas\.toBlob/);
  assert.match(page, /saveAs\(blob, filename\);\s*await showExportNotice\(\{/);
  assert.match(page, /\}, reportPdfFilename\(`Demographic_\$\{chartTitle\}`\), \{ showSuccess: false \}\);\s*await showExportNotice\(\{/);
  assert.match(page, /\}, reportPdfFilename\("Comprehensive_Municipal_Business_Demographic_Profile"\), \{ showSuccess: false \}\);\s*await showExportNotice\(\{/);
  assert.match(page, /saveAs\([\s\S]*?await showExportNotice\(\{\s*icon: "success",\s*title: "CSV Exported!"/);
  assert.doesNotMatch(page, /ReportLoadingOverlay|export-report-loading-/);
  assert.match(page, /const REPORT_REQUEST_TIMEOUT_MS = 20_000;/);
  assert.match(page, /timedOut = true;\s*controller\.abort\(\);[\s\S]*?REPORT_REQUEST_TIMEOUT_MS/);
  assert.match(page, /const failure = timedOut[\s\S]*?window\.clearTimeout\(timeout\);/);
  assert.match(loader, /animateMotion[\s\S]*repeatCount="indefinite" calcMode="paced"/);
  assert.match(loaderStyles, /animation:\s*revela-loader-trail 3\.2s var\(--loader-phase\) linear infinite/);
  assert.match(loaderStyles, /stroke-dasharray:\s*7 100/);
  assert.match(loaderStyles, /@media \(prefers-reduced-motion: reduce\)/);
  assert.doesNotMatch(page, /animateMotion/);
});

test("export page omits the redundant KPI strip without removing figures from downloads", () => {
  assert.doesNotMatch(page, /Quick Census KPI Strip|Active Municipality-wide|Active vs Total Ratio/);
  assert.match(page, /Section: "KPI", Metric: "Total Registered Entities", Value: kpis\?\.total_businesses/);
  assert.match(page, /Section: "KPI", Metric: "Compliance Rate", Value: `\$\{kpis\?\.compliance_rate/);
  assert.match(page, /type: "demographic-complete"/);
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

test("PDF exports download directly instead of opening the browser print dialog", () => {
  assert.match(page, /downloadCanvasAsPdf\(cropRegion\(reportRegionBounds\["\.report-body"\]\)/);
  assert.match(page, /headerCanvas:\s*cropRegion\(reportRegionBounds\["\.print-header"\]\)/);
  assert.match(page, /footerCanvas:\s*cropRegion\(reportRegionBounds\["\.print-footer"\]\)/);
  assert.match(page, /pageBreaks:\s*safePageBreaks/);
  assert.match(page, /title:\s*"PDF Exported!"/);
  assert.match(page, /text:\s*`Saved as \$\{filename\}`/);
  assert.match(pdfDownload, /pdf\.save\(filename\)/);
  assert.doesNotMatch(page, /window\.print\(\)/);
  assert.match(page, /await downloadReportPdf\(\{/);
  assert.match(page, /visibility:\s*"hidden"/);
  assert.match(page, /clonedDoc\.getElementById\("pdf-report-render-root"\)/);
  assert.match(page, /visibility:\s*"visible"/);
  assert.match(compliance, /PDF downloads directly as a file/);
});

test("complete dossier tables share one print palette while the official header and footer remain", () => {
  const dossier = page.split("CASE 2: Complete Demographic Profile Dossier")[1]?.split("CASE 3: List of Unregistered Businesses")[0] ?? "";
  assert.equal((dossier.match(/className="dossier-section(?: dossier-section--long)?"/g) || []).length, 8);
  assert.doesNotMatch(dossier, /<th style=\{\{ background:/);
  assert.match(page, /\.demographic-complete-body \.print-table th\s*\{[^}]*background: #eaf1ed !important/);
  assert.match(page, /box-decoration-break: clone/);
  assert.match(page, /className="print-header"/);
  assert.match(page, /className="print-footer"/);
});

test("operational PDFs use compact neutral tables without changing the letterhead", () => {
  const unregistered = page.split("CASE 3: List of Unregistered Businesses")[1]?.split("CASE 4: Field Inspector Dispatch Plan")[0] ?? "";
  const dispatch = page.split("CASE 4: Field Inspector Dispatch Plan")[1]?.split("Official Signature Block")[0] ?? "";
  assert.match(page, /operational-print-body \$\{printReport\.type === "admin-confirmed-compliant"/);
  assert.match(page, /admin-confirmed-print-body/);
  assert.match(unregistered, /className="operational-print-body unregistered-print-body"/);
  assert.match(dispatch, /className="operational-print-body dispatch-print-body"/);
  assert.doesNotMatch(unregistered + dispatch, /<th style=\{\{ background:|background: f\.Status|background: r\.RiskLevel/);
  assert.match(page, /\.print-report-container:has\(\.operational-print-body\) \.report-body\s*\{[^}]*box-decoration-break: clone/);
  assert.match(page, /\.operational-print-body \.print-table th\s*\{[^}]*background: #eaf1ed !important/);
  assert.match(page, /className="print-header"/);
  assert.match(page, /className="print-footer"/);
});

test("direct admin confirmation is a separate exportable report from field inspection", () => {
  assert.match(page, /id: "inspection-compliant"/);
  assert.match(page, /id: "admin-confirmed"/);
  assert.match(page, /ADMIN_CONFIRMED_REPORT_TITLE/);
  assert.match(page, /reportType=\{report\.id === "admin-confirmed" \? "admin-confirmed" : "inspection"\}/);
  assert.match(page, /admin-confirmed-compliant/);
});
