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

/** In-memory, account-scoped dataset. Undefined means it has never loaded; [] is usable data. */
export function useSessionDataset(key, name, emptyValue, owner = key) {
  const coordinator = useRefreshCoordinator();
  const subscribe = useCallback(listener => coordinator?.subscribe(listener) ?? (() => {}), [coordinator]);
  const getSnapshot = useCallback(() => coordinator?.readData(key, name), [coordinator, key, name]);
  const cached = useSyncExternalStore(subscribe, getSnapshot);
  const initialValue = useRef(emptyValue);
  const mounted = useRef(false);
  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; };
  }, []);
  const setCached = useCallback(value => {
    if (!mounted.current) return false;
    const previous = coordinator?.readData(key, name);
    return coordinator?.writeData(key, name, typeof value === "function" ? value(previous ?? initialValue.current) : value, owner);
  }, [coordinator, key, name, owner]);
  return [cached === undefined ? emptyValue : cached, setCached, cached !== undefined];
}

export async function refreshResults(requests) {
  const results = await Promise.allSettled(requests);
  const failed = results.flatMap((result, index) => {
    if (result.status === "fulfilled" && result.value !== false && result.value?.ok !== false) return [];
    const reason = result.status === "rejected" ? result.reason : result.value?.error;
    return [`Request ${index + 1}: ${reason?.message || (typeof reason === "string" ? reason : "Could not update")}`];
  });
  return { ok: failed.length === 0, status: failed.length === 0 ? "success" : failed.length === results.length ? "failure" : "partial-failure", errors: failed };
}
