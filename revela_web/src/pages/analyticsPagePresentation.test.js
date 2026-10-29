import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const pageSource = readFileSync(new URL("./AnalyticsPage.jsx", import.meta.url), "utf8");
const stylesheet = readFileSync(new URL("../styles/AnalyticsPage.css", import.meta.url), "utf8");

test("Overview and Recommendations share one centered width and title wrapper", () => {
  assert.match(pageSource, /<div className="analytics-page-shell">[\s\S]*?analytics-page-heading[\s\S]*?analytics-recommendation-list/);
  assert.match(stylesheet, /\.analytics-page-shell\s*\{\s*width:\s*min\(100%,\s*1440px\);\s*min-width:\s*0;\s*margin-inline:\s*auto;/);
  assert.doesNotMatch(stylesheet, /\.analytics-page--prescriptive\s+\.saas-content/);
});

test("ranked row owns its single expandable dispatch detail surface", () => {
  assert.match(pageSource, /<details key=\{row\.barangayID\} className="analytics-recommendation-row">[\s\S]*?<summary>[\s\S]*?<div className="analytics-recommendation-detail">[\s\S]*?dispatch\.actionSteps/);
  assert.equal((pageSource.match(/className="analytics-recommendation-detail"/g) || []).length, 1);
  assert.match(pageSource, /ADMIN_PRESCRIPTIVE_DETAILS_ENABLED\s*=\s*false/);
});

test("recommendation controls use the agreed wording and lazily mount Evidence", () => {
  assert.match(pageSource, /Dispatch recommendations cover up to 3 barangays; others wait for a free inspector\./);
  assert.match(pageSource, /Show all \$\{activeRecommendations\.rows\.length\}/);
  assert.match(pageSource, /activeRecommendations\.noActiveFlagsCount[\s\S]*?no active flags\./);
  assert.match(pageSource, /straight-line distance from the BPLO office to the average location of dispatchable Red and Yellow records/);
  assert.match(pageSource, /sector score is a configured policy input, not measured industry risk/);
  assert.match(pageSource, /evidenceOpen && \([\s\S]*?Spatial clusters and scan history are supporting evidence only/);
});
