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
  return {
    text: `Last detection scan: ${date} · ${status}`,
    coverageIncomplete,
  };
}
