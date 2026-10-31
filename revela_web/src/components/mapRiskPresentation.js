export function opsRiskTooltipLines(entry) {
  if (!entry || entry.ops_score == null || !Number.isFinite(Number(entry.ops_score))) return [];

  const lines = [
    `OPS priority score: ${Number(entry.ops_score).toFixed(1)}/100 (${entry.risk_level || "Unranked"} tier)`,
  ];
  if (entry.risk_score != null && Number.isFinite(Number(entry.risk_score))) {
    lines.push(
      `Risk component: ${Number(entry.risk_score).toFixed(1)}/100 (normalized weighted Red/Yellow/Black burden)`,
    );
  }
  return lines;
}

export function hotspotCircleSummary(cluster) {
  const size = Number(cluster.size) || 0;
  const radius = Number(cluster.radius_m) || 0;
  return {
    title: `Nearby flagged cluster (DBSCAN) #${Number(cluster.clusterID)}`,
    members: `${size} eligible geospatial record${size === 1 ? "" : "s"}`,
    radius: `${radius.toFixed(1)} m from centroid`,
    parameters: `Haversine eps = ${Number(cluster.eps_m ?? 50)} m · MinPts = ${Number(cluster.min_samples ?? 3)}`,
  };
}
