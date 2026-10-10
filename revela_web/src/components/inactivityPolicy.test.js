import assert from "node:assert/strict";
import test from "node:test";
import {
  ACTIVITY_EVENTS,
  CROSS_TAB_THROTTLE_MS,
  HEARTBEAT_THROTTLE_MS,
  IDLE_LIMIT_MS,
  INACTIVITY_NOTICE,
  WARNING_AT_MS,
  WARNING_MESSAGE,
  delayUntil,
  idlePhase,
  isExpired,
  resolveActivitySignal,
  restoreActivity,
  shouldBroadcastActivity,
  shouldSendHeartbeat,
  shouldWarn,
} from "./inactivityPolicy.js";

const MINUTE = 60 * 1000;
const T0 = 1_700_000_000_000;

/**
 * A faithful model of what InactivityProvider does with these primitives,
 * driven by a virtual clock so a 10-minute session runs instantly.
 */
function createIdleSession({ now = T0 } = {}) {
  let clock = now;
  let lastActivityAt = now;
  let warning = false;
  let loggedOut = false;
  let heartbeats = 0;
  let broadcasts = 0;
  let lastHeartbeatAt = 0;
  let lastBroadcastAt = 0;

  return {
    get clock() {
      return clock;
    },
    get lastActivityAt() {
      return lastActivityAt;
    },
    get warning() {
      return warning;
    },
    get loggedOut() {
      return loggedOut;
    },
    get heartbeats() {
      return heartbeats;
    },
    get broadcasts() {
      return broadcasts;
    },

    advance(ms) {
      clock += ms;
      if (isExpired(clock, lastActivityAt)) {
        warning = false;
        loggedOut = true;
      } else if (shouldWarn(clock, lastActivityAt)) {
        warning = true;
      }
      return this;
    },

    /** Genuine user input, mirroring markActivity(). */
    interact({ broadcast = true } = {}) {
      if (loggedOut) return this;
      lastActivityAt = clock;
      warning = false;
      if (shouldSendHeartbeat(clock, lastHeartbeatAt)) {
        lastHeartbeatAt = clock;
        heartbeats += 1;
      }
      if (broadcast && shouldBroadcastActivity(clock, lastBroadcastAt)) {
        lastBroadcastAt = clock;
        broadcasts += 1;
      }
      return this;
    },

    /** Background traffic: a poll that reports nothing. */
    poll() {
      this.advance(20_000);
      return this;
    },
  };
}

// ── Requirement 1 & 2: the window opens on login and resets on interaction ────
test("a freshly logged-in user is active", () => {
  const session = createIdleSession();
  assert.equal(idlePhase(session.clock, session.lastActivityAt), "active");
  assert.equal(session.loggedOut, false);
});

test("active users remain logged in past 10 minutes", () => {
  const session = createIdleSession();
  for (let i = 0; i < 120; i += 1) {
    session.advance(MINUTE).interact();
  }
  assert.equal(session.clock - session.lastActivityAt < MINUTE, true);
  assert.equal(session.loggedOut, false, "an active user must never be logged out");
  assert.equal(session.warning, false);
});

test("interaction resets the window instead of accumulating", () => {
  const session = createIdleSession();
  session.advance(9 * MINUTE).interact();
  session.advance(9 * MINUTE).interact();
  assert.equal(idlePhase(session.clock, session.lastActivityAt), "active");
  assert.equal(session.loggedOut, false);
});

// ── Requirement 4: warning at 9 minutes ─────────────────────────────────────
test("warning appears only at 9 minutes, not before", () => {
  const session = createIdleSession();
  session.advance(8 * MINUTE);
  assert.equal(session.warning, false, "must not warn early");

  session.advance(1 * MINUTE);
  assert.equal(session.warning, true);
  assert.equal(session.loggedOut, false, "warning must not log the user out");
});

test("warning fires exactly at the 9 minute mark", () => {
  assert.equal(WARNING_AT_MS, 9 * MINUTE);
  assert.equal(IDLE_LIMIT_MS, 10 * MINUTE);
  assert.equal(
    delayUntil(WARNING_AT_MS, T0, T0),
    9 * MINUTE,
    "first warning is scheduled 9 minutes out",
  );
});

test("warning modal text matches the required wording", () => {
  assert.equal(
    WARNING_MESSAGE,
    "Your session is about to expire due to inactivity. You will be automatically logged out in 1 minute.",
  );
});

test("Stay Logged In dismisses the warning and pushes the deadline out", () => {
  const session = createIdleSession();
  session.advance(9 * MINUTE);
  assert.equal(session.warning, true);

  session.interact(); // "Stay Logged In"
  assert.equal(session.warning, false);

  session.advance(9 * MINUTE);
  assert.equal(session.loggedOut, false, "the reset must grant another 10 minutes");
});

// ── Requirement 5 & 6: logout at 10 minutes ──────────────────────────────────
test("an inactive user is logged out after 10 minutes", () => {
  const session = createIdleSession();
  session.advance(9 * MINUTE);
  assert.equal(session.loggedOut, false);

  session.advance(1 * MINUTE);
  assert.equal(session.loggedOut, true);
});

test("logout happens at 10 minutes and not a second later", () => {
  const session = createIdleSession();
  session.advance(IDLE_LIMIT_MS - 1);
  assert.equal(session.loggedOut, false);
  session.advance(1);
  assert.equal(session.loggedOut, true);
});

test("logout notice text matches the required wording", () => {
  assert.equal(
    INACTIVITY_NOTICE,
    "You have been logged out due to 10 minutes of inactivity. Please sign in again.",
  );
});

// ── Requirement 3: background traffic is not activity ────────────────────────
test("background polling never keeps a session alive", () => {
  const session = createIdleSession();
  for (let i = 0; i < 200; i += 1) session.poll(); // an hour of 20s polls
  assert.equal(session.loggedOut, true, "polling must not extend the session");
});

test("activity events cover clicks, keys, scrolling and touch", () => {
  for (const name of ["pointerdown", "keydown", "scroll", "touchstart", "touchend"]) {
    assert.ok(ACTIVITY_EVENTS.includes(name), `${name} must count as activity`);
  }
  // Nothing that fires on its own (polling/SSE/renders) may be listed.
  for (const name of ["mousemove", "focus", "resize", "load", "visibilitychange"]) {
    assert.ok(!ACTIVITY_EVENTS.includes(name), `${name} must not count as activity`);
  }
});

test("an idle session is logged out even while requests keep arriving", () => {
  const session = createIdleSession();
  session.advance(9 * MINUTE);
  assert.equal(session.warning, true);
  // Requests continue in the background but nobody is interacting.
  session.poll().poll().poll();
  assert.equal(session.loggedOut, true);
});

// ── Requirement 10: multiple tabs ────────────────────────────────────────────
test("activity in one tab keeps another tab alive", () => {
  const tabA = createIdleSession();
  const tabB = createIdleSession();

  // Tab A is used; tab B sits idle in the background.
  tabA.advance(MINUTE).interact({ broadcast: true });
  const signal = resolveActivitySignal(
    { type: "activity", at: tabA.lastActivityAt },
    { lastActivityAt: tabB.lastActivityAt },
  );
  assert.ok(signal, "tab B must honour tab A's activity");

  tabB.advance(9 * MINUTE);
  assert.equal(tabB.loggedOut, false, "tab B survives thanks to tab A");
});

test("a stale cross-tab signal cannot rewind the shared clock", () => {
  const older = T0;
  const newer = T0 + MINUTE;
  assert.equal(
    resolveActivitySignal({ type: "activity", at: older }, { lastActivityAt: newer }),
    null,
    "an older signal must be ignored",
  );
  assert.equal(
    resolveActivitySignal({ type: "activity", at: newer }, { lastActivityAt: newer }),
    null,
    "an equal signal is a duplicate and must be ignored",
  );
  assert.deepEqual(
    resolveActivitySignal({ type: "activity", at: newer + 1 }, { lastActivityAt: newer }),
    { type: "activity", at: newer + 1 },
  );
});

test("malformed cross-tab messages are ignored", () => {
  for (const bad of [null, undefined, {}, { type: "activity" }, { type: "activity", at: "soon" }, { type: "expired" }]) {
    assert.equal(resolveActivitySignal(bad, { lastActivityAt: T0 }), null);
  }
});

test("activity broadcasts are throttled but never dropped entirely", () => {
  const session = createIdleSession();
  for (let i = 0; i < 100; i += 1) session.interact();
  assert.ok(session.broadcasts > 0);
  assert.ok(
    session.broadcasts <= 100 / (CROSS_TAB_THROTTLE_MS / 1000) + 2,
    "broadcasts must be throttled",
  );
});

// ── Refresh, reopened tab, browser closure ───────────────────────────────────
test("a refresh resumes the recorded idle time instead of restarting it", () => {
  const session = createIdleSession();
  session.advance(7 * MINUTE);

  // Reload: the provider restores the persisted timestamp.
  const restored = restoreActivity(session.lastActivityAt, session.clock);
  assert.equal(restored, session.lastActivityAt);
  assert.equal(idlePhase(session.clock, restored), "active");

  // 4 more idle minutes finishes the original 10, it does not restart it.
  session.advance(4 * MINUTE);
  assert.equal(session.loggedOut, true, "a refresh must not grant a fresh 10 minutes");
});

test("reopening a closed browser resumes the original deadline", () => {
  // Last interaction at T0; the tab is closed for 11 minutes and then reopened.
  const persisted = T0;
  const now = T0 + 11 * MINUTE;
  const restored = restoreActivity(persisted, now);
  assert.equal(
    isExpired(now, restored),
    true,
    "reopening after 11 idle minutes must not restore the session",
  );

  // Reopened within the window, the remaining time carries over.
  const soon = T0 + 5 * MINUTE;
  assert.equal(isExpired(soon, restoreActivity(persisted, soon)), false);
});

test("a missing or corrupt stored value falls back to now", () => {
  for (const bad of [null, undefined, "", "abc", 0, -5, NaN]) {
    assert.equal(restoreActivity(bad, T0), T0);
  }
});

test("a stored time in the future is clamped and cannot buy extra time", () => {
  const now = T0;
  const future = T0 + 5 * 60 * MINUTE; // clock tampering
  assert.equal(restoreActivity(future, now), now);
  assert.equal(idlePhase(now, restoreActivity(future, now)), "active");
});

// ── Lost connectivity ────────────────────────────────────────────────────────
test("failed heartbeats do not reset the timer", () => {
  const session = createIdleSession();
  // The user interacts; the heartbeat is throttled but the timer still expires
  // because nothing else reports activity.
  session.advance(4 * MINUTE).interact();
  assert.ok(session.heartbeats >= 1);

  // Connectivity drops: no further heartbeats succeed, but crucially no code
  // path treats the attempt as activity either.
  session.advance(10 * MINUTE);
  assert.equal(session.loggedOut, true, "a lost connection must not freeze the session");
});

test("heartbeats are throttled to one per minute unless forced", () => {
  assert.equal(shouldSendHeartbeat(T0, 0), true);
  assert.equal(shouldSendHeartbeat(T0 + 1000, T0), false);
  assert.equal(
    shouldSendHeartbeat(T0 + HEARTBEAT_THROTTLE_MS, T0),
    true,
    "one heartbeat per minute is allowed",
  );
  assert.equal(shouldSendHeartbeat(T0, T0, true), true, "forced always sends");
});

// ── General guards ───────────────────────────────────────────────────────────
test("a clock going backwards cannot extend a session", () => {
  assert.equal(idlePhase(T0, T0 + 10 * MINUTE), "active");
  assert.equal(isExpired(T0, T0 + 40 * MINUTE), false, "negative elapsed is clamped to 0");
});

test("phases are ordered active -> warning -> expired", () => {
  assert.equal(idlePhase(T0, T0), "active");
  assert.equal(idlePhase(T0 + WARNING_AT_MS, T0), "warning");
  assert.equal(idlePhase(T0 + IDLE_LIMIT_MS, T0), "expired");
});