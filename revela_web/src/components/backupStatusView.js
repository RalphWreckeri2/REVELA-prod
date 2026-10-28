const STATUS_LABELS = {
  not_configured: { text: "Not configured", tone: "neutral" },
  ready: { text: "Ready", tone: "ready" },
  running: { text: "Running", tone: "warning" },
  failed: { text: "Failed", tone: "error" },
};

// Reject incomplete responses instead of turning missing flags into readiness.
export function validateBackupStatus(data) {
  if (!data || !Object.hasOwn(STATUS_LABELS, data.status)
    || typeof data.configured !== "boolean"
    || (data.status === "ready" && !data.configured)
    || typeof data.schedule?.configured !== "boolean"
    || typeof data.schedule?.enabled !== "boolean"
    || typeof data.retention?.configured !== "boolean"
    || !(data.lastSuccessfulBackup === null || isBackupRecord(data.lastSuccessfulBackup, true))
    || !(data.history === null || (Array.isArray(data.history) && data.history.every(row => isBackupRecord(row))))) {
    throw new Error("The backend returned an incomplete database backup status. Backup actions remain unavailable.");
  }
  return data;
}

function isBackupRecord(record, completed = false) {
  return record && typeof record === "object"
    && typeof record.id === "string" && record.id.length > 0
    && ["manual", "automatic"].includes(record.trigger)
    && ["completed", "running", "failed"].includes(record.status)
    && (!completed || record.status === "completed");
}

export function formatBackupDate(value) {
  // Unzoned timestamps are ambiguous. Never interpret them in the browser's zone.
  if (typeof value !== "string" || !/T.*(?:Z|[+-]\d{2}:\d{2})$/i.test(value)) return "—";
  const date = new Date(value);
  if (!Number.isFinite(date.getTime())) return "—";
  return new Intl.DateTimeFormat("en-PH", {
    timeZone: "Asia/Manila", year: "numeric", month: "short", day: "numeric",
    hour: "numeric", minute: "2-digit", hour12: true,
  }).format(date);
}

export function formatBackupSize(bytes) {
  if (typeof bytes !== "number" || !Number.isFinite(bytes) || bytes < 0) return "—";
  if (bytes < 1024) return `${bytes} B`;
  const unit = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), 3);
  return `${new Intl.NumberFormat("en-PH", { maximumFractionDigits: 2 }).format(bytes / (1024 ** unit))} ${["B", "KB", "MB", "GB"][unit]}`;
}

export function backupStatusPresentation(data, loading, error) {
  if (loading) return { text: "Loading…", tone: "neutral", summary: "Checking database backup status…" };
  if (error || !data) return { text: "Status unavailable", tone: "error", summary: "Could not verify database backup status. Refresh Status to retry." };
  return {
    ...STATUS_LABELS[data.status],
    summary: `${STATUS_LABELS[data.status].text} · ${data.lastSuccessfulBackup
      ? `Last successful backup: ${formatBackupDate(data.lastSuccessfulBackup.completedAt)} · ${formatBackupSize(data.lastSuccessfulBackup.sizeBytes)}`
      : "No successful backup yet"}`,
  };
}
