import {
  createContext,
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";
import { useLocation } from "react-router-dom";
import { useAuth } from "../context/authContext";
import { recordActivityRequest } from "../services/api";
import InactivityWarningModal from "./InactivityWarningModal";
import {
  ACTIVITY_EVENTS,
  IDLE_LIMIT_MS,
  INACTIVITY_NOTICE,
  LAST_ACTIVITY_KEY,
  SIGNAL_KEY,
  SESSION_NOTICE_KEY,
  WARNING_AT_MS,
  delayUntil,
  isExpired,
  resolveActivitySignal,
  restoreActivity,
  shouldBroadcastActivity,
  shouldSendHeartbeat,
} from "./inactivityPolicy";

const InactivityContext = createContext(null);

function readPersistedActivity() {
  try {
    const raw = window.localStorage.getItem(LAST_ACTIVITY_KEY);
    return restoreActivity(raw, Date.now());
  } catch {
    return Date.now();
  }
}

export default function InactivityProvider({ children }) {
  const { token, logout } = useAuth();
  const location = useLocation();

  const [showWarning, setShowWarning] = useState(false);
  // Seeded with "now" and replaced by the persisted value once the session
  // effect runs, so this ref is never briefly a non-timestamp.
  const lastActivityRef = useRef(() => Date.now());
  const lastHeartbeatRef = useRef(0);
  const lastBroadcastRef = useRef(0);
  const endedRef = useRef(false);
  const warningTimerRef = useRef(null);
  const logoutTimerRef = useRef(null);

  const isAuthenticated = Boolean(token);

  const persistActivity = useCallback((timestamp) => {
    try {
      window.localStorage.setItem(LAST_ACTIVITY_KEY, String(timestamp));
    } catch {
      /* storage full or blocked - the in-memory timer still works */
    }
  }, []);

  const signalOtherTabs = useCallback((message) => {
    try {
      // The nonce guarantees the stored value changes so `storage` fires even
      // when the payload is otherwise identical.
      window.localStorage.setItem(
        SIGNAL_KEY,
        JSON.stringify({ ...message, _nonce: Math.random() }),
      );
    } catch {
      /* ignore */
    }
  }, []);

  /** End the session locally and release it server-side. */
  const endSessionForInactivity = useCallback(() => {
    if (endedRef.current) return;
    endedRef.current = true;

    signalOtherTabs({ type: "expired", notice: INACTIVITY_NOTICE });
    try {
      window.sessionStorage.setItem(SESSION_NOTICE_KEY, INACTIVITY_NOTICE);
    } catch {
      /* ignore */
    }
    // Releases the session row so another device can sign in straight away.
    logout();
  }, [logout, signalOtherTabs]);

  const sendHeartbeat = useCallback(
    (force = false) => {
      const now = Date.now();
      if (!shouldSendHeartbeat(now, lastHeartbeatRef.current, force)) return;
      lastHeartbeatRef.current = now;
      if (!token) return;
      // A failed heartbeat (e.g. lost connectivity) is not fatal: the backend
      // still refuses the session, and the client-side timer still fires.
      void recordActivityRequest(token).catch(() => {});
    },
    [token],
  );

  const schedule = useCallback(() => {
    window.clearTimeout(warningTimerRef.current);
    window.clearTimeout(logoutTimerRef.current);

    const now = Date.now();
    if (isExpired(now, lastActivityRef.current)) {
      setShowWarning(false);
      endSessionForInactivity();
      return;
    }
    warningTimerRef.current = window.setTimeout(
      () => setShowWarning(true),
      delayUntil(WARNING_AT_MS, now, lastActivityRef.current),
    );
    logoutTimerRef.current = window.setTimeout(
      () => endSessionForInactivity(),
      delayUntil(IDLE_LIMIT_MS, now, lastActivityRef.current),
    );
  }, [endSessionForInactivity]);

  const markActivity = useCallback(
    ({ broadcast = false } = {}) => {
      if (!isAuthenticated || endedRef.current) return;
      const now = Date.now();
      lastActivityRef.current = now;
      persistActivity(now);
      setShowWarning(false);
      sendHeartbeat();
      schedule();

      if (broadcast && shouldBroadcastActivity(now, lastBroadcastRef.current)) {
        lastBroadcastRef.current = now;
        signalOtherTabs({ type: "activity", at: now });
      }
    },
    [
      isAuthenticated,
      persistActivity,
      schedule,
      sendHeartbeat,
      signalOtherTabs,
    ],
  );

  // Reset tracking whenever the session changes (login, logout, forced sign-out).
  useEffect(() => {
    if (!isAuthenticated) {
      // No setState here: the modal is already gated on `isAuthenticated`, so
      // clearing state would only trigger a redundant render.
      endedRef.current = false;
      lastActivityRef.current = Date.now();
      window.clearTimeout(warningTimerRef.current);
      window.clearTimeout(logoutTimerRef.current);
      return undefined;
    }
    // A refresh or reopened tab resumes the recorded idle time, so a browser
    // restart cannot silently hand out a fresh 10 minutes.
    lastActivityRef.current = readPersistedActivity();
    schedule();
    return () => {
      window.clearTimeout(warningTimerRef.current);
      window.clearTimeout(logoutTimerRef.current);
    };
  }, [isAuthenticated, schedule]);

  // Genuine user interaction.
  useEffect(() => {
    if (!isAuthenticated) return undefined;
    const handler = () => markActivity({ broadcast: true });
    ACTIVITY_EVENTS.forEach((name) =>
      window.addEventListener(name, handler, {
        capture: name === "scroll",
        passive: true,
      }),
    );
    return () => {
      ACTIVITY_EVENTS.forEach((name) =>
        window.removeEventListener(name, handler, {
          capture: name === "scroll",
        }),
      );
    };
  }, [isAuthenticated, markActivity]);

  // In-app navigation counts as activity (requirement 2).
  useEffect(() => {
    if (!isAuthenticated) return;
    markActivity({ broadcast: true });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [location.pathname, isAuthenticated]);

  // Background tabs have their timers throttled by the browser, so re-check the
  // real elapsed time whenever the tab becomes visible again.
  useEffect(() => {
    if (!isAuthenticated) return undefined;
    const recheck = () => {
      if (document.visibilityState !== "visible") return;
      schedule();
    };
    document.addEventListener("visibilitychange", recheck);
    window.addEventListener("focus", recheck);
    window.addEventListener("pageshow", recheck);
    return () => {
      document.removeEventListener("visibilitychange", recheck);
      window.removeEventListener("focus", recheck);
      window.removeEventListener("pageshow", recheck);
    };
  }, [isAuthenticated, schedule]);

  // Cross-tab coordination: activity anywhere keeps every tab alive, and an
  // inactivity logout in one tab ends the session in all of them.
  useEffect(() => {
    if (!isAuthenticated) return undefined;
    const onStorage = (event) => {
      if (event.key !== SIGNAL_KEY || !event.newValue) return;
      let message;
      try {
        message = JSON.parse(event.newValue);
      } catch {
        return;
      }
      if (message.type === "activity") {
        if (endedRef.current) return;
        const signal = resolveActivitySignal(message, {
          lastActivityAt: lastActivityRef.current,
        });
        // Stale signals are ignored so a slow tab cannot rewind the clock.
        if (!signal) return;
        lastActivityRef.current = signal.at;
        persistActivity(signal.at);
        setShowWarning(false);
        sendHeartbeat();
        schedule();
      } else if (message.type === "expired") {
        if (endedRef.current) return;
        endedRef.current = true;
        try {
          window.sessionStorage.setItem(
            SESSION_NOTICE_KEY,
            message.notice || INACTIVITY_NOTICE,
          );
        } catch {
          /* ignore */
        }
        logout();
      }
    };
    window.addEventListener("storage", onStorage);
    return () => window.removeEventListener("storage", onStorage);
  }, [
    isAuthenticated,
    logout,
    persistActivity,
    schedule,
    sendHeartbeat,
  ]);

  const stayLoggedIn = useCallback(() => {
    if (endedRef.current) return;
    const now = Date.now();
    lastActivityRef.current = now;
    persistActivity(now);
    setShowWarning(false);
    sendHeartbeat(true);
    schedule();
    signalOtherTabs({ type: "activity", at: now });
  }, [persistActivity, schedule, sendHeartbeat, signalOtherTabs]);

  return (
    <InactivityContext.Provider
      value={{
        showWarning,
        stayLoggedIn,
        markActivity: () => markActivity({ broadcast: true }),
        idleLimitMs: IDLE_LIMIT_MS,
        warningAtMs: WARNING_AT_MS,
      }}
    >
      {children}
      {showWarning && isAuthenticated && (
        <InactivityWarningModal
          onStayLoggedIn={stayLoggedIn}
          onLogout={endSessionForInactivity}
        />
      )}
    </InactivityContext.Provider>
  );
}