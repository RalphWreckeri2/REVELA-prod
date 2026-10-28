function localDateString(date) {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function laterDate(first, second) {
  if (!first) return second;
  if (!second) return first;
  return first > second ? first : second;
}

function earlierDate(first, second) {
  if (!first) return second;
  if (!second) return first;
  return first < second ? first : second;
}

export function buildBarangayOverviewFilters(filters, preset, now = new Date()) {
  const result = { ...filters };
  if (preset === "all") return result;

  const end = localDateString(now);
  const start = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  if (preset === "year") {
    start.setMonth(0, 1);
  } else {
    const days = preset === "7days" ? 6 : 29;
    start.setDate(start.getDate() - days);
  }
  const from = localDateString(start);
  result.detected_from = laterDate(filters.detected_from, from);
  result.detected_to = earlierDate(filters.detected_to, end);
  result.inspection_from = laterDate(filters.inspection_from, from);
  result.inspection_to = earlierDate(filters.inspection_to, end);
  return result;
}

export function visibleRegistryDimensions(registry = {}) {
  return [
    { key: "business_size", label: "By size" },
    { key: "business_type", label: "By business type" },
    { key: "registration_type", label: "By registration type" },
    { key: "line_of_business", label: "By line of business" },
  ].filter(({ key }) => {
    const values = registry[key] || [];
    return new Set(values.map((item) => item.value)).size > 1;
  });
}

export function quantileBreaks(values, classCount = 5) {
  const sorted = values
    .map(Number)
    .filter((value) => Number.isFinite(value) && value > 0)
    .sort((first, second) => first - second);
  if (!sorted.length || classCount < 1) return [];

  return Array.from({ length: classCount - 1 }, (_, index) => {
    const position = ((index + 1) * (sorted.length - 1)) / classCount;
    const lowerIndex = Math.floor(position);
    const fraction = position - lowerIndex;
    const upperIndex = Math.min(lowerIndex + 1, sorted.length - 1);
    return sorted[lowerIndex] + (sorted[upperIndex] - sorted[lowerIndex]) * fraction;
  });
}

export function quantileClass(value, breaks) {
  const count = Number(value);
  if (!Number.isFinite(count) || count <= 0) return -1;
  const index = breaks.findIndex((boundary) => count <= boundary);
  return index === -1 ? breaks.length : index;
}

export function quantileRangeLabels(breaks) {
  const format = (value) => Number.isInteger(value)
    ? value.toLocaleString()
    : value.toLocaleString(undefined, { maximumFractionDigits: 1 });
  return breaks.map((boundary, index) => (
    index === 0
      ? `1–${format(boundary)}`
      : `>${format(breaks[index - 1])}–${format(boundary)}`
  )).concat(breaks.length ? `>${format(breaks[breaks.length - 1])}` : []);
}
