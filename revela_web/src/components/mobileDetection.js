/**
 * Device-access policy for the REVELA Admin Web Portal.
 *
 * Purpose: the administrative dashboard is not usable on a phone-sized screen.
 * This is a *usability* guard, not authentication or authorization. It must
 * never be relied on to decide whether a user is permitted to sign in -- role
 * checks, JWT validation and session policy remain the only authorities.
 *
 * Why not just the user agent:
 *   On iPadOS, every browser (Safari included, unless the user enables
 *   "Request Desktop Website") sends `Mobile/15E148`, so a naive /Mobile/ test
 *   blocks every iPad. Chromium additionally reports `userAgentData.mobile ===
 *   true` on iPad. Matching the user agent alone therefore locked tablets out.
 *
 * Why not just viewport width:
 *   Viewport widths overlap. An iPhone 16 Pro Max in landscape is 932px wide,
 *   which is wider than an iPad in portrait (820px). Width alone cannot tell
 *   them apart.
 *
 * The policy therefore combines two signals:
 *   1. The *short side* of the viewport -- the dimension that actually decides
 *      whether the dashboard fits. Phones stay under ~440px on their short
 *      side in either orientation; the smallest common tablet (iPad mini) is
 *      744px. That is a clean split, unlike width.
 *   2. A tablet-aware user-agent check, used to catch a phone that inflates its
 *      layout viewport by requesting the desktop site. Tablets always win this
 *      check, so no tablet can be blocked for carrying a "Mobile" token.
 *
 * LIMITATION: none of this is a security boundary. A user agent and a viewport
 * can both be spoofed (browser devtools, desktop user-agent switchers). The
 * portal is still protected by real server-side authorization.
 */

// Largest short side across current phones (~440px, e.g. iPhone Pro Max) and
// smallest across current tablets (744px, iPad mini) is 592px. 560px keeps a
// >120px margin to the phone maximum and >180px to the tablet minimum, so the
// policy does not flip on a single device generation or a browser chrome
// difference. A bare 768px breakpoint would wrongly admit large phones in
// landscape and wrongly block nothing useful, which is why it is not used.
export const MIN_SUPPORTED_SHORT_SIDE = 560;

/** Tablets always take precedence: no tablet is blocked for a "Mobile" token. */
const TABLET_USER_AGENT =
  /iPad|Tablet|PlayBook|Silk|Kindle|Nexus (?:7|9|10)|Android(?![\s\S]*Mobile)/i;

/**
 * Phone markers. `Mobile/<digits>` catches iPhone/iPadOS browsers in desktop
 * mode, whose layout viewport is inflated to 980px; Android tablets never emit
 * a `Mobile` token at all, and any UA that also matches TABLET_USER_AGENT is
 * treated as a tablet before this regex is consulted.
 */
const PHONE_USER_AGENT =
  /iPhone|iPod|Android[\s\S]*Mobile|Windows Phone|IEMobile|Opera Mini|BlackBerry|BB10|webOS|Mobile\/\d/i;

export function isTabletUserAgent(userAgent) {
  return TABLET_USER_AGENT.test(userAgent || "");
}

export function isPhoneUserAgent(userAgent) {
  const ua = userAgent || "";
  if (TABLET_USER_AGENT.test(ua)) return false;
  return PHONE_USER_AGENT.test(ua);
}

/**
 * Pure decision function, so the policy can be unit-tested without a browser.
 *
 * @returns {{restricted: boolean, reason: string}}
 */
export function evaluateAccess({
  width,
  height,
  userAgent = "",
  uaDataMobile = false,
} = {}) {
  const tablet = isTabletUserAgent(userAgent);
  const phone = tablet ? false : isPhoneUserAgent(userAgent) || uaDataMobile === true;

  const shortSide = Math.min(width, height);

  // Unknown/unmeasured viewport: fall back to the user agent alone. Tablets are
  // never blocked on that path.
  if (!Number.isFinite(shortSide) || shortSide <= 0) {
    return phone
      ? { restricted: true, reason: "phone-user-agent" }
      : { restricted: false, reason: "viewport-unknown" };
  }

  // Usability floor, applied to every device class: a 375px-wide viewport is
  // phone-sized regardless of what the device claims to be.
  if (shortSide < MIN_SUPPORTED_SHORT_SIDE) {
    return { restricted: true, reason: "viewport-too-small" };
  }

  // The viewport is large but the UA is a phone: "Request Desktop Website".
  if (phone) {
    return { restricted: true, reason: "phone-user-agent" };
  }

  return { restricted: false, reason: "supported" };
}

function readViewport() {
  if (typeof window === "undefined") {
    return { width: undefined, height: undefined };
  }
  // visualViewport reflects pinch-zoom; innerWidth is the layout viewport and is
  // what media queries see, so it is the right signal here.
  return {
    width: window.innerWidth,
    height: window.innerHeight,
  };
}

export function readAccessDecision() {
  if (typeof navigator === "undefined") {
    return { restricted: false, reason: "no-navigator" };
  }
  return evaluateAccess({
    ...readViewport(),
    userAgent: navigator.userAgent,
    uaDataMobile: navigator.userAgentData?.mobile === true,
  });
}

/**
 * True when this device should be shown the restricted-access notice.
 * Kept as the single call site used by the app shell.
 */
export function isMobileBrowser() {
  return readAccessDecision().restricted;
}