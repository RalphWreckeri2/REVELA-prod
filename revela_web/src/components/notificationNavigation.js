export function notificationNavigationTarget(notification) {
  if (notification?.type === "inspection_submitted") {
    const reportID = String(notification.body || "").match(/\breport\s+#(\d+)\b/i)?.[1];
    if (reportID) return `/inspections?reportID=${reportID}&openReport=1`;
  }
  return typeof notification?.link === "string" && notification.link
    ? notification.link
    : null;
}
