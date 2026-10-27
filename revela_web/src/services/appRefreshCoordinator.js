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
  const listeners = new Set();
  let active = null;
  let timer = null;
  let serial = 0;
  let status = "idle";
  let currentSnapshot;
  const notify = () => { currentSnapshot = makeSnapshot(); listeners.forEach(listener => listener()); };
  const record = key => {
    if (!records.has(key)) records.set(key, { lastSuccess: null, stale: false, staleEpoch: 0, retryAt: 0, flight: null });
    return records.get(key);
  };
  const deadline = key => {
    const last = records.get(key)?.lastSuccess;
    return last == null ? null : last + REFRESH_MODES[mode];
  };
  const makeSnapshot = () => ({ mode, activeKey: active?.key ?? null,
    lastSuccess: active ? record(active.key).lastSuccess : null,
    nextRefresh: active ? deadline(active.key) : null,
    stale: active ? record(active.key).stale : false, status });
  currentSnapshot = makeSnapshot();
  const clear = () => { if (timer != null) cancel(timer); timer = null; };
  const arm = () => {
    clear();
    if (!active || !isAvailable()) return;
    const entry = record(active.key);
    if (entry.flight) return;
    const due = deadline(active.key);
    if (due == null && !entry.retryAt) return; // initial load belongs to registration
    const next = Math.max(due ?? 0, entry.retryAt);
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
    clear(); notify();
    const flight = (async () => {
      let result;
      try {
        result = await operation(reason);
        if (!result || result.ok !== true) result = { ok: false, status: result?.status || "failure" };
      } catch (error) { result = { ok: false, status: "failure", error }; }
      if (active?.key === key && generation === serial) {
        if (result.ok) {
          entry.lastSuccess = now();
          if (entry.staleEpoch === staleEpoch) entry.stale = false;
          entry.retryAt = 0;
        } else {
          entry.retryAt = now() + 60_000;
        }
        status = result.ok ? "success" : result.status;
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
    if ((due == null && !entry.retryAt) || (due != null && due > now()) || entry.retryAt > now()) { arm(); return Promise.resolve(null); }
    return run("scheduled");
  }
  function register(key, refresh) {
    serial++;
    active = { key, refresh };
    record(key).flight = null;
    status = "idle";
    notify();
    // A view mount or filter change always reads its own current query, even if
    // another view (or the same view on a previous visit) was recently loaded.
    queueMicrotask(() => { if (active?.key === key && active.refresh === refresh) void run("initial", key); });
    return () => {
      if (active?.key !== key || active.refresh !== refresh) return;
      serial++; active = null; clear(); status = "idle"; notify();
    };
  }
  return {
    subscribe(listener) { listeners.add(listener); return () => listeners.delete(listener); },
    snapshot: () => currentSnapshot,
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
    dispose() { clear(); active = null; serial++; listeners.clear(); },
  };
}
