import pointData from "../../../revela_backend/api/utils/barangay_points.json" with { type: "json" };
import { ADM4_EN_TO_BARANGAY_ID } from "../components/barangayMapMapping.js";

const pointsById = new Map(
  pointData.barangays.map((row) => [Number(row.barangayID), row]),
);

export const BARANGAY_POINT_DATA = pointData;
export const DEFAULT_MAP_CENTER = pointData.municipalityCentroid;

const APPROXIMATE_POINT_GOLDEN_ANGLE = Math.PI * (3 - Math.sqrt(5));

const aliasesById = {
  1: ["district i", "district i (pob.)", "barangay i", "i"],
  2: ["district ii", "district ii (pob.)", "barangay ii", "ii"],
  3: ["barangay ii-a", "barangay ii-a (pob.)", "ii-a", "ii-a (pob.)"],
  4: ["district iii", "district iii (pob.)", "barangay iii", "iii"],
  5: ["district iv", "district iv (pob.)", "barangay iv", "iv"],
  10: ["lumanglipa"],
  14: ["san seb."],
};

function normalizeBarangayName(name) {
  return String(name || "")
    .toLowerCase()
    .replace(/^(barangay|brgy\.?)\s+/, "")
    .trim();
}

const pointsByName = new Map();
for (const [featureName, barangayID] of Object.entries(ADM4_EN_TO_BARANGAY_ID)) {
  const row = pointsById.get(Number(barangayID));
  if (!row) continue;
  pointsByName.set(normalizeBarangayName(featureName), row.representativePoint);
  for (const alias of aliasesById[barangayID] || []) {
    pointsByName.set(alias, row.representativePoint);
  }
}

export const BARANGAY_CENTROIDS = Object.freeze(
  Object.fromEntries(pointsByName),
);

export function getKnownBarangayCentroid(barangayName) {
  if (!barangayName) return null;
  return pointsByName.get(normalizeBarangayName(barangayName)) || null;
}

export function getBarangayCentroid(barangayName) {
  return getKnownBarangayCentroid(barangayName) || DEFAULT_MAP_CENTER;
}

export function getApproximateBarangayDisplayPoint(barangayID, index) {
  const row = pointsById.get(Number(barangayID));
  const pointIndex = Number(index);
  if (!row || !Number.isInteger(pointIndex) || pointIndex < 0) return null;

  const { lat, lng } = row.representativePoint;
  const clearance = Number(row.representativeClearanceM);
  if (!Number.isFinite(clearance) || clearance <= 0) return null;

  const maxRadiusMeters = Math.min(60, clearance * 0.8);
  const radiusMeters = maxRadiusMeters * Math.sqrt(
    (pointIndex + 1) / (pointIndex + 20),
  );
  const angle = pointIndex * APPROXIMATE_POINT_GOLDEN_ANGLE;
  const latitudeScale = 111_320;
  const longitudeScale = latitudeScale * Math.max(
    0.01,
    Math.cos((lat * Math.PI) / 180),
  );

  return {
    lat: lat + (Math.cos(angle) * radiusMeters) / latitudeScale,
    lng: lng + (Math.sin(angle) * radiusMeters) / longitudeScale,
  };
}
