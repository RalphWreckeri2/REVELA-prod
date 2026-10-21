// Interview-derived default; input coverage must never change these weights.
export const DEFAULT_WLC_WEIGHTS = Object.freeze({ w1_risk: 68, w2_sector: 7, w3_distance: 25 });

export function wlcPolicyError(config) {
  const weights = [config.w1_risk, config.w2_sector, config.w3_distance];
  if (weights.some(value => typeof value !== "number" || !Number.isFinite(value) || value < 0 || value > 100)) {
    return "Each WLC weight must be a number between 0 and 100.";
  }
  if (Math.abs(weights.reduce((sum, value) => sum + value, 0) - 100) > 0.000001) {
    return "WLC weights must total 100%.";
  }
  for (const [key, limit] of [["bplo_lat", 90], ["bplo_lng", 180]]) {
    if (key in config && (typeof config[key] !== "number" || !Number.isFinite(config[key]) || Math.abs(config[key]) > limit)) {
      return "BPLO coordinates must be valid latitude and longitude values.";
    }
  }
  return "";
}

export function registryFlagRateLabel(rate) {
  return typeof rate === "number" && Number.isFinite(rate) && rate >= 0 && rate <= 100
    ? `${rate.toFixed(1)}%` : "N/A";
}

export function hasDispatchableWlcTargets(row) {
  return (row.dispatchable_count ?? ((row.red_count || 0) + (row.yellow_count || 0))) > 0;
}

export function wlcEligibilityLabel(row) {
  if (hasDispatchableWlcTargets(row)) return `${row.dispatchable_count ?? ((row.red_count || 0) + (row.yellow_count || 0))} eligible for new dispatch`;
  if (!row.flagged_count) return "No active flags";
  if (!(row.red_count || row.yellow_count)) return "Black-only — administrative review, no inspection dispatch";
  return "Already assigned — no new dispatchable targets";
}

export function opsRadarData(rankings, formatName = name => name) {
  return (rankings || []).filter(row => row.flagged_count > 0).slice(0, 8).map(row => ({
    barangay: formatName(row.barangayName),
    OPS: row.ops_score,
    Risk: row.risk_score,
    Proximity: row.proximity_score,
  }));
}

export function rebalanceWlcWeight(config, changedKey, value) {
  // Linked sliders rebalance only after an explicit user edit, never because
  // sector data is unavailable. The saved/default weights are used as-is.
  const amount = Math.min(100, Math.max(0, Math.round(Number(value) || 0)));
  const next = { ...config, [changedKey]: amount };
  const others = ["w1_risk", "w2_sector", "w3_distance"]
    .filter(key => key !== changedKey);
  if (!others.length) return next;
  const remaining = 100 - next[changedKey];
  const previous = others.reduce((sum, key) => sum + (config[key] || 0), 0);
  let distributed = 0;
  others.forEach((key, index) => {
    next[key] = index === others.length - 1 ? remaining - distributed
      : Math.round(previous ? (config[key] / previous) * remaining : remaining / others.length);
    distributed += next[key];
  });
  return next;
}
