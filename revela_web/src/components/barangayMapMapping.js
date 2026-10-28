export const ADM4_EN_TO_BARANGAY_ID = Object.freeze({
  "District I (Pob.)": 1,
  "District II (Pob.)": 2,
  "Barangay II-A (Pob.)": 3,
  "District III (Pob.)": 4,
  "District IV (Pob.)": 5,
  Bayorbor: 6,
  Bubuyan: 7,
  Calingatan: 8,
  Kinalaglagan: 9,
  "Lumang Lipa": 10,
  Loob: 11,
  Manggahan: 12,
  Nangkaan: 13,
  "San Sebastian": 14,
  Santol: 15,
  Upa: 16,
});

export function getBarangayIdForGeoJsonName(name) {
  return ADM4_EN_TO_BARANGAY_ID[name] ?? null;
}

export function getShortBarangayLabel(name) {
  const labels = {
    "District I (Pob.)": "I",
    "District II (Pob.)": "II",
    "Barangay II-A (Pob.)": "II-A",
    "District III (Pob.)": "III",
    "District IV (Pob.)": "IV",
    "San Sebastian": "San Seb.",
    "Lumang Lipa": "Lumanglipa",
  };
  return labels[name] || String(name || "").replace(/^Barangay /, "Brgy. ");
}

function signedRingArea(ring) {
  return ring.reduce((area, point, index) => {
    const next = ring[(index + 1) % ring.length];
    return area + point[0] * next[1] - next[0] * point[1];
  }, 0) / 2;
}

function normalizePolygonRings(rings) {
  return rings.map((ring, index) => {
    const isExterior = index === 0;
    const isCounterClockwise = signedRingArea(ring) > 0;
    return isExterior === isCounterClockwise ? ring : [...ring].reverse();
  });
}

export function normalizeGeoJsonWinding(geoJson) {
  return {
    ...geoJson,
    features: (geoJson.features || []).map((feature) => {
      const { geometry } = feature;
      if (!geometry) return feature;
      const coordinates = geometry.type === "Polygon"
        ? normalizePolygonRings(geometry.coordinates)
        : geometry.type === "MultiPolygon"
          ? geometry.coordinates.map(normalizePolygonRings)
          : geometry.coordinates;
      return {
        ...feature,
        geometry: { ...geometry, coordinates },
      };
    }),
  };
}

function ringCentroid(ring) {
  let twiceArea = 0;
  let longitudeSum = 0;
  let latitudeSum = 0;
  ring.forEach((point, index) => {
    const next = ring[(index + 1) % ring.length];
    const cross = point[0] * next[1] - next[0] * point[1];
    twiceArea += cross;
    longitudeSum += (point[0] + next[0]) * cross;
    latitudeSum += (point[1] + next[1]) * cross;
  });
  if (!twiceArea) return { area: 0, longitude: 0, latitude: 0 };
  return {
    area: Math.abs(twiceArea / 2),
    longitude: longitudeSum / (3 * twiceArea),
    latitude: latitudeSum / (3 * twiceArea),
  };
}

function polygonCentroid(rings) {
  let weightedArea = 0;
  let longitude = 0;
  let latitude = 0;
  rings.forEach((ring, index) => {
    const centroid = ringCentroid(ring);
    const weight = centroid.area * (index === 0 ? 1 : -1);
    weightedArea += weight;
    longitude += centroid.longitude * weight;
    latitude += centroid.latitude * weight;
  });
  return weightedArea
    ? { area: weightedArea, longitude: longitude / weightedArea, latitude: latitude / weightedArea }
    : null;
}

export function getGeoJsonCentroid(feature) {
  const { type, coordinates } = feature?.geometry || {};
  const polygons = type === "Polygon"
    ? [coordinates]
    : type === "MultiPolygon"
      ? coordinates
      : [];
  let totalArea = 0;
  let longitude = 0;
  let latitude = 0;
  polygons.forEach((rings) => {
    const centroid = polygonCentroid(rings);
    if (!centroid) return;
    totalArea += centroid.area;
    longitude += centroid.longitude * centroid.area;
    latitude += centroid.latitude * centroid.area;
  });
  if (!totalArea) return null;
  return { lat: latitude / totalArea, lng: longitude / totalArea };
}
