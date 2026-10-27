export const ANALYTICS_MAX_STALE_MS = 15 * 60 * 1000;

export function analyticsSnapshotMatchesFilters(snapshot, filters) {
  return Boolean(snapshot && snapshot.filters === filters);
}

export function analyticsSnapshotDeadline(metadata, requestStartedAt, wallNow = Date.now()) {
  if (!metadata || metadata.expired || !Number.isFinite(Date.parse(metadata.computed_at))) return 0;
  if (Number.isFinite(metadata.age_seconds)) {
    if (metadata.age_seconds < 0) return 0;
    // Anchor to request START, not receipt: network delay cannot extend validity,
    // and a browser/server clock difference cannot reset the 15-minute age cap.
    return requestStartedAt + ANALYTICS_MAX_STALE_MS - metadata.age_seconds * 1000;
  }
  return requestStartedAt + Date.parse(metadata.computed_at) + ANALYTICS_MAX_STALE_MS - wallNow;
}

export function analyticsSnapshotExpired(snapshot, now, wallNow = Date.now()) {
  return Boolean(snapshot && (snapshot.expired || !Number.isFinite(snapshot.expiresAt)
    || now > snapshot.expiresAt
    || (Number.isFinite(snapshot.wallExpiresAt) && wallNow > snapshot.wallExpiresAt)));
}

export function analyticsRefreshPending(metadata) {
  return Boolean(metadata?.refreshing || metadata?.refresh_deferred);
}

export function analyticsSnapshotStatus(metadata) {
  if (metadata?.expired) return "Snapshot expired — last successful results are historical (maximum fresh age: 15 minutes)";
  if (metadata?.refreshing) return "Cached snapshot — refreshing in the background";
  if (metadata?.refresh_failed) return "Cached snapshot — refresh failed; will retry";
  if (metadata?.refresh_deferred) return "Cached snapshot — waiting to refresh";
  return metadata?.stale ? "Cached snapshot" : "Latest cached snapshot";
}
