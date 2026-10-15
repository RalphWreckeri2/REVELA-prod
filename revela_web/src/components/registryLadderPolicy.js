/**
 * Which registry-page actions an admin may take, and which map flags may be
 * dispatched.
 *
 * Extracted so the rules are testable without a DOM, following the existing
 * policy-module convention (see dispatchEligibility.js, locationReviewPolicy.js).
 *
 * The server enforces the same rules and is the authority:
 *   clear_warning            POST /api/registry/<id>/clear-warning      Admin
 *   unlock_black_dispatch    POST /api/registry/<id>/unlock-black-dispatch
 *                                                            SUPER_ADMIN only
 *   assign_inspection        the eligibility gate, on the effective colour
 *
 * These helpers only decide whether to SHOW a button. A stale "false" hides a
 * button that would have worked; a stale "true" shows one that comes back 409.
 * The latter is why the server refuses rather than trusting the client.
 */

/** Roles that may use the registry page's enforcement actions. */
export const ADMIN_ROLES = Object.freeze(["Admin", "SUPER_ADMIN"]);

/**
 * "Clear Warning" is offered only when the server would accept it.
 *
 * @param business  a registry row as the Registry page holds it
 * @param role      the signed-in user's role
 */
export function canClearWarning(business, role) {
  if (!ADMIN_ROLES.includes(role)) return false;
  if (!business) return false;
  if (isBlackLocked(business)) return false;
  return warningLevel(business) > 0;
}

/**
 * "Unlock for Inspection" is SUPER_ADMIN only, Black rows only, and never
 * offered twice for the same grant.
 */
export function canUnlockBlackDispatch(business, role) {
  if (role !== "SUPER_ADMIN") return false;
  if (!business) return false;
  if (!isBlackLocked(business)) return false;
  return !isBlackDispatchUnlocked(business);
}

export function warningLevel(business) {
  const raw = Number(business?.warningLevel ?? 0);
  return Number.isFinite(raw) ? raw : 0;
}

export function isBlackLocked(business) {
  // blackLocked wins the ladder precedence, so this is the single source of
  // "this business is Black" on the client. A Black colour alone is not
  // enough: Revoked and Blacklisted permits are also Black but are not locked.
  return Boolean(business?.blackLocked);
}

export function isBlackDispatchUnlocked(business) {
  return Boolean(business?.blackDispatchUnlocked);
}

/**
 * Why the Clear Warning button is hidden, for a tooltip or a caption.
 * Returns null when the action is available.
 */
export function clearWarningBlockedReason(business, role) {
  if (canClearWarning(business, role)) return null;
  if (!ADMIN_ROLES.includes(role)) return "Admins only";
  if (!business) return "No business selected";
  if (isBlackLocked(business)) {
    return "This business is Black locked. Only a SUPER_ADMIN unlock applies.";
  }
  if (warningLevel(business) <= 0) return "There is no warning to clear";
  return "Not available";
}

/**
 * Black is dispatchable only while a SUPER_ADMIN grant is open.
 *
 * Mirrors assign_inspection: the gate reads the effective colour, and Black
 * passes only when blackDispatchUnlocked is set. A missing field is treated
 * as not unlocked, which keeps Black blocked on an un-migrated database.
 */
export function isBlackDispatchAllowed(flag) {
  if (flag?.color !== "Black") return true;
  return isBlackDispatchUnlocked(flag);
}
