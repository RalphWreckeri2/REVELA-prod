// The light map's north–south road in its native 4096 × 2301 coordinates.
// The dark asset has its own registration and trace below.
export const MAP_WIDTH = 4096;
export const MAP_HEIGHT = 2301;

export const ROAD_POINTS = [
  [2954, 0], [2955, 200], [2952, 300], [2939, 400],
  [2911, 500], [2875, 600], [2844, 700], [2820, 800],
  [2799, 900], [2777, 1000], [2755, 1100], [2732, 1200],
  [2702, 1300], [2662, 1400], [2615, 1500], [2563, 1600],
  [2510, 1700], [2464, 1800], [2415, 1900], [2367, 2000],
  [2336, 2100], [2320, 2200], [2316, 2301],
];

// The dark asset has the same 4096 × 2301 canvas but a different geographic
// registration (including black padding). These are centers sampled from its
// own bright north–south road, not offsets applied to the light road.
export const DARK_ROAD_POINTS = [
  [2733, 0], [2737, 100], [2737, 200], [2738, 300],
  [2739, 400], [2737, 500], [2722, 600], [2689, 700],
  [2656, 800], [2627, 900], [2611, 1000], [2589, 1100],
  [2566, 1200], [2533, 1300], [2487, 1400], [2437, 1500],
  [2388, 1600], [2338, 1700], [2290, 1800], [2261, 1900],
  [2252, 2000], [2247, 2100], [2248, 2200], [2256, 2301],
];

// The eastern road runs alongside the sign-in card rather than behind it.
// Sampled from the same map image at its visible intersections/turns.
const EAST_ROAD_POINTS = [
  [3152, 0], [3190, 150], [3215, 300], [3235, 450],
  [3240, 600], [3230, 750], [3205, 900], [3178, 1050],
  [3185, 1200], [3185, 1350], [3190, 1500], [3200, 1600],
  [3225, 1700], [3260, 1800], [3300, 1900], [3360, 2000],
  [3440, 2100], [3500, 2200], [3560, 2301],
];

// A slightly closer crop keeps the road outside the card. Use these exact
// numbers both for CSS background placement and SVG projection.
export function signInMapCrop(width, height) {
  const scale = Math.max(width / MAP_WIDTH, height / MAP_HEIGHT) * 1.1;
  const imageWidth = MAP_WIDTH * scale;
  const imageHeight = MAP_HEIGHT * scale;
  const cardRight = (width + Math.min(940, width * 0.92)) / 2;
  const narrow = width <= 1200;
  const openSpace = Math.min(65, Math.max(30, (width - 1180) * 0.25));
  const desiredRoadX = narrow ? width - 42 : Math.min(width - 40, cardRight + openSpace);
  const position = Math.min(1, Math.max(0, ((narrow ? 3380 : 3200) * scale - desiredRoadX) / (imageWidth - width)));
  return { scale, imageWidth, imageHeight, frameLeft: (width - imageWidth) * position, frameTop: (height - imageHeight) / 2, position };
}

export function roadAtViewportY(y, crop) {
  const { scale, frameLeft, frameTop } = crop;
  const mapY = (y - frameTop) / scale;
  if (mapY < 0 || mapY > MAP_HEIGHT) return null;
  const next = EAST_ROAD_POINTS.findIndex((point) => point[1] >= mapY);
  if (next <= 0) return next === 0 ? frameLeft + EAST_ROAD_POINTS[0][0] * scale : null;
  const [x1, y1] = EAST_ROAD_POINTS[next - 1];
  const [x2, y2] = EAST_ROAD_POINTS[next];
  return frameLeft + (x1 + (x2 - x1) * (mapY - y1) / (y2 - y1)) * scale;
}
