import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import {
  hotspotOverlayRadius,
  hotspotRequestParams,
  hotspotScanNote,
  hotspotSummary,
} from "./hotspotPresentation.js";

const mapOverviewSource = readFileSync(
  new URL("./MapOverview.jsx", import.meta.url),
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
