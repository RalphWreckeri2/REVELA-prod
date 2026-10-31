import "../src/styles/global.css";
import "../src/styles/InspectionPage.css";
import "../src/styles/InspectionDialog.css";
import "../src/styles/UserManagement.css";
import "../src/styles/AnalyticsPage.css";
import "../src/styles/LoginPage.css";
import "../src/styles/BusinessIDReview.css";

const theme = new URLSearchParams(location.search).get("theme") === "dark" ? "dark" : "light";
document.documentElement.classList.toggle("theme-dark", theme === "dark");
const checks = [];
const check = (ok, label) => { if (!ok) throw new Error(label); checks.push(label); };
const fixture = document.getElementById("focus-fixture");
fixture.innerHTML = `
  <div class="saas-root inspection-dispatch-page"><main class="saas-content">
    <div class="dispatch-search-input"><input type="text" aria-label="Inspection search"></div>
    <div class="search-bar"><input type="search" aria-label="Registry search"></div>
    <div class="um-search"><input type="text" aria-label="Users search"></div>
    <div class="date-range-pair" style="border-width: 1px; border-style: solid"><input type="date" aria-label="Date range"></div>
    <input type="search" aria-label="Map search">
    <input type="email" class="um-input" aria-label="Email field">
    <textarea class="ai-chat-input" aria-label="Message field"></textarea>
    <input type="text" class="business-id-review__input" aria-label="Review field">
    <input type="checkbox" aria-label="Checkbox">
  </main></div>
  <div class="login-root"><input type="password" class="glass-input" aria-label="Password field"></div>
`;

try {
  const focusBorder = getComputedStyle(document.documentElement).getPropertyValue("--field-focus-border").trim();
  const input = (label) => fixture.querySelector(`[aria-label="${label}"]`);
  // Let the browser resolve the CSS custom property to its actual RGB color.
  const sample = document.createElement("div");
  sample.style.border = `1px solid ${focusBorder}`;
  fixture.append(sample);
  const borderColor = getComputedStyle(sample).borderTopColor;
  sample.remove();

  for (const [label, shell] of [
    ["Inspection search", ".dispatch-search-input"],
    ["Registry search", ".search-bar"],
    ["Users search", ".um-search"],
    ["Date range", ".date-range-pair"],
  ]) {
    const field = input(label);
    field.focus();
    field.closest(shell).getAnimations().forEach(animation => animation.finish());
    const inner = getComputedStyle(field);
    const outer = getComputedStyle(field.closest(shell));
    check(outer.borderTopColor === borderColor && outer.boxShadow !== "none",
      `${label} highlights its outer field`);
    check(inner.outlineStyle === "none" && inner.boxShadow === "none", `${label} has no duplicate inner focus ring`);
    if (theme === "dark") check(inner.backgroundColor === "rgba(0, 0, 0, 0)", `${label} inner background stays transparent in dark mode`);
  }
  for (const label of ["Map search", "Email field", "Message field", "Review field", "Password field"]) {
    const field = input(label);
    field.focus();
    field.getAnimations().forEach(animation => animation.finish());
    const style = getComputedStyle(field);
    check(style.borderTopColor === borderColor && style.boxShadow !== "none" && style.outlineStyle === "none",
      `${label} uses the shared single focus boundary`);
  }
  input("Checkbox").focus();
  check(getComputedStyle(input("Checkbox")).boxShadow === "none", "non-text controls keep their own focus behavior");
  document.getElementById("text-field-focus-smoke-results").textContent = JSON.stringify({ failed: false, checks });
} catch (error) {
  document.getElementById("text-field-focus-smoke-results").textContent = JSON.stringify({ failed: true, error: error.message, checks });
}
