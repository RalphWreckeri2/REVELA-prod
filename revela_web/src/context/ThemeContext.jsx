import { createContext, useContext, useEffect, useMemo, useState, useCallback } from "react";

const ThemeContext = createContext(null);

/**
 * Resolves the effective theme ("light" | "dark") from the user's preference.
 * When preference is "system", it queries the OS-level media query.
 */
function resolveTheme(preference) {
  if (preference === "system") {
    return window.matchMedia?.("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  }
  return preference;
}

export function ThemeProvider({ children }) {
  const [preference, setPreference] = useState(() => {
    if (typeof window === "undefined") return "system";
    const stored = window.localStorage.getItem("revela-theme");
    if (stored === "dark" || stored === "light" || stored === "system") return stored;
    return "system";
  });

  const [preview, setPreview] = useState(null);
  const activePref = preview || preference;
  
  const [resolved, setResolved] = useState(() => resolveTheme(activePref));

  useEffect(() => {
    setResolved(resolveTheme(activePref));
  }, [activePref]);

  // Apply the resolved theme to <html>
  useEffect(() => {
    const root = document.documentElement;
    root.classList.toggle("theme-dark", resolved === "dark");
  }, [resolved]);

  // Persist real preference
  useEffect(() => {
    window.localStorage.setItem("revela-theme", preference);
  }, [preference]);

  // Listen for OS theme changes when in "system" mode
  useEffect(() => {
    if (activePref !== "system") {
      return;
    }
    const mql = window.matchMedia("(prefers-color-scheme: dark)");
    const handler = (e) => setResolved(e.matches ? "dark" : "light");

    mql.addEventListener("change", handler);
    return () => mql.removeEventListener("change", handler);
  }, [activePref]);

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

export function useTheme() {
  const context = useContext(ThemeContext);
  if (!context) {
    throw new Error("useTheme must be used within ThemeProvider");
  }
  return context;
}
