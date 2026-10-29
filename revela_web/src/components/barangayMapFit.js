export const MIN_BARANGAY_MAP_ZOOM = 10;
export const BARANGAY_MAP_INTERACTION_EVENTS = Object.freeze([
  "dragstart",
  "center_changed",
  "zoom_changed",
]);

function visitCoordinates(coordinates, visit) {
  if (!Array.isArray(coordinates)) return;
  if (coordinates.length >= 2
    && Number.isFinite(Number(coordinates[0]))
    && Number.isFinite(Number(coordinates[1]))) {
    visit(Number(coordinates[0]), Number(coordinates[1]));
    return;
  }
  coordinates.forEach((coordinate) => visitCoordinates(coordinate, visit));
}

export function getGeoJsonFeaturesBounds(features = []) {
  const bounds = {
    south: Infinity,
    west: Infinity,
    north: -Infinity,
    east: -Infinity,
  };
  let hasCoordinates = false;

  features.forEach((feature) => {
    visitCoordinates(feature?.geometry?.coordinates, (longitude, latitude) => {
      hasCoordinates = true;
      bounds.south = Math.min(bounds.south, latitude);
      bounds.west = Math.min(bounds.west, longitude);
      bounds.north = Math.max(bounds.north, latitude);
      bounds.east = Math.max(bounds.east, longitude);
    });
  });

  return hasCoordinates ? bounds : null;
}

export function fitMapToGeoJsonFeatures(map, features, padding = 24) {
  const bounds = getGeoJsonFeaturesBounds(features);
  if (!map || !bounds) return null;

  map.fitBounds(
    {
      south: bounds.south,
      west: bounds.west,
      north: bounds.north,
      east: bounds.east,
    },
    { top: padding, right: padding, bottom: padding, left: padding },
  );
  return bounds;
}

export function shouldFitBarangayMap({ force = false, userInteracted = false } = {}) {
  return force || !userInteracted;
}
