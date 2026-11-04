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

function finiteCount(value) {
  const count = Number(value);
  return Number.isFinite(count) ? count : 0;
}

/**
 * Split a barangay row into dispatchable Red/Yellow targets and the flags that
 * cannot be dispatched.  Dispatchable counts exclude records with Assigned,
 * Reassigned or In Progress inspections.  Black is risk context only.
 */
export function dispatchableBreakdown(row = {}) {
  const totalRed = finiteCount(row.red_count);
  const totalYellow = finiteCount(row.yellow_count);
  const totalBlack = finiteCount(row.black_count);
  const hasDispatchableRed = row.dispatchable_red_count !== undefined && row.dispatchable_red_count !== null;
  const hasDispatchableYellow = row.dispatchable_yellow_count !== undefined && row.dispatchable_yellow_count !== null;
  let red = hasDispatchableRed ? finiteCount(row.dispatchable_red_count) : null;
  let yellow = hasDispatchableYellow ? finiteCount(row.dispatchable_yellow_count) : null;
  const dispatchable = row.dispatchable_count !== undefined && row.dispatchable_count !== null
    ? finiteCount(row.dispatchable_count)
    : (red ?? totalRed) + (yellow ?? totalYellow);

  // Older callers only send dispatchable_count plus totals.  Keep the visible
  // breakdown internally consistent instead of showing a larger Red/Yellow sum.
  if (red === null && yellow === null) {
    red = Math.min(totalRed, dispatchable);
    yellow = Math.min(totalYellow, Math.max(0, dispatchable - red));
  } else if (red === null) {
    red = Math.max(0, dispatchable - yellow);
  } else if (yellow === null) {
    yellow = Math.max(0, dispatchable - red);
  }

  return {
    dispatchable,
    red,
    yellow,
    black: totalBlack,
    totalRed,
    totalYellow,
    totalBlack,
    assignedRed: Math.max(0, totalRed - red),
    assignedYellow: Math.max(0, totalYellow - yellow),
  };
}

export function hasDispatchableWlcTargets(row) {
  return dispatchableBreakdown(row).dispatchable > 0;
}

export function wlcEligibilityLabel(row) {
  const { dispatchable, red, yellow, black } = dispatchableBreakdown(row);
  if (dispatchable > 0) {
    return `Red ${red} + Yellow ${yellow} = ${dispatchable} eligible for new dispatch${black > 0 ? ` · ${black} Black for administrative review` : ""}`;
  }
  if (!row.flagged_count) return "No active flags";
  if (!(Number(row.red_count || 0) + Number(row.yellow_count || 0))) {
    return `${black} Black-only — administrative review, no inspection dispatch`;
  }
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
