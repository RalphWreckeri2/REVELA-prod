const HOTSPOT_GROUP_LOG_ID_LIMIT = 50;
const HOTSPOT_EARTH_RADIUS_M = 6_371_008.8;

export function hotspotViewTransition(enabled) {
  return {
    showHotspots: enabled,
    mapView: enabled ? "registered" : null,
  };
}

export function hotspotClusterPinIds(cluster) {
  return Array.isArray(cluster?.log_ids)
    ? cluster.log_ids.map(Number).filter(Number.isFinite)
    : [];
}

export function hotspotPinMapPath(logID) {
  const pinId = Number(logID);
  return Number.isSafeInteger(pinId) && pinId > 0
    ? `/map?flag=${encodeURIComponent(pinId)}`
    : null;
}

export function hotspotGroupMapPath(cluster) {
  const logIds = hotspotClusterPinIds(cluster);
  if (!logIds.length) return null;

  const params = new URLSearchParams();
  if (logIds.length <= HOTSPOT_GROUP_LOG_ID_LIMIT) {
    params.set("hotspot_ids", logIds.join(","));
  } else {
    const lat = Number(cluster?.centroid?.lat);
    const lng = Number(cluster?.centroid?.lng);
    const radius = Number(cluster?.radius_m);
    if (!Number.isFinite(lat) || !Number.isFinite(lng) || !Number.isFinite(radius) || radius < 0) {
      return null;
    }
    params.set("hotspot_lat", String(lat));
    params.set("hotspot_lng", String(lng));
    params.set("hotspot_radius_m", String(radius));
  }
  return `/map?${params.toString()}`;
}

export function parseHotspotGroupParams(search = "") {
  const params = new URLSearchParams(search);
  const rawIds = params.get("hotspot_ids");
  if (rawIds) {
    const logIds = [...new Set(rawIds.split(",")
      .map(Number)
      .filter((logID) => Number.isSafeInteger(logID) && logID > 0))];
    if (logIds.length > 0 && logIds.length <= HOTSPOT_GROUP_LOG_ID_LIMIT) {
      return { active: true, logIds, center: null, radiusMeters: null };
    }
  }

  const lat = Number(params.get("hotspot_lat"));
  const lng = Number(params.get("hotspot_lng"));
  const radiusMeters = Number(params.get("hotspot_radius_m"));
  if (
    params.has("hotspot_lat")
    && params.has("hotspot_lng")
    && params.has("hotspot_radius_m")
    && Number.isFinite(lat)
    && Number.isFinite(lng)
    && Number.isFinite(radiusMeters)
    && radiusMeters >= 0
  ) {
    return {
      active: true,
      logIds: [],
      center: { lat, lng },
      radiusMeters,
    };
  }

  return { active: false, logIds: [], center: null, radiusMeters: null };
}

export function matchesHotspotGroup(flag, group) {
  if (!group?.active) return true;
  const flagId = Number(flag?.logID ?? flag?.id);
  if (group.logIds.length) return group.logIds.includes(flagId);

  if (
    flag?.source !== "detection"
    || flag?.color !== "Red"
    || flag?.registryLinked
    || flag?.businessID != null
    || flag?.latitude == null
    || flag?.longitude == null
  ) {
    return false;
  }

  const distance = hotspotDistanceMeters(
    group.center,
    { lat: Number(flag.latitude), lng: Number(flag.longitude) },
  );
  return Number.isFinite(distance) && distance <= group.radiusMeters + 2;
}

function hotspotDistanceMeters(first, second) {
  const lat1 = Number(first?.lat);
  const lng1 = Number(first?.lng);
  const lat2 = Number(second?.lat);
  const lng2 = Number(second?.lng);
  if (![lat1, lng1, lat2, lng2].every(Number.isFinite)) return Number.NaN;

  const radians = Math.PI / 180;
  const deltaLat = (lat2 - lat1) * radians;
  const deltaLng = (lng2 - lng1) * radians;
  const haversine = (
    Math.sin(deltaLat / 2) ** 2
    + Math.cos(lat1 * radians) * Math.cos(lat2 * radians)
      * Math.sin(deltaLng / 2) ** 2
  );
  return 2 * HOTSPOT_EARTH_RADIUS_M * Math.asin(Math.sqrt(haversine));
}

export function hotspotCirclePath(center, radiusMeters, pointCount = 64) {
  const lat = Number(center?.lat);
  const lng = Number(center?.lng);
  const radius = Number(radiusMeters);
  if (![lat, lng, radius].every(Number.isFinite) || radius < 0 || pointCount < 8) {
    return [];
  }

  const angularDistance = radius / HOTSPOT_EARTH_RADIUS_M;
  const latitude = lat * Math.PI / 180;
  const longitude = lng * Math.PI / 180;
  return Array.from({ length: pointCount + 1 }, (_, index) => {
    const bearing = 2 * Math.PI * index / pointCount;
    const pointLatitude = Math.asin(
      Math.sin(latitude) * Math.cos(angularDistance)
      + Math.cos(latitude) * Math.sin(angularDistance) * Math.cos(bearing),
    );
    const pointLongitude = longitude + Math.atan2(
      Math.sin(bearing) * Math.sin(angularDistance) * Math.cos(latitude),
      Math.cos(angularDistance) - Math.sin(latitude) * Math.sin(pointLatitude),
    );
    return {
      lat: pointLatitude * 180 / Math.PI,
      lng: pointLongitude * 180 / Math.PI,
    };
  });
}

export function hotspotBadgeTier(size) {
  const count = Number(size) || 0;
  if (count >= 10) return "large";
  if (count >= 5) return "medium";
  return "small";
}

export function hotspotGroupLocation(cluster) {
  const barangays = [...new Set((cluster?.per_barangay || [])
    .filter((row) => Number(row.count) > 0)
    .map((row) => row.barangay_name)
    .filter(Boolean))];
  if (Number(cluster?.uncertain_count) > 0 || barangays.length === 0) {
    return "Location unclear";
  }
  if (barangays.length > 1) return "Several barangays";
  return `Brgy. ${barangays[0].replace(/^Barangay\s+/i, "")}`;
}

export function hotspotTooltipLabel(cluster) {
  const count = Number(cluster?.size) || hotspotClusterPinIds(cluster).length;
  return `${count} locations · ${hotspotGroupLocation(cluster)}`;
}

function formatHotspotDate(value) {
  const date = String(value || "").slice(0, 10);
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(date);
  if (!match) return "Date unavailable";
  return new Date(Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3])))
    .toLocaleDateString("en-US", {
      timeZone: "UTC",
      month: "short",
      day: "numeric",
      year: "numeric",
    });
}

export function hotspotClusterDetails(cluster, pinRows = []) {
  const memberIds = new Set(hotspotClusterPinIds(cluster));
  const pinsById = new Map(
    pinRows
      .filter((pin) => pin?.logID != null && memberIds.has(Number(pin.logID)))
      .map((pin) => [Number(pin.logID), pin]),
  );
  return {
    location: hotspotGroupLocation(cluster),
    pinCount: Number(cluster?.size) || memberIds.size,
    pins: [...memberIds].map((logID) => {
      const pin = pinsById.get(logID);
      return {
        logID,
        name: pin?.detectedName || "Unnamed detection",
        address: pin?.resolvedAddress || pin?.address || pin?.nearestLandmark || "Address or landmark unavailable",
        detectedDate: formatHotspotDate(pin?.detectedDate || pin?.detected_date),
      };
    }),
  };
}

export async function fetchHotspotClusterPins(getFlagsPage, token, cluster, signal) {
  const memberIds = new Set(hotspotClusterPinIds(cluster));
  if (!memberIds.size) return [];

  const rows = [];
  let page = 1;
  let pages;
  do {
    const result = await getFlagsPage({
      page,
      limit: 1000,
      color: "Red",
      origin: "detection",
      registryLink: "unlinked",
      signal,
    }, token);
    rows.push(...(Array.isArray(result) ? result : (result?.data || [])));
    pages = result?.pages ?? 1;
    page += 1;
  } while (page <= pages);

  return rows.filter((row) => memberIds.has(Number(row.logID)));
}

export function hotspotRequestParams(datePreset) {
  return { date_preset: datePreset || "all" };
}

export function hotspotPeriodLabel(datePreset) {
  return ({
    all: "All time",
    year: "This year",
    "30days": "Last 30 days",
    "7days": "Last 7 days",
  })[datePreset] || "All time";
}

export function hotspotResponseMatchesPeriod(data, datePreset) {
  return data?.date_preset === (datePreset || "all");
}

export function hotspotSummary(data) {
  const clusters = Array.isArray(data?.clusters) ? data.clusters : [];
  return {
    clusterCount: clusters.length,
    locationCount: Number(data?.totals?.clustered_points || 0),
    uncertainCount: Number(data?.totals?.uncertain_points || 0),
    outsideBoundaryCount: Number(data?.totals?.outside_boundary_count || 0),
    redFlaggedCount: Number(data?.population?.eligible_points || 0),
  };
}

export function hotspotMethodNote(parameters) {
  if (!parameters) return "";
  return `Grouping method: DBSCAN with Haversine distance, eps ${Number(parameters.eps_m)} m, and MinPts ${Number(parameters.min_samples)}.`;
}

export function hotspotOverlayRadius(radiusMeters) {
  const radius = Number(radiusMeters) || 0;
  return radius + Math.max(8, radius * 0.1);
}

export function hotspotScanNote(lastDetectionRun) {
  if (!lastDetectionRun) {
    return {
      text: "No detection scan data yet. Run a scan to identify possible groups.",
      coverageIncomplete: false,
    };
  }

  const date = formatHotspotDate(lastDetectionRun.date);
  const status = String(lastDetectionRun.status || "").toLowerCase();
  const reasonLabels = {
    work_budget: "work budget",
    places_quota: "Places quota",
    api_error: "API error",
    request_limit: "request limit",
  };
  const rawReason = String(lastDetectionRun.stop_reason || "").toLowerCase();
  const completed = status === "completed" || rawReason === "completed";
  const reason = reasonLabels[rawReason]
    || (rawReason ? rawReason.replaceAll("_", " ") : "reason not recorded");
  const coverageIncomplete = !completed;
  const statusText = completed
    ? "Completed."
    : `stopped early (${reason}). Counts may be undercounted.`;
  return {
    text: `Last detection scan: ${date} · ${statusText}`,
    coverageIncomplete,
  };
}

export function analyticsDetectionScanSummary(lastDetectionRun) {
  if (!lastDetectionRun) {
    return "Last detection scan: unavailable · Stop reason: unavailable";
  }
  const date = String(lastDetectionRun.date || "").slice(0, 10) || "unknown date";
  const status = String(lastDetectionRun.status || "unknown")
    .replaceAll("_", " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
  const reasonLabels = {
    completed: "Completed normally",
    completed_with_gaps: "Coverage gaps",
    work_budget: "Work budget",
    places_quota: "Places quota",
    api_error: "API error",
    request_limit: "Request limit",
  };
  const rawReason = lastDetectionRun.stop_reason;
  const stopReason = reasonLabels[rawReason]
    || (rawReason ? String(rawReason).replaceAll("_", " ") : "not recorded");
  return `Last detection scan: ${date} · ${status} · Stop reason: ${stopReason}`;
}
