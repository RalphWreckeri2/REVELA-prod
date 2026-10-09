import {
  useEffect,
  useMemo,
  useState,
  useCallback,
  useSyncExternalStore,
} from "react";
import { ThemeContext } from "./themeContext";

const subscribeToSystemTheme = (onChange) => {
  if (typeof window === "undefined" || !window.matchMedia) return () => {};
  const mediaQuery = window.matchMedia("(prefers-color-scheme: dark)");
  mediaQuery.addEventListener("change", onChange);
  return () => mediaQuery.removeEventListener("change", onChange);
};

const getSystemThemeSnapshot = () => (
  typeof window !== "undefined" &&
  Boolean(window.matchMedia?.("(prefers-color-scheme: dark)").matches)
);

/**
 * Resolves the effective theme ("light" | "dark") from the user's preference.
 * When preference is "system", it queries the OS-level media query.
 */
export function ThemeProvider({ children }) {
  const [preference, setPreference] = useState(() => {
    if (typeof window === "undefined") return "system";
    const stored = window.localStorage.getItem("revela-theme");
    if (stored === "dark" || stored === "light" || stored === "system") return stored;
    return "system";
  });

  const [preview, setPreview] = useState(null);
  const activePref = preview || preference;
  const systemPrefersDark = useSyncExternalStore(
    subscribeToSystemTheme,
    getSystemThemeSnapshot,
    () => false,
  );
  const resolved = activePref === "system"
    ? systemPrefersDark ? "dark" : "light"
    : activePref;

  // Apply the resolved theme to <html>
  useEffect(() => {
    const root = document.documentElement;
    root.classList.toggle("theme-dark", resolved === "dark");
  }, [resolved]);

  // Persist real preference
  useEffect(() => {
    window.localStorage.setItem("revela-theme", preference);
  }, [preference]);

  const setTheme = useCallback((newPref) => {
    setPreference(newPref);
    setPreview(null);
  }, []);
  
  const setPreviewTheme = useCallback((newPref) => {
    setPreview(newPref);
  }, []);

  const value = useMemo(
    () => ({
      theme: preference,       
      previewTheme: preview,
      resolvedTheme: resolved,  
      setTheme,
      setPreviewTheme,
      isDark: resolved === "dark",
    }),
    [preference, preview, resolved, setTheme, setPreviewTheme]
  );

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}
