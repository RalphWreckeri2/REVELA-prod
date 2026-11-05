import { useEffect } from "react";

/**
 * Shows the browser's leave/refresh warning while `active` is true.
 * This covers full page unloads only; in-app React Router navigation does not
 * fire `beforeunload`, so callers must keep that limitation in mind.
 */
export function useBeforeUnloadWarning(active) {
  useEffect(() => {
    if (!active) return undefined;

    const warnBeforeUnload = (event) => {
      event.preventDefault();
      event.returnValue = "";
    };

    window.addEventListener("beforeunload", warnBeforeUnload);
    return () => window.removeEventListener("beforeunload", warnBeforeUnload);
  }, [active]);
}
