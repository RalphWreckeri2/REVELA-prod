import { useEffect, useLayoutEffect, useRef, useState } from "react";
import revelaLogo from "../assets/logo.png";
import mapRoads from "../assets/intro-map-roads.png";
import { ROAD_POINTS } from "./landingMapRoad";
import { useTheme } from "../context/themeContext";
import { useLocation } from "react-router-dom";

const SESSION_KEY = "revela.landing.intro.v9";
const INTRO_FALLBACK_MS = 6100;
let playedWithoutStorage = false;

const prefersReducedMotion = () => (
  typeof window !== "undefined" &&
  typeof window.matchMedia === "function" &&
  window.matchMedia("(prefers-reduced-motion: reduce)").matches
);

const hasAlreadyPlayed = () => {
  try {
    return playedWithoutStorage || window.sessionStorage.getItem(SESSION_KEY) === "played";
  } catch {
    return playedWithoutStorage;
  }
};

// Project the already-traced road from the source map into this exact crop.
// The artwork itself is extracted from the same source by generate-intro-map.py.
const cropRoad = ROAD_POINTS.filter(([, y]) => y >= 350 && y <= 2150)
  .map(([x, y]) => [((x - 700) / 3200) * 1200, ((y - 350) / 1800) * 675]);
const pathFromPoints = (points) => points.map(([x, y], index) => `${index ? "L" : "M"} ${x.toFixed(2)} ${y.toFixed(2)}`).join(" ");
const highlightedRoad = pathFromPoints(cropRoad);
const travelingRoad = pathFromPoints(cropRoad.filter(([, y]) => y >= 375 && y <= 620).reverse());

export default function LandingIntroReveal({ children }) {
  const { isDark } = useTheme();
  const location = useLocation();
  const contentRef = useRef(null);
  const mapRef = useRef(null);
  const [status, setStatus] = useState(() => {
    if (typeof window === "undefined") return "complete";
    return location.state?.skipIntro || prefersReducedMotion() || hasAlreadyPlayed() ? "complete" : "playing";
  });

  useEffect(() => {
    if (!location.state?.skipIntro) return;
    playedWithoutStorage = true;
    try { window.sessionStorage.setItem(SESSION_KEY, "played"); } catch { /* Optional storage. */ }
  }, [location.state?.skipIntro]);

  // Non-scaling strokes use screen-pixel dash lengths. Measure each path at
  // its rendered size so the end of every street is drawn on all viewports.
  useLayoutEffect(() => {
    if (status !== "playing" || !mapRef.current) return undefined;
    const svg = mapRef.current;
    const measure = () => {
      const scale = svg.getBoundingClientRect().width / svg.viewBox.baseVal.width;
      svg.querySelectorAll(".landing-opening__main-road").forEach((path) => {
        path.style.setProperty("--line-length", `${Math.ceil(path.getTotalLength() * scale * 1.08)}px`);
      });
    };
    measure();
    const observer = typeof ResizeObserver === "function" ? new ResizeObserver(measure) : null;
    observer?.observe(svg);
    return () => observer?.disconnect();
  }, [status]);

  // Independent of animation events: always release the page.
  useEffect(() => {
    if (status !== "playing") return undefined;

    playedWithoutStorage = true;
    try {
      window.sessionStorage.setItem(SESSION_KEY, "played");
    } catch {
      // Retain once-per-mount-session behavior when storage is unavailable.
    }

    const timer = window.setTimeout(() => setStatus("complete"), INTRO_FALLBACK_MS);
    return () => window.clearTimeout(timer);
  }, [status]);

  // Hold the page still while the intro owns the screen. Cleanup always
  // restores the exact inline styles so scrolling and interaction come back.
  useEffect(() => {
    if (status !== "playing") return undefined;

    const scroller = contentRef.current?.querySelector(".landing-page");
    const bodyOverflow = document.body.style.overflow;
    const rootOverflow = document.documentElement.style.overflow;
    const scrollerOverflow = scroller?.style.overflowY;

    document.body.style.overflow = "hidden";
    document.documentElement.style.overflow = "hidden";
    if (scroller) scroller.style.overflowY = "hidden";

    return () => {
      document.body.style.overflow = bodyOverflow;
      document.documentElement.style.overflow = rootOverflow;
      if (scroller) scroller.style.overflowY = scrollerOverflow;
    };
  }, [status]);

  useEffect(() => {
    if (typeof window.matchMedia !== "function") return undefined;
    const query = window.matchMedia("(prefers-reduced-motion: reduce)");
    const handleChange = () => {
      if (query.matches) setStatus("complete");
    };

    query.addEventListener?.("change", handleChange);
    return () => query.removeEventListener?.("change", handleChange);
  }, []);

  const handleRevealEnd = (event) => {
    if (event.animationName === "landing-opening-reveal") setStatus("complete");
  };

  return (
    <>
      <div
        ref={contentRef}
        className={`landing-intro-content is-${status}`}
        inert={status !== "complete"}
      >
        {children}
      </div>

      {status === "playing" && (
        <div className="landing-opening" data-theme={isDark ? "dark" : "light"} aria-hidden="true">
          <div className="landing-opening__cover" onAnimationEnd={handleRevealEnd} />
          <div className="landing-opening__disc" />

          <div className="landing-opening__scene">
            <div className="landing-opening__map">
              <div className="landing-opening__artwork">
                <img className="landing-opening__roads" src={mapRoads} alt="" draggable="false" />
                <svg ref={mapRef} className="landing-opening__road-overlay" viewBox="0 0 1200 675" focusable="false">
                  <path className="landing-opening__main-road landing-opening__main-road--glow" d={highlightedRoad} vectorEffect="non-scaling-stroke" />
                  <path className="landing-opening__main-road" d={highlightedRoad} vectorEffect="non-scaling-stroke" />
                  <circle className="landing-opening__traveler" r="3.5" style={{ offsetPath: `path("${travelingRoad}")` }} />
                </svg>
              </div>
            </div>
          </div>

          <div className="landing-opening__portal">
            <span className="landing-opening__dot" />

            <div className="landing-opening__logo">
              <div className="landing-opening__logo-jump">
                <img
                  src={revelaLogo}
                  alt=""
                  width="117"
                  height="159"
                  draggable="false"
                />
              </div>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
