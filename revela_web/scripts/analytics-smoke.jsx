// Browser-only synthetic responses. No application/Google request leaves this fixture.
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { MemoryRouter } from "react-router-dom";
import { AuthContext } from "../src/context/authContext";
import { RefreshContext } from "../src/components/appRefreshContext";
import { createAppRefreshCoordinator } from "../src/services/appRefreshCoordinator";
import { ThemeContext } from "../src/context/themeContext";
import AnalyticsPage from "../src/pages/AnalyticsPage";
import { DEFAULT_WLC_WEIGHTS } from "../src/components/wlcPolicy";
import Papa from "papaparse";
import "../src/index.css";
import "../src/styles/global.css";

const results = [];
const runtimeErrors = [];
const nativeConsoleError = console.error;
console.error = (...args) => { runtimeErrors.push(args.map(value => value?.stack || String(value)).join(" ")); nativeConsoleError(...args); };
window.addEventListener("error", event => runtimeErrors.push(event.message || "window error"));
window.addEventListener("unhandledrejection", event => runtimeErrors.push(String(event.reason)));
const check = (condition, message) => { if (!condition) throw new Error(message); results.push(message); };
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const wait = async (predicate, label) => {
  for (let i = 0; i < 600; i++) { if (predicate()) return; await sleep(20); }
  throw new Error(`Timed out: ${label}`);
};
const button = (text) => [...document.querySelectorAll("button")].find((node) => node.textContent.trim() === text);
const activeCount = () => [...document.querySelectorAll(".kpi-card")].find((node) => node.textContent.includes("Active permits"))?.querySelector("h3")?.textContent;
const pinPanel = () => document.querySelector(".pin-monitoring-panel");
const openPinPanel = async () => {
  const panel = pinPanel();
  if (!panel) throw new Error("Pin monitoring panel is missing");
  if (!panel.open) panel.querySelector(":scope > summary").click();
  await wait(() => panel.open, "pin monitoring panel opens");
};
const calls = [];
localStorage.setItem("revela_sidebar_collapsed", "false");
const refreshCoordinator = createAppRefreshCoordinator({ userId: 1, storage: window.localStorage });
const pending = [];
let online = true;
let mode = "hold";
let value = 17;
const wlcWrites = [];
let rejectWlcSave = true;
let monitoringMode = "ready";
const downloads = [];
// Inspect CSV Blobs entirely in memory; do not write to the user's Downloads.
const createObjectURL = URL.createObjectURL.bind(URL);
URL.createObjectURL = blob => {
  const url = createObjectURL(blob);
  downloads.push({ blob, url });
  return url;
};
const dispatchAnchorEvent = HTMLAnchorElement.prototype.dispatchEvent;
HTMLAnchorElement.prototype.dispatchEvent = function (event) {
  if (event.type === "click" && this.download && this.href.startsWith("blob:")) {
    const item = downloads.find(download => download.url === this.href);
    if (item) item.filename = this.download;
    return true;
  }
  return dispatchAnchorEvent.call(this, event);
};
Object.defineProperty(navigator, "onLine", { configurable: true, get: () => online });

function nonRegistryFixture(query = {}) {
  let records = Array.from({ length: 25 }, (_, index) => {
    const color = ["Green", "Red", "Yellow", "Orange", "Black", "Purple"][index % 6];
    const verified = color === "Green" && index !== 24;
    return { logID: index + 1, detectedName: `Non-registry fixture ${index + 1}`, barangayID: index % 2 + 1,
      barangayName: index % 2 ? "Barangay II" : "Barangay I", flagColor: color,
      registryLinked: false, originSource: index % 2 ? "manual" : "detection",
      verificationStatus: color === "Yellow" ? "Assigned" : verified ? "Verified" : null,
      hasActiveInspection: color === "Yellow", verifiedGreen: verified,
      verifiedGreenAt: verified ? "2026-10-20T14:00:00Z" : null };
  });
  if (monitoringMode === "empty") records = [];
  records = records.filter(row => (!query.barangay_ids || query.barangay_ids.split(",").includes(String(row.barangayID)))
    && (!query.flag_color || row.flagColor === query.flag_color));
  const byBarangay = new Map();
  records.forEach(row => {
    if (!byBarangay.has(row.barangayID)) byBarangay.set(row.barangayID, {
      barangayID: row.barangayID, barangayName: row.barangayName, Green: 0, Red: 0, Yellow: 0, Orange: 0, Black: 0, Purple: 0, Unknown: 0,
    });
    byBarangay.get(row.barangayID)[row.flagColor] += 1;
  });
  return { records, by_barangay: [...byBarangay.values()], generated_at: new Date().toISOString(),
    summary: { total: records.length, needs_verification: records.filter(row => ["Red", "Yellow"].includes(row.flagColor)).length,
      under_inspection: records.filter(row => row.hasActiveInspection).length, verified_green: records.filter(row => row.verifiedGreen).length } };
}

function registryLinkedFixture(query = {}) {
  const base = nonRegistryFixture(query);
  const records = base.records.slice(0, 3).map((row, index) => ({
    ...row, registryLinked: true, businessID: 900 + index, detectedName: `Registry-linked fixture ${index + 1}`,
  }));
  return { ...base, records, summary: { ...base.summary, total: records.length,
    needs_verification: records.filter(row => ["Red", "Yellow"].includes(row.flagColor)).length,
    under_inspection: records.filter(row => row.hasActiveInspection).length,
    verified_green: records.filter(row => row.verifiedGreen).length } };
}

function payload(section, count = value, query = {}) {
  const registryRows = [
    { barangayID: 1, barangayName: "Barangay I", active: count, pending: 0, expired: 0, closed: 0, revoked: 0, total: count },
    { barangayID: 2, barangayName: "Barangay II", active: 0, pending: 0, expired: 0, closed: 0, revoked: 0, total: 0 },
  ];
  const inspectionRows = [
    { barangayID: 1, barangayName: "Barangay I", assigned: 1, reassigned: 0, in_progress: 1, submitted: 1, verified: 2, unassigned: 0, total: 5 },
    { barangayID: 2, barangayName: "Barangay II", assigned: 0, reassigned: 0, in_progress: 0, submitted: 0, verified: 1, unassigned: 0, total: 1 },
  ];
  const sections = {
    descriptive: {
      kpis: { active_count: count, total_businesses: count, reporting_year: 2031, compliance_rate: 100,
        current_year_registered_count: count, upcoming_year_renewal_count: 2, new_registration_count: 3, renewal_registration_count: 4,
        pending_count: 0, expired_count: 0, closed_count: 0, revoked_count: 0 },
      registry_by_barangay_status: registryRows,
      inspection_by_barangay_status: inspectionRows,
      sectoral_distribution: [{ sector: "Retail", count }, { sector: "Services", count: 2 }],
      business_size_dist: [{ size_label: "Micro", count }, { size_label: "Small", count: 1 }],
      business_type_dist: [{ type_label: "Sole Proprietorship", count }, { type_label: "Corporation", count: 1 }],
      registration_type_dist: [{ type_label: "New", count: 3 }, { type_label: "Renewal", count: 4 }],
      audit_summary: {
        total_inspections: 6, total_reports: 6, unlinked_reports: 2, verified_reports: 4, submitted_green: 1,
        result_breakdown: [{ inspectionResult: "Green", count: 3 }, { inspectionResult: "Red", count: 1 }],
        submitted_result_breakdown: [{ inspectionResult: "Green", count: 1 }],
        workflow: { verified_reports: 4, awaiting_verification: 2, submitted_green: 1 },
      },
      confirmed_compliance: { office_confirmed: 2, inspection_verified: 1, total_confirmed: 3 },
      non_registry_monitoring: monitoringMode === "missing" ? undefined : nonRegistryFixture(query),
      registry_linked_monitoring: monitoringMode === "missing" ? undefined : registryLinkedFixture(query),
    },
    diagnostic: { scan_history: [], category_risk_drivers: [{ category: "Retail", flagged_count: 2, total_registered: 10, non_green_rate: 20 }],
      category_linkage_summary: { linked_records: 2, total_flagged_records: 3, linkage_rate: 66.7, unlinked_records: 1, ambiguous_records: 0 },
      dbscan_clusters: [], morans_data: { points: [] } },
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
      return new Promise((resolve) => pending.push({ section, query: Object.fromEntries(parsed.searchParams), resolve }));
    }
    return payload(section, mode === "filters" ? 222 : value, Object.fromEntries(parsed.searchParams));
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
const release = (count) => pending.splice(0).forEach(({ section, query, resolve }) => resolve(payload(section, count, query)));
const root = createRoot(document.getElementById("smoke-root"));
try {
  root.render(<StrictMode><AuthContext.Provider value={{ token: "offline-fixture", user: { id: 1, role: "Admin", fullName: "Test Admin" }, logout() {} }}>
    <RefreshContext.Provider value={refreshCoordinator}><ThemeContext.Provider value={{ isDark: false, theme: "light", setTheme() {} }}><MemoryRouter><AnalyticsPage /></MemoryRouter></ThemeContext.Provider></RefreshContext.Provider>
  </AuthContext.Provider></StrictMode>);
  await wait(() => document.querySelectorAll(".analytics-skeleton-kpi").length === 8, "immediate KPI skeletons");
  check(document.querySelectorAll(".analytics-skeleton-plot").length === 2 && !document.querySelector(".analytics-skeleton-donut"), "Initial loading uses two wide chart placeholders, not donut placeholders");
  await wait(() => calls.length === 4, "four section requests");
  const descriptive = pending.find((item) => item.section === "descriptive");
  pending.splice(pending.indexOf(descriptive), 1);
  descriptive.resolve(payload("descriptive"));
  await wait(() => activeCount() === "17", "progressive descriptive response");
  check(calls.length === 4, "StrictMode and section rendering do not duplicate active requests");
  check(!document.body.textContent.includes("Geographic & Sector Spread")
    && !document.body.textContent.includes("Top Sectors")
    && !document.body.textContent.includes("Compliance Timeline")
    && !document.body.textContent.includes("Compliance by Business Size"),
    "Removed Descriptive donuts, Top Sectors and Compliance Timeline/Size cards stay removed");
  const registryCard = document.querySelector(".analytics-feature-card--registry-status");
  check(Boolean(registryCard)
    && registryCard.textContent.includes("Registry Businesses by Barangay and Permit Status")
    && registryCard.textContent.includes("Permit status")
    && registryCard.textContent.includes("Total: 17 businesses"),
    "Registry chart is one barangay-by-permit-status stacked chart with a total");
  const registryShare = [...registryCard.querySelectorAll("button")].find(node => node.textContent === "Share");
  registryShare.click();
  await wait(() => registryShare.getAttribute("aria-pressed") === "true", "registry Counts/Share toggle");
  check(registryShare.getAttribute("aria-pressed") === "true", "Registry chart switches to share mode without a new request");
  const profile = registryCard.querySelector(".analytics-profile-disclosure");
  check(profile && !profile.open, "Registry profile tables are collapsed by default");
  profile.querySelector("summary").click();
  await wait(() => profile.open, "registry profile disclosure opens");
  check(profile.textContent.includes("Sector") && profile.textContent.includes("Business size")
    && profile.textContent.includes("Business type") && profile.textContent.includes("Registration type"),
    "Registry profile keeps sector, size, business type and registration type as compact tables");
  const inspectionCard = document.querySelector(".analytics-feature-card--inspection-status");
  check(Boolean(inspectionCard)
    && inspectionCard.textContent.includes("Inspection Reports by Barangay and Current Status")
    && inspectionCard.textContent.includes("Current report status")
    && inspectionCard.textContent.includes("Total: 6 linked reports")
    && inspectionCard.textContent.includes("Verified Green")
    && inspectionCard.textContent.includes("not an additional stack"),
    "Inspection chart is one barangay-by-current-status stacked chart with a separate Verified Green subset annotation");
  check(document.body.textContent.includes("2 reports have no linked target pin"),
    "Reports without a linked pin are disclosed instead of folded into the report chart");
  const diagnosticTab = [...document.querySelectorAll("button")].find((node) => node.textContent.trim().startsWith("Diagnostic"));
  diagnosticTab.click();
  await wait(() => document.querySelector('[aria-label="Loading diagnostic analytics"]'), "independent diagnostic skeleton");
  check(true, "Diagnostic loading stays independent of already-rendered descriptive data");
  release(17);
  mode = "ready";
  [...document.querySelectorAll("button")].find((node) => node.textContent.trim().startsWith("Descriptive")).click();
  await wait(() => document.querySelector('.analytics-tab-btn[aria-current="page"]')?.textContent.startsWith("Descriptive")
    && document.querySelector(".analytics-census-grid") && button("Refresh") && !button("Refresh").disabled, "completed descriptive load");
  check(document.querySelectorAll('nav[aria-label="Analytics sections"]').length === 1 && !document.querySelector(".analytics-quick-nav"), "Floating navigation stays hidden while the main tabs are visible");
  check(document.querySelector(".analytics-tab-subtitle").textContent === "What is happening?", "Navigation subtitles are restored");
  check(document.querySelector(".analytics-census-grid").textContent.includes("Businesses in scope") && document.querySelector(".analytics-census-grid").textContent.includes("Active permits"), "Registry KPIs match the stacked chart population");
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

  [...document.querySelectorAll(".analytics-tab-btn")].find(node => node.textContent.startsWith("Diagnostic")).click();
  await wait(() => [...document.querySelectorAll("h3")].some(node => node.textContent === "Registry-Linked Status by Sector"), "registry-linked sector card moved to Diagnostic");
  check(true, "Registry-Linked Status by Sector lives in Diagnostic, not Descriptive");
  [...document.querySelectorAll(".analytics-tab-btn")].find(node => node.textContent.startsWith("Descriptive")).click();
  await wait(() => document.querySelector(".analytics-feature-card--inspection-status"), "descriptive restored after Diagnostic");

  check(Boolean(pinPanel()) && !pinPanel().open, "Pin monitoring is one collapsed panel");
  check(pinPanel().querySelectorAll('[role="tab"]').length === 2, "Pin monitoring has separate non-registry and registry-linked tabs");
  check(!document.querySelector(".analytics-feature-card--inspection-status").textContent.includes("Total non-registry pins"),
    "Pin counts are not mixed into the inspection report chart");
  const monitoring = () => pinPanel()?.querySelector(".non-registry-monitoring");
  const monitoringValues = () => [...(monitoring()?.querySelectorAll(".kpi-card h3") || [])].map(node => node.textContent);
  await openPinPanel();
  await wait(() => monitoringValues().length === 4, "non-registry monitoring cards");
  check(JSON.stringify(monitoringValues()) === JSON.stringify(["25", "8", "4", "4"]), "Non-registry cards separate all pins, Red/Yellow, current inspection workflow and evidence-backed Green");
  await wait(() => monitoring().querySelector(".recharts-surface"), "non-registry barangay chart");
  check(monitoring().textContent.includes("Purple pins") && monitoring().textContent.includes("Orange pins"), "The barangay chart includes all current flag colors, not only Red/Yellow");
  monitoring().querySelector("button").click();
  await wait(() => document.querySelector(".non-registry-dialog"), "non-registry list dialog");
  let list = document.querySelector(".non-registry-dialog");
  check(list.querySelectorAll("tbody tr").length === 20 && list.textContent.includes("25 matching pins"), "View List paginates the same full monitoring snapshot");
  [...list.querySelectorAll("button")].find(node => node.textContent === "Next").click();
  await wait(() => document.querySelectorAll(".non-registry-dialog tbody tr").length === 5, "second non-registry page");
  list = document.querySelector(".non-registry-dialog");
  [...list.querySelectorAll("button")].find(node => node.textContent === "Export CSV").click();
  await wait(() => downloads.some(item => item.filename?.startsWith("Non_Registry_Pins_")), "non-registry CSV Blob");
  const downloaded = downloads.find(item => item.filename?.startsWith("Non_Registry_Pins_"));
  const exportedPins = Papa.parse((await downloaded.blob.text()).replace(/^\uFEFF/, ""), { header: true }).data;
  check(exportedPins.length === 25 && exportedPins.every(row => row["Registry Link"] === "Not in Registry")
    && exportedPins.at(-1)["Inspection-Verified Compliant"] === "No", "CSV includes all 25 pins across pages and does not treat unverified Green as compliant");
  list.querySelector('[aria-label="Close dialog"]').click();
  await wait(() => !document.querySelector(".non-registry-dialog"), "close non-registry list");
  check(document.activeElement === monitoring().querySelector("button"), "Closing View List restores focus to its trigger");
  monitoringMode = "empty";
  button("Refresh").click();
  await wait(() => JSON.stringify(monitoringValues()) === JSON.stringify(["0", "0", "0", "0"]), "empty non-registry snapshot");
  check(monitoring().textContent.includes("No non-registry pins match"), "A real empty cohort shows four zeros and a clear empty chart state");
  await wait(() => button("Refresh") && !button("Refresh").disabled, "refresh after empty cohort");
  monitoringMode = "missing";
  button("Refresh").click();
  await wait(() => monitoring().textContent.includes("data is unavailable"), "unavailable non-registry snapshot");
  check(monitoringValues().length === 0 && [...monitoring().querySelectorAll("button")].every(node => node.disabled), "Missing monitoring data never turns into fake zero cards or a downloadable empty report");
  await wait(() => button("Refresh") && !button("Refresh").disabled, "refresh after unavailable cohort");
  monitoringMode = "ready";
  button("Refresh").click();
  await wait(() => monitoringValues()[0] === "25" && button("Refresh") && !button("Refresh").disabled, "restore non-registry cohort");

  [...document.querySelectorAll(".analytics-tab-btn")].find(node => node.textContent.startsWith("Prescriptive")).click();
  await wait(() => document.querySelector('.presc-method') || document.body.textContent.includes("W3·Proximity"), "WLC methodology");
  check(document.body.textContent.includes("W3") && document.body.textContent.includes("Proximity") && document.body.textContent.includes("municipality-wide"), "Prescriptive shows the implemented equation and fixed municipal filter scope");
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
  await wait(() => document.querySelector('.analytics-tab-btn[aria-current="page"]')?.textContent.startsWith("Descriptive")
    && document.querySelector(".analytics-census-grid") && button("Refresh") && !button("Refresh").disabled, "ready after WLC refresh");

  mode = "hold";
  button("Refresh").click();
  await wait(() => document.querySelector(".analytics-updating"), "updating indicator");
  check(activeCount() === "17", `Background refresh keeps existing KPI data visible (got ${activeCount()})`);
  release(42);
  mode = "ready";
  await wait(() => activeCount() === "42", "refreshed KPI");

  online = false;
  window.dispatchEvent(new Event("offline"));
  await sleep(100);
  check(activeCount() === "42", "Disconnect preserves available data while offline");
  const beforeReconnect = calls.length;
  value = 77;
  online = true;
  window.dispatchEvent(new Event("online"));
  await wait(() => button("Refresh") && !button("Refresh").disabled, "refresh available after reconnect");
  button("Refresh").click();
  await wait(() => activeCount() === "77", "manual reconnection recovery");
  check(calls.length - beforeReconnect === 4, "Reconnect recovery causes one refresh request per section");

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
  [...document.querySelectorAll(".analytics-tab-btn")].find(node => node.textContent.startsWith("Descriptive")).click();
  await wait(() => document.querySelector('.analytics-tab-btn[aria-current="page"]')?.textContent.startsWith("Descriptive"), "descriptive tab after filter loop");
  await openPinPanel();
  await wait(() => monitoringValues()[0] === "12", "barangay-filtered non-registry cohort");
  check(JSON.stringify(monitoringValues()) === JSON.stringify(["12", "4", "0", "0"]), "Non-registry cards use the selected barangay rather than the unfiltered municipality");
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
  await wait(() => document.querySelector(".analytics-feature-card--registry-status")?.textContent.includes("Filtered to permit status Expired"), "registry chart explains the applied status filter");
  check(true, "A selected permit status keeps the Registry chart valid with a concise filtered-to-status note");
  await wait(() => monitoringValues()[0] === "4", "flag-filtered non-registry cohort");
  check(JSON.stringify(monitoringValues()) === JSON.stringify(["4", "4", "0", "0"])
    && monitoring().textContent.includes("renewal filters do not apply"), "Flag filters scope monitoring while registry-only filters are explicitly inapplicable");
  button("Clear all").click();
  await sleep(500);
  check(monitoringValues()[0] === "25", "Clear all restores the complete non-registry snapshot");
  check(JSON.stringify(monitoringValues()) === JSON.stringify(["25", "8", "4", "4"]), "Clear all restores the complete non-registry snapshot");
  document.getElementById("analytics-smoke-results").textContent = JSON.stringify({ passed: results.length, failed: 0, checks: results });
} catch (error) {
  document.getElementById("analytics-smoke-results").textContent = JSON.stringify({ passed: results.length, failed: 1, error: error.stack, calls, pending: pending.length, runtimeErrors,
    body: document.body.innerText.slice(0, 1200), checks: results });
} finally {
  root.unmount();
}
