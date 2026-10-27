import test from "node:test";
import assert from "node:assert/strict";
import { analyticsRoute } from "./analyticsNavigation.js";

test("deep link parses a validated prescriptive tab and barangay across reloads", () => {
  const url = "?tab=prescriptive&barangay_id=12";
  assert.deepEqual(analyticsRoute(url), { tab: "prescriptive", barangayId: 12 });
  assert.deepEqual(analyticsRoute(new URL(`https://local.test/analytics${url}`).search), analyticsRoute(url));
  assert.deepEqual(analyticsRoute("?tab=unsupported&barangay_id=-1"), { tab: "descriptive", barangayId: null });
  assert.deepEqual(analyticsRoute("?tab=prescriptive&barangay_id=1%20OR%201"), { tab: "prescriptive", barangayId: null });
});
