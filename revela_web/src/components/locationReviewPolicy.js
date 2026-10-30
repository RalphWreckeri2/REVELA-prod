export const PREVIOUS_LOCATION = "previous";
export const IMPORTED_LOCATION = "imported";
export const SAME_PIN_TOLERANCE_METERS = 2;

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

function formatCoordinates(latitude, longitude) {
  return hasFiniteCoordinates(latitude, longitude)
    ? `${Number(latitude).toFixed(6)}, ${Number(longitude).toFixed(6)}`
    : "Coordinates unavailable";
}

export function pinMoveDistanceMeters(candidate) {
  const proposedLatitude = candidate?.candidateLatitude
    ?? candidate?.latitude;
  const proposedLongitude = candidate?.candidateLongitude
    ?? candidate?.longitude;
  if (!hasFiniteCoordinates(candidate?.originalLatitude, candidate?.originalLongitude)
    || !hasFiniteCoordinates(proposedLatitude, proposedLongitude)) {
    return null;
  }

  const radians = (degrees) => (Number(degrees) * Math.PI) / 180;
  const [lat1, lon1, lat2, lon2] = [
    candidate.originalLatitude,
    candidate.originalLongitude,
    proposedLatitude,
    proposedLongitude,
  ].map(radians);
  const latitudeDelta = lat2 - lat1;
  const longitudeDelta = lon2 - lon1;
  const haversine = Math.sin(latitudeDelta / 2) ** 2
    + Math.cos(lat1) * Math.cos(lat2)
    * Math.sin(longitudeDelta / 2) ** 2;
  return 2 * 6_371_000 * Math.asin(Math.sqrt(haversine));
}

export function isSamePinCandidate(candidate) {
  const distance = pinMoveDistanceMeters(candidate);
  return distance !== null && distance <= SAME_PIN_TOLERANCE_METERS;
}

export function formatPinMoveDistance(distanceMeters) {
  if (!Number.isFinite(distanceMeters)) return "Unavailable";
  if (distanceMeters < 1) return "<1 m";
  return `${Math.round(distanceMeters).toLocaleString()} m`;
}

export function reviewApprovalConfirmation(candidate) {
  const distance = pinMoveDistanceMeters(candidate);
  return [
    `Business: ${candidate?.businessName || "Unnamed business"}`,
    `Current pin: ${formatCoordinates(candidate?.originalLatitude, candidate?.originalLongitude)}`,
    `Proposed pin: ${formatCoordinates(
      candidate?.candidateLatitude ?? candidate?.latitude,
      candidate?.candidateLongitude ?? candidate?.longitude,
    )}`,
    `Distance: ${formatPinMoveDistance(distance)}`,
    `Match score: ${candidate?.matchScore == null
      ? "Unavailable"
      : Number(candidate.matchScore).toFixed(2)}`,
  ].join("\n");
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
