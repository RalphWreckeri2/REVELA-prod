import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { DEFAULT_WLC_WEIGHTS, wlcPolicyError, registryFlagRateLabel, opsRadarData, rebalanceWlcWeight, hasDispatchableWlcTargets, wlcEligibilityLabel } from "./wlcPolicy.js";

const analyticsPageSource = readFileSync(
  new URL("../pages/AnalyticsPage.jsx", import.meta.url),
  "utf8",
);
const settingsPageSource = readFileSync(
  new URL("../pages/SettingsPage.jsx", import.meta.url),
  "utf8",
);

test("interview-derived defaults remain exactly 68/7/25", () => {
  assert.deepEqual(DEFAULT_WLC_WEIGHTS, { w1_risk: 68, w2_sector: 7, w3_distance: 25 });
  assert.equal(wlcPolicyError(DEFAULT_WLC_WEIGHTS), "");
});

test("invalid weights cannot be saved, including NaN, strings and incorrect totals", () => {
  const invalid = [
    { w1_risk: -1 }, { w1_risk: 101 }, { w1_risk: NaN }, { w1_risk: "68" },
    { w1_risk: true }, { w3_distance: Infinity }, { w1_risk: 50 },
    { bplo_lat: 91 }, { bplo_lng: -181 }, { bplo_lat: null },
  ];
  invalid.forEach(update => assert.notEqual(wlcPolicyError({ ...DEFAULT_WLC_WEIGHTS, ...update }), ""));
  assert.equal(wlcPolicyError({ w1_risk: 68.1, w2_sector: 7, w3_distance: 24.9 }), "");
  assert.equal(wlcPolicyError({ w1_risk: 0, w2_sector: 100, w3_distance: 0 }), "");
});

test("unknown registry denominator is N/A, never an invented zero or clipped percentage", () => {
  assert.equal(registryFlagRateLabel(null), "N/A");
  assert.equal(registryFlagRateLabel(undefined), "N/A");
  assert.equal(registryFlagRateLabel(0), "0.0%");
  assert.equal(registryFlagRateLabel(25), "25.0%");
  assert.equal(registryFlagRateLabel(100), "100.0%");
  assert.equal(registryFlagRateLabel(150), "N/A");
});

test("radar shows actual WLC components instead of a capped record-to-registry ratio", () => {
  const rows = [
    { barangayName: "A", flagged_count: 5, ops_score: 75, risk_score: 80, proximity_score: 50, non_compliance_rate: 500 },
    { barangayName: "Empty", flagged_count: 0, ops_score: 0 },
  ];
  assert.deepEqual(opsRadarData(rows), [{ barangay: "A", OPS: 75, Risk: 80, Proximity: 50 }]);
  assert.equal(opsRadarData(Array.from({ length: 12 }, () => rows[0])).length, 8);
});

test("linked sliders rebalance only explicit edits and keep the sector criterion available", () => {
  for (let weight = 0; weight <= 100; weight += 1) {
    for (const key of ["w1_risk", "w2_sector", "w3_distance"]) {
      const next = rebalanceWlcWeight(DEFAULT_WLC_WEIGHTS, key, weight);
      assert.equal(next[key], weight);
      assert.equal(wlcPolicyError(next), "");
    }
  }
  assert.deepEqual(rebalanceWlcWeight(DEFAULT_WLC_WEIGHTS, "w1_risk", 68), DEFAULT_WLC_WEIGHTS);
  assert.deepEqual(DEFAULT_WLC_WEIGHTS, { w1_risk: 68, w2_sector: 7, w3_distance: 25 });
});

test("sector weight is not gated or zeroed by missing sector data", () => {
  const next = rebalanceWlcWeight(DEFAULT_WLC_WEIGHTS, "w2_sector", 20);
  assert.equal(next.w2_sector, 20);
  assert.equal(wlcPolicyError(next), "");
});

test("analytics and policy settings disclose the neutral sector fallback", () => {
  assert.match(analyticsPageSource, /Missing sector overrides use the existing neutral score of 50/);
  assert.match(analyticsPageSource, /configured sector weight is retained; weights are not redistributed/i);
  assert.match(settingsPageSource, /Missing sector overrides use the existing neutral score of 50/);
  assert.match(settingsPageSource, /saved weights are applied unchanged, not redistributed/i);
});

test("field queues skip Black-only and fully assigned barangays while retaining WLC risk context", () => {
  const black = { flagged_count: 10, red_count: 0, yellow_count: 0, black_count: 10, dispatchable_count: 0 };
  const assigned = { flagged_count: 5, red_count: 5, yellow_count: 0, dispatchable_count: 0 };
  const eligible = { flagged_count: 5, red_count: 3, yellow_count: 2, dispatchable_count: 1 };
  assert.equal(hasDispatchableWlcTargets(black), false);
  assert.match(wlcEligibilityLabel(black), /administrative review/);
  assert.equal(hasDispatchableWlcTargets(assigned), false);
  assert.match(wlcEligibilityLabel(assigned), /Already assigned/);
  assert.equal(hasDispatchableWlcTargets(eligible), true);
  assert.equal(wlcEligibilityLabel(eligible), "1 eligible for new dispatch");
});
