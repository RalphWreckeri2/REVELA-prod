import test from "node:test";
import assert from "node:assert/strict";
import { createAppRefreshCoordinator, REFRESH_MODES, refreshPreferenceKey } from "./appRefreshCoordinator.js";

const flush = async () => { await Promise.resolve(); await Promise.resolve(); await Promise.resolve(); };
function fixture(saved) {
  let time = 1_000_000;
  let visible = true;
  let online = true;
  const timers = new Map();
  let nextId = 0;
  const storage = new Map(saved);
  const coordinator = createAppRefreshCoordinator({ userId: 17,
    storage: { getItem: key => storage.get(key), setItem: (key, value) => storage.set(key, value) },
    now: () => time, isAvailable: () => visible && online,
    schedule: (fn, ms) => { const id = ++nextId; timers.set(id, { fn, due: time + ms }); return id; },
    cancel: id => timers.delete(id),
  });
  return { coordinator, storage, timers, advance: async ms => {
    time += ms;
    for (const [id, timer] of [...timers]) if (timer.due <= time) { timers.delete(id); timer.fn(); }
    await flush();
  }, setVisible: value => { visible = value; coordinator.availabilityChanged(); },
  setOnline: value => { online = value; coordinator.availabilityChanged(); }, now: () => time };
}

test("Medium is the default; all four modes persist per user and recalculate from success", async () => {
  const f = fixture();
  assert.equal(f.coordinator.snapshot().mode, "medium");
  let calls = 0;
  f.coordinator.register("home", async () => { calls++; return { ok: true }; });
  await flush();
  assert.equal(calls, 1);
  const last = f.coordinator.snapshot().lastSuccess;
  for (const [name, interval] of Object.entries(REFRESH_MODES)) {
    f.coordinator.setMode(name);
    assert.equal(f.coordinator.snapshot().nextRefresh, last + interval);
    assert.equal(f.coordinator.snapshot().lastSuccess, last);
    assert.equal(f.storage.get(refreshPreferenceKey(17)), name);
    assert.equal(fixture(f.storage).coordinator.snapshot().mode, name);
  }
  assert.equal(fixture().coordinator.snapshot().mode, "medium");
  f.coordinator.dispose();
});

test("view and query identity stay isolated across navigation and filter changes", async () => {
  const f = fixture();
  const calls = [];
  let remove = f.coordinator.register("registry:[1]", async () => { calls.push("one"); return { ok: true }; });
  await flush();
  const registryTime = f.coordinator.snapshot().lastSuccess;
  remove();
  remove = f.coordinator.register("registry:[2]", async () => { calls.push("two"); return { ok: true }; });
  await flush();
  f.coordinator.markStale(["registry"]);
  assert.equal(f.coordinator.snapshot().stale, true);
  assert.deepEqual(calls, ["one", "two"]);
  remove();
  f.coordinator.register("home", async () => { calls.push("home"); return { ok: true }; });
  await flush();
  assert.equal(f.coordinator.snapshot().stale, false);
  assert.equal(f.coordinator.snapshot().lastSuccess, registryTime);
  assert.deepEqual(calls, ["one", "two", "home"]);
  f.coordinator.dispose();
});

test("passive stale events never fetch; hidden/offline resume runs at most one due refresh", async () => {
  const f = fixture();
  let calls = 0;
  f.coordinator.setMode("hard");
  f.coordinator.register("map", async () => { calls++; return { ok: true }; });
  await flush();
  f.coordinator.markStale(["map"]);
  assert.equal(calls, 1);
  assert.equal(f.coordinator.snapshot().stale, true);
  f.setVisible(false);
  await f.advance(3 * REFRESH_MODES.hard);
  assert.equal(calls, 1);
  f.setOnline(false);
  f.setVisible(true);
  await flush();
  assert.equal(calls, 1);
  f.setOnline(true);
  f.coordinator.availabilityChanged();
  await flush();
  assert.equal(calls, 2);
  assert.equal(f.coordinator.snapshot().stale, false);
  f.coordinator.dispose();
});

test("manual joins active work, waits for completion and only all-success resets the deadline", async () => {
  const f = fixture();
  let resolve;
  let calls = 0;
  f.coordinator.register("reports", () => {
    calls++;
    return new Promise(done => { resolve = done; });
  });
  await flush();
  const first = f.coordinator.run("manual");
  assert.equal(f.coordinator.snapshot().status, "loading");
  assert.equal(calls, 1);
  resolve({ ok: true });
  await first;
  assert.equal(f.coordinator.snapshot().status, "success");
  const previous = f.coordinator.snapshot().lastSuccess;
  await f.advance(10_000);
  const partial = f.coordinator.run("manual");
  resolve({ ok: false, status: "partial-failure" });
  await partial;
  assert.equal(f.coordinator.snapshot().status, "partial-failure");
  assert.equal(f.coordinator.snapshot().lastSuccess, previous);
  const failure = f.coordinator.run("manual");
  resolve({ ok: false, status: "failure" });
  await failure;
  assert.equal(f.coordinator.snapshot().status, "failure");
  assert.equal(f.coordinator.snapshot().lastSuccess, previous);
  f.coordinator.dispose();
});

test("an overdue failing view waits for backoff rather than looping", async () => {
  const f = fixture();
  let calls = 0;
  f.coordinator.setMode("hard");
  f.coordinator.register("users", async () => { calls++; return { ok: calls === 1 }; });
  await flush();
  await f.advance(60_000);
  assert.equal(calls, 2);
  await f.advance(1);
  f.coordinator.availabilityChanged();
  assert.equal(calls, 2);
  await f.advance(60_000);
  assert.equal(calls, 3);
  f.coordinator.dispose();
});

test("an old query's late completion cannot refresh the new query; events during a flight remain stale", async () => {
  const f = fixture();
  let finishOld;
  const removeOld = f.coordinator.register("registry:old", () => new Promise(resolve => { finishOld = resolve; }));
  await flush();
  removeOld();
  let finishNew;
  f.coordinator.register("registry:new", () => new Promise(resolve => { finishNew = resolve; }));
  await flush();
  f.coordinator.markStale(["registry"]);
  finishOld({ ok: true });
  await flush();
  assert.equal(f.coordinator.snapshot().activeKey, "registry:new");
  assert.equal(f.coordinator.snapshot().lastSuccess, null);
  finishNew({ ok: true });
  await flush();
  assert.equal(f.coordinator.snapshot().stale, true);
  assert.equal(f.coordinator.snapshot().lastSuccess, f.now());
  f.coordinator.dispose();
});
