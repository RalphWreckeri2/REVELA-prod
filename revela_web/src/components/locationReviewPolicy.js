export const PREVIOUS_LOCATION = "previous";
export const IMPORTED_LOCATION = "imported";

function hasFiniteCoordinates(latitude, longitude) {
  return (
    latitude != null &&
    longitude != null &&
    latitude !== "" &&
    longitude !== "" &&
    Number.isFinite(Number(latitude)) &&
    Number.isFinite(Number(longitude))
  );
}

export function hasImportedLocationCandidate(candidate) {
  return Boolean(
    candidate?.candidateAvailable &&
    candidate.candidateHistoryID != null &&
    hasFiniteCoordinates(
      candidate.candidateLatitude,
      candidate.candidateLongitude,
    ),
  );
}

export function selectedLocationChoice(choices, candidate) {
  const choice = choices[candidate?.businessID] || PREVIOUS_LOCATION;
  return choice === IMPORTED_LOCATION &&
    !hasImportedLocationCandidate(candidate)
    ? PREVIOUS_LOCATION
    : choice;
}

export function selectLocationChoice(choices, candidate, choice) {
  if (choice === PREVIOUS_LOCATION) {
    return { ...choices, [candidate.businessID]: choice };
  }
  if (choice === IMPORTED_LOCATION && hasImportedLocationCandidate(candidate)) {
    return { ...choices, [candidate.businessID]: choice };
  }
  return choices;
}

export function canConfirmLocationChoice(candidate, choice) {
  if (!candidate?.locationReapproval) return true;
  if (choice === IMPORTED_LOCATION)
    return hasImportedLocationCandidate(candidate);
  return (
    choice === PREVIOUS_LOCATION &&
    hasFiniteCoordinates(
      candidate.originalLatitude,
      candidate.originalLongitude,
    )
  );
}

export function resetLocationChoices() {
  return {};
}

export async function confirmLocationChoice(
  candidate,
  choice,
  submitDecision,
  onSuccess,
) {
  if (!canConfirmLocationChoice(candidate, choice)) return false;
  await submitDecision({
    locationChoice: choice,
    candidateHistoryID:
      choice === IMPORTED_LOCATION ? candidate.candidateHistoryID : undefined,
  });
  onSuccess();
  return true;
}
