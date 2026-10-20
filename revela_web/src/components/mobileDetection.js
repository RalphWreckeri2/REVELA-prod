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
 * The policy therefore combines these signals:
 *   1. The *short side* of the viewport -- the dimension that actually decides
 *      whether the dashboard fits. Phones stay under ~440px on their short
 *      side in either orientation; the smallest common tablet (iPad mini) is
 *      744px. That is a clean split, unlike width.
 *   2. A tablet-aware user-agent check, used to catch a phone that inflates its
 *      layout viewport by requesting the desktop site. Tablets always win this
 *      check, so no tablet can be blocked for carrying a "Mobile" token.
 *   3. Touch capability and the physical screen in CSS pixels disambiguate
 *      Android tablets that emit Mobile and iPadOS that identifies as a Mac.
 *      A large layout viewport alone never overrides a phone user agent.
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
 * Some tablet browsers also emit these markers; evaluateAccess disambiguates
 * them using touch + screen size before consulting the phone fallback.
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
  screenWidth,
  screenHeight,
  maxTouchPoints = 0,
} = {}) {
  const screenShortSide = Math.min(screenWidth, screenHeight);
  const tabletScreen = Number.isFinite(screenShortSide) && screenShortSide >= MIN_SUPPORTED_SHORT_SIDE;
  const explicitPhone = /iPhone|iPod|Windows Phone|IEMobile|Opera Mini|BlackBerry|BB10|webOS/i.test(userAgent);
  const touchTablet = !explicitPhone && maxTouchPoints > 1 && tabletScreen && /Android|Linux|Macintosh/i.test(userAgent);
  const tablet = isTabletUserAgent(userAgent) || touchTablet;
  const phone = tablet ? false : isPhoneUserAgent(userAgent) || uaDataMobile === true;

  // An on-screen keyboard can shrink innerHeight on a supported tablet. It
  // must not replace the login form with the access notice while typing.
  const shortSide = tablet && tabletScreen && width >= MIN_SUPPORTED_SHORT_SIDE
    ? Math.min(width, screenShortSide)
    : Math.min(width, height);

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

// Also sent with web login so the server's usability gate can recognize the
// same Mobile-marked tablets. These hints never grant authentication/roles.
export function readDeviceAccessHints() {
  return {
    screenWidth: typeof window === "undefined" ? undefined : window.screen?.width,
    screenHeight: typeof window === "undefined" ? undefined : window.screen?.height,
    maxTouchPoints: typeof navigator === "undefined" ? 0 : navigator.maxTouchPoints || 0,
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
    ...readDeviceAccessHints(),
  });
}

/**
 * True when this device should be shown the restricted-access notice.
 * Kept as the single call site used by the app shell.
 */
export function isMobileBrowser() {
  return readAccessDecision().restricted;
}
