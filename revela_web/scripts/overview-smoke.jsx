// Synthetic network responses only. No backend, weather or Google data is used.
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { MemoryRouter } from "react-router-dom";
import { AuthContext } from "../src/context/authContext";
import { ThemeContext } from "../src/context/themeContext";
import HomePage from "../src/pages/HomePage";
import "../src/index.css";
import "../src/styles/global.css";

const checks = [];
const timings = {};
const check = (condition, message) => { if (!condition) throw new Error(message); checks.push(message); };
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
const wait = async (predicate, label) => {
  for (let i = 0; i < 600; i++) { if (predicate()) return; await sleep(20); }
  throw new Error(`Timed out: ${label}`);
};
const calls = [];
const held = [];
let summaryMode = "hold";
let othersMode = "hold";
let count = 123;
localStorage.setItem("revela_sidebar_collapsed", "false");
const cache = () => ({ computed_at: new Date().toISOString(), age_seconds: 0 });
const metrics = () => ({ total_businesses: count, compliance_rate: 81.3, current_year_registered_count: 99, upcoming_year_renewal_count: 80, total_flagged: 0, reporting_year: 2031 });
const summaryResponse = () => Response.json({ summary: { kpis: metrics(), new_year_rollover: null }, analytics_cache: cache() });
const partialSummaryResponse = () => {
  const readyMetrics = Object.fromEntries(Object.entries(metrics()).filter(([key]) => key !== "total_flagged"));
  return Response.json({
    summary: { kpis: readyMetrics, new_year_rollover: null },
    analytics_cache: { ...cache(), loading: true, refreshing: true },
  });
};
const respond = kind => kind === "summary" ? summaryResponse()
  : kind === "prescriptive" ? Response.json({ prescriptive: { rankings: [] }, analytics_cache: cache() })
    : kind === "weather" ? Response.json({ current: { temperature_2m: 29, weather_code: 2 } })
      : Response.json({ data: [] });
window.fetch = async (url, options = {}) => {
  const parsed = new URL(url, location.href);
  const path = parsed.pathname.replace(/\/$/, "");
  const kind = path.endsWith("/analytics/all") ? parsed.searchParams.get("section") || "all"
    : path.endsWith("/flags") ? "flags"
      : path.endsWith("/inspections") ? "inspections"
        : path.endsWith("/users") && parsed.searchParams.get("role") === "Inspector" ? "inspectors"
          : parsed.hostname === "api.open-meteo.com" ? "weather" : null;
  if (kind) {
    calls.push(kind);
    if (kind === "summary" && summaryMode === "fail") return Response.json({ error: "Synthetic summary failure" }, { status: 503 });
    if (kind === "summary" && summaryMode === "pending") return Response.json({ analytics_cache: { loading: true, refreshing: true } }, { status: 202 });
    if ((kind === "summary" ? summaryMode : othersMode) === "hold") {
      return new Promise((resolve, reject) => {
        const entry = { kind, resolve };
        held.push(entry);
        options.signal?.addEventListener("abort", () => {
          const index = held.indexOf(entry);
          if (index >= 0) held.splice(index, 1);
          reject(new DOMException("Aborted", "AbortError"));
        }, { once: true });
      });
    }
    return respond(kind);
  }
  if (parsed.pathname.endsWith("/unread-count")) return Response.json({ count: 0 });
  if (parsed.pathname.endsWith("/stream")) return new Response('data: {"type":"connected"}\n\n', { headers: { "Content-Type": "text/event-stream" } });
  return Response.json({ data: [] });
};
const release = kind => held.splice(0).forEach(entry => {
  if (!kind || entry.kind === kind) entry.resolve(respond(entry.kind));
  else held.push(entry);
});
const summary = () => document.querySelector(".overview-kpis");
const values = () => [...summary().querySelectorAll("dd")].map(node => node.textContent);
const button = text => [...document.querySelectorAll("button")].find(node => node.textContent.trim() === text);
const root = createRoot(document.getElementById("smoke-root"));
const render = () => root.render(<StrictMode><AuthContext.Provider value={{ token: "offline-fixture", user: { role: "Admin", fullName: "Test Admin" }, logout() {} }}>
  <ThemeContext.Provider value={{ isDark: false, resolvedTheme: "light", theme: "light", setTheme() {} }}><MemoryRouter><HomePage /></MemoryRouter></ThemeContext.Provider>
</AuthContext.Provider></StrictMode>);
try {
  render();
  await wait(() => held.some(entry => entry.kind === "summary") && calls.includes("prescriptive") && calls.includes("inspections"), "initial requests");
  check(summary().textContent.includes("Loading summary metrics") && values().every(value => value === "—"), "Initial loading shows unavailable values instead of fabricated zeros");
  const started = performance.now();
  summaryMode = "partial";
  const partial = held.find(entry => entry.kind === "summary");
  held.splice(held.indexOf(partial), 1);
  partial.resolve(partialSummaryResponse());
  await wait(() => values()[0] === "123", "registry summary before the map count");
  timings.summaryAfterReleaseMs = Math.round(performance.now() - started);
  check(values()[0] === "123" && values()[4] === "—", "Registry metrics render early while the not-yet-computed map count stays unavailable");
  check(summary().getAttribute("aria-busy") === "true" && summary().textContent.includes("Some metric values are unavailable"), "Partial summary clearly indicates remaining metrics are pending");
  summaryMode = "ready";
  await wait(() => values()[4] === "0", "completed map count");
  await wait(() => values()[0] === "123", "summary before unrelated requests");
  check(summary().getAttribute("aria-busy") === "false" && !summary().textContent.includes("Loading"), "Summary renders immediately after its own response");
  check(held.some(entry => entry.kind === "prescriptive") && held.some(entry => entry.kind === "inspections") && held.some(entry => entry.kind === "flags") && held.some(entry => entry.kind === "weather"), "Rankings, inspections, map records and weather remain pending after summary is rendered");
  check(!calls.includes("all")
    && calls.filter(kind => kind === "summary").length === 2
    && ["prescriptive", "flags", "inspections", "inspectors"].every(resource => calls.filter(kind => kind === resource).length === 1),
  "Overview polls once for the completed summary while StrictMode avoids duplicate dashboard requests");
  check(values()[4] === "0", "A reported zero remains a real zero");
  release("inspections");
  await wait(() => document.querySelector(".calendar-widget").getAttribute("aria-busy") === "false", "independent inspection response");
  check(document.querySelector(".overview-map").textContent.includes("Loading map records"), "Inspection deadlines finish independently of map records");
  othersMode = "ready";
  release();
  await wait(() => button("Refresh dashboard") && !button("Refresh dashboard").disabled, "initial load completed");

  summaryMode = "hold";
  button("Refresh dashboard").click();
  await wait(() => summary().textContent.includes("Refreshing summary metrics"), "background refresh");
  check(values()[0] === "123", "Background refresh keeps previous summary values visible and labels the refresh");
  count = 456;
  release("summary");
  summaryMode = "ready";
  await wait(() => values()[0] === "456", "refreshed summary values");

  summaryMode = "fail";
  await wait(() => button("Refresh dashboard") && !button("Refresh dashboard").disabled, "refresh available");
  const beforeFailure = calls.filter(kind => kind === "summary").length;
  button("Refresh dashboard").click();
  await wait(() => button("Retry summary"), "failed refresh ends");
  check(values()[0] === "456" && summary().textContent.includes("Showing last loaded data"), "A failed refresh preserves the last values with an explicit stale-data message");
  check(calls.filter(kind => kind === "summary").length - beforeFailure === 3 && summary().getAttribute("aria-busy") === "false", "Summary failures stop after bounded retries and clear loading");
  summaryMode = "ready";
  count = 789;
  button("Retry summary").click();
  await wait(() => values()[0] === "789", "summary retry recovery");

  // Remount with no prior result to verify initial errors and a pending 202 retry.
  root.render(null);
  await wait(() => !document.querySelector(".overview-page"), "unmount");
  summaryMode = "fail";
  render();
  await wait(() => button("Retry summary"), "initial request failure");
  check(values().every(value => value === "—") && summary().textContent.includes("Could not load summary metrics"), "An initial failure displays unavailable metrics, never fake zero totals");
  summaryMode = "pending";
  button("Retry summary").click();
  await wait(() => summary().getAttribute("aria-busy") === "true", "202 preparation state");
  summaryMode = "ready";
  await wait(() => values()[0] === "789", "pending snapshot recovery");
  check(true, "A preparing 202 response is polled and recovers to actual summary values");
  document.getElementById("overview-smoke-results").textContent = JSON.stringify({ passed: checks.length, failed: 0, checks, timings, data: "synthetic; unrelated responses deliberately held" });
} catch (error) {
  document.getElementById("overview-smoke-results").textContent = JSON.stringify({ passed: checks.length, failed: 1, error: error.stack, checks, timings });
} finally {
  root.unmount();
}
