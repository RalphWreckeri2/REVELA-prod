export const WORKFLOW_SUMMARY_PAGE_SIZE = 20;

const WORKFLOW_SUMMARIES = {
  detection: {
    title: "Run Detection Summary",
    outcomes: [
      ["new_detected", "Newly detected"],
      ["matched", "Matched to registry"],
      ["already_flagged", "Already flagged"],
      ["reconciled", "Reconciled"],
      ["failed", "Failed"],
    ],
  },
  reconcile: {
    title: "Reconcile Summary",
    outcomes: [
      ["reconciled", "Reconciled"],
      ["no_match", "No match"],
      ["unchanged", "Unchanged"],
      ["failed", "Failed"],
    ],
  },
  snap: {
    title: "Snap Pins Summary",
    outcomes: [
      ["snapped", "Updated / snapped"],
      ["no_match", "No match"],
      ["unchanged", "Unchanged"],
      ["cached", "Unchanged / cached"],
      ["skipped_quota", "Skipped by quota"],
      ["api_error", "Failed"],
      ["failed", "Failed"],
    ],
  },
  reverify: {
    title: "Re-verify Summary",
    outcomes: [
      ["reverified", "Reverified / updated"],
      ["review", "Sent for review"],
      ["matched", "Already matched"],
      ["unchanged", "Unchanged"],
      ["no_match", "No match"],
      ["skipped_quota", "Skipped by quota"],
      ["not_processed", "Not processed"],
      ["failed", "Failed"],
    ],
  },
};

export function createWorkflowOperationId(cryptoObject = globalThis.crypto) {
  if (typeof cryptoObject?.randomUUID === "function") {
    return cryptoObject.randomUUID();
  }
  if (typeof cryptoObject?.getRandomValues !== "function") {
    throw new Error("Secure random IDs are unavailable in this browser.");
  }
  const bytes = cryptoObject.getRandomValues(new Uint8Array(16));
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = [...bytes].map((value) => value.toString(16).padStart(2, "0")).join("");
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

export function buildWorkflowSummaryModel(operation, result = {}) {
  const config = WORKFLOW_SUMMARIES[operation];
  if (!config) throw new Error(`Unknown workflow operation: ${operation}`);
  const records = Array.isArray(result.records) ? result.records : [];
  const counts = config.outcomes.map(([key, label]) => ({
    key,
    label,
    count: records.filter((record) => record?.outcome === key).length,
  }));
  const countByLabel = new Map();
  for (const item of counts) {
    countByLabel.set(item.label, (countByLabel.get(item.label) || 0) + item.count);
  }
  const runSummary = result.run_summary || {};
  const contextCounts = operation === "detection"
    ? [
      ["Non-business Places", Number(runSummary.non_business || 0)],
      ["Closed Places results", Number(runSummary.closed_results || 0)],
      ["Duplicate results", Number(runSummary.duplicates || 0)],
    ].filter(([, count]) => count > 0)
    : [];
  return {
    title: config.title,
    records,
    counts: [...countByLabel].map(([label, count]) => ({ label, count })),
    contextCounts,
    contextNote: operation === "detection"
      ? "Detailed rows cover captured business outcomes. Non-business and duplicate scan results are summarized separately."
      : "",
    checked: Number(result.total_checked ?? result.total ?? result.total_candidates ?? 0),
    activityLabel: operation === "detection"
      ? "Places checked"
      : operation === "reconcile"
        ? "red flags"
        : operation === "snap"
          ? "candidates"
          : "pins",
    hasCapturedDetails: records.length > 0,
    emptyMessage: operation === "detection"
      ? result.error
        ? "No new businesses flagged in the captured results for this run."
        : "No new businesses flagged this run."
      : "No records changed in this run.",
    error: result.error || null,
    operationId: result.operation_id || result.run_id || null,
  };
}

export function paginateWorkflowRecords(records, page, pageSize = WORKFLOW_SUMMARY_PAGE_SIZE) {
  const items = Array.isArray(records) ? records : [];
  const safePageSize = Math.max(1, Math.floor(Number(pageSize) || 1));
  const pageCount = Math.max(1, Math.ceil(items.length / safePageSize));
  const currentPage = Math.min(pageCount, Math.max(1, Math.floor(Number(page) || 1)));
  const start = (currentPage - 1) * safePageSize;
  return {
    page: currentPage,
    pageCount,
    total: items.length,
    records: items.slice(start, start + safePageSize),
  };
}
