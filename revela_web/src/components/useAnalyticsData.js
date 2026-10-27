import { useEffect, useMemo, useSyncExternalStore } from "react";
import { getAnalyticsOverviewRequest } from "../services/api";
import { ANALYTICS_SECTIONS, createAnalyticsLoader } from "../services/analyticsLoader";
import { useAppDataRefresh } from "./useAppDataRefresh";
import { refreshResults } from "./useAppDataRefresh";

export function useAnalyticsData(token, filters, sectionNames = ANALYTICS_SECTIONS, view = "analytics", additionalRefresh) {
  const loader = useMemo(() => createAnalyticsLoader({
    sectionNames,
    request: (section, signal) => getAnalyticsOverviewRequest(token, filters, {
      section, signal, staleWhileRevalidate: true,
    }),
  }), [token, filters, sectionNames]);
  const state = useSyncExternalStore(loader.subscribe, loader.getSnapshot);
  const key = `${view}:${JSON.stringify(filters ?? {})}`;
  const refreshOperation = async () => {
    const analyticsRead = async () => {
      await loader.refresh(true);
      const sections = Object.values(loader.getSnapshot().sections);
      const succeeded = sections.filter(section => section.data && !section.error && section.status !== "expired").length;
      return { ok: succeeded === sections.length, status: succeeded === sections.length ? "success" : succeeded ? "partial-failure" : "failure" };
    };
    return additionalRefresh ? refreshResults([analyticsRead(), additionalRefresh()]) : analyticsRead();
  };
  const registeredRefresh = useAppDataRefresh(view ? key : null, refreshOperation);
  useEffect(() => {
    if (!token) return undefined;
    return () => {
      loader.stop();
    };
  }, [loader, token]);
  return { ...state, refresh: view ? registeredRefresh : refreshOperation };
}
