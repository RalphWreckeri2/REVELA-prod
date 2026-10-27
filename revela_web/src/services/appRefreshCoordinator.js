export const REFRESH_MODES = Object.freeze({
  hard: 60_000, medium: 15 * 60_000, easy: 60 * 60_000, lax: 24 * 60 * 60_000,
});

export const refreshPreferenceKey = userId => `revela_app_refresh_mode_${userId}`;

export function createAppRefreshCoordinator({ userId, storage, now = Date.now,
  isAvailable = () => document.visibilityState === "visible" && navigator.onLine,
  schedule = (fn, ms) => setTimeout(fn, ms), cancel = clearTimeout } = {}) {
  let mode;
  try { mode = storage?.getItem(refreshPreferenceKey(userId)); } catch { /* private browsing */ }
  if (!Object.hasOwn(REFRESH_MODES, mode)) mode = "medium";
  const records = new Map();
  const resources = new Map();
  const listeners = new Set();
  let active = null;
  let timer = null;
  let serial = 0;
  let status = "idle";
  let errors = [];
  let currentSnapshot;
  const notify = () => { currentSnapshot = makeSnapshot(); listeners.forEach(listener => listener()); };
  const record = key => {
    if (!records.has(key)) records.set(key, { lastSuccess: null, stale: false, staleEpoch: 0, retryAt: 0, flight: null, datasets: {}, available: false, invalidated: false, lastStatus: "idle", errors: [] });
    return records.get(key);
  };
  const deadline = key => {
    const last = records.get(key)?.lastSuccess;
    return last == null ? null : last + REFRESH_MODES[mode];
  };
  const makeSnapshot = () => ({ mode, activeKey: active?.key ?? null,
    lastSuccess: active ? record(active.key).lastSuccess : null,
    nextRefresh: active ? deadline(active.key) : null,
    stale: active ? record(active.key).stale : false, status, errors });
  currentSnapshot = makeSnapshot();
  const clear = () => { if (timer != null) cancel(timer); timer = null; };
  const arm = () => {
    clear();
    if (!active || !isAvailable()) return;
    const entry = record(active.key);
    if (entry.flight) return;
    const due = deadline(active.key);
    if (due == null && !entry.retryAt && !entry.available) return; // uncached initial load belongs to registration
    const next = Math.max(entry.invalidated ? 0 : due ?? 0, entry.retryAt);
    timer = schedule(() => { timer = null; void checkDue(); }, Math.max(0, next - now()));
  };
  async function run(reason = "manual", key = active?.key) {
    if (!active || active.key !== key) return { ok: false, status: "failure" };
    const entry = record(key);
    if (entry.flight) return entry.flight;
    const operation = active.refresh;
    const generation = serial;
    const staleEpoch = entry.staleEpoch;
    status = "loading";
    errors = [];
    clear(); notify();
    const flight = (async () => {
      let result;
      try {
        result = await operation(reason);
        if (!result || result.ok !== true) result = { ok: false, status: result?.status || "failure", errors: result?.errors || (result?.error ? [result.error.message || String(result.error)] : []) };
      } catch (error) { result = { ok: false, status: "failure", error }; }
      if (active?.key === key && generation === serial) {
        if (result.ok) {
          entry.lastSuccess = now();
          entry.invalidated = false;
          if (entry.staleEpoch === staleEpoch) entry.stale = false;
          entry.retryAt = 0;
        } else {
          entry.retryAt = now() + 60_000;
        }
        status = result.ok ? "success" : result.status;
        errors = result.ok ? [] : result.errors?.length ? result.errors : ["Refresh could not complete. Check the current page for more information."];
        entry.lastStatus = status;
        entry.errors = errors;
        notify();
      }
      return result;
    })();
    entry.flight = flight;
    try { return await flight; } finally {
      if (entry.flight === flight) entry.flight = null;
      arm();
    }
  }
  function checkDue() {
    if (!active || !isAvailable()) { arm(); return Promise.resolve(null); }
    const entry = record(active.key);
    const due = deadline(active.key);
    if ((!entry.invalidated && due != null && due > now()) || entry.retryAt > now()) { arm(); return Promise.resolve(null); }
    return run("scheduled");
  }
  function register(key, refresh) {
    serial++;
    active = { key, refresh };
    record(key).flight = null;
    status = record(key).lastStatus;
    errors = record(key).errors;
    notify();
    queueMicrotask(() => {
      if (active?.key !== key || active.refresh !== refresh) return;
      const entry = record(key);
      const hasData = entry.available || Object.keys(entry.datasets).length > 0;
      if (!hasData) void run("initial", key);
      else void checkDue(); // cached view is already painted; only refetch when due
    });
    return () => {
      if (active?.key !== key || active.refresh !== refresh) return;
      serial++; active = null; clear(); status = "idle"; errors = []; notify();
    };
  }
  return {
    subscribe(listener) { listeners.add(listener); return () => listeners.delete(listener); },
    snapshot: () => currentSnapshot,
    readData(key, name) { return records.get(key)?.datasets[name]; },
    writeData(key, name, value, owner = key) {
      if (active?.key !== owner) return false;
      const entry = record(key);
      entry.datasets = { ...entry.datasets, [name]: value };
      entry.available = true;
      notify();
      return true;
    },
    markAvailable(key) { record(key).available = true; },
    resource(key, factory) {
      if (!resources.has(key)) resources.set(key, factory());
      return resources.get(key);
    },
    invalidate(prefixes) {
      for (const [key, entry] of records) {
        if (prefixes.some(prefix => key === prefix || key.startsWith(`${prefix}:`))) {
          entry.invalidated = true;
          entry.stale = true;
          entry.staleEpoch++;
        }
      }
      notify();
    },
    register, run, checkDue,
    markStale(keys) {
      for (const key of records.keys()) {
        if (keys.some(prefix => key === prefix || key.startsWith(`${prefix}:`))) {
          record(key).stale = true;
          record(key).staleEpoch++;
        }
      }
      notify(); // no network request, no deadline reset
    },
    setMode(next) {
      if (!Object.hasOwn(REFRESH_MODES, next)) return;
      mode = next;
      try { storage?.setItem(refreshPreferenceKey(userId), mode); } catch { /* private browsing */ }
      notify(); arm();
    },
    availabilityChanged() { void checkDue(); },
    dispose() { clear(); active = null; serial++; resources.forEach(value => value.stop?.()); resources.clear(); records.clear(); listeners.clear(); },
  };
}
