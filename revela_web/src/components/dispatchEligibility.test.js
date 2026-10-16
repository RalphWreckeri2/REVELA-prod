import test from "node:test";
import assert from "node:assert/strict";
import {
  canDispatchFlag,
  dispatchButtonLabel,
  INSPECTABLE_FLAG_COLORS,
  NON_DISPATCHABLE_FLAG_COLORS,
  canReassignInspection,
  canFollowUpInspection,
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
    canDispatchFlag(flag("Black", { verificationStatus: "Verified" }), {
      isAdmin: true,
    }),
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
    assert.equal(
      canDispatchFlag(flag(color), { isAdmin: false }),
      false,
      color,
    );
  }
});

test("a flag under active inspection still shows the button, for re-dispatch", () => {
  assert.equal(
    canDispatchFlag(flag("Red", { hasActiveInspection: true }), {
      isAdmin: true,
    }),
    true,
  );
});

test("a verified flag can be re-dispatched", () => {
  assert.equal(
    canDispatchFlag(flag("Purple", { verificationStatus: "Verified" }), {
      isAdmin: true,
    }),
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
  assert.deepEqual([...INSPECTABLE_FLAG_COLORS].sort(), [
    "Orange",
    "Purple",
    "Red",
    "Yellow",
  ]);
});

test("Reassign is offered only for Assigned and Submitted reports to admins", () => {
  for (const verificationStatus of ["Assigned", "Submitted"]) {
    assert.equal(
      canReassignInspection({ verificationStatus }, { isAdmin: true }),
      true,
    );
  }
  for (const verificationStatus of ["Reassigned", "Verified"]) {
    assert.equal(
      canReassignInspection({ verificationStatus }, { isAdmin: true }),
      false,
    );
  }
  assert.equal(
    canReassignInspection(
      { verificationStatus: "Assigned" },
      { isAdmin: false },
    ),
    false,
  );
});

test("Follow-up is offered only for Verified Orange reports", () => {
  for (const noticeLevel of [0, 1, 2, 3, 4]) {
    assert.equal(
      canFollowUpInspection(
        {
          flagColor: "Orange",
          noticeLevel,
          inspectionResult: "Black",
          verificationStatus: "Verified",
        },
        { isAdmin: true },
      ),
      true,
    );
  }
  for (const flagColor of ["Red", "Yellow", "Green", "Purple", "Black"]) {
    assert.equal(
      canFollowUpInspection(
        { flagColor, verificationStatus: "Verified" },
        { isAdmin: true },
      ),
      false,
      flagColor,
    );
  }
});

test("Follow-up always hides Black, even if an old grant remains", () => {
  const report = {
    flagColor: "Black",
    verificationStatus: "Verified",
    inspectionResult: "Orange",
    noticeLevel: 1,
  };
  for (const blackDispatchUnlocked of [undefined, 0, "0", false]) {
    assert.equal(
      canFollowUpInspection(
        { ...report, blackDispatchUnlocked },
        { isAdmin: true },
      ),
      false,
    );
  }
  assert.equal(
    canFollowUpInspection(
      { ...report, blackDispatchUnlocked: 1 },
      { isAdmin: true },
    ),
    false,
  );
  assert.equal(
    canFollowUpInspection(
      { ...report, flagColor: "Orange", applicationStatus: "Revoked" },
      { isAdmin: true },
    ),
    false,
  );
});

test("Follow-up preserves the Green, non-admin and non-Verified blocks", () => {
  assert.equal(
    canFollowUpInspection(
      {
        flagColor: "Green",
        verificationStatus: "Verified",
        blackDispatchUnlocked: 1,
      },
      { isAdmin: true },
    ),
    false,
  );
  assert.equal(
    canFollowUpInspection(
      { flagColor: "Orange", verificationStatus: "Verified" },
      { isAdmin: false },
    ),
    false,
  );
  for (const verificationStatus of ["Assigned", "Reassigned", "Submitted"]) {
    assert.equal(
      canFollowUpInspection(
        { flagColor: "Orange", verificationStatus },
        { isAdmin: true },
      ),
      false,
    );
  }
});

test("Map API payload cannot dispatch Black even if it has an old grant", () => {
  const payload = {
    data: [
      {
        logID: 41,
        businessID: "B-1",
        flagColor: "Black",
        flagSource: "registry",
        verificationStatus: "Verified",
        blackDispatchUnlocked: 1,
      },
    ],
  };
  const apiFlag = payload.data[0];
  // normalizeFlag spreads the API record and adds its canonical color key.
  const normalized = {
    ...apiFlag,
    id: apiFlag.logID,
    color: apiFlag.flagColor,
  };
  assert.equal(canDispatchFlag(normalized, { isAdmin: true }), false);
  assert.equal(
    dispatchButtonLabel(normalized),
    "Black businesses cannot be dispatched",
  );
  assert.equal(
    canDispatchFlag(
      { ...normalized, blackDispatchUnlocked: 0 },
      { isAdmin: true },
    ),
    false,
  );
  assert.equal(canDispatchFlag(normalized, { isAdmin: false }), false);
});
