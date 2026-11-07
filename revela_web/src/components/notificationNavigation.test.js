import assert from "node:assert/strict";
import test from "node:test";
import { notificationNavigationTarget } from "./notificationNavigation.js";

test("submitted-inspection notifications open the specific report, including older stored alerts", () => {
  assert.equal(notificationNavigationTarget({
    type: "inspection_submitted",
    body: 'Inspection submitted (report #31).',
    link: "/inspections",
  }), "/inspections?reportID=31&openReport=1");
});

test("notifications without an inspection report keep their stored destination", () => {
  assert.equal(notificationNavigationTarget({
    type: "inspection_assigned",
    body: "New inspection assigned.",
    link: "/home",
  }), "/home");
  assert.equal(notificationNavigationTarget({
    type: "inspection_submitted",
    body: "Inspection submitted without a report number.",
    link: "/inspections",
  }), "/inspections");
});
