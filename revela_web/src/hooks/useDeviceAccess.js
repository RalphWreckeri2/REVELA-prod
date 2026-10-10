import { useEffect, useState } from "react";
import { readAccessDecision } from "../components/mobileDetection";

/**
 * Tracks the device-access decision and keeps it current.
 *
 * Re-evaluates on resize, orientation change and visual-viewport changes so
 * rotating a tablet out of the restricted range (or a phone into it) takes
 * effect without a reload.
 */
export function useDeviceAccess() {
  const [decision, setDecision] = useState(readAccessDecision);

  useEffect(() => {
    const update = () => setDecision(readAccessDecision());

    window.addEventListener("resize", update);
    window.addEventListener("orientationchange", update);
    window.visualViewport?.addEventListener("resize", update);

    // Safari reports the final size slightly after orientationchange settles.
    const settle = window.setTimeout(update, 250);
    const recheck = window.setTimeout(update, 900);

    return () => {
      window.removeEventListener("resize", update);
      window.removeEventListener("orientationchange", update);
      window.visualViewport?.removeEventListener("resize", update);
      window.clearTimeout(settle);
      window.clearTimeout(recheck);
    };
  }, []);

  return decision;
}