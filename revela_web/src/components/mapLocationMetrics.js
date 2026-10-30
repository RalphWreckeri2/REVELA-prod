import { getBarangayIdForGeoJsonName } from "./barangayMapMapping.js";

const MAP_COLORS = ["Green", "Orange", "Red", "Yellow", "Purple", "Black"];

export const MAP_LOCATION_METRIC_DEFINITIONS = Object.freeze({
  matchingLocations: "Distinct map records with valid real coordinates after the active filters; approximate previews are excluded.",
  activeBusinesses: "Distinct official-registry business IDs represented by filtered map rows with effective Green status; grouped by the pin's recorded barangay, may include records without exact coordinates, and can differ from popup totals grouped by official registry barangay.",
  flagColorLocations: "Distinct map records with valid real coordinates and this effective flag color; approximate previews are excluded. Red includes expired registered businesses and unregistered detections.",
});

export function formatBarangayLocationMismatch(storedName, mapPositionName) {
  if (!mapPositionName) return "";
  return storedName
    ? `Recorded in ${storedName}; map position in ${mapPositionName}`
    : `No recorded barangay; map position in ${mapPositionName}`;
}

export function hasMapCoordinates(flag) {
  if (flag?.hasExactCoords === false) return false;
  const latitude = Number(flag?.latitude);
  const longitude = Number(flag?.longitude);
  return Number.isFinite(latitude) && Number.isFinite(longitude) &&
    latitude !== 0 && longitude !== 0 &&
    latitude >= -90 && latitude <= 90 &&
    longitude >= -180 && longitude <= 180;
}

function validBarangayID(value) {
  if (value == null || String(value).trim() === "") return null;
  const id = Number(value);
  return Number.isInteger(id) && id > 0 ? id : null;
}

function stableFlagKey(flag) {
  return String(flag.logID ?? flag.id ?? flag.businessID ?? "");
}

function compareStableFlags(left, right) {
  const leftKey = stableFlagKey(left);
  const rightKey = stableFlagKey(right);
  const leftNumber = Number(leftKey);
  const rightNumber = Number(rightKey);
  if (Number.isFinite(leftNumber) && Number.isFinite(rightNumber)) {
    return leftNumber - rightNumber;
  }
  return leftKey < rightKey ? -1 : leftKey > rightKey ? 1 : 0;
}

function isRegistryRecord(flag) {
  const isSet = (value) => value === true || value === 1 || value === "1";
  return isSet(flag.registryMatched) ||
    isSet(flag.registryLinked) ||
    String(flag.originSource || flag.flagSource || "").toLowerCase() === "registry";
}

export function createCentroidPreviewFlags(flags, resolveDisplayPoint) {
  const grouped = new Map();
  for (const flag of flags) {
    if (hasMapCoordinates(flag) || !isRegistryRecord(flag)) continue;
    const barangayID = validBarangayID(
      flag.recordedBarangayID ?? flag.barangayID,
    );
    if (!Number.isInteger(barangayID) || barangayID <= 0) continue;
    const group = grouped.get(barangayID) || [];
    group.push(flag);
    grouped.set(barangayID, group);
  }

  return [...grouped].flatMap(([barangayID, group]) => (
    group
      .sort(compareStableFlags)
      .flatMap((flag, index) => {
        const position = resolveDisplayPoint(barangayID, index);
        if (!position) return [];
        return [{
          ...flag,
          hasExactCoords: false,
          isCentroidPreview: true,
          mapPreviewPosition: position,
        }];
      })
  ));
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

export function featureContainsPoint(feature, latitude, longitude) {
  const { type, coordinates } = feature?.geometry || {};
  if (!Array.isArray(coordinates)) return false;
  if (type === "Polygon") return pointInPolygon(latitude, longitude, coordinates);
  if (type === "MultiPolygon") return coordinates.some((polygon) => pointInPolygon(latitude, longitude, polygon));
  return false;
}

export function getMapPositionBarangayIDs(flag, boundaryFeatures) {
  if (!hasMapCoordinates(flag) ||
      !Array.isArray(boundaryFeatures) ||
      boundaryFeatures.length === 0) {
    return [];
  }

  return [...new Set(boundaryFeatures.flatMap((feature) => {
    if (!featureContainsPoint(
      feature,
      Number(flag.latitude),
      Number(flag.longitude),
    )) {
      return [];
    }
    const id = getBarangayIdForGeoJsonName(feature?.properties?.ADM4_EN);
    return id == null ? [] : [id];
  }))];
}

export function matchesMapBarangayFilter(flag, selectedBarangayID, boundaryFeatures) {
  if (selectedBarangayID == null || selectedBarangayID === "" ||
      selectedBarangayID === "all") {
    return true;
  }
  const selectedID = validBarangayID(selectedBarangayID);
  if (selectedID == null) return false;

  const recordedID = validBarangayID(
    flag.recordedBarangayID ?? flag.barangayID,
  );
  return recordedID === selectedID ||
    getMapPositionBarangayIDs(flag, boundaryFeatures).includes(selectedID);
}

export function findStoredBarangayLocationMismatches(flags, boundaryFeatures) {
  if (!Array.isArray(boundaryFeatures) || boundaryFeatures.length === 0) return [];

  return flags.flatMap((flag) => {
    const polygonBarangayIDs = getMapPositionBarangayIDs(flag, boundaryFeatures);
    if (polygonBarangayIDs.length !== 1) return [];

    const polygonBarangayID = polygonBarangayIDs[0];
    const storedBarangayID = validBarangayID(
      flag.recordedBarangayID ?? flag.barangayID,
    );
    if (storedBarangayID === polygonBarangayID) return [];

    return [{
      flagId: flag.id ?? flag.logID,
      storedBarangayID,
      polygonBarangayID,
    }];
  });
}

export function aggregateMapLocationMetrics(flags, boundaryFeatures = null) {
  const overall = createScope();
  const barangays = new Map();
  const mapPositionBarangays = new Map();
  let unassignedLocations = 0;
  let unassignedWithCoordinates = 0;
  let ambiguousBoundaryLocations = 0;
  const hasBoundaries = Array.isArray(boundaryFeatures) && boundaryFeatures.length > 0;

  for (const flag of flags) {
    const recordedBarangayID = validBarangayID(
      flag.recordedBarangayID ?? flag.barangayID,
    );
    const recordedScope = recordedBarangayID != null
      ? barangays.get(recordedBarangayID) || createScope()
      : null;
    if (recordedBarangayID != null) {
      barangays.set(recordedBarangayID, recordedScope);
    }
    else unassignedLocations += 1;

    const color = MAP_COLORS.includes(flag.color) ? flag.color : null;
    const businessID = flag.businessID == null ? "" : String(flag.businessID).trim();
    const registered = flag.registryMatched === true || flag.registryMatched === 1 ||
      flag.registryLinked === true || flag.registryLinked === 1;
    if (registered && businessID) {
      overall.registeredBusinessIDs.add(businessID);
      if (recordedScope) recordedScope.registeredBusinessIDs.add(businessID);
      if (color === "Green") {
        overall.activeBusinessIDs.add(businessID);
        if (recordedScope) recordedScope.activeBusinessIDs.add(businessID);
      }
    }

    if (!hasMapCoordinates(flag)) {
      overall.withoutCoordinates += 1;
      if (recordedScope) recordedScope.withoutCoordinates += 1;
      continue;
    }

    const polygonBarangayIDs = hasBoundaries
      ? getMapPositionBarangayIDs(flag, boundaryFeatures)
      : [];
    if (polygonBarangayIDs.length === 0 && hasBoundaries) {
      overall.outsideBoundaryLocations += 1;
      if (recordedScope) recordedScope.outsideBoundaryLocations += 1;
    } else if (polygonBarangayIDs.length > 1) {
      ambiguousBoundaryLocations += 1;
    }
    const mapPositionBarangayID = polygonBarangayIDs.length === 1
      ? polygonBarangayIDs[0]
      : null;
    const mapPositionScope = mapPositionBarangayID == null
      ? null
      : mapPositionBarangays.get(mapPositionBarangayID) || createScope();
    if (mapPositionBarangayID != null) {
      mapPositionBarangays.set(mapPositionBarangayID, mapPositionScope);
    }

    overall.matchingLocations += 1;
    if (recordedScope) recordedScope.matchingLocations += 1;
    else unassignedWithCoordinates += 1;
    if (mapPositionScope) mapPositionScope.matchingLocations += 1;

    if (color) {
      overall.colors[color] += 1;
      if (recordedScope) recordedScope.colors[color] += 1;
      if (mapPositionScope) mapPositionScope.colors[color] += 1;
    }

    if (registered && businessID) {
      overall.registeredBusinessIDsWithCoordinates.add(businessID);
      if (recordedScope) recordedScope.registeredBusinessIDsWithCoordinates.add(businessID);
      if (mapPositionScope) {
        mapPositionScope.registeredBusinessIDs.add(businessID);
        mapPositionScope.registeredBusinessIDsWithCoordinates.add(businessID);
      }
      if (color === "Green") {
        overall.activeBusinessIDsWithCoordinates.add(businessID);
        if (recordedScope) recordedScope.activeBusinessIDsWithCoordinates.add(businessID);
        if (mapPositionScope) {
          mapPositionScope.activeBusinessIDs.add(businessID);
          mapPositionScope.activeBusinessIDsWithCoordinates.add(businessID);
        }
      }
    }
  }

  return {
    ...finishScope(overall, hasBoundaries),
    unassignedLocations,
    unassignedWithCoordinates,
    ambiguousBoundaryLocations: hasBoundaries ? ambiguousBoundaryLocations : null,
    byBarangay: Object.fromEntries(
      [...barangays].map(([id, scope]) => [id, finishScope(scope, hasBoundaries)]),
    ),
    byMapPositionBarangay: Object.fromEntries(
      [...mapPositionBarangays].map(([id, scope]) => [id, finishScope(scope, hasBoundaries)]),
    ),
  };
}
