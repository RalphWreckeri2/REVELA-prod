import { useCallback, useContext, useEffect, useRef, useSyncExternalStore } from "react";
import { RefreshContext } from "./appRefreshContext.js";

export function useRefreshCoordinator() {
  return useContext(RefreshContext);
}

export function useRefreshSnapshot() {
  const coordinator = useRefreshCoordinator();
  const subscribe = useCallback(listener => coordinator?.subscribe(listener) ?? (() => {}), [coordinator]);
  const getSnapshot = useCallback(() => coordinator?.snapshot(), [coordinator]);
  return useSyncExternalStore(subscribe, getSnapshot);
}

export function useAppDataRefresh(key, operation) {
  const coordinator = useRefreshCoordinator();
  const latest = useRef(operation);
  useEffect(() => { latest.current = operation; });
  useEffect(() => {
    if (!coordinator || !key) return undefined;
    return coordinator.register(key, reason => latest.current(reason));
  }, [coordinator, key]);
  return useCallback(() => coordinator?.run("manual", key), [coordinator, key]);
}

export async function refreshResults(requests) {
  const results = await Promise.allSettled(requests);
  const failed = results.filter(result => result.status === "rejected" || result.value === false || result.value?.ok === false);
  return { ok: failed.length === 0, status: failed.length === 0 ? "success" : failed.length === results.length ? "failure" : "partial-failure" };
}
