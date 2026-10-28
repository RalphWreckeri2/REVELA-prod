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
