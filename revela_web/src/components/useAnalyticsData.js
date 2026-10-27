import { useEffect, useMemo, useSyncExternalStore } from "react";
import { getAnalyticsOverviewRequest } from "../services/api";
import { ANALYTICS_SECTIONS, createAnalyticsLoader } from "../services/analyticsLoader";
import { useAppDataRefresh, useRefreshCoordinator } from "./useAppDataRefresh";
import { refreshResults } from "./useAppDataRefresh";

export function useAnalyticsData(token, filters, sectionNames = ANALYTICS_SECTIONS, view = "analytics", additionalRefresh) {
  const coordinator = useRefreshCoordinator();
  const key = view ? `${view}:${JSON.stringify(filters ?? {})}` : "home";
  const loaderKey = `analytics-loader:${key}:${sectionNames.join(",")}`;
  const loader = useMemo(() => (coordinator?.resource(loaderKey, () => createAnalyticsLoader({
    sectionNames,
    request: (section, signal) => getAnalyticsOverviewRequest(token, filters, {
      section, signal, staleWhileRevalidate: true,
    }),
  })) ?? createAnalyticsLoader({
    sectionNames, request: (section, signal) => getAnalyticsOverviewRequest(token, filters, { section, signal, staleWhileRevalidate: true }),
  })), [coordinator, loaderKey, token, filters, sectionNames]);
  const state = useSyncExternalStore(loader.subscribe, loader.getSnapshot);
  const refreshOperation = async () => {
    const analyticsRead = async () => {
      await loader.refresh(true);
      const sections = Object.values(loader.getSnapshot().sections);
      const succeeded = sections.filter(section => section.data && !section.error && section.status !== "expired").length;
      if (sections.some(section => section.data)) coordinator?.markAvailable(key);
      return { ok: succeeded === sections.length, status: succeeded === sections.length ? "success" : succeeded ? "partial-failure" : "failure" };
    };
    return additionalRefresh ? refreshResults([analyticsRead(), additionalRefresh()]) : analyticsRead();
  };
  const registeredRefresh = useAppDataRefresh(view ? key : null, refreshOperation);
  useEffect(() => {
    if (!token) return undefined;
    loader.recheck();
    return () => {
      loader.stop();
    };
  }, [loader, token]);
  return { ...state, refresh: view ? registeredRefresh : refreshOperation };
}
