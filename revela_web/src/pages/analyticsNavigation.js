export const ANALYTICS_TABS = ["descriptive", "diagnostic", "prescriptive", "operations"];

export function analyticsRoute(search) {
  const params = new URLSearchParams(search);
  const requested = params.get("tab");
  const raw = params.get("barangay_id");
  const barangayId = raw && /^[1-9]\d*$/.test(raw) && Number.isSafeInteger(Number(raw)) ? Number(raw) : null;
  return { tab: ANALYTICS_TABS.includes(requested) ? requested : "descriptive", barangayId };
}
