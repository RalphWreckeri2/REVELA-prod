import { test } from "node:test";
import assert from "node:assert/strict";
import { setImmediate } from "node:timers";
import { ANALYTICS_SECTIONS, createAnalyticsLoader } from "./analyticsLoader.js";

const response = (section, value = 1) => ({
  [section]: { value },
  analytics_cache: { computed_at: new Date().toISOString(), age_seconds: 0 },
});
const deferred = () => {
  let resolve;
  const promise = new Promise((r) => { resolve = r; });
  return { promise, resolve };
};
const tick = () => new Promise((resolve) => setImmediate(resolve));
function setup(t, options) {
  const loader = createAnalyticsLoader({ isOnline: () => true, delay: async () => {}, ...options });
  t.after(() => loader.stop());
  return loader;
}

test("initial placeholders and sections resolve independently on a slow connection", async (t) => {
  const pending = Object.fromEntries(ANALYTICS_SECTIONS.map((name) => [name, deferred()]));
  const calls = [];
  const loader = setup(t, { request: (section) => { calls.push(section); return pending[section].promise; } });
  assert.ok(Object.values(loader.getSnapshot().sections).every((s) => s.status === "loading" && !s.data));
  const load = loader.refresh();
  void loader.refresh(true); // focus/manual/SSE while loading join the same flights
  assert.equal(calls.length, 4);
  pending.descriptive.resolve(response("descriptive"));
  await tick();
  assert.equal(loader.getSnapshot().sections.descriptive.data.value, 1);
  assert.equal(loader.getSnapshot().sections.diagnostic.status, "loading");
  for (const section of ANALYTICS_SECTIONS.slice(1)) pending[section].resolve(response(section));
  await load;
});

test("background refresh keeps existing data and exposes updating state", async (t) => {
  let pending;
  const loader = setup(t, { request: (section) => pending ? pending.promise.then(() => response(section, 2)) : Promise.resolve(response(section)) });
  await loader.refresh();
  pending = deferred();
  const refresh = loader.refresh(true);
  assert.equal(loader.getSnapshot().sections.descriptive.data.value, 1);
  assert.equal(loader.getSnapshot().sections.descriptive.updating, true);
  pending.resolve();
  await refresh;
  assert.equal(loader.getSnapshot().sections.descriptive.data.value, 2);
  assert.equal(loader.getSnapshot().sections.descriptive.updating, false);
});

test("failed requests stop after two retries and manual retry can recover", async (t) => {
  let fail = true;
  let calls = 0;
  const loader = setup(t, { request: async (section) => { calls++; if (fail) throw new Error("network failure"); return response(section); } });
  await loader.refresh();
  assert.equal(calls, 12); // initial + 2 retries for each of four sections
  assert.equal(loader.getSnapshot().sections.descriptive.status, "error");
  await loader.refresh(); // ordinary polling cannot restart an exhausted retry loop
  assert.equal(calls, 12);
  fail = false;
  await loader.refresh(true);
  assert.equal(calls, 16);
  assert.equal(loader.getSnapshot().sections.descriptive.status, "ready");
});

test("disconnect aborts active work; repeated reconnect events start only one recovery", async (t) => {
  let online = true;
  let calls = 0;
  const pending = deferred();
  const loader = setup(t, {
    isOnline: () => online,
    request: (section, signal) => {
      calls++;
      if (calls > 4) return Promise.resolve(response(section, 2));
      return new Promise((resolve, reject) => {
        pending.promise.then(() => resolve(response(section)));
        signal.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError")), { once: true });
      });
    },
  });
  const first = loader.refresh();
  online = false;
  loader.connectionChanged();
  await first;
  assert.equal(loader.getSnapshot().sections.descriptive.status, "offline");
  online = true;
  loader.connectionChanged();
  loader.connectionChanged();
  await tick();
  assert.equal(calls, 8);
  assert.equal(loader.getSnapshot().sections.descriptive.data.value, 2);
});

test("late responses from an old filter scope are ignored even if transport ignores abort", async (t) => {
  const old = deferred();
  const loader = setup(t, { request: (section) => old.promise.then(() => response(section, 1)) });
  const first = loader.refresh();
  loader.stop();
  old.resolve();
  await first;
  assert.equal(loader.getSnapshot().sections.descriptive.data, null);
  const next = setup(t, { request: async (section) => response(section, 9) });
  await next.refresh();
  assert.equal(next.getSnapshot().sections.descriptive.data.value, 9);
});

test("hanging fetches time out and do not leave permanent loading indicators", async (t) => {
  let calls = 0;
  const loader = setup(t, { timeoutMs: 5, request: (_section, signal) => new Promise((_resolve, reject) => {
    calls++;
    signal.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError")), { once: true });
  }) });
  await loader.refresh();
  assert.equal(calls, 12);
  assert.match(loader.getSnapshot().sections.descriptive.error, /timed out/);
  assert.equal(loader.getSnapshot().sections.descriptive.updating, false);
});

test("cold backend preparation polls are bounded, separately from failed-request retries", async (t) => {
  let calls = 0;
  const loader = setup(t, { maxPendingPolls: 3, request: async () => { calls++; return { analytics_cache: { loading: true } }; } });
  await loader.refresh();
  assert.equal(calls, 12);
  assert.equal(loader.getSnapshot().sections.operations.status, "error");
  assert.match(loader.getSnapshot().sections.operations.error, /longer than expected/);
});

test("expired 503 responses keep polling a replacement without displaying expired data", async (t) => {
  const attempts = {};
  const loader = setup(t, { maxRetries: 0, request: async (section) => {
    attempts[section] = (attempts[section] || 0) + 1;
    if (attempts[section] <= 3) throw Object.assign(new Error("Expired snapshot"), {
      status: 503, responseData: { analytics_cache: { expired: true, refreshing: true } },
    });
    return response(section, 4);
  } });
  await loader.refresh();
  assert.equal(attempts.descriptive, 4);
  assert.equal(loader.getSnapshot().sections.descriptive.status, "ready");
  assert.equal(loader.getSnapshot().sections.descriptive.data.value, 4);
});

test("empty data is a ready response; permanent errors are not retried", async (t) => {
  let calls = 0;
  const loader = setup(t, { request: async (section) => {
    calls++;
    if (section === "diagnostic") throw Object.assign(new Error("Forbidden"), { status: 403 });
    return { ...response(section), [section]: { items: [] } };
  } });
  await loader.refresh();
  assert.equal(calls, 4);
  assert.deepEqual(loader.getSnapshot().sections.descriptive.data.items, []);
  assert.equal(loader.getSnapshot().sections.descriptive.status, "ready");
  assert.equal(loader.getSnapshot().sections.diagnostic.status, "error");
});

test("an expired snapshot is hidden after offline sleep and recovers on reconnect", async (t) => {
  let online = true;
  let clock = 1;
  const loader = setup(t, { now: () => clock, isOnline: () => online, request: async (section) => response(section) });
  await loader.refresh();
  online = false;
  loader.connectionChanged();
  clock += 16 * 60 * 1000;
  await loader.refresh();
  assert.equal(loader.getSnapshot().sections.descriptive.data, null);
  online = true;
  loader.connectionChanged();
  await tick();
  assert.equal(loader.getSnapshot().sections.descriptive.status, "ready");
});

test("focus recovery clears a stale offline state when a suspended tab missed online", async (t) => {
  let online = false;
  const loader = setup(t, { isOnline: () => online, request: async (section) => response(section) });
  await loader.refresh();
  assert.equal(loader.getSnapshot().offline, true);
  online = true;
  await loader.refresh();
  assert.equal(loader.getSnapshot().offline, false);
  assert.equal(loader.getSnapshot().sections.descriptive.status, "ready");
});

test("Overview summary finishes independently while rankings remain pending", async (t) => {
  const rankings = deferred();
  const calls = [];
  const loader = setup(t, {
    sectionNames: ["summary", "prescriptive"],
    request: async (section) => {
      calls.push(section);
      if (section === "prescriptive") await rankings.promise;
      return response(section, 17);
    },
  });
  const flight = loader.refresh();
  void loader.refresh(true);
  await tick();
  assert.deepEqual(calls, ["summary", "prescriptive"]);
  assert.equal(loader.getSnapshot().sections.summary.data.value, 17);
  assert.equal(loader.getSnapshot().sections.summary.updating, false);
  assert.equal(loader.getSnapshot().sections.prescriptive.status, "loading");
  rankings.resolve();
  await flight;
});

test("a missing section is an error rather than an endless loading state or a fake zero", async (t) => {
  const loader = setup(t, { sectionNames: ["summary"], request: async () => ({}) });
  await loader.refresh();
  assert.equal(loader.getSnapshot().sections.summary.status, "error");
  assert.equal(loader.getSnapshot().sections.summary.updating, false);
  assert.equal(loader.getSnapshot().sections.summary.data, null);
});
