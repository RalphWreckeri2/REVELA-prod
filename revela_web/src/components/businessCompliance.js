import Papa from "papaparse";

// These are view predicates over the backend's shared effective-colour result.
// Registry membership is never inferred from businessID, source, or a name.
export const STATUS_OPTIONS = Object.freeze([
  { value: "all", label: "All Locations" },
  { value: "in_inspection", label: "Currently Being Inspected / Dispatched" },
  { value: "Green", label: "Active Business" },
  { value: "Yellow", label: "Suspected Unregistered" },
  { value: "Yellow_Inspector", label: "Suspected Unregistered from Inspectors" },
  { value: "Orange", label: "1st/2nd Warning / 3rd Notice Closure" },
  { value: "Red", label: "Detected Unregistered" },
  { value: "Black", label: "Blacklisted / Non-Responsive" },
  { value: "Purple", label: "Closed / Abandoned" },
]);

export const BUSINESS_SOURCE_OPTIONS = Object.freeze([
  { value: "all", label: "All Sources" },
  { value: "detection", label: "Business Detection" },
  { value: "manual", label: "Inspector Report" },
  { value: "registry", label: "Official BPLO Registry" },
]);

export const REGISTRY_LINK_OPTIONS = Object.freeze([
  { value: "all", label: "All" },
  { value: "linked", label: "Linked to Registry" },
  { value: "unlinked", label: "Not in Registry" },
]);
export const MAP_REGISTRY_LINK_OPTIONS = Object.freeze([
  ...REGISTRY_LINK_OPTIONS,
  { value: "compliant_unlinked", label: "Inspection-verified compliant · Not in Registry" },
]);
export const UNLINKED_COMPLIANCE_TEXT = "Inspection-verified compliant · Not yet in imported registry";
export const COMPLIANCE_REPORT_TITLE = "Inspection-Verified Compliant Businesses";
export const COMPLIANCE_REPORT_DESCRIPTION = "Current admin-verified Green inspections, including linked manual-origin pins and historical unlinked pin references. Linked businesses are classified by their latest valid confirmation.";
export const COMPLIANCE_REPORT_SCOPE = "Distinct confirmed registry businesses with effective Green status and current admin-verification evidence. Office-confirmed businesses are counted separately; Green color alone is not sufficient.";
export const COMPLIANCE_COLUMNS = Object.freeze([
  "Pin Reference", "Business Name", "Barangay", "Address", "Verified On", "Registry Link",
]);

export function businessSourceLabel(source) {
  if (source === "registry_detected") return "Official BPLO Registry";
  return BUSINESS_SOURCE_OPTIONS.find(option => option.value === source && source !== "all")?.label
    ?? "Unknown origin";
}

export function isRegistryLinked(record) {
  return record?.registryLinked === true;
}

export function hasUnlinkedCompliance(record) {
  return record?.inspectionVerifiedCompliant === true
    && (record.color ?? record.flagColor) === "Green" && !isRegistryLinked(record);
}

export function businessDetailsInfo(record) {
  return {
    source: `Source: ${businessSourceLabel(record?.originSource ?? record?.source)}`,
    compliance: hasUnlinkedCompliance(record) ? UNLINKED_COMPLIANCE_TEXT : null,
  };
}

export function matchesRegistryLink(record, value = "all") {
  if (value === "linked") return isRegistryLinked(record);
  if (value === "unlinked") return !isRegistryLinked(record);
  if (value === "compliant_unlinked") return hasUnlinkedCompliance(record);
  return true;
}

export function matchesMapFilters(record, {
  status = "all", source = "all", registryLink = "all", search = "", barangayID = "all",
} = {}) {
  const color = record.color ?? record.flagColor;
  const workflow = record.hasActiveInspection === true
    || (record.verificationStatus != null && record.verificationStatus !== "Verified");
  const statusMatches = status === "all" || (status === "in_inspection" ? workflow
    : status === "Yellow_Inspector" ? color === "Yellow" && Boolean(record.reportedByUserID)
      : color === status);
  const origin = record.originSource ?? record.source ?? "unknown";
  const sourceMatches = source === "all" || origin === source
    || (source === "registry" && origin === "registry_detected");
  const q = search.trim().toLowerCase();
  const referenceQuery = q.startsWith("#") ? q.slice(1).trim() : q;
  const searchMatches = !q || [record.name, record.detectedName, record.barangay,
    record.barangayName, record.address, record.notes, record.businessType]
    .some(value => String(value ?? "").toLowerCase().includes(q))
    || [record.id, record.logID].some(value => value != null
      && String(value).toLowerCase().includes(referenceQuery));
  return statusMatches && sourceMatches && searchMatches
    && (barangayID === "all" || String(record.barangayID) === String(barangayID))
    && matchesRegistryLink(record, registryLink);
}

export function paginateRecords(records, page = 1, pageSize = 10) {
  const pages = Math.max(1, Math.ceil(records.length / pageSize));
  const current = Math.max(1, Math.min(page, pages));
  return { page: current, pages, total: records.length,
    data: records.slice((current - 1) * pageSize, current * pageSize) };
}

export function filterComplianceRecords(records, {
  search = "", barangayID = "all", registryLink = "all",
} = {}) {
  const q = search.trim().toLowerCase().replace(/^#\s*/, "");
  return records.filter(record => (!q
    || String(record.businessName ?? "").toLowerCase().includes(q)
    || String(record.detectionReference).toLowerCase().includes(q))
    && (barangayID === "all" || String(record.barangayID) === String(barangayID))
    && matchesRegistryLink(record, registryLink));
}

export function formatManilaDate(value) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return `${new Intl.DateTimeFormat("en-PH", {
    timeZone: "Asia/Manila", year: "numeric", month: "short", day: "2-digit",
    hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false,
  }).format(date)} (Asia/Manila)`;
}

export function complianceRow(record) {
  return {
    "Pin Reference": String(record.detectionReference),
    "Business Name": record.businessName ?? "",
    Barangay: record.barangayName ?? "",
    Address: record.address ?? "",
    "Verified On": formatManilaDate(record.verifiedOn),
    "Registry Link": isRegistryLinked(record) ? "Linked to Registry" : "Not in Registry",
  };
}

// View List, CSV and PDF all consume this full filtered snapshot. Pagination
// happens afterwards, exclusively for the screen table.
export function buildComplianceReport(records, filters = {}, generatedAt = new Date().toISOString()) {
  const matching = filterComplianceRecords(records, filters);
  const barangay = records.find(record => String(record.barangayID) === String(filters.barangayID))?.barangayName;
  return {
    title: COMPLIANCE_REPORT_TITLE, scope: COMPLIANCE_REPORT_SCOPE,
    date: formatManilaDate(generatedAt), count: matching.length,
    filtersLabel: `Search: ${filters.search?.trim() || "All"}; Barangay: ${filters.barangayID && filters.barangayID !== "all" ? filters.barangayName || barangay || filters.barangayID : "All"}; Registry Link: ${REGISTRY_LINK_OPTIONS.find(option => option.value === filters.registryLink)?.label || "All"}`,
    columns: COMPLIANCE_COLUMNS, records: matching, rows: matching.map(complianceRow),
  };
}

export function complianceCsv(report) {
  const csv = Papa.unparse({
    fields: report.columns, data: report.rows.map(row => report.columns.map(column => row[column])),
  }, { escapeFormulae: /^\s*[=+\-@]|^[\t\r]/ });
  return "\uFEFF" + (report.count === 0 ? csv.replace(/\r?\n$/, "") : csv);
}

export function compliancePrintReport(report, user) {
  return {
    type: "inspection-compliant", title: report.title, subtitle: report.scope,
    date: report.date, preparedBy: user?.fullName || "BPLO Staff",
    office: "BPLO Mataasnakahoy", classification: "Operational Report · Current Compliance",
    isLandscape: true, data: report,
  };
}
