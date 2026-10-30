export const ANALYTICS_SKELETON_DELAY_MS = 150;

export function scheduleAnalyticsSkeleton(show, setTimer = setTimeout, clearTimer = clearTimeout) {
  const timer = setTimer(show, ANALYTICS_SKELETON_DELAY_MS);
  return () => clearTimer(timer);
}
