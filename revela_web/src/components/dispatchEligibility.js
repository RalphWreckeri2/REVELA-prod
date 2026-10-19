/**
 * Which map flags an admin may dispatch an inspection to.
 *
 * Extracted from MapPage so the rule is testable without a DOM, matching the
 * existing policy-module convention (see locationReviewPolicy.js).
 *
 * The server enforces the same rule in assign_inspection, decided on the
 * effective colour the Map renders. This is the UI half of that contract and
 * must not drift from it:
 *   Allowed: Red, Yellow, Orange, Purple
 *   Blocked: Green (registered and compliant), Black (permanent offender)
 *   Except:  Black is dispatchable while a SUPER_ADMIN has granted exactly one
 *            inspection (blackDispatchUnlocked). The business stays Black; the
 *            grant is spent when that inspection is verified, cancelled or
 *            sent back. See registryLadderPolicy.js.
 */

export const INSPECTABLE_FLAG_COLORS = Object.freeze([
  "Red",
  "Yellow",
  "Orange",
  "Purple",
]);

/** Colours that are never dispatchable, whatever the flag's history. */
export const NON_DISPATCHABLE_FLAG_COLORS = Object.freeze(["Green", "Black"]);

const KNOWN_FLAG_COLORS = new Set([
  ...INSPECTABLE_FLAG_COLORS,
  ...NON_DISPATCHABLE_FLAG_COLORS,
]);

export function normalizeDispatchColor(rawColor) {
  const normalized = String(rawColor ?? "")
    .trim()
    .toLowerCase();
  if (!normalized) return "Unknown";
  const color = normalized.charAt(0).toUpperCase() + normalized.slice(1);
  return KNOWN_FLAG_COLORS.has(color) ? color : "Unknown";
}

export function canDispatchFlag(flag, { isAdmin } = {}) {
  if (!isAdmin) return false;
  if (NON_DISPATCHABLE_FLAG_COLORS.includes(flag?.color)) {
    return false;
  }
  // Already-inspected or in-flight work may be re-dispatched.
  if (flag?.hasActiveInspection) return true;
  if (flag?.verificationStatus === "Verified") return true;
  return INSPECTABLE_FLAG_COLORS.includes(flag?.color);
}

export function dispatchButtonLabel(flag) {
  if (flag?.color === "Black") return "Black businesses cannot be dispatched";
  if (flag?.hasActiveInspection) return "Undergoing Inspection";
  if (flag?.verificationStatus === "Verified") return "Re-dispatch inspector";
  return "Dispatch inspector";
}

export function canReassignInspection(report, { isAdmin } = {}) {
  return (
    isAdmin && ["Assigned", "Submitted"].includes(report?.verificationStatus)
  );
}

/** Inspection details use API flagColor, not Map's normalized color key. */
export function canFollowUpInspection(report, { isAdmin } = {}) {
  if (!isAdmin || report?.verificationStatus !== "Verified") return false;
  if (report.flagColor !== "Orange") return false;
  const black =
    report.flagColor === "Black" ||
    Number(report.blackLocked) === 1 ||
    ["Revoked", "Blacklisted"].includes(report.applicationStatus);
  if (black) return false;
  return true;
}
