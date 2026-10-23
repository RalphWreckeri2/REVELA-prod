/**
 * Which registry-page actions an admin may take, and which map flags may be
 * dispatched.
 *
 * Extracted so the rules are testable without a DOM, following the existing
 * policy-module convention (see dispatchEligibility.js, locationReviewPolicy.js).
 *
 * The server enforces the same rules and is the authority:
 *   clear_warning            POST /api/registry/<id>/clear-warning      Admin
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
  if (business.flagColor === "Black") return false;
  if (Number(business.hasNonVerifiedInspection) > 0) return false;
  return warningLevel(business) > 0;
}

export function canClearInspectionWarning(report, role) {
  if (
    report?.inspectionResult !== "Orange" ||
    report?.verificationStatus !== "Verified" ||
    Number(report.hasNonVerifiedInspection) !== 0 ||
    !ADMIN_ROLES.includes(role)
  )
    return false;
  if (report.businessID != null) return canClearWarning(report, role);

  return (
    report.logID != null &&
    report.flagColor === "Orange" &&
    warningLevel(report) > 0 &&
    !isBlackLocked(report)
  );
}

/** Refresh the open detail before notifying the Map of the successful change. */
export async function clearInspectionWarning({
  report,
  role,
  reason,
  token,
  businessID,
  registryReviewToken,
  confirmEstablishment,
  request,
  refresh,
  onChanged,
}) {
  if (!canClearInspectionWarning(report, role))
    throw new Error("This inspection's warning cannot be cleared.");
  const isPinSubject = report.businessID == null;
  if (
    isPinSubject &&
    (!businessID || !registryReviewToken || confirmEstablishment !== true)
  )
    throw new Error("Review and confirm the official Business ID first.");
  const subjectId = isPinSubject ? report.logID : report.businessID;
  const result = await request(
    subjectId,
    reason,
    token,
    isPinSubject ? "geospatial_log" : "business",
    isPinSubject
      ? {
          reportID: report.reportID,
          businessID,
          registryReviewToken,
          confirmEstablishment: true,
        }
      : {},
  );
  await refresh();
  onChanged?.(result);
  return result;
}

/** Black dispatch unlocks are no longer supported. */
export function canUnlockBlackDispatch() {
  return false;
}

export function warningLevel(business) {
  const raw = Number(business?.warningLevel ?? 0);
  return Number.isFinite(raw) ? raw : 0;
}

export function isBlackLocked(business) {
  return (
    Number(business?.blackLocked) === 1 ||
    ["Revoked", "Blacklisted"].includes(business?.applicationStatus)
  );
}

export function isBlackDispatchUnlocked() {
  return false;
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
    return "Warnings cannot be cleared while this business is Black locked.";
  }
  if (Number(business.hasNonVerifiedInspection) > 0)
    return "An inspection is not yet Verified";
  if (warningLevel(business) <= 0) return "There is no warning to clear";
  return "Not available";
}

/** Black is never dispatchable, regardless of legacy grant fields. */
export function isBlackDispatchAllowed(flag) {
  return flag?.color !== "Black";
}
