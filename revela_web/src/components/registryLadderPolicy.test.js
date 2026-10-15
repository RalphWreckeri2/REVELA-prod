import test from "node:test";
import assert from "node:assert/strict";

import {
  canClearWarning,
  canUnlockBlackDispatch,
  clearWarningBlockedReason,
  isBlackDispatchAllowed,
  isBlackLocked,
  warningLevel,
} from "./registryLadderPolicy.js";
import {
  canDispatchFlag,
  dispatchButtonLabel,
} from "./dispatchEligibility.js";

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
  assert.equal(canClearWarning(business({ warningLevel: 3 }), "SUPER_ADMIN"), true);
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
    canClearWarning(business({ warningLevel: 1 }), "Inspector"), false);
  assert.equal(
    canClearWarning(business({ warningLevel: 1 }), "System Administrator"), false);
});

test("the blocked reason explains each case", () => {
  assert.equal(
    clearWarningBlockedReason(business({ warningLevel: 2 }), "Admin"), null);
  assert.equal(
    clearWarningBlockedReason(business({ warningLevel: 0 }), "Admin"),
    "There is no warning to clear");
  assert.equal(
    clearWarningBlockedReason(business({ warningLevel: 1, blackLocked: true }), "Admin"),
    "This business is Black locked. Only a SUPER_ADMIN unlock applies.");
  assert.equal(
    clearWarningBlockedReason(business({ warningLevel: 1 }), "Inspector"),
    "Admins only");
});

test("Unlock is SUPER_ADMIN only", () => {
  const black = business({ blackLocked: true });
  assert.equal(canUnlockBlackDispatch(black, "SUPER_ADMIN"), true);
  assert.equal(canUnlockBlackDispatch(black, "Admin"), false);
  assert.equal(canUnlockBlackDispatch(black, "Inspector"), false);
});

test("Unlock is only for Black rows", () => {
  assert.equal(canUnlockBlackDispatch(business({ warningLevel: 2 }), "SUPER_ADMIN"), false);
  assert.equal(canUnlockBlackDispatch(business(), "SUPER_ADMIN"), false);
});

test("Unlock is not offered twice for one grant", () => {
  const unlocked = business({ blackLocked: true, blackDispatchUnlocked: true });
  assert.equal(canUnlockBlackDispatch(unlocked, "SUPER_ADMIN"), false);
});

test("a Black colour alone does not count as locked", () => {
  // Revoked and Blacklisted permits render Black but are not locked, so they
  // are not unlockable.
  assert.equal(isBlackLocked(business({ applicationStatus: "Revoked" })), false);
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

test("Black is dispatchable only while a grant is open", () => {
  assert.equal(isBlackDispatchAllowed({ color: "Black" }), false);
  assert.equal(isBlackDispatchAllowed({ color: "Black", blackDispatchUnlocked: true }), true);
});

test("a non-Black flag is unaffected by the unlock flag", () => {
  for (const color of ["Red", "Yellow", "Orange", "Purple", "Green"]) {
    assert.equal(isBlackDispatchAllowed({ color }), true, color);
  }
});

test("the gate agrees: a plain Black is blocked, an unlocked Black is allowed", () => {
  assert.equal(canDispatchFlag({ color: "Black" }, { isAdmin: true }), false);
  assert.equal(
    canDispatchFlag({ color: "Black", blackDispatchUnlocked: true }, { isAdmin: true }),
    true,
  );
});

test("an unlocked Black still needs an admin", () => {
  assert.equal(
    canDispatchFlag({ color: "Black", blackDispatchUnlocked: true }, { isAdmin: false }),
    false,
  );
});

test("the button label says when the Black dispatch is an exception", () => {
  assert.equal(
    dispatchButtonLabel({ color: "Black", blackDispatchUnlocked: true }),
    "Dispatch inspector (unlocked)",
  );
  assert.equal(dispatchButtonLabel({ color: "Black" }), "Dispatch inspector");
});

test("Green stays blocked even on a re-dispatch", () => {
  assert.equal(canDispatchFlag({ color: "Green", verificationStatus: "Verified" }, { isAdmin: true }), false);
  assert.equal(canDispatchFlag({ color: "Green", hasActiveInspection: true }, { isAdmin: true }), false);
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
  assert.equal(clearWarningBlockedReason(row, "Admin"),
    "There is no warning to clear");
});

test("a warned business still shows nothing to a non-admin", () => {
  const row = registryRow({ warningLevel: 2, flagColor: "Orange" });
  assert.equal(canClearWarning(row, "Inspector"), false);
  assert.equal(clearWarningBlockedReason(row, "Inspector"), "Admins only");
});

test("a locked Black business shows Unlock only to SUPER_ADMIN", () => {
  const row = registryRow({
    applicationStatus: "Revoked",
    flagColor: "Black",
    warningLevel: 3,
    blackLocked: 1,
  });
  assert.equal(canUnlockBlackDispatch(row, "SUPER_ADMIN"), true);
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
  assert.equal(clearWarningBlockedReason(row, "SUPER_ADMIN"),
    "This business is Black locked. Only a SUPER_ADMIN unlock applies.");
});

test("an unmigrated payload - all zeros - shows neither button", () => {
  // What the readers return when the columns do not exist.
  const row = registryRow({ warningLevel: 0, blackLocked: 0, blackDispatchUnlocked: 0 });
  assert.equal(canClearWarning(row, "SUPER_ADMIN"), false);
  assert.equal(canUnlockBlackDispatch(row, "SUPER_ADMIN"), false);
  assert.equal(canDispatchFlag({ ...row, color: "Black" }, { isAdmin: true }), false);
});

test("the Black dispatch rule reads the same payload", () => {
  const locked = { ...registryRow({ flagColor: "Black", blackLocked: 1 }), color: "Black" };
  const unlocked = { ...locked, blackDispatchUnlocked: 1 };
  assert.equal(canDispatchFlag(locked, { isAdmin: true }), false);
  assert.equal(canDispatchFlag(unlocked, { isAdmin: true }), true);
});
