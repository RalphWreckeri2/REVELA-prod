import assert from "node:assert/strict";
import test from "node:test";
import {
  APPROXIMATE_LOCATION_LABEL,
  getApproximateMarkerSvg,
} from "./approximateMapMarker.js";

test("approximate marker uses its flag color with a translucent fill and dashed outline", () => {
  const svg = getApproximateMarkerSvg("#ef4444");

  assert.match(svg, /fill="#ef4444" fill-opacity="0\.22"/);
  assert.match(svg, /stroke="#ef4444"/);
  assert.match(svg, /stroke-dasharray=/);
  assert.match(svg, /<circle cx="24" cy="6" r="5" fill="#ef4444"/);
  assert.match(svg, />~<\/text>/);
  assert.doesNotMatch(svg, /#64748b/);
  assert.equal(APPROXIMATE_LOCATION_LABEL, "Approximate location: barangay center");
});

test("map adjustment rendering forces both exact and approximate pins blue", async () => {
  const mapPage = await import("node:fs/promises").then(({ readFile }) => (
    readFile(new URL("../pages/MapPage.jsx", import.meta.url), "utf8")
  ));
  assert.match(mapPage, /isAdjusting \? "#2563eb" : fc\.marker/);
  assert.match(mapPage, /createApproximateMarkerContent\([\s\S]*?isAdjusting \? "#2563eb" : fc\.marker/);
});
