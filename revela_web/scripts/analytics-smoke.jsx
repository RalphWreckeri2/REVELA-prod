// Browser-only synthetic responses. No application/Google request leaves this fixture.
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { MemoryRouter } from "react-router-dom";
import { AuthContext } from "../src/context/authContext";
import { ThemeContext } from "../src/context/themeContext";
import AnalyticsPage from "../src/pages/AnalyticsPage";
import "../src/index.css";
import "../src/styles/global.css";

const results = [];
const check = (condition, message) => { if (!condition) throw new Error(message); results.push(message); };
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const wait = async (predicate, label) => {
  for (let i = 0; i < 600; i++) { if (predicate()) return; await sleep(20); }
  throw new Error(`Timed out: ${label}`);
};
const button = (text) => [...document.querySelectorAll("button")].find((node) => node.textContent.trim() === text);
const activeCount = () => [...document.querySelectorAll(".kpi-card")].find((node) => node.textContent.includes("Active Permits"))?.querySelector("h3")?.textContent;
const calls = [];
localStorage.setItem("revela_sidebar_collapsed", "false");
const pending = [];
let online = true;
let mode = "hold";
let value = 17;
Object.defineProperty(navigator, "onLine", { configurable: true, get: () => online });

function payload(section, count = value) {
  const sections = {
    descriptive: { kpis: { active_count: count, total_businesses: count, reporting_year: 2031 }, audit_summary: { total_inspections: 0, result_breakdown: [] } },
    diagnostic: { scan_history: [], category_risk_drivers: [], dbscan_clusters: [], morans_data: { points: [] } },
    prescriptive: { rankings: [], dispatch_recommendations: [], wlc_config: {} },
    operations: { inspector_stats: [], status_breakdown: [], inspection_timeline: [] },
  };
  return Response.json({ [section]: sections[section], analytics_cache: { age_seconds: 0, computed_at: new Date().toISOString() } });
}

window.fetch = async (url) => {
  const parsed = new URL(url, location.href);
  if (parsed.pathname.endsWith("/analytics/all")) {
    const section = parsed.searchParams.get("section");
    calls.push({ section, filter: parsed.searchParams.get("barangay_ids"), query: Object.fromEntries(parsed.searchParams) });
    if (mode === "fail") return Response.json({ error: "Synthetic backend failure" }, { status: 503 });
    if (mode === "hold" || (mode === "filters" && parsed.searchParams.get("barangay_ids") === "1")) {
      // Deliberately ignore AbortSignal: stale-response rejection must still work.
      return new Promise((resolve) => pending.push({ section, resolve }));
    }
    return payload(section, mode === "filters" ? 222 : value);
  }
  if (parsed.pathname.endsWith("/barangays")) return Response.json([{ barangayID: 1, barangayName: "Barangay I" }, { barangayID: 2, barangayName: "Barangay II" }]);
  if (parsed.pathname.endsWith("/filter-metadata")) return Response.json({ lines_of_business: [], business_types: [], business_sizes: [] });
  if (parsed.pathname.endsWith("/wlc-config")) return Response.json({ w1_risk: 68, w2_sector: 7, w3_distance: 25 });
  if (parsed.pathname.endsWith("/unread-count")) return Response.json({ count: 0 });
  if (parsed.pathname.endsWith("/stream")) return new Response('data: {"type":"connected"}\n\n', { headers: { "Content-Type": "text/event-stream" } });
  return Response.json({ data: [] });
};
const release = (count) => pending.splice(0).forEach(({ section, resolve }) => resolve(payload(section, count)));
const root = createRoot(document.getElementById("smoke-root"));
try {
  root.render(<StrictMode><AuthContext.Provider value={{ token: "offline-fixture", user: { role: "Admin", fullName: "Test Admin" }, logout() {} }}>
    <ThemeContext.Provider value={{ isDark: false, theme: "light", setTheme() {} }}><MemoryRouter><AnalyticsPage /></MemoryRouter></ThemeContext.Provider>
  </AuthContext.Provider></StrictMode>);
  await wait(() => document.querySelectorAll(".analytics-skeleton-kpi").length === 8, "immediate KPI skeletons");
  check(Boolean(document.querySelector(".analytics-skeleton-plot")) && Boolean(document.querySelector(".analytics-skeleton-donut")), "Initial loading includes card, bar-chart, and donut placeholders");
  await wait(() => calls.length === 4, "four section requests");
  const descriptive = pending.find((item) => item.section === "descriptive");
  pending.splice(pending.indexOf(descriptive), 1);
  descriptive.resolve(payload("descriptive"));
  await wait(() => activeCount() === "17", "progressive descriptive response");
  check(calls.length === 4, "StrictMode and section rendering do not duplicate active requests");
  check(document.body.textContent.includes("No Geographic Data"), "Successful empty charts show an empty state after loading");
  const diagnosticTab = [...document.querySelectorAll("button")].find((node) => node.textContent.trim().startsWith("Diagnostic"));
  diagnosticTab.click();
  await wait(() => document.querySelector('[aria-label="Loading diagnostic analytics"]'), "independent diagnostic skeleton");
  check(true, "Diagnostic loading stays independent of already-rendered descriptive data");
  release(17);
  mode = "ready";
  [...document.querySelectorAll("button")].find((node) => node.textContent.trim().startsWith("Descriptive")).click();
  await wait(() => button("Refresh") && !button("Refresh").disabled, "completed load");
  check(document.querySelectorAll('nav[aria-label="Analytics sections"]').length === 1 && !document.querySelector(".analytics-quick-nav"), "Floating navigation stays hidden while the main tabs are visible");
  check(document.querySelector(".analytics-tab-subtitle").textContent === "What is happening?", "Navigation subtitles are restored");
  check(document.querySelector(".analytics-census-grid").textContent.includes("Registered Current Year (2031)") && document.querySelector(".analytics-census-grid").textContent.includes("Scheduled Renewal (2032)"), "Census years follow the backend reporting year");
  const content = document.querySelector(".saas-content");
  const mainNav = document.querySelector(".analytics-section-nav");
  content.scrollTop = mainNav.offsetTop + mainNav.offsetHeight + 32;
  await wait(() => document.querySelector(".analytics-quick-nav"), "floating navigation after tabs scroll away");
  const floatingOperations = [...document.querySelectorAll(".analytics-quick-nav-btn")].find(node => node.textContent === "Operations");
  floatingOperations.click();
  await wait(() => document.querySelector('.analytics-tab-btn[aria-current="page"]')?.textContent.includes("Operations"), "floating tab synchronizes main navigation");
  check(document.querySelector('.analytics-quick-nav-btn[aria-pressed="true"]')?.textContent === "Operations", "Floating and main tab selection stay synchronized");
  content.scrollTop = 0;
  await wait(() => !document.querySelector(".analytics-quick-nav"), "floating navigation hides when main tabs return");
  const mascot = document.querySelector('[aria-label="Open AI Analyst"]');
  mascot.click();
  await wait(() => document.querySelector('[aria-label="Close AI Analyst"]'), "open existing AI chat from mascot");
  check(!document.querySelector('[aria-label="Open AI Analyst"]'), "Standalone mascot hides while chat is open");
  document.querySelector('[aria-label="Close AI Analyst"]').click();
  await wait(() => document.querySelector('[aria-label="Open AI Analyst"]'), "mascot returns when chat closes");
  check(true, "Closing AI chat restores the standalone mascot");
  for (const [label, heading] of [["Diagnostic", "Diagnostic"], ["Prescriptive", "Prescriptive Analytics"], ["Operations", "Inspector Operations"], ["Descriptive", "Descriptive Analytics"]]) {
    const tab = [...document.querySelectorAll(".analytics-tab-btn")].find(node => node.textContent.startsWith(label));
    tab.click();
    await wait(() => tab.getAttribute("aria-current") === "page" && [...document.querySelectorAll("h2")].some(node => node.textContent.includes(heading)), `${label} tab`);
    check(true, `${label} tab switches to its existing section`);
  }

  mode = "hold";
  button("Refresh").click();
  await wait(() => document.querySelector(".analytics-updating"), "updating indicator");
  check(activeCount() === "17", "Background refresh keeps existing KPI data visible");
  release(42);
  mode = "ready";
  await wait(() => activeCount() === "42", "refreshed KPI");

  online = false;
  window.dispatchEvent(new Event("offline"));
  await wait(() => document.body.textContent.includes("You are offline"), "offline state");
  check(activeCount() === "42", "Disconnect preserves available data and shows an offline state");
  const beforeReconnect = calls.length;
  value = 77;
  online = true;
  window.dispatchEvent(new Event("online"));
  window.dispatchEvent(new Event("online"));
  await wait(() => activeCount() === "77", "automatic reconnection recovery");
  check(calls.length - beforeReconnect === 4, "Repeated reconnect events cause exactly one recovery request per section");

  mode = "fail";
  await wait(() => button("Refresh") && !button("Refresh").disabled, "refresh action available");
  const beforeFailure = calls.length;
  button("Refresh").click();
  await wait(() => button("Retry analytics"), "bounded failure retries");
  check(calls.length - beforeFailure === 12, "Failed requests stop after initial attempt plus two retries per section");
  check(activeCount() === "77", "A failed refresh keeps the last available data and offers Retry");
  mode = "ready";
  value = 88;
  button("Retry analytics").click();
  await wait(() => activeCount() === "88", "manual recovery");

  [...document.querySelectorAll("h3")].find((node) => node.textContent.includes("Data filters")).click();
  await wait(() => document.querySelector("select"), "filter controls");
  const barangay = [...document.querySelectorAll("select")].find((node) => node.options[0].textContent === "All Barangays");
  mode = "filters";
  barangay.value = "1";
  barangay.dispatchEvent(new Event("change", { bubbles: true }));
  await wait(() => pending.length === 4, "first filter scope");
  barangay.value = "2";
  barangay.dispatchEvent(new Event("change", { bubbles: true }));
  await wait(() => activeCount() === "222", "second filter scope");
  release(111);
  await sleep(50);
  check(activeCount() === "222", "Late responses from an older filter scope cannot overwrite newer results");
  for (const label of ["Descriptive", "Diagnostic", "Prescriptive", "Operations"]) {
    const tab = [...document.querySelectorAll(".analytics-tab-btn")].find(node => node.textContent.startsWith(label));
    tab.click();
    await wait(() => tab.getAttribute("aria-current") === "page", `filtered ${label} tab`);
    check(calls.some(call => call.section === label.toLowerCase() && call.filter === "2") && barangay.value === "2", `${label} receives and retains the selected filter`);
  }
  mode = "ready";
  const registryStatus = [...document.querySelectorAll("select")].find(node => [...node.options].some(option => option.value === "Active"));
  const flagStatus = [...document.querySelectorAll("select")].find(node => [...node.options].some(option => option.value === "Green"));
  registryStatus.value = "Expired";
  registryStatus.dispatchEvent(new Event("change", { bubbles: true }));
  flagStatus.value = "Red";
  flagStatus.dispatchEvent(new Event("change", { bubbles: true }));
  await sleep(20);
  const beforeApply = calls.length;
  button("Apply filters").click();
  await wait(() => calls.length >= beforeApply + 4, "apply shared registry and flag filters");
  check(calls.slice(beforeApply).every(call => call.query.application_status === "Expired" && call.query.flag_color === "Red" && call.filter === "2"), "Apply filters sends registry, flag and barangay criteria to all four sections");
  const beforeClear = calls.length;
  button("Clear all").click();
  await wait(() => calls.length >= beforeClear + 4, "clear all shared filters");
  check(calls.slice(beforeClear).every(call => !call.query.application_status && !call.query.flag_color && !call.filter), "Clear all resets the filters across all four sections");
  document.getElementById("analytics-smoke-results").textContent = JSON.stringify({ passed: results.length, failed: 0, checks: results });
} catch (error) {
  document.getElementById("analytics-smoke-results").textContent = JSON.stringify({ passed: results.length, failed: 1, error: error.stack, checks: results });
} finally {
  root.unmount();
}
