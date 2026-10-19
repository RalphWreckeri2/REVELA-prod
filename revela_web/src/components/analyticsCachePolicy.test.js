import test from "node:test";
import assert from "node:assert/strict";
import { Buffer } from "node:buffer";
import { readFileSync } from "node:fs";
import {
  ANALYTICS_MAX_STALE_MS,
  analyticsRefreshPending,
  analyticsSnapshotDeadline,
  analyticsSnapshotExpired,
  analyticsSnapshotMatchesFilters,
  analyticsSnapshotStatus,
} from "./analyticsCachePolicy.js";

const COMPUTED_AT = "2026-10-19T01:00:00+00:00";

test("snapshots are bound to the applied filters, including on refresh", () => {
  const filters = { barangay_ids: [1], flag_color: "Red" };
  const snapshot = { filters, data: {} };
  assert.equal(analyticsSnapshotMatchesFilters(snapshot, filters), true);
  assert.equal(analyticsSnapshotMatchesFilters(snapshot, { ...filters }), false);
  assert.equal(analyticsSnapshotMatchesFilters(snapshot, { barangay_ids: [2] }), false);
  assert.equal(analyticsSnapshotMatchesFilters(null, undefined), false);
});

test("maximum age is 15 minutes, with the exact boundary allowed", () => {
  assert.equal(ANALYTICS_MAX_STALE_MS, 900000);
  const expiresAt = analyticsSnapshotDeadline({ computed_at: COMPUTED_AT, age_seconds: 899 }, 1000);
  assert.equal(expiresAt, 2000);
  assert.equal(analyticsSnapshotExpired({ expiresAt }, 2000), false);
  assert.equal(analyticsSnapshotExpired({ expiresAt }, 2001), true);
});

test("a response cannot reset an already old computation to a fresh 15 minutes", () => {
  const expiresAt = analyticsSnapshotDeadline({ computed_at: COMPUTED_AT, age_seconds: 901 }, 1000000);
  assert.equal(expiresAt, 999000);
  assert.equal(analyticsSnapshotExpired({ expiresAt }, 1000000), true);
});

test("server age plus monotonic request start prevents clock skew and transport extending age", () => {
  const metadata = { computed_at: COMPUTED_AT, age_seconds: 600 };
  const start = 5000;
  const wallNow = Date.parse(COMPUTED_AT);
  const deadline = analyticsSnapshotDeadline(metadata, start, wallNow - 86400000);
  assert.equal(deadline, analyticsSnapshotDeadline(metadata, start, wallNow + 86400000));
  assert.equal(deadline, start + 300000);
  assert.equal(analyticsSnapshotExpired({ expiresAt: deadline }, start + 300001), true);
});

test("legacy timestamp-only metadata still expires from computed_at, not receipt", () => {
  const wallNow = Date.parse(COMPUTED_AT) + 899000;
  assert.equal(analyticsSnapshotDeadline({ computed_at: COMPUTED_AT }, 5000, wallNow), 6000);
});

test("invalid, missing and explicitly expired timestamps fail closed", () => {
  for (const metadata of [null, {}, { computed_at: "invalid" },
    { computed_at: COMPUTED_AT, expired: true },
    { computed_at: COMPUTED_AT, age_seconds: -1 }]) {
    assert.equal(analyticsSnapshotDeadline(metadata, 1000), 0);
  }
  assert.equal(analyticsSnapshotExpired({ expiresAt: 0 }, 1000), true);
  assert.equal(analyticsSnapshotExpired({}, 1000), true);
});

test("failed requests and hung refreshes cannot extend the local deadline", () => {
  const snapshot = { expiresAt: 900000, data: { analytics_cache: { refreshing: true } } };
  assert.equal(analyticsSnapshotExpired(snapshot, 899999), false);
  // No successful response/state replacement occurs: the same object expires.
  assert.equal(analyticsSnapshotExpired(snapshot, 900001), true);
  assert.equal(analyticsSnapshotExpired({ ...snapshot, expired: true }, 1), true);
});

test("tab resume/sleep and moving the wall clock back cannot extend validity", () => {
  const snapshot = { expiresAt: 901000, wallExpiresAt: 2000000 };
  // Browser slept; its monotonic clock barely advanced, but wall time expired.
  assert.equal(analyticsSnapshotExpired(snapshot, 2000, 2000001), true);
  // Conversely, moving wall time back cannot bypass the monotonic deadline.
  assert.equal(analyticsSnapshotExpired(snapshot, 901001, 1), true);
});

test("expired refreshes continue polling for recovery, without displaying their rows", () => {
  const metadata = { expired: true, refreshing: true, computed_at: COMPUTED_AT };
  assert.equal(analyticsRefreshPending(metadata), true);
  assert.equal(analyticsRefreshPending({ refresh_deferred: true }), true);
  assert.equal(analyticsRefreshPending({ refresh_failed: true }), false);
  assert.match(analyticsSnapshotStatus(metadata), /expired.*hidden/i);
  assert.match(analyticsSnapshotStatus({ refresh_failed: true }), /refresh failed/);
  assert.match(analyticsSnapshotStatus({ refresh_deferred: true }), /waiting to refresh/);
});

// Only replace Vite's environment constant. Every HTTP call below is mocked.
const apiSource = readFileSync(new URL("../services/api.js", import.meta.url), "utf8")
  .replace("import.meta.env.VITE_API_ORIGIN", '"http://analytics.test"');
const { getAnalyticsOverviewRequest } = await import(
  `data:text/javascript;base64,${Buffer.from(apiSource).toString("base64")}`
);

test("Analytics opt-in leaves the actual filter values and ordering unchanged", async (t) => {
  const calls = [];
  t.mock.method(globalThis, "fetch", async (url, options) => {
    calls.push({ url: new URL(url), options });
    return { ok: true, json: async () => ({}) };
  });
  const filters = Object.freeze({ barangay_ids: Object.freeze([2, 1]), flag_color: "Red" });
  await getAnalyticsOverviewRequest("header.payload.signature", filters, { staleWhileRevalidate: true });
  assert.deepEqual(Object.fromEntries(calls[0].url.searchParams), {
    barangay_ids: "2,1", flag_color: "Red", stale_while_revalidate: "1",
  });
  assert.equal(calls[0].options.cache, "no-store");
});

test("expired HTTP errors preserve timestamp and refresh status for the page", async (t) => {
  const metadata = { expired: true, computed_at: COMPUTED_AT, refreshing: true };
  t.mock.method(globalThis, "fetch", async () => ({
    ok: false, status: 503,
    json: async () => ({ error: "Snapshot expired", analytics_cache: metadata }),
  }));
  await assert.rejects(getAnalyticsOverviewRequest("header.payload.signature", {}, {
    staleWhileRevalidate: true,
  }), (error) => error.responseData.analytics_cache === metadata);
});

test("other callers do not opt into stale responses", async (t) => {
  t.mock.method(globalThis, "fetch", async (url) => {
    assert.equal(new URL(url).searchParams.has("stale_while_revalidate"), false);
    return { ok: true, json: async () => ({}) };
  });
  await getAnalyticsOverviewRequest("header.payload.signature");
});
