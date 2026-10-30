import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { formatBarangayMapPopupCount } from "./barangayMapPopup.js";

const mapPageSource = readFileSync(
  new URL("../pages/MapPage.jsx", import.meta.url),
  "utf8",
);
const analyticsMapSource = readFileSync(
  new URL("./MapOverview.jsx", import.meta.url),
  "utf8",
);
const sharedPopupStyles = readFileSync(
  new URL("../styles/barangayMapPopup.css", import.meta.url),
  "utf8",
);

test("shared barangay popup formats registry and map-view metrics accurately", () => {
  assert.equal(formatBarangayMapPopupCount(1234, "registered businesses"), "1,234 registered businesses");
  assert.equal(formatBarangayMapPopupCount(0, "registered businesses"), "0 registered businesses");
  assert.equal(formatBarangayMapPopupCount(null, "registered businesses"), "Unavailable registered businesses");
  assert.equal(formatBarangayMapPopupCount(3, "inspection reports"), "3 inspection reports");
});

test("map hover popup shows only the barangay name and total business count", () => {
  const normalizeFlagSource = mapPageSource.match(/function normalizeFlag\(flag\) \{[\s\S]*?\n\}/)?.[0] ?? "";
  assert.match(normalizeFlagSource, /hasMapCoordinates/);
  assert.match(normalizeFlagSource, /const lat = hasExactCoords \? rawLat : null/);
  assert.match(normalizeFlagSource, /Coordinates unavailable/);
  assert.doesNotMatch(normalizeFlagSource, /getBarangayCentroid|DEFAULT_MAP_CENTER/);
  const hoverHandler = mapPageSource.match(/const handleBoundaryMouseOver = useCallback\([\s\S]*?\n\s{2}\},\s\[barangays,[\s\S]*?\]\);/)?.[0] ?? "";
  assert.match(hoverHandler, /name:\s*label/);
  assert.match(hoverHandler, /count:\s*ranking\?\.total_registered/);
  assert.match(hoverHandler, /countLabel:\s*"total businesses"/);
  assert.doesNotMatch(hoverHandler, /details:|mapMetricsByBarangay|opsRiskTooltipLines/);
  assert.match(mapPageSource, /aggregateMapLocationMetrics\(scopedFilteredFlags,\s*boundaryFeatures\)/);
  assert.match(analyticsMapSource, /createBarangayMapPopup\(\{/);
  assert.match(analyticsMapSource, /row\?\.registry_total/);
  assert.match(analyticsMapSource, /row\?\.inspections\?\.total/);
  assert.match(analyticsMapSource, /"registered businesses"\s*:\s*"inspection reports"/);
});

test("shared popup shell removes Google white surfaces and styles both themes consistently", () => {
  for (const selector of [".map-page .gm-style-iw-c", ".map-overview .gm-style-iw-c"]) {
    assert.ok(sharedPopupStyles.includes(selector));
  }
  assert.match(sharedPopupStyles, /background:\s*var\(--color-modal-bg\)\s*!important/);
  assert.match(sharedPopupStyles, /border:\s*1px solid var\(--color-border\)\s*!important/);
  assert.match(sharedPopupStyles, /box-shadow:/);
  assert.match(sharedPopupStyles, /html\.theme-dark[\s\S]*?filter:\s*invert\(1\)/);
});
