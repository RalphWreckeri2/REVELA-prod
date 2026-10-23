import { useEffect, useLayoutEffect, useRef, useState } from "react";
import revelaLogo from "../assets/logo.png";
import mapRoads from "../assets/intro-map-roads.png";
import mapRoadsLarge from "../assets/intro-map-roads-large.png";
import { ROAD_POINTS } from "./landingMapRoad";
import { useTheme } from "../context/themeContext";
import { useLocation } from "react-router-dom";

const SESSION_KEY = "revela.landing.intro.v13";
const ASSET_TIMEOUT_MS = 6000;
const PLAYBACK_WATCHDOG_MS = 14000;
let playedWithoutStorage = false;

function markIntroPlayed() {
  playedWithoutStorage = true;
  try { window.sessionStorage.setItem(SESSION_KEY, "played"); } catch { /* Optional storage. */ }
}

function decodeImage(src) {
  return new Promise((resolve, reject) => {
    const image = new Image();
    image.onload = () => {
      if (image.decode) image.decode().then(resolve, reject);
      else resolve();
    };
    image.onerror = () => reject(new Error(`Could not load intro asset: ${src}`));
    image.src = src;
  });
}

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
  const playbackStartedRef = useRef(null);
  const [mapSource] = useState(() => (
    typeof window !== "undefined" && window.innerWidth * window.devicePixelRatio > 1200
      ? mapRoadsLarge : mapRoads
  ));
  const [phase, setPhase] = useState(() => {
    if (typeof window === "undefined") return "complete";
    return location.state?.skipIntro || prefersReducedMotion() || hasAlreadyPlayed() ? "complete" : "preparing";
  });
  const isActive = phase !== "complete";

  useEffect(() => {
    if (!location.state?.skipIntro) return;
    markIntroPlayed();
  }, [location.state?.skipIntro]);

  useEffect(() => {
    if (phase !== "preparing") return undefined;
    let active = true;
    let ready = false;
    const begin = () => {
      if (!active || !ready || document.hidden) return;
      window.clearTimeout(timeout);
      markIntroPlayed();
      playbackStartedRef.current = performance.now();
      setPhase("drawing");
    };
    const timeout = window.setTimeout(() => {
      if (active && !ready) { markIntroPlayed(); setPhase("complete"); }
    }, ASSET_TIMEOUT_MS);
    window.addEventListener("visibilitychange", begin);
    Promise.all([decodeImage(mapSource), decodeImage(revelaLogo)])
      .then(() => { ready = true; begin(); })
      .catch(() => { if (active) { markIntroPlayed(); setPhase("complete"); } });
    return () => {
      active = false;
      window.clearTimeout(timeout);
      window.removeEventListener("visibilitychange", begin);
    };
  }, [phase, mapSource]);

  // Non-scaling strokes use screen-pixel dash lengths. Measure each path at
  // its rendered size so the end of every street is drawn on all viewports.
  useLayoutEffect(() => {
    if (phase === "preparing" || phase === "complete" || !mapRef.current) return undefined;
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
  }, [phase]);

  // A watchdog is only for failed animation events or long background-tab
  // interruptions. It never schedules the next visual phase.
  useEffect(() => {
    if (!playbackStartedRef.current || phase === "complete") return undefined;
    const remaining = Math.max(0, PLAYBACK_WATCHDOG_MS - (performance.now() - playbackStartedRef.current));
    const timer = window.setTimeout(() => setPhase("complete"), remaining);
    const checkVisibility = () => {
      if (!document.hidden && performance.now() - playbackStartedRef.current >= PLAYBACK_WATCHDOG_MS) {
        setPhase("complete");
      }
    };
    window.addEventListener("visibilitychange", checkVisibility);
    return () => { window.clearTimeout(timer); window.removeEventListener("visibilitychange", checkVisibility); };
  }, [phase]);

  // Hold the page still while the intro owns the screen. Cleanup always
  // restores the exact inline styles so scrolling and interaction come back.
  useEffect(() => {
    if (!isActive) return undefined;

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
  }, [isActive]);

  useEffect(() => {
    if (typeof window.matchMedia !== "function") return undefined;
    const query = window.matchMedia("(prefers-reduced-motion: reduce)");
    const handleChange = () => {
      if (query.matches) setPhase("complete");
    };

    query.addEventListener?.("change", handleChange);
    return () => query.removeEventListener?.("change", handleChange);
  }, []);

  const handleAnimationEnd = (event) => {
    if (phase === "drawing" && event.target.classList.contains("landing-opening__roads") && event.animationName === "landing-opening-map-coast") {
      setPhase("collapsing");
    } else if (phase === "collapsing" && event.target.classList.contains("landing-opening__map") && event.animationName === "landing-opening-lines-out") {
      setPhase("logo");
    } else if (phase === "logo" && event.target.classList.contains("landing-opening__logo-jump") && event.animationName === "landing-opening-logo-jump") {
      setPhase("revealing");
    } else if (phase === "revealing" && event.target.classList.contains("landing-opening__cover") && event.animationName === "landing-opening-reveal") {
      setPhase("complete");
    }
  };

  const skipIntro = () => {
    markIntroPlayed();
    setPhase("complete");
    window.requestAnimationFrame(() => document.querySelector(".landing-brand")?.focus({ preventScroll: true }));
  };

  const roadsImage = { src: mapSource, alt: "", draggable: false };

  return (
    <>
      <div
        ref={contentRef}
        className={`landing-intro-content is-${phase === "complete" ? "complete" : "playing"}`}
        inert={phase !== "complete"}
      >
        {children}
      </div>

      {phase !== "complete" && <>
        <div className={`landing-opening is-${phase}`} data-theme={isDark ? "dark" : "light"} aria-hidden="true" onAnimationEnd={handleAnimationEnd}>
          <div className="landing-opening__cover" />
          <div className="landing-opening__disc" />

          <div className="landing-opening__scene">
            <div className="landing-opening__map">
              <div className="landing-opening__artwork">
                <div className="landing-opening__map-frame">
                  <img className="landing-opening__roads" {...roadsImage} />
                  <img className="landing-opening__branch-light landing-opening__branch-light--first" {...roadsImage} />
                  <img className="landing-opening__branch-light landing-opening__branch-light--second" {...roadsImage} />
                  <svg ref={mapRef} className="landing-opening__road-overlay" viewBox="0 0 1200 675" preserveAspectRatio="xMidYMid meet" focusable="false">
                  <path className="landing-opening__main-road landing-opening__main-road--glow" d={highlightedRoad} vectorEffect="non-scaling-stroke" />
                  <path className="landing-opening__main-road" d={highlightedRoad} vectorEffect="non-scaling-stroke" />
                  <circle className="landing-opening__traveler" r="3.5" style={{ offsetPath: `path("${travelingRoad}")` }} />
                  </svg>
                </div>
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
        <button className="landing-opening-skip" type="button" onClick={skipIntro}>Skip intro</button>
      </>}
    </>
  );
}
