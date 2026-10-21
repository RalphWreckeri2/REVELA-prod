// Synthetic API responses only. The browser runner also blocks external DNS.
import { createRoot } from "react-dom/client";
import { MemoryRouter } from "react-router-dom";
import InspectionPage from "../src/pages/InspectionPage";
import { AuthContext } from "../src/context/authContext";
import { ThemeContext } from "../src/context/themeContext";
import { previewGreenRegistryLinkRequest, verifyInspectionRequest } from "../src/services/api";
import "../src/index.css";
import "../src/styles/global.css";

const checks = [];
const check = (condition, message) => { if (!condition) throw new Error(message); checks.push(message); };
const wait = async (predicate, label) => {
  for (let attempt = 0; attempt < 200; attempt += 1) {
    if (predicate()) return;
    await new Promise(resolve => setTimeout(resolve, 20));
  }
  throw new Error(`Timed out waiting for ${label}`);
};
const button = text => [...document.querySelectorAll("button")].find(node => node.textContent.trim() === text);
const input = (node, value) => {
  Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set.call(node, value);
  node.dispatchEvent(new Event("input", { bubbles: true }));
};
const reports = [
  { reportID: 1, logID: 21, detectedName: "Existing linked shop", linkedBusinessID: "BPLO-001" },
  { reportID: 2, logID: 22, detectedName: "New field shop", linkedBusinessID: null },
].map(row => ({ ...row, verificationStatus: "Submitted", inspectionResult: "Green", flagColor: "Yellow",
  inspectorName: "Isolated Inspector", barangayID: 1, barangayName: "Barangay I", latitude: 13.9667, longitude: 121.1167,
  verifiedLatitude: 13.9680, verifiedLongitude: 121.1180, verifiedAccuracy: 8 }));
const submissions = [];
let missingName = false;
let conflict = false;
let reviewFailure = null;
let verificationFailure = null;
window.fetch = async (url, options = {}) => {
  const parsed = new URL(url, location.href);
  if (/\/inspections\/?$/.test(parsed.pathname)) return Response.json({ data: reports, total: 2, pages: 1 });
  const review = parsed.pathname.match(/\/inspections\/(\d+)\/green-registry-link$/);
  if (review) {
    if (reviewFailure === "network") throw new TypeError("Failed to fetch");
    if (reviewFailure === "missing-route") return new Response("<!doctype html><title>404 Not Found</title>", { status: 404, headers: { "Content-Type": "text/html" } });
    if (reviewFailure === "proxy") return new Response("Bad Gateway", { status: 502 });
    if (reviewFailure === "validation") return Response.json({ error: "Could not fetch registry details for this Business ID.", code: "green_registry_link_invalid" }, { status: 400 });
    if (conflict) return Response.json({ error: "This Business ID is already confirmed against a different pin.", code: "green_registry_link_conflict" }, { status: 409 });
    const report = reports.find(row => row.reportID === Number(review[1]));
    return Response.json({
      businessID: parsed.searchParams.get("businessID").trim().toUpperCase(), reviewToken: "isolated-review-token",
      registryExists: Boolean(report.linkedBusinessID),
      registry: { businessName: missingName ? null : report.detectedName, barangayID: 1, businessAddress: null },
      pin: { logID: report.logID, detectedName: report.detectedName, latitude: report.latitude, longitude: report.longitude, source: "manual" },
      missingRequiredFields: missingName ? ["businessName"] : [],
      barangays: [{ barangayID: 1, barangayName: "Barangay I" }],
    });
  }
  if (/\/inspections\/\d+\/verify$/.test(parsed.pathname)) {
    if (verificationFailure === "network") throw new TypeError("Failed to fetch");
    if (verificationFailure === "conflict") return Response.json({ error: "Review the registry link again before confirming.", code: "green_registry_link_conflict" }, { status: 409 });
    submissions.push(JSON.parse(options.body));
    return Response.json({ status: "Verified", locationUpdated: false });
  }
  if (parsed.pathname.endsWith("/unread-count")) return Response.json({ count: 0 });
  if (parsed.pathname.endsWith("/stream")) return new Response('data: {"type":"connected"}\n\n', { headers: { "Content-Type": "text/event-stream" } });
  return Response.json({ data: [] });
};

const root = createRoot(document.getElementById("smoke-root"));
try {
  root.render(<AuthContext.Provider value={{ token: "offline-fixture", user: { role: "Admin", fullName: "Test Admin" }, logout() {} }}>
    <ThemeContext.Provider value={{ isDark: false, theme: "light", setTheme() {} }}><MemoryRouter><InspectionPage /></MemoryRouter></ThemeContext.Provider>
  </AuthContext.Provider>);
  const open = async reportID => {
    await wait(() => document.querySelector(`[data-report-id="${reportID}"]`), "submitted inspection card");
    document.querySelector(`[data-report-id="${reportID}"]`).click();
    await wait(() => button("Verify"), "inspection detail");
    button("Verify").click();
    await wait(() => document.getElementById("green-business-id"), "Green confirmation");
  };
  await open(1);
  check(document.getElementById("green-business-id").value === "BPLO-001" && document.getElementById("green-business-id").readOnly, "Already linked Business ID is shown and read-only");
  check(button("Confirm & Verify").disabled, "Green confirmation is disabled until Business ID review and attestation");
  button("Review Business ID").click();
  await wait(() => document.querySelector('[aria-label="Official registry link"] input[type="checkbox"]'), "registry identity review");
  check(button("Confirm & Verify").disabled && submissions.length === 0, "Reviewing an ID does not verify the report");
  const attestation = () => document.querySelector('[aria-label="Official registry link"] input[type="checkbox"]');
  attestation().click();
  await wait(() => !button("Confirm & Verify").disabled, "admin attestation");
  check(document.querySelectorAll('[role="dialog"] input[type="checkbox"]').length === 1, "Green confirmation offers no GPS relocation option");
  button("Confirm & Verify").click();
  await wait(() => submissions.length === 1 && !document.getElementById("green-business-id"), "atomic confirmation request");
  check(submissions[0].businessID === "BPLO-001" && submissions[0].registryReviewToken === "isolated-review-token" && submissions[0].confirmEstablishment && submissions[0].updateLocation === false, "Confirmation sends official ID, reviewed identity, attestation and original-location choice together");
  await wait(() => !document.querySelector('[role="dialog"]'), "closed verification");

  missingName = true;
  await open(2);
  input(document.getElementById("green-business-id"), "BPLO-002");
  await wait(() => !button("Review Business ID").disabled, "entered Business ID");
  button("Review Business ID").click();
  await wait(() => attestation(), "new registry review");
  const requiredName = [...document.querySelectorAll("label")].find(node => node.textContent.includes("Official business name"))?.querySelector("input");
  check(Boolean(requiredName), "New registry requests a missing required name");
  attestation().click();
  await new Promise(resolve => setTimeout(resolve, 30));
  check(button("Confirm & Verify").disabled, "Missing required registry details prevent confirmation");
  input(requiredName, "Actual official business name");
  await wait(() => !attestation().checked, "edited details invalidate attestation");
  attestation().click();
  await wait(() => !button("Confirm & Verify").disabled, "completed required fields");
  check(!document.querySelector('[aria-label="Official registry link"] select'), "Known barangay is reused instead of requested again");
  input(document.getElementById("green-business-id"), "CONFLICT-ID");
  await wait(() => !attestation(), "ID edit invalidates review");
  check(button("Confirm & Verify").disabled, "Changing the Business ID requires a fresh review");
  conflict = true;
  button("Review Business ID").click();
  await wait(() => document.body.textContent.includes("already confirmed against a different pin"), "conflicting link error");
  check(submissions.length === 1 && button("Confirm & Verify").disabled, "Conflicting links cannot submit a verification");
  conflict = false;
  for (const [failure, code, status, message] of [
    ["validation", "green_registry_link_invalid", 400, "Could not fetch registry details for this Business ID."],
    ["network", "api_network_error", undefined, "Business ID review could not reach the API"],
    ["missing-route", "api_endpoint_not_found", 404, "endpoint was not found (HTTP 404)"],
    ["proxy", "api_invalid_response", 502, "unexpected API response (HTTP 502)"],
  ]) {
    reviewFailure = failure;
    button("Review Business ID").click();
    await wait(() => document.body.textContent.includes(message), `${failure} review message`);
    let caught;
    try { await previewGreenRegistryLinkRequest(2, "BPLO-002", "offline-fixture"); } catch (error) { caught = error; }
    check(caught?.code === code && caught?.status === status && caught?.message.includes(message), `${failure} review error preserves its distinct code, HTTP status and user message`);
    check(submissions.length === 1 && button("Confirm & Verify").disabled, `${failure} review failure cannot submit a verification`);
  }
  for (const [failure, code, status] of [["network", "api_network_error", undefined], ["conflict", "green_registry_link_conflict", 409]]) {
    verificationFailure = failure;
    let caught;
    try { await verifyInspectionRequest(2, "offline-fixture", false, { businessID: "BPLO-002" }); } catch (error) { caught = error; }
    check(caught?.code === code && caught?.status === status, `Verification distinguishes ${failure} failures without hiding backend validation`);
  }
  document.getElementById("green-link-smoke-results").textContent = JSON.stringify({ passed: checks.length, failed: 0, checks });
} catch (error) {
  document.getElementById("green-link-smoke-results").textContent = JSON.stringify({ passed: checks.length, failed: 1, error: String(error), checks });
} finally {
  root.unmount();
}
