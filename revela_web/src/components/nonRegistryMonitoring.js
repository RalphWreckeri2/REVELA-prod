import Papa from "papaparse";
import { businessSourceLabel, formatManilaDate } from "./businessCompliance.js";

export const NON_REGISTRY_PIN_COLORS = Object.freeze([
  { key: "Green", color: "#10b981" },
  { key: "Red", color: "#f43f5e" },
  { key: "Yellow", color: "#f59e0b" },
  { key: "Orange", color: "#f97316" },
  { key: "Black", color: "#475569" },
  { key: "Purple", color: "#8b5cf6" },
  { key: "Unknown", color: "#94a3b8" },
]);

export const NON_REGISTRY_COLUMNS = Object.freeze([
  "Pin Reference", "Business Name", "Barangay", "Address", "Source", "Current Flag",
  "Inspection Status", "Inspection-Verified Compliant", "Verified On", "Registry Link",
]);

export function isNonRegistrySnapshot(snapshot) {
  return isPinMonitoringSnapshot(snapshot, false);
}

export function isRegistryLinkedSnapshot(snapshot) {
  return isPinMonitoringSnapshot(snapshot, true);
}

function isPinMonitoringSnapshot(snapshot, linked) {
  return Boolean(snapshot && Array.isArray(snapshot.records) && Array.isArray(snapshot.by_barangay)
    && ["total", "needs_verification", "under_inspection", "verified_green"].every(key =>
      Number.isInteger(snapshot.summary?.[key]) && snapshot.summary[key] >= 0)
    && snapshot.summary.total === snapshot.records.length
    && snapshot.records.every(row => row.registryLinked === linked)
    && typeof snapshot.generated_at === "string" && Number.isFinite(Date.parse(snapshot.generated_at)));
}

export function nonRegistryRows(records) {
  return records.map(row => ({
    "Pin Reference": String(row.logID),
    "Business Name": row.detectedName || "Unnamed pin",
    Barangay: row.barangayName || "Unknown barangay",
    Address: row.address || "",
    Source: businessSourceLabel(row.originSource),
    "Current Flag": row.flagColor,
    "Inspection Status": row.verificationStatus || "Not assigned",
    "Inspection-Verified Compliant": row.verifiedGreen === true ? "Yes" : "No",
    "Verified On": row.verifiedGreen === true ? formatManilaDate(row.verifiedGreenAt) : "—",
    "Registry Link": row.registryLinked ? "Linked to Registry" : "Not in Registry",
  }));
}

export function nonRegistryCsv(snapshot) {
  if (!isNonRegistrySnapshot(snapshot)) throw new Error("The non-registry snapshot is unavailable. Refresh Analytics before exporting.");
  return monitoringCsv(snapshot);
}

export function registryLinkedCsv(snapshot) {
  if (!isRegistryLinkedSnapshot(snapshot)) throw new Error("The Registry-linked snapshot is unavailable. Refresh Analytics before exporting.");
  return monitoringCsv(snapshot);
}

function monitoringCsv(snapshot) {
  const rows = nonRegistryRows(snapshot.records);
  const csv = Papa.unparse({
    fields: [...NON_REGISTRY_COLUMNS, "Snapshot Checked At"],
    data: rows.map(row => [...NON_REGISTRY_COLUMNS.map(column => row[column]), formatManilaDate(snapshot.generated_at)]),
  }, { escapeFormulae: /^\s*[=+\-@]|^[\t\r]/ });
  return "\uFEFF" + (rows.length === 0 ? csv.replace(/\r?\n$/, "") : csv);
}
