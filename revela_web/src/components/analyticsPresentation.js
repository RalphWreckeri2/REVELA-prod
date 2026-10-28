const DAY_MS = 24 * 60 * 60 * 1000;

function parseDate(value) {
  if (!value) return null;
  const match = String(value).match(/^(\d{4})-(\d{2})-(\d{2})/);
  if (!match) return null;
  const date = new Date(Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3])));
  return Number.isNaN(date.getTime()) ? null : date;
}

function formatDate(date) {
  return date.toISOString().slice(0, 10);
}

function mondayOf(date) {
  const monday = new Date(date);
  monday.setUTCDate(monday.getUTCDate() - ((monday.getUTCDay() + 6) % 7));
  return monday;
}

export function groupInspectionStatuses(rows = []) {
  return rows.map(row => {
    const pending = ["assigned", "reassigned", "in_progress", "unassigned"]
      .reduce((sum, key) => sum + Number(row[key] || 0), 0);
    const awaitingReview = Number(row.submitted || 0);
    const verified = Number(row.verified || 0);
    return {
      ...row,
      pending,
      awaiting_review: awaitingReview,
      verified,
      total: pending + awaitingReview + verified,
    };
  }).filter(row => row.total > 0);
}

export function pivotCategoryCounts(rows = [], labelKey, countKey = "count") {
  const byCategory = new Map();
  for (const row of rows) {
    const label = String(row[labelKey] ?? "Unknown").trim() || "Unknown";
    const current = byCategory.get(row.barangayName) || { barangayName: row.barangayName };
    current[label] = Number(current[label] || 0) + Number(row[countKey] || 0);
    byCategory.set(row.barangayName, current);
  }
  return [...byCategory.values()];
}

export function completeInspectionTimeline(rows = [], fromDate, toDate) {
  const entries = new Map();
  for (const row of rows) {
    const date = parseDate(row.date);
    if (!date) continue;
    const key = formatDate(date);
    const current = entries.get(key) || { submitted: 0, verified: 0 };
    current.submitted += Number(row.submitted || 0);
    current.verified += Number(row.verified || 0);
    entries.set(key, current);
  }
  const actualDates = [...entries.keys()].map(parseDate);
  const start = parseDate(fromDate) || (actualDates.length
    ? new Date(Math.min(...actualDates.map(date => date.getTime())))
    : null);
  const end = parseDate(toDate) || (actualDates.length
    ? new Date(Math.max(...actualDates.map(date => date.getTime())))
    : null);
  if (!start || !end || start > end) return { interval: "day", rows: [] };

  const dayCount = Math.floor((end - start) / DAY_MS) + 1;
  if (dayCount <= 31) {
    const result = [];
    for (let date = start; date <= end; date = new Date(date.getTime() + DAY_MS)) {
      const key = formatDate(date);
      result.push({ date: key, ...entries.get(key) ?? { submitted: 0, verified: 0 } });
    }
    return { interval: "day", rows: result };
  }

  const firstWeek = mondayOf(start);
  const lastWeek = mondayOf(end);
  const result = [];
  for (let week = firstWeek; week <= lastWeek; week = new Date(week.getTime() + 7 * DAY_MS)) {
    const weekKey = formatDate(week);
    result.push({ date: weekKey, submitted: 0, verified: 0 });
  }
  const weeklyRows = new Map(result.map(row => [row.date, row]));
  for (const [key, counts] of entries) {
    const weekKey = formatDate(mondayOf(parseDate(key)));
    const week = weeklyRows.get(weekKey);
    if (week) {
      week.submitted += counts.submitted;
      week.verified += counts.verified;
    }
  }
  return { interval: "week", rows: result };
}
