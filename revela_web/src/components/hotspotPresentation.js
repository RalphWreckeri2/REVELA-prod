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

export function hotspotClusterDetails(cluster, pinRows = []) {
  const memberIds = new Set(hotspotClusterPinIds(cluster));
  const pinsById = new Map(
    pinRows
      .filter((pin) => pin?.logID != null && memberIds.has(Number(pin.logID)))
      .map((pin) => [Number(pin.logID), pin]),
  );
  const barangays = (cluster?.per_barangay || [])
    .map((row) => row.barangay_name)
    .filter(Boolean);

  return {
    clusterId: cluster?.cluster_id,
    location: barangays.length
      ? [...new Set(barangays)].join(", ")
      : `Near ${Number(cluster?.centroid?.lat).toFixed(5)}, ${Number(cluster?.centroid?.lng).toFixed(5)}`,
    pinCount: Number(cluster?.size) || memberIds.size,
    centroid: cluster?.centroid || null,
    pins: [...memberIds].map((logID) => {
      const pin = pinsById.get(logID);
      return {
        logID,
        name: pin?.detectedName || `Detection pin #${logID}`,
        landmark: pin?.resolvedAddress || pin?.nearestLandmark || "",
        latitude: pin?.latitude == null ? null : Number(pin.latitude),
        longitude: pin?.longitude == null ? null : Number(pin.longitude),
        detailsAvailable: Boolean(pin),
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

export function hotspotSummary(data, selectedBarangayId = null) {
  const clusters = Array.isArray(data?.clusters) ? data.clusters : [];
  if (selectedBarangayId != null) {
    const barangayId = Number(selectedBarangayId);
    let clusterCount = 0;
    let locationCount = 0;
    for (const cluster of clusters) {
      const membership = cluster.per_barangay?.find(
        (row) => Number(row.barangay_id) === barangayId,
      );
      if (membership && Number(membership.count) > 0) {
        clusterCount += 1;
        locationCount += Number(membership.count);
      }
    }
    return {
      clusterCount,
      locationCount,
      uncertainCount: 0,
    };
  }
  return {
    clusterCount: clusters.length,
    locationCount: Number(data?.totals?.clustered_points || 0),
    uncertainCount: Number(data?.totals?.uncertain_points || 0),
  };
}

export function hotspotMethodNote(parameters, mapView) {
  if (!parameters) return "";
  const polygonMeasure = mapView === "inspections"
    ? "inspection counts"
    : "registered-business counts";
  return `DBSCAN groups eligible effective-Red detection pins (Haversine eps ${Number(parameters.eps_m)} m; MinPts ${Number(parameters.min_samples)}). Orange circles show hotspot groups; polygon fills show ${polygonMeasure}, not OPS tiers.`;
}

export function hotspotOverlayRadius(radiusMeters) {
  const radius = Number(radiusMeters) || 0;
  return radius + Math.max(8, radius * 0.1);
}

export function hotspotScanNote(lastDetectionRun) {
  if (!lastDetectionRun) {
    return {
      text: "Last detection scan: unavailable",
      coverageIncomplete: false,
    };
  }

  const date = String(lastDetectionRun.date || "").slice(0, 10) || "unknown date";
  const status = String(lastDetectionRun.status || "unknown")
    .replaceAll("_", " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
  const coverageIncomplete = ["partial", "completed with gaps"].includes(
    status.toLowerCase(),
  );
  const reasonLabels = {
    completed: "Completed",
    work_budget: "Work budget",
    places_quota: "Places quota",
    api_error: "API error",
    request_limit: "Request limit",
  };
  const rawReason = lastDetectionRun.stop_reason;
  const stopReason = reasonLabels[rawReason]
    || (rawReason
      ? String(rawReason).replaceAll("_", " ")
      : "reason not recorded");
  const stopDetail = status.toLowerCase() === "partial"
    ? ` · Stop reason: ${stopReason}`
    : "";
  return {
    text: `Last detection scan: ${date} · ${status}${stopDetail}`,
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
