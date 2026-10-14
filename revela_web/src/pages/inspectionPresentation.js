const SEARCH_FIELDS = [
  "detectedName", "barangayName", "inspectorName", "verificationStatus",
  "inspectionResult", "reportID", "logID",
];

export function matchesDispatchSearch(report, search = "") {
  const query = search.trim().toLowerCase();
  if (!query) return true;
  return SEARCH_FIELDS.map(field => report[field]).filter(Boolean).join(" ").toLowerCase().includes(query);
}

export function matchesGridSearch(report, search = "", initialSearch = "") {
  // An unchanged copied query must match the board exactly, including status text.
  if (search.trim().toLowerCase() === initialSearch.trim().toLowerCase()) {
    return matchesDispatchSearch(report, search);
  }
  if (matchesDispatchSearch(report, search)) return true;
  // Keep the grid's existing #ID lookup when its local query is edited.
  const query = search.trim().toLowerCase();
  const idQuery = query.startsWith("#") ? query.slice(1).trim() : query;
  return String(report.reportID || "").toLowerCase().includes(idQuery)
    || String(report.logID || "").toLowerCase().includes(idQuery);
}

export function inspectionColumnPreview(reports) {
  return { visibleReports: reports.slice(0, 5), hasMore: reports.length > 5 };
}

export function inspectionNoticeLabel(level) {
  if (!(level > 0)) return null;
  return level === 1 ? "1st Notice" : level === 2 ? "2nd Notice" : level === 3 ? "3rd Notice" : "Escalated";
}

export function inspectionDeadline(value) {
  if (!value) return { label: "No deadline set", dateTime: null };
  const date = new Date(value);
  if (!Number.isFinite(date.getTime())) return { label: "Deadline unavailable", dateTime: null };
  return {
    label: date.toLocaleString(undefined, {
      month: "short", day: "numeric", year: "numeric", hour: "numeric", minute: "2-digit",
    }),
    dateTime: date.toISOString(),
  };
}
