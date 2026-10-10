/**
 * Presentation helpers for the "API Usage & Limits" modal.
 *
 * These are pure functions so the wording, thresholds, and arithmetic that the
 * BPLO administrator actually reads can be unit tested without a DOM. The
 * component in `ApiUsageSettingsPanel.jsx` only renders what this module
 * returns.
 *
 * Deliberate exclusions (the modal was simplified for non-technical staff):
 *  - No SKU labels, per-SKU free-call allowances, or estimated USD figures.
 *    Pricing has never been verified against Google's current price sheet, so
 *    presenting it invited wrong conclusions.
 *  - No combined "requests remaining" total. Each API method has an
 *    independent budget, so a summed remainder implies a transferable pool
 *    that does not exist. Combined *used* counts are still shown because they
 *    answer "how much did we spend today/month", which is what an operator
 *    asks.
 *
 * This module changes nothing about quota enforcement — the backend
 * reservation logic is untouched.
 */

export const NEAR_LIMIT_PERCENT = 80;

/**
 * Administrator-facing names. One per REVELA feature, not per Google SKU.
 * `nearby_search_new` is the disabled alternate endpoint, so it is named
 * separately to avoid two identically titled cards.
 */
export const METHOD_LABELS = {
  text_search: "Business Lookup",
  place_details: "Map Pin Refresh",
  nearby_search_legacy: "Run Detection Requests",
  nearby_search_new: "Run Detection Requests (Alternate)",
  geocoding: "Address Lookup",
};

export function formatNumber(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return "0";
  return number.toLocaleString("en-US");
}

export function methodLabel(method) {
  if (!method) return "Requests";
  return METHOD_LABELS[method.method] ?? method.label ?? "Requests";
}

function capOf(method) {
  return method?.revela_app_cap ?? {};
}

/**
 * Compare one usage figure against its application cap.
 *
 * Returns a level rather than a raw percentage so the caller picks the colour:
 *   off  — no cap configured; the method is switched off
 *   full — the cap is reached
 *   near — at or above NEAR_LIMIT_PERCENT of the cap
 *   ok   — normal
 */
export function limitState(used, cap, exceeded = false) {
  const limit = Number(cap) || 0;
  const count = Number(used) || 0;
  if (limit <= 0) return { level: "off", percent: 0, remaining: 0 };
  if (exceeded || count >= limit) {
    return { level: "full", percent: 100, remaining: 0 };
  }
  const percent = Math.min(100, Math.round((count / limit) * 100));
  return {
    level: percent >= NEAR_LIMIT_PERCENT ? "near" : "ok",
    percent,
    remaining: Math.max(0, limit - count),
  };
}

/** Combined *used* counters only. Never a combined remaining allowance. */
export function summarizeUsage(methods = []) {
  return methods.reduce(
    (totals, method) => {
      const cap = capOf(method);
      return {
        usedToday: totals.usedToday + (Number(cap.used_today) || 0),
        usedMonth: totals.usedMonth + (Number(cap.used_month) || 0),
      };
    },
    { usedToday: 0, usedMonth: 0 },
  );
}

export function detectionScanSummary(detectionQuota) {
  const used = Number(detectionQuota?.used_this_month) || 0;
  const limit = Number(detectionQuota?.monthly_limit) || 0;
  return {
    used,
    limit,
    remaining: limit > 0 ? Math.max(0, limit - used) : 0,
    state: limitState(used, limit),
  };
}

/**
 * Plain-language warnings for the administrator. Only actionable states are
 * reported: a limit that is met, nearly met, or switched off entirely.
 */
export function buildUsageWarnings(methods = [], detectionQuota = null) {
  const warnings = [];

  for (const method of methods) {
    const cap = capOf(method);
    if (cap.disabled) continue;
    const label = methodLabel(method);
    const daily = limitState(cap.used_today, cap.daily_cap, cap.daily_quota_exceeded);
    const monthly = limitState(
      cap.used_month, cap.monthly_cap, cap.monthly_quota_exceeded,
    );

    if (daily.level === "full") {
      warnings.push({
        id: `${method.method}-day-full`,
        level: "danger",
        text: `${label} has used all of today's limit (`
          + `${formatNumber(cap.daily_cap)} requests). It resets at midnight.`,
      });
    } else if (daily.level === "near") {
      warnings.push({
        id: `${method.method}-day-near`,
        level: "warning",
        text: `${label} is close to today's limit: `
          + `${formatNumber(cap.used_today)} of ${formatNumber(cap.daily_cap)} `
          + "requests used.",
      });
    }

    if (monthly.level === "full") {
      warnings.push({
        id: `${method.method}-month-full`,
        level: "danger",
        text: `${label} has used its monthly limit of `
          + `${formatNumber(cap.monthly_cap)} requests.`,
      });
    } else if (monthly.level === "near") {
      warnings.push({
        id: `${method.method}-month-near`,
        level: "warning",
        text: `${label} is close to this month's limit: `
          + `${formatNumber(cap.used_month)} of `
          + `${formatNumber(cap.monthly_cap)} requests used.`,
      });
    }
  }

  const scans = detectionScanSummary(detectionQuota);
  if (scans.limit > 0 && scans.state.level === "full") {
    warnings.push({
      id: "detection-scans-full",
      level: "danger",
      text: `All ${formatNumber(scans.limit)} Run Detection scans for this `
        + "month have been used.",
    });
  } else if (scans.limit > 0 && scans.state.level === "near") {
    warnings.push({
      id: "detection-scans-near",
      level: "warning",
      text: "Run Detection scans are close to this month's limit: "
        + `${formatNumber(scans.used)} of ${formatNumber(scans.limit)} used.`,
    });
  }

  return warnings;
}

/**
 * Whether a limit is the shipped default or a stored custom value. Advanced
 * Settings must never blur the two, because "restore defaults" is destructive
 * and the administrator needs to know which one they are editing.
 */
export function describeLimitSource(field) {
  if (!field) return "Application default";
  if (field.source !== "admin_override") return "Application default";
  return `Custom setting (application default: ${formatNumber(field.baseline)})`;
}

export function isCustomLimit(field) {
  return field?.source === "admin_override";
}