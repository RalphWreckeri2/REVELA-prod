import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import {
  analyticsDetectionScanSummary,
  fetchHotspotClusterPins,
  hotspotBadgeTier,
  hotspotCirclePath,
  hotspotOverlayRadius,
  hotspotClusterDetails,
  hotspotGroupLocation,
  hotspotGroupMapPath,
  hotspotTooltipLabel,
  matchesHotspotGroup,
  parseHotspotGroupParams,
  hotspotMethodNote,
  hotspotPinMapPath,
  hotspotPeriodLabel,
  hotspotRequestParams,
  hotspotResponseMatchesPeriod,
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
    totals: { clustered_points: 6, uncertain_points: 1, outside_boundary_count: 2 },
    population: { eligible_points: 8 },
  };
  assert.deepEqual(hotspotSummary(data), {
    clusterCount: 2,
    locationCount: 6,
    uncertainCount: 1,
    outsideBoundaryCount: 2,
    redFlaggedCount: 8,
  });
});

test("outside-boundary locations appear as a small panel note when present", () => {
  const stats = hotspotSummary({
    totals: { outside_boundary_count: 3 },
  });
  assert.equal(stats.outsideBoundaryCount, 3);
  assert.match(
    mapOverviewSource,
    /\{hotspotStats\.outsideBoundaryCount > 0 && \([\s\S]*?map-overview-hotspot-outside-boundary[\s\S]*?locations are outside the municipal boundary/,
  );
  assert.match(
    mapOverviewStyles,
    /\.map-overview-hotspot-outside-boundary\s*\{[^}]*font-size:\s*11px/,
  );
  assert.doesNotMatch(mapOverviewSource, /locations could not be assigned to a barangay/);
});

test("hotspot request is scoped only by the selected date preset", () => {
  assert.deepEqual(hotspotRequestParams("all"), { date_preset: "all" });
  assert.deepEqual(hotspotRequestParams("30days"), { date_preset: "30days" });
  assert.deepEqual(hotspotRequestParams("7days"), { date_preset: "7days" });
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

test("hotspot period labels, response guard, and current population counts match the dropdown", () => {
  assert.equal(hotspotPeriodLabel("all"), "All time");
  assert.equal(hotspotPeriodLabel("7days"), "Last 7 days");
  assert.match(mapOverviewSource, /Period: \{hotspotPeriodLabel\(datePreset\)\}/);
  assert.match(mapOverviewSource, /hotspotResponseMatchesPeriod\(data, hotspotRequest\.date_preset\)/);

  const currentResponses = [
    { date_preset: "all", population: { eligible_points: 200 } },
    { date_preset: "7days", population: { eligible_points: 66 } },
  ];
  assert.equal(hotspotResponseMatchesPeriod(currentResponses[0], "all"), true);
  assert.equal(hotspotSummary(currentResponses[0]).redFlaggedCount, 200);
  assert.equal(hotspotResponseMatchesPeriod(currentResponses[1], "7days"), true);
  assert.equal(hotspotSummary(currentResponses[1]).redFlaggedCount, 66);
  assert.equal(hotspotResponseMatchesPeriod(currentResponses[1], "all"), false);
  assert.equal(hotspotSummary(currentResponses[0]).outsideBoundaryCount, 0);
});

test("overlay radius and scan stop reason are presented clearly", () => {
  assert.equal(hotspotOverlayRadius(100), 110);
  assert.equal(hotspotOverlayRadius(0), 8);
  assert.deepEqual(hotspotScanNote({
    date: "2026-10-29T04:30:00Z",
    status: "partial",
    stop_reason: "request_limit",
  }), {
    text: "Last detection scan: Oct 29, 2026 · stopped early (request limit). Counts may be undercounted.",
    coverageIncomplete: true,
  });

  assert.deepEqual(hotspotScanNote({
    date: "2026-10-29T04:30:00Z",
    status: "partial",
    stop_reason: "places_quota",
  }), {
    text: "Last detection scan: Oct 29, 2026 · stopped early (Places quota). Counts may be undercounted.",
    coverageIncomplete: true,
  });
  assert.match(hotspotScanNote({
    date: "2026-10-29T04:30:00Z",
    status: "completed",
    stop_reason: "completed",
  }).text, /Last detection scan: Oct 29, 2026 · Completed\.$/);
  assert.equal(hotspotScanNote(null).text,
    "No detection scan data yet. Run a scan to identify possible groups.");
  assert.match(mapOverviewSource, /No nearby groups for this period\./);
  assert.match(mapOverviewSource, /Nearby groups are possible hotspots only; they do not confirm a violation\./);
});

test("hotspot method wording is limited to the information tooltip", () => {
  assert.equal(hotspotMethodNote({
    eps_m: 50,
    min_samples: 3,
  }),
  "Grouping method: DBSCAN with Haversine distance, eps 50 m, and MinPts 3.");
  assert.match(mapOverviewSource, /<AnalyticsInfoTip label="About hotspot locations">[\s\S]*?hotspotMethodNote\(hotspotData\?\.parameters_used\)/);
  assert.doesNotMatch(mapOverviewSource, /Haversine|MinPts/);
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

test("hotspot legend is gated by hotspot mode and the choropleth is muted", () => {
  assert.match(mapOverviewSource, /legendOpen && showHotspots && \([\s\S]*?data-hotspot-legend/);
  assert.match(mapOverviewSource, /legendOpen && !showHotspots && \(/);
  assert.match(mapOverviewSource, /fillColor: showHotspots\s*\?\s*isDark \? "#34d399" : "#166534"/);
  assert.match(mapOverviewSource, /fillOpacity: showHotspots \? \(isDark \? 0\.2 : 0\.16\) : 1/);
  assert.match(mapOverviewSource, /strokeColor: showHotspots\s*\?\s*isDark \? "#a7f3d0" : "#ffffff"/);
  assert.match(mapOverviewSource, /strokeWeight: showHotspots \? 1\.5/);
  assert.match(mapOverviewSource, /mapZoom >= 14/);
  assert.match(mapOverviewSource, /fillOpacity:\s*isDimmed\s*\?\s*0\.08\s*:\s*0\.25/);
  assert.match(mapOverviewSource, /strokeWeight:\s*isSelected\s*\?\s*4\s*:\s*2/);
  assert.match(mapOverviewStyles, /map-overview-hotspot-badge--small/);
  assert.match(mapOverviewStyles, /map-overview-hotspot-badge--medium/);
  assert.match(mapOverviewStyles, /map-overview-hotspot-badge--large/);
  assert.match(mapOverviewSource, /Hotspot group: 3 or more Red-flagged \(expired or unregistered\) locations within about 50 m\. Number = locations in the group\. Circle = area they cover\./);
});

test("hotspot panel lists all groups and supports selection and recovery states", () => {
  assert.match(
    mapOverviewSource,
    /showHotspots && \(\s*<>[\s\S]*?<h4>Possible hotspot groups<\/h4>[\s\S]*?hotspotClusters\.map\(\(cluster\) => \([\s\S]*?onClick=\{\(\) => selectHotspotCluster\(cluster\)\}/,
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
    /Group of \{Number\(cluster\.size\)\} · \{hotspotGroupLocation\(cluster\)\}/,
  );
  assert.match(mapOverviewSource, /No nearby groups for this period\./);
  assert.match(mapOverviewSource, /Show all time/);
  assert.match(mapOverviewSource, /No detection scan data yet\. A scan is needed to identify possible groups\./);
  assert.match(mapOverviewSource, /role="alert" className="map-overview-hotspot-error"/);
  assert.match(mapOverviewSource, />\s*Retry\s*</);
  assert.match(mapOverviewSource, /map-overview-hotspot-list-skeleton/);
  assert.match(mapOverviewStyles, /\.map-overview-hotspot-list-skeleton\s*\{[^}]*min-height:\s*390px/);
  assert.match(mapOverviewStyles, /map-overview-hotspot-group-list button\s*\{[^}]*min-height:\s*44px/);
  assert.match(mapOverviewSource, /aria-pressed=\{selectedClusterRequestKey === hotspotRequestKey[\s\S]*?Number\(cluster\.cluster_id\) === Number\(selectedClusterId\)\}/);
});

test("hotspot summary header keeps its info button aligned at the far right", () => {
  assert.match(
    mapOverviewStyles,
    /\.map-overview-hotspot-summary \.map-overview-card-heading\s*\{[^}]*display:\s*flex;[^}]*align-items:\s*center;[^}]*justify-content:\s*space-between;/,
  );
  assert.match(
    mapOverviewSource,
    /<h4>Possible hotspot groups<\/h4>\s*<AnalyticsInfoTip label="About hotspot locations">/,
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
            detectedDate: "2026-10-25T00:00:00Z",
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
        detectedDate: "2026-10-26T00:00:00Z",
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
  assert.equal(details.location, "Brgy. One");
  assert.equal(details.pinCount, 2);
  assert.deepEqual(details.pins, [
    {
      logID: 101,
      name: "Corner Store",
      address: "Near the plaza",
      detectedDate: "Oct 25, 2026",
    },
    {
      logID: 102,
      name: "Market Stall",
      address: "Main road",
      detectedDate: "Oct 26, 2026",
    },
  ]);
  assert.equal("centroid" in details, false);
  assert.equal("clusterId" in details, false);
  assert.doesNotMatch(JSON.stringify(details), /latitude|longitude|cluster center|clusterId/i);
  assert.match(mapOverviewSource, /Group of \{clusterDetail\.pinCount\} nearby locations/);
  assert.match(mapOverviewSource, /View on Maps &amp; Flags/);
  assert.match(mapOverviewSource, /Back to list/);
  assert.match(mapOverviewSource, /<article className="map-overview-cluster-pin"/);
  assert.doesNotMatch(mapOverviewSource, /Cluster center|Hotspot cluster #/);
  assert.match(mapOverviewStyles, /\.map-overview-cluster-pin\s*\{/);
});

test("hotspot group member list scrolls without shrinking rows into its button footer", () => {
  const listCss = mapOverviewStyles.match(
    /\.map-overview-cluster-pin-list\s*\{[^}]*\}/,
  )?.[0] || "";
  const itemCss = mapOverviewStyles.match(
    /\.map-overview-cluster-pin\s*\{[^}]*\}/,
  )?.[0] || "";
  const footerCss = mapOverviewStyles.match(
    /\.map-overview-hotspot-actions\s*\{[^}]*\}/,
  )?.[0] || "";

  assert.match(listCss, /overflow-y:\s*auto/);
  assert.match(listCss, /grid-auto-rows:\s*max-content/);
  assert.match(listCss, /scrollbar-gutter:\s*stable/);
  assert.match(listCss, /padding:[^;]*10px/);
  assert.match(itemCss, /min-height:\s*max-content/);
  assert.match(itemCss, /gap:\s*5px/);
  assert.match(itemCss, /padding:\s*12px 12px/);
  assert.match(footerCss, /flex:\s*0 0 auto/);
  assert.match(mapOverviewStyles, /max-height:\s*min\(50dvh,\s*420px\)/);
});

test("Maps & Flags hotspot members use the normal pin without an outer ring", () => {
  const markerBuilder = mapPageSource.slice(
    mapPageSource.indexOf("const buildMarkerContent"),
    mapPageSource.indexOf("el.innerHTML = innerHtml"),
  );
  assert.doesNotMatch(markerBuilder, /drop-shadow/);
  assert.match(markerBuilder, /<circle cx="12" cy="11" r="4\.5" fill="white"/);
  assert.doesNotMatch(mapPageSource, /hotspotRingMarkerDataUri|stroke="#111827" stroke-width="2\.5"|stroke="#ffffff" stroke-width="5"/);
  assert.match(markerBuilder, /flag\.matchStatus === "review"/);
  assert.match(markerBuilder, /isHotspotGroupMember/);
});

test("hotspot mode uses subtle green municipal fill and mode-specific clear borders", () => {
  assert.match(mapOverviewSource, /fillColor: showHotspots\s*\?\s*isDark \? "#34d399" : "#166534"/);
  assert.match(mapOverviewSource, /fillOpacity: showHotspots \? \(isDark \? 0\.2 : 0\.16\) : 1/);
  assert.match(mapOverviewSource, /strokeColor: showHotspots\s*\?\s*isDark \? "#a7f3d0" : "#ffffff"/);
  assert.match(mapOverviewSource, /strokeWeight: showHotspots \? 1\.5/);
});

test("group deep links cap IDs, use centroid and radius for large groups, and preserve pin links", () => {
  assert.equal(hotspotGroupMapPath({
    log_ids: [101, 102, 103],
  }), "/map?hotspot_ids=101%2C102%2C103");
  const parsedIds = parseHotspotGroupParams("?hotspot_ids=101%2C102%2C103");
  assert.deepEqual(parsedIds, {
    active: true,
    logIds: [101, 102, 103],
    center: null,
    radiusMeters: null,
  });
  assert.equal(matchesHotspotGroup({ id: 102 }, parsedIds), true);
  assert.equal(matchesHotspotGroup({ id: 999 }, parsedIds), false);

  const largeGroupPath = hotspotGroupMapPath({
    log_ids: Array.from({ length: 51 }, (_, index) => index + 1),
    centroid: { lat: 13.95, lng: 121.11 },
    radius_m: 75.5,
  });
  const largeGroup = parseHotspotGroupParams(largeGroupPath.slice(4));
  assert.deepEqual(largeGroup, {
    active: true,
    logIds: [],
    center: { lat: 13.95, lng: 121.11 },
    radiusMeters: 75.5,
  });
  assert.equal(matchesHotspotGroup({
    id: 200,
    source: "detection",
    color: "Red",
    latitude: 13.9501,
    longitude: 121.11,
  }, largeGroup), true);
  assert.equal(matchesHotspotGroup({
    id: 201,
    source: "registry",
    color: "Red",
    latitude: 13.9501,
    longitude: 121.11,
  }, largeGroup), false);

  assert.equal(hotspotPinMapPath(325), "/map?flag=325");
  assert.equal(hotspotPinMapPath("325"), "/map?flag=325");
  assert.equal(hotspotPinMapPath(0), null);
  assert.equal(hotspotPinMapPath("invalid"), null);
  assert.match(mapPageSource, /searchParams\.get\("flag"\)/);
  assert.match(mapPageSource, /flags\.find\(f => String\(f\.logID \|\| f\.id\) === flagId\)/);
  assert.match(mapPageSource, /mapRef\.current\.panTo\(\{ lat: Number\(found\.latitude\), lng: Number\(found\.longitude\) \}\)/);
  assert.match(mapPageSource, /setModalFlag\(found\)/);
  assert.match(mapPageSource, /matchesHotspotGroup\(flag, hotspotGroup\)/);
  assert.match(mapPageSource, /fitBounds\(bounds, \{ top: 80, right: 80, bottom: 80, left: 80 \}\)/);
  assert.match(mapPageSource, /const needsFit = !initialMunicipalFitRef\.current && !hotspotGroupActive/);
  assert.match(mapPageSource, /Showing \{visibleFlags\.length\.toLocaleString\(\)\} locations from a hotspot group/);
  assert.match(mapPageSource, /hotspotGroupMemberIds\.has\(Number\(flag\.id\)\)/);
  assert.doesNotMatch(mapPageSource, /hotspotRingMarkerDataUri|stroke="#111827" stroke-width="2\.5"|stroke="#ffffff" stroke-width="5"/);
});

test("size tiers, polygon labels, and shared Red flag color drive hotspot presentation", () => {
  assert.equal(hotspotBadgeTier(3), "small");
  assert.equal(hotspotBadgeTier(4), "small");
  assert.equal(hotspotBadgeTier(5), "medium");
  assert.equal(hotspotBadgeTier(9), "medium");
  assert.equal(hotspotBadgeTier(10), "large");
  assert.equal(hotspotGroupLocation({
    per_barangay: [{ barangay_name: "Barangay II", count: 3 }],
  }), "Brgy. II");
  assert.equal(hotspotGroupLocation({
    per_barangay: [
      { barangay_name: "Barangay II", count: 2 },
      { barangay_name: "Barangay III", count: 1 },
    ],
  }), "Several barangays");
  assert.equal(hotspotGroupLocation({
    per_barangay: [{ barangay_name: "Barangay II", count: 2 }],
    uncertain_count: 1,
  }), "Location unclear");
  assert.equal(hotspotTooltipLabel({
    size: 3,
    per_barangay: [{ barangay_name: "Barangay II", count: 3 }],
  }), "3 locations · Brgy. II");
  assert.equal(hotspotCirclePath({ lat: 13.95, lng: 121.11 }, 50).length, 65);
  assert.match(mapOverviewSource, /fillColor: FLAG_COLORS\.Red\.marker/);
  assert.match(mapPageSource, /import \{ FLAG_COLORS, defaultColor \} from "\.\.\/components\/flagColors"/);
  assert.match(mapOverviewSource, /import \{ FLAG_COLORS \} from "\.\/flagColors"/);
  assert.match(mapOverviewSource, /Number\(second\.size\) - Number\(first\.size\)/);
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
