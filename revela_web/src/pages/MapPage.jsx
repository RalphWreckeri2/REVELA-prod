/**
 * MapPage.jsx
 * Map & Flags â€” Google Maps with color-coded pin markers, click-to-open detail
 * modal, working zoom controls, fixed "See Full List" modal.
 */

import { useState, useEffect, useCallback, useRef, useContext, useMemo } from "react";
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell } from "recharts";
import AnimatePresence from "../components/AnimatePresence";
import { createPortal } from "react-dom";
import { useNavigate, useLocation } from "react-router-dom";
import { useLoadScript, GoogleMap, Data } from "@react-google-maps/api";
import { MarkerClusterer, SuperClusterAlgorithm } from "@googlemaps/markerclusterer";
import DashboardLayout from "../components/DashboardLayout";
import InspectorReportsModal from "../components/InspectorReportsModal";
import StatusBadge from "../components/StatusBadge";
import { AuthContext } from "../context/AuthContext";
import { useTheme } from "../context/ThemeContext";
import {
  API_ORIGIN,
  getFlagsRequest,
  escalateFlagToBlackRequest,
  runDetectionRequest,
  createYellowFlagRequest,
  getBarangaysRequest,
  assignInspectionRequest,
  getOpsRankingsRequest,
  getDiagnosticClustersRequest,
  updateFlagLocationRequest,
  deleteFlagRequest,
  updateFlagColorRequest,
  cancelRunDetection,
  getDetectionQuotaRequest,
} from "../services/api";
import Swal from "sweetalert2";

// â”€â”€ Icons â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
const Icon = {
  Layers: () => (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <polygon points="12 2 2 7 12 12 22 7 12 2" />
      <polyline points="2 17 12 22 22 17" />
      <polyline points="2 12 12 17 22 12" />
    </svg>
  ),
  Flag: () => (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <path d="M4 15s1-1 4-1 5 2 8 2 4-1 4-1V3s-1 1-4 1-5-2-8-2-4 1-4 1z" />
      <line x1="4" y1="22" x2="4" y2="15" />
    </svg>
  ),
  MapPin: () => (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <circle cx="12" cy="10" r="3" />
      <path d="M12 2C8.13 2 5 5.13 5 9c0 5.25 7 13 7 13s7-7.75 7-13c0-3.87-3.13-7-7-7z" />
    </svg>
  ),
  AlertTriangle: () => (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z" />
      <line x1="12" y1="9" x2="12" y2="13" />
      <line x1="12" y1="17" x2="12.01" y2="17" />
    </svg>
  ),
  Crosshair: () => (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <circle cx="12" cy="12" r="10" />
      <line x1="22" y1="12" x2="18" y2="12" />
      <line x1="6" y1="12" x2="2" y2="12" />
      <line x1="12" y1="6" x2="12" y2="2" />
      <line x1="12" y1="22" x2="12" y2="18" />
    </svg>
  ),
  Send: () => (
    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <line x1="22" y1="2" x2="11" y2="13" />
      <polygon points="22 2 15 22 11 13 2 9 22 2" />
    </svg>
  ),
  Search: () => (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <circle cx="11" cy="11" r="8" /><line x1="21" y1="21" x2="16.65" y2="16.65" />
    </svg>
  ),
  ZoomIn: () => (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <circle cx="11" cy="11" r="8" />
      <line x1="21" y1="21" x2="16.65" y2="16.65" />
      <line x1="11" y1="8" x2="11" y2="14" />
      <line x1="8" y1="11" x2="14" y2="11" />
    </svg>
  ),
  ZoomOut: () => (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <circle cx="11" cy="11" r="8" />
      <line x1="21" y1="21" x2="16.65" y2="16.65" />
      <line x1="8" y1="11" x2="14" y2="11" />
    </svg>
  ),
  X: () => (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <line x1="18" y1="6" x2="6" y2="18" />
      <line x1="6" y1="6" x2="18" y2="18" />
    </svg>
  ),
  ExternalLink: () => (
    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6" />
      <polyline points="15 3 21 3 21 9" />
      <line x1="10" y1="14" x2="21" y2="3" />
    </svg>
  ),
  Radar: () => (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <circle cx="12" cy="12" r="2" />
      <path d="M12 2a10 10 0 0 1 10 10" />
      <path d="M12 6a6 6 0 0 1 6 6" />
    </svg>
  ),
  Check: () => (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <polyline points="20 6 9 17 4 12" />
    </svg>
  ),
  Trash: () => (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <polyline points="3 6 5 6 21 6" />
      <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
    </svg>
  ),
  FileText: () => (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
      <polyline points="14 2 14 8 20 8" />
      <line x1="16" y1="13" x2="8" y2="13" />
      <line x1="16" y1="17" x2="8" y2="17" />
      <polyline points="10 9 9 9 8 9" />
    </svg>
  ),
  Calendar: () => (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <rect x="3" y="4" width="18" height="18" rx="2" ry="2" />
      <line x1="16" y1="2" x2="16" y2="6" />
      <line x1="8" y1="2" x2="8" y2="6" />
      <line x1="3" y1="10" x2="21" y2="10" />
    </svg>
  ),
  Maximize: () => (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <path d="M8 3H5a2 2 0 0 0-2 2v3m18 0V5a2 2 0 0 0-2-2h-3m0 18h3a2 2 0 0 0 2-2v-3M3 16v3a2 2 0 0 0 2 2h3" />
    </svg>
  ),
};

// â”€â”€ Constants â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
const DEFAULT_MAP_CENTER = { lat: 13.9667, lng: 121.1167 };
const MAP_LIBRARIES = ["places", "marker"];

// `public/data/mataasnakahoy.json` is a single outer boundary for the whole
// municipality. Feature names must be listed here so the heatmap sums all
// per-barangay Red Flag counts instead of matching barangay names to "Mataasnakahoy".
const MUNICIPAL_BOUNDARY_NAMES = new Set(["mataasnakahoy", "mataas na kahoy"]);
// const MAP_OPTIONS        = {
//  disableDefaultUI: true,
//  clickableIcons:   false,
//  zoomControl:      false,
//  mapTypeId:        isSatellite ? "satellite" : "roadmap",
//  mapId:            isSatellite ? undefined : "34390388b3abb63aa84876a7",
//};

const LAYER_OPTIONS = [
  { id: "base", label: "Base Map" },
  { id: "flags", label: "Flag Markers" },
  { id: "barangay", label: "Barangay Boundaries" },
  { id: "diagnostics", label: "Risk Heatmap" },
];

// Flag color â†’ UI color mapping
const FLAG_COLORS = {
  Red: { marker: "#ef4444", bg: "var(--flag-red-bg)", text: "var(--flag-red-text)", label: "Detected Unregistered" },
  Yellow: { marker: "#f59e0b", bg: "var(--flag-yellow-bg)", text: "var(--flag-yellow-text)", label: "Suspected Unregistered" },
  Yellow_Inspector: { marker: "#f59e0b", bg: "var(--flag-yellow-bg)", text: "var(--flag-yellow-text)", label: "Suspected Unregistered from Inspectors" },
  Orange: { marker: "#e65100", bg: "var(--flag-orange-bg)", text: "var(--flag-orange-text)", label: "1st/2nd Warning / 3rd Notice Closure" },
  Black: { marker: "#000000", bg: "var(--flag-black-bg)", text: "var(--flag-black-text)", label: "Blacklisted / Non-Responsive" },
  Purple: { marker: "#7c3aed", bg: "var(--flag-purple-bg)", text: "var(--flag-purple-text)", label: "Closed / Abandoned" },
  Green: { marker: "#22c55e", bg: "var(--flag-green-bg)", text: "var(--flag-green-text)", label: "Active Business" },
  in_inspection: { marker: "#0284c7", bg: "rgba(2, 132, 199, 0.12)", text: "#0284c7", label: "Currently Being Inspected / Dispatched" },
};

const defaultColor = { marker: "var(--color-muted)", bg: "var(--flag-default-bg)", text: "var(--flag-default-text)", label: "Unknown" };

/** Discrete barangay risk fills (HRI-style). Keys align with analytics `risk_level` + edge cases. */
const HEATMAP_RISK_STYLE = {
  High: {
    fillColor: "#D32F2F",
    fillOpacity: 0.72,
    strokeColor: "#212121",
    strokeWeight: 1,
    zIndex: 4,
  },
  Medium: {
    fillColor: "#FFB74D",
    fillOpacity: 0.72,
    strokeColor: "#212121",
    strokeWeight: 1,
    zIndex: 3,
  },
  Low: {
    fillColor: "#A5D6A7",
    fillOpacity: 0.72,
    strokeColor: "#212121",
    strokeWeight: 1,
    zIndex: 2,
  },
  /** Red flags present but barangay not in prescriptive rankings yet */
  unranked: {
    fillColor: "#FFF9C4",
    fillOpacity: 0.72,
    strokeColor: "#616161",
    strokeWeight: 1,
    zIndex: 2,
  },
  /** No red flags (or no data) â€” â€œvery lowâ€  style */
  none: {
    fillColor: "#BBDEFB",
    fillOpacity: 0.72,
    strokeColor: "#546E7A",
    strokeWeight: 1,
    zIndex: 1,
  },
};

function heatmapTierKey(riskLevel, redFlagCount) {
  if (riskLevel === "High") return "High";
  if (riskLevel === "Medium") return "Medium";
  if (riskLevel === "Low") return "Low";
  if (redFlagCount > 0) return "unranked";
  return "none";
}

function getFlagColor(flagColor) {
  return FLAG_COLORS[flagColor] ?? defaultColor;
}

/** Higher = more severe â€” used so mixed clusters show the worst color, not green. */
const FLAG_SEVERITY_RANK = { Green: 1, Purple: 2, Orange: 3, Yellow: 4, Red: 5, Black: 6 };

function flagSeverityRank(flagColor) {
  return FLAG_SEVERITY_RANK[flagColor] ?? 0;
}

/** Dominant flag color among clustered markers (see `_revelaFlagColor` on each marker). */
function getDominantFlagColorFromMarkers(markers) {
  let dominant = "Green";
  let best = 0;
  for (const m of markers) {
    const raw = m?._revelaFlagColor;
    if (raw == null || raw === "") continue;
    const c = canonicalFlagColor(raw);
    const r = flagSeverityRank(c);
    if (r > best) {
      best = r;
      dominant = c;
    }
  }
  return dominant;
}

/** Map API `flagColor` to a canonical key in FLAG_COLORS (handles casing / unknown). */
function canonicalFlagColor(raw) {
  if (raw == null || raw === "") return "Red";
  const s = String(raw).trim();
  const cap = s.length ? s.charAt(0).toUpperCase() + s.slice(1).toLowerCase() : "Red";
  return FLAG_COLORS[cap] ? cap : "Red";
}

// Barangay centroid coordinates used as fallback for establishments without exact GPS
export const BARANGAY_CENTROIDS = {
  "barangay ii-a": { lat: 13.952260, lng: 121.115799 },
  "barangay ii-a (pob.)": { lat: 13.952260, lng: 121.115799 },
  "bayorbor": { lat: 13.979234, lng: 121.095818 },
  "bubuyan": { lat: 13.983266, lng: 121.108556 },
  "calingatan": { lat: 13.962879, lng: 121.121234 },
  "district i": { lat: 13.955117, lng: 121.110199 },
  "district i (pob.)": { lat: 13.955117, lng: 121.110199 },
  "barangay i": { lat: 13.955117, lng: 121.110199 },
  "district ii": { lat: 13.960630, lng: 121.113447 },
  "district ii (pob.)": { lat: 13.960630, lng: 121.113447 },
  "barangay ii": { lat: 13.960630, lng: 121.113447 },
  "district iii": { lat: 13.961458, lng: 121.109487 },
  "district iii (pob.)": { lat: 13.961458, lng: 121.109487 },
  "barangay iii": { lat: 13.961458, lng: 121.109487 },
  "district iv": { lat: 13.956173, lng: 121.117793 },
  "district iv (pob.)": { lat: 13.956173, lng: 121.117793 },
  "barangay iv": { lat: 13.956173, lng: 121.117793 },
  "kinalaglagan": { lat: 14.005574, lng: 121.094954 },
  "loob": { lat: 13.980785, lng: 121.114404 },
  "lumang lipa": { lat: 13.974504, lng: 121.087937 },
  "manggahan": { lat: 13.967686, lng: 121.088860 },
  "nangkaan": { lat: 13.990223, lng: 121.089892 },
  "san sebastian": { lat: 13.984496, lng: 121.103597 },
  "san seb.": { lat: 13.984496, lng: 121.103597 },
  "santol": { lat: 13.972238, lng: 121.104850 },
  "upa": { lat: 13.968345, lng: 121.111783 },
};

export function getBarangayCentroid(barangayName) {
  if (!barangayName) return DEFAULT_MAP_CENTER;
  const raw = String(barangayName).toLowerCase().replace("barangay ", "").replace("brgy. ", "").trim();
  if (BARANGAY_CENTROIDS[raw]) return BARANGAY_CENTROIDS[raw];
  for (const key in BARANGAY_CENTROIDS) {
    if (raw.includes(key) || key.includes(raw)) {
      return BARANGAY_CENTROIDS[key];
    }
  }
  return DEFAULT_MAP_CENTER;
}

// ── Point-in-polygon helpers (ray-casting) ────────────────────────────────────
// GeoJSON coords are [lng, lat]; we receive (lat, lng) from Google Maps.
function pointInRing(lat, lng, ring) {
  let inside = false;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const [xi, yi] = ring[i]; // xi=lng, yi=lat
    const [xj, yj] = ring[j];
    const intersect =
      (yi > lat) !== (yj > lat) &&
      lng < ((xj - xi) * (lat - yi)) / (yj - yi) + xi;
    if (intersect) inside = !inside;
  }
  return inside;
}

function distToSegmentSq(px, py, ax, ay, bx, by) {
  const l2 = (bx - ax) * (bx - ax) + (by - ay) * (by - ay);
  if (l2 === 0) return (px - ax) * (px - ax) + (py - ay) * (py - ay);
  let t = ((px - ax) * (bx - ax) + (py - ay) * (by - ay)) / l2;
  t = Math.max(0, Math.min(1, t));
  const projX = ax + t * (bx - ax);
  const projY = ay + t * (by - ay);
  return (px - projX) * (px - projX) + (py - projY) * (py - projY);
}

function distanceToRingInMeters(lat, lng, ring) {
  if (!ring || ring.length === 0) return Infinity;
  let minSq = Infinity;
  const latToMeters = 110540.0;
  const lngToMeters = 111320.0 * Math.cos((lat * Math.PI) / 180.0);
  const px = lng * lngToMeters;
  const py = lat * latToMeters;

  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const ax = ring[j][0] * lngToMeters;
    const ay = ring[j][1] * latToMeters;
    const bx = ring[i][0] * lngToMeters;
    const by = ring[i][1] * latToMeters;
    const dSq = distToSegmentSq(px, py, ax, ay, bx, by);
    if (dSq < minSq) minSq = dSq;
  }
  return Math.sqrt(minSq);
}

/** Returns true if (lat, lng) is inside a GeoJSON Polygon or MultiPolygon geometry or within bufferMeters distance. */
function pointInGeoJsonGeometry(lat, lng, geometry, bufferMeters = 100) {
  if (!geometry) return false;
  const polys =
    geometry.type === "MultiPolygon"
      ? geometry.coordinates          // [ [ [ring], ...], ... ]
      : geometry.type === "Polygon"
        ? [geometry.coordinates]      // [ [ [ring], ... ] ]
        : [];

  for (const poly of polys) {
    // poly[0] = outer ring; poly[1..] = holes
    if (poly.length === 0) continue;
    if (pointInRing(lat, lng, poly[0])) {
      // Check holes — if inside a hole the point is outside the polygon
      let inHole = false;
      for (let h = 1; h < poly.length; h++) {
        if (pointInRing(lat, lng, poly[h])) { inHole = true; break; }
      }
      if (!inHole) return true;
    } else if (distanceToRingInMeters(lat, lng, poly[0]) <= bufferMeters) {
      return true;
    }
  }
  return false;
}

/**
 * Explicit GeoJSON ADM4_EN → DB barangayName mapping.
 * Mirrors the same table in revela_backend/api/flags/service.py.
 * Keys are lowercased ADM4_EN values from mataasnakahoy.json.
 */
const GEOJSON_TO_DB_BRGY = {
  "district i (pob.)":     "Barangay I",
  "district ii (pob.)":    "Barangay II",
  "barangay ii-a (pob.)":  "Barangay II-A",
  "district iii (pob.)":   "Barangay III",
  "district iv (pob.)":    "Barangay IV",
  "lumang lipa":           "Barangay Lumanglipa",
  // Straight matches (GeoJSON name == DB name after "Barangay " prefix)
  "bayorbor":     "Barangay Bayorbor",
  "bubuyan":      "Barangay Bubuyan",
  "calingatan":   "Barangay Calingatan",
  "loob":         "Barangay Loob",
  "kinalaglagan": "Barangay Kinalaglagan",
  "manggahan":    "Barangay Manggahan",
  "nangkaan":     "Barangay Nangkaan",
  "san sebastian":"Barangay San Sebastian",
  "santol":       "Barangay Santol",
  "upa":          "Barangay Upa",
};

/**
 * Given a raw GeoJSON ADM4_EN string, return the DB barangayName it maps to,
 * or null if unknown.
 */
function resolveGeoJsonToDbName(geoAdm4En) {
  const key = String(geoAdm4En).toLowerCase().trim();
  return GEOJSON_TO_DB_BRGY[key] ?? null;
}

/**
 * Normalize a barangay name for fuzzy fallback matching.
 * Only strips (Pob.) and normalises whitespace.
 */
function normalizeBrgyName(name) {
  return String(name).toLowerCase()
    .replace(/\(pob\.\)/gi, "")
    .replace(/brgy\.?\s*/gi, "barangay ")
    .replace(/\s+/g, " ")
    .trim();
}

/**
 * Find the DB barangay entry that corresponds to a GeoJSON ADM4_EN value.
 * Uses the explicit lookup table first, then falls back to normalized comparison.
 */
function matchBrgyFromGeoName(geoAdm4En, barangays) {
  const resolved = resolveGeoJsonToDbName(geoAdm4En);
  if (resolved) {
    const exact = barangays.find(b => b.barangayName === resolved);
    if (exact) return exact;
  }
  // Fallback: normalized comparison without substring matching
  const geoNorm = normalizeBrgyName(geoAdm4En);
  const geoStripped = geoNorm.replace(/^barangay\s+/, "");
  return barangays.find(b => {
    const dbNorm = normalizeBrgyName(b.barangayName);
    const dbStripped = dbNorm.replace(/^barangay\s+/, "");
    return dbNorm === geoNorm || dbStripped === geoStripped;
  }) ?? null;
}

// ── Normalise flag from API → UI shape ────────────────────────────────────────
function normalizeFlag(flag) {
  const color = canonicalFlagColor(flag.flagColor);
  const rawLat = flag.latitude != null ? Number(flag.latitude) : null;
  const rawLng = flag.longitude != null ? Number(flag.longitude) : null;
  const hasExactCoords = rawLat != null && rawLng != null && !isNaN(rawLat) && !isNaN(rawLng) && rawLat !== 0 && rawLng !== 0;

  const centroid = !hasExactCoords ? getBarangayCentroid(flag.barangayName || flag.barangay) : null;
  const lat = hasExactCoords ? rawLat : (centroid?.lat ?? DEFAULT_MAP_CENTER.lat);
  const lng = hasExactCoords ? rawLng : (centroid?.lng ?? DEFAULT_MAP_CENTER.lng);

  const coords = `${Number(lat).toFixed(6)}°N, ${Number(lng).toFixed(6)}°E`;

  const hasActiveInspection = (flag.verificationStatus != null && flag.verificationStatus !== 'Verified') ||
    flag.hasActiveInspection === true;

  return {
    ...flag,
    id: flag.logID ?? flag.id,
    name: flag.detectedName ?? "Unknown Establishment",
    barangay: flag.barangayName ?? "Unknown Barangay",
    address: flag.resolvedAddress ?? flag.nearestLandmark ?? "",
    notes: flag.notes || "",
    source: flag.flagSource ?? "registry_only",
    size: flag.businessSize ?? "—",
    coords,
    latitude: lat,
    longitude: lng,
    hasExactCoords,
    color,
    verificationStatus: flag.verificationStatus,
    hasActiveInspection
  };
}

// â”€â”€ Flag Detail Modal â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
function FlagDetailModal({ flag, onClose, onEscalate, onDispatch, onAdjustLocation, onDelete, onUpdateColor, isAdmin, actionLoading, isClosing }) {
  const [showMoreActions, setShowMoreActions] = useState(false);
  const fc = getFlagColor(flag.color);

  const canShowDispatchButton = (() => {
    if (!isAdmin) return false;
    if (flag.color === "Black") return false;
    if (flag.hasActiveInspection) {
      return true;
    }
    if (flag.verificationStatus === 'Verified') {
      return true;
    }
    return flag.color === "Red" || flag.color === "Yellow" || flag.color === "Orange";
  })();

  const dispatchButtonLabel = (() => {
    if (flag.hasActiveInspection) {
      return "Undergoing Inspection";
    }
    if (flag.verificationStatus === 'Verified') {
      return "Re-dispatch inspector";
    }
    return "Dispatch inspector";
  })();


  // Source labels
  const sourceLabel = flag.source === "registry_and_maps"
    ? "Registry & Google Maps"
    : flag.source === "maps_only"
      ? "Google Maps only"
      : flag.source === "inspector_reported"
        ? "Inspector Field Report"
        : "Official BPLO Registry";

  const isInspectorReported = flag.source === "inspector_reported";
  const mapsUrl = flag.latitude
    ? `https://www.google.com/maps/search/?api=1&query=${flag.latitude},${flag.longitude}${flag.placeID ? `&query_place_id=${flag.placeID}` : ''}`
    : null;

  return createPortal(
    <div className={"modal-backdrop" + (isClosing ? " closing" : "")} style={styles.modalBackdrop} onClick={onClose}>
      <div
        className={"modal-panel" + (isClosing ? " closing" : "")}
        style={{
          ...styles.detailModal,
          width: "min(100%, 420px)",
          borderRadius: 16,
          background: "var(--color-modal-bg)",
          boxShadow: "0 20px 50px rgba(0, 0, 0, 0.4)",
          border: "1px solid var(--color-border)",
          padding: 24,
          display: "flex",
          flexDirection: "column",
          gap: 20
        }}
        onClick={e => e.stopPropagation()}
      >
        {/* Header Section */}
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
          <div style={{ flex: 1, paddingRight: 16 }}>
            <h2 style={{ fontSize: 24, color: "var(--color-ink)", fontWeight: 800, margin: "0 0 12px 0", lineHeight: 1.2 }}>
              {flag.name}
            </h2>
            <div style={{ display: "inline-flex", alignItems: "center", gap: 6, padding: "4px 10px", borderRadius: 8, background: fc.bg, border: `1px solid ${fc.marker}33`, fontSize: 12, fontWeight: 600, color: fc.marker }}>
              {fc.label}
            </div>
            {isInspectorReported && (
              <div style={{ display: "inline-flex", alignItems: "center", gap: 6, padding: "4px 10px", borderRadius: 8, background: "rgba(234, 88, 12, 0.15)", border: "1px solid rgba(234, 88, 12, 0.1)", fontSize: 12, fontWeight: 600, color: "#ea580c", marginTop: 8 }}>
                Inspector reported
              </div>
            )}
          </div>
          <button
            style={{ width: 32, height: 32, borderRadius: "50%", border: "none", background: "transparent", display: "flex", alignItems: "center", justifyContent: "center", cursor: "pointer", color: "var(--color-muted)", flexShrink: 0 }}
            onClick={onClose}
          >
            <Icon.X size={18} />
          </button>
        </div>

        {/* Metadata Card */}
        <div style={{ background: "var(--color-surface)", borderRadius: 12, padding: "16px", display: "flex", flexDirection: "column", gap: 12, border: "1px solid var(--color-border-soft)" }}>
          <div style={{ display: "flex", alignItems: "flex-start", gap: 12, color: "var(--color-ink)", fontSize: 14, fontWeight: 500 }}>
            <div style={{ color: "var(--color-muted)", marginTop: 2 }}><Icon.MapPin size={16} /></div>
            <div style={{ lineHeight: 1.4 }}>
              <span style={{ fontWeight: 600 }}>{flag.barangay || "Mataasnakahoy"}</span>
              {flag.size && flag.size !== "—" && flag.size !== "â€”" && <span style={{ color: "var(--color-muted)" }}> &bull; {flag.size} Size</span>}
            </div>
          </div>
          {flag.address && (
            <div style={{ display: "flex", alignItems: "flex-start", gap: 12, color: "var(--color-ink)", fontSize: 14, fontWeight: 500 }}>
              <div style={{ color: "var(--color-muted)", marginTop: 2 }}><Icon.Search size={16} /></div>
              <div style={{ lineHeight: 1.4 }}>{flag.address}</div>
            </div>
          )}
          {flag.notes && (
            <div style={{ display: "flex", alignItems: "flex-start", gap: 12, color: "var(--color-ink)", fontSize: 14, fontWeight: 500 }}>
              <div style={{ color: "var(--color-muted)", marginTop: 2 }}><Icon.FileText size={16} /></div>
              <div style={{ lineHeight: 1.4 }}>{flag.notes}</div>
            </div>
          )}
          <div style={{ display: "flex", alignItems: "center", gap: 12, color: "var(--color-ink)", fontSize: 14, fontWeight: 500 }}>
            <div style={{ color: "var(--color-muted)" }}><Icon.Calendar size={16} /></div>
            <div>{sourceLabel} <span style={{ color: "var(--color-muted)" }}>&bull; {flag.detectedDate ? flag.detectedDate.slice(0, 10) : "—"}</span></div>
          </div>
        </div>

        {canShowDispatchButton && (
          <button
            style={{
              width: "100%",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              gap: 8,
              height: 48,
              borderRadius: 10,
              fontWeight: 600,
              fontSize: 15,
              cursor: flag.hasActiveInspection ? "not-allowed" : "pointer",
              background: flag.hasActiveInspection ? "var(--color-border)" : "#16a34a",
              color: flag.hasActiveInspection ? "var(--color-muted)" : "#ffffff",
              border: "none",
              transition: "all 0.2s"
            }}
            disabled={actionLoading || flag.hasActiveInspection}
            onClick={() => onDispatch(flag)}
          >
            <Icon.Send size={18} /> {dispatchButtonLabel}
          </button>
        )}

        {/* Secondary Actions */}
        <div style={{ display: "flex", gap: 12 }}>
          {isAdmin && flag.color !== "Purple" && flag.color !== "Black" && (
            <button
              style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center", height: 44, borderRadius: 10, fontWeight: 600, fontSize: 14, cursor: "pointer", border: "1px solid var(--color-border)", background: "var(--color-surface)", color: "var(--color-ink)", transition: "all 0.2s" }}
              disabled={actionLoading}
              onClick={() => onUpdateColor(flag.id, "Purple")}
            >
              Mark as closed
            </button>
          )}
          {isAdmin && flag.color === "Purple" && (
            <button
              style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center", height: 44, borderRadius: 10, fontWeight: 600, fontSize: 14, cursor: "pointer", border: "1px solid var(--color-border)", background: "var(--color-surface)", color: "var(--color-ink)", transition: "all 0.2s" }}
              disabled={actionLoading}
              onClick={() => onUpdateColor(flag.id, "Green")}
            >
              Mark as active
            </button>
          )}
          {mapsUrl && (
            <a
              href={mapsUrl}
              target="_blank"
              rel="noreferrer"
              style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center", gap: 6, height: 44, borderRadius: 10, border: flag.color === "Black" ? "1px solid var(--color-border)" : "none", background: flag.color === "Black" ? "var(--color-surface)" : "transparent", color: "#3b82f6", fontSize: 14, fontWeight: 600, textDecoration: "none", cursor: "pointer", transition: "all 0.15s" }}
            >
              <Icon.ExternalLink size={16} /> Open in maps
            </a>
          )}
          {isAdmin && flag.color === "Black" && (
            <button
              style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center", gap: 6, height: 44, borderRadius: 10, border: "none", background: "rgba(239, 68, 68, 0.1)", color: "#ef4444", fontSize: 14, fontWeight: 600, cursor: "pointer", transition: "all 0.15s" }}
              disabled={actionLoading}
              onClick={() => onDelete(flag.id)}
            >
              <Icon.Trash size={16} /> Delete Flag
            </button>
          )}
        </div>

        {/* More Actions Toggle */}
        {flag.color !== "Black" && (
          <div style={{ borderTop: "1px solid var(--color-border-soft)", paddingTop: 16, marginTop: 4 }}>
            <button
              style={{ display: "flex", alignItems: "center", gap: 8, background: "none", border: "none", color: "var(--color-muted)", fontSize: 14, fontWeight: 600, cursor: "pointer", padding: 0 }}
              onClick={() => setShowMoreActions(!showMoreActions)}
            >
              <div style={{ display: "flex", gap: 2 }}>
                <span style={{ width: 3, height: 3, borderRadius: "50%", background: "currentColor" }} />
                <span style={{ width: 3, height: 3, borderRadius: "50%", background: "currentColor" }} />
                <span style={{ width: 3, height: 3, borderRadius: "50%", background: "currentColor" }} />
              </div>
              {showMoreActions ? "Less actions" : "More actions"}
            </button>

            {showMoreActions && (
              <div style={{ display: "flex", flexDirection: "column", gap: 8, marginTop: 16 }}>
                {isAdmin && (flag.color === "Red" || flag.color === "Yellow" || flag.color === "Orange") && (
                  <button
                    style={{ display: "flex", alignItems: "center", gap: 12, width: "100%", height: 44, borderRadius: 8, border: "none", background: "rgba(239, 68, 68, 0.1)", color: "#ef4444", fontSize: 14, fontWeight: 600, padding: "0 16px", cursor: "pointer", transition: "all 0.15s" }}
                    disabled={actionLoading}
                    onClick={() => onEscalate(flag.id)}
                  >
                    <Icon.AlertTriangle size={16} /> Escalate to Black
                  </button>
                )}
                {isAdmin && (
                  <button
                    style={{ display: "flex", alignItems: "center", gap: 12, width: "100%", height: 44, borderRadius: 8, border: "1px solid var(--color-border)", background: "transparent", color: "var(--color-ink)", fontSize: 14, fontWeight: 500, padding: "0 16px", cursor: "pointer", transition: "all 0.15s" }}
                    disabled={actionLoading}
                    onClick={() => onAdjustLocation(flag)}
                  >
                    <Icon.Crosshair size={16} /> Adjust Pin Location
                  </button>
                )}
                {isAdmin && (
                  <button
                    style={{ display: "flex", alignItems: "center", gap: 12, width: "100%", height: 44, borderRadius: 8, border: "1px solid var(--color-border)", background: "transparent", color: "var(--color-ink)", fontSize: 14, fontWeight: 500, padding: "0 16px", cursor: "pointer", transition: "all 0.15s" }}
                    disabled={actionLoading}
                    onClick={() => onDelete(flag.id)}
                  >
                    <Icon.Trash size={16} /> Delete Flag
                  </button>
                )}
              </div>
            )}
          </div>
        )}

      </div>
    </div>,
    document.body
  );
}

// — Map Canvas —————————————————————————————————————————————————————————————————————————————————————————————————————
// darkMapStyle + REVELA_MAP_ID are shared with SettingsPage / HomePage via src/utils/mapStyles.js

function MapCanvas({
  isDark,
  isLoaded,
  loadError,
  center,
  zoom,
  mapRef,
  layers,
  flags,
  barangayRiskLevels,
  selectedFlagId,
  onMarkerClick,
  onMapClick,
  onDataClick,
  isPickingLocation,
  runDetectionLoading,
  detectionProgress,
  elapsedTime,
  satellite,
  clusters,
  barangayRedFlagCounts,
  adjustingFlagId,
  adjustingLatLng,
  onAdjustDragEnd,
  cancellingDetection,
  handleCancelDetection,
  loadingFlags,
}) {
  const [mapInstance, setMapInstance] = useState(null);
  const [currentZoom, setCurrentZoom] = useState(zoom || 13);
  const markerRefs = useRef(new Map());
  const internalMapRef = useRef(null);
  const clusterRef = useRef(null);
  const diagnosticCircleRefs = useRef([]);
  const geoJsonDataRef = useRef(null);

  // Sync zoom prop if parent changes it
  useEffect(() => {
    if (zoom != null) setCurrentZoom(zoom);
  }, [zoom]);

  // — Draw / clear DBSCAN cluster circles ————————————————————————————————————————————————————————————————————————
  useEffect(() => {
    diagnosticCircleRefs.current.forEach(c => c.setMap(null));
    diagnosticCircleRefs.current = [];

    const activeMap = mapInstance || internalMapRef.current;
    if (!isLoaded || !activeMap) return;
    if (!layers.diagnostics) return;
    if (!clusters || clusters.length === 0) return;

    clusters.forEach((cl) => {
      let fillColor, strokeColor, fillOpacity, strokeOpacity, strokeWeight, zIndex;

      if (cl.size >= 10) {
        fillColor = "#ef4444";
        strokeColor = "#b91c1c";
        fillOpacity = 0.28;
        strokeOpacity = 0.9;
        strokeWeight = 2;
        zIndex = 4;
      } else if (cl.size >= 4) {
        fillColor = "#f59e0b";
        strokeColor = "#b45309";
        fillOpacity = 0.22;
        strokeOpacity = 0.85;
        strokeWeight = 2;
        zIndex = 3;
      } else {
        fillColor = "#fb923c";
        strokeColor = "#c2410c";
        fillOpacity = 0.16;
        strokeOpacity = 0.7;
        strokeWeight = 1.5;
        zIndex = 2;
      }

      const circle = new window.google.maps.Circle({
        map: activeMap,
        center: { lat: cl.centroidLat, lng: cl.centroidLng },
        radius: Math.max(cl.radius_m, 30),
        fillColor,
        fillOpacity,
        strokeColor,
        strokeOpacity,
        strokeWeight,
        zIndex,
        clickable: true,
      });

      const infoWindow = new window.google.maps.InfoWindow({
        content: `
          <div style="font-family:sans-serif;font-size:13px;line-height:1.6;padding:4px 6px;">
            <strong style="color:#b91c1c;">
              Risk Heatmap Cluster #${cl.clusterID}
            </strong><br/>
            <span style="color:#475569;">
              ${cl.size} Red Flag${cl.size !== 1 ? "s" : ""} within ${cl.radius_m} m
            </span><br/>
            <span style="color:#94a3b8;font-size:11px;">
              eps = 20 m · MinPts = 3  · 
              IDs: ${cl.logIDs.slice(0, 6).map(id => `#${id}`).join(", ")}${cl.logIDs.length > 6 ? "…" : ""}
            </span>
          </div>
        `,
      });

      circle.addListener("click", (e) => {
        infoWindow.setPosition(e.latLng);
        infoWindow.open(activeMap);
      });

      diagnosticCircleRefs.current.push(circle);
    });

    return () => {
      diagnosticCircleRefs.current.forEach(c => c.setMap(null));
      diagnosticCircleRefs.current = [];
    };
  }, [isLoaded, mapInstance, layers.diagnostics, clusters]);

  const handleMapLoad = useCallback((map) => {
    internalMapRef.current = map;
    setMapInstance(map);
    setCurrentZoom(map.getZoom() || zoom || 13);
    if (mapRef) mapRef.current = map;

    map.addListener("zoom_changed", () => {
      const z = map.getZoom();
      if (z != null) setCurrentZoom(z);
    });

    if (isPickingLocation) {
      map.setOptions({ draggableCursor: 'crosshair' });
    }
  }, [mapRef, isPickingLocation, zoom]);

  const handleMapUnmount = useCallback(() => {
    markerRefs.current.forEach(m => {
      if (typeof m.setMap === "function") m.setMap(null);
      else m.map = null;
    });
    markerRefs.current.clear();
    if (clusterRef.current) {
      clusterRef.current.clearMarkers();
      clusterRef.current = null;
    }
    internalMapRef.current = null;
    setMapInstance(null);
  }, []);

  // google.maps.Data does not re-apply the react-google-maps <Data> `options`
  // prop after mount — we keep a ref and call data.setStyle() imperatively.
  const geoJsonFeatureStyle = useMemo(
    () => (feature) => {
      if (!layers.barangay && !layers.diagnostics && !isPickingLocation) return { visible: false };

      if (layers.diagnostics) {
        const rawName = (
          feature.getProperty('ADM4_EN') ||
          feature.getProperty('NAME_4') ||
          feature.getProperty('name') ||
          feature.getProperty('brgy_name') || ""
        ).toLowerCase();
        const bName = rawName
          .replace("barangay ", "").replace("brgy. ", "")
          .replace("san sebastian", "san seb.")
          .replace("(pob.)", "")
          .trim();

        const compact = rawName.replace(/\s+/g, "");
        const isMunicipalBoundary =
          MUNICIPAL_BOUNDARY_NAMES.has(bName) ||
          [...MUNICIPAL_BOUNDARY_NAMES].some(
            (n) => compact === n.replace(/\s+/g, "") || bName === n,
          );

        let count;
        let riskLevel;

        if (isMunicipalBoundary) {
          count = Object.values(barangayRedFlagCounts || {}).reduce(
            (sum, n) => sum + Number(n || 0),
            0,
          );
          const levels = Object.values(barangayRiskLevels || {}).map((e) =>
            typeof e === "object" ? e?.risk_level : e,
          );
          riskLevel = levels.includes("High")
            ? "High"
            : levels.includes("Medium")
              ? "Medium"
              : levels.some(Boolean)
                ? "Low"
                : undefined;
        } else {
          count = barangayRedFlagCounts?.[bName] ?? 0;
          if (count === 0) {
            const fuzzyKey = Object.keys(barangayRedFlagCounts || {}).find(
              (k) => rawName.includes(k) || k.includes(rawName),
            );
            if (fuzzyKey) count = barangayRedFlagCounts[fuzzyKey];
          }

          let entry = barangayRiskLevels?.[bName];
          if (!entry) {
            const fuzzyKey = Object.keys(barangayRiskLevels || {}).find(
              (k) => rawName.includes(k) || k.includes(rawName),
            );
            if (fuzzyKey) entry = barangayRiskLevels[fuzzyKey];
          }
          riskLevel = typeof entry === "object" ? entry?.risk_level : entry;
        }

        const tier = heatmapTierKey(riskLevel, count);
        const s = HEATMAP_RISK_STYLE[tier];
        return { ...s, visible: true };
      }

      // Base barangay boundaries style
      return {
        fillColor: "#1f7a1f",
        fillOpacity: 0.12,
        strokeColor: "#166534",
        strokeWeight: 1,
        visible: true,
      };
    },
    [layers.barangay, layers.diagnostics, barangayRiskLevels, barangayRedFlagCounts, isPickingLocation],
  );

  useEffect(() => {
    const dl = geoJsonDataRef.current;
    if (!dl) return;
    dl.setStyle(geoJsonFeatureStyle);
  }, [geoJsonFeatureStyle]);

  // Build a proper pin-shaped SVG marker element for AdvancedMarkerElement
  const buildMarkerContent = useCallback((flag, selected) => {
    const fc = getFlagColor(flag.color);
    const color = selected ? "#2563eb" : fc.marker;
    const w = selected ? 32 : 26;
    const h = selected ? 42 : 34;

    const el = document.createElement("div");
    el.style.cssText = `
      width: ${w}px;
      height: ${h}px;
      cursor: pointer;
      filter: drop-shadow(0 2px 5px rgba(0,0,0,0.35));
      transition: transform 0.15s ease;
      position: relative;
      user-select: none;
    `;

    let innerHtml = `
      <svg viewBox="0 0 24 32" width="${w}" height="${h}" xmlns="http://www.w3.org/2000/svg" style="display: block; overflow: visible;">
        <path d="M12 0C5.37 0 0 5.37 0 12c0 9 12 20 12 20s12-11 12-20C24 5.37 18.63 0 12 0z" fill="${color}" stroke="#ffffff" stroke-width="1.2" />
        <circle cx="12" cy="11" r="4.5" fill="white" opacity="0.95"/>
      </svg>
    `;

    if (flag.hasActiveInspection) {
      innerHtml += `
        <div style="position: absolute; top: -4px; right: -4px; background: white; border-radius: 50%; padding: 2px; box-shadow: 0 1px 3px rgba(0,0,0,0.3); z-index: 10;">
          <div style="background: #3b82f6; width: 14px; height: 14px; border-radius: 50%; display: flex; align-items: center; justify-content: center;">
             <svg width="8" height="8" viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="3" stroke-linecap="round" stroke-linejoin="round">
               <circle cx="11" cy="8"></circle>
               <line x1="21" y1="21" x2="16.65" y2="16.65"></line>
             </svg>
          </div>
        </div>
      `;
    }

    el.innerHTML = innerHtml;
    el.title = flag.name;
    return el;
  }, []);

  // Recreate markers whenever map instance, flags, layers, or selection changes
  useEffect(() => {
    const activeMap = mapInstance || internalMapRef.current;
    if (!isLoaded || !activeMap) return;

    // Clear old clusterer and markers
    if (clusterRef.current) {
      clusterRef.current.clearMarkers();
      clusterRef.current = null;
    }
    markerRefs.current.forEach(m => {
      if (typeof m.setMap === "function") m.setMap(null);
      else m.map = null;
    });
    markerRefs.current.clear();

    if (!layers.flags) return;

    const visibleFlags = flags.filter(
      f => f.latitude != null && f.longitude != null && !isNaN(Number(f.latitude)) && !isNaN(Number(f.longitude))
    );

    const coordCounts = {};
    const markers = [];

    const canUseAdvanced = Boolean(
      window.google?.maps?.marker?.AdvancedMarkerElement
    );

    visibleFlags.forEach(flag => {
      const isAdjusting = flag.id === adjustingFlagId;
      let lat = Number(flag.latitude);
      let lng = Number(flag.longitude);

      if (isAdjusting && adjustingLatLng) {
        lat = adjustingLatLng.lat;
        lng = adjustingLatLng.lng;
      } else if (!isAdjusting) {
        const coordKey = `${lat.toFixed(4)}_${lng.toFixed(4)}`;
        const countIndex = coordCounts[coordKey] || 0;
        coordCounts[coordKey] = countIndex + 1;

        if (countIndex > 0) {
          // Golden spiral micro-jitter so multiple establishments in the same barangay fan out neatly without colliding
          const angle = countIndex * 2.39996;
          const radius = 0.00010 * Math.sqrt(countIndex);
          lat += Math.cos(angle) * radius;
          lng += Math.sin(angle) * radius;
        }
      }

      const isSelected = flag.id === selectedFlagId || isAdjusting;
      let marker = null;

      if (canUseAdvanced) {
        try {
          marker = new window.google.maps.marker.AdvancedMarkerElement({
            position: { lat, lng },
            content: buildMarkerContent(flag, isSelected),
            gmpDraggable: isAdjusting,
            title: flag.name,
          });

          marker._revelaFlagColor = flag.color;
          marker._revelaHasActiveInspection = flag.hasActiveInspection;

          if (isAdjusting) {
            marker.map = activeMap;
            marker.addListener("dragend", (e) => {
              const newLat = typeof marker.position?.lat === 'function' ? marker.position.lat() : (marker.position?.lat ?? e.latLng?.lat());
              const newLng = typeof marker.position?.lng === 'function' ? marker.position.lng() : (marker.position?.lng ?? e.latLng?.lng());
              if (newLat != null && newLng != null) {
                onAdjustDragEnd({ lat: Number(newLat), lng: Number(newLng) });
              }
            });
          } else {
            marker.addListener("gmp-click", () => onMarkerClick(flag.id));
            marker.addListener("click", () => onMarkerClick(flag.id));
            markers.push(marker);
          }
        } catch (e) {
          marker = null;
        }
      }

      if (!marker) {
        const fc = getFlagColor(flag.color);
        const color = isSelected ? "#2563eb" : fc.marker;
        marker = new window.google.maps.Marker({
          position: { lat, lng },
          draggable: isAdjusting,
          title: flag.name,
          zIndex: isSelected ? 9999 : 100,
          icon: {
            path: "M12 0C5.37 0 0 5.37 0 12c0 9 12 20 12 20s12-11 12-20C24 5.37 18.63 0 12 0z",
            fillColor: color,
            fillOpacity: 1,
            strokeColor: "#ffffff",
            strokeWeight: 1.5,
            scale: isSelected ? 1.3 : 1.0,
            anchor: new window.google.maps.Point(12, 32),
          }
        });

        marker._revelaFlagColor = flag.color;
        marker._revelaHasActiveInspection = flag.hasActiveInspection;

        if (isAdjusting) {
          marker.setMap(activeMap);
          marker.addListener("dragend", (e) => {
            if (e.latLng) {
              onAdjustDragEnd({ lat: e.latLng.lat(), lng: e.latLng.lng() });
            }
          });
        } else {
          marker.addListener("click", () => onMarkerClick(flag.id));
          markers.push(marker);
        }
      }

      markerRefs.current.set(flag.id, marker);
    });

    // Initialize MarkerClusterer with SuperClusterAlgorithm
    if (markers.length > 0) {
      clusterRef.current = new MarkerClusterer({
        map: activeMap,
        markers,
        algorithm: new SuperClusterAlgorithm({
          radius: 80,
          maxZoom: 16,
          minPoints: 2,
        }),
        renderer: {
          render: (cluster) => {
            const { count, position, markers: clusterMarkers } = cluster;
            const hasInspection = clusterMarkers.some(m => m._revelaHasActiveInspection);
            const dominant = getDominantFlagColorFromMarkers(clusterMarkers);
            const fc = getFlagColor(dominant);
            const sev = flagSeverityRank(dominant);
            const size = count > 100 ? 56 : count > 50 ? 48 : count > 10 ? 42 : 36;
            const fontSize = count > 99 ? 11 : 13;

            const el = document.createElement("div");
            el.style.cssText = `
              width: ${size}px;
              height: ${size}px;
              background: ${fc.marker};
              border: 3px solid ${fc.text || 'rgba(255,255,255,0.95)'};
              border-radius: 50%;
              display: flex;
              align-items: center;
              justify-content: center;
              color: #ffffff;
              font-weight: 800;
              font-size: ${fontSize}px;
              font-family: system-ui, -apple-system, sans-serif;
              cursor: pointer;
              box-shadow: 0 4px 14px rgba(0, 0, 0, 0.35);
              text-shadow: ${dominant === "Yellow" ? "none" : "0 1px 2px rgba(0, 0, 0, 0.4)"};
              position: relative;
              user-select: none;
            `;

            let html = `<span>${count}</span>`;
            if (hasInspection) {
              html += `
                <div style="position: absolute; top: -5px; right: -5px; background: white; border-radius: 50%; padding: 2px; box-shadow: 0 2px 5px rgba(0,0,0,0.3); z-index: 10;">
                  <div style="background: #3b82f6; width: 16px; height: 16px; border-radius: 50%; display: flex; align-items: center; justify-content: center;">
                     <svg width="9" height="9" viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="3" stroke-linecap="round" stroke-linejoin="round">
                       <circle cx="11" cy="8"></circle>
                       <line x1="21" y1="21" x2="16.65" y2="16.65"></line>
                     </svg>
                  </div>
                </div>
              `;
            }

            el.innerHTML = html;
            el.title = `${count} ${fc.label || 'flags'}`;

            if (window.google?.maps?.marker?.AdvancedMarkerElement) {
              return new window.google.maps.marker.AdvancedMarkerElement({
                position,
                content: el,
                zIndex: 800 + sev * 50 + Math.min(count, 99),
              });
            }

            return new window.google.maps.Marker({
              position,
              label: { text: String(count), color: "#fff", fontWeight: "bold" },
              zIndex: 800 + sev * 50 + Math.min(count, 99),
              icon: {
                path: window.google.maps.SymbolPath.CIRCLE,
                fillColor: fc.marker,
                fillOpacity: 1,
                strokeColor: "#ffffff",
                strokeWeight: 2,
                scale: size / 2,
              }
            });
          },
        },
      });
    }

    return () => {
      if (clusterRef.current) {
        clusterRef.current.clearMarkers();
        clusterRef.current = null;
      }
      markerRefs.current.forEach(m => {
        if (typeof m.setMap === "function") m.setMap(null);
        else m.map = null;
      });
      markerRefs.current.clear();
    };
  }, [isLoaded, mapInstance, layers.flags, flags, selectedFlagId, onMarkerClick, buildMarkerContent, adjustingFlagId, adjustingLatLng, onAdjustDragEnd]);

  // Update cursor dynamically if picking state changes
  useEffect(() => {
    const activeMap = mapInstance || internalMapRef.current;
    if (activeMap) {
      activeMap.setOptions({ draggableCursor: isPickingLocation ? 'crosshair' : null });
    }
  }, [isPickingLocation, mapInstance]);

  // Zoom controls that actually work
  const handleZoomIn = () => {
    const activeMap = mapInstance || internalMapRef.current;
    if (activeMap) {
      activeMap.setZoom(activeMap.getZoom() + 1);
    }
  };

  const handleZoomOut = () => {
    const activeMap = mapInstance || internalMapRef.current;
    if (activeMap) {
      activeMap.setZoom(activeMap.getZoom() - 1);
    }
  };

  const handleCenter = () => {
    const activeMap = mapInstance || internalMapRef.current;
    if (activeMap) {
      activeMap.panTo(DEFAULT_MAP_CENTER);
      activeMap.setZoom(13);
    }
  };

  if (loadError) {
    return (
      <div style={styles.mapCanvas}>
        <div style={styles.mapFallback}>
          <strong>Google Maps failed to load.</strong>
          <span>{loadError?.message ? `Google Maps error: ${loadError.message}` : "Set VITE_GOOGLE_MAPS_API_KEY in your .env and restart."}</span>
          <small style={{ marginTop: 6, color: "var(--color-muted)", fontSize: 12 }}>
            Check browser console for Google Maps API diagnostics.
          </small>
        </div>
      </div>
    );
  }

  if (!isLoaded) {
    return (
      <div style={styles.mapCanvas}>
        <div style={styles.mapFallback}>Loading Google Maps…</div>
      </div>
    );
  }

  return (
    <div style={styles.mapCanvas}>
      <GoogleMap
        mapContainerStyle={{ width: "100%", height: "100%" }}
        center={center}
        zoom={zoom}
        options={{
          disableDefaultUI: true,
          clickableIcons: false,
          zoomControl: false,
          mapTypeId: satellite ? "satellite" : "roadmap",
          mapId: "34390388b3abb63aa84876a7",
          colorScheme: isDark && !satellite ? "DARK" : "LIGHT",
        }}
        onLoad={handleMapLoad}
        onUnmount={handleMapUnmount}
        onClick={onMapClick}
      >
        {(layers.barangay || layers.diagnostics || isPickingLocation) && (
          <Data
            onClick={onDataClick}
            onLoad={(dataLayer) => {
              geoJsonDataRef.current = dataLayer;
              dataLayer.setStyle(geoJsonFeatureStyle);
              Promise.resolve(dataLayer.loadGeoJson("/data/mataasnakahoy.json")).then(() => {
                dataLayer.setStyle(geoJsonFeatureStyle);
              });
            }}
            onUnmount={(dataLayer) => {
              geoJsonDataRef.current = null;
              dataLayer.setMap(null);
            }}
          />
        )}
      </GoogleMap>

      {/* Notice while flags are loading or plotting */}
      {loadingFlags && (
        <div style={{
          position: "absolute",
          top: 16,
          left: "50%",
          transform: "translateX(-50%)",
          zIndex: 40,
          background: "rgba(15, 23, 42, 0.88)",
          backdropFilter: "blur(12px)",
          WebkitBackdropFilter: "blur(12px)",
          color: "#f8fafc",
          borderRadius: 30,
          padding: "9px 20px",
          display: "flex",
          alignItems: "center",
          gap: 10,
          boxShadow: "0 8px 30px rgba(0, 0, 0, 0.4)",
          border: "1px solid rgba(255, 255, 255, 0.15)",
          fontSize: 13,
          fontWeight: 600,
          pointerEvents: "none",
          animation: "fadeIn 0.25s ease-out"
        }}>
          <span style={{ display: "inline-flex", animation: "spin 1s linear infinite" }}>
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="#38bdf8" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
              <path d="M21 12a9 9 0 1 1-6.219-8.56" />
            </svg>
          </span>
          <span>Plotting establishments… The pins are on their way!</span>
        </div>
      )}

      {/* Helpful banner when 0 flags exist */}
      {!loadingFlags && !runDetectionLoading && flags.length === 0 && (
        <div style={{
          position: "absolute",
          top: 16,
          left: "50%",
          transform: "translateX(-50%)",
          zIndex: 40,
          background: "rgba(15, 23, 42, 0.9)",
          backdropFilter: "blur(12px)",
          WebkitBackdropFilter: "blur(12px)",
          color: "#e2e8f0",
          borderRadius: 14,
          padding: "10px 18px",
          display: "flex",
          alignItems: "center",
          gap: 12,
          boxShadow: "0 8px 24px rgba(0,0,0,0.35)",
          border: "1px solid rgba(255,255,255,0.12)",
          fontSize: 12,
          maxWidth: "min(90%, 460px)",
        }}>
          <span style={{ color: "#f59e0b", display: "flex", flexShrink: 0 }}>
            <Icon.AlertTriangle />
          </span>
          <div style={{ lineHeight: 1.4 }}>
            <span style={{ fontWeight: 700, color: "#fff", display: "block" }}>No flagged establishments yet</span>
            <span style={{ color: "#94a3b8" }}>
              Run <strong>Geospatial Scan</strong> or click <strong>+ Add Flag</strong> to plot suspect establishments on the map.
            </span>
          </div>
        </div>
      )}

      {/* Zoom / Center controls */}
      <div style={styles.zoomControls}>
        <button type="button" style={styles.mapBtn} onClick={handleZoomIn} title="Zoom in">  <Icon.ZoomIn /></button>
        <button type="button" style={styles.mapBtn} onClick={handleZoomOut} title="Zoom out"> <Icon.ZoomOut /></button>
        <button type="button" style={styles.mapBtn} onClick={handleCenter} title="Re-center"><Icon.Crosshair /></button>
      </div>

      {/* Detection overlay */}
      {runDetectionLoading && (() => {
        let etrText = "Calculating ETR...";
        if (detectionProgress) {
          const { stage, percentage, current_step, total_steps } = detectionProgress;
          if (stage === "scanning" && current_step && total_steps) {
            if (current_step > 0 && elapsedTime > 0) {
              const timePerStep = elapsedTime / current_step;
              const remainingSteps = total_steps - current_step;
              const remainingMs = remainingSteps * timePerStep;
              // Add a 3 second buffer for matching stage
              const totalRemainingSeconds = Math.round(remainingMs + 3);
              if (totalRemainingSeconds > 0) {
                etrText = `~${totalRemainingSeconds}s remaining`;
              } else {
                etrText = "Finishing up...";
              }
            } else {
              // Initial fallback based on total steps (typical 2s/step)
              etrText = `~${total_steps * 2}s remaining`;
            }
          } else if (stage === "matching") {
            etrText = "Finishing up...";
          } else if (stage === "completed" || percentage >= 100) {
            etrText = "Scan Complete!";
          }
        }

        return (
          <div style={{
            position: "absolute",
            inset: 0,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            background: "rgba(15, 23, 42, 0.45)",
            backdropFilter: "blur(12px)",
            WebkitBackdropFilter: "blur(12px)",
            zIndex: 200,
            transition: "all 0.3s ease"
          }}>
            <div style={{
              display: "flex",
              flexDirection: "column",
              gap: 16,
              color: "#fff",
              background: "linear-gradient(135deg, rgba(30, 41, 59, 0.9), rgba(15, 23, 42, 0.98))",
              borderRadius: 24,
              padding: "24px 28px",
              width: "min(92%, 400px)",
              boxShadow: "0 24px 60px rgba(0, 0, 0, 0.45), inset 0 1px 0 rgba(255, 255, 255, 0.12)",
              border: "1px solid rgba(255, 255, 255, 0.1)",
              fontFamily: "var(--font-base)",
              boxSizing: "border-box"
            }}>
              {/* Header section with radar and title */}
              <div style={{ display: "flex", alignItems: "center", gap: 14, width: "100%", borderBottom: "1px solid var(--color-input-bg)", paddingBottom: 14 }}>
                <div style={{ position: "relative", width: 40, height: 40, display: "flex", alignItems: "center", justifyContent: "center", borderRadius: "50%", background: "rgba(86, 171, 47, 0.15)", border: "1px solid rgba(86, 171, 47, 0.3)", flexShrink: 0 }}>
                  {/* Radar pulsing ring */}
                  <div style={{ position: "absolute", inset: -4, borderRadius: "50%", border: "2px solid var(--color-primary)", opacity: 0.6, animation: "ping 1.5s cubic-bezier(0, 0, 0.2, 1) infinite" }} />
                  <div style={{ display: "flex", alignItems: "center", justifyContent: "center", animation: "spin 3s linear infinite" }}>
                    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="var(--color-primary)" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                      <circle cx="12" cy="12" r="2" />
                      <path d="M12 2a10 10 0 0 1 10 10" />
                      <path d="M12 6a6 6 0 0 1 6 6" />
                    </svg>
                  </div>
                </div>
                <div style={{ display: "flex", flexDirection: "column", minWidth: 0 }}>
                  <span style={{ fontSize: 15, fontWeight: 700, letterSpacing: "-0.01em", color: "#f8fafc" }}>Geospatial Scan Active</span>
                  <span style={{ fontSize: 10, color: "var(--color-muted)", fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.05em" }}>REVELA Engine v2.0</span>
                </div>
              </div>

              {/* Status updates */}
              <div style={{ display: "flex", flexDirection: "column", gap: 8, width: "100%" }}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
                  <span style={{ fontSize: 11, color: "#a8e063", fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.03em" }}>
                    {detectionProgress?.stage === "scanning" ? "🔍 Bounded Map Scan" : detectionProgress?.stage === "matching" ? "📄 Cross-Referencing" : "⚡ Initializing"}
                  </span>
                  <span style={{ fontSize: 13, fontWeight: 800, color: "#f1f5f9" }}>
                    {detectionProgress?.percentage ?? 0}%
                  </span>
                </div>

                {/* Progress bar */}
                <div style={{ width: "100%", height: 8, background: "rgba(15, 23, 42, 0.6)", borderRadius: 10, overflow: "hidden", border: "1px solid var(--color-input-bg)" }}>
                  <div
                    style={{
                      width: `${detectionProgress?.percentage ?? 0}%`,
                      height: "100%",
                      background: "linear-gradient(90deg, #56ab2f, #a8e063, #56ab2f)",
                      backgroundSize: "200% 100%",
                      borderRadius: 10,
                      transition: "width 0.4s cubic-bezier(0.4, 0, 0.2, 1)",
                      animation: "progress-shimmer 2.5s linear infinite"
                    }}
                  />
                </div>

                <div style={{ fontSize: 12, color: "#cbd5e1", lineHeight: "1.4", minHeight: 34, marginTop: 4 }}>
                  {detectionProgress?.status || "Starting scan..."}
                </div>
              </div>

              {/* Footer with clock and ETR */}
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", width: "100%", borderTop: "1px solid var(--color-input-bg)", paddingTop: 12 }}>
                <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 6, color: "var(--color-muted)", fontSize: 11, fontWeight: 500 }}>
                    <span style={{ display: "inline-block", width: 6, height: 6, borderRadius: "50%", background: "#10b981", boxShadow: "0 0 8px #10b981" }} />
                    <span>Elapsed: {elapsedTime}s</span>
                  </div>
                  <button
                    className="ghost-btn"
                    style={{
                      color: "#ef4444",
                      fontSize: 11,
                      fontWeight: 600,
                      padding: "2px 8px",
                      border: "1px solid rgba(239, 68, 68, 0.2)",
                      opacity: cancellingDetection ? 0.5 : 1,
                      cursor: cancellingDetection ? "not-allowed" : "pointer"
                    }}
                    onClick={handleCancelDetection}
                    disabled={cancellingDetection}
                  >
                    {cancellingDetection ? "Cancelling..." : "Cancel Detection"}
                  </button>
                </div>
                <div style={{ fontSize: 11, fontWeight: 700, color: "#e2e8f0", background: "var(--color-input-bg)", padding: "4px 8px", borderRadius: 6, border: "1px solid var(--color-input-bg)" }}>
                  {etrText}
                </div>
              </div>
            </div>
          </div>
        );
      })()}
    </div>
  );
}

// — Side panel flag card ————————————————————————————————————————————————————————————————————————————————————————
function FlagCard({ flag, selected, onClick }) {
  const fc = getFlagColor(flag.color);
  return (
    <div
      onClick={onClick}
      style={{
        ...styles.flagCard,
        borderLeft: `3px solid ${fc.marker}`,
        borderColor: selected ? fc.marker : "var(--color-border)",
        background: selected ? `${fc.bg}` : "var(--color-input-bg)",
      }}
    >
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
        <div style={{ minWidth: 0 }}>
          <p style={styles.flagName}>{flag.name}</p>
          <p style={styles.flagMeta}>{flag.barangay}</p>
        </div>
        <div style={{ textAlign: "right", display: "flex", flexDirection: "column", alignItems: "flex-end", gap: 4 }}>
          {flag.noticeLevel && (
            <span style={{ fontSize: 10, fontWeight: 700, padding: "2px 6px", borderRadius: 4, background: "var(--flag-orange-bg)", color: "var(--flag-orange-text)", display: "inline-block" }}>
              {flag.noticeLevel}
            </span>
          )}
          <span style={{ fontSize: 11, fontWeight: 700, padding: "2px 8px", borderRadius: 12, background: fc.bg || "var(--color-hover)", color: fc.text || "var(--color-ink)" }}>
            {fc.label}
          </span>
        </div>
      </div>
    </div>
  );
}

function YellowFlagModal({ token, barangays, draft, onPickLocation, onClose, onSuccess, isClosing }) {
  const [form, setForm] = useState(draft || { businessName: "", lat: "", lng: "", barangayID: "", notes: "", flagColor: "Yellow" });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (draft) {
      setForm(prev => ({ ...prev, ...draft, flagColor: draft.flagColor || prev.flagColor || "Yellow" }));
    }
  }, [draft]);

  const set = (k, v) => setForm(p => ({ ...p, [k]: v }));

  const handlePickOnMap = () => {
    onPickLocation(form); // pass current form state back to parent so it's not lost
  };

  const handleSubmit = async () => {
    if (!form.businessName || !form.lat || !form.lng || !form.barangayID) {
      setError("Business name, coordinates, and barangay are required.");
      return;
    }
    setLoading(true);
    setError("");
    try {
      await createYellowFlagRequest({
        businessName: form.businessName,
        lat: parseFloat(form.lat),
        lng: parseFloat(form.lng),
        barangayID: parseInt(form.barangayID, 10),
        notes: form.notes || undefined,
        flagColor: form.flagColor,
      }, token);
      onSuccess();
    } catch (err) {
      setError(err.message || "Failed to create flag.");
      setLoading(false);
    }
  };

  const dotBg = "var(--color-warning)";
  const headerLabel = "Flag Suspected Business";
  const btnBg = "var(--color-warning)";
  const btnLabel = loading ? "Saving…" : "+ Flag Suspected Business";

  return createPortal(
    <div className={"modal-backdrop" + (isClosing ? " closing" : "")} onClick={!loading ? onClose : undefined} style={{ position: "fixed", inset: 0, background: "rgba(15,23,42,0.55)", backdropFilter: "blur(4px)", zIndex: 9999, display: "flex", alignItems: "center", justifyContent: "center" }}>
      <div className={"modal-panel" + (isClosing ? " closing" : "")} onClick={e => e.stopPropagation()} style={{ width: 640, maxWidth: "95vw", maxHeight: "85vh", display: "flex", flexDirection: "column", padding: 32, borderRadius: 24, background: "var(--color-modal-bg)", boxShadow: "0 24px 48px rgba(0,0,0,0.2)" }}>

        {/* Header */}
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 24 }}>
          <h2 style={{ margin: 0, fontSize: 22, fontWeight: 800, color: "var(--color-ink)", display: "flex", alignItems: "center", gap: 12 }}>
            <span style={{ width: 12, height: 12, borderRadius: "50%", background: dotBg, display: "inline-block" }}></span>
            {headerLabel}
          </h2>
          <button className="modal-close-btn" onClick={onClose}>
            <Icon.X />
          </button>
        </div>

        {/* Body */}
        <div style={{ flex: 1, overflowY: "auto", paddingRight: 16 }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 18 }}>
            <p style={{ fontSize: 13, color: "var(--color-muted)", lineHeight: 1.6, maxWidth: "70%" }}>
              Manually flag a suspected or closed establishment. It will appear on the map immediately.
            </p>
            <button
              type="button"
              className="ghost-btn"
              style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 12, color: "var(--color-primary)", borderColor: "var(--color-primary-light)", background: "var(--color-primary-light)" }}
              onClick={handlePickOnMap}
            >
              <Icon.Crosshair /> Pick on Map
            </button>
          </div>

          {error && (
            <div style={{ display: "flex", alignItems: "center", gap: 8, background: "var(--color-error-bg)", border: "1px solid var(--color-error-border)", borderRadius: 8, padding: "10px 14px", fontSize: 13, color: "var(--color-danger)", marginBottom: 14 }}>
              <Icon.AlertTriangle /> {error}
            </div>
          )}

          {/* Business Name */}
          <div style={{ marginBottom: 14 }}>
            <label style={{ display: "block", fontSize: 11, fontWeight: 600, color: "var(--color-ink)", marginBottom: 6, textTransform: "uppercase", letterSpacing: "0.05em" }}>
              Business Name *
            </label>
            <input
              style={{ width: "100%", padding: "10px 12px", border: "1px solid var(--color-border)", borderRadius: 8, fontSize: 14, fontFamily: "var(--font-base)", color: "var(--color-ink)", background: "var(--color-input-bg)", outline: "none" }}
              placeholder="e.g. Aling Nena's Tindahan"
              value={form.businessName}
              onChange={e => set("businessName", e.target.value)}
            />
          </div>

          {/* Location status pill — replaces raw lat/lng fields */}
          <div style={{ marginBottom: 14 }}>
            <label style={{ display: "block", fontSize: 11, fontWeight: 600, color: "var(--color-ink)", marginBottom: 6, textTransform: "uppercase", letterSpacing: "0.05em" }}>
              Location *
            </label>
            {form.lat && form.lng ? (
              <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "10px 14px", borderRadius: 8, border: "1px solid var(--color-border)", background: "var(--color-hover)" }}>
                <Icon.MapPin />
                <span style={{ fontSize: 13, color: "var(--color-ink)", fontWeight: 500, flex: 1 }}>
                  Plotted on map
                </span>
                <span style={{ fontSize: 11, color: "var(--color-muted)", fontFamily: "monospace" }}>
                  {form.lat}, {form.lng}
                </span>
              </div>
            ) : (
              <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "10px 14px", borderRadius: 8, border: "1px dashed var(--color-border)", background: "var(--color-surface)", color: "var(--color-muted)", fontSize: 13 }}>
                <Icon.Crosshair />
                <span>No location set — use "Pick on Map" above.</span>
              </div>
            )}
          </div>

          {/* Notes */}
          <div style={{ marginBottom: 14 }}>
            <label style={{ display: "block", fontSize: 11, fontWeight: 600, color: "var(--color-ink)", marginBottom: 6, textTransform: "uppercase", letterSpacing: "0.05em" }}>
              Notes
            </label>
            <input
              style={{ width: "100%", padding: "10px 12px", border: "1px solid var(--color-border)", borderRadius: 8, fontSize: 14, fontFamily: "var(--font-base)", color: "var(--color-ink)", background: "var(--color-input-bg)", outline: "none" }}
              placeholder="Reason for flagging…"
              value={form.notes}
              onChange={e => set("notes", e.target.value)}
            />
          </div>

          {/* Barangay — locked when plotted from map, editable otherwise */}
          <div style={{ marginBottom: 4 }}>
            <label style={{ display: "block", fontSize: 11, fontWeight: 600, color: "var(--color-ink)", marginBottom: 6, textTransform: "uppercase", letterSpacing: "0.05em" }}>
              Barangay *
            </label>
            {form.lat && form.lng ? (
              // Locked — auto-filled from map plot
              <div>
                <div style={{ width: "100%", padding: "10px 12px", border: "1px solid var(--color-border)", borderRadius: 8, fontSize: 14, fontFamily: "var(--font-base)", color: "var(--color-muted)", background: "var(--color-hover)", cursor: "not-allowed", boxSizing: "border-box" }}>
                  {barangays.find(b => String(b.barangayID) === String(form.barangayID))?.barangayName || "Unknown Barangay"}
                </div>
                <p style={{ margin: "5px 0 0", fontSize: 11, color: "var(--color-muted)" }}>
                  Auto-filled from map. Re-plot to change.
                </p>
              </div>
            ) : (
              // Editable — no map location set yet
              <select
                style={{ width: "100%", padding: "10px 12px", border: "1px solid var(--color-border)", borderRadius: 8, fontSize: 14, fontFamily: "var(--font-base)", color: "var(--color-ink)", background: "var(--color-input-bg)", cursor: "pointer" }}
                value={form.barangayID}
                onChange={e => set("barangayID", e.target.value)}
              >
                <option value="">Select barangay…</option>
                {barangays.map(b => (
                  <option key={b.barangayID} value={b.barangayID}>{b.barangayName}</option>
                ))}
              </select>
            )}
          </div>
        </div>

        {/* Footer */}
        <div style={{ display: "flex", justifyContent: "flex-end", gap: 12, marginTop: 24, paddingTop: 24, borderTop: "1px solid var(--color-border-soft)" }}>
          <button className="ghost-btn" onClick={onClose} disabled={loading}>Cancel</button>
          <button
            className="primary-btn"
            style={{ background: btnBg, borderColor: btnBg }}
            onClick={handleSubmit}
            disabled={loading}
          >
            {btnLabel}
          </button>
        </div>
      </div>
    </div>,
    document.body
  );
}

// — Dispatch Modal —————————————————————————————————————————————————————————————————————————————————————————————
function DispatchModal({ flag, token, onClose, onSuccess, isClosing }) {
  const [inspectors, setInspectors] = useState([]);
  const [selectedUID, setSelectedUID] = useState("");
  const [deadline, setDeadline] = useState("");
  const [loading, setLoading] = useState(false);
  const [fetching, setFetching] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    fetch(`${API_ORIGIN}/api/users/?role=Inspector`, {
      headers: { Authorization: `Bearer ${token}` },
    })
      .then(r => r.json())
      .then(data => {
        console.log("Inspectors API Response:", data);
        const list = Array.isArray(data) ? data : (data.data ?? data.users ?? []);
        console.log("Filtered inspectors list:", list);
        setInspectors(list);
        setFetching(false);
      })
      .catch(err => {
        console.error("Error loading inspectors:", err);
        setFetching(false);
        setError("Could not load inspectors.");
      });
  }, [token]);

  const handleAssign = async () => {
    if (!selectedUID) { setError("Select an inspector first."); return; }
    if (deadline && new Date(deadline) < new Date()) {
      Swal.fire({
        icon: 'error',
        title: 'Invalid Deadline',
        text: 'It is no longer possible to select any date or time in the past when assigning a task to an inspector.',
        confirmButtonColor: 'var(--color-primary)'
      });
      return;
    }
    setLoading(true);
    setError("");
    try {
      await assignInspectionRequest({ logID: flag.id, userID: parseInt(selectedUID, 10), deadline }, token);
      Swal.fire({
        icon: 'success',
        title: 'Inspector Dispatched',
        text: 'The inspection task has been successfully assigned.',
        timer: 1500,
        showConfirmButton: false
      });
      onSuccess();
      onClose();
    } catch (err) {
      setError(err.message || "Assignment failed.");
    } finally {
      setLoading(false);
    }
  };

  const fc = getFlagColor(flag.color);

  return createPortal(
    <div className="modal-backdrop" style={{ ...styles.modalBackdrop, zIndex: 10001 }} onClick={!loading ? onClose : undefined}>
      <div className="modal-panel" style={{ ...styles.detailModal, padding: 24, width: 440 }} onClick={e => e.stopPropagation()}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 20 }}>
          <h3 style={styles.modalTitle}>Dispatch Inspector</h3>
          {!loading && <button className="modal-close-btn" onClick={onClose}><Icon.X /></button>}
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 12, background: "var(--color-hover)", border: "1px solid var(--color-border)", borderRadius: "var(--radius-md)", padding: "12px 14px", marginBottom: 20 }}>
          <span style={{ ...styles.flagPill, background: fc.bg, color: fc.text }}>{fc.label}</span>
          <div>
            <p style={{ fontWeight: 700, fontSize: 14, color: "var(--color-ink)", marginBottom: 2 }}>{flag.name}</p>
            <p style={{ fontSize: 12, color: "var(--color-muted)" }}>{flag.barangay}</p>
          </div>
        </div>
        {error && (
          <div style={{ display: "flex", alignItems: "center", gap: 8, background: "var(--color-error-bg)", border: "1px solid var(--color-error-border)", borderRadius: 8, padding: "10px 14px", fontSize: 13, color: "var(--color-danger)", marginBottom: 16 }}>
            <Icon.AlertTriangle /> &nbsp;{error}
          </div>
        )}
        <label style={{ display: "block", fontSize: 11, fontWeight: 600, color: "var(--color-ink)", marginBottom: 8, textTransform: "uppercase", letterSpacing: "0.05em" }}>Select Inspector</label>
        {fetching ? (
          <p style={{ fontSize: 13, color: "var(--color-muted)" }}>Loading inspectors…</p>
        ) : (
          <select style={{ width: "100%", padding: "10px 12px", border: "1px solid var(--color-border)", borderRadius: 8, fontSize: 14, fontFamily: "var(--font-base)", color: "var(--color-ink)", background: "var(--color-modal-bg)", cursor: "pointer", marginBottom: 4 }} value={selectedUID} onChange={e => setSelectedUID(e.target.value)}>
            <option value="">Choose an inspector…</option>
            {inspectors.map(u => (<option key={u.userID} value={u.userID}>{u.fullName}</option>))}
          </select>
        )}
        <label style={{ display: "block", fontSize: 11, fontWeight: 600, color: "var(--color-ink)", marginBottom: 8, marginTop: 12, textTransform: "uppercase", letterSpacing: "0.05em" }}>Deadline (Optional)</label>
        <input
          type="datetime-local"
          style={{ width: "100%", padding: "10px 12px", border: "1px solid var(--color-border)", borderRadius: 8, fontSize: 14, fontFamily: "var(--font-base)", color: "var(--color-ink)", background: "var(--color-modal-bg)", marginBottom: 4, outline: "none", boxSizing: "border-box" }}
          value={deadline}
          min={new Date(new Date().getTime() - new Date().getTimezoneOffset() * 60000).toISOString().slice(0, 16)}
          onChange={e => setDeadline(e.target.value)}
        />

        <div style={{ display: "flex", justifyContent: "flex-end", gap: 10, marginTop: 24 }}>
          <button className="ghost-btn" onClick={onClose} disabled={loading}>Cancel</button>
          <button className="primary-btn" style={{ display: "flex", alignItems: "center", gap: 6 }} onClick={handleAssign} disabled={loading || fetching}>{loading ? "Dispatching…" : <><Icon.Send /> Dispatch</>}</button>
        </div>
      </div>
    </div>,
    document.body
  );
}

// â”€â”€ Main Page â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
export default function MapPage() {
  const navigate = useNavigate();
  const { token, user } = useContext(AuthContext);
  const { isDark } = useTheme();
  const googleMapsApiKey = import.meta.env.VITE_GOOGLE_MAPS_API_KEY || "";
  const { isLoaded, loadError } = useLoadScript({
    googleMapsApiKey,
    libraries: MAP_LIBRARIES,
    version: "beta",
  });

  const mapRef = useRef(null);

  const [flags, setFlags] = useState([]);
  const [barangayRiskLevels, setBarangayRiskLevels] = useState({});
  const [loadingFlags, setLoadingFlags] = useState(false);
  const [flagsError, setFlagsError] = useState("");
  const [actionError, setActionError] = useState("");
  const [actionLoading, setActionLoading] = useState(false);
  const [runDetectionLoading, setRunDetectionLoading] = useState(false);
  const [cancellingDetection, setCancellingDetection] = useState(false);
  const [detectionProgress, setDetectionProgress] = useState(null);
  const [detectionQuota, setDetectionQuota] = useState(null);
  const [elapsedTime, setElapsedTime] = useState(0);
  const startTimeRef = useRef(null);
  const timerIntervalRef = useRef(null);
  const [opsRankings, setOpsRankings] = useState([]);

  const [layers, setLayers] = useState({ base: true, flags: true, barangay: false, diagnostics: false });
  const [selectedFlag, setSelectedFlag] = useState(null);   // logID of selected flag
  const [modalFlag, setModalFlag] = useState(null);   // flag object shown in detail modal
  const location = useLocation();

  useEffect(() => {
    if (!flags || flags.length === 0) return;
    const searchParams = new URLSearchParams(location.search);
    const flagId = searchParams.get("flag");
    if (flagId) {
      const found = flags.find(f => String(f.logID || f.id) === flagId);
      if (found) {
        setModalFlag(found);
      }
    }
  }, [location.search, flags]);
  const [isInspectorModalOpen, setIsInspectorModalOpen] = useState(false);
  const [dispatchTarget, setDispatchTarget] = useState(null);
  const [filterColor, setFilterColor] = useState("all");
  const [search, setSearch] = useState("");
  const [satellite, setSatellite] = useState(false);
  const [filterSource, setFilterSource] = useState("all");

  const isAdmin = user?.role === "Admin" || user?.role === "SUPER_ADMIN";

  const [showYellowModal, setShowYellowModal] = useState(false);
  const [isPickingYellowLocation, setIsPickingYellowLocation] = useState(false);
  const [yellowDraft, setYellowDraft] = useState(null);
  const [barangays, setBarangays] = useState([]);
  const [clusters, setClusters] = useState([]);
  const [clustersLoading, setClustersLoading] = useState(false);
  const geoJsonFeaturesRef = useRef(null); // cached GeoJSON features for PiP checks

  const [adjustingFlagId, setAdjustingFlagId] = useState(null);
  const [adjustingLatLng, setAdjustingLatLng] = useState(null);
  const [saveAdjustLoading, setSaveAdjustLoading] = useState(false);

  const [isRefreshing, setIsRefreshing] = useState(false);

  // ── Fetch ──────────────────────────────────────────────────────────────────
  const fetchFlags = useCallback(async (isSilent = false) => {
    if (!token) return;
    if (!isSilent) {
      setLoadingFlags(true);
      setIsRefreshing(true);
    }
    setFlagsError("");
    try {
      const result = await getFlagsRequest({ limit: 5000 }, token);
      const rawList = Array.isArray(result) ? result : (result?.data ?? result?.flags ?? []);
      setFlags(rawList.map(normalizeFlag));

      // Fetch analytics for border-to-border risk heatmap (current state of the barangay)
      try {
        const ops = await getOpsRankingsRequest(token);
        const rankings = Array.isArray(ops) ? ops : (ops?.data ?? []);
        setOpsRankings(rankings);

        const riskMap = {};
        rankings.forEach(r => {
          const bName = (r.barangayName || "").toLowerCase()
            .replace("barangay ", "").replace("brgy. ", "")
            .replace("san sebastian", "san seb.").trim();
          riskMap[bName] = {
            risk_level: r.risk_level,             // "High" | "Medium" | "Low"
            redFlagCount: r.flagged_count ?? 0,
          };
        });
        setBarangayRiskLevels(riskMap);
      } catch (err) {
        console.error("Failed to load analytics for map", err);
      }
    } catch (err) {
      if (!isSilent) {
        setFlagsError(err.message || "Unable to load flags.");
      }
    } finally {
      setLoadingFlags(false);
      setIsRefreshing(false);
    }
  }, [token]);

  // Count Red Flags per barangay from the already-loaded flags array.
  // Used when prescriptive rankings omit a barangay (unranked tier on the map).
  const barangayRedFlagCounts = useMemo(() => {
    const counts = {};
    flags.forEach(f => {
      if (f.color !== "Red") return;
      const bName = (f.barangay || "unknown").toLowerCase()
        .replace("barangay ", "").replace("brgy. ", "")
        .replace("san sebastian", "san seb.").trim();
      counts[bName] = (counts[bName] || 0) + 1;
    });
    return counts;
  }, [flags]);

  const fetchDetectionQuota = useCallback(async () => {
    if (!token || !isAdmin) return;
    try {
      const data = await getDetectionQuotaRequest(token);
      if (data) {
        setDetectionQuota(data);
      }
    } catch (err) {
      console.error("Failed to load detection quota", err);
    }
  }, [token, isAdmin]);

  useEffect(() => {
    fetchFlags(false);
    fetchDetectionQuota();
  }, [fetchFlags, fetchDetectionQuota]);

  useEffect(() => {
    if (!token || !isAdmin) return;
    getBarangaysRequest(token)
      .then(data => {
        // API may return a bare array or a {data: [...]} wrapper — handle
        // both so the dropdown doesn't silently end up empty.
        const list = Array.isArray(data)
          ? data
          : Array.isArray(data?.data)
            ? data.data
            : [];
        setBarangays(list);
      })
      .catch(err => console.error("Failed to load barangays", err));
  }, [token, isAdmin]);

  // Pre-fetch GeoJSON once so handleMapClick can do real point-in-polygon checks
  useEffect(() => {
    if (geoJsonFeaturesRef.current) return; // already loaded
    fetch("/data/mataasnakahoy.json")
      .then(r => r.json())
      .then(json => {
        geoJsonFeaturesRef.current = Array.isArray(json.features) ? json.features : [];
      })
      .catch(err => console.warn("Could not pre-load GeoJSON for PiP checks", err));
  }, []);

  const [inspectors, setInspectors] = useState([]);
  useEffect(() => {
    if (!token) return;
    fetch(`${import.meta.env.VITE_API_ORIGIN || "http://127.0.0.1:5000"}/api/users/?role=Inspector`, {
      headers: { Authorization: `Bearer ${token}` },
    })
      .then(r => r.json())
      .then(data => {
        const list = Array.isArray(data) ? data : (data.data ?? []);
        setInspectors(list.filter(u => u.isActive !== 0 && u.isActive !== false && u.userRole === 'Inspector'));
      })
      .catch(() => { });
  }, [token]);

  useEffect(() => {
    const handleProgress = (event) => {
      const { detail } = event;
      setDetectionProgress(detail);
      if (detail?.stage === "completed") {
        if (timerIntervalRef.current) {
          clearInterval(timerIntervalRef.current);
          timerIntervalRef.current = null;
        }
        fetchFlags(true);
        fetchDetectionQuota();
      }
    };
    window.addEventListener("revela:detection-progress", handleProgress);
    return () => {
      window.removeEventListener("revela:detection-progress", handleProgress);
      if (timerIntervalRef.current) {
        clearInterval(timerIntervalRef.current);
      }
    };
  }, [fetchFlags, fetchDetectionQuota]);

  // Real-time flag and inspection event listeners + 20s background polling
  useEffect(() => {
    const handleSync = () => { fetchFlags(true); };
    window.addEventListener("revela:yellow-flag", handleSync);
    window.addEventListener("revela:flag-update", handleSync);
    window.addEventListener("revela:inspection-update", handleSync);
    window.addEventListener("revela:registry-update", handleSync);
    window.addEventListener("revela:user-update", handleSync);
    window.addEventListener("revela:global-refresh", handleSync);

    const poll = window.setInterval(() => {
      if (document.visibilityState === "visible") {
        fetchFlags(true);
      }
    }, 20000);

    const handleVisibility = () => {
      if (document.visibilityState === "visible") {
        fetchFlags(true);
      }
    };
    document.addEventListener("visibilitychange", handleVisibility);
    window.addEventListener("focus", handleVisibility);

    return () => {
      window.removeEventListener("revela:yellow-flag", handleSync);
      window.removeEventListener("revela:flag-update", handleSync);
      window.removeEventListener("revela:inspection-update", handleSync);
      window.removeEventListener("revela:registry-update", handleSync);
      window.removeEventListener("revela:user-update", handleSync);
      window.removeEventListener("revela:global-refresh", handleSync);
      window.clearInterval(poll);
      document.removeEventListener("visibilitychange", handleVisibility);
      window.removeEventListener("focus", handleVisibility);
    };
  }, [fetchFlags]);


  useEffect(() => {
    if (!layers.diagnostics || !token) return;
    if (clusters.length > 0) return;           // already fetched this session

    setClustersLoading(true);
    getDiagnosticClustersRequest(token)
      .then(data => {
        setClusters(Array.isArray(data) ? data : (data?.clusters ?? []));
      })
      .catch(err => {
        console.error("[Diagnostics] Failed to load clusters:", err);
      })
      .finally(() => setClustersLoading(false));
  }, [layers.diagnostics, token]);

  // ──────────────────────────────────────────────────────────────────────────────────────────────────
  const handleEscalate = async (logId) => {
    setActionLoading(true);
    setActionError("");
    try {
      await escalateFlagToBlackRequest(logId, token);
      await fetchFlags();
      setModalFlag(null);  // close modal after escalation
      setSelectedFlag(null);
    } catch (err) {
      setActionError(err.message || "Failed to escalate.");
    } finally {
      setActionLoading(false);
    }
  };

  const handleUpdateFlagColor = async (logId, color) => {
    setActionLoading(true);
    setActionError("");
    try {
      await updateFlagColorRequest(logId, color, token);
      await fetchFlags();
      setModalFlag(null); // close modal after color update
      setSelectedFlag(null);
      Swal.fire({
        icon: "success",
        title: "Flag Updated",
        text: `Flag color successfully set to ${color}.`,
        timer: 1500,
        showConfirmButton: false,
      });
    } catch (err) {
      setActionError(err.message || "Failed to update flag color.");
      Swal.fire({
        icon: "error",
        title: "Error",
        text: err.message || "Failed to update flag color.",
      });
    } finally {
      setActionLoading(false);
    }
  };

  const handleRunDetection = async () => {
    if (detectionQuota && detectionQuota.remaining_this_month <= 0) {
      await Swal.fire({
        title: 'Monthly Scan Limit Reached',
        html: `<p style="font-size:14px; margin-bottom:8px;">Detection scans are limited to <strong>2 times per month</strong>.</p>
               <p style="color:var(--color-muted, #94a3b8); font-size:13px;">
                 You have used <strong>${detectionQuota.used_this_month || 2}/2</strong> scans this month.<br/>
                 Next scan will be available on <strong>${detectionQuota.resets_on || 'the 1st of next month'}</strong>.
               </p>`,
        icon: 'info',
        confirmButtonColor: '#6366f1',
        confirmButtonText: 'Understood'
      });
      return;
    }

    const remaining = detectionQuota ? detectionQuota.remaining_this_month : 2;
    const isFinalScan = remaining === 1;

    const confirmRes = await Swal.fire({
      title: 'Run Detection Scan?',
      html: `<p style="margin-bottom:12px; font-size:14px;">This will scan Google Places within Mataasnakahoy and cross-reference against the official business registry.</p>
             ${isFinalScan ? `
             <div style="background:rgba(245,158,11,0.12); border:1px solid rgba(245,158,11,0.4); border-radius:8px; padding:10px 14px; font-size:13px; color:#f59e0b; text-align:left;">
               <strong>Notice: This is your 2nd and final scan for this month.</strong><br/>
               <span style="font-size:12px; opacity:0.95;">After this scan, detection will be locked until <strong>${detectionQuota?.resets_on || 'the 1st of next month'}</strong>.</span>
             </div>
             ` : `
             <div style="background:rgba(99,102,241,0.08); border:1px solid rgba(99,102,241,0.25); border-radius:8px; padding:10px 14px; font-size:13px; color:#6366f1; text-align:left;">
               <strong>Monthly Quota:</strong> 2 of 2 scans remaining for this month.<br/>
               <span style="font-size:12px; opacity:0.85;">(Limited to 2 scans/month; resets on ${detectionQuota?.resets_on || 'the 1st of next month'})</span>
             </div>
             `}`,
      icon: isFinalScan ? 'warning' : 'question',
      showCancelButton: true,
      confirmButtonColor: '#6366f1',
      cancelButtonColor: 'var(--color-muted, #64748b)',
      confirmButtonText: isFinalScan ? 'Proceed with Final Scan' : 'Start Detection Scan'
    });

    if (!confirmRes.isConfirmed) return;

    setRunDetectionLoading(true);
    setDetectionProgress({ stage: "initializing", percentage: 0, status: "Initializing detection engine..." });
    setElapsedTime(0);
    startTimeRef.current = Date.now();

    if (timerIntervalRef.current) clearInterval(timerIntervalRef.current);
    timerIntervalRef.current = setInterval(() => {
      setElapsedTime(Math.round((Date.now() - startTimeRef.current) / 1000));
    }, 1000);

    setActionError("");
    try {
      const result = await runDetectionRequest(token);
      await fetchFlags();
      await fetchDetectionQuota();
      setClusters([]);

      // Stop loader so map is fully visible behind dialog
      setRunDetectionLoading(false);
      setCancellingDetection(false);
      if (timerIntervalRef.current) {
        clearInterval(timerIntervalRef.current);
        timerIntervalRef.current = null;
      }
      setDetectionProgress(null);

      // If the scan was cancelled the backend returns { message: "Detection cancelled by user." }
      // with no new_flags — exit silently, the cancel handler already dismissed the overlay.
      if (!result || result.message) {
        return;
      }

      const count = Number(result.new_flags ?? 0);
      const totalChecked = Number(result.total_checked ?? 0);
      const remainingScans = result.quota?.remaining_this_month ?? 0;
      const resetsOn = result.quota?.resets_on || "the 1st of next month";

      const alertRes = await Swal.fire({
        icon: count > 0 ? "success" : "info",
        title: count > 0 ? "Detection Scan Complete!" : "Scan Complete — No New Gaps",
        html: `
          <div style="text-align: left; font-size: 13.5px; line-height: 1.55; color: var(--color-ink, #0f172a);">
            <div style="background: ${count > 0 ? "rgba(239, 68, 68, 0.08)" : "rgba(16, 185, 129, 0.08)"}; border: 1px solid ${count > 0 ? "rgba(239, 68, 68, 0.25)" : "rgba(16, 185, 129, 0.25)"}; border-radius: 10px; padding: 14px 16px; margin-bottom: 16px;">
              <div style="font-size: 20px; font-weight: 800; color: ${count > 0 ? "#dc2626" : "#059669"}; margin-bottom: 3px;">
                ${count} Unregistered Business${count !== 1 ? "es" : ""} Detected
              </div>
              <div style="font-size: 12.5px; color: ${count > 0 ? "#7f1d1d" : "#065f46"};">
                ${count > 0
                  ? "New Red Flags have been plotted on the municipal map and queued for field verification."
                  : `All ${totalChecked} commercial POIs checked within Mataasnakahoy match active registry permits or are already flagged.`}
              </div>
            </div>
            <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-bottom: 14px;">
              <div style="background: rgba(0,0,0,0.03); border: 1px solid rgba(0,0,0,0.06); border-radius: 8px; padding: 10px 12px;">
                <div style="font-size: 11px; font-weight: 600; color: var(--color-muted, #64748b); text-transform: uppercase;">Places Scanned</div>
                <div style="font-size: 16px; font-weight: 800; color: var(--color-ink, #0f172a); margin-top: 2px;">${totalChecked} locations</div>
              </div>
              <div style="background: rgba(0,0,0,0.03); border: 1px solid rgba(0,0,0,0.06); border-radius: 8px; padding: 10px 12px;">
                <div style="font-size: 11px; font-weight: 600; color: var(--color-muted, #64748b); text-transform: uppercase;">Monthly Scans Left</div>
                <div style="font-size: 16px; font-weight: 800; color: #6366f1; margin-top: 2px;">${remainingScans} of 2</div>
              </div>
            </div>
            ${remainingScans === 0 ? `
              <div style="font-size: 12px; color: #b45309; background: rgba(245, 158, 11, 0.1); border: 1px solid rgba(245, 158, 11, 0.25); border-radius: 6px; padding: 8px 12px;">
                <strong>Notice:</strong> Monthly quota reached. Next scan unlocks on <strong>${resetsOn}</strong>.
              </div>
            ` : ""}
          </div>
        `,
        confirmButtonColor: "#6366f1",
        confirmButtonText: count > 0 ? "View Detected on Map" : "Understood"
      });

      if (alertRes.isConfirmed && count > 0) {
        setFilterColor("Red");
      }
    } catch (err) {
      console.error("Detection scan error:", err);
      Swal.fire({
        icon: "error",
        title: "Detection Scan Failed",
        text: err.message || "An error occurred during the geospatial scan.",
        confirmButtonColor: "#ef4444"
      });
      setActionError(err.message || "Detection failed.");
    } finally {
      setRunDetectionLoading(false);
      setCancellingDetection(false);
      if (timerIntervalRef.current) {
        clearInterval(timerIntervalRef.current);
        timerIntervalRef.current = null;
      }
      setDetectionProgress(null);
    }
  };


  const handleCancelDetection = async () => {
    const result = await Swal.fire({
      title: 'Are you sure?',
      text: "Everything loaded will be rolled back.",
      icon: 'warning',
      showCancelButton: true,
      confirmButtonColor: '#ef4444',
      cancelButtonColor: "var(--color-muted)",
      confirmButtonText: 'Yes, cancel it'
    });

    if (result.isConfirmed) {
      setCancellingDetection(true);
      // Immediately dismiss the overlay — don't wait for the slow
      // run-detection HTTP response to eventually resolve.
      setRunDetectionLoading(false);
      setDetectionProgress(null);
      if (timerIntervalRef.current) {
        clearInterval(timerIntervalRef.current);
        timerIntervalRef.current = null;
      }
      try {
        await cancelRunDetection(token);
        // Refresh flags in the background so any partial results are rolled back
        fetchFlags(true);
      } catch (err) {
        setActionError("Failed to cancel detection.");
      } finally {
        setCancellingDetection(false);
      }
    }
  };

  // â”€â”€ Drag & Drop Adjust Location â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
  const handleStartAdjustLocation = (flag) => {
    setModalFlag(null);
    setSelectedFlag(null);
    setAdjustingFlagId(flag.id);
    setAdjustingLatLng({ lat: Number(flag.latitude), lng: Number(flag.longitude) });
  };

  const handleSaveAdjustedLocation = async () => {
    setSaveAdjustLoading(true);
    try {
      await updateFlagLocationRequest(adjustingFlagId, adjustingLatLng.lat, adjustingLatLng.lng, token);
      await fetchFlags();
      setAdjustingFlagId(null);
      setAdjustingLatLng(null);
    } catch (err) {
      setActionError(err.message || "Failed to update location.");
    } finally {
      setSaveAdjustLoading(false);
    }
  };

  const handleDeleteFlag = async (logId) => {
    const result = await Swal.fire({
      title: 'Are you sure?',
      text: "This flag will be permanently removed from the map.",
      icon: 'warning',
      showCancelButton: true,
      confirmButtonColor: '#ef4444',
      cancelButtoncolor: "var(--color-muted)",
      confirmButtonText: 'Yes, delete it'
    });

    if (result.isConfirmed) {
      setActionLoading(true);
      setActionError("");
      try {
        await deleteFlagRequest(logId, token);
        Swal.fire({ icon: 'success', title: 'Deleted', text: 'Flag deleted successfully.', timer: 1500, showConfirmButton: false });
        await fetchFlags();
        setModalFlag(null);
        setSelectedFlag(null);
      } catch (err) {
        setActionError(err.message || "Failed to delete flag.");
      } finally {
        setActionLoading(false);
      }
    }
  };

  // â”€â”€ Marker click â†’ pan map + open detail modal â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
  const handleMarkerClick = useCallback((id) => {
    const flag = flags.find(f => f.id === id);
    if (!flag) return;

    setSelectedFlag(id);
    setModalFlag(flag);

    // Pan map to marker
    if (mapRef.current && flag.latitude && flag.longitude) {
      mapRef.current.panTo({ lat: Number(flag.latitude), lng: Number(flag.longitude) });
      mapRef.current.setZoom(18);
    }
  }, [flags]);

  // â”€â”€ When user clicks a flag in the side panel â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
  const handleSidePanelClick = (flag) => {
    setSelectedFlag(flag.id);
    setModalFlag(flag);
    if (mapRef.current && flag.latitude && flag.longitude) {
      mapRef.current.panTo({ lat: Number(flag.latitude), lng: Number(flag.longitude) });
      mapRef.current.setZoom(18);
    }
  };

  const handleMapClick = useCallback((e) => {
    if (!isPickingYellowLocation) return;

    const lat = e.latLng.lat();
    const lng = e.latLng.lng();

    const features = geoJsonFeaturesRef.current;

    // If GeoJSON isn't loaded yet, fall back to a tight centroid-distance check
    // (handles the rare race where the fetch hasn't resolved).
    if (!features || features.length === 0) {
      let matchedId = "";
      let bestDist = Infinity;
      for (const b of barangays) {
        const nameKey = b.barangayName.toLowerCase()
          .replace(/barangay/g, "").replace(/brgy\.?/g, "")
          .replace(/district/g, "").replace(/\(pob\.\)/g, "")
          .trim();
        const centroid = BARANGAY_CENTROIDS[nameKey] ||
          Object.entries(BARANGAY_CENTROIDS).find(([k]) => k.includes(nameKey) || nameKey.includes(k))?.[1];
        if (!centroid) continue;
        const dist = Math.hypot(lat - centroid.lat, lng - centroid.lng);
        if (dist < bestDist) { bestDist = dist; matchedId = String(b.barangayID); }
      }
      // 0.04° ≈ ~4 km — tight enough to reject clearly out-of-bounds clicks
      if (bestDist > 0.04) {
        Swal.fire({ icon: 'error', title: 'Out of Bounds', text: 'You can only plot flags within the boundaries of Mataasnakahoy.', confirmButtonColor: 'var(--color-primary)' });
        return;
      }
      setYellowDraft(prev => ({ ...prev, lat: lat.toFixed(6), lng: lng.toFixed(6), barangayID: matchedId }));
      setIsPickingYellowLocation(false);
      setShowYellowModal(true);
      return;
    }

    // ── Real point-in-polygon check against the GeoJSON boundaries ────────────
    let matchedFeature = null;
    for (const feature of features) {
      if (pointInGeoJsonGeometry(lat, lng, feature.geometry)) {
        matchedFeature = feature;
        break;
      }
    }

    if (!matchedFeature) {
      Swal.fire({
        icon: 'error',
        title: 'Out of Bounds',
        text: 'You can only plot flags within the boundaries of Mataasnakahoy.',
        confirmButtonColor: 'var(--color-primary)'
      });
      return;
    }

    // Resolve GeoJSON feature name → DB barangay ID
    const geoAdm4En =
      matchedFeature.properties?.ADM4_EN ||
      matchedFeature.properties?.NAME_4 || "";
    const matched = matchBrgyFromGeoName(geoAdm4En, barangays);
    const matchedId = matched ? String(matched.barangayID) : "";

    setYellowDraft(prev => ({
      ...prev,
      lat: lat.toFixed(6),
      lng: lng.toFixed(6),
      barangayID: matchedId
    }));
    setIsPickingYellowLocation(false);
    setShowYellowModal(true);
  }, [isPickingYellowLocation, barangays]);

  const handleDataClick = useCallback((e) => {
    if (isPickingYellowLocation) {
      e.stop(); // Prevent base map click
      const lat = e.latLng.lat();
      const lng = e.latLng.lng();

      const geoAdm4En =
        e.feature.getProperty('ADM4_EN') ||
        e.feature.getProperty('NAME_4') || "";
      const matched = matchBrgyFromGeoName(geoAdm4En, barangays);
      const matchedId = matched ? String(matched.barangayID) : "";

      setYellowDraft(prev => ({
        ...prev,
        lat: lat.toFixed(6),
        lng: lng.toFixed(6),
        barangayID: matchedId
      }));
      setIsPickingYellowLocation(false);
      setShowYellowModal(true);
    }
  }, [isPickingYellowLocation, barangays]);

  // â”€â”€ Filters â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
  const visibleFlags = flags.filter(f => {
    let matchColor = filterColor === "all" || f.color === filterColor;
    if (filterColor === "Yellow_Inspector") {
      matchColor = f.color === "Yellow" && f.reportedByUserID;
    } else if (filterColor === "in_inspection") {
      matchColor = Boolean(
        f.hasActiveInspection ||
        ['Assigned', 'Reassigned', 'In Progress', 'Submitted'].includes(f.verificationStatus)
      );
    }
    const matchSearch = (f.name || "").toLowerCase().includes(search.toLowerCase()) ||
      (f.barangay || "").toLowerCase().includes(search.toLowerCase());
    const matchSource = filterSource === "all" || f.source === filterSource;
    return matchColor && matchSearch && matchSource;
  });

  const mapCenter = selectedFlag
    ? (() => {
      const f = flags.find(x => x.id === selectedFlag);
      return f?.latitude ? { lat: Number(f.latitude), lng: Number(f.longitude) } : DEFAULT_MAP_CENTER;
    })()
    : DEFAULT_MAP_CENTER;

  const mapZoom = selectedFlag ? 18 : 13;

  // Flag counts
  const counts = {
    all: flags.length,
    in_inspection: flags.filter(f => f.hasActiveInspection || ['Assigned', 'Reassigned', 'In Progress', 'Submitted'].includes(f.verificationStatus)).length,
    Red: flags.filter(f => f.color === "Red").length,
    Yellow: flags.filter(f => f.color === "Yellow").length,
    Yellow_Inspector: flags.filter(f => f.color === "Yellow" && f.reportedByUserID).length,
    Black: flags.filter(f => f.color === "Black").length,
    Green: flags.filter(f => f.color === "Green").length,
    Orange: flags.filter(f => f.color === "Orange").length,
    Purple: flags.filter(f => f.color === "Purple").length,
  };

  return (
    <DashboardLayout user={{ initials: user?.fullName?.charAt(0) ?? "?", name: user?.fullName ?? "" }}>

      {/* Page Header */}
      <div className="page-header">
        <div>
          <h1 className="page-title">Map &amp; Flags</h1>
          <p className="page-subtitle">
            Geospatial view of flagged and unregistered establishments in Mataasnakahoy.
          </p>
          {(flagsError || actionError) && (
            <p style={{ fontSize: 13, marginTop: 6, color: actionError && !flagsError ? "var(--color-primary)" : "var(--color-danger)" }}>
              {flagsError || actionError}
            </p>
          )}
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "nowrap", whiteSpace: "nowrap" }}>
          <button
            className="quick-refresh-btn"
            type="button"
            onClick={() => fetchFlags(false)}
            disabled={isRefreshing}
            title="Refresh map pins and flags"
          >
            <svg
              className={isRefreshing ? "spin-icon" : ""}
              viewBox="0 0 24 24"
              width="14"
              height="14"
              fill="none"
              stroke="currentColor"
              strokeWidth="2.2"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <path d="M21.5 2v6h-6M21.34 15.57a10 10 0 1 1-.57-8.38l5.67-5.19" />
            </svg>
            <span>{isRefreshing ? "Syncing…" : "Refresh"}</span>
          </button>

          <span style={styles.livePill}>
            <span style={styles.liveDot} />
            {flags.filter(f => f.color !== "Green").length} Inactive Flags
          </span>
          {isAdmin && (
            <>
              <button className="ghost-btn" type="button" onClick={() => setShowYellowModal(true)}>
                + Add Flag
              </button>
              <button
                className="primary-btn"
                type="button"
                onClick={handleRunDetection}
                disabled={runDetectionLoading || (detectionQuota && detectionQuota.remaining_this_month === 0)}
                title={
                  detectionQuota && detectionQuota.remaining_this_month === 0
                    ? `Monthly limit reached (0/2 remaining). Resets on ${detectionQuota.resets_on}`
                    : "Run geospatial detection scan (Max 2x/month)"
                }
                style={{
                  opacity: (detectionQuota && detectionQuota.remaining_this_month === 0 && !runDetectionLoading) ? 0.6 : 1,
                  cursor: (detectionQuota && detectionQuota.remaining_this_month === 0 && !runDetectionLoading) ? "not-allowed" : "pointer",
                  display: "inline-flex",
                  alignItems: "center",
                  gap: "7px"
                }}
              >
                <span>{runDetectionLoading ? "Running…" : "Run Detection"}</span>
                {detectionQuota && (
                  <span
                    style={{
                      fontSize: "11px",
                      padding: "1px 7px",
                      borderRadius: "10px",
                      background: detectionQuota.remaining_this_month === 0 ? "rgba(0, 0, 0, 0.3)" : "rgba(255, 255, 255, 0.22)",
                      color: "#ffffff",
                      fontWeight: 700,
                      letterSpacing: "0.02em",
                      lineHeight: 1.4,
                      display: "inline-flex",
                      alignItems: "center"
                    }}
                  >
                    {detectionQuota.remaining_this_month}/2
                  </span>
                )}
              </button>
            </>
          )}
        </div>
      </div>

      {/* Banner showing when picking location */}
      {isPickingYellowLocation && (
        <div style={styles.pickingBanner}>
          <Icon.Crosshair /> Click anywhere on the map to set the flag's coordinates.
          <button style={{ marginLeft: 16, background: "none", border: "none", color: "#fff", textDecoration: "underline", cursor: "pointer" }} onClick={() => { setIsPickingYellowLocation(false); setShowYellowModal(true); }}>Cancel</button>
        </div>
      )}

      {/* Banner showing when adjusting an existing flag */}
      {adjustingFlagId && (
        <div style={{ ...styles.pickingBanner, background: "var(--color-ink)", zIndex: 101, top: 70 }}>
          <Icon.MapPin /> Drag the pin to its correct location.
          <div style={{ display: "flex", gap: 8, marginLeft: 16 }}>
            <button style={{ background: "none", border: "none", color: "var(--color-muted)", cursor: "pointer", fontWeight: 600, fontSize: 13 }} onClick={() => { setAdjustingFlagId(null); setAdjustingLatLng(null); }} disabled={saveAdjustLoading}>
              Cancel
            </button>
            <button className="primary-btn" style={{ padding: "6px 14px", fontSize: 12 }} onClick={handleSaveAdjustedLocation} disabled={saveAdjustLoading}>
              {saveAdjustLoading ? "Saving..." : "Save Location"}
            </button>
          </div>
        </div>
      )}

      {/* Map layout */}
      <div style={styles.mapLayout}>

        {/* Left: map + layer controls */}
        <div style={styles.mapColumn}>

          {/* Layer toggle */}
          <div className="frosted-glass saas-card" style={styles.layerBar}>
            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <Icon.Layers />
              <span style={{ fontSize: 13, fontWeight: 600, color: "var(--color-ink)" }}>Layers</span>
            </div>
            <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
              {LAYER_OPTIONS.map(l => (
                <button
                  key={l.id}
                  onClick={() => {
                    if (l.id === "base") {
                      setSatellite(prev => !prev);
                    } else {
                      setLayers(prev => ({ ...prev, [l.id]: !prev[l.id] }));
                    }
                  }}
                  style={{
                    ...styles.layerToggle,
                    background: (l.id === "base" ? satellite : layers[l.id])
                      ? "var(--color-primary)" : "var(--color-hover)",
                    color: (l.id === "base" ? satellite : layers[l.id])
                      ? "#fff" : "var(--color-muted)",
                    borderColor: (l.id === "base" ? satellite : layers[l.id])
                      ? "var(--color-primary)" : "var(--color-border-soft)",
                  }}
                >
                  {l.label}
                  {l.id === "diagnostics" && layers.diagnostics && clustersLoading && (
                    <span style={{ fontSize: 11, color: "var(--color-muted)", marginLeft: 4 }}>
                      loadingâ€¦
                    </span>
                  )}
                </button>
              ))}
            </div>
          </div>

          {/* Map */}
          <div className="frosted-glass" style={styles.mapWrapper}>
            <MapCanvas
              isDark={isDark}
              isLoaded={isLoaded}
              loadError={loadError}
              center={mapCenter}
              zoom={mapZoom}
              mapRef={mapRef}
              layers={layers}
              flags={visibleFlags}
              barangayRiskLevels={barangayRiskLevels}
              selectedFlagId={selectedFlag}
              onMarkerClick={handleMarkerClick}
              onMapClick={handleMapClick}
              onDataClick={handleDataClick}
              isPickingLocation={isPickingYellowLocation}
              runDetectionLoading={runDetectionLoading}
              detectionProgress={detectionProgress}
              elapsedTime={elapsedTime}
              satellite={satellite}
              clusters={clusters}
              barangayRedFlagCounts={barangayRedFlagCounts}
              adjustingFlagId={adjustingFlagId}
              adjustingLatLng={adjustingLatLng}
              onAdjustDragEnd={setAdjustingLatLng}
              cancellingDetection={cancellingDetection}
              handleCancelDetection={handleCancelDetection}
              loadingFlags={loadingFlags}
            />
            {/* Discrete risk legend â€” matches HEATMAP_RISK_STYLE on the Data layer */}
            {layers.diagnostics && (
              <div style={{
                position: "absolute",
                bottom: 14,
                left: 14,
                zIndex: 10,
                background: "var(--color-modal-bg)",
                backdropFilter: "blur(6px)",
                borderRadius: 10,
                padding: "10px 14px",
                boxShadow: "0 2px 12px rgba(0,0,0,0.15)",
                minWidth: 168,
              }}>
                <p style={{ fontSize: 10, fontWeight: 700, color: "var(--color-muted)", textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 8 }}>
                  Barangay risk index
                </p>
                <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                  {[
                    { tier: "High", label: "High risk" },
                    { tier: "Medium", label: "Moderate risk" },
                    { tier: "Low", label: "Low risk" },
                    { tier: "unranked", label: "Red flags (unranked)" },
                    { tier: "none", label: "No red flags" },
                  ].map(({ tier, label }) => {
                    const row = HEATMAP_RISK_STYLE[tier];
                    return (
                      <div key={tier} style={{ display: "flex", alignItems: "center", gap: 8 }}>
                        <span
                          style={{
                            width: 22,
                            height: 14,
                            borderRadius: 2,
                            background: row.fillColor,
                            border: `1px solid ${row.strokeColor}`,
                            flexShrink: 0,
                            opacity: 0.92,
                          }}
                        />
                        <span style={{ fontSize: 11, color: "var(--color-ink)", fontWeight: 500 }}>{label}</span>
                      </div>
                    );
                  })}
                </div>
              </div>
            )}
          </div>

          {/* Stats strip */}
          <div style={styles.statsStrip}>
            {[
              { label: "Total Flags", value: flags.length, color: "var(--color-ink)" },
              { label: "Active Businesses", value: counts.Green, color: "#22c55e" },
              { label: "1st/2nd Warning / Notice", value: counts.Orange, color: "#e65100" },
              { label: "Detected Unregistered", value: counts.Red, color: "#ef4444" },
              { label: "Suspected Unregistered", value: counts.Yellow, color: "#f59e0b" },
              { label: "Closed / Abandoned", value: counts.Purple, color: "#7c3aed" },
              { label: "Critical Violations", value: counts.Black, color: "var(--color-ink)" },
            ].map(s => (
              <div key={s.label} className="frosted-glass saas-card" style={styles.statCard}>
                <span style={{ fontSize: "clamp(15px, 1.4vw, 22px)", fontWeight: 800, color: s.color, lineHeight: 1, textAlign: "left" }}>{s.value}</span>
                <span style={{
                  fontSize: "clamp(9.5px, 0.85vw, 11.5px)",
                  color: "var(--color-muted)",
                  fontWeight: 600,
                  lineHeight: 1.2,
                  textAlign: "left",
                  wordBreak: "break-word",
                  overflowWrap: "anywhere",
                }}>{s.label}</span>
              </div>
            ))}
          </div>
        </div>

        {/* Right: side panel */}
        <div className="frosted-glass saas-card" style={styles.sidePanel}>

          <div style={{ marginBottom: 14 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 10 }}>
              <Icon.Flag />
              <h3 style={{ fontSize: 14, fontWeight: 700, color: "var(--color-ink)", flex: 1 }}>
                Flagged Locations
              </h3>
              {(filterColor !== "all" || search !== "" || filterSource !== "all") && (
                <button
                  type="button"
                  style={{ background: "transparent", border: "none", color: "var(--color-primary)", fontSize: 11, fontWeight: 600, cursor: "pointer", padding: "0 8px" }}
                  onClick={() => { setFilterColor("all"); setSearch(""); setFilterSource("all"); }}
                >
                  Clear Filters
                </button>
              )}
              <span style={styles.countBadge}>{visibleFlags.length}</span>
            </div>
            <hr style={{ border: "none", borderTop: "1px solid var(--color-border-soft)", margin: "0 0 14px 0" }} />

            {/* Legend / Filter List */}
            <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
              {["all", "in_inspection", "Green", "Yellow", "Yellow_Inspector", "Orange", "Red", "Black", "Purple"].map(c => {
                const isSelected = filterColor === c;
                const dotColor = c === "all" ? "var(--color-ink)" : (FLAG_COLORS[c]?.marker ?? "var(--color-ink)");
                const label = c === "all" ? "All Locations" : (FLAG_COLORS[c]?.label ?? c);

                return (
                  <button
                    key={c}
                    onClick={() => {
                      setFilterColor(c);
                      if (c !== "Green") setFilterSource("all");
                    }}
                    style={{
                      display: "flex",
                      justifyContent: "space-between",
                      alignItems: "center",
                      width: "100%",
                      padding: "8px 12px",
                      background: isSelected ? "var(--color-input-bg)" : "transparent",
                      border: "1px solid",
                      borderColor: isSelected ? "var(--color-border-soft)" : "transparent",
                      borderRadius: 8,
                      cursor: "pointer",
                      transition: "all 0.15s ease",
                      textAlign: "left"
                    }}
                  >
                    <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                      <span style={{
                        width: 10, height: 10, borderRadius: "50%",
                        background: dotColor,
                        boxShadow: isSelected ? `0 0 0 2px var(--color-surface), 0 0 0 4px ${dotColor}40` : "none"
                      }} />
                      <span style={{
                        fontSize: 13,
                        fontWeight: isSelected ? 700 : 500,
                        color: isSelected ? "var(--color-ink)" : "var(--color-muted)"
                      }}>
                        {label}
                      </span>
                    </div>
                    <span style={{
                      fontSize: 11,
                      fontWeight: 700,
                      color: isSelected ? "var(--color-ink)" : "var(--color-muted)",
                      background: isSelected ? "var(--color-hover)" : "transparent",
                      padding: "2px 8px",
                      borderRadius: 12
                    }}>
                      {counts[c] || 0}
                    </span>
                  </button>
                );
              })}
            </div>

            {/* Source filter â€” shows only when Green is selected */}
            {filterColor === "Green" && (
              <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginTop: 8 }}>
                {[
                  { value: "all", label: "All Sources" },
                  { value: "registry_only", label: "ðŸ“‹ Registry Only" },
                  { value: "registry_and_maps", label: "ðŸ—ºï¸  Registry + Maps" },
                ].map(s => (
                  <button
                    key={s.value}
                    onClick={() => setFilterSource(s.value)}
                    style={{
                      ...styles.filterPill,
                      fontSize: 10,
                      background: filterSource === s.value ? "var(--color-ink)" : "var(--color-input-bg)",
                      color: filterSource === s.value ? "#fff" : "var(--color-muted)",
                      borderColor: filterSource === s.value ? "transparent" : "var(--color-border)",
                    }}
                  >
                    {s.label}
                  </button>
                ))}
              </div>
            )}
          </div>

          {/* Priority Dispatch Queue */}
          {isAdmin && opsRankings.length > 0 && (
            <div className="priority-dispatch-queue" style={{ marginBottom: 14, background: "var(--color-input-bg)", padding: 12, borderRadius: "var(--radius-md)", border: "1px solid var(--color-border-soft)" }}>
              <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 8 }}>
                <div className="priority-dispatch-icon" style={{ color: "var(--color-primary)", display: "flex" }}><Icon.AlertTriangle /></div>
                <h4 style={{ fontSize: 12, fontWeight: 700, color: "var(--color-ink)", margin: 0, textTransform: "uppercase", letterSpacing: "0.05em" }}>
                  Priority Dispatch Queue
                </h4>
              </div>
              <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                {opsRankings.filter(r => r.flagged_count > 0).slice(0, 3).map((r, i) => (
                  <div className="priority-dispatch-item" key={r.barangayID} style={{ display: "flex", justifyContent: "space-between", alignItems: "center", background: "var(--color-modal-bg)", padding: "8px 10px", borderRadius: 8, border: "1px solid var(--color-border-soft)" }}>
                    <div>
                      <div className="priority-dispatch-name" style={{ fontSize: 12, fontWeight: 700, color: "var(--color-ink)", marginBottom: 2 }}>{i + 1}. {r.barangayName}</div>
                      <div className="priority-dispatch-meta" style={{ fontSize: 10, color: "var(--color-muted)", fontWeight: 600 }}>
                        OPS: <span style={{ color: r.ops_score >= 60 ? "#dc2626" : r.ops_score >= 30 ? "#d97706" : "#16a34a" }}>{r.ops_score}</span>
                        <span style={{ margin: "0 4px" }}>&bull;</span>
                        {r.flagged_count} flagged
                      </div>
                    </div>
                    <button
                      className="ghost-btn priority-filter-btn"
                      style={{ fontSize: 10, padding: "4px 10px" }}
                      onClick={() => {
                        setSearch(r.barangayName);
                        setFilterColor("all");
                      }}
                    >
                      Filter
                    </button>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Action Buttons at Bottom */}
          <div style={{ display: "flex", flexDirection: "column", gap: 8, marginTop: 12 }}>
            {isAdmin && (
              <button
                className="primary-btn"
                style={{
                  width: "100%",
                  justifyContent: "center",
                  padding: "12px 14px",
                  borderRadius: 12,
                  fontSize: 13,
                  fontWeight: 700,
                  boxSizing: "border-box",
                }}
                onClick={() => setIsInspectorModalOpen(true)}
              >
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" style={{ marginRight: 6, flexShrink: 0 }}><path d="M4 15s1-1 4-1 5 2 8 2 4-1 4-1V3s-1 1-4 1-5-2-8-2-4 1-4 1z" /><line x1="4" y1="22" x2="4" y2="15" /></svg>
                View Inspector Backlog
              </button>
            )}
          </div>

        </div>
      </div>

      {/* Footer */}
      <footer className="saas-footer frosted-glass">
        <p>&copy; 2026 Municipality of Mataasnakahoy. All Rights Reserved.</p>
        <p className="footer-links"><span>BPLO Portal</span> &bull; <span>System Settings</span></p>
      </footer>

      {/* Flag detail modal â€” opens on marker or side panel click */}
      <AnimatePresence isVisible={!!modalFlag}>
        <FlagDetailModal
          flag={modalFlag}
          onClose={() => { setModalFlag(null); setSelectedFlag(null); }}
          onEscalate={handleEscalate}
          onAdjustLocation={handleStartAdjustLocation}
          onDispatch={(flag) => setDispatchTarget(flag)}
          onDelete={handleDeleteFlag}
          onUpdateColor={handleUpdateFlagColor}
          isAdmin={isAdmin}
          actionLoading={actionLoading}
        />
      </AnimatePresence>



      <AnimatePresence isVisible={!!dispatchTarget}>
        <DispatchModal
          flag={dispatchTarget}
          token={token}
          onClose={() => setDispatchTarget(null)}
          onSuccess={() => {
            setDispatchTarget(null);
            setModalFlag(null);
            setSelectedFlag(null);
            fetchFlags();
          }}
        />
      </AnimatePresence>

      <AnimatePresence isVisible={showYellowModal}>
        <YellowFlagModal
          token={token}
          barangays={barangays}
          draft={yellowDraft}
          onPickLocation={(currentForm) => {
            setYellowDraft(currentForm);
            setShowYellowModal(false);
            setIsPickingYellowLocation(true);
          }}
          onClose={() => setShowYellowModal(false)}
          onSuccess={() => { setShowYellowModal(false); setYellowDraft(null); fetchFlags(); }}
        />
      </AnimatePresence>

      {/* Modals */}
      <InspectorReportsModal
        isOpen={isInspectorModalOpen}
        onClose={() => setIsInspectorModalOpen(false)}
        flags={flags}
        inspectors={inspectors}
        navigate={navigate}
      />
    </DashboardLayout>
  );
}

// â”€â”€ Styles â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
const styles = {
  livePill: { display: "inline-flex", alignItems: "center", gap: 6, background: "#fee2e2", color: "#b91c1c", padding: "6px 14px", borderRadius: 20, fontSize: 12, fontWeight: 700 },
  liveDot: { width: 7, height: 7, borderRadius: "50%", background: "#ef4444" },

  mapLayout: { display: "grid", gridTemplateColumns: "1fr 320px", gap: 20, alignItems: "stretch" },
  mapColumn: { display: "flex", flexDirection: "column", gap: 14, minWidth: 0 },

  layerBar: { display: "flex", alignItems: "center", gap: 16, padding: "12px 18px", borderRadius: "var(--radius-lg)", flexWrap: "wrap" },
  layerToggle: { padding: "6px 12px", borderRadius: 20, border: "1px solid", fontSize: 12, fontWeight: 600, cursor: "pointer", fontFamily: "var(--font-base)", transition: "all 0.15s" },

  mapWrapper: { borderRadius: "var(--radius-lg)", overflow: "hidden", position: "relative", flex: 1, minHeight: 480 },
  mapCanvas: { width: "100%", height: "100%", position: "relative", background: "#e8f5e2" },
  mapFallback: { position: "absolute", inset: 0, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 8, color: "var(--color-ink)", fontSize: 14, textAlign: "center", padding: 24 },

  zoomControls: { position: "absolute", top: 16, right: 16, display: "flex", flexDirection: "column", gap: 4, zIndex: 10 },
  mapBtn: { width: 36, height: 36, background: "var(--color-modal-bg)", border: "1px solid var(--color-border)", borderRadius: "var(--radius-sm)", display: "flex", alignItems: "center", justifyContent: "center", cursor: "pointer", color: "var(--color-muted)", backdropFilter: "blur(8px)" },
  overlay: { position: "absolute", inset: 0, display: "flex", alignItems: "center", justifyContent: "center", background: "rgba(15,23,42,0.5)", zIndex: 20 },
  overlayCard: { display: "flex", flexDirection: "column", alignItems: "center", gap: 6, color: "#fff", background: "rgba(15,23,42,0.8)", borderRadius: 16, padding: "16px 24px", fontSize: 14 },
  pickingBanner: { position: "fixed", top: 16, left: "50%", transform: "translateX(-50%)", background: "var(--color-primary)", color: "#fff", padding: "12px 24px", borderRadius: 30, zIndex: 100, display: "flex", alignItems: "center", gap: 8, fontSize: 14, fontWeight: 600, boxShadow: "0 10px 25px rgba(0,0,0,0.2)" },

  statsStrip: { display: "grid", gridTemplateColumns: "repeat(7, minmax(0, 1fr))", gap: 6 },
  statCard: { display: "flex", flexDirection: "column", alignItems: "flex-start", justifyContent: "center", textAlign: "left", gap: 4, padding: "12px 10px", borderRadius: "var(--radius-lg)", minWidth: 0, overflow: "hidden" },

  sidePanel: { borderRadius: "var(--radius-lg)", padding: 16, display: "flex", flexDirection: "column", position: "sticky", top: 20, minWidth: 0 },
  flagList: { overflowY: "auto", display: "flex", flexDirection: "column", gap: 8, flex: 1, paddingRight: 2 },
  flagCard: { border: "1px solid", borderRadius: "var(--radius-md)", padding: "12px 14px", cursor: "pointer", transition: "all 0.12s" },
  flagName: { fontSize: 13, fontWeight: 700, color: "var(--color-ink)", marginBottom: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" },
  flagMeta: { fontSize: 11, color: "var(--color-muted)" },
  flagPill: { fontSize: 10, fontWeight: 700, padding: "2px 8px", borderRadius: 10, letterSpacing: "0.03em", whiteSpace: "nowrap" },

  countBadge: { background: "#fee2e2", color: "#b91c1c", fontSize: 11, fontWeight: 700, padding: "2px 8px", borderRadius: 12 },
  filterPill: { padding: "4px 10px", borderRadius: 20, border: "1px solid", fontSize: 11, fontWeight: 600, cursor: "pointer", fontFamily: "var(--font-base)", transition: "all 0.12s" },
  emptyPanel: { textAlign: "center", padding: "40px 0", color: "var(--color-muted)", fontSize: 13, display: "flex", flexDirection: "column", alignItems: "center", gap: 8 },

  // Detail modal
  modalBackdrop: { position: "fixed", inset: 0, zIndex: 10000, background: "rgba(15,23,42,0.55)", backdropFilter: "blur(4px)", display: "flex", alignItems: "center", justifyContent: "center", padding: 24 },
  detailModal: { width: "min(100%, 480px)", borderRadius: 20, background: "var(--color-modal-bg)", boxShadow: "0 24px 60px rgba(15,23,42,0.18)", overflow: "hidden" },
  detailHeader: { display: "flex", alignItems: "center", justifyContent: "space-between", padding: "16px 20px" },
  detailBody: { padding: "20px 24px" },
  detailName: { fontSize: 18, fontWeight: 700, color: "var(--color-ink)", marginBottom: 16, lineHeight: 1.3 },
  detailGrid: { display: "flex", flexDirection: "column", gap: 10 },
  detailRow: { display: "flex", gap: 12, alignItems: "flex-start" },
  detailLabel: { minWidth: 110, fontSize: 12, color: "var(--color-muted)", fontWeight: 500, paddingTop: 1 },
  detailValue: { fontSize: 13, color: "var(--color-ink)", fontWeight: 400, flex: 1 },
  detailFooter: { display: "flex", gap: 10, padding: "16px 24px", borderTop: "1px solid var(--color-border-soft)", flexWrap: "wrap" },
  closeBtn: { width: 32, height: 32, borderRadius: 8, border: "1px solid rgba(148,163,184,0.3)", background: "var(--color-input-bg)", display: "flex", alignItems: "center", justifyContent: "center", cursor: "pointer", color: "var(--color-muted)" },

  // Full list modal
  fullListModal: { width: "min(100%, 900px)", maxHeight: "85vh", borderRadius: 20, background: "var(--color-modal-bg)", boxShadow: "0 24px 60px rgba(15,23,42,0.16)", overflow: "hidden" },
  fullListHeader: { display: "flex", alignItems: "flex-start", justifyContent: "space-between", padding: "24px 24px 16px" },
  modalTitle: { fontSize: 18, fontWeight: 700, color: "var(--color-ink)", margin: 0 },
  fullListTable: { width: "100%", borderCollapse: "collapse", minWidth: 640, fontSize: 13 },
  th: { textAlign: "left", padding: "10px 16px", color: "var(--color-muted)", fontSize: 11, textTransform: "uppercase", letterSpacing: "0.04em", borderBottom: "1px solid rgba(148,163,184,0.2)", fontWeight: 700, whiteSpace: "nowrap" },
  td: { padding: "12px 16px", borderBottom: "1px solid rgba(148,163,184,0.12)", color: "var(--color-ink)", verticalAlign: "middle" },
  modalSelect: { padding: "0 12px", height: 40, borderRadius: "var(--radius-sm)", border: "1px solid var(--color-border)", background: "var(--color-hover)", fontSize: 13, color: "var(--color-ink)", outline: "none", cursor: "pointer", fontFamily: "var(--font-base)" },
};
