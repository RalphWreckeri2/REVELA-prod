/** Format a measured duration in minutes; do not use for whole-day-only ages. */
export function formatElapsedMinutes(minutes) {
  if (typeof minutes !== "number" || !Number.isFinite(minutes) || minutes < 0) return "Unavailable";

  // Round the total first so carries at 60 minutes / 24 hours are correct.
  const total = Math.round(minutes);
  if (!Number.isSafeInteger(total)) return "Unavailable";
  if (total === 0) return "0 min";

  const days = Math.floor(total / 1440);
  const hours = Math.floor((total % 1440) / 60);
  const remainingMinutes = total % 60;
  return [days && `${days}d`, hours && `${hours}h`, remainingMinutes && `${remainingMinutes} min`]
    .filter(Boolean).join(" ");
}
