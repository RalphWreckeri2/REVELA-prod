import test from "node:test";
import assert from "node:assert/strict";

import {
  METHOD_LABELS,
  NEAR_LIMIT_PERCENT,
  buildUsageWarnings,
  describeLimitSource,
  detectionScanSummary,
  formatNumber,
  isCustomLimit,
  limitState,
  methodLabel,
  summarizeUsage,
} from "./apiUsageView.js";

function method(key, cap) {
  return {
    method: key,
    label: key,
    revela_app_cap: {
      used_today: 0,
      used_month: 0,
      daily_cap: 0,
      monthly_cap: 0,
      daily_quota_exceeded: false,
      monthly_quota_exceeded: false,
      disabled: false,
      ...cap,
    },
  };
}

test("every Google method maps to an administrator-facing label", () => {
  assert.deepEqual(Object.values(METHOD_LABELS), [
    "Business Lookup",
    "Map Pin Refresh",
    "Run Detection Requests",
    "Run Detection Requests (Alternate)",
    "Address Lookup",
  ]);
  // The report's raw SKU-ish label is only a fallback for unknown methods.
  assert.equal(methodLabel({ method: "text_search" }), "Business Lookup");
  assert.equal(methodLabel({ method: "mystery", label: "Something Else" }), "Something Else");
  assert.equal(methodLabel(null), "Requests");
});

test("formatNumber renders thousands separators and tolerates junk", () => {
  assert.equal(formatNumber(1234567), "1,234,567");
  assert.equal(formatNumber("42"), "42");
  assert.equal(formatNumber(undefined), "0");
  assert.equal(formatNumber("abc"), "0");
});

test("limitState separates switched-off, met, nearly met, and healthy caps", () => {
  assert.equal(limitState(0, 0).level, "off");
  assert.equal(limitState(10, 10).level, "full");
  assert.equal(limitState(11, 10).level, "full", "over cap still reads as full");
  assert.equal(limitState(79, 100).level, "ok");
  assert.equal(limitState(80, 100).level, "near");
  assert.equal(limitState(95, 100).level, "near");
  assert.equal(limitState(2, 10).remaining, 8);
  assert.equal(limitState(12, 10).remaining, 0);
  assert.equal(NEAR_LIMIT_PERCENT, 80);
});

test("summarizeUsage sums used counters only, never remaining allowances", () => {
  const totals = summarizeUsage([
    method("text_search", { used_today: 3, used_month: 40, daily_cap: 10, monthly_cap: 100 }),
    method("place_details", { used_today: 2, used_month: 60, daily_cap: 5, monthly_cap: 90 }),
  ]);
  assert.equal(totals.usedToday, 5);
  assert.equal(totals.usedMonth, 100);
  assert.ok(!("remaining" in totals), "no combined remaining total is produced");
  assert.deepEqual(summarizeUsage([]), { usedToday: 0, usedMonth: 0 });
});

test("summarizeUsage ignores missing rows instead of producing NaN", () => {
  assert.deepEqual(summarizeUsage([{}, { revela_app_cap: { used_today: 2 } }]), {
    usedToday: 2,
    usedMonth: 0,
  });
});

test("no warnings while every budget has headroom", () => {
  assert.deepEqual(
    buildUsageWarnings(
      [method("text_search", {
        used_today: 5, used_month: 50, daily_cap: 80, monthly_cap: 2500,
      })],
      { used_this_month: 1, monthly_limit: 10 },
    ),
    [],
  );
});

test("a method at 80% of its daily cap raises one clear warning", () => {
  const warnings = buildUsageWarnings([
    method("text_search", {
      used_today: 64, used_month: 100, daily_cap: 80, monthly_cap: 2500,
    }),
  ]);
  assert.equal(warnings.length, 1);
  assert.equal(warnings[0].level, "warning");
  assert.equal(warnings[0].id, "text_search-day-near");
  assert.match(warnings[0].text, /^Business Lookup is close to today's limit: 64 of 80 /);
});

test("an exhausted monthly cap is reported separately from the daily one", () => {
  const warnings = buildUsageWarnings([
    method("geocoding", {
      used_today: 1500, used_month: 8000,
      daily_cap: 1500, monthly_cap: 8000,
      daily_quota_exceeded: true, monthly_quota_exceeded: true,
    }),
  ]);
  assert.deepEqual(warnings.map((w) => w.id), ["geocoding-day-full", "geocoding-month-full"]);
  assert.ok(warnings.every((w) => w.level === "danger"));
  assert.match(warnings[0].text, /^Address Lookup has used all of today's limit \(1,500 /);
});

test("a switched-off method never warns", () => {
  assert.deepEqual(
    buildUsageWarnings([
      method("nearby_search_new", {
        used_today: 0, used_month: 0, daily_cap: 0, monthly_cap: 0, disabled: true,
      }),
    ]),
    [],
  );
});

test("Run Detection scan warnings appear only when the scan budget is configured", () => {
  assert.deepEqual(buildUsageWarnings([], null), []);
  assert.deepEqual(
    buildUsageWarnings([], { used_this_month: 0, monthly_limit: 0 }),
    [],
  );
  const near = buildUsageWarnings([], { used_this_month: 9, monthly_limit: 10 });
  assert.equal(near.length, 1);
  assert.equal(near[0].level, "warning");
  assert.match(near[0].text, /Run Detection scans are close to this month's limit: 9 of 10 used\./);

  const done = buildUsageWarnings([], { used_this_month: 10, monthly_limit: 10 });
  assert.equal(done[0].level, "danger");
  assert.match(done[0].text, /All 10 Run Detection scans for this month have been used\./);
});

test("detectionScanSummary reports remaining scans", () => {
  assert.deepEqual(
    detectionScanSummary({ used_this_month: 4, monthly_limit: 10 }),
    { used: 4, limit: 10, remaining: 6, state: { level: "ok", percent: 40, remaining: 6 } },
  );
  assert.equal(detectionScanSummary(null).remaining, 0);
  assert.equal(
    detectionScanSummary({ used_this_month: 12, monthly_limit: 10 }).remaining,
    0,
    "over-limit usage never yields a negative remainder",
  );
});

test("effective limits are described as defaults or custom settings", () => {
  assert.equal(describeLimitSource({ source: "env", baseline: 80 }), "Application default");
  assert.equal(
    describeLimitSource({ source: "admin_override", baseline: 80 }),
    "Custom setting (application default: 80)",
  );
  assert.equal(describeLimitSource(null), "Application default");
  assert.equal(isCustomLimit({ source: "admin_override" }), true);
  assert.equal(isCustomLimit({ source: "env" }), false);
  assert.equal(isCustomLimit(undefined), false);
});