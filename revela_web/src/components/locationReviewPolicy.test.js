import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import {
  IMPORTED_LOCATION,
  PREVIOUS_LOCATION,
  canConfirmLocationChoice,
  confirmLocationChoice,
  hasImportedLocationCandidate,
  isSamePinCandidate,
  pinMoveDistanceMeters,
  resetLocationChoices,
  reviewApprovalConfirmation,
  selectLocationChoice,
  selectedLocationChoice,
} from "./locationReviewPolicy.js";

const mapPageSource = readFileSync(
  new URL("../pages/MapPage.jsx", import.meta.url),
  "utf8",
);

function pendingCandidate(businessID, overrides = {}) {
  return {
    businessID,
    locationReapproval: true,
    originalLatitude: 13.96,
    originalLongitude: 121.11,
    candidateAvailable: true,
    candidateHistoryID: 52,
    candidateLatitude: 13.97,
    candidateLongitude: 121.12,
    ...overrides,
  };
}

test("previous location is selected by default", () => {
  const candidate = pendingCandidate("BIZ-1");
  assert.equal(selectedLocationChoice({}, candidate), PREVIOUS_LOCATION);
  assert.equal(canConfirmLocationChoice(candidate, PREVIOUS_LOCATION), true);
});

test("radio selection changes local state without submitting an approval", () => {
  const candidate = pendingCandidate("BIZ-1");
  const submit = () => assert.fail("selection must not submit");
  const choices = selectLocationChoice({}, candidate, IMPORTED_LOCATION);
  assert.equal(selectedLocationChoice(choices, candidate), IMPORTED_LOCATION);
  assert.equal(typeof submit, "function");
});

test("closing and reopening starts with a clean previous-location choice", () => {
  const candidate = pendingCandidate("BIZ-1");
  const beforeClose = selectLocationChoice({}, candidate, IMPORTED_LOCATION);
  const afterReopen = resetLocationChoices();
  assert.equal(
    selectedLocationChoice(beforeClose, candidate),
    IMPORTED_LOCATION,
  );
  assert.equal(
    selectedLocationChoice(afterReopen, candidate),
    PREVIOUS_LOCATION,
  );
});

test("a different business cannot inherit another business's selection", () => {
  const first = pendingCandidate("BIZ-1");
  const second = pendingCandidate("BIZ-2");
  const choices = selectLocationChoice({}, first, IMPORTED_LOCATION);
  assert.equal(selectedLocationChoice(choices, first), IMPORTED_LOCATION);
  assert.equal(selectedLocationChoice(choices, second), PREVIOUS_LOCATION);
});

test("an unavailable or stale imported candidate cannot be selected or confirmed", () => {
  const candidate = pendingCandidate("BIZ-1", {
    candidateAvailable: false,
    candidateHistoryID: null,
  });
  const choices = selectLocationChoice({}, candidate, IMPORTED_LOCATION);
  assert.equal(selectedLocationChoice(choices, candidate), PREVIOUS_LOCATION);
  assert.equal(hasImportedLocationCandidate(candidate), false);
  assert.equal(canConfirmLocationChoice(candidate, IMPORTED_LOCATION), false);
});

test("null candidate or retained coordinates cannot be confirmed", () => {
  const noCandidateCoordinates = pendingCandidate("BIZ-1", {
    candidateLatitude: null,
    candidateLongitude: null,
  });
  const noPreviousCoordinates = pendingCandidate("BIZ-2", {
    originalLatitude: null,
    originalLongitude: null,
  });
  assert.equal(hasImportedLocationCandidate(noCandidateCoordinates), false);
  assert.equal(
    canConfirmLocationChoice(noCandidateCoordinates, IMPORTED_LOCATION),
    false,
  );
  assert.equal(
    canConfirmLocationChoice(noPreviousCoordinates, PREVIOUS_LOCATION),
    false,
  );
});

test("valid imported candidate is sent only on explicit confirmation", async () => {
  const candidate = pendingCandidate("BIZ-1");
  const sent = [];
  let successes = 0;
  const choices = selectLocationChoice({}, candidate, IMPORTED_LOCATION);
  assert.equal(sent.length, 0);
  await confirmLocationChoice(
    candidate,
    selectedLocationChoice(choices, candidate),
    async (payload) => sent.push(payload),
    () => {
      successes += 1;
    },
  );
  assert.deepEqual(sent, [
    {
      locationChoice: IMPORTED_LOCATION,
      candidateHistoryID: 52,
    },
  ]);
  assert.equal(successes, 1);
});

test("previous pin confirmation sends the explicit previous choice", async () => {
  const candidate = pendingCandidate("BIZ-1");
  let payload;
  await confirmLocationChoice(
    candidate,
    PREVIOUS_LOCATION,
    async (value) => {
      payload = value;
    },
    () => {},
  );
  assert.deepEqual(payload, {
    locationChoice: PREVIOUS_LOCATION,
    candidateHistoryID: undefined,
  });
});

test("API failure does not run the success callback", async () => {
  const candidate = pendingCandidate("BIZ-1");
  let successes = 0;
  await assert.rejects(
    confirmLocationChoice(
      candidate,
      IMPORTED_LOCATION,
      async () => {
        throw new Error("request failed");
      },
      () => {
        successes += 1;
      },
    ),
    /request failed/,
  );
  assert.equal(successes, 0);
});

test("same-pin proposals cannot be approved as moves and show the no-move state", () => {
  const candidate = pendingCandidate("BIZ-SAME", {
    locationReapproval: false,
    originalLatitude: 13.947664,
    originalLongitude: 121.119366,
    candidateLatitude: 13.947664,
    candidateLongitude: 121.119366,
  });
  assert.equal(pinMoveDistanceMeters(candidate), 0);
  assert.equal(isSamePinCandidate(candidate), true);
});

test("approval confirmation includes the move distance, coordinates, business, and score", () => {
  const candidate = pendingCandidate("BIZ-MOVE", {
    businessName: "Example Shop",
    locationReapproval: false,
    originalLatitude: 13.947664,
    originalLongitude: 121.119366,
    candidateLatitude: 13.948664,
    candidateLongitude: 121.119366,
    matchScore: 0.55,
  });
  const confirmation = reviewApprovalConfirmation(candidate);
  assert.match(confirmation, /Business: Example Shop/);
  assert.match(confirmation, /Current pin: 13\.947664, 121\.119366/);
  assert.match(confirmation, /Proposed pin: 13\.948664, 121\.119366/);
  assert.match(confirmation, /Distance: \d+ m/);
  assert.match(confirmation, /Match score: 0\.55/);
});

test("review queue clears stale cards, keeps Retry, and guards same-pin approval", () => {
  assert.match(mapPageSource, /setReviewQueue\(null\);[\s\S]*getRegistryReviewQueueRequest/);
  assert.match(mapPageSource, /catch \(err\) \{[\s\S]*setReviewQueue\(null\);[\s\S]*Request ID:/);
  assert.match(mapPageSource, /Could not load pin suggestions\. Please try again\./);
  assert.match(mapPageSource, /onClick=\{\(\) => loadRegistryReviewQueue\(reviewQueuePage\)\}[\s\S]*Retry/);
  assert.match(mapPageSource, /disabled=\{[^}]*samePin[^}]*\}/);
  assert.match(mapPageSource, /Proposed location is the same as the current pin/);
  assert.match(mapPageSource, /Distance to move:/);
  assert.match(mapPageSource, /Low match score\. Check the Google place before approving\./);
  assert.match(mapPageSource, /Barangay \{String\(candidate\.barangayName/);
  assert.match(mapPageSource, /Address: \{candidate\.businessAddress/);
  assert.match(mapPageSource, /reviewApprovalConfirmation\(candidate\)/);
});
