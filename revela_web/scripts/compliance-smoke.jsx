// Browser-only, synthetic API data. Loaded by verify-compliance-browser.mjs;
// not an application entry point and not part of the production build.
import { useState } from "react";
import { createRoot } from "react-dom/client";
import { MemoryRouter } from "react-router-dom";
import { AuthContext } from "../src/context/authContext";
import { ThemeContext } from "../src/context/themeContext";
import FilterDropdown from "../src/components/FilterDropdown";
import ExportReportsPage from "../src/pages/ExportReportsPage";
import MapPage from "../src/pages/MapPage";
import { STATUS_OPTIONS } from "../src/components/businessCompliance";
import "../src/index.css";
import "../src/styles/global.css";
import "../src/styles/InspectionPage.css";

const results = [];
const check = (condition, message) => { if (!condition) throw new Error(message); results.push(message); };
const wait = async (predicate, label = "browser state") => {
  for (let attempt = 0; attempt < 200; attempt += 1) {
    if (predicate()) return;
    await new Promise(resolve => setTimeout(resolve, 20));
  }
  throw new Error(`Timed out waiting for ${label}`);
};
const button = (text, within = document) => [...within.querySelectorAll("button")].find(node => node.textContent.trim() === text);
const key = (element, name) => element.dispatchEvent(new KeyboardEvent("keydown", { key: name, bubbles: true, cancelable: true }));
const records = Array.from({ length: 25 }, (_, index) => ({
  detectionReference: index + 1, businessName: `Detected Shop ${index + 1}`,
  barangayID: 1, barangayName: "Barangay I", address: "Main Street",
  verifiedOn: "2026-10-16T01:02:03Z", registryLinked: index % 2 === 0,
}));
const mapRows = [
  { logID: 1, detectedName: "L & U Bigasan", flagColor: "Green", originSource: "detection", registryLinked: false, inspectionVerifiedCompliant: true },
  { logID: 2, detectedName: "Linked Detection", flagColor: "Green", originSource: "detection", registryLinked: true, inspectionVerifiedCompliant: true },
  { logID: 3, detectedName: "Inspector Shop", flagColor: "Yellow", originSource: "manual", registryLinked: false, reportedByUserID: 9, verificationStatus: "Assigned" },
  { logID: 4, detectedName: "Warned Detection", flagColor: "Orange", originSource: "detection", registryLinked: false, verificationStatus: "Submitted" },
  { logID: -5, detectedName: "Registry Shop", flagColor: "Green", originSource: "registry", registryLinked: true },
  { logID: 6, detectedName: "Legacy Unknown", flagColor: "Green", originSource: "unknown", registryLinked: false },
].map(row => ({ barangayID: 1, barangayName: "Barangay I", resolvedAddress: "Main Street",
  latitude: 13.9667, longitude: 121.1167, detectedDate: "2026-10-16", ...row }));
let failReport = false;
let prints = 0;
const csvBlobs = [];
window.print = () => { prints += 1; };
const createObjectURL = URL.createObjectURL.bind(URL);
URL.createObjectURL = blob => { if (blob.type.startsWith("text/csv")) csvBlobs.push(blob); return createObjectURL(blob); };
document.addEventListener("click", event => { if (event.target.closest("a[download]")) event.preventDefault(); }, true);
window.fetch = async url => {
  const path = new URL(url, location.href).pathname;
  if (path.endsWith("/inspection-verified-compliant")) {
    if (failReport) return Response.json({ error: "Synthetic report failure" }, { status: 500 });
    return Response.json({ data: records, total: 25, generatedAt: "2026-10-16T02:00:00Z" });
  }
  if (path.endsWith("/demographic-reports")) return Response.json({ descriptive: { kpis: { total_businesses: 0 } } });
  if (/\/flags\/?$/.test(path)) {
    const page = Number(new URL(url, location.href).searchParams.get("page") || 1);
    return Response.json({ data: page === 1 ? mapRows.slice(0, 4) : mapRows.slice(4), pages: 2, total: 6 });
  }
  if (path.endsWith("/detection-quota")) return Response.json({ registry_count: 1, monthly_limit: 10, remaining_this_month: 10 });
  if (path.endsWith("/barangays")) return Response.json([{ barangayID: 1, barangayName: "Barangay I" }]);
  if (path.endsWith("/unread-count")) return Response.json({ count: 0 });
  if (path.endsWith("/stream")) return new Response('data: {"type":"connected"}\n\n', { headers: { "Content-Type": "text/event-stream" } });
  // All remaining application requests stay in this fixture, never production.
  return Response.json({ data: [] });
};

export function DropdownFixture() {
  const [value, setValue] = useState("all");
  return <div><FilterDropdown label="Status" value={value} options={STATUS_OPTIONS} onChange={setValue} />
    <button id="outside" type="button">Outside</button><output>{value}</output></div>;
}

const root = createRoot(document.getElementById("smoke-root"));
try {
  root.render(<DropdownFixture />);
  await wait(() => document.querySelector('[role="combobox"]'));
  const trigger = document.querySelector('[role="combobox"]');
  trigger.focus();
  key(trigger, "ArrowDown");
  await wait(() => trigger.getAttribute("aria-expanded") === "true");
  key(trigger, "End");
  await wait(() => trigger.getAttribute("aria-activedescendant")?.endsWith("-8"), "End-key navigation");
  key(trigger, "Enter");
  await wait(() => document.querySelector("output").textContent === "Purple", "keyboard selection");
  check(document.activeElement === trigger, "Keyboard selection restores combobox focus");
  trigger.click();
  await wait(() => trigger.getAttribute("aria-expanded") === "true");
  key(trigger, "Escape");
  await wait(() => trigger.getAttribute("aria-expanded") === "false");
  check(document.activeElement === trigger, "Escape closes the menu and retains focus");
  trigger.click();
  await wait(() => trigger.getAttribute("aria-expanded") === "true");
  document.getElementById("outside").dispatchEvent(new PointerEvent("pointerdown", { bubbles: true }));
  await wait(() => trigger.getAttribute("aria-expanded") === "false");
  check(true, "Outside pointer closes the menu");

  root.render(<AuthContext.Provider value={{ token: "offline-fixture", user: { role: "Admin", fullName: "Test Admin" }, logout() {} }}>
    <ThemeContext.Provider value={{ isDark: false, theme: "light", setTheme() {} }}>
      <MemoryRouter><ExportReportsPage /></MemoryRouter>
    </ThemeContext.Provider>
  </AuthContext.Provider>);
  await wait(() => document.body.textContent.includes("Official Registry is Currently Empty"));
  check(Boolean(button("View List")), "Compliance report remains available with an empty Official Registry");
  const titles = [...document.querySelectorAll("h3")].map(node => node.textContent);
  check(titles.indexOf("Inspection-Verified Compliant Businesses") === titles.indexOf("List of Unregistered Businesses") + 1
    && titles.indexOf("Field Inspector Dispatch Plan") === titles.indexOf("Inspection-Verified Compliant Businesses") + 1,
  "Operational card order and Dispatch Plan are preserved");
  button("View List").click();
  await wait(() => document.querySelector('[role="dialog"]')?.textContent.includes("25 matching businesses"));
  const dialog = document.querySelector('[role="dialog"]');
  check(dialog.querySelectorAll("tbody tr").length === 10, "Report View List paginates the full dataset");
  button("Next", dialog).click();
  await wait(() => dialog.textContent.includes("Page 2 of 3"));
  check(dialog.querySelector("tbody tr td").textContent === "11", "Page two contains records beyond page one");
  const registry = [...dialog.querySelectorAll('[role="combobox"]')].find(node => node.textContent.includes("All" ) && node.closest(".filter-dropdown").textContent.startsWith("Registry Link"));
  registry.focus(); registry.click();
  await wait(() => registry.getAttribute("aria-expanded") === "true");
  key(registry, "Escape");
  await wait(() => registry.getAttribute("aria-expanded") === "false");
  check(Boolean(document.querySelector('[role="dialog"]')), "Dropdown Escape does not close the containing report dialog");
  registry.click();
  await wait(() => dialog.querySelector('[role="option"]'));
  [...dialog.querySelectorAll('[role="option"]')].find(node => node.textContent.trim() === "Linked to Registry").click();
  await wait(() => dialog.textContent.includes("13 matching businesses"));
  check(dialog.textContent.includes("Page 1 of 2"), "Changing a filter resets report pagination");
  button("Download CSV", dialog).click();
  await wait(() => csvBlobs.length === 1);
  const csv = await csvBlobs[0].text();
  check(csv.split("\r\n").length === 14 && csv.includes("Detected Shop 25"), "CSV exports all 13 filtered rows, including the last page");
  button("Download PDF", dialog).click();
  await wait(() => prints === 1);
  const printed = document.querySelector(".print-report-container");
  check(printed.querySelectorAll("tbody tr").length === 13 && printed.textContent.includes("Detected Shop 25"), "PDF print view exports the same full filtered dataset");
  check(printed.textContent.includes("Asia/Manila") && printed.textContent.includes("Record count:")
    && printed.textContent.includes("Linked to Registry"), "PDF includes Manila dates, filters, and record count");
  window.dispatchEvent(new Event("afterprint"));
  failReport = true;
  button("Refresh list", dialog).click();
  await wait(() => dialog.querySelector('[role="alert"]'));
  check(dialog.textContent.includes("Synthetic report failure"), "Report failures are displayed rather than reported as empty success");
  failReport = false;
  button("Retry", dialog).click();
  await wait(() => dialog.textContent.includes("13 matching businesses") && !dialog.querySelector('[role="alert"]'));
  check(true, "Report retry restores the filtered result list");
  button("Clear filters", dialog).click();
  await wait(() => dialog.textContent.includes("25 matching businesses"));
  const input = dialog.querySelector('input[type="search"]');
  Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set.call(input, "does-not-exist");
  input.dispatchEvent(new Event("input", { bubbles: true }));
  await wait(() => dialog.textContent.includes("No inspection-verified compliant businesses match these filters."));
  check(dialog.textContent.includes("0 matching businesses"), "Report empty results have a consistent zero count");
  check(document.documentElement.scrollWidth <= window.innerWidth, "Supported narrow viewport has no page-level horizontal overflow");

  root.render(<AuthContext.Provider value={{ token: "offline-fixture", user: { role: "Admin", fullName: "Test Admin" }, logout() {} }}>
    <ThemeContext.Provider value={{ isDark: false, theme: "light", setTheme() {} }}>
      <MemoryRouter><MapPage /></MemoryRouter>
    </ThemeContext.Provider>
  </AuthContext.Provider>);
  await wait(() => document.querySelector(".map-location-count")?.textContent.includes("6 matching locations"), "Map pages to load");
  const dropdowns = [...document.querySelectorAll('.map-location-filters [role="combobox"]')];
  check(dropdowns.length === 3 && dropdowns[0].closest(".filter-dropdown").textContent.startsWith("Status")
    && dropdowns[1].closest(".filter-dropdown").textContent.startsWith("Source")
    && dropdowns[2].closest(".filter-dropdown").textContent.startsWith("Registry Link"), "Map has the three ordered dropdowns and loads all API pages");
  const select = async (trigger, label) => {
    trigger.focus(); trigger.click();
    await wait(() => trigger.getAttribute("aria-expanded") === "true");
    [...trigger.closest(".filter-dropdown").querySelectorAll('[role="option"]')]
      .find(node => node.textContent.trim().replace(/✓$/, "").trim() === label).click();
    await wait(() => trigger.getAttribute("aria-expanded") === "false");
  };
  await select(dropdowns[0], "Active Business");
  await select(dropdowns[1], "Business Detection");
  await select(dropdowns[2], "Inspection-verified compliant · Not in Registry");
  await wait(() => document.querySelectorAll(".map-location-card").length === 1);
  check(document.querySelector(".map-location-card").textContent.includes("L & U Bigasan"), "Map source/status/registry filters combine with AND logic");
  document.querySelector(".map-location-card").click();
  await wait(() => document.querySelector(".business-source-info"));
  const info = document.querySelector(".business-source-info");
  check(info.textContent.includes("Source: Business Detection")
    && info.textContent.includes("Inspection-verified compliant · Not yet in imported registry")
    && info.previousElementSibling.textContent.includes("Main Street"), "Business details show the source and exact neutral indicator below the address");
  mapRows[0].registryLinked = true;
  window.dispatchEvent(new CustomEvent("revela:registry-update"));
  await wait(() => !document.querySelector(".business-compliance-info"), "linked detail refresh");
  check(info.textContent.includes("Source: Business Detection"), "Refresh removes the Not yet indicator after linking without losing source");
  document.querySelector(".modal-backdrop").click();
  await wait(() => !document.querySelector(".business-source-info"));
  button("Clear filters").click();
  await wait(() => document.querySelectorAll(".map-location-card").length === 6);
  await select(dropdowns[0], "Currently Being Inspected / Dispatched");
  await select(dropdowns[1], "Business Detection");
  await wait(() => document.querySelectorAll(".map-location-card").length === 1);
  check(document.querySelector(".map-location-card").textContent.includes("Warned Detection"), "Map workflow filter includes dispatched Orange without treating workflow as a color");
  check(document.documentElement.scrollWidth <= window.innerWidth, "Map filters and locations remain readable at the narrow supported viewport");
  document.getElementById("compliance-smoke-results").textContent = JSON.stringify({ passed: results.length, results });
} catch (error) {
  document.getElementById("compliance-smoke-results").textContent = JSON.stringify({ failed: error.message, passed: results.length, results });
}
