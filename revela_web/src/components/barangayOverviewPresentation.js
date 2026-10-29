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

export function sortRegistryBreakdownRows(dimension, rows = []) {
  const sizeOrder = new Map([
    ["micro", 0],
    ["small", 1],
    ["medium", 2],
    ["large", 3],
  ]);
  return [...rows].sort((first, second) => {
    const firstValue = String(first.value ?? first.label ?? "");
    const secondValue = String(second.value ?? second.label ?? "");
    const firstNormalized = firstValue.trim().toLowerCase();
    const secondNormalized = secondValue.trim().toLowerCase();
    const firstIsOthers = firstNormalized === "others";
    const secondIsOthers = secondNormalized === "others";
    if (firstIsOthers !== secondIsOthers) return firstIsOthers ? 1 : -1;

    if (dimension === "business_size") {
      const firstRank = sizeOrder.get(firstNormalized) ?? Number.MAX_SAFE_INTEGER;
      const secondRank = sizeOrder.get(secondNormalized) ?? Number.MAX_SAFE_INTEGER;
      if (firstRank !== secondRank) return firstRank - secondRank;
    }

    const countDifference = Number(second.count || 0) - Number(first.count || 0);
    if (countDifference) return countDifference;
    return firstValue.localeCompare(secondValue);
  });
}

export function quantileBreaks(values, classCount = 5) {
  const sorted = values
    .map(Number)
    .filter((value) => Number.isFinite(value) && value > 0)
    .sort((first, second) => first - second);
  const roundedUnique = [...new Set(sorted.map(Math.round))];
  if (!roundedUnique.length || classCount < 1) return [];
  if (roundedUnique.length <= classCount) return roundedUnique;

  const breaks = Array.from({ length: classCount - 1 }, (_, index) => {
    const position = ((index + 1) * (sorted.length - 1)) / classCount;
    const lowerIndex = Math.floor(position);
    const fraction = position - lowerIndex;
    const upperIndex = Math.min(lowerIndex + 1, sorted.length - 1);
    return Math.round(sorted[lowerIndex]
      + (sorted[upperIndex] - sorted[lowerIndex]) * fraction);
  });
  return [...new Set([...breaks, roundedUnique[roundedUnique.length - 1]])];
}

export function quantileClass(value, breaks) {
  const count = Number(value);
  if (!Number.isFinite(count) || count <= 0) return -1;
  const index = breaks.findIndex((boundary) => count <= boundary);
  return index === -1 ? breaks.length : index;
}

export function quantileRangeLabels(breaks, values = []) {
  const distinctCount = new Set(values
    .map(Number)
    .filter((value) => Number.isFinite(value) && value > 0)
    .map(Math.round)).size;
  const format = (value) => Math.round(value).toLocaleString();
  if (distinctCount > 0 && distinctCount <= 5) {
    return breaks.map(format);
  }
  return breaks.map((boundary, index) => (
    index === 0
      ? `1–${format(boundary)}`
      : `>${format(breaks[index - 1])}–${format(boundary)}`
  ));
}

export function getNotInRegistryPinTotal(pins = {}) {
  return Number(pins.detected_not_in_registry || 0)
    + Number(pins.added_by_inspector || 0);
}

export function getBarangayTopTotals(data = {}) {
  return {
    registered: Number(data.registry_total || 0),
    notInRegistry: getNotInRegistryPinTotal(data.pins),
    beingInspected: Number(data.inspections?.pending || 0)
      + Number(data.inspections?.waiting_for_review || 0),
  };
}

export function getMapPinBuckets(pins = {}) {
  return [
    {
      key: "registered_on_map",
      label: "Registered on map",
      count: Number(pins.registered_on_map || 0)
        + Number(pins.detection_with_business_id || 0),
    },
    {
      key: "detected_not_in_registry",
      label: "Detected, not in registry",
      count: Number(pins.detected_not_in_registry || 0),
    },
    {
      key: "added_by_inspector",
      label: "Added by inspector",
      count: Number(pins.added_by_inspector || 0),
    },
    {
      key: "other_source",
      label: "Other pins",
      count: Number(pins.other_source || 0),
    },
  ];
}

const CATEGORY_PALETTE = [
  "#2563eb",
  "#0f9f8f",
  "#7c3aed",
  "#f59e0b",
  "#e11d48",
  "#64748b",
  "#0891b2",
  "#65a30d",
];

const BUSINESS_SIZE_COLORS = Object.freeze({
  micro: "#2563eb",
  small: "#0f9f8f",
  medium: "#7c3aed",
  large: "#f59e0b",
});

// Stable colors for the registry's named dimensions. Hashing into the small
// fallback palette makes New/Renewal and Sole Proprietorship/Cooperative collide.
const REGISTRATION_TYPE_COLORS = Object.freeze({
  new: "#2563eb",
  renewal: "#0f9f8f",
});

const BUSINESS_TYPE_COLORS = Object.freeze({
  "sole proprietorship": "#7c3aed",
  corporation: "#2563eb",
  partnership: "#f59e0b",
  cooperative: "#0f9f8f",
  "one person corporation": "#e11d48",
});

export const DISPLAY_SECTOR_COLORS = Object.freeze({
  retail: "#8b5cf6",
  wholesale_vehicles: "#be123c",
  food_drink: "#a16207",
  real_estate: "#0891b2",
  manufacturing: "#7f1d1d",
  agriculture_mining: "#6b21a8",
  construction_utilities: "#c026d3",
  transport_storage: "#0f766e",
  finance_professional: "#a21caf",
  information_communication: "#854d0e",
  hospitality_arts_recreation: "#e11d48",
  education_health_other_services: "#475569",
  unmapped: "#6b7280",
});

export function registryCategoryColor(dimension, value) {
  const normalizedValue = String(value ?? "Unknown").trim().toLowerCase();
  if (dimension === "display_sector" && DISPLAY_SECTOR_COLORS[normalizedValue]) {
    return DISPLAY_SECTOR_COLORS[normalizedValue];
  }
  if (dimension === "business_size" && BUSINESS_SIZE_COLORS[normalizedValue]) {
    return BUSINESS_SIZE_COLORS[normalizedValue];
  }
  if (dimension === "registration_type" && REGISTRATION_TYPE_COLORS[normalizedValue]) {
    return REGISTRATION_TYPE_COLORS[normalizedValue];
  }
  if (dimension === "business_type" && BUSINESS_TYPE_COLORS[normalizedValue]) {
    return BUSINESS_TYPE_COLORS[normalizedValue];
  }
  const colorKey = `${dimension}:${normalizedValue}`;
  let hash = 0;
  for (let index = 0; index < colorKey.length; index += 1) {
    hash = (hash * 31 + colorKey.charCodeAt(index)) >>> 0;
  }
  return CATEGORY_PALETTE[hash % CATEGORY_PALETTE.length];
}

/** Resolve palette collisions within a breakdown without changing its data or order. */
export function registryCategoryColorsForRows(dimension, rows) {
  const values = [...new Set(rows.map(row => String(row.value ?? "Unknown")))].sort();
  const fixed = dimension === "business_size" ? BUSINESS_SIZE_COLORS
    : dimension === "business_type" ? BUSINESS_TYPE_COLORS
      : dimension === "registration_type" ? REGISTRATION_TYPE_COLORS
        : dimension === "display_sector" ? DISPLAY_SECTOR_COLORS : {};
  const assigned = new Map();
  const used = new Set();
  values.forEach(value => {
    const color = fixed[value.trim().toLowerCase()];
    if (color) { assigned.set(value, color); used.add(color); }
  });
  values.forEach(value => {
    if (assigned.has(value)) return;
    let color = registryCategoryColor(dimension, value);
    if (used.has(color)) color = CATEGORY_PALETTE.find(candidate => !used.has(candidate));
    let hue = 0;
    while (!color || used.has(color)) {
      color = `hsl(${Math.round((hue++ * 137.5) % 360)} 70% 55%)`;
    }
    assigned.set(value, color);
    used.add(color);
  });
  return assigned;
}
