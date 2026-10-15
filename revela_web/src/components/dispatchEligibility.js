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

import { isBlackDispatchUnlocked } from "./registryLadderPolicy.js";

export const INSPECTABLE_FLAG_COLORS = Object.freeze([
  "Red",
  "Yellow",
  "Orange",
  "Purple",
]);

/** Colours that are never dispatchable, whatever the flag's history. */
export const NON_DISPATCHABLE_FLAG_COLORS = Object.freeze(["Green", "Black"]);

export function canDispatchFlag(flag, { isAdmin } = {}) {
  if (!isAdmin) return false;
  // Black is the only colour with an exception, and only while a SUPER_ADMIN
  // grant is open. Green has none, so it stays blocked even on a re-dispatch.
  const blackUnlocked = flag?.color === "Black"
    && isBlackDispatchUnlocked(flag);
  if (NON_DISPATCHABLE_FLAG_COLORS.includes(flag?.color) && !blackUnlocked) {
    return false;
  }
  // Already-inspected or in-flight work may be re-dispatched.
  if (flag?.hasActiveInspection) return true;
  if (flag?.verificationStatus === "Verified") return true;
  if (flag?.color === "Black") return blackUnlocked;
  return INSPECTABLE_FLAG_COLORS.includes(flag?.color);
}

export function dispatchButtonLabel(flag) {
  if (flag?.color === "Black" && isBlackDispatchUnlocked(flag)) {
    return "Dispatch inspector (unlocked)";
  }
  if (flag?.hasActiveInspection) return "Undergoing Inspection";
  if (flag?.verificationStatus === "Verified") return "Re-dispatch inspector";
  return "Dispatch inspector";
}