export function formatBarangayMapPopupCount(count, countLabel) {
  const numericCount = count == null || count === "" ? NaN : Number(count);
  const formattedCount = Number.isFinite(numericCount)
    ? numericCount.toLocaleString()
    : "Unavailable";
  return `${formattedCount} ${countLabel}`;
}

export function createBarangayMapPopup({
  name,
  count,
  countLabel,
  details = [],
}) {
  const content = document.createElement("div");
  content.className = "revela-map-popup";

  const title = document.createElement("strong");
  title.className = "revela-map-popup__title";
  title.textContent = name || "Barangay";

  const metric = document.createElement("span");
  metric.className = "revela-map-popup__metric";
  metric.textContent = formatBarangayMapPopupCount(count, countLabel);

  content.append(title, metric);
  details.filter(Boolean).forEach((text) => {
    const detail = document.createElement("span");
    detail.className = "revela-map-popup__detail";
    detail.textContent = text;
    content.append(detail);
  });
  return content;
}
