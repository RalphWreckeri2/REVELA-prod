const MAP_COLORS = ["Green", "Orange", "Red", "Yellow", "Purple", "Black"];

export function hasMapCoordinates(flag) {
  if (flag?.hasExactCoords === false) return false;
  const latitude = Number(flag?.latitude);
  const longitude = Number(flag?.longitude);
  return Number.isFinite(latitude) && Number.isFinite(longitude) &&
    latitude !== 0 && longitude !== 0 &&
    latitude >= -90 && latitude <= 90 &&
    longitude >= -180 && longitude <= 180;
}

export function createCentroidPreviewFlags(flags, barangays, resolveCentroid, fallbackPosition) {
  return flags.flatMap((flag) => {
    if (hasMapCoordinates(flag)) return [];

    const barangayID = Number(flag.barangayID);
    if (!Number.isInteger(barangayID) || barangayID <= 0) return [];
    const barangay = barangays.find((item) => Number(item.barangayID) === barangayID);
    const barangayName = barangay?.barangayName || flag.barangayName || flag.barangay;
    if (!barangayName) return [];

    const position = resolveCentroid(barangayName);
    if (!position || position === fallbackPosition) return [];
    return [{ ...flag, isCentroidPreview: true, mapPreviewPosition: position }];
  });
}

function createScope() {
  return {
    matchingLocations: 0,
    withoutCoordinates: 0,
    outsideBoundaryLocations: 0,
    colors: Object.fromEntries(MAP_COLORS.map((color) => [color, 0])),
    registeredBusinessIDs: new Set(),
    activeBusinessIDs: new Set(),
    registeredBusinessIDsWithCoordinates: new Set(),
    activeBusinessIDsWithCoordinates: new Set(),
  };
}

function finishScope(scope, hasBoundaries) {
  return {
    matchingLocations: scope.matchingLocations,
    withoutCoordinates: scope.withoutCoordinates,
    outsideBoundaryLocations: hasBoundaries ? scope.outsideBoundaryLocations : null,
    colors: scope.colors,
    registeredBusinesses: scope.registeredBusinessIDs.size,
    activeBusinesses: scope.activeBusinessIDs.size,
    registeredBusinessesWithCoordinates: scope.registeredBusinessIDsWithCoordinates.size,
    activeBusinessesWithCoordinates: scope.activeBusinessIDsWithCoordinates.size,
  };
}

function pointInRing(latitude, longitude, ring) {
  let inside = false;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const [x1, y1] = ring[j];
    const [x2, y2] = ring[i];
    const cross = (longitude - x1) * (y2 - y1) - (latitude - y1) * (x2 - x1);
    if (Math.abs(cross) < 1e-10 &&
        longitude >= Math.min(x1, x2) - 1e-10 && longitude <= Math.max(x1, x2) + 1e-10 &&
        latitude >= Math.min(y1, y2) - 1e-10 && latitude <= Math.max(y1, y2) + 1e-10) {
      return true;
    }
    if ((y1 > latitude) !== (y2 > latitude) &&
        longitude < ((x2 - x1) * (latitude - y1)) / (y2 - y1) + x1) {
      inside = !inside;
    }
  }
  return inside;
}

function pointInPolygon(latitude, longitude, rings) {
  return pointInRing(latitude, longitude, rings[0]) &&
    !rings.slice(1).some((ring) => pointInRing(latitude, longitude, ring));
}

function featureContainsPoint(feature, latitude, longitude) {
  const { type, coordinates } = feature?.geometry || {};
  if (!Array.isArray(coordinates)) return false;
  if (type === "Polygon") return pointInPolygon(latitude, longitude, coordinates);
  if (type === "MultiPolygon") return coordinates.some((polygon) => pointInPolygon(latitude, longitude, polygon));
  return false;
}

export function aggregateMapLocationMetrics(flags, boundaryFeatures = null) {
  const overall = createScope();
  const barangays = new Map();
  let unassignedLocations = 0;
  let unassignedWithCoordinates = 0;
  const hasBoundaries = Array.isArray(boundaryFeatures) && boundaryFeatures.length > 0;

  for (const flag of flags) {
    const rawBarangayID = flag.barangayID;
    const barangayID = rawBarangayID == null || String(rawBarangayID).trim() === ""
      ? NaN
      : Number(rawBarangayID);
    const assigned = Number.isInteger(barangayID) && barangayID > 0;
    const scope = assigned
      ? barangays.get(barangayID) || createScope()
      : null;
    if (assigned) barangays.set(barangayID, scope);
    else unassignedLocations += 1;

    const color = MAP_COLORS.includes(flag.color) ? flag.color : null;
    const businessID = flag.businessID == null ? "" : String(flag.businessID).trim();
    const registered = flag.registryMatched === true || flag.registryMatched === 1 ||
      flag.registryLinked === true || flag.registryLinked === 1;
    if (registered && businessID) {
      overall.registeredBusinessIDs.add(businessID);
      if (scope) scope.registeredBusinessIDs.add(businessID);
      if (color === "Green") {
        overall.activeBusinessIDs.add(businessID);
        if (scope) scope.activeBusinessIDs.add(businessID);
      }
    }

    if (!hasMapCoordinates(flag)) {
      overall.withoutCoordinates += 1;
      if (scope) scope.withoutCoordinates += 1;
      continue;
    }

    overall.matchingLocations += 1;
    if (scope) scope.matchingLocations += 1;
    if (!assigned) unassignedWithCoordinates += 1;
    if (hasBoundaries && !boundaryFeatures.some((feature) => (
      featureContainsPoint(feature, Number(flag.latitude), Number(flag.longitude))
    ))) {
      overall.outsideBoundaryLocations += 1;
      if (scope) scope.outsideBoundaryLocations += 1;
    }

    if (color) {
      overall.colors[color] += 1;
      if (scope) scope.colors[color] += 1;
    }

    if (registered && businessID) {
      overall.registeredBusinessIDsWithCoordinates.add(businessID);
      if (scope) scope.registeredBusinessIDsWithCoordinates.add(businessID);
      if (color === "Green") {
        overall.activeBusinessIDsWithCoordinates.add(businessID);
        if (scope) scope.activeBusinessIDsWithCoordinates.add(businessID);
      }
    }
  }

  return {
    ...finishScope(overall, hasBoundaries),
    unassignedLocations,
    unassignedWithCoordinates,
    byBarangay: Object.fromEntries(
      [...barangays].map(([id, scope]) => [id, finishScope(scope, hasBoundaries)]),
    ),
  };
}
