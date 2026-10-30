import assert from "node:assert/strict";
import test from "node:test";
import {
  APPROXIMATE_LOCATION_LABEL,
  getApproximateMarkerSvg,
} from "./approximateMapMarker.js";

test("approximate marker is neutral, hollow, dashed, and labeled with a tilde", () => {
  const svg = getApproximateMarkerSvg();

  assert.match(svg, /fill="none"/);
  assert.match(svg, /stroke="#64748b"/);
  assert.match(svg, /stroke-dasharray=/);
  assert.match(svg, />~<\/text>/);
  assert.doesNotMatch(svg, /#ef4444|#22c55e|#f59e0b|#e65100/);
  assert.equal(APPROXIMATE_LOCATION_LABEL, "Approximate location: barangay center");
});
