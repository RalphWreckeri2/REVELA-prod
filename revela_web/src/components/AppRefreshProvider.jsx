import { useEffect, useMemo } from "react";
import { useAuth } from "../context/authContext";
import { createAppRefreshCoordinator } from "../services/appRefreshCoordinator";
import { RefreshContext } from "./appRefreshContext";

const EVENT_VIEWS = {
  "inspection-update": ["home", "map", "analytics", "inspections", "reports", "calendar"],
  "yellow-flag": ["home", "map", "analytics"],
  "flag-update": ["home", "map", "analytics", "inspections", "reports"],
  "registry-update": ["home", "map", "analytics", "registry", "inspections", "reports"],
  "registry-progress": ["registry"],
  "user-update": ["home", "map", "analytics", "inspections", "users"],
  "password-reset": ["users"],
};

export function AppRefreshProvider({ children }) {
  const { user } = useAuth();
  const userId = user?.id ?? user?.userID;
  const coordinator = useMemo(() => userId == null ? null : createAppRefreshCoordinator({
    userId, storage: window.localStorage,
  }), [userId]);
  useEffect(() => {
    if (!coordinator) return undefined;
    const check = () => coordinator.availabilityChanged();
    window.addEventListener("focus", check);
    window.addEventListener("online", check);
    document.addEventListener("visibilitychange", check);
    const handlers = Object.entries(EVENT_VIEWS).map(([event, views]) => {
      const handler = () => coordinator.markStale(views);
      window.addEventListener(`revela:${event}`, handler);
      return [event, handler];
    });
    return () => {
      window.removeEventListener("focus", check);
      window.removeEventListener("online", check);
      document.removeEventListener("visibilitychange", check);
      handlers.forEach(([event, handler]) => window.removeEventListener(`revela:${event}`, handler));
      coordinator.dispose();
    };
  }, [coordinator]);
  return <RefreshContext.Provider value={coordinator}>{children}</RefreshContext.Provider>;
}
