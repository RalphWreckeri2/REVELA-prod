export const APPROXIMATE_LOCATION_LABEL = "Approximate location: barangay center";

export function getApproximateMarkerSvg(color = "#64748b") {
  return `<svg xmlns="http://www.w3.org/2000/svg" width="30" height="38" viewBox="0 0 30 38">
    <path d="M15 2C8.37 2 3 7.37 3 14c0 8 12 22 12 22s12-14 12-22C27 7.37 21.63 2 15 2z" fill="${color}" fill-opacity="0.22" stroke="${color}" stroke-width="2" stroke-dasharray="3 2"/>
    <circle cx="24" cy="6" r="5" fill="${color}" stroke="#fff" stroke-width="1"/>
    <text x="24" y="9" text-anchor="middle" font-family="sans-serif" font-size="8" font-weight="700" fill="#fff">~</text>
  </svg>`;
}

export function createApproximateMarkerContent(
  width = 26,
  height = 34,
  isSelected = false,
  isAdjusting = false,
  markerColor = "#64748b",
) {
  const element = document.createElement("div");
  element.style.cssText = `
    width: ${width}px;
    height: ${height}px;
    cursor: ${isAdjusting ? "grab" : "pointer"};
    position: relative;
    user-select: none;
    touch-action: none;
  `;
  const color = isAdjusting ? "#2563eb" : markerColor;
  const svg = getApproximateMarkerSvg(color)
    .replace('width="30" height="38"', `width="${width}" height="${height}"`)
    .replace('stroke-width="2"', `stroke-width="${isSelected ? 3 : 2}"`);
  element.innerHTML = svg;
  element.title = APPROXIMATE_LOCATION_LABEL;
  element.setAttribute("aria-label", APPROXIMATE_LOCATION_LABEL);
  element.setAttribute("role", "img");
  return element;
}

export function createApproximateMarkerIcon(maps, scale = 1, markerColor = "#64748b") {
  return {
    url: `data:image/svg+xml;charset=UTF-8,${encodeURIComponent(getApproximateMarkerSvg(markerColor))}`,
    scaledSize: new maps.Size(30 * scale, 38 * scale),
    anchor: new maps.Point(15 * scale, 38 * scale),
  };
}
