import test from "node:test";
import assert from "node:assert/strict";
import { ANALYTICS_TABS, analyticsRoute } from "./analyticsNavigation.js";

test("only Overview and Recommendations are canonical tabs", () => {
  assert.deepEqual(ANALYTICS_TABS, ["descriptive", "prescriptive"]);
});

test("deep link parses a validated prescriptive tab and barangay across reloads", () => {
  const url = "?tab=prescriptive&barangay_id=12";
  assert.deepEqual(analyticsRoute(url), { tab: "prescriptive", barangayId: 12 });
  assert.deepEqual(analyticsRoute(new URL(`https://local.test/analytics${url}`).search), analyticsRoute(url));
  assert.deepEqual(analyticsRoute("?tab=unsupported&barangay_id=-1"), { tab: "descriptive", barangayId: null });
  assert.deepEqual(analyticsRoute("?tab=prescriptive&barangay_id=1%20OR%201"), { tab: "prescriptive", barangayId: null });
});

test("legacy Diagnostic and Operations links resolve to the remaining tabs", () => {
  assert.deepEqual(analyticsRoute("?tab=diagnostic&barangay_id=12"), { tab: "prescriptive", barangayId: 12 });
  assert.deepEqual(analyticsRoute("?tab=operations&barangay_id=12"), { tab: "descriptive", barangayId: 12 });
});
