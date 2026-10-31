import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const pageSource = readFileSync(new URL("./AnalyticsPage.jsx", import.meta.url), "utf8");
const stylesheet = readFileSync(new URL("../styles/AnalyticsPage.css", import.meta.url), "utf8");
const mapStylesheet = readFileSync(new URL("../styles/MapOverview.css", import.meta.url), "utf8");

test("Overview and Recommendations share one centered width and title wrapper", () => {
  assert.match(pageSource, /<div className="analytics-page-shell">[\s\S]*?analytics-page-heading[\s\S]*?analytics-recommendation-list/);
  assert.match(stylesheet, /\.analytics-page-shell\s*\{\s*width:\s*100%;\s*min-width:\s*0;/);
  assert.doesNotMatch(stylesheet, /\.analytics-page--prescriptive\s+\.saas-content/);
});

test("analytics view switch is prominent, descriptive, and responsive in both themes", () => {
  assert.match(pageSource, /className="analytics-view-switcher"/);
  assert.match(pageSource, /description: "Key numbers and trends"/);
  assert.match(pageSource, /description: "Where to focus next"/);
  assert.match(pageSource, /aria-current=\{isActive \? "page" : undefined\}/);
  assert.match(stylesheet, /\.analytics-section-nav\s*\{[^}]*grid-template-columns:\s*repeat\(2,\s*minmax\(0,\s*1fr\)\)/);
  assert.match(stylesheet, /\.analytics-tab-btn\.active::before/);
  assert.match(stylesheet, /html\.theme-dark \.analytics-tab-btn\.active/);
  assert.match(stylesheet, /@container analytics-content \(max-width: 639px\)\s*\{\s*\.analytics-section-nav\s*\{ grid-template-columns: minmax\(0, 1fr\); \}/);
});

test("Overview KPI cards share the content width and use balanced sizing", () => {
  assert.match(mapStylesheet, /\.map-overview-topbar\s*\{[^}]*grid-template-columns:\s*repeat\(3,\s*minmax\(0,\s*1fr\)\)/);
  assert.match(mapStylesheet, /\.map-overview-total\s*\{[^}]*box-sizing:\s*border-box;[^}]*min-height:\s*88px;[^}]*padding:\s*14px 16px;/);
  assert.match(mapStylesheet, /\.map-overview-total strong\s*\{[^}]*font-size:\s*clamp\(24px,\s*2\.2vw,\s*32px\)/);
});

test("ranked row owns its single expandable dispatch detail surface", () => {
  assert.match(pageSource, /<details key=\{row\.barangayID\} className="analytics-recommendation-row">[\s\S]*?<summary>[\s\S]*?<div className="analytics-recommendation-detail">[\s\S]*?dispatch\.actionSteps/);
  assert.equal((pageSource.match(/className="analytics-recommendation-detail"/g) || []).length, 1);
  assert.match(pageSource, /ADMIN_PRESCRIPTIVE_DETAILS_ENABLED\s*=\s*false/);
});

test("recommendation controls retain wording and show one scan summary without Evidence", () => {
  assert.match(pageSource, /Dispatch recommendations cover up to 3 barangays; others wait for a free inspector\./);
  assert.match(pageSource, /Show all \$\{activeRecommendations\.rows\.length\}/);
  assert.match(pageSource, /activeRecommendations\.noActiveFlagsCount[\s\S]*?no active flags\./);
  assert.match(pageSource, /straight-line distance from the BPLO office to the average location of dispatchable Red and Yellow records/);
  assert.match(pageSource, /sector score is a configured policy input, not measured industry risk/);
  assert.doesNotMatch(pageSource, /analytics-evidence-disclosure|Evidence: nearby records/);
  assert.doesNotMatch(pageSource, /Nearby flagged records|Severe flags by barangay|Registry-Linked Status by Sector|Detection Scan History/);
  assert.match(pageSource, /analyticsDetectionScanSummary\(lastDetectionRun\)/);
  assert.match(pageSource, /getAnalyticsHotspotsRequest\(token, "all"/);
  assert.match(pageSource, /categoryRiskDrivers: data\?\.diagnostic\?\.category_risk_drivers/);
  assert.match(pageSource, /scanHistory: data\?\.diagnostic\?\.scan_history/);
  assert.match(pageSource, /dbscan_clusters/);
});
