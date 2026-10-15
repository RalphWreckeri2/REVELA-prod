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
