// Entirely synthetic network: this fixture must not access a backend.
import { createRoot } from "react-dom/client";
import { MemoryRouter, Routes, Route, useLocation, useNavigate } from "react-router-dom";
import { AuthContext } from "../src/context/authContext";
import { ThemeContext } from "../src/context/themeContext";
import { AppRefreshProvider } from "../src/components/AppRefreshProvider";
import HomePage from "../src/pages/HomePage";
import InspectionPage from "../src/pages/InspectionPage";
import AnalyticsPage from "../src/pages/AnalyticsPage";
import SourceRecordsPage from "../src/pages/SourceRecordsPage";
import { analyticsRoute } from "../src/pages/analyticsNavigation";
import "../src/index.css";
import "../src/styles/global.css";

const checks = [];
const check = (ok, label) => { if (!ok) throw new Error(label); checks.push(label); };
const wait = async predicate => {
  for (let i = 0; i < 200; i++) { if (predicate()) return; await new Promise(resolve => setTimeout(resolve, 25)); }
  throw new Error("Synthetic UI did not become ready");
};
const response = (data) => Response.json(data);
const requests = [];
const deadline = new Date();
deadline.setDate(Math.min(deadline.getDate() + 1, new Date(deadline.getFullYear(), deadline.getMonth() + 1, 0).getDate()));
const deadlineValue = `${deadline.getFullYear()}-${String(deadline.getMonth() + 1).padStart(2, "0")}-${String(deadline.getDate()).padStart(2, "0")}`;
window.fetch = async input => {
  const url = new URL(input, location.href);
  const path = url.pathname.replace(/\/$/, "");
  requests.push(path + url.search);
  if (url.hostname === "api.open-meteo.com") return response({ current: { temperature_2m: 25, weather_code: 1 } });
  if (path.endsWith("/analytics/all")) {
    if (url.searchParams.get("section") === "summary") return response({ summary: { kpis: { total_businesses: 3 }, new_year_rollover: null }, analytics_cache: { computed_at: new Date().toISOString(), age_seconds: 0 } });
    return response({ prescriptive: { rankings: [{ barangayID: 12, barangayName: "Barangay Twelve", rank: 3, ops_score: 80, dispatchable_count: 1, red_count: 1 }] }, analytics_cache: { computed_at: new Date().toISOString(), age_seconds: 0 } });
  }
  if (path.endsWith("/inspections/workload")) return url.searchParams.get("summary") === "1"
    ? response({ as_of: "2026-10-27T12:00:00Z", period_from: "2026-09-27T12:00:00Z", period_to: "2026-10-27T12:00:00Z", open: 2, overdue: 1, oldest_open_days: 6, oldest_report_id: 42, average_resolution_minutes: 30, resolution_sample_size: 1, resolution_excluded: 0, missing_submission_received: 0, age_groups: { "0-3": 1, "4-7": 1, "8-14": 0, "15+": 0 }, age_unavailable: 0, missing_deadlines: 0, ambiguous_deadlines: 2, invalid_deadlines: 0, older_hidden_open_reports: 0, legacy_in_progress: 0 })
    : response({ data: [{ reportID: 42, logID: 1, verificationStatus: "Assigned", detectedName: "Test shop", irTimestamp: "2026-10-21 12:00:00", flagColor: "Red" }], total: 1, page: 1, pages: 1, as_of: "2026-10-27T12:00:00Z" });
  if (path.endsWith("/registry")) return response({ total: 3, data: [] });
  if (path.endsWith("/flags")) return url.searchParams.has("origin")
    ? response({ total: 21, pages: url.searchParams.get("limit") === "1" ? 21 : 2,
        data: Array.from({ length: url.searchParams.get("limit") === "1" || url.searchParams.get("page") === "2" ? 1 : 20 }, (_, index) => ({
          logID: url.searchParams.get("page") === "2" ? 30 : index + 9, detectedName: "Unlinked test pin",
          barangayName: "Barangay Twelve", originSource: url.searchParams.get("origin"), registryLinked: false,
        })) })
    : response({ total: 0, pages: 1, data: [] });
  if (path.endsWith("/inspections")) return response({ total: 1, data: [{ reportID: 42, verificationStatus: "Assigned", deadline: `${deadlineValue} 08:00:00`, detectedName: "Test shop", inspectorName: "Inspector One" }] });
  if (path.endsWith("/users")) return response({ data: [] });
  if (path.endsWith("/stream")) return new Response('data: {"type":"connected"}\n\n', { headers: { "Content-Type": "text/event-stream" } });
  return response({ data: [], count: 0 });
};
export function LocationProbe() {
  const where = useLocation();
  const navigate = useNavigate();
  return <div hidden><span id="route-probe">{where.pathname + where.search}</span><button id="back-probe" onClick={() => navigate(-1)}>Back</button></div>;
}
const root = createRoot(document.getElementById("smoke-root"));
const mount = initial => root.render(<AuthContext.Provider value={{ token: "fixture", user: { id: 77, role: "Admin", fullName: "Test Admin" }, logout() {} }}>
  <ThemeContext.Provider value={{ theme: "light", resolvedTheme: "light" }}><AppRefreshProvider>
    <MemoryRouter initialEntries={[initial]}><LocationProbe /><Routes>
      <Route path="/home" element={<HomePage />} /><Route path="/inspections" element={<InspectionPage />} />
      <Route path="/analytics" element={<AnalyticsPage />} />
      <Route path="/map/records" element={<SourceRecordsPage />} />
    </Routes></MemoryRouter>
  </AppRefreshProvider></ThemeContext.Provider></AuthContext.Provider>
);
try {
  mount("/home");
  await wait(() => document.querySelector(".overview-workload .overview-action-card strong")?.textContent === "2");
  check(!document.body.textContent.includes("System Status") && !document.body.textContent.includes("Registry & Flag Summary"), "obsolete panels absent");
  check(document.querySelector(".overview-workload")?.textContent.includes("Age unavailable"), "workload and age breakdown visible");
  check(document.querySelector('a[href="/inspections?view=overdue"]')?.textContent.includes("1"), "overdue KPI links to its predicate");
  check(document.querySelector('a[href="/map/records?origin=detection&registryLink=unlinked"]')?.textContent.includes("21"), "detection card uses unlinked source predicate");
  check(document.querySelector('a[href="/analytics?tab=prescriptive&barangay_id=12"]') != null, "priority links to prescriptive barangay");
  check(document.querySelector(".overview-priority-rank")?.textContent === "3", "priority keeps municipal rank without rescoring");
  check(analyticsRoute("?tab=prescriptive&barangay_id=12").barangayId === 12, "direct/reloaded URL parses selected barangay");
  const card = document.querySelector('a[href="/inspections?view=overdue"]');
  card.focus();
  check(card.tabIndex === 0 && document.activeElement === card && card.getBoundingClientRect().width > 0, "full-card link is keyboard reachable");
  const initialSummaries = requests.filter(path => path.includes("/inspections/workload?summary=1")).length;
  card.click();
  await wait(() => document.getElementById("route-probe")?.textContent === "/inspections?view=overdue");
  await wait(() => document.querySelector(".dispatch-workload-navigation")?.textContent.includes("Page 1 of 1"));
  check(document.querySelector(".dispatch-workload-navigation")?.textContent.includes("overdue"), "drill-down reflects URL filter and count");
  document.getElementById("back-probe").click();
  await wait(() => document.getElementById("route-probe")?.textContent === "/home");
  check(document.querySelector(".overview-workload .overview-action-card strong")?.textContent === "2", "back restores cached Overview");
  check(requests.filter(path => path.includes("/inspections/workload?summary=1")).length === initialSummaries, "cached revisit does not refetch workload before cadence");
  const dateWithAssignment = [...document.querySelectorAll(".calendar-widget-day")].find(node => node.getAttribute("aria-label")?.includes("1 outstanding deadline"));
  check(dateWithAssignment != null, "assignment date is available as a target");
  dateWithAssignment.click();
  await wait(() => document.getElementById("route-probe")?.textContent.includes("view=deadline_day"));
  check(document.getElementById("route-probe")?.textContent.includes(`deadlineDate=${deadlineValue}`), "assignment date opens matching Dispatch records");
  document.getElementById("back-probe").click();
  await wait(() => document.getElementById("route-probe")?.textContent === "/home");
  document.querySelector(".calendar-widget-task")?.click();
  await wait(() => document.getElementById("route-probe")?.textContent.includes("reportID=42"));
  check(document.getElementById("route-probe")?.textContent.includes("view=open"), "assignment entry opens its report");
  document.getElementById("back-probe").click();
  await wait(() => document.getElementById("route-probe")?.textContent === "/home");
  document.querySelector('a[href="/map/records?origin=detection&registryLink=unlinked"]').click();
  await wait(() => document.querySelector(".source-records-page")?.textContent.includes("21 matching records"));
  check(document.getElementById("route-probe")?.textContent.includes("origin=detection")
    && document.querySelectorAll(".source-records-list li").length === 20, "source KPI opens matching server-filtered paginated list");
  const firstPageReads = requests.filter(path => path.includes("/flags?page=1&limit=20&origin=detection")).length;
  check(firstPageReads === 1, "one backend read supplies the first source page");
  document.querySelector(".source-records-pagination button:last-child").click();
  await wait(() => document.getElementById("route-probe")?.textContent.includes("page=2"));
  await wait(() => document.querySelectorAll(".source-records-list li").length === 1);
  check(document.querySelector(".source-records-page")?.textContent.includes("page 2 of 2"), "source page 2 preserves URL filter and final record");
  document.getElementById("back-probe").click();
  await wait(() => document.querySelectorAll(".source-records-list li").length === 20);
  check(requests.filter(path => path.includes("/flags?page=1&limit=20&origin=detection")).length === firstPageReads, "cached source page does not refetch on back");
  document.getElementById("back-probe").click();
  await wait(() => document.getElementById("route-probe")?.textContent === "/home");
  document.querySelector('a[href="/analytics?tab=prescriptive&barangay_id=12"]').click();
  await wait(() => document.getElementById("route-probe")?.textContent === "/analytics?tab=prescriptive&barangay_id=12");
  await wait(() => document.querySelector(".analytics-page--prescriptive") != null);
  check(document.querySelector(".analytics-page--prescriptive") != null, "priority opens actual Prescriptive tab");
  document.getElementById("back-probe").click();
  await wait(() => document.getElementById("route-probe")?.textContent === "/home");
  const content = document.querySelector(".overview-dashboard-layout");
  check(content.scrollWidth <= content.clientWidth + 3, "dashboard stays within viewport");
  root.render(null);
  await wait(() => document.getElementById("route-probe") == null);
  mount("/analytics?tab=prescriptive&barangay_id=12");
  await wait(() => document.querySelector(".analytics-page--prescriptive") != null);
  await wait(() => requests.some(path => path.includes("/analytics/all?barangay_ids=12")));
  check(document.getElementById("route-probe")?.textContent === "/analytics?tab=prescriptive&barangay_id=12", "fresh mount retains direct Prescriptive URL");
  check(requests.some(path => path.includes("/analytics/all?barangay_ids=12") && !path.includes("application_status")), "prescriptive request only narrows barangay display");
  const descriptive = [...document.querySelectorAll(".analytics-tab-btn")].find(node => node.textContent.includes("Descriptive"));
  descriptive?.click();
  await wait(() => document.getElementById("route-probe")?.textContent.includes("tab=descriptive"));
  document.getElementById("back-probe").click();
  await wait(() => document.querySelector(".analytics-page--prescriptive") != null);
  check(document.getElementById("route-probe")?.textContent.includes("tab=prescriptive"), "tab state follows browser back");
  document.getElementById("actionable-smoke-results").textContent = JSON.stringify({ failed: false, checks });
} catch (error) {
  document.getElementById("actionable-smoke-results").textContent = JSON.stringify({ failed: true, error: error.message, checks });
} finally { root.render(null); }
