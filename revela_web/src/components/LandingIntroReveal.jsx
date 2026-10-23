import { useEffect, useRef, useState } from "react";
import revelaLogo from "../assets/logo.png";

const SESSION_KEY = "revela.landing.intro.v5";
const INTRO_FALLBACK_MS = 5600;
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

/**
 * Abstract, map-inspired streets drawn in a 1000 × 1000 frame. Paths start
 * outside the viewport and finish just short of the center so the drawing
 * motion converges on the portal. Branches finish at their junction.
 */
const mapLines = [
  { id: "north", tone: "primary", delay: 0.42, duration: 1.24, d: "M500 -20 L500 120 L500 200 L492 235 L492 292 L500 330 L500 486" },
  { id: "north-east", tone: "primary", delay: 0.48, duration: 1.3, d: "M1000 -10 L880 70 L820 120 L780 190 L720 240 L676 298 L620 350 L566 402 L522 478" },
  { id: "east", tone: "primary", delay: 0.54, duration: 1.2, d: "M1020 520 L900 520 L820 514 L740 514 L660 506 L585 500 L518 500" },
  { id: "south-east", tone: "primary", delay: 0.6, duration: 1.28, d: "M1010 1010 L920 900 L860 840 L790 780 L740 720 L680 662 L620 612 L568 566 L522 520" },
  { id: "south", tone: "primary", delay: 0.66, duration: 1.2, d: "M540 1020 L540 920 L528 850 L528 780 L520 720 L512 660 L506 600 L502 516" },
  { id: "south-west", tone: "primary", delay: 0.72, duration: 1.3, d: "M-10 1010 L110 900 L180 840 L240 780 L300 720 L360 660 L420 610 L462 566 L486 522" },
  { id: "west", tone: "primary", delay: 0.78, duration: 1.16, d: "M-20 470 L110 470 L190 476 L270 480 L350 490 L420 496 L452 500 L520 500" },
  { id: "north-west", tone: "primary", delay: 0.84, duration: 1.3, d: "M-20 40 L100 120 L170 170 L230 230 L290 290 L350 350 L410 410 L460 446 L490 482" },
  { id: "west-lower", tone: "primary", delay: 0.9, duration: 1.18, d: "M-20 760 L120 760 L200 748 L280 730 L350 710 L410 680 L452 646 L496 586 L520 514" },
  { id: "north-north-west", tone: "primary", delay: 0.96, duration: 1.22, d: "M310 -20 L310 100 L320 160 L360 220 L400 280 L440 340 L470 400 L490 440 L500 482" },
  { id: "branch-north", tone: "branch", delay: 0.86, duration: 0.7, d: "M620 110 L560 150 L500 160" },
  { id: "branch-nnw", tone: "branch", delay: 0.98, duration: 0.64, d: "M260 250 L270 190 L320 140" },
  { id: "branch-east", tone: "branch", delay: 1.06, duration: 0.62, d: "M880 420 L840 460 L820 520" },
  { id: "branch-west", tone: "branch", delay: 1.02, duration: 0.66, d: "M280 596 L262 540 L270 480" },
  { id: "branch-south", tone: "branch", delay: 1.12, duration: 0.62, d: "M650 890 L600 858 L528 850" },
  { id: "branch-se", tone: "branch", delay: 1.18, duration: 0.62, d: "M850 860 L830 810 L790 780" },
  { id: "branch-sw", tone: "branch", delay: 1.24, duration: 0.62, d: "M180 870 L200 820 L240 780" },
  { id: "branch-ne", tone: "branch", delay: 1.08, duration: 0.62, d: "M720 200 L710 260 L676 298" },
  { id: "branch-west-mid", tone: "branch", delay: 1.14, duration: 0.6, d: "M310 580 L340 540 L350 490" },
  { id: "branch-nw-mid", tone: "branch", delay: 1.2, duration: 0.6, d: "M372 500 L380 450 L420 410" },
  { id: "gold-north-east", tone: "gold", delay: 0.92, duration: 0.7, d: "M590 250 L600 300 L620 350" },
  { id: "gold-south-west", tone: "gold", delay: 1.16, duration: 0.68, d: "M330 750 L340 700 L360 660" },
  { id: "curl", tone: "curl", delay: 1.52, duration: 0.58, d: "M500 455 C556 448 588 492 566 530 C544 568 490 572 464 536 C442 504 462 470 492 468" },
];

export default function LandingIntroReveal({ children }) {
  const contentRef = useRef(null);
  const [status, setStatus] = useState(() => {
    if (typeof window === "undefined") return "complete";
    return prefersReducedMotion() || hasAlreadyPlayed() ? "complete" : "playing";
  });

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
        <div className="landing-opening" aria-hidden="true">
          <div className="landing-opening__cover" onAnimationEnd={handleRevealEnd} />
          <div className="landing-opening__disc" />

          <div className="landing-opening__scene">
            <svg
              className="landing-opening__lines"
              viewBox="0 0 1000 1000"
              preserveAspectRatio="xMidYMid slice"
              focusable="false"
            >
              {mapLines.map((line) => (
                <path
                  key={line.id}
                  d={line.d}
                  pathLength="1"
                  vectorEffect="non-scaling-stroke"
                  className={`landing-opening__line landing-opening__line--${line.tone}`}
                  style={{
                    "--line-delay": `${line.delay}s`,
                    "--line-duration": `${line.duration}s`,
                  }}
                />
              ))}
            </svg>
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
