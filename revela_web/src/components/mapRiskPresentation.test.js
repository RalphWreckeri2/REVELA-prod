import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import {
  hotspotCircleSummary,
  opsRiskTooltipLines,
} from "./mapRiskPresentation.js";

const mapPageSource = readFileSync(
  new URL("../pages/MapPage.jsx", import.meta.url),
  "utf8",
);

test("OPS polygon tooltip distinguishes priority score from its risk component", () => {
  assert.deepEqual(opsRiskTooltipLines({
    ops_score: 72.15,
    risk_score: 80,
    risk_level: "High",
  }), [
    "OPS priority score: 72.2/100 (High tier)",
    "Risk component: 80.0/100 (normalized weighted Red/Yellow/Black burden)",
  ]);
  assert.deepEqual(opsRiskTooltipLines({ ops_score: null }), []);
  assert.match(mapPageSource, /OPS priority tiers/i);
  assert.match(mapPageSource, /not DBSCAN cluster density/i);
});

test("DBSCAN circle presentation identifies eligible detection records and its parameters", () => {
  assert.deepEqual(hotspotCircleSummary({
    clusterID: 2,
    size: 3,
    radius_m: 42.24,
    eps_m: 50,
    min_samples: 3,
  }), {
    title: "Detection hotspot (DBSCAN) #2",
    members: "3 eligible effective-Red detection pins",
    radius: "42.2 m from centroid",
    parameters: "Haversine eps = 50 m · MinPts = 3",
  });
  assert.match(mapPageSource, /OPS Priority Tiers/);
  assert.match(mapPageSource, /hotspotCircleSummary\(cl\)/);
});
