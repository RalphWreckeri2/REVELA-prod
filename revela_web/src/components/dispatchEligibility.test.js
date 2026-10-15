import test from "node:test";
import assert from "node:assert/strict";
import {
  canDispatchFlag,
  dispatchButtonLabel,
  INSPECTABLE_FLAG_COLORS,
  NON_DISPATCHABLE_FLAG_COLORS,
} from "./dispatchEligibility.js";

const flag = (color, extra = {}) => ({ color, ...extra });

test("Red, Yellow, Orange and Purple are dispatchable", () => {
  for (const color of ["Red", "Yellow", "Orange", "Purple"]) {
    assert.equal(canDispatchFlag(flag(color), { isAdmin: true }), true, color);
  }
});

test("Purple is dispatchable - closed businesses can still be inspected", () => {
  assert.equal(canDispatchFlag(flag("Purple"), { isAdmin: true }), true);
});

test("Green is not dispatchable", () => {
  assert.equal(canDispatchFlag(flag("Green"), { isAdmin: true }), false);
});

test("Black is not dispatchable", () => {
  assert.equal(canDispatchFlag(flag("Black"), { isAdmin: true }), false);
});

test("Black stays blocked even after a verified inspection", () => {
  assert.equal(
    canDispatchFlag(flag("Black", { verificationStatus: "Verified" }),
      { isAdmin: true }),
    false,
  );
});

test("an unknown colour is not dispatchable", () => {
  assert.equal(canDispatchFlag(flag("Magenta"), { isAdmin: true }), false);
  assert.equal(canDispatchFlag(flag(undefined), { isAdmin: true }), false);
  assert.equal(canDispatchFlag(null, { isAdmin: true }), false);
});

test("non-admins can never dispatch", () => {
  for (const color of INSPECTABLE_FLAG_COLORS) {
    assert.equal(canDispatchFlag(flag(color), { isAdmin: false }), false, color);
  }
});

test("a flag under active inspection still shows the button, for re-dispatch", () => {
  assert.equal(
    canDispatchFlag(flag("Red", { hasActiveInspection: true }),
      { isAdmin: true }),
    true,
  );
});

test("a verified flag can be re-dispatched", () => {
  assert.equal(
    canDispatchFlag(flag("Purple", { verificationStatus: "Verified" }),
      { isAdmin: true }),
    true,
  );
});

test("the blocked colours and the allowed colours do not overlap", () => {
  for (const color of NON_DISPATCHABLE_FLAG_COLORS) {
    assert.equal(INSPECTABLE_FLAG_COLORS.includes(color), false, color);
  }
});

test("button label reflects the dispatch state", () => {
  assert.equal(dispatchButtonLabel(flag("Red")), "Dispatch inspector");
  assert.equal(
    dispatchButtonLabel(flag("Red", { hasActiveInspection: true })),
    "Undergoing Inspection",
  );
  assert.equal(
    dispatchButtonLabel(flag("Red", { verificationStatus: "Verified" })),
    "Re-dispatch inspector",
  );
});

test("the colour list is frozen so callers cannot mutate the rule", () => {
  assert.equal(Object.isFrozen(INSPECTABLE_FLAG_COLORS), true);
  assert.deepEqual([...INSPECTABLE_FLAG_COLORS].sort(),
    ["Orange", "Purple", "Red", "Yellow"]);
});