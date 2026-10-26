const scanHistoryDateFormat = new Intl.DateTimeFormat("en-PH", {
  timeZone: "Asia/Manila",
  year: "numeric",
  month: "short",
  day: "numeric",
  hour: "numeric",
  minute: "2-digit",
  hour12: true,
});

export function formatScanHistoryTimestamp(value) {
  if (!value) return "—";

  const timestamp = String(value);
  const normalized = /^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}/.test(timestamp)
    && !/(Z|[+-]\d{2}:?\d{2})$/i.test(timestamp)
    ? `${timestamp.replace(" ", "T")}Z`
    : timestamp;
  const date = new Date(normalized);

  return Number.isNaN(date.getTime())
    ? timestamp
    : scanHistoryDateFormat.format(date);
}
