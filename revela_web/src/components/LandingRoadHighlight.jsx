import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { MAP_WIDTH, MAP_HEIGHT, ROAD_POINTS, DARK_ROAD_POINTS } from "./landingMapRoad";
import { useTheme } from "../context/themeContext";
const TIP_LEAD_RATIO = 0.4;

const clamp01 = (value) => Math.min(1, Math.max(0, value));
const format = (value) => (Number.isFinite(value) ? value.toFixed(2) : "0");
const pointString = ([x, y]) => `${format(x)} ${format(y)}`;
const cubic = (a, b, c, d, t) => {
  const remaining = 1 - t;
  return remaining ** 3 * a + 3 * remaining ** 2 * t * b + 3 * remaining * t ** 2 * c + t ** 3 * d;
};

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

function buildRoute({ content, hero, about, features, contact, footer, roadPoints }) {
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
  const transformed = roadPoints.map(([x, y]) => [
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
  const mobile = width <= 640;
  const center = mobile ? 23 : width / 2;
  // Both desktop columns reserve a central track; on phones text begins 50px
  // in, leaving the narrow route lane to the left of the stacked content.
  const inner = features.querySelector(".landing-section-inner");
  const columnGap = inner ? parseFloat(window.getComputedStyle(inner).columnGap) : 130;
  const amplitude = mobile ? 7 : Math.min(34, Math.max(20, columnGap / 2 - 27));
  const x = (factor) => center + factor * amplitude;
  const endY = footerRect ? footerRect.top - 36 : contactRect.top + contactRect.height - 38;
  const cardRects = [...features.querySelectorAll(".landing-feature-card")]
    .map((card) => rectInContent(card, contentRect));
  const cardRows = [...new Set(cardRects.map((rect) => Math.round(rect.top)))].map((top) => {
    const row = cardRects.filter((rect) => Math.abs(rect.top - top) < 3);
    return { top, bottom: Math.max(...row.map((rect) => rect.top + rect.height)) };
  });

  const anchors = [
    [x(mobile ? 0 : 0.45), aboutRect.top + 110],
    [x(-0.82), aboutRect.top + aboutRect.height * 0.37],
    [x(0.93), aboutRect.top + aboutRect.height * 0.68],
    [x(-0.24), aboutRect.top + aboutRect.height - 38],
    [x(0.48), featuresRect.top + 50],
    [x(-0.7), featuresRect.top + Math.min(220, featuresRect.height * 0.23)],
    ...cardRows.map((row, index) => [x([0.82, -0.91, 0.56, -0.67, 0.72][index % 5]), (row.top + row.bottom) / 2]),
    [x(0.18), featuresRect.top + featuresRect.height - 38],
    [x(-0.4), contactRect.top + 50],
    [x(0.84), contactRect.top + contactRect.height * 0.34],
    [x(-0.68), contactRect.top + contactRect.height * 0.68],
    [x(0.2), endY],
  ].sort((a, b) => a[1] - b[1]);

  // Monotone-in-Y cubic spans with shared tangents create broad, unequal
  // bends. This avoids sharp joints and avoids a repeating sine-wave rhythm.
  const nodes = [join, ...anchors];
  const slope = (index) => {
    if (index === 0) return tangent.x / Math.max(0.2, tangent.y);
    const before = nodes[index - 1];
    const after = nodes[Math.min(nodes.length - 1, index + 1)];
    return Math.max(-0.27, Math.min(0.27, (after[0] - before[0]) / Math.max(1, after[1] - before[1])));
  };
  const spans = [];
  let path = heroPath;
  for (let index = 0; index < nodes.length - 1; index += 1) {
    const from = nodes[index];
    const to = nodes[index + 1];
    const rise = (to[1] - from[1]) * (index === 0 ? 0.3 : 0.34);
    const control1 = [from[0] + slope(index) * rise, from[1] + rise];
    const control2 = [to[0] - slope(index + 1) * rise, to[1] - rise];
    path += ` C ${pointString(control1)} ${pointString(control2)} ${pointString(to)}`;
    spans.push({ from, control1, control2, to });
  }

  const atY = (y) => {
    const span = spans.find(({ to }) => y <= to[1]) ?? spans.at(-1);
    if (!span) return center;
    let low = 0;
    let high = 1;
    for (let index = 0; index < 22; index += 1) {
      const middle = (low + high) / 2;
      if (cubic(span.from[1], span.control1[1], span.control2[1], span.to[1], middle) < y) low = middle;
      else high = middle;
    }
    return cubic(span.from[0], span.control1[0], span.control2[0], span.to[0], (low + high) / 2);
  };

  const featureJunctions = mobile
    ? [cardRows[1], cardRows[3]].filter(Boolean).map((row) => row.bottom + 13)
    : cardRows.slice(0, 3).map((row) => (row.top + row.bottom) / 2 + 18);
  const junctions = [
    [aboutRect.top + aboutRect.height * 0.3, 1, 0],
    ...(!mobile ? [[aboutRect.top + aboutRect.height * 0.57, -1, 1]] : []),
    [aboutRect.top + aboutRect.height * 0.76, 1, 2],
    ...featureJunctions.map((y, index) => [y, index % 2 ? 1 : -1, index + 3]),
    [contactRect.top + contactRect.height * 0.26, -1, 6],
    ...(!mobile ? [[contactRect.top + contactRect.height * 0.49, 1, 7]] : []),
    [contactRect.top + contactRect.height * 0.72, -1, 8],
  ];
  const branches = junctions.map(([y, side, index]) => {
    const startX = atY(y);
    const available = columnGap / 2 - 14 - Math.abs(startX - center);
    const length = mobile ? 7 + (index % 2) * 2 : Math.min(16 + (index * 7) % 15, Math.max(6, available));
    const turn = (index % 3 - 1) * (mobile ? 4 : 10);
    const end = [startX + side * length, y + turn];
    return {
      y,
      path: `M ${pointString([startX, y])} C ${pointString([startX + side * length * 0.3, y - 5])} ${pointString([startX + side * length * 0.72, y + turn * 0.72])} ${pointString(end)}`,
    };
  });

  return { width, height, path, branches, branchSignature: branches.map(({ path: d }) => d).join("|") };
}

export default function LandingRoadHighlight() {
  const { isDark } = useTheme();
  const hostRef = useRef(null);
  const pathRef = useRef(null);
  const glowRef = useRef(null);
  const tipRef = useRef(null);
  const updateProgressRef = useRef(null);
  const branchDistancesRef = useRef([]);
  const branchNodesRef = useRef([]);
  const [route, setRoute] = useState(null);

  useLayoutEffect(() => {
    const host = hostRef.current;
    const content = host?.closest(".landing-page-content");
    const hero = content?.querySelector(".landing-hero");
    const about = content?.querySelector("#about");
    const features = content?.querySelector("#features");
    const contact = content?.querySelector("#contact");
    const footer = contact?.querySelector(".landing-footer");
    if (!content || !hero || !about || !features || !contact) return undefined;

    const measure = () => {
      const next = buildRoute({ content, hero, about, features, contact, footer, roadPoints: isDark ? DARK_ROAD_POINTS : ROAD_POINTS });
      if (!next) return;
      setRoute((previous) => (
        previous
        && previous.path === next.path
        && previous.width === next.width
        && previous.height === next.height
        && previous.branchSignature === next.branchSignature
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
    if (footer) observer?.observe(footer);
    [about, features, contact].forEach((section) => {
      const inner = section.querySelector(".landing-section-inner");
      if (inner) observer?.observe(inner);
    });
    const featureGrid = features.querySelector(".landing-feature-grid");
    if (featureGrid) observer?.observe(featureGrid);
    features.querySelectorAll(".landing-feature-card").forEach((card) => observer?.observe(card));
    window.addEventListener("resize", measure);
    document.fonts?.ready?.then(measure).catch(() => {});

    return () => {
      observer?.disconnect();
      window.removeEventListener("resize", measure);
    };
  }, [isDark]);

  useLayoutEffect(() => {
    const path = pathRef.current;
    if (!route || !path?.getAttribute("d")) return;
    const total = path.getTotalLength();
    branchNodesRef.current = [...hostRef.current.querySelectorAll(".landing-road-highlight__branch")];
    branchDistancesRef.current = route.branches.map(({ y }) => {
      let low = 0;
      let high = total;
      for (let index = 0; index < 24; index += 1) {
        const middle = (low + high) / 2;
        if (path.getPointAtLength(middle).y < y) low = middle;
        else high = middle;
      }
      return (low + high) / 2;
    });
    updateProgressRef.current?.();
  }, [route]);

  useEffect(() => {
    const host = hostRef.current;
    const scroller = host?.closest(".landing-page");
    const path = pathRef.current;
    const glow = glowRef.current;
    const tip = tipRef.current;
    if (!scroller || !path) return undefined;

    const motion = window.matchMedia?.("(prefers-reduced-motion: reduce)");
    let animationFrame = 0;

    const update = () => {
      animationFrame = 0;
      if (motion?.matches) {
        path.style.strokeDashoffset = "0";
        if (glow) glow.style.strokeDashoffset = "0";
        if (tip) tip.style.display = "none";
        branchNodesRef.current.forEach((node) => {
          const core = node.querySelector(".landing-road-highlight__branch-core");
          const aura = node.querySelector(".landing-road-highlight__branch-glow");
          core.style.strokeDashoffset = "0";
          core.style.opacity = "0.28";
          aura.style.strokeDashoffset = "0";
          aura.style.opacity = "0.1";
        });
        return;
      }

      const viewportHeight = scroller.clientHeight;
      const maxScroll = Math.max(1, scroller.scrollHeight - viewportHeight);
      const lead = Math.min(scroller.scrollTop, viewportHeight * TIP_LEAD_RATIO);
      const progress = clamp01(
        (scroller.scrollTop + lead) / (maxScroll + viewportHeight * TIP_LEAD_RATIO),
      );
      path.style.strokeDashoffset = String(1 - progress);
      if (glow) glow.style.strokeDashoffset = String(1 - progress);
      const length = path.getAttribute("d") ? path.getTotalLength() : 0;
      branchNodesRef.current.forEach((node, index) => {
        const core = node.querySelector(".landing-road-highlight__branch-core");
        const aura = node.querySelector(".landing-road-highlight__branch-glow");
        const distance = length * progress - branchDistancesRef.current[index];
        const reveal = clamp01(distance / (route?.width <= 640 ? 38 : 96));
        const pulse = Math.sin(Math.PI * reveal);
        core.style.strokeDashoffset = String(1 - reveal);
        aura.style.strokeDashoffset = String(1 - reveal);
        core.style.opacity = reveal ? String(0.28 + 0.45 * pulse) : "0";
        aura.style.opacity = reveal ? String(0.09 + 0.42 * pulse) : "0";
      });
      if (tip) {
        tip.style.display = progress > 0 && progress < 1 ? "" : "none";
        if (progress > 0 && progress < 1 && path.getAttribute("d")) {
          const point = path.getPointAtLength(length * progress);
          tip.setAttribute("cx", String(point.x));
          tip.setAttribute("cy", String(point.y));
        } else {
          tip.style.display = "none";
        }
      }
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
  }, [route]);

  return (
    <div ref={hostRef} className="landing-road-highlight" aria-hidden="true">
      <svg
        viewBox={route ? `0 0 ${route.width} ${route.height}` : undefined}
        preserveAspectRatio="none"
        focusable="false"
        style={route ? undefined : { visibility: "hidden" }}
      >
        {route?.branches.map((branch, index) => (
          <g className="landing-road-highlight__branch" key={`${index}-${branch.y}`}>
            <path d={branch.path} pathLength="1" className="landing-road-highlight__branch-glow" />
            <path d={branch.path} pathLength="1" className="landing-road-highlight__branch-core" />
          </g>
        ))}
        <path ref={glowRef} d={route?.path ?? ""} pathLength="1" className="landing-road-highlight__glow" />
        <path
          ref={pathRef}
          d={route?.path ?? ""}
          pathLength="1"
          className="landing-road-highlight__stroke"
        />
        <circle ref={tipRef} className="landing-road-highlight__tip" r="4" style={{ display: "none" }} />
      </svg>
    </div>
  );
}
