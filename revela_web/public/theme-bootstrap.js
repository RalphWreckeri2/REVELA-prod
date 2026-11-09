// Use ThemeProvider's saved preference and system fallback before CSS or
// the React intro can paint, so a saved dark landing never flashes white.
try {
  const preference = localStorage.getItem("revela-theme");
  if (preference === "dark" ||
    (preference !== "light" && matchMedia("(prefers-color-scheme: dark)").matches)) {
    document.documentElement.classList.add("theme-dark");
  }
} catch {
  if (matchMedia("(prefers-color-scheme: dark)").matches) {
    document.documentElement.classList.add("theme-dark");
  }
}
