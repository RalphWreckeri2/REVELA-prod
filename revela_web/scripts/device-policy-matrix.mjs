/**
 * Device-access decision matrix, dumped as JSON.
 *
 * Used by the backend parity test (tests/test_device_access_parity.py) to
 * compare the shipped browser policy against the API gate, so the two cannot
 * drift apart. Run: node scripts/device-policy-matrix.mjs
 */
import { evaluateAccess, isPhoneUserAgent } from "../src/components/mobileDetection.js";

const UA = {
  iphone:
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
  iphoneDesktopSite:
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
  ipad:
    "Mozilla/5.0 (iPad; CPU OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
  ipadDesktopSite:
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
  ipadChrome:
    "Mozilla/5.0 (iPad; CPU OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) CriOS/120.0.6099.119 Mobile/15E148 Safari/604.1",
  ipadFirefox:
    "Mozilla/5.0 (iPad; CPU OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) FxiOS/120.0 Mobile/15E148 Safari/605.1.15",
  androidPhone:
    "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Mobile Safari/537.36",
  androidPhoneReduced:
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
  androidTablet:
    "Mozilla/5.0 (Linux; Android 14; SM-X200) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
  desktop:
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
  surface:
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; Touch) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
};

// [label, userAgent, width, height, uaDataMobile]
const CASES = [
  ["iphone_safari", UA.iphone, 393, 852, false],
  ["iphone_safari_landscape", UA.iphone, 852, 393, false],
  ["iphone_desktop_site", UA.iphoneDesktopSite, 980, 1000, false],
  ["android_phone", UA.androidPhone, 412, 915, false],
  ["android_phone_landscape", UA.androidPhone, 915, 412, false],
  ["android_phone_reduced_ua", UA.androidPhoneReduced, 1920, 1080, true],

  ["ipad_safari", UA.ipad, 820, 1180, false],
  ["ipad_safari_landscape", UA.ipad, 1180, 820, false],
  ["ipad_mini", UA.ipad, 744, 1133, false],
  ["ipad_chrome", UA.ipadChrome, 834, 1194, true],
  ["ipad_firefox", UA.ipadFirefox, 834, 1194, true],
  ["ipad_desktop_site", UA.ipadDesktopSite, 980, 1180, false],
  ["ipad_split_view", UA.ipad, 320, 1024, false],
  ["android_tablet", UA.androidTablet, 800, 1280, false],
  ["android_tablet_landscape", UA.androidTablet, 1280, 800, false],

  ["laptop", UA.desktop, 1280, 800, false],
  ["desktop", UA.desktop, 1920, 1080, false],
  ["surface_pro_touch", UA.surface, 1920, 1080, false],

  // Desktop agent at phone-sized viewports: the viewport rule must decide.
  ["desktop_ua_375x812", UA.desktop, 375, 812, false],
  ["desktop_ua_844x390", UA.desktop, 844, 390, false],
  ["desktop_ua_768x1024", UA.desktop, 768, 1024, false],
  ["desktop_ua_820x1180", UA.desktop, 820, 1180, false],
];

const out = CASES.map(([label, userAgent, width, height, uaDataMobile]) => {
  const decision = evaluateAccess({ width, height, userAgent, uaDataMobile });
  // The UA-only verdict the API gate will reach, from a roomy viewport.
  const apiGateRejects = evaluateAccess({
    width: 1920,
    height: 1080,
    userAgent,
    uaDataMobile,
  }).reason === "phone-user-agent";
  return {
    label,
    userAgent,
    width,
    height,
    uaDataMobile,
    restricted: decision.restricted,
    reason: decision.reason,
    frontendPhoneUA: isPhoneUserAgent(userAgent),
    apiGateRejects,
  };
});

process.stdout.write(JSON.stringify(out, null, 2));