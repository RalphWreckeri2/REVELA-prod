import { useState } from "react";
import { useTheme } from "../context/themeContext";
import "../styles/RevelaLoader.css";

const CYCLE_SECONDS = 3.2;

// One connected walk: main road, out-and-back at each junction, then onward.
// The traveler fades between the distinct endpoints rather than jumping visibly.
const searchRoute = [
  "M 14 96 C 34 96 38 74 60 65",
  "C 64 48 49 43 55 26 C 58 19 67 19 72 16",
  "C 67 19 58 19 55 26 C 49 43 64 48 60 65",
  "C 82 56 91 69 108 80 C 125 91 137 84 149 72",
  "C 154 83 165 86 178 105 C 182 112 195 115 205 108",
  "C 195 115 182 112 178 105 C 165 86 154 83 149 72",
  "C 169 51 185 60 204 42",
].join(" ");

export default function RevelaLoader({ message }) {
  const { isDark } = useTheme();
  // Preserve the loop's phase when Suspense hands off to access verification.
  const [phase] = useState(() => typeof performance === "undefined" ? 0 : performance.now() / 1000 % CYCLE_SECONDS);

  return (
    <div className="revela-loader" data-theme={isDark ? "dark" : "light"}
      role="status" aria-live="polite" style={{ "--loader-phase": `${-phase}s` }}>
      <svg className="revela-loader__map" viewBox="0 0 220 132" aria-hidden="true" focusable="false">
        <g className="revela-loader__streets">
          <path d="M 14 96 C 34 96 38 74 60 65 C 82 56 91 69 108 80 C 125 91 137 84 149 72 C 169 51 185 60 204 42" />
          <path d="M 60 65 C 64 48 49 43 55 26 C 58 19 67 19 72 16" />
          <path d="M 149 72 C 154 83 165 86 178 105 C 182 112 195 115 205 108" />
          <path d="M 35 84 C 27 77 30 63 18 55" />
          <path d="M 108 80 C 104 93 102 98 91 109" />
          <path d="M 179 55 C 179 42 187 33 197 27" />
        </g>
        <g className="revela-loader__junctions">
          <path className="revela-loader__junction revela-loader__junction--first" d="M 60 65 C 64 48 49 43 55 26 C 58 19 67 19 72 16" />
          <path className="revela-loader__junction revela-loader__junction--second" d="M 149 72 C 154 83 165 86 178 105 C 182 112 195 115 205 108" />
        </g>
        <path className="revela-loader__trail-glow" d={searchRoute} pathLength="100" />
        <path className="revela-loader__trail" d={searchRoute} pathLength="100" />
        <circle className="revela-loader__scan revela-loader__scan--first" cx="60" cy="65" r="7" />
        <circle className="revela-loader__scan revela-loader__scan--second" cx="149" cy="72" r="7" />
        <g className="revela-loader__traveler">
          <circle className="revela-loader__halo" r="7" />
          <circle className="revela-loader__point" r="3.1" />
          <animateMotion path={searchRoute} dur={`${CYCLE_SECONDS}s`} begin={`${-phase}s`}
            repeatCount="indefinite" calcMode="paced" />
        </g>
        <circle className="revela-loader__static-point" cx="60" cy="65" r="3.1" />
      </svg>
      <p className="revela-loader__message">{message}</p>
    </div>
  );
}
