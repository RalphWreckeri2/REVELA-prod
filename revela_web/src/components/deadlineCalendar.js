const MANILA_OFFSET_MS = 8 * 60 * 60 * 1000;
const dayFormat = new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Manila", year: "numeric", month: "2-digit", day: "2-digit" });

export function manilaToday(now = new Date()) {
  const parts = Object.fromEntries(dayFormat.formatToParts(now).map(part => [part.type, part.value]));
  return `${parts.year}-${parts.month}-${parts.day}`;
}

export function recordedDeadline(value) {
  if (typeof value !== "string") return null;
  const match = value.trim().match(/^(\d{4})-(\d{2})-(\d{2})(?:[ T](\d{2}):(\d{2})(?::(\d{2})(?:\.\d{1,6})?)?(Z|[+-]\d{2}:\d{2})?)?$/);
  if (!match) return null;
  const [, yearText, monthText, dayText, hourText, minuteText, secondText, zone] = match;
  const [year, month, day, hour, minute, second] = [yearText, monthText, dayText, hourText || 0, minuteText || 0, secondText || 0].map(Number);
  if (year < 1000 || month < 1 || month > 12 || day < 1 || hour > 23 || minute > 59 || second > 59) return null;
  // UTC methods validate civil fields only: naive deadlines are never parsed as
  // UTC or in the viewer's timezone. Their recorded wall time is assumed Manila.
  const civil = new Date(Date.UTC(year, month - 1, day, hour, minute, second));
  if (civil.getUTCFullYear() !== year || civil.getUTCMonth() !== month - 1 || civil.getUTCDate() !== day) return null;
  let date = `${yearText}-${monthText}-${dayText}`;
  let clock = hourText ? `${hourText}:${minuteText}` : null;
  if (zone) {
    let offset = 0;
    if (zone !== "Z") {
      const hours = Number(zone.slice(1, 3));
      const minutes = Number(zone.slice(4));
      if (hours > 14 || minutes > 59 || (hours === 14 && minutes !== 0)) return null;
      offset = (zone[0] === "+" ? 1 : -1) * (hours * 60 + minutes) * 60000;
    }
    const local = new Date(civil.getTime() - offset + MANILA_OFFSET_MS);
    date = local.toISOString().slice(0, 10);
    clock = `${String(local.getUTCHours()).padStart(2, "0")}:${String(local.getUTCMinutes()).padStart(2, "0")}`;
  }
  return { date, clock, dateTime: `${date}T${clock || "00:00"}:00+08:00`, sortKey: `${date}T${clock || "00:00"}:${String(second).padStart(2, "0")}` };
}

export async function loadLatestAssignments(fetchPage, { isCurrent = () => true, onProgress = () => {}, limit = 200 } = {}) {
  const unique = new Map();
  let expected = null;
  for (let page = 1; expected === null || page <= expected.pages; page += 1) {
    if (!isCurrent()) return null;
    let response;
    try {
      response = await fetchPage({ page, limit });
    } catch (error) {
      throw new Error(`Could not load inspection page ${page}${expected ? ` of ${expected.pages}` : ""}. ${error.message || "Try again."}`, { cause: error });
    }
    if (!isCurrent()) return null;
    if (!Array.isArray(response?.data) || response.page !== page || response.per_page !== limit
      || !Number.isSafeInteger(response.total) || response.total < 0
      || !Number.isSafeInteger(response.pages) || response.pages !== Math.max(1, Math.ceil(response.total / limit))) {
      throw new Error(`Incomplete pagination: invalid metadata on page ${page}. Deadline counts are unavailable.`);
    }
    if (!expected) expected = { total: response.total, pages: response.pages };
    if (response.total !== expected.total || response.pages !== expected.pages) {
      throw new Error("Inspection pagination changed during loading. Deadline counts are unavailable; refresh to try again.");
    }
    const expectedLength = Math.min(limit, Math.max(0, expected.total - (page - 1) * limit));
    if (response.data.length !== expectedLength) {
      throw new Error(`Incomplete pagination: page ${page} returned an unexpected number of rows. Deadline counts are unavailable.`);
    }
    for (const report of response.data) {
      const id = Number(report?.reportID);
      if (!Number.isSafeInteger(id) || id <= 0) throw new Error("Inspection response contains an invalid report identity. Deadline counts are unavailable.");
      if (!unique.has(id)) unique.set(id, report);
    }
    onProgress({ page, pages: expected.pages, loaded: unique.size, total: expected.total });
  }
  if (unique.size !== expected.total) {
    throw new Error(`Incomplete pagination: ${unique.size} unique rows received of ${expected.total} expected. Deadline counts are unavailable.`);
  }
  return [...unique.values()];
}

export function deadlineGroups(reports) {
  const days = new Map();
  let excluded = 0;
  const seen = new Set();
  for (const report of reports) {
    const id = Number(report.reportID);
    if (seen.has(id)) continue;
    seen.add(id);
    const deadline = recordedDeadline(report.deadline);
    if (!deadline) { excluded += 1; continue; }
    if (!days.has(deadline.date)) days.set(deadline.date, []);
    days.get(deadline.date).push({ ...report, recordedDeadline: deadline });
  }
  for (const rows of days.values()) rows.sort((a, b) => a.recordedDeadline.sortKey.localeCompare(b.recordedDeadline.sortKey) || Number(a.reportID) - Number(b.reportID));
  return { days, excluded };
}

export function deadlineStatusCounts(rows) {
  const counts = { pending: 0, submitted: 0, verified: 0, other: 0 };
  for (const row of rows) {
    if (["Assigned", "Reassigned"].includes(row.verificationStatus)) counts.pending += 1;
    else if (row.verificationStatus === "Submitted") counts.submitted += 1;
    else if (row.verificationStatus === "Verified") counts.verified += 1;
    else counts.other += 1;
  }
  return counts;
}
