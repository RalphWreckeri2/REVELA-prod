import { useEffect, useLayoutEffect, useRef, useState } from "react";

const MAP_WIDTH = 4096;
const MAP_HEIGHT = 2301;
const TIP_LEAD_RATIO = 0.4;

/**
 * The prominent north–south road through Mataasnakahoy, traced in the
 * background image's native 4096 × 2301 pixel coordinates.
 */
const ROAD_POINTS = [
  [2954, 0], [2955, 200], [2952, 300], [2939, 400],
  [2911, 500], [2875, 600], [2844, 700], [2820, 800],
  [2799, 900], [2777, 1000], [2755, 1100], [2732, 1200],
  [2702, 1300], [2662, 1400], [2615, 1500], [2563, 1600],
  [2510, 1700], [2464, 1800], [2415, 1900], [2367, 2000],
  [2336, 2100], [2320, 2200], [2316, 2301],
];

const clamp01 = (value) => Math.min(1, Math.max(0, value));
const format = (value) => (Number.isFinite(value) ? value.toFixed(2) : "0");
const pointString = ([x, y]) => `${format(x)} ${format(y)}`;

function rectInContent(element, contentRect) {
  const rect = element.getBoundingClientRect();
  return {
    top: rect.top - contentRect.top,
    left: rect.left - contentRect.left,
    width: rect.width,
    height: rect.height,
    right: rect.right - contentRect.left,
  };
}

function buildRoute({ content, hero, about, features, contact, footer, header }) {
  const contentRect = content.getBoundingClientRect();
  const width = content.clientWidth;
  const height = Math.max(content.clientHeight, content.scrollHeight);
  if (!width || !height) return null;

  const heroRect = rectInContent(hero, contentRect);
  const mapPosition = parseFloat(
    window.getComputedStyle(hero).getPropertyValue("--landing-map-position"),
  ) / 100;
  const horizontalPosition = Number.isFinite(mapPosition) ? mapPosition : 0.5;
  const scale = Math.max(heroRect.width / MAP_WIDTH, heroRect.height / MAP_HEIGHT);
  const renderedWidth = MAP_WIDTH * scale;
  const renderedHeight = MAP_HEIGHT * scale;
  const frameLeft = heroRect.left + (heroRect.width - renderedWidth) * horizontalPosition;
  const frameTop = heroRect.top + (heroRect.height - renderedHeight) * 0.5;
  const heroBottom = heroRect.top + heroRect.height;

  // Transform the traced road into page coordinates and clip it at the bottom
  // of the hero. The continuation starts from that exact intersection.
  const transformed = ROAD_POINTS.map(([x, y]) => [
    frameLeft + x * scale,
    frameTop + y * scale,
  ]);
  const heroPoints = [];
  let join = null;
  let tangent = { x: 0, y: 1 };

  for (let index = 0; index < transformed.length; index += 1) {
    const point = transformed[index];
    if (!heroPoints.length) {
      if (point[1] <= heroBottom) {
        heroPoints.push(point);
        continue;
      }
      join = point;
      break;
    }

    const previous = heroPoints[heroPoints.length - 1];
    if (point[1] <= heroBottom) {
      heroPoints.push(point);
      continue;
    }

    const deltaY = point[1] - previous[1];
    const ratio = deltaY ? (heroBottom - previous[1]) / deltaY : 0;
    const intersection = [
      previous[0] + (point[0] - previous[0]) * ratio,
      heroBottom,
    ];
    heroPoints.push(intersection);
    join = intersection;

    const deltaX = point[0] - previous[0];
    const length = Math.hypot(deltaX, deltaY) || 1;
    tangent = { x: deltaX / length, y: deltaY / length };
    break;
  }

  if (!join) {
    join = heroPoints[heroPoints.length - 1] ?? [frameLeft, heroBottom];
    const previous = heroPoints[heroPoints.length - 2] ?? [join[0], join[1] - 1];
    const deltaX = join[0] - previous[0];
    const deltaY = join[1] - previous[1];
    const length = Math.hypot(deltaX, deltaY) || 1;
    tangent = { x: deltaX / length, y: deltaY / length };
  }

  const heroPath = heroPoints.length
    ? `M ${pointString(heroPoints[0])}${heroPoints.slice(1).map((point) => ` L ${pointString(point)}`).join("")}`
    : `M ${pointString(join)}`;

  const aboutRect = rectInContent(about, contentRect);
  const featuresRect = rectInContent(features, contentRect);
  const contactRect = rectInContent(contact, contentRect);
  const footerRect = footer ? rectInContent(footer, contentRect) : null;
  const aboutContentRect = about.querySelector(".landing-section-inner")
    ? rectInContent(about.querySelector(".landing-section-inner"), contentRect)
    : null;

  const sectionInners = [about, features, contact]
    .map((section) => section.querySelector(".landing-section-inner"))
    .filter(Boolean)
    .map((element) => element.getBoundingClientRect());
  const contentLeft = sectionInners.length
    ? Math.min(...sectionInners.map((rect) => rect.left - contentRect.left))
    : 20;
  const contentRight = sectionInners.length
    ? Math.max(...sectionInners.map((rect) => rect.right - contentRect.left))
    : width - 20;
  const headerRect = header ? rectInContent(header, contentRect) : null;

  // Prefer the right-hand whitespace: at least 10px clear of section content,
  // at least 8px inside the viewport edge, and outside the fixed navbar.
  const rightCorridor = Math.min(
    width - 8,
    contentRight + Math.max(12, (width - contentRight) * 0.35),
  );
  const rightClear = !headerRect
    || rightCorridor - 2.5 > headerRect.right
    || rightCorridor + 2.5 < headerRect.left;

  // On narrow screens the mobile navbar spans almost the full width in both
  // its expanded and compact states. Use the narrow left edge instead so the
  // route never runs behind the navbar and does not switch sides on scroll.
  const leftBoundary = Math.min(headerRect?.left ?? contentLeft, contentLeft);
  const leftCorridor = Math.max(6, leftBoundary - 14);
  const leftClear = Boolean(headerRect) && leftCorridor + 2.5 < leftBoundary;
  const useLeftCorridor = leftClear && (window.innerWidth <= 640 || !rightClear);

  const safeLeft = contentRight + 10;
  const safeRight = Math.max(safeLeft, width - 8);
  const corridorX = useLeftCorridor ? leftCorridor : rightCorridor;
  const amplitude = useLeftCorridor
    ? 0
    : Math.min(18, Math.max(0, (safeRight - safeLeft) / 2 - 3));

  const aboutJoinY = Math.max(
    join[1] + 80,
    Math.min(
      aboutRect.top + aboutRect.height * 0.28,
      (aboutContentRect?.top ?? aboutRect.top + aboutRect.height * 0.5) - 24,
    ),
  );
  const endY = Math.max(
    contactRect.top + 40,
    Math.min(
      contactRect.top + contactRect.height - 24,
      (footerRect?.top ?? contactRect.top + contactRect.height - 69) - 28,
    ),
  );

  // Leave the road along its own tangent, then ease into the safe corridor.
  // The end tangent is vertical so the section S-curves start clean.
  const joinControl1 = [
    join[0] + tangent.x * 90,
    join[1] + tangent.y * 90,
  ];
  const joinControl2 = [
    corridorX,
    join[1] + (aboutJoinY - join[1]) * 0.65,
  ];
  let path = `${heroPath} C ${pointString(joinControl1)} ${pointString(joinControl2)} ${pointString([corridorX, aboutJoinY])}`;

  // Each section gets a gentle S-curve. Both ends are vertical and both
  // control points stay between the corridor edges, so the route cannot
  // overshoot into content or off the viewport edge.
  const appendBulge = (startY, finishY, bulge) => {
    const middleY = startY + (finishY - startY) * 0.52;
    const middleX = corridorX + bulge;
    const firstRise = (middleY - startY) * 0.38;
    const secondRise = (finishY - middleY) * 0.38;
    path += ` C ${pointString([corridorX, startY + firstRise])} ${pointString([middleX, middleY - firstRise])} ${pointString([middleX, middleY])}`;
    path += ` C ${pointString([middleX, middleY + secondRise])} ${pointString([corridorX, finishY - secondRise])} ${pointString([corridorX, finishY])}`;
  };

  appendBulge(aboutJoinY, aboutRect.top + aboutRect.height, amplitude);
  appendBulge(featuresRect.top, featuresRect.top + featuresRect.height, -amplitude);
  appendBulge(contactRect.top, endY, amplitude);

  return { width, height, path };
}

export default function LandingRoadHighlight() {
  const hostRef = useRef(null);
  const pathRef = useRef(null);
  const updateProgressRef = useRef(null);
  const [route, setRoute] = useState(null);

  useLayoutEffect(() => {
    const host = hostRef.current;
    const content = host?.closest(".landing-page-content");
    const hero = content?.querySelector(".landing-hero");
    const about = content?.querySelector("#about");
    const features = content?.querySelector("#features");
    const contact = content?.querySelector("#contact");
    const footer = contact?.querySelector(".landing-footer");
    const header = document.querySelector(".landing-header-inner");
    if (!content || !hero || !about || !features || !contact) return undefined;

    const measure = () => {
      const next = buildRoute({ content, hero, about, features, contact, footer, header });
      if (!next) return;
      setRoute((previous) => (
        previous
        && previous.path === next.path
        && previous.width === next.width
        && previous.height === next.height
          ? previous
          : next
      ));
      window.requestAnimationFrame(() => updateProgressRef.current?.());
    };

    measure();

    const observer = typeof ResizeObserver === "function"
      ? new ResizeObserver(measure)
      : null;
    observer?.observe(content);
    observer?.observe(hero);
    observer?.observe(about);
    observer?.observe(features);
    observer?.observe(contact);
    if (header) observer?.observe(header);
    window.addEventListener("resize", measure);
    document.fonts?.ready?.then(measure).catch(() => {});

    return () => {
      observer?.disconnect();
      window.removeEventListener("resize", measure);
    };
  }, []);

  useEffect(() => {
    const host = hostRef.current;
    const scroller = host?.closest(".landing-page");
    const path = pathRef.current;
    if (!scroller || !path) return undefined;

    const motion = window.matchMedia?.("(prefers-reduced-motion: reduce)");
    let animationFrame = 0;

    const update = () => {
      animationFrame = 0;
      if (motion?.matches) {
        path.style.strokeDashoffset = "0";
        return;
      }

      const viewportHeight = scroller.clientHeight;
      const maxScroll = Math.max(1, scroller.scrollHeight - viewportHeight);
      const lead = Math.min(scroller.scrollTop, viewportHeight * TIP_LEAD_RATIO);
      const progress = clamp01(
        (scroller.scrollTop + lead) / (maxScroll + viewportHeight * TIP_LEAD_RATIO),
      );
      path.style.strokeDashoffset = String(1 - progress);
    };

    const schedule = () => {
      if (animationFrame) return;
      animationFrame = window.requestAnimationFrame(update);
    };

    updateProgressRef.current = schedule;
    update();

    scroller.addEventListener("scroll", schedule, { passive: true });
    window.addEventListener("resize", schedule);
    motion?.addEventListener?.("change", update);

    return () => {
      scroller.removeEventListener("scroll", schedule);
      window.removeEventListener("resize", schedule);
      motion?.removeEventListener?.("change", update);
      if (animationFrame) window.cancelAnimationFrame(animationFrame);
      if (updateProgressRef.current === schedule) updateProgressRef.current = null;
    };
  }, []);

  return (
    <div ref={hostRef} className="landing-road-highlight" aria-hidden="true">
      <svg
        viewBox={route ? `0 0 ${route.width} ${route.height}` : undefined}
        preserveAspectRatio="none"
        focusable="false"
        style={route ? undefined : { visibility: "hidden" }}
      >
        <path
          ref={pathRef}
          d={route?.path ?? ""}
          pathLength="1"
          className="landing-road-highlight__stroke"
        />
      </svg>
    </div>
  );
}
