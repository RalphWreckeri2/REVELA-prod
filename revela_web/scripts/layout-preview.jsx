// Development-only visual fixture. All API responses are synthetic; no server
// credentials or production data are needed. The production app/routes render.
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "../src/App";
import "../src/styles/global.css";

const params = new URLSearchParams(location.search);
const page = params.get("page") || "analytics";
const state = params.get("state") || "populated";
localStorage.clear();
localStorage.setItem("revela_sidebar_collapsed", String(params.get("sidebar") === "collapsed"));
localStorage.setItem("revela_theme", "light");
if (page !== "access") localStorage.setItem("revela_token", "dev-admin-token");
history.replaceState(null, "", page === "reports" ? "/reports" : "/analytics");

const barangays = ["Barangay I", "Barangay II", "Barangay II-A", "Barangay III", "Barangay IV", "Barangay Bayorbor", "Barangay Bubuyan", "Barangay Calingatan", "Barangay Kinalaglagan", "Barangay Loob", "Barangay Lumang Lipa", "Barangay Manggahan", "Barangay Nangkaan", "Barangay San Sebastian", "Barangay Santol", "Barangay Upa"];
const sectors = ["Retail Sale in Non-Specialized Stores with Food, Beverages or Tobacco Predominating", "Food and Beverage Service Activities — Restaurants and Mobile Food Services", "Wholesale and Retail Trade; Repair of Motor Vehicles and Motorcycles", "Manufacture of Other Food Products and Prepared Meals", "Other Community, Social and Personal Service Activities", "Transportation and Storage"];
const sizes = ["Micro", "Small", "Medium", "Large"];
const empty = state === "empty";
const descriptive = {
  kpis: { total_businesses: empty ? 0 : 1248, active_count: empty ? 0 : 1010, expired_count: empty ? 0 : 156, pending_count: empty ? 0 : 42, closed_count: 24, revoked_count: 16, compliance_rate: 80.9, current_year_registered_count: 1098, upcoming_year_renewal_count: 870, new_registration_count: 276, renewal_registration_count: 972 },
  nature_per_barangay: empty ? [] : barangays.map((barangayName, i) => ({ barangayName, Retail: 48 + i * 3, Services: 24 + i })),
  sectoral_distribution: empty ? [] : sectors.map((sector, i) => ({ sector, count: 340 - i * 48 })),
  business_size_dist: empty ? [] : sizes.map((size_label, i) => ({ size_label, count: [960, 210, 62, 16][i] })),
  business_type_dist: empty ? [] : ["Single Proprietorship", "Corporation", "Partnership", "Cooperative", "One Person Corporation"].map((type_label, i) => ({ type_label, count: [848, 260, 84, 36, 20][i] })),
  registration_type_dist: empty ? [] : [{ type_label: "New", count: 276 }, { type_label: "Renewal", count: 972 }],
  compliance_by_size: empty ? [] : sizes.map((size_label, i) => ({ size_label, active_count: [770, 180, 48, 12][i], inactive_count: [190, 30, 14, 4][i] })),
  compliance_timeline: empty ? [] : ["Oct 2025", "Nov 2025", "Dec 2025", "Jan 2026", "Feb 2026", "Mar 2026", "Apr 2026", "May 2026", "Jun 2026", "Jul 2026", "Aug 2026", "Sep 2026"].map((month, i) => ({ month, active_count: [270, 305, 290, 1010, 960, 860, 740, 660, 590, 440, 370, 310][i], non_active_count: [180, 165, 178, 238, 220, 190, 174, 160, 141, 132, 112, 101][i] })),
  enforcement_progress: empty ? [] : barangays.map((barangayName, i) => ({ barangayName, green_count: 44 + i, red_count: 3 + i, yellow_count: 5, black_count: 1, orange_count: 2, purple_count: 1 })),
  audit_summary: { total_inspections: empty ? 0 : 96, result_breakdown: empty ? [] : [{ inspectionResult: "Green", count: 64 }, { inspectionResult: "Red", count: 22 }, { inspectionResult: "Black", count: 10 }] },
};
const sections = {
  descriptive,
  diagnostic: { scan_history: [], category_risk_drivers: [], dbscan_clusters: [], morans_data: { points: [] } },
  prescriptive: { rankings: [], dispatch_recommendations: [], wlc_config: {} },
  operations: { inspector_stats: [], status_breakdown: [{ status: "Assigned", count: 28 }, { status: "Submitted", count: 32 }, { status: "Verified", count: 64 }], inspection_timeline: [{ date: "2026-09-01", count: 12 }, { date: "2026-09-08", count: 24 }, { date: "2026-09-15", count: 19 }, { date: "2026-09-22", count: 32 }] },
};
const held = [];
window.__releaseLayout = () => held.splice(0).forEach(resolve => resolve());
window.__printCount = 0;
window.print = () => { window.__printCount += 1; };
window.fetch = async (url, options = {}) => {
  const parsed = new URL(url, location.href);
  if (parsed.pathname.endsWith("/analytics/all") || parsed.pathname.endsWith("/analytics/demographic-reports")) {
    if (state === "loading") await new Promise(resolve => held.push(resolve));
    if (state === "error") return Response.json({ error: "Preview: report service temporarily unavailable." }, { status: 503 });
    const section = parsed.searchParams.get("section");
    return Response.json({ ...(section ? { [section]: sections[section] } : sections), analytics_cache: { age_seconds: 0, computed_at: new Date().toISOString() } });
  }
  if (parsed.pathname.endsWith("/barangays")) return Response.json(barangays.map((barangayName, i) => ({ barangayID: i + 1, barangayName })));
  if (parsed.pathname.endsWith("/filter-metadata")) return Response.json({ lines_of_business: sectors, business_types: [], business_sizes: [] });
  if (parsed.pathname.endsWith("/wlc-config")) return Response.json({ w1_risk: 68, w2_sector: 7, w3_distance: 25 });
  if (parsed.pathname.endsWith("/unread-count")) return Response.json({ count: 0 });
  if (parsed.pathname.endsWith("/stream")) return new Response('data: {"type":"connected"}\n\n', { headers: { "Content-Type": "text/event-stream" } });
  if (parsed.pathname.endsWith("/auth/login")) {
    window.__loginPayload = JSON.parse(options.body);
    return Response.json({ error: "Preview credentials rejected." }, { status: 401 });
  }
  return Response.json({ data: [] });
};

createRoot(document.getElementById("root")).render(<StrictMode><App /></StrictMode>);
