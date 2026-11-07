function positiveID(value) {
  const id = String(value ?? "");
  return /^\d+$/.test(id) && Number(id) > 0 ? id : null;
}

function linkedQueryValue(notification, key) {
  if (typeof notification?.link !== "string") return null;
  try {
    return new URL(notification.link, "https://revela.local").searchParams.get(key);
  } catch {
    return null;
  }
}

export function notificationNavigationTarget(notification) {
  if (["inspection_assigned", "inspection_submitted"].includes(notification?.type)) {
    const reportID = positiveID(notification.reportID) ??
      positiveID(linkedQueryValue(notification, "reportID")) ??
      positiveID(String(notification.body || "").match(/\breport\s+#(\d+)\b/i)?.[1]);
    if (reportID) return `/inspections?reportID=${reportID}&openReport=1`;
  }
  if (notification?.type === "yellow_flag_reported") {
    const logID = positiveID(notification.logID) ??
      positiveID(linkedQueryValue(notification, "flag")) ??
      positiveID(String(notification.body || "").match(/\blog\s+#(\d+)\b/i)?.[1]);
    if (logID) return `/map?flag=${logID}`;
  }
  if (notification?.type === "password_reset_requested") {
    const userID = positiveID(notification.userID ?? notification.requestedUserID) ??
      positiveID(linkedQueryValue(notification, "userID"));
    if (userID) return `/users?userID=${encodeURIComponent(userID)}&openReset=1`;
    const linkedUserName = linkedQueryValue(notification, "userName");
    if (linkedUserName) {
      return `/users?userName=${encodeURIComponent(linkedUserName)}&openReset=1`;
    }
    const userName = String(notification.body || "").match(
      /^(.+?) has requested a manual password reset\./i,
    )?.[1];
    if (userName) return `/users?userName=${encodeURIComponent(userName)}&openReset=1`;
  }
  return typeof notification?.link === "string" && notification.link
    ? notification.link
    : null;
}
