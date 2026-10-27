// Presentation only: all KPI values, OPS categories and populations come from
// the existing responses. No business measure is calculated here.
const numberFormat = new Intl.NumberFormat("en-PH", { maximumFractionDigits: 1 });
const manilaHourFormat = new Intl.DateTimeFormat("en-US", {
  timeZone: "Asia/Manila", hour: "numeric", hour12: false,
});

export function availableNumber(value) {
  if (typeof value !== "number" && typeof value !== "string") return null;
  if (typeof value === "string" && !value.trim()) return null;
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

export function formatOverviewNumber(value, suffix = "") {
  const number = availableNumber(value);
  return number === null ? "—" : `${numberFormat.format(number)}${suffix}`;
}

export function manilaGreeting(now = new Date()) {
  const hour = Number(manilaHourFormat.format(now)) % 24;
  return hour < 12 ? "Good morning" : hour < 18 ? "Good afternoon" : "Good evening";
}

const updatedAtFormat = new Intl.DateTimeFormat("en-US", {
  timeZone: "Asia/Manila", month: "short", day: "numeric",
  hour: "numeric", minute: "2-digit", hour12: true,
});

export function formatOverviewUpdatedAt(value) {
  // The workload API supplies an ISO UTC instant; reject timezone-less values.
  if (typeof value !== "string" || !/(Z|[+-]\d{2}:?\d{2})$/i.test(value)) return null;
  const timestamp = Date.parse(value);
  return Number.isFinite(timestamp) ? `Updated ${updatedAtFormat.format(timestamp)}` : null;
}

// WMO codes supplied by the existing Open-Meteo integration.
const WEATHER_CODES = {
  0: ["Clear sky", "sun"],
  1: ["Mostly clear", "partly-cloudy"],
  2: ["Partly cloudy", "partly-cloudy"],
  3: ["Overcast", "cloud"],
  45: ["Fog", "fog"], 48: ["Rime fog", "fog"],
  51: ["Light drizzle", "rain"], 53: ["Drizzle", "rain"], 55: ["Heavy drizzle", "rain"],
  56: ["Light freezing drizzle", "rain"], 57: ["Heavy freezing drizzle", "rain"],
  61: ["Light rain", "rain"], 63: ["Rain", "rain"], 65: ["Heavy rain", "rain"],
  66: ["Light freezing rain", "rain"], 67: ["Heavy freezing rain", "rain"],
  71: ["Light snow", "snow"], 73: ["Snow", "snow"], 75: ["Heavy snow", "snow"],
  77: ["Snow grains", "snow"],
  80: ["Light showers", "rain"], 81: ["Showers", "rain"], 82: ["Heavy showers", "rain"],
  85: ["Light snow showers", "snow"], 86: ["Heavy snow showers", "snow"],
  95: ["Thunderstorm", "thunderstorm"],
  96: ["Thunderstorm with light hail", "thunderstorm"],
  99: ["Thunderstorm with heavy hail", "thunderstorm"],
};

function observationTime(time, offsetSeconds) {
  if (typeof time !== "string" || !time.trim()) return null;
  let timestamp;
  if (/(Z|[+-]\d{2}:?\d{2})$/i.test(time)) {
    timestamp = Date.parse(time);
  } else {
    const offset = availableNumber(offsetSeconds);
    // A timezone-less observation is only interpretable with its response offset.
    if (offset === null) return null;
    timestamp = Date.parse(`${time}Z`) - offset * 1000;
  }
  if (!Number.isFinite(timestamp)) return null;
  return new Intl.DateTimeFormat("en-PH", {
    timeZone: "Asia/Manila", month: "short", day: "numeric",
    hour: "numeric", minute: "2-digit", hour12: true,
  }).format(new Date(timestamp));
}

export function weatherPresentation(data) {
  const current = data?.current;
  if (!current || typeof current !== "object" || Array.isArray(current)) return null;
  const temperature = availableNumber(current.temperature_2m);
  const code = availableNumber(current.weather_code);
  const conditions = code === null ? null : WEATHER_CODES[code];
  return {
    temperature: temperature === null ? "—" : `${Math.round(temperature)}°C`,
    description: conditions?.[0] ?? (code === null ? "Conditions unavailable" : "Unknown weather code"),
    icon: conditions?.[1] ?? "unknown",
    observation: observationTime(current.time, data.utc_offset_seconds),
    partial: temperature === null || !conditions,
  };
}

export function dateQuery(date) {
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
}

export function deadlinePresentation(inspections, month, selectedDay, now = new Date()) {
  const outstanding = (Array.isArray(inspections) ? inspections : []).filter(task =>
    task && (task.verificationStatus === "Assigned" || task.verificationStatus === "Reassigned") &&
    task.deadline && Number.isFinite(new Date(task.deadline).getTime()),
  );
  const tasksByDate = {};
  const statusByDate = {};
  for (const task of outstanding) {
    const deadline = new Date(task.deadline);
    if (deadline.getFullYear() !== month.getFullYear() || deadline.getMonth() !== month.getMonth()) continue;
    const day = deadline.getDate();
    (tasksByDate[day] ??= []).push(task);
    if (statusByDate[day] !== "overdue") {
      statusByDate[day] = deadline < now ? "overdue" : "upcoming";
    }
  }
  // A selected date with no deadlines must stay empty, rather than showing the
  // unrelated earliest three assignments. Sort copies, not response arrays.
  const displayedTasks = selectedDay !== null
    ? [...(tasksByDate[selectedDay] ?? [])].sort((a, b) => new Date(a.deadline) - new Date(b.deadline))
    : [...outstanding].sort((a, b) => new Date(a.deadline) - new Date(b.deadline)).slice(0, 3);
  return { outstanding, tasksByDate, statusByDate, displayedTasks };
}
