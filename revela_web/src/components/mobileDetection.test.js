import assert from "node:assert/strict";
import test from "node:test";
import { isMobileBrowser } from "./mobileDetection.js";

function withNavigator(value, callback) {
  const original = Object.getOwnPropertyDescriptor(globalThis, "navigator");
  Object.defineProperty(globalThis, "navigator", {
    configurable: true,
    value,
  });

  try {
    callback();
  } finally {
    if (original) {
      Object.defineProperty(globalThis, "navigator", original);
    } else {
      delete globalThis.navigator;
    }
  }
}

test("detects a phone browser", () => {
  withNavigator(
    {
      userAgent: "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X)",
      platform: "iPhone",
      maxTouchPoints: 5,
    },
    () => assert.equal(isMobileBrowser(), true),
  );
});

test("allows an Android tablet browser", () => {
  withNavigator(
    {
      userAgent: "Mozilla/5.0 (Linux; Android 14; Tablet)",
      platform: "Linux armv8l",
      maxTouchPoints: 5,
    },
    () => assert.equal(isMobileBrowser(), false),
  );
});

test("allows iPadOS Safari using its desktop-style Mac user-agent", () => {
  withNavigator(
    {
      userAgent: "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15) AppleWebKit/605.1.15",
      platform: "MacIntel",
      maxTouchPoints: 5,
    },
    () => assert.equal(isMobileBrowser(), false),
  );
});

test("detects a phone using the User-Agent Client Hints mobile flag", () => {
  withNavigator(
    {
      userAgent: "Mozilla/5.0 (Linux; Android 14)",
      userAgentData: { mobile: true },
    },
    () => assert.equal(isMobileBrowser(), true),
  );
});

test("allows a non-touch desktop browser", () => {
  withNavigator(
    {
      userAgent: "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
      platform: "Win32",
      maxTouchPoints: 0,
    },
    () => assert.equal(isMobileBrowser(), false),
  );
});
