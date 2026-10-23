import test from "node:test";
import assert from "node:assert/strict";

import {
  canClearWarning,
  canUnlockBlackDispatch,
  clearWarningBlockedReason,
  isBlackDispatchAllowed,
  isBlackLocked,
  warningLevel,
  canClearInspectionWarning,
  clearInspectionWarning,
} from "./registryLadderPolicy.js";
import { canDispatchFlag, dispatchButtonLabel } from "./dispatchEligibility.js";

const business = (over = {}) => ({
  businessID: "BIZ-1",
  applicationStatus: "Active",
  warningLevel: 0,
  blackLocked: false,
  blackDispatchUnlocked: false,
  ...over,
});

test("Clear Warning is offered to an admin when there is a warning", () => {
  assert.equal(canClearWarning(business({ warningLevel: 1 }), "Admin"), true);
  assert.equal(
    canClearWarning(business({ warningLevel: 3 }), "SUPER_ADMIN"),
    true,
  );
});

test("Clear Warning is hidden at level 0", () => {
  assert.equal(canClearWarning(business({ warningLevel: 0 }), "Admin"), false);
  assert.equal(canClearWarning(business(), "Admin"), false);
});

test("Clear Warning is hidden on a Black-locked row even with a warning", () => {
  assert.equal(
    canClearWarning(business({ warningLevel: 2, blackLocked: true }), "Admin"),
    false,
  );
});

test("Clear Warning is hidden from non-admins even with a warning", () => {
  assert.equal(
    canClearWarning(business({ warningLevel: 1 }), "Inspector"),
    false,
  );
  assert.equal(
    canClearWarning(business({ warningLevel: 1 }), "System Administrator"),
    false,
  );
});

test("the blocked reason explains each case", () => {
  assert.equal(
    clearWarningBlockedReason(business({ warningLevel: 2 }), "Admin"),
    null,
  );
  assert.equal(
    clearWarningBlockedReason(business({ warningLevel: 0 }), "Admin"),
    "There is no warning to clear",
  );
  assert.equal(
    clearWarningBlockedReason(
      business({ warningLevel: 1, blackLocked: true }),
      "Admin",
    ),
    "Warnings cannot be cleared while this business is Black locked.",
  );
  assert.equal(
    clearWarningBlockedReason(business({ warningLevel: 1 }), "Inspector"),
    "Admins only",
  );
});

test("Black dispatch unlock is never offered", () => {
  const black = business({ blackLocked: true });
  assert.equal(canUnlockBlackDispatch(black, "SUPER_ADMIN"), false);
  assert.equal(canUnlockBlackDispatch(black, "Admin"), false);
  assert.equal(canUnlockBlackDispatch(black, "Inspector"), false);
});

test("Unlock is only for Black rows", () => {
  assert.equal(
    canUnlockBlackDispatch(business({ warningLevel: 2 }), "SUPER_ADMIN"),
    false,
  );
  assert.equal(canUnlockBlackDispatch(business(), "SUPER_ADMIN"), false);
});

test("Unlock is not offered twice for one grant", () => {
  const unlocked = business({ blackLocked: true, blackDispatchUnlocked: true });
  assert.equal(canUnlockBlackDispatch(unlocked, "SUPER_ADMIN"), false);
});

test("Revoked counts as Black even without a stored lock bit", () => {
  const revoked = business({
    applicationStatus: "Revoked",
    warningLevel: 1,
    blackLocked: 0,
  });
  assert.equal(isBlackLocked(revoked), true);
  assert.equal(canClearWarning(revoked, "Admin"), false);
  assert.equal(canUnlockBlackDispatch(revoked, "SUPER_ADMIN"), false);
});

test("a missing business never shows either button", () => {
  assert.equal(canClearWarning(null, "SUPER_ADMIN"), false);
  assert.equal(canUnlockBlackDispatch(undefined, "SUPER_ADMIN"), false);
});

test("a missing or unreadable warning level reads as zero", () => {
  assert.equal(warningLevel({}), 0);
  assert.equal(warningLevel({ warningLevel: null }), 0);
  assert.equal(warningLevel({ warningLevel: "nonsense" }), 0);
  assert.equal(warningLevel({ warningLevel: "2" }), 2);
});

test("Black is never dispatchable, including with a legacy grant", () => {
  assert.equal(isBlackDispatchAllowed({ color: "Black" }), false);
  assert.equal(
    isBlackDispatchAllowed({ color: "Black", blackDispatchUnlocked: true }),
    false,
  );
});

test("a non-Black flag is unaffected by the unlock flag", () => {
  for (const color of ["Red", "Yellow", "Orange", "Purple", "Green"]) {
    assert.equal(isBlackDispatchAllowed({ color }), true, color);
  }
});

test("the gate always blocks Black regardless of legacy grant", () => {
  assert.equal(canDispatchFlag({ color: "Black" }, { isAdmin: true }), false);
  assert.equal(
    canDispatchFlag(
      { color: "Black", blackDispatchUnlocked: true },
      { isAdmin: true },
    ),
    false,
  );
});

test("an unlocked Black still needs an admin", () => {
  assert.equal(
    canDispatchFlag(
      { color: "Black", blackDispatchUnlocked: true },
      { isAdmin: false },
    ),
    false,
  );
});

test("the Black dispatch label explains dispatch is forbidden", () => {
  assert.equal(
    dispatchButtonLabel({ color: "Black", blackDispatchUnlocked: true }),
    "Black businesses cannot be dispatched",
  );
  assert.equal(
    dispatchButtonLabel({ color: "Black" }),
    "Black businesses cannot be dispatched",
  );
});

test("Green stays blocked even on a re-dispatch", () => {
  assert.equal(
    canDispatchFlag(
      { color: "Green", verificationStatus: "Verified" },
      { isAdmin: true },
    ),
    false,
  );
  assert.equal(
    canDispatchFlag(
      { color: "Green", hasActiveInspection: true },
      { isAdmin: true },
    ),
    false,
  );
});

/**
 * The rows below are the shape get_business_by_id actually returns: the
 * registry's own snake_case columns alongside the ladder's camelCase ones,
 * plus the derived flagColor and flagSource the readers compute.
 *
 * These are the cases the buttons exist for. If the readers ever rename a key
 * or stop returning one, these fail rather than the buttons quietly vanishing.
 */
const registryRow = (over = {}) => ({
  businessID: "BIZ-1",
  businessName: "ACME STORE",
  applicationStatus: "Active",
  latitude: 13.96,
  longitude: 121.11,
  coordSource: "manual",
  matchStatus: "approved",
  matchScore: null,
  placeID: null,
  lastRenewalDate: "2026-01-15",
  barangayID: 1,
  barangayName: "Poblacion",
  flagSource: "registry_and_maps",
  flagColor: "Green",
  warningLevel: 0,
  blackLocked: 0,
  blackDispatchUnlocked: 0,
  ...over,
});

test("an Active business with a warning shows Clear Warning to an admin", () => {
  const row = registryRow({ warningLevel: 1, flagColor: "Orange" });
  assert.equal(canClearWarning(row, "Admin"), true);
  assert.equal(canClearWarning(row, "SUPER_ADMIN"), true);
});

test("an Active business with no warning shows nothing", () => {
  const row = registryRow();
  assert.equal(canClearWarning(row, "Admin"), false);
  assert.equal(
    clearWarningBlockedReason(row, "Admin"),
    "There is no warning to clear",
  );
});

test("a warned business still shows nothing to a non-admin", () => {
  const row = registryRow({ warningLevel: 2, flagColor: "Orange" });
  assert.equal(canClearWarning(row, "Inspector"), false);
  assert.equal(clearWarningBlockedReason(row, "Inspector"), "Admins only");
});

test("a locked Black business never offers a dispatch unlock", () => {
  const row = registryRow({
    applicationStatus: "Revoked",
    flagColor: "Black",
    warningLevel: 3,
    blackLocked: 1,
  });
  assert.equal(canUnlockBlackDispatch(row, "SUPER_ADMIN"), false);
  assert.equal(canUnlockBlackDispatch(row, "Admin"), false);
  assert.equal(canUnlockBlackDispatch(row, "System Administrator"), false);
});

test("an unlocked Black business hides Unlock", () => {
  const row = registryRow({
    applicationStatus: "Revoked",
    flagColor: "Black",
    warningLevel: 3,
    blackLocked: 1,
    blackDispatchUnlocked: 1,
  });
  assert.equal(canUnlockBlackDispatch(row, "SUPER_ADMIN"), false);
});

test("a locked Black business cannot have its warning cleared", () => {
  const row = registryRow({
    applicationStatus: "Revoked",
    flagColor: "Black",
    warningLevel: 3,
    blackLocked: 1,
  });
  assert.equal(canClearWarning(row, "SUPER_ADMIN"), false);
  assert.equal(
    clearWarningBlockedReason(row, "SUPER_ADMIN"),
    "Warnings cannot be cleared while this business is Black locked.",
  );
});

test("an unmigrated payload - all zeros - shows neither button", () => {
  // What the readers return when the columns do not exist.
  const row = registryRow({
    warningLevel: 0,
    blackLocked: 0,
    blackDispatchUnlocked: 0,
  });
  assert.equal(canClearWarning(row, "SUPER_ADMIN"), false);
  assert.equal(canUnlockBlackDispatch(row, "SUPER_ADMIN"), false);
  assert.equal(
    canDispatchFlag({ ...row, color: "Black" }, { isAdmin: true }),
    false,
  );
});

test("the Black dispatch rule reads the same payload", () => {
  const locked = {
    ...registryRow({ flagColor: "Black", blackLocked: 1 }),
    color: "Black",
  };
  const unlocked = { ...locked, blackDispatchUnlocked: 1 };
  assert.equal(canDispatchFlag(locked, { isAdmin: true }), false);
  assert.equal(canDispatchFlag(unlocked, { isAdmin: true }), false);
});

const inspection = (over = {}) => ({
  ...registryRow({ warningLevel: 1, flagColor: "Orange" }),
  reportID: 7,
  inspectionResult: "Orange",
  verificationStatus: "Verified",
  hasNonVerifiedInspection: 0,
  ...over,
});

test("Inspection Clear Warning requires a Verified warned business and no open inspection", () => {
  assert.equal(canClearInspectionWarning(inspection(), "Admin"), true);
  for (const changes of [
    { verificationStatus: "Submitted" },
    { inspectionResult: "Green", flagColor: "Green" },
    { warningLevel: 0 },
    { hasNonVerifiedInspection: 1 },
    { hasNonVerifiedInspection: undefined },
    { blackLocked: 1 },
    { applicationStatus: "Revoked" },
    { flagColor: "Black" },
  ]) {
    assert.equal(
      canClearInspectionWarning(inspection(changes), "Admin"),
      false,
    );
  }
  assert.equal(canClearInspectionWarning(inspection(), "Inspector"), false);
});

test("Inspection Clear Warning supports an unregistered pin with an active warning", () => {
  const pin = inspection({
    businessID: null,
    logID: 21,
    warningBaseColor: "Yellow",
  });
  assert.equal(canClearInspectionWarning(pin, "Admin"), true);
  for (const changes of [
    { logID: null },
    { flagColor: "Red" },
    { warningLevel: 0 },
    { blackLocked: 1 },
  ]) {
    assert.equal(
      canClearInspectionWarning({ ...pin, ...changes }, "Admin"),
      false,
    );
  }
});

test("clearing an Inspection warning refreshes detail before notifying the Map", async () => {
  const calls = [];
  const report = inspection();
  const result = await clearInspectionWarning({
    report,
    role: "Admin",
    reason: "resolved",
    token: "test-token",
    request: async (...args) => {
      calls.push(["clear", ...args]);
      return { warningLevel: 0 };
    },
    refresh: async () => {
      calls.push(["refresh-detail"]);
    },
    onChanged: () => calls.push(["refresh-map"]),
  });
  assert.equal(result.warningLevel, 0);
  assert.deepEqual(calls, [
    ["clear", "BIZ-1", "resolved", "test-token", "business", {}],
    ["refresh-detail"],
    ["refresh-map"],
  ]);
});

test("clearing an unregistered Inspection warning targets the geospatial log", async () => {
  const calls = [];
  const report = inspection({
    businessID: null,
    logID: 21,
    warningBaseColor: "Red",
  });
  await clearInspectionWarning({
    report,
    role: "Admin",
    reason: "Complied",
    token: "test-token",
    businessID: "B-21",
    registryReviewToken: "review-token",
    confirmEstablishment: true,
    request: async (...args) => {
      calls.push(args);
      return { warningLevel: 0 };
    },
    refresh: async () => {},
  });
  assert.deepEqual(calls, [[
    21, "Complied", "test-token", "geospatial_log", {
      reportID: 7,
      businessID: "B-21",
      registryReviewToken: "review-token",
      confirmEstablishment: true,
    },
  ]]);
});

test("a refused clear cannot trigger a success refresh", async () => {
  const calls = [];
  await assert.rejects(
    clearInspectionWarning({
      report: inspection(),
      role: "Admin",
      request: async () => {
        throw new Error("Inspection is still open");
      },
      refresh: async () => calls.push("refresh"),
      onChanged: () => calls.push("changed"),
    }),
    /Inspection is still open/,
  );
  assert.deepEqual(calls, []);
});

test("driver string zero never creates a lock or an unlock grant", () => {
  assert.equal(isBlackLocked(business({ blackLocked: "0" })), false);
  assert.equal(
    canDispatchFlag(
      { color: "Black", blackDispatchUnlocked: "0" },
      { isAdmin: true },
    ),
    false,
  );
});
