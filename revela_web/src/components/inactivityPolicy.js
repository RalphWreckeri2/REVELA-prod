/**
 * Pure inactivity policy for the web admin portal.
 *
 * Extracted from the React provider so the timing rules can be unit-tested
 * without a DOM or a component runner. `InactivityProvider` owns the timers,
 * listeners and network calls; this module owns only the decisions.
 */

export const IDLE_LIMIT_MS = 30 * 60 * 1000;
export const WARNING_AT_MS = 29 * 60 * 1000;

// The backend window is 30 minutes, so one heartbeat a minute is ample.
export const HEARTBEAT_THROTTLE_MS = 60 * 1000;
// Other tabs need to stay roughly in sync, not frame-accurate.
export const CROSS_TAB_THROTTLE_MS = 5 * 1000;

export const LAST_ACTIVITY_KEY = "revela_last_activity";
export const SIGNAL_KEY = "revela_idle_signal";
export const SESSION_NOTICE_KEY = "revela_session_notice";

export const WARNING_MESSAGE =
  "Your session is about to expire due to inactivity. You will be automatically logged out in 1 minute.";
export const INACTIVITY_NOTICE =
  "You have been logged out due to 30 minutes of inactivity. Please sign in again.";

/**
 * Real user input only.
 *
 * Background polling, notification SSE frames and silent refreshes are
 * deliberately absent: that is what makes "background traffic must not count
 * as activity" true by construction rather than by bookkeeping.
 */
export const ACTIVITY_EVENTS = [
  "pointerdown", // mouse clicks and touch
  "keydown",
  "scroll",
  "touchstart",
  "touchend",
];

/** Where the idle timer currently stands. */
export function idlePhase(now, lastActivityAt) {
  const elapsed = Math.max(now - lastActivityAt, 0);
  if (elapsed >= IDLE_LIMIT_MS) return "expired";
  if (elapsed >= WARNING_AT_MS) return "warning";
  return "active";
}

export function isExpired(now, lastActivityAt) {
  return idlePhase(now, lastActivityAt) === "expired";
}

export function shouldWarn(now, lastActivityAt) {
  return idlePhase(now, lastActivityAt) === "warning";
}

/** Milliseconds until a given offset is reached (never negative). */
export function delayUntil(offsetMs, now, lastActivityAt) {
  const elapsed = Math.max(now - lastActivityAt, 0);
  return Math.max(offsetMs - elapsed, 0);
}

export function shouldSendHeartbeat(now, lastHeartbeatAt, force = false) {
  if (force) return true;
  return now - lastHeartbeatAt >= HEARTBEAT_THROTTLE_MS;
}

export function shouldBroadcastActivity(now, lastBroadcastAt) {
  return now - lastBroadcastAt >= CROSS_TAB_THROTTLE_MS;
}

/**
 * Decide whether a cross-tab "activity" signal should be honoured.
 *
 * Older or duplicate signals are ignored so a slow tab cannot pull the shared
 * idle clock backwards.
 */
export function resolveActivitySignal(message, { lastActivityAt }) {
  if (!message || message.type !== "activity") return null;
  const at = Number(message.at);
  if (!Number.isFinite(at) || at <= lastActivityAt) return null;
  return { type: "activity", at };
}

/**
 * Restore the recorded idle time after a refresh, a reopened tab or a crash.
 *
 * A value in the future (clock change, tampering) is clamped to now so it can
 * never be used to claim time that has not elapsed.
 */
export function restoreActivity(persisted, now) {
  const parsed = Number(persisted);
  if (!Number.isFinite(parsed) || parsed <= 0) return now;
  return Math.min(parsed, now);
}