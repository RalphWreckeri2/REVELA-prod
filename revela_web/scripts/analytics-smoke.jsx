// Browser-only synthetic responses. No application/Google request leaves this fixture.
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { MemoryRouter } from "react-router-dom";
import { AuthContext } from "../src/context/authContext";
import { ThemeContext } from "../src/context/themeContext";
import AnalyticsPage from "../src/pages/AnalyticsPage";
import { DEFAULT_WLC_WEIGHTS } from "../src/components/wlcPolicy";
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
const wlcWrites = [];
let rejectWlcSave = true;
Object.defineProperty(navigator, "onLine", { configurable: true, get: () => online });

function payload(section, count = value) {
  const sections = {
    descriptive: { kpis: { active_count: count, total_businesses: count, reporting_year: 2031 }, audit_summary: { total_inspections: 0, result_breakdown: [] } },
    diagnostic: { scan_history: [], category_risk_drivers: [], dbscan_clusters: [], morans_data: { points: [] } },
    prescriptive: {
      rankings: [
        { barangayID: 1, barangayName: "Barangay I", rank: 1, ops_score: 84, risk_score: 100, sector_score: 50, proximity_score: 50, flagged_count: 100, red_count: 100, yellow_count: 0, black_count: 0, registry_active_flag_rate: 25, registry_flagged_count: 1, total_registered: 4, unregistered_candidate_count: 10, risk_level: "High", priority_label: "HIGH PRIORITY", priority_color: "#6366f1", location_missing: true },
        { barangayID: 2, barangayName: "Barangay II", rank: 2, ops_score: 39.1, risk_score: 34, sector_score: 50, proximity_score: 50, flagged_count: 34, red_count: 34, yellow_count: 0, black_count: 0, registry_active_flag_rate: null, registry_flagged_count: 0, total_registered: 0, unregistered_candidate_count: 34, risk_level: "Medium", priority_label: "STANDARD", priority_color: "#0ea5e9", location_missing: true },
      ],
      dispatch_recommendations: [{ barangayID: 1, barangayName: "Barangay I", rank: 1, ops_score: 84, inspectors: 0, allocation_status: "deferred", flagged_count: 100, red_count: 100, urgency: "HIGH PRIORITY", urgencyColor: "#6366f1", scoreBreakdown: { risk: { raw: 100, weight: 68, contribution: 68 }, sector: { raw: 50, weight: 7, contribution: 3.5 }, distance: { raw: 50, weight: 25, contribution: 12.5 } }, actionSteps: ["Keep Barangay I in WLC priority order; deployment is deferred until inspectors are available"] }],
      wlc_config: DEFAULT_WLC_WEIGHTS,
      model: { version: "wlc-v2", weights: { w1: .68, w2: .07, w3: .25 }, reference_max_burden: 300, sector_scores_ready: false, sector_enabled: true, sector_note: "Missing sector overrides use neutral score 50; interview-derived weights remain unchanged.", location_note: "Missing locations use neutral proximity 50." },
      workforce: {
        active_inspectors: 0, available_inspectors: 0, allocation_capacity: 0,
        allocated_inspectors: 0, unallocated_inspectors: 0,
      },
    },
    operations: { inspector_stats: [], status_breakdown: [], inspection_timeline: [] },
  };
  return Response.json({ [section]: sections[section], analytics_cache: { age_seconds: 0, computed_at: new Date().toISOString() } });
}

window.fetch = async (url, options = {}) => {
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
  if (parsed.pathname.endsWith("/wlc-config")) {
    if (options.method === "PUT") {
      wlcWrites.push(JSON.parse(options.body));
      if (rejectWlcSave) { rejectWlcSave = false; return Response.json({ error: "Synthetic policy validation failure" }, { status: 400 }); }
      return Response.json({ data: DEFAULT_WLC_WEIGHTS });
    }
    return Response.json(DEFAULT_WLC_WEIGHTS);
  }
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

  [...document.querySelectorAll(".analytics-tab-btn")].find(node => node.textContent.startsWith("Prescriptive")).click();
  await wait(() => document.querySelector('[aria-label="WLC methodology"]'), "WLC methodology");
  check(document.body.textContent.includes("W3·Proximity") && document.body.textContent.includes("municipality-wide"), "Prescriptive shows the implemented equation and fixed municipal filter scope");
  check(document.body.textContent.includes("Deployments are deferred") && !document.body.textContent.includes("Deploy 0"), "Zero inspectors defer deployment without inventing staff");
  const priorityTable = [...document.querySelectorAll("h3")].find(node => node.textContent === "Inspector Deployment Priority Table").parentElement.parentElement.querySelector("table");
  check(priorityTable.textContent.includes("N/A") && priorityTable.textContent.includes("25.0%") && !priorityTable.textContent.includes("Non-Compliance"), "Registry context displays valid business rates and N/A, not a clipped record ratio");
  check(content.scrollWidth <= content.clientWidth + 2, "Prescriptive content stays within the viewport; the wide priority table scrolls inside its card");
  [...document.querySelectorAll("button")].find(node => node.textContent.includes("Deferred — no free inspector")).click();
  await wait(() => document.body.textContent.includes("Sector (7%)"), "interview-derived sector contribution");
  check(document.body.textContent.includes("Registration / renewal checks"), "Red flags are registration/renewal checks, not automatically proven unregistered businesses");
  button("⚙ Quick Adjust WLC Weights").click();
  await wait(() => button("Apply") && !button("Apply").disabled, "loaded WLC weights");
  const ranges = [...document.querySelectorAll('input[type="range"]')];
  check(!ranges[1].disabled && ranges[1].value === "7" && document.body.textContent.includes("→ +3.5"), "Interview-derived 7% sector weight remains active and contributes 3.5 points for neutral score 50");
  Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set.call(ranges[0], "69");
  ranges[0].dispatchEvent(new Event("input", { bubbles: true }));
  await wait(() => button("Apply").disabled && document.body.textContent.includes("WLC weights must total 100%"), "invalid total disables Apply");
  check(wlcWrites.length === 0, "An invalid WLC total never sends a save request");
  button("Use Default (68/7/25)").click();
  await wait(() => !button("Apply").disabled, "restore valid default weights");
  button("Apply").click();
  await wait(() => document.body.textContent.includes("Synthetic policy validation failure"), "visible server validation failure");
  check(Boolean(button("Apply")), "Rejected saves keep Quick Adjust open and show the backend error");
  button("Apply").click();
  await wait(() => !button("Apply"), "successful WLC save closes Quick Adjust");
  check(wlcWrites.length === 2 && wlcWrites.every(payload => JSON.stringify(payload) === JSON.stringify(DEFAULT_WLC_WEIGHTS)), "Only validated default weights are submitted; a successful save refreshes analytics");
  [...document.querySelectorAll(".analytics-tab-btn")].find(node => node.textContent.startsWith("Descriptive")).click();
  await wait(() => button("Refresh") && !button("Refresh").disabled, "ready after WLC refresh");

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
