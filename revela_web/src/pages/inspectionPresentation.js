import { formatOverviewPeriod, formatOverviewUpdatedAt } from "./overviewPresentation.js";

const SEARCH_FIELDS = [
  "detectedName", "barangayName", "inspectorName", "verificationStatus",
  "inspectionResult", "reportID", "logID",
];

const WORKLOAD_FILTER_LABELS = Object.freeze({
  all: "All inspection reports",
  open: "Open assignments",
  overdue: "Overdue assignments",
  awaiting_verification: "Reports awaiting verification",
  oldest: "Oldest open assignment",
  resolution: "Average resolution time",
  "age_0-3": "Assignments open 0–3 days",
  "age_4-7": "Assignments open 4–7 days",
  "age_8-14": "Assignments open 8–14 days",
  "age_15+": "Assignments open 15+ days",
  age_unavailable: "Assignments with unknown age",
  deadline_missing: "Assignments without a due date",
});

function deadlineDayLabel(value) {
  if (typeof value !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return null;
  const [year, month, day] = value.split("-").map(Number);
  const date = new Date(Date.UTC(year, month - 1, day));
  if (!Number.isFinite(date.getTime())) return null;
  return date.toLocaleDateString("en-US", { timeZone: "UTC", month: "short", day: "numeric" });
}

export function workloadFilterLabel(view, deadlineDate) {
  if (view === "deadline_day") {
    const day = deadlineDayLabel(deadlineDate);
    return day ? `Assignments due ${day}` : "Assignments due that day";
  }
  return WORKLOAD_FILTER_LABELS[view] ?? WORKLOAD_FILTER_LABELS.all;
}

export function workloadResultLabel(total, page = 1, pageSize = 20) {
  const count = Number.isFinite(Number(total)) ? Math.max(0, Number(total)) : 0;
  const size = Number.isFinite(Number(pageSize)) ? Math.max(1, Math.floor(Number(pageSize))) : 20;
  const current = Number.isFinite(Number(page)) ? Math.max(1, Math.floor(Number(page))) : 1;
  if (count === 0) return "Showing 0 of 0";
  const pages = Math.ceil(count / size);
  if (pages <= 1) return `Showing ${count} of ${count}`;
  const visiblePage = Math.min(current, pages);
  const first = (visiblePage - 1) * size + 1;
  const last = Math.min(visiblePage * size, count);
  return `Showing ${first}–${last} of ${count}`;
}

export function dashboardUpdatedLabel(value) {
  const label = formatOverviewUpdatedAt(value);
  return label ? label.replace(/^Updated /, "Dashboard data updated ") : null;
}

export function inspectionPeriodLabel(from, to) {
  return formatOverviewPeriod(from, to);
}

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
  if (!value) return { label: "No deadline", dateTime: null };
  const date = new Date(value);
  if (!Number.isFinite(date.getTime())) return { label: "Deadline unavailable", dateTime: null };
  return {
    label: date.toLocaleString(undefined, {
      month: "short", day: "numeric", year: "numeric", hour: "numeric", minute: "2-digit",
    }),
    dateTime: date.toISOString(),
  };
}
