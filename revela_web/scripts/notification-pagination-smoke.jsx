import { createRoot } from "react-dom/client";
import { MemoryRouter } from "react-router-dom";
import { AuthContext } from "../src/context/authContext";
import { ThemeContext } from "../src/context/themeContext";
import { AppRefreshProvider } from "../src/components/AppRefreshProvider";
import DashboardLayout from "../src/components/DashboardLayout";
import "../src/index.css";

const checks = [];
const theme = new URLSearchParams(location.search).get("theme") === "dark" ? "dark" : "light";
document.documentElement.classList.toggle("theme-dark", theme === "dark");
const check = (ok, label) => { if (!ok) throw new Error(label); checks.push(label); };
const wait = async predicate => {
  for (let i = 0; i < 200; i++) { if (predicate()) return; await new Promise(resolve => setTimeout(resolve, 25)); }
  throw new Error("Notification panel did not become ready");
};

let entries = Array.from({ length: 8 }, (_, i) => ({
  id: 8 - i, title: `Alert ${8 - i}`, body: `Message ${8 - i}`,
  readAt: i > 1 ? "2026-10-30 10:00:00" : null, createdAt: "2026-10-31 10:00:00",
}));
const requestedOffsets = [];
window.fetch = async (input, options = {}) => {
  const url = new URL(input, location.href);
  if (url.pathname.endsWith("/notifications/stream")) {
    return new Response('data: {"type":"connected"}\n\n', { headers: { "Content-Type": "text/event-stream" } });
  }
  if (url.pathname.endsWith("/notifications/unread-count")) {
    return Response.json({ count: entries.filter(n => !n.readAt).length });
  }
  if (url.pathname.endsWith("/notifications/read")) {
    entries = entries.map(n => ({ ...n, readAt: n.readAt || "2026-10-31 11:00:00" }));
    return Response.json({ updated: entries.length });
  }
  if (url.pathname.endsWith("/notifications")) {
    if (options.method === "DELETE") { entries = []; return Response.json({ deleted: 8 }); }
    const limit = Number(url.searchParams.get("limit"));
    const offset = Number(url.searchParams.get("offset"));
    requestedOffsets.push(offset);
    return Response.json({ data: entries.slice(offset, offset + limit), total: entries.length });
  }
  return Response.json({ data: [] });
};

const root = createRoot(document.getElementById("smoke-root"));
try {
  root.render(
    <AuthContext.Provider value={{ token: "fixture", user: { role: "Admin", fullName: "Test Admin" }, logout() {}, refreshUser: async () => {} }}>
      <ThemeContext.Provider value={{ theme, resolvedTheme: theme }}>
        <AppRefreshProvider><MemoryRouter initialEntries={["/home"]}>
          <DashboardLayout><p>Notification paging fixture</p></DashboardLayout>
        </MemoryRouter></AppRefreshProvider>
      </ThemeContext.Provider>
    </AuthContext.Provider>,
  );
  await wait(() => document.querySelector('.notification-wrapper > button'));
  document.querySelector('.notification-wrapper > button').click();
  await wait(() => document.querySelectorAll('.notification-list .notification-item').length === 3);
  const panel = document.querySelector('.notification-popover').getBoundingClientRect();
  check(panel.left >= 0 && panel.right <= innerWidth + 1 && panel.bottom <= innerHeight + 1,
    `notification pages stay inside the viewport (${Math.round(panel.left)}–${Math.round(panel.right)}, bottom ${Math.round(panel.bottom)})`);
  const shown = () => [...document.querySelectorAll('.notification-list .notification-item strong')].map(n => n.textContent);
  const previous = () => document.querySelector('[aria-label="See previous notifications"]');
  const newer = () => document.querySelector('[aria-label="See newer notifications"]');
  check(shown().join(',') === 'Alert 8,Alert 7,Alert 6', 'only the three newest notifications appear first');
  check(newer().disabled && !previous().disabled, 'newer is disabled on the first page');
  previous().click();
  await wait(() => shown()[0] === 'Alert 5');
  check(shown().join(',') === 'Alert 5,Alert 4,Alert 3', 'previous replaces rather than piles up notifications');
  previous().click();
  await wait(() => shown()[0] === 'Alert 2');
  check(shown().join(',') === 'Alert 2,Alert 1' && previous().disabled, 'last page has only the remaining older alerts');
  newer().click();
  await wait(() => shown()[0] === 'Alert 5');
  check(requestedOffsets.includes(0) && requestedOffsets.includes(3) && requestedOffsets.includes(6), 'each page requests its own server offset');
  document.querySelector('[title="Mark all as read"]').click();
  newer().click();
  await wait(() => shown()[0] === 'Alert 8');
  check(!document.querySelector('.notification-item--unread') && !document.querySelector('.nav-badge'), 'mark all as read also updates newer pages and the unread badge');
  previous().click();
  await wait(() => shown()[0] === 'Alert 5');
  document.querySelector('.notification-wrapper > button').click();
  await wait(() => !document.querySelector('.notification-popover'));
  document.querySelector('.notification-wrapper > button').click();
  await wait(() => shown()[0] === 'Alert 8');
  check(newer().disabled, 'reopening the panel starts with the newest notifications');
  document.querySelector('[title="Clear all"]').click();
  await wait(() => !document.querySelector('.notification-pagination'));
  check(document.querySelectorAll('.notification-list .notification-item').length === 0, 'clear all resets paging and content');
  document.getElementById('notification-pagination-smoke-results').textContent = JSON.stringify({ failed: false, checks });
} catch (error) {
  document.getElementById('notification-pagination-smoke-results').textContent = JSON.stringify({ failed: true, error: error.message, checks });
} finally { root.unmount(); }
