import { useCallback, useEffect, useMemo, useSyncExternalStore } from "react";
import { getAnalyticsOverviewRequest } from "../services/api";
import { ANALYTICS_SECTIONS, createAnalyticsLoader } from "../services/analyticsLoader";

export function useAnalyticsData(token, filters, sectionNames = ANALYTICS_SECTIONS, pollIntervalMs = 30000) {
  const loader = useMemo(() => createAnalyticsLoader({
    sectionNames,
    request: (section, signal) => getAnalyticsOverviewRequest(token, filters, {
      section, signal, staleWhileRevalidate: true,
    }),
  }), [token, filters, sectionNames]);
  const state = useSyncExternalStore(loader.subscribe, loader.getSnapshot);
  useEffect(() => {
    if (!token) return undefined;
    // StrictMode's discarded effect never starts a duplicate request.
    let current = true;
    queueMicrotask(() => { if (current) void loader.refresh(true); });
    const refresh = () => { if (document.visibilityState === "visible") void loader.refresh(); };
    const sync = () => { void loader.refresh(true); };
    const connection = () => loader.connectionChanged();
    const events = ["inspection-update", "yellow-flag", "flag-update", "registry-update", "user-update", "global-refresh"];
    events.forEach((event) => window.addEventListener(`revela:${event}`, sync));
    window.addEventListener("online", connection);
    window.addEventListener("offline", connection);
    window.addEventListener("focus", refresh);
    document.addEventListener("visibilitychange", refresh);
    const timer = setInterval(refresh, pollIntervalMs);
    return () => {
      current = false;
      loader.stop();
      clearInterval(timer);
      events.forEach((event) => window.removeEventListener(`revela:${event}`, sync));
      window.removeEventListener("online", connection);
      window.removeEventListener("offline", connection);
      window.removeEventListener("focus", refresh);
      document.removeEventListener("visibilitychange", refresh);
    };
  }, [loader, token, pollIntervalMs]);
  const refresh = useCallback(() => loader.refresh(true), [loader]);
  return { ...state, refresh };
}
