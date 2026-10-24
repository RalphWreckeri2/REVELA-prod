import { useState } from "react";
import revelaLogo from "../assets/logo.png";
import { useTheme } from "../context/themeContext";
import "../styles/RevelaLoader.css";

const CYCLE_SECONDS = 2.4;

export default function RevelaLoader({ message }) {
  const { isDark } = useTheme();
  // Keep the three CSS loops in phase even if Suspense hands off to access verification.
  const [phase] = useState(() => typeof performance === "undefined" ? 0 : performance.now() / 1000 % CYCLE_SECONDS);

  return (
    <div className="revela-loader" data-theme={isDark ? "dark" : "light"} role="status" aria-live="polite" style={{ "--loader-phase": `${-phase}s` }}>
      <div className="revela-loader__scene" aria-hidden="true">
        <div className="revela-loader__stage">
          {[0, 1, 2].map((index) => (
            <div className={`revela-loader__figure revela-loader__figure--${index + 1}`} key={index}>
              <span className="revela-loader__jump">
                <img src={revelaLogo} alt="" width="117" height="159" draggable="false" />
              </span>
            </div>
          ))}
        </div>
        <span className="revela-loader__ground" />
        {[0, 1, 2].map((index) => <span className={`revela-loader__shadow revela-loader__shadow--${index + 1}`} key={index} />)}
      </div>
      <p className="revela-loader__message">{message}</p>
    </div>
  );
}
