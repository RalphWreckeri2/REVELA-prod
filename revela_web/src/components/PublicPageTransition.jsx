import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { useTheme } from "../context/themeContext";
import municipalMap from "../assets/mkahoybg.png";
import municipalMapDark from "../assets/mkahoybgdark.png";
import { PublicTransitionContext } from "../context/publicPageTransitionContext";
import { useDeviceAccess } from "../hooks/useDeviceAccess";
import { roadAtViewportY, signInMapCrop } from "./landingMapRoad";
import "../styles/PublicPageTransition.css";

const DURATION = 720;
const reducedMotion = () => window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;

function currentRoutePoint() {
  const path = document.querySelector(".landing-road-highlight__stroke");
  const svg = path?.ownerSVGElement;
  if (!svg?.viewBox.baseVal.width || !path.getTotalLength()) return null;
  const length = path.getTotalLength();
  const offset = path.style.strokeDashoffset === "" ? 1 : Number(path.style.strokeDashoffset);
  const progress = Math.max(0, Math.min(1, 1 - offset));
  const point = path.getPointAtLength(length * progress);
  const box = svg.getBoundingClientRect();
  return {
    x: box.left + point.x * box.width / svg.viewBox.baseVal.width,
    y: box.top + point.y * box.height / svg.viewBox.baseVal.height,
  };
}

function visibleRoad([width, height], card, crop) {
  // Before navigation use the card's normal dimensions; after navigation use
  // its measured edges. Only trace road outside the card, never its outline.
  const top = card?.top ?? height / 2 - (width <= 800 ? 327 : 305);
  const bottom = card?.bottom ?? height / 2 + (width <= 800 ? 362 : 339);
  const below = bottom + 40 < height;
  const endY = below ? bottom + 24 : Math.min(height - 36, Math.max(height * 0.72, (top + bottom) / 2));
  const edgeY = 8;
  if (Math.abs(endY - edgeY) < 24) return null;
  const count = Math.ceil(Math.abs(endY - edgeY) / 24);
  const points = Array.from({ length: count + 1 }, (_, index) => {
    const y = edgeY + (endY - edgeY) * index / count;
    const x = roadAtViewportY(y, crop);
    return x == null ? null : { x, y };
  });
  if (points.some((point) => !point)) return null;
  return { entry: points[0], end: points.at(-1), path: points.map((point, index) => `${index ? "L" : "M"} ${point.x.toFixed(2)} ${point.y.toFixed(2)}`).join(" ") };
}

export function PublicPageTransition({ children }) {
  const navigate = useNavigate();
  const location = useLocation();
  const { isDark } = useTheme();
  const { restricted } = useDeviceAccess();
  const scrollPosition = useRef(null);
  const busy = useRef(false);
  const timers = useRef([]);
  const [phase, setPhase] = useState("idle");
  const [line, setLine] = useState(null);
  const [size, setSize] = useState([window.innerWidth, window.innerHeight]);
  const [cardBounds, setCardBounds] = useState(null);

  const clearTimers = useCallback(() => {
    timers.current.forEach(window.clearTimeout);
    timers.current = [];
  }, []);

  useEffect(() => {
    const resize = () => setSize([window.innerWidth, window.innerHeight]);
    window.addEventListener("resize", resize);
    return () => { window.removeEventListener("resize", resize); clearTimers(); };
  }, [clearTimers]);

  useLayoutEffect(() => {
    if (location.pathname !== "/login") return undefined;
    const card = document.querySelector(".login-card");
    if (!card) return undefined;
    const measure = () => {
      const { top, bottom } = card.getBoundingClientRect();
      setCardBounds((previous) => previous?.top === top && previous?.bottom === bottom ? previous : { top, bottom });
    };
    const frame = window.requestAnimationFrame(measure);
    const observer = typeof ResizeObserver === "function" ? new ResizeObserver(measure) : null;
    observer?.observe(card);
    card.addEventListener("animationend", measure);
    window.addEventListener("resize", measure);
    return () => { window.cancelAnimationFrame(frame); observer?.disconnect(); card.removeEventListener("animationend", measure); window.removeEventListener("resize", measure); };
  }, [location.pathname, location.key]);

  useEffect(() => {
    // History changes can interrupt a transition; defer state cleanup so
    // React does not synchronously cascade an extra render from an effect.
    const timer = window.setTimeout(() => {
      if (location.pathname === "/login") return;
      if (location.pathname === "/" && (phase === "to-home" || phase === "idle")) return;
      clearTimers();
      busy.current = false;
      setPhase("idle");
      setLine(null);
    }, 0);
    return () => window.clearTimeout(timer);
  // Only react to a history entry change, not to the forward phase starting.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [location.key]);

  const toLogin = useCallback((event) => {
    if (event && (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey)) return;
    event?.preventDefault();
    if (busy.current) return;
    busy.current = true;
    scrollPosition.current = document.querySelector(".landing-page")?.scrollTop ?? 0;
    let start;
    try { start = currentRoutePoint(); } catch { start = null; }
    if (reducedMotion() || !start) {
      busy.current = false;
      navigate("/login");
      return;
    }
    if (!visibleRoad([window.innerWidth, window.innerHeight], null, signInMapCrop(window.innerWidth, window.innerHeight))) {
      busy.current = false;
      navigate("/login");
      return;
    }
    setLine({ start });
    setPhase("to-login");
    timers.current.push(window.setTimeout(() => navigate("/login", { state: { publicTransition: true } }), 360));
    timers.current.push(window.setTimeout(() => { setPhase("settled"); busy.current = false; }, DURATION));
  }, [navigate]);

  const toHome = useCallback(() => {
    if (busy.current) return;
    busy.current = true;
    if (reducedMotion()) {
      setPhase("idle");
      setLine(null);
      busy.current = false;
      navigate("/", { state: { skipIntro: true } });
      return;
    }
    setPhase("to-home");
    timers.current.push(window.setTimeout(() => navigate("/", { state: { skipIntro: true } }), 320));
    timers.current.push(window.setTimeout(() => {
      setPhase("idle");
      setLine(null);
      busy.current = false;
    }, DURATION));
  }, [navigate]);

  // The landing scroller is a nested element, not window. Restore it after
  // mounting, including browser Back, without a visible jump to the hero.
  useLayoutEffect(() => {
    if (location.pathname !== "/" || scrollPosition.current == null) return;
    const scroller = document.querySelector(".landing-page");
    if (!scroller) return;
    scroller.style.scrollBehavior = "auto";
    scroller.scrollTop = scrollPosition.current;
    scroller.style.removeProperty("scroll-behavior");
    if (location.state?.skipIntro) document.querySelector(".landing-brand")?.focus({ preventScroll: true });
  }, [location.pathname, location.key, location.state?.skipIntro]);

  const active = location.pathname === "/" || location.pathname === "/login";
  const crop = signInMapCrop(...size);
  const road = visibleRoad(size, phase === "to-login" ? null : cardBounds, crop);
  const connector = line?.start && road
    ? `M ${line.start.x} ${line.start.y} C ${line.start.x + (road.entry.x - line.start.x) * 0.35} ${line.start.y + (road.entry.y - line.start.y) * 0.25} ${road.entry.x} ${road.entry.y - (road.entry.y - line.start.y) * 0.2} ${road.entry.x} ${road.entry.y}`
    : null;
  const visible = active && !restricted && (phase !== "idle" || location.pathname === "/login");

  return (
    <PublicTransitionContext.Provider value={{ toLogin, toHome }}>
      {children}
      {visible && road && (
        <div className={`public-route-layer public-route-layer--${phase}`} data-theme={isDark ? "dark" : "light"} aria-hidden="true"
          style={{
            "--public-map": `url("${isDark ? municipalMapDark : municipalMap}")`,
            "--public-map-width": `${crop.imageWidth}px`,
            "--public-map-height": `${crop.imageHeight}px`,
            "--public-map-x": `${crop.position * 100}%`,
          }}>
          <div className="public-route-layer__map" />
          <svg viewBox={`0 0 ${size[0]} ${size[1]}`} preserveAspectRatio="none" focusable="false">
            {phase === "to-login" && connector && (
              <g className="public-route-layer__connector">
                <path className="public-route-layer__glow" d={connector} pathLength="1" />
                <path className="public-route-layer__line" d={connector} pathLength="1" />
              </g>
            )}
            <g className="public-route-layer__road">
              <path className="public-route-layer__glow" d={road.path} pathLength="1" />
              <path className="public-route-layer__line" d={road.path} pathLength="1" />
            </g>
            <circle className="public-route-layer__dot" cx={road.end.x} cy={road.end.y} r="4" />
          </svg>
        </div>
      )}
    </PublicTransitionContext.Provider>
  );
}
