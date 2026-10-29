import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import {
  analyticsDetectionScanSummary,
  fetchHotspotClusterPins,
  hotspotOverlayRadius,
  hotspotClusterDetails,
  hotspotMethodNote,
  hotspotPinMapPath,
  hotspotRequestParams,
  hotspotScanNote,
  hotspotSummary,
  hotspotViewTransition,
} from "./hotspotPresentation.js";

const mapOverviewSource = readFileSync(
  new URL("./MapOverview.jsx", import.meta.url),
  "utf8",
);
const mapOverviewStyles = readFileSync(
  new URL("../styles/MapOverview.css", import.meta.url),
  "utf8",
);
const mapPageSource = readFileSync(
  new URL("../pages/MapPage.jsx", import.meta.url),
  "utf8",
);
const apiSource = readFileSync(
  new URL("../services/api.js", import.meta.url),
  "utf8",
);

test("hotspot totals count spanning clusters once overall and once per barangay", () => {
  const data = {
    clusters: [
      {
        cluster_id: 0,
        per_barangay: [
          { barangay_id: 2, count: 2 },
          { barangay_id: 3, count: 1 },
        ],
      },
      {
        cluster_id: 1,
        per_barangay: [{ barangay_id: 2, count: 3 }],
      },
    ],
    totals: { clustered_points: 6, uncertain_points: 1 },
  };
  assert.deepEqual(hotspotSummary(data), {
    clusterCount: 2,
    locationCount: 6,
    uncertainCount: 1,
  });
  assert.deepEqual(hotspotSummary(data, 2), {
    clusterCount: 2,
    locationCount: 5,
    uncertainCount: 0,
  });
  assert.deepEqual(hotspotSummary(data, 3), {
    clusterCount: 1,
    locationCount: 1,
    uncertainCount: 0,
  });
});

test("hotspot request is scoped only by the selected date preset", () => {
  assert.deepEqual(hotspotRequestParams("30days"), { date_preset: "30days" });
  assert.deepEqual(hotspotRequestParams(""), { date_preset: "all" });
  assert.match(apiSource, /getAnalyticsHotspotsRequest\(token, datePreset = "all"/);
  assert.match(apiSource, /new URLSearchParams\(\{\s*date_preset: datePreset \|\| "all"/);
  assert.doesNotMatch(
    apiSource.slice(
      apiSource.indexOf("export async function getAnalyticsHotspotsRequest"),
      apiSource.indexOf("export async function getDemographicReportsRequest"),
    ),
    /filters|display_sector|barangay_id/,
  );
  assert.match(mapOverviewSource, /const \[showHotspots, setShowHotspots\] = useState\(false\)/);
  assert.match(mapOverviewSource, /\[hotspotRequest\.date_preset,[^\]]*token\]\);/);
  assert.match(mapOverviewSource, /role="switch"[\s\S]*?aria-checked=\{showHotspots\}/);
});

test("overlay radius adds padding and incomplete scan note is explicit", () => {
  assert.equal(hotspotOverlayRadius(100), 110);
  assert.equal(hotspotOverlayRadius(0), 8);
  assert.deepEqual(hotspotScanNote({
    date: "2026-10-29T04:30:00Z",
    status: "partial",
  }), {
    text: "Last detection scan: 2026-10-29 · Partial · Stop reason: reason not recorded",
    coverageIncomplete: true,
  });

  assert.deepEqual(hotspotScanNote({
    date: "2026-10-29T04:30:00Z",
    status: "partial",
    stop_reason: "places_quota",
  }), {
    text: "Last detection scan: 2026-10-29 · Partial · Stop reason: Places quota",
    coverageIncomplete: true,
  });
  assert.match(hotspotScanNote({
    date: "2026-10-29T04:30:00Z",
    status: "partial",
    stop_reason: "api_error",
  }).text, /Stop reason: API error$/);
  assert.match(mapOverviewSource, /clickable: false,[\s\S]*?zIndex: 200/);
  assert.match(mapOverviewSource, /No nearby groups for this period\./);
  assert.match(mapOverviewSource, /Nearby groups are possible hotspots only; they do not confirm a violation\./);
});

test("hotspot method note separates eligible detection clusters from map fill measures", () => {
  assert.equal(hotspotMethodNote({
    eps_m: 50,
    min_samples: 3,
  }, "registered"),
  "DBSCAN groups eligible effective-Red detection pins (Haversine eps 50 m; MinPts 3). Orange circles show hotspot groups; polygon fills show registered-business counts, not OPS tiers.");
  assert.match(mapOverviewSource, /hotspotMethodNote\(hotspotData\.parameters_used, mapView\)/);
  assert.match(mapOverviewSource, /eligible effective-Red detection pins/);
});

test("enabling hotspots overrides map mode and hides registered/inspection controls", () => {
  assert.deepEqual(hotspotViewTransition(true), {
    showHotspots: true,
    mapView: "registered",
  });
  assert.deepEqual(hotspotViewTransition(false), {
    showHotspots: false,
    mapView: null,
  });
  assert.match(mapOverviewSource, /!showHotspots && \([\s\S]*?aria-label="Map color"/);
  assert.match(mapOverviewSource, /const transition = hotspotViewTransition\(next\)/);
});

test("map stage stretches with its panel and map zoom stays focused on the municipality", () => {
  assert.match(mapOverviewStyles, /\.map-overview-layout\s*\{[^}]*align-items:\s*stretch/);
  assert.match(
    mapOverviewStyles,
    /\.map-overview-map-stage\s*\{[^}]*flex:\s*1 1 auto;[^}]*height:\s*auto;/,
  );
  assert.match(mapOverviewSource, /const MAP_MIN_ZOOM = 12/);
  assert.match(
    mapOverviewSource,
    /minZoom:\s*Math\.max\(MIN_BARANGAY_MAP_ZOOM,\s*MAP_MIN_ZOOM\)/,
  );
});

test("hotspot panel shows only its summary and selected-cluster content", () => {
  assert.match(
    mapOverviewSource,
    /showHotspots && \(\s*<>[\s\S]*?<h4>Possible nearby groups<\/h4>[\s\S]*?selectedCluster && clusterDetail[\s\S]*?Select an orange hotspot cluster on the map[\s\S]*?<\/>\s*\)/,
  );
  assert.match(
    mapOverviewSource,
    /!showHotspots && \(\s*<div className="map-overview-panel-heading">/,
  );
  assert.match(
    mapOverviewSource,
    /!showHotspots && \(\s*<>[\s\S]*?A\. Official Registry[\s\S]*?B\. Field Inspections[\s\S]*?Inspections ·[\s\S]*?<\/>\s*\)/,
  );
  assert.match(
    mapOverviewSource,
    /map-overview-cluster-prompt" role="status"/,
  );
});

test("hotspot summary header keeps its info button aligned at the far right", () => {
  assert.match(
    mapOverviewStyles,
    /\.map-overview-hotspot-summary \.map-overview-card-heading\s*\{[^}]*display:\s*flex;[^}]*align-items:\s*center;[^}]*justify-content:\s*space-between;/,
  );
  assert.match(
    mapOverviewSource,
    /<h4>Possible nearby groups<\/h4>\s*<AnalyticsInfoTip label="About hotspot locations">/,
  );
});

test("selected hotspot details itemize pins from existing flag pages", async () => {
  const cluster = {
    cluster_id: 7,
    centroid: { lat: 13.95, lng: 121.11 },
    size: 2,
    log_ids: [101, 102],
    per_barangay: [{ barangay_name: "Barangay One", count: 2 }],
  };
  const pages = [];
  const getFlagsPage = async (params) => {
    pages.push(params);
    if (params.page === 1) {
      return {
        data: [{
          logID: 101,
          detectedName: "Corner Store",
          nearestLandmark: "Near the plaza",
          latitude: "13.951",
          longitude: "121.112",
        }],
        pages: 2,
      };
    }
    return {
      data: [{
        logID: 102,
        detectedName: "Market Stall",
        resolvedAddress: "Main road",
        latitude: 13.952,
        longitude: 121.113,
      }, {
        logID: 999,
        detectedName: "Unrelated pin",
      }],
      pages: 2,
    };
  };
  const pins = await fetchHotspotClusterPins(getFlagsPage, "token", cluster);
  assert.equal(pages.length, 2);
  assert.ok(pages.every((params) => (
    params.color === "Red"
    && params.origin === "detection"
    && params.registryLink === "unlinked"
  )));
  const details = hotspotClusterDetails(cluster, pins);
  assert.equal(details.clusterId, 7);
  assert.equal(details.location, "Barangay One");
  assert.equal(details.pinCount, 2);
  assert.deepEqual(details.pins, [
    {
      logID: 101,
      name: "Corner Store",
      landmark: "Near the plaza",
    },
    {
      logID: 102,
      name: "Market Stall",
      landmark: "Main road",
    },
  ]);
  assert.match(mapOverviewSource, /aria-label="Clear selected hotspot cluster"/);
  assert.match(mapOverviewSource, /onClick=\{clearSelectedCluster\}/);
  assert.match(mapOverviewSource, /setSelectedClusterId\(Number\(cluster\.cluster_id\)\)/);
  assert.match(mapOverviewSource, /className="map-overview-cluster-pin"[\s\S]*?navigate\(pinPath\)/);
  assert.doesNotMatch(mapOverviewSource, /<span>Pin #\$\{pin\.logID\}<\/span>/);
  assert.doesNotMatch(mapOverviewSource, /pin\.latitude\.toFixed|pin\.longitude\.toFixed/);
  assert.match(mapOverviewStyles, /\.map-overview-cluster-pin:not\(:disabled\):hover/);
  assert.match(mapOverviewStyles, /\.map-overview-cluster-pin:focus-visible/);
});

test("cluster pin navigation reuses Maps & Flags deep-link selection and map focus", () => {
  assert.equal(hotspotPinMapPath(325), "/map?flag=325");
  assert.equal(hotspotPinMapPath("325"), "/map?flag=325");
  assert.equal(hotspotPinMapPath(0), null);
  assert.equal(hotspotPinMapPath("invalid"), null);
  assert.match(mapPageSource, /searchParams\.get\("flag"\)/);
  assert.match(mapPageSource, /flags\.find\(f => String\(f\.logID \|\| f\.id\) === flagId\)/);
  assert.match(mapPageSource, /mapRef\.current\.panTo\(\{ lat: Number\(found\.latitude\), lng: Number\(found\.longitude\) \}\)/);
  assert.match(mapPageSource, /setModalFlag\(found\)/);
});

test("analytics scan summary includes the latest date, status, and stop reason", () => {
  assert.equal(analyticsDetectionScanSummary({
    date: "2026-10-29T04:30:00Z",
    status: "completed_with_gaps",
    stop_reason: "places_quota",
  }), "Last detection scan: 2026-10-29 · Completed With Gaps · Stop reason: Places quota");
  assert.equal(analyticsDetectionScanSummary(null),
    "Last detection scan: unavailable · Stop reason: unavailable");
});
