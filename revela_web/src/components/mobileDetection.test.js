import assert from "node:assert/strict";
import test from "node:test";
import {
  MIN_SUPPORTED_SHORT_SIDE,
  evaluateAccess,
  isMobileBrowser,
  isPhoneUserAgent,
  isTabletUserAgent,
} from "./mobileDetection.js";

// Real user-agent strings. iPadOS sends `Mobile/15E148` in its default mode and
// only switches to the `(Macintosh; ...)` string when "Request Desktop Website"
// is enabled -- this is what made the old /Mobile/ test reject every iPad.
const UA = {
  iphoneSafari:
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
  iphoneDesktopMode:
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
  ipadSafari:
    "Mozilla/5.0 (iPad; CPU OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
  ipadSafariDesktopMode:
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
  ipadChrome:
    "Mozilla/5.0 (iPad; CPU OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) CriOS/120.0.6099.119 Mobile/15E148 Safari/604.1",
  ipadFirefox:
    "Mozilla/5.0 (iPad; CPU OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) FxiOS/120.0 Mobile/15E148 Safari/605.1.15",
  androidPhone:
    "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36",
  androidPhoneReduced:
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
  androidTablet:
    "Mozilla/5.0 (Linux; Android 14; SM-X200) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
  desktopChrome:
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
  desktopEdge:
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.2210.91",
  desktopSafari:
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
  surfacePro:
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; Touch) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
};

function withNavigator(value, callback) {
  const original = Object.getOwnPropertyDescriptor(globalThis, "navigator");
  Object.defineProperty(globalThis, "navigator", {
    configurable: true,
    value,
  });
  try {
    return callback();
  } finally {
    if (original) {
      Object.defineProperty(globalThis, "navigator", original);
    } else {
      delete globalThis.navigator;
    }
  }
}

// ── Task 2: the required device matrix ──────────────────────────────────────
const DEVICE_MATRIX = [
  // [label, userAgent, width, height, expected restricted]
  ["Smartphone portrait", UA.iphoneSafari, 393, 852, true],
  ["Smartphone landscape", UA.iphoneSafari, 852, 393, true],
  ["iPad mini portrait", UA.ipadSafari, 744, 1133, false],
  ["iPad mini landscape", UA.ipadSafari, 1133, 744, false],
  ["iPad portrait", UA.ipadSafari, 820, 1180, false],
  ["iPad landscape", UA.ipadSafari, 1180, 820, false],
  ["iPad Air / Pro portrait", UA.ipadChrome, 834, 1194, false],
  ["iPad in desktop-site mode", UA.ipadSafariDesktopMode, 980, 1180, false],
  ["Android tablet portrait", UA.androidTablet, 800, 1280, false],
  ["Android tablet landscape", UA.androidTablet, 1280, 800, false],
  ["Laptop", UA.desktopChrome, 1280, 800, false],
  ["Desktop", UA.desktopChrome, 1920, 1080, false],
  ["Large touchscreen device", UA.surfacePro, 1920, 1080, false],
];

for (const [label, userAgent, width, height, expected] of DEVICE_MATRIX) {
  test(`device policy: ${label}`, () => {
    const result = evaluateAccess({ width, height, userAgent });
    assert.equal(
      result.restricted,
      expected,
      `${label} (${width}x${height}) -> ${result.restricted} (${result.reason})`,
    );
  });
}

// ── Task 6: the required viewport table ─────────────────────────────────────
const VIEWPORT_TABLE = [
  [375, 812, true],
  [390, 844, true],
  [430, 932, true],
  [844, 390, true],
  [768, 1024, false],
  [820, 1180, false],
  [1024, 768, false],
  [1280, 800, false],
  [1440, 900, false],
  [1920, 1080, false],
];

for (const [width, height, expected] of VIEWPORT_TABLE) {
  test(`viewport ${width}x${height} -> ${expected ? "restricted" : "login"}`, () => {
    // Desktop UA on purpose: viewport alone must make the call, so the result
    // is not a function of which browser was simulated.
    const result = evaluateAccess({
      width,
      height,
      userAgent: UA.desktopChrome,
    });
    assert.equal(result.restricted, expected, `reason=${result.reason}`);
  });
}

// ── Task 6: the named browser/device combinations ───────────────────────────
const BROWSER_TARGETS = [
  ["Safari on iPad", UA.ipadSafari, 820, 1180, false],
  ["Safari on iPad (desktop site)", UA.ipadSafariDesktopMode, 980, 1180, false],
  ["Chrome on iPad", UA.ipadChrome, 834, 1194, false],
  ["Firefox on iPad", UA.ipadFirefox, 834, 1194, false],
  ["Chrome on Android tablet", UA.androidTablet, 800, 1280, false],
  ["Desktop Chrome", UA.desktopChrome, 1440, 900, false],
  ["Desktop Edge", UA.desktopEdge, 1440, 900, false],
  ["iPhone Safari", UA.iphoneSafari, 393, 852, true],
];

for (const [label, userAgent, width, height, expected] of BROWSER_TARGETS) {
  test(`target: ${label}`, () => {
    assert.equal(
      evaluateAccess({ width, height, userAgent }).restricted,
      expected,
      label,
    );
  });
}

// ── The regression that motivated this change ───────────────────────────────
test("REGRESSION: every iPad browser is allowed, including iOS ones with Mobile tokens", () => {
  // [label, userAgent, carries an explicit tablet token?]
  // Desktop-site mode makes an iPad indistinguishable from a Mac, which is
  // fine: the requirement is that it is not treated as a phone.
  const ipads = [
    ["iPad Safari", UA.ipadSafari, true],
    ["iPad Safari desktop mode", UA.ipadSafariDesktopMode, false],
    ["iPad Chrome", UA.ipadChrome, true],
    ["iPad Firefox", UA.ipadFirefox, true],
  ];
  for (const [label, userAgent, hasTabletToken] of ipads) {
    assert.equal(
      isTabletUserAgent(userAgent),
      hasTabletToken,
      `${label} tablet-token detection`,
    );
    assert.equal(
      isPhoneUserAgent(userAgent),
      false,
      `${label} must not be classified as a phone`,
    );
    assert.equal(
      evaluateAccess({ width: 820, height: 1180, userAgent }).restricted,
      false,
      `${label} must not be blocked`,
    );
  }
});

test("REGRESSION: an iPad is allowed even when Chromium reports mobile:true", () => {
  // navigator.userAgentData.mobile is true on iPad Chromium -- an independent
  // reason the old implementation blocked tablets.
  assert.equal(
    evaluateAccess({
      width: 834,
      height: 1194,
      userAgent: UA.ipadChrome,
      uaDataMobile: true,
    }).restricted,
    false,
  );
});

test("REGRESSION: the old /Mobile/ test would have blocked these tablets", () => {
  const legacy = /iPhone|iPod|Mobile|Windows Phone/i;
  assert.equal(legacy.test(UA.ipadSafari), true, "precondition: old rule blocked it");
  assert.equal(legacy.test(UA.ipadChrome), true, "precondition: old rule blocked it");
});

// ── Phones cannot bypass by rotating or requesting the desktop site ─────────
test("REGRESSION: a phone cannot escape by requesting the desktop site", () => {
  // Desktop-site mode inflates the layout viewport to 980px.
  const result = evaluateAccess({
    width: 980,
    height: 1000,
    userAgent: UA.iphoneDesktopMode,
  });
  assert.equal(result.restricted, true);
  assert.equal(result.reason, "phone-user-agent");
});

test("REGRESSION: an Android phone cannot escape with a reduced user agent", () => {
  // A reduced UA looks like a desktop, but Client Hints still reports mobile.
  assert.equal(
    evaluateAccess({
      width: 1920,
      height: 1080,
      userAgent: UA.androidPhoneReduced,
      uaDataMobile: true,
    }).restricted,
    true,
    "userAgentData.mobile must still catch a reduced-UA phone",
  );
  // Without the hint there is nothing left to distinguish it, which is an
  // accepted and documented limitation of browser-side detection.
  assert.equal(
    evaluateAccess({
      width: 1920,
      height: 1080,
      userAgent: UA.androidPhoneReduced,
      uaDataMobile: false,
    }).restricted,
    false,
  );
});

test("a large viewport never overrides a real phone-class user agent", () => {
  for (const userAgent of [UA.iphoneSafari, UA.androidPhone]) {
    assert.equal(
      evaluateAccess({ width: 2560, height: 1440, userAgent }).restricted,
      true,
    );
  }
});

test("touch capability alone never restricts a device", () => {
  // A large touchscreen (Surface, kiosk, iPad) must not be blocked.
  assert.equal(
    evaluateAccess({
      width: 1920,
      height: 1080,
      userAgent: UA.surfacePro,
      uaDataMobile: false,
    }).restricted,
    false,
  );
  // A desktop UA reporting mobile:true is genuinely ambiguous; the short-side
  // rule and the UA rule are what keep tablets out of the restricted branch.
  assert.equal(
    evaluateAccess({
      width: 1920,
      height: 1080,
      userAgent: UA.ipadChrome,
      uaDataMobile: true,
    }).restricted,
    false,
    "userAgentData.mobile is true on iPad Chromium and must not block tablets",
  );
});

// ── Orientation symmetry ───────────────────────────────────────────────────
test("the decision is orientation-symmetric per device class", () => {
  for (const [w, h] of [
    [393, 852],
    [852, 393],
  ]) {
    assert.equal(
      evaluateAccess({ width: w, height: h, userAgent: UA.iphoneSafari })
        .restricted,
      true,
    );
  }
  for (const [w, h] of [
    [820, 1180],
    [1180, 820],
  ]) {
    assert.equal(
      evaluateAccess({ width: w, height: h, userAgent: UA.ipadSafari })
        .restricted,
      false,
    );
  }
});

// ── Breakpoint margins ─────────────────────────────────────────────────────
test("the breakpoint sits clear of every real device class", () => {
  // Widest phone short side (~440px, Pro Max) must be well below the floor.
  assert.ok(MIN_SUPPORTED_SHORT_SIDE - 440 > 100, "phone margin");
  // Narrowest tablet short side (744px, iPad mini) must be well above it.
  assert.ok(744 - MIN_SUPPORTED_SHORT_SIDE > 100, "tablet margin");
  // The task's own guidance: 768px must not be used as the phone/tablet split.
  assert.notEqual(MIN_SUPPORTED_SHORT_SIDE, 768);
});

test("a 768px-wide viewport is not treated as phone-class", () => {
  // Landscape phone and portrait tablet overlap around this width; the short
  // side is what disambiguates them.
  assert.equal(
    evaluateAccess({ width: 1024, height: 768, userAgent: UA.desktopChrome })
      .restricted,
    false,
  );
  assert.equal(
    evaluateAccess({ width: 768, height: 1024, userAgent: UA.ipadSafari })
      .restricted,
    false,
  );
});

// ── Unknown / defensive input ──────────────────────────────────────────────
test("an unmeasurable viewport falls back to the user agent and never blocks tablets", () => {
  assert.deepEqual(
    evaluateAccess({ width: undefined, height: undefined, userAgent: UA.ipadSafari }),
    { restricted: false, reason: "viewport-unknown" },
  );
  assert.equal(
    evaluateAccess({ width: undefined, height: undefined, userAgent: UA.iphoneSafari })
      .restricted,
    true,
  );
  assert.equal(evaluateAccess().restricted, false, "empty input must not lock anyone out");
  assert.equal(evaluateAccess({ userAgent: UA.ipadSafari }).restricted, false);
});

test("an empty user agent is treated as unknown, not as a phone", () => {
  assert.equal(
    evaluateAccess({ width: 1280, height: 800, userAgent: "" }).restricted,
    false,
  );
  assert.equal(isPhoneUserAgent(""), false);
  assert.equal(isTabletUserAgent(""), false);
});

// ── isMobileBrowser() keeps working for the app shell ───────────────────────
test("isMobileBrowser reflects the viewport as well as the user agent", () => {
  withNavigator(
    { userAgent: UA.iphoneSafari, platform: "iPhone", maxTouchPoints: 5 },
    () => assert.equal(isMobileBrowser(), true),
  );
  withNavigator(
    { userAgent: UA.ipadChrome, platform: "MacIntel", maxTouchPoints: 5 },
    () => assert.equal(isMobileBrowser(), false, "iPad Chrome must be allowed"),
  );
  withNavigator(
    { userAgent: UA.desktopChrome, platform: "Win32", maxTouchPoints: 0 },
    () => assert.equal(isMobileBrowser(), false),
  );
});