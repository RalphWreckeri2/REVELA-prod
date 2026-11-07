import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import { notificationNavigationTarget } from "./notificationNavigation.js";

test("inspection notifications open the specific report, including older stored alerts", () => {
  for (const type of ["inspection_assigned", "inspection_submitted"]) {
    assert.equal(notificationNavigationTarget({
      type,
      body: `Inspection activity (report #31).`,
      link: type === "inspection_assigned" ? "/home" : "/inspections",
    }), "/inspections?reportID=31&openReport=1");
  }
    assert.equal(notificationNavigationTarget({
      type: "inspection_assigned",
      body: "New inspection assignment.",
      link: "/inspections?reportID=42&openReport=1",
    }), "/inspections?reportID=42&openReport=1");
  assert.equal(notificationNavigationTarget({
    type: "inspection_submitted",
    reportID: 47,
    body: "Inspection submitted.",
    link: "/inspections",
  }), "/inspections?reportID=47&openReport=1");
});

test("flag notifications open the specific map flag from current and legacy alerts", () => {
  assert.equal(notificationNavigationTarget({
    type: "yellow_flag_reported",
    logID: 633,
    body: "Flag reported.",
    link: "/map",
  }), "/map?flag=633");
  assert.equal(notificationNavigationTarget({
    type: "yellow_flag_reported",
    body: "Open the Map to review (log #632).",
    link: "/map",
  }), "/map?flag=632");
  assert.equal(notificationNavigationTarget({
    type: "yellow_flag_reported",
    body: "Flag reported.",
    link: "/map?flag=634",
  }), "/map?flag=634");
});

test("password reset notifications open the requested user's reset details", () => {
  assert.equal(notificationNavigationTarget({
    type: "password_reset_requested",
    body: "Inspector Name has requested a manual password reset.",
    link: "/users",
  }), "/users?userName=Inspector%20Name&openReset=1");
  assert.equal(notificationNavigationTarget({
    type: "password_reset_requested",
    userID: 9,
    body: "Password reset requested.",
    link: "/users",
  }), "/users?userID=9&openReset=1");
});

test("notifications without a specific record keep their stored destination", () => {
  assert.equal(notificationNavigationTarget({
    type: "inspection_submitted",
    body: "Inspection submitted without a report number.",
    link: "/inspections",
  }), "/inspections");
  assert.equal(notificationNavigationTarget({
    type: "unrecognized",
    link: "/home",
  }), "/home");
});

test("user management opens and clears reset-request deep links", () => {
  const source = readFileSync(
    new URL("../pages/UserManagementPage.jsx", import.meta.url),
    "utf8",
  );
  assert.match(source, /searchParams\.get\("openReset"\)/);
  assert.match(source, /setUserToReset\(matchingUsers\[0\]\)/);
  assert.match(source, /next\.delete\("openReset"\)/);
});
