import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { ANALYTICS_SKELETON_DELAY_MS, scheduleAnalyticsSkeleton } from "../components/analyticsLoadingPolicy.js";

const page = readFileSync(new URL("./AnalyticsPage.jsx", import.meta.url), "utf8");
const map = readFileSync(new URL("../components/MapOverview.jsx", import.meta.url), "utf8");
const layouts = readFileSync(new URL("../components/AnalyticsLoadingLayouts.jsx", import.meta.url), "utf8");
const styles = readFileSync(new URL("../styles/AnalyticsPage.css", import.meta.url), "utf8");
const mapStyles = readFileSync(new URL("../styles/MapOverview.css", import.meta.url), "utf8");

test("first-load skeleton waits 150 ms, and a fast response cancels it", () => {
  let pending;
  let displayed = false;
  const cancel = scheduleAnalyticsSkeleton(() => { displayed = true; }, (callback, delay) => {
    assert.equal(delay, ANALYTICS_SKELETON_DELAY_MS);
    pending = callback;
    return 1;
  }, (timer) => { assert.equal(timer, 1); pending = null; });
  assert.equal(displayed, false);
  cancel();
  assert.equal(pending, null);
  assert.equal(displayed, false);
});

test("cold-load skeleton shares the real KPI, filter, map, panel and ranked-row sizing classes", () => {
  for (const className of ["map-overview-topbar", "map-overview-total", "map-overview-filter-card",
    "map-overview-control-group", "map-overview-layout", "map-overview-map-card", "map-overview-map-stage",
    "map-overview-panel", "map-overview-detail-card", "map-overview-stacked-bar", "analytics-inspector-operations-card",
    "analytics-recommendation-list", "analytics-recommendation-columns", "analytics-recommendation-rows",
    "analytics-recommendation-row", "analytics-recommendation-assignment"]) {
    assert.ok(layouts.includes(className), `missing shared sizing class: ${className}`);
  }
  assert.match(mapStyles, /\.map-overview-total\s*\{[^}]*min-height:\s*88px/);
  assert.match(mapStyles, /\.map-overview-map-card\s*\{[^}]*min-height:\s*610px/);
  assert.match(mapStyles, /\.map-overview-map-stage\s*\{[^}]*min-height:\s*520px/);
  assert.match(styles, /\.analytics-loading-operations-chart\s*\{[^}]*height:\s*260px/);
  assert.match(page, /<ResponsiveChart height=\{Math\.max\(260, operationsStatusRows\.length \* 40 \+ 80\)\}>/);
  assert.match(styles, /\.analytics-loading-recommendation-row\s*\{[^}]*grid-template-columns:\s*var\(--analytics-recommendation-columns\)/);
  assert.match(styles, /\.analytics-update-slot\s*\{[^}]*min-height:\s*18px/);
});

test("cached tabs and refreshes retain content without another page skeleton", () => {
  assert.match(page, /const hasVisibleData = Boolean\(currentSection\.data \|\| rememberedSections\.data\[activeTab\]\)/);
  assert.match(page, /const loading = !hasVisibleData && currentSection\.status === "loading"/);
  assert.match(page, /activeTab === "descriptive" && loading &&/);
  assert.match(page, /activeTab === "prescriptive" && loading &&/);
  assert.match(page, /aria-busy=\{loading\}/);
  assert.match(page, /aria-live="polite"/);
  assert.match(map, /previous\.overview/);
  assert.match(map, /<OverviewMapSkeleton \/>/);
  assert.match(styles, /@media \(prefers-reduced-motion: reduce\)/);
});
