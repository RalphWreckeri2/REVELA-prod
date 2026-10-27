import {
  analyticsRefreshPending, analyticsSnapshotDeadline, analyticsSnapshotExpired,
} from "../components/analyticsCachePolicy.js";

export const ANALYTICS_SECTIONS = ["descriptive", "diagnostic", "prescriptive", "operations"];

function abortableDelay(ms, signal) {
  return new Promise((resolve, reject) => {
    const abort = () => { clearTimeout(timer); reject(new DOMException("Aborted", "AbortError")); };
    const timer = setTimeout(() => { signal.removeEventListener("abort", abort); resolve(); }, ms);
    signal.addEventListener("abort", abort, { once: true });
    if (signal.aborted) abort();
  });
}

/** One coordinator per token/filter scope. All triggers join its active requests. */
export function createAnalyticsLoader({
  request, isOnline = () => navigator.onLine, now = () => performance.now(),
  delay = abortableDelay, timeoutMs = 20000, maxRetries = 2, maxPendingPolls = 45,
  sectionNames = ANALYTICS_SECTIONS,
}) {
  let state = {
    offline: !isOnline(),
    sections: Object.fromEntries(sectionNames.map((name) => [name, {
      data: null, status: isOnline() ? "loading" : "offline", updating: false, error: null, metadata: null,
    }])),
  };
  const listeners = new Set();
  const flights = new Map();
  const expiryTimers = new Map();
  let generation = 0;

  const emit = (name, changes) => {
    state = { ...state, sections: { ...state.sections, [name]: { ...state.sections[name], ...changes } } };
    listeners.forEach((listener) => listener());
  };
  const expire = (name) => {
    const section = state.sections[name];
    if (section.data && analyticsSnapshotExpired(section, now())) {
      emit(name, { status: "expired" });
    }
  };

  async function load(name, force) {
    if (flights.has(name)) return flights.get(name).promise;
    const previous = state.sections[name];
    if (!force && (previous.error || (previous.fetchedAt && now() - previous.fetchedAt < 1000))) return;
    const scope = generation;
    const lifetime = new AbortController();
    const flight = { controller: lifetime, promise: null };
    flights.set(name, flight);
    emit(name, { status: previous.data ? "ready" : "loading", updating: true, error: null });
    flight.promise = (async () => {
      let failures = 0;
      let polls = 0;
      try {
        while (!lifetime.signal.aborted && scope === generation) {
          const attempt = new AbortController();
          const abort = () => attempt.abort();
          lifetime.signal.addEventListener("abort", abort, { once: true });
          let timedOut = false;
          const timer = setTimeout(() => { timedOut = true; attempt.abort(); }, timeoutMs);
          const started = now();
          const wallStarted = Date.now();
          let json;
          try {
            json = await request(name, attempt.signal);
          } catch (cause) {
            if (lifetime.signal.aborted || scope !== generation) return;
            const preparing = cause.responseData?.analytics_cache;
            if (preparing?.expired) {
              emit(name, { status: previous.data ? "expired" : "loading" });
              if (analyticsRefreshPending(preparing) && !preparing.refresh_failed) {
                // An expired snapshot's 503 is also the server's signal that a
                // replacement is being prepared. Poll it within the cold-load
                // bound instead of exhausting failure retries prematurely.
                json = { analytics_cache: { ...preparing, loading: true } };
              }
            }
            const error = timedOut ? new Error("Analytics request timed out. Please retry.") : cause;
            if (!json) {
              if (!isOnline()) throw error;
              const retryable = timedOut || !error.status || [408, 429, 500, 502, 503, 504].includes(error.status);
              if (!retryable || failures >= maxRetries) throw error;
              failures += 1;
              await delay(Math.max(1000 * 2 ** (failures - 1),
                (error.responseData?.analytics_cache?.retry_after_seconds || 0) * 1000), lifetime.signal);
              continue;
            }
          } finally {
            clearTimeout(timer);
            lifetime.signal.removeEventListener("abort", abort);
          }
          // Abort is advisory; some mocked/cached transports can resolve after it.
          if (lifetime.signal.aborted || scope !== generation) return;
          const metadata = json.analytics_cache;
          if (!json[name] && !metadata?.loading && !analyticsRefreshPending(metadata)) {
            throw new Error("The server returned no data for this section. Please retry.");
          }
          if (json[name]) {
            const snapshot = {
              expiresAt: analyticsSnapshotDeadline(metadata, started),
              wallExpiresAt: analyticsSnapshotDeadline(metadata, wallStarted),
            };
            const expired = analyticsSnapshotExpired(snapshot, now());
            emit(name, {
              ...snapshot, data: expired ? previous.data : json[name], metadata: expired && previous.data ? previous.metadata : metadata,
              status: expired ? "expired" : "ready", error: null, fetchedAt: now(),
            });
            clearTimeout(expiryTimers.get(name));
            expiryTimers.set(name, setTimeout(() => expire(name),
              Math.max(1, Math.min(snapshot.expiresAt - now(), snapshot.wallExpiresAt - Date.now()) + 1)));
          }
          if (metadata?.refresh_failed) throw new Error("The background refresh failed. Your last available data is shown.");
          if (!metadata?.loading && !analyticsRefreshPending(metadata)) break;
          if (++polls >= maxPendingPolls) throw new Error("Analytics is taking longer than expected. Please retry.");
          await delay(2000, lifetime.signal);
        }
      } catch (error) {
        if (lifetime.signal.aborted || scope !== generation) return;
        emit(name, { status: state.sections[name].data && analyticsSnapshotExpired(state.sections[name], now())
          ? "expired" : !isOnline() ? "offline" : "error", error: error.message });
      } finally {
        if (flights.get(name) === flight) {
          flights.delete(name);
          emit(name, { updating: false });
        }
      }
    })();
    return flight.promise;
  }

  return {
    subscribe(listener) { listeners.add(listener); return () => listeners.delete(listener); },
    getSnapshot: () => state,
    recheck() {
      sectionNames.forEach((name) => {
        expire(name);
        const section = state.sections[name];
        clearTimeout(expiryTimers.get(name));
        if (section.data && section.status !== "expired") {
          const remaining = Math.min(section.expiresAt - now(), section.wallExpiresAt - Date.now());
          expiryTimers.set(name, setTimeout(() => expire(name), Math.max(1, remaining + 1)));
        }
      });
    },
    refresh(force = false) {
      sectionNames.forEach(expire);
      if (!isOnline()) { this.connectionChanged(); return Promise.resolve(); }
      // Focus/visibility can be the first signal after a suspended tab missed
      // the browser's online event. Clear the offline state and retry once.
      if (state.offline) {
        state = { ...state, offline: false };
        force = true;
        listeners.forEach((listener) => listener());
      }
      return Promise.all(sectionNames.map((name) => load(name, force)));
    },
    connectionChanged() {
      const offline = !isOnline();
      const wasOffline = state.offline;
      state = { ...state, offline };
      if (offline) {
        this.stop(false);
        sectionNames.forEach((name) => emit(name, { status: state.sections[name].data && analyticsSnapshotExpired(state.sections[name], now()) ? "expired" : "offline", updating: false }));
      } else if (wasOffline) {
        void this.refresh(true);
      }
      listeners.forEach((listener) => listener());
    },
    stop(cancelExpiry = true) {
      generation += 1;
      flights.forEach(({ controller }) => controller.abort());
      flights.clear();
      if (cancelExpiry) {
        expiryTimers.forEach(clearTimeout);
        expiryTimers.clear();
      }
    },
  };
}
