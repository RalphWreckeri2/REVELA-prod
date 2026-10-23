// North–south road traced in the shared 4096 × 2301 map assets. The landing
// hero and public sign-in backdrop use these same coordinates.
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
