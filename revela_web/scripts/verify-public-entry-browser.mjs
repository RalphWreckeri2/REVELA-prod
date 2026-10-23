// Exercise the production app/router with synthetic API responses only.
// No credentials, backend requests, or production data are used.
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { existsSync, mkdtempSync } from "node:fs";
import { mkdir, rm, writeFile } from "node:fs/promises";
import { join } from "node:path";
import { preview } from "vite";

const edge = process.env.EDGE_BINARY || "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe";
const tempRoot = process.env.LOCALAPPDATA && join(process.env.LOCALAPPDATA, "Temp", "opencode");
if (!existsSync(edge) || !tempRoot || !existsSync(tempRoot)) {
  throw new Error("This browser check requires local Edge and the approved temporary directory.");
}
const profile = mkdtempSync(join(tempRoot, "revela-public-entry-browser-"));
const output = join(tempRoot, "revela-public-entry-review");
await mkdir(output, { recursive: true });
const server = await preview({ preview: { host: "127.0.0.1", port: 0, open: false } });
const origin = `http://127.0.0.1:${server.httpServer.address().port}`;
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
const results = [];
const exceptions = [];
let browser;
let socket;
let call;
let session;

// Runs before the real bundle, leaving the login component and AuthProvider intact.
function installFixtures() {
  const nativeFetch = window.fetch.bind(window);
  window.__entryRequests = [];
  window.fetch = async (input, options = {}) => {
    const url = new URL(typeof input === "string" ? input : input.url, location.href);
    const json = (data, status = 200) => {
      const response = Response.json(data, { status });
      Object.defineProperty(response, "url", { value: url.href });
      return response;
    };
    if (url.pathname.startsWith("/api/")) {
      const path = url.pathname;
      const body = options.body ? JSON.parse(options.body) : null;
      const authorization = options.headers?.Authorization || "";
      window.__entryRequests.push({ path, body, authorization });
      if (path.endsWith("/auth/login")) {
        if (body.password === "incorrect") return json({ error: "Invalid credentials." }, 401);
        if (body.email === "2fa@example.test") return json({ status: "2fa_required", tempToken: "entry-test-temp" });
        const userRole = body.email === "inspector@example.test" ? "Inspector" : "Admin";
        return json({ access_token: "entry-test-token", user: { userRole } });
      }
      if (path.endsWith("/auth/verify-2fa-login")) return json({ access_token: "entry-test-token" });
      if (path.endsWith("/auth/me")) {
        if (authorization.includes("expired-entry-test-token")) return json({ error: "Session expired." }, 401);
        return json({ id: 1, fullName: "Browser Test Admin", email: "admin@example.test",
          role: authorization.includes("inspector-entry-test-token") ? "Inspector" : "Admin", mustChangePassword: false });
      }
      if (path.endsWith("/unread-count")) return json({ count: 0 });
      if (path.endsWith("/stream")) return new Response('data: {"type":"connected"}\n\n', { headers: { "Content-Type": "text/event-stream" } });
      if (path.endsWith("/analytics/all")) {
        const section = url.searchParams.get("section");
        return json({ [section]: section === "summary" ? { kpis: { total_businesses: 0, compliance_rate: 0,
          current_year_registered_count: 0, upcoming_year_renewal_count: 0, total_flagged: 0, reporting_year: 2026 }, new_year_rollover: null }
          : { rankings: [], dispatch_recommendations: [] }, analytics_cache: { age_seconds: 0, computed_at: new Date().toISOString() } });
      }
      return json({ data: [], message: "Browser fixture success." });
    }
    if (url.hostname === "api.open-meteo.com") return json({ current: { temperature_2m: 29, weather_code: 2 } });
    if (url.origin === location.origin) return nativeFetch(input, options);
    throw new Error(`Unexpected external fetch in browser check: ${url.origin}`);
  };
}

try {
  const debuggerURL = await new Promise((resolve, reject) => {
    browser = spawn(edge, ["--headless", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
      "--disable-background-networking", "--disable-component-update", "--disable-sync", "--no-proxy-server",
      "--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1, EXCLUDE localhost, EXCLUDE fonts.googleapis.com, EXCLUDE fonts.gstatic.com",
      `--user-data-dir=${profile}`, "--remote-debugging-port=0", "about:blank"], { windowsHide: true });
    let stderr = "";
    const timer = setTimeout(() => reject(new Error(`Browser startup timed out: ${stderr}`)), 20000);
    browser.stdout.resume();
    browser.stderr.on("data", chunk => {
      stderr += chunk;
      const url = stderr.match(/DevTools listening on (ws:\/\/[^\s]+)/)?.[1];
      if (url) { clearTimeout(timer); resolve(url); }
    });
    browser.on("error", error => { clearTimeout(timer); reject(error); });
  });
  socket = new WebSocket(debuggerURL);
  await new Promise((resolve, reject) => { socket.addEventListener("open", resolve); socket.addEventListener("error", reject); });
  let id = 0;
  const pending = new Map();
  socket.addEventListener("message", event => {
    const message = JSON.parse(event.data);
    if (message.method === "Runtime.exceptionThrown") exceptions.push(message.params.exceptionDetails.exception?.description || message.params.exceptionDetails.text);
    if (!message.id) return;
    const request = pending.get(message.id);
    pending.delete(message.id);
    clearTimeout(request?.timer);
    if (message.error) request?.reject(new Error(JSON.stringify(message.error)));
    else request?.resolve(message.result);
  });
  call = (method, params = {}, sessionId = session) => new Promise((resolve, reject) => {
    const requestID = ++id;
    const timer = setTimeout(() => { pending.delete(requestID); reject(new Error(`Browser call timed out: ${method}`)); }, 30000);
    pending.set(requestID, { resolve, reject, timer });
    socket.send(JSON.stringify({ id: requestID, method, params, sessionId }));
  });
  const { targetId } = await call("Target.createTarget", { url: "about:blank" });
  session = (await call("Target.attachToTarget", { targetId, flatten: true })).sessionId;
  await call("Runtime.enable");
  await call("Page.enable");
  await call("Page.addScriptToEvaluateOnNewDocument", { source: `(${installFixtures.toString()})()` });
  const evaluate = async expression => {
    const response = await call("Runtime.evaluate", { expression, returnByValue: true, awaitPromise: true });
    if (response.exceptionDetails) throw new Error(response.exceptionDetails.exception?.description || response.exceptionDetails.text);
    return response.result?.value;
  };
  const wait = async (expression, label) => {
    const deadline = Date.now() + 20000;
    while (Date.now() < deadline) { if (await evaluate(`Boolean(${expression})`)) return; await sleep(50); }
    throw new Error(`Timed out: ${label}`);
  };
  const navigate = async (path, selector) => {
    await call("Page.navigate", { url: `${origin}${path}` });
    await wait(`location.pathname === ${JSON.stringify(path)} && document.querySelector(${JSON.stringify(selector)})`, path);
  };
  const screenshot = async name => {
    const metrics = await call("Page.getLayoutMetrics");
    const { data } = await call("Page.captureScreenshot", { format: "png", captureBeyondViewport: true,
      clip: { x: 0, y: 0, width: metrics.cssContentSize.width, height: metrics.cssContentSize.height, scale: 1 } });
    await writeFile(join(output, `${name}.png`), Buffer.from(data, "base64"));
  };
  const desktopUA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36";
  const phoneUA = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1";
  const tabletUA = "Mozilla/5.0 (iPad; CPU OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1";
  const viewport = async (width, height, mobile = false) => {
    await call("Emulation.setDeviceMetricsOverride", { width, height, deviceScaleFactor: 1, mobile, screenWidth: width, screenHeight: height });
    await call("Emulation.setUserAgentOverride", { userAgent: mobile ? (Math.min(width, height) < 560 ? phoneUA : tabletUA) : desktopUA });
    await call("Emulation.setTouchEmulationEnabled", { enabled: mobile, maxTouchPoints: mobile ? 5 : 1 });
  };
  const key = async (key, code, virtualKey) => {
    // Chromium needs Enter's text to emit the keypress that activates native buttons.
    for (const type of ["keyDown", "keyUp"]) await call("Input.dispatchKeyEvent", {
      type, key, code, windowsVirtualKeyCode: virtualKey,
      ...(type === "keyDown" && key === "Enter" ? { text: "\r", unmodifiedText: "\r" } : {}),
    });
  };
  const fill = async (selector, value) => evaluate(`(() => {
    const input = document.querySelector(${JSON.stringify(selector)});
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(input, ${JSON.stringify(value)});
    input.dispatchEvent(new Event('input', { bubbles: true }));
  })()`);
  const click = selector => evaluate(`document.querySelector(${JSON.stringify(selector)}).click()`);

  await viewport(1440, 900);
  await navigate("/", ".landing-page");
  await evaluate("localStorage.clear(); sessionStorage.clear()");
  for (const [width, height, mobile] of [[320, 568, true], [320, 740, true], [393, 852, true], [412, 915, true], [852, 393, true],
    [768, 1024, true], [820, 1180, true], [900, 420, false], [1024, 768, false], [1280, 800, false], [1440, 900, false], [1920, 1080, false]]) {
    await viewport(width, height, mobile);
    for (const theme of ["light", "dark"]) {
      await evaluate(`localStorage.setItem('revela-theme', ${JSON.stringify(theme)})`);
      await navigate("/", ".landing-page");
      await wait("[...document.querySelectorAll('.landing-page img')].every(img => img.complete && img.naturalWidth > 0)", "branding assets");
      const map = await evaluate(`new Promise((resolve, reject) => {
        const image = new Image();
        image.onload = () => resolve({ width: image.naturalWidth, height: image.naturalHeight, url: image.src });
        image.onerror = () => reject(new Error('Map background failed to load'));
        image.src = getComputedStyle(document.querySelector('.landing-page')).backgroundImage.match(/url\\("?([^"\\)]+)"?\\)/)[1];
      })`);
      assert.ok(map.width > 0 && map.height > 0 && map.url.includes('mkahoybg'), "the supplied map is the loaded background");
      await evaluate("document.fonts.ready");
      // Let theme-triggered button transitions finish before measuring/capturing.
      await sleep(250);
      const layout = await evaluate(`(() => {
        const page = document.querySelector('.landing-page');
        const luminance = color => {
          const rgb = color.match(/[\\d.]+/g).slice(0, 3).map(Number).map(v => { v /= 255; return v <= .04045 ? v / 12.92 : ((v + .055) / 1.055) ** 2.4; });
          return rgb[0] * .2126 + rgb[1] * .7152 + rgb[2] * .0722;
        };
        const contrast = (a, b) => { const x = luminance(a), y = luminance(b); return (Math.max(x, y) + .05) / (Math.min(x, y) + .05); };
        const cta = getComputedStyle(document.querySelector('.landing-login--primary'));
        const pageStyle = getComputedStyle(page);
        const background = pageStyle.backgroundColor;
        const hero = document.querySelector('.landing-intro').getBoundingClientRect();
        const identity = document.querySelector('.landing-municipal-identity').getBoundingClientRect();
        return { width: innerWidth, overflow: document.documentElement.scrollWidth > innerWidth,
          public: !document.querySelector('.restricted-root, .login-root'), headingCount: page.querySelectorAll('h1').length,
          ctaContrast: contrast(cta.color, cta.backgroundColor),
          textContrast: contrast(getComputedStyle(document.querySelector('.landing-description')).color, background),
          linksFit: [...page.querySelectorAll('a:not(.landing-skip-link), button')].filter(a => a.getClientRects().length).every(a => { const r = a.getBoundingClientRect(); return r.left >= 0 && r.right <= innerWidth + 1 && r.height >= 44; }),
          brandingProportions: [...page.querySelectorAll('.landing-logo, .landing-seal')].every(img => { const r = img.getBoundingClientRect(); return Math.abs(r.width / r.height - img.naturalWidth / img.naturalHeight) < .01 && Number(img.getAttribute('width')) === img.naturalWidth && Number(img.getAttribute('height')) === img.naturalHeight; }),
          twoLineHeadline: [...page.querySelectorAll('h1 span')].length === 2 && [...page.querySelectorAll('h1 span')].every(line => line.getBoundingClientRect().height <= parseFloat(getComputedStyle(line).lineHeight) + 1),
          identityGap: identity.top - hero.bottom,
          mapUnfiltered: pageStyle.filter === 'none' && pageStyle.backdropFilter === 'none' && pageStyle.opacity === '1',
          horizontalWash: pageStyle.backgroundImage.startsWith('linear-gradient(90deg'),
          apiRequests: window.__entryRequests.length };
      })()`);
      assert.equal(layout.width, width);
      assert.equal(layout.overflow, false);
      assert.ok(layout.public && layout.linksFit && layout.brandingProportions);
      assert.ok(layout.twoLineHeadline, `headline stays on two lines at ${width}px`);
      assert.ok(layout.identityGap >= 64, `municipal identity never overlaps the hero at ${width}x${height}`);
      assert.ok(layout.mapUnfiltered && layout.horizontalWash, "only a directional wash overlays the unfiltered map");
      assert.equal(layout.headingCount, 1);
      assert.ok(layout.ctaContrast >= 4.5 && layout.textContrast >= 4.5, `WCAG AA contrast at ${width}px ${theme}: ${JSON.stringify(layout)}`);
      assert.equal(layout.apiRequests, 0, "the anonymous landing page makes no API calls");
      results.push({ check: "responsive landing", width, height, theme, ...layout });
      if ([320, 393, 820, 900, 1440].includes(width)) await screenshot(`landing-${width}-${height}-${theme}`);
    }
  }
  console.log("Passed 24 desktop, tablet, phone, and short-screen layouts in light/dark themes; map, branding, contrast, spacing, and touch targets verified.");

  await viewport(1440, 900);
  await evaluate("localStorage.setItem('revela-theme', 'light')");
  await navigate("/", ".landing-page");
  await key("Tab", "Tab", 9);
  assert.equal(await evaluate("document.activeElement.className"), "landing-skip-link");
  assert.ok(await evaluate("document.activeElement.getBoundingClientRect().top >= 0 && getComputedStyle(document.activeElement).outlineStyle === 'solid'"));
  await key("Enter", "Enter", 13);
  assert.equal(await evaluate("document.activeElement.id"), "landing-main");
  await key("Tab", "Tab", 9);
  assert.ok(await evaluate("document.activeElement.matches('.landing-login--primary') && getComputedStyle(document.activeElement).outlineWidth === '3px'"));
  await key("Enter", "Enter", 13);
  await wait("location.pathname === '/login' && document.querySelector('.login-card input')", "keyboard login navigation");
  await screenshot("login-1440-light");
  results.push({ check: "keyboard skip link, visible focus, and login activation", passed: true });

  for (const cta of [".landing-login--secondary", ".landing-login--primary"]) {
    await navigate("/", ".landing-page");
    await evaluate("window.__routerSentinel = true");
    await click(cta);
    await wait("location.pathname === '/login' && document.querySelector('.login-card input')", cta);
    assert.equal(await evaluate("window.__routerSentinel"), true, "login uses client-side routing");
    await evaluate("history.back()");
    await wait("location.pathname === '/' && document.querySelector('.landing-page')", "browser back to landing");
  }

  await navigate("/", ".landing-page");
  await call("Page.bringToFront");
  await evaluate("document.querySelector('.landing-about-trigger').focus()");
  await key("Enter", "Enter", 13);
  await wait("document.querySelector('#landing-about:modal')", "About opens a native modal dialog");
  assert.ok(await evaluate("document.querySelector('#landing-about').contains(document.activeElement)"));
  assert.ok(await evaluate("document.querySelector('#landing-about').textContent.includes('Business Permits and Licensing Office')"));
  await evaluate("document.querySelector('.landing-login--primary').focus()");
  assert.ok(await evaluate("document.querySelector('#landing-about').contains(document.activeElement)"), "the modal makes background controls inert");
  await evaluate("document.querySelector('.landing-about-legal a:last-child').focus()");
  await key("Tab", "Tab", 9);
  // A native dialog may pass through browser chrome before cycling back, never the inert page.
  if (await evaluate("document.activeElement === document.body")) await key("Tab", "Tab", 9);
  assert.ok(await evaluate("document.querySelector('#landing-about').contains(document.activeElement)"), "Tab cycles back into About, not into the page");
  await screenshot("about-desktop");
  await key("Escape", "Escape", 27);
  assert.ok(await evaluate("!document.querySelector('#landing-about').open && document.activeElement.matches('.landing-about-trigger')"));
  await click(".landing-about-trigger");
  await click(".landing-about-close");
  assert.equal(await evaluate("document.querySelector('#landing-about').open"), false);
  await click(".landing-about-trigger");
  for (const type of ["mousePressed", "mouseReleased"]) await call("Input.dispatchMouseEvent", { type, x: 4, y: 4, button: "left", clickCount: 1 });
  assert.equal(await evaluate("document.querySelector('#landing-about').open"), false, "clicking outside closes About");
  await viewport(900, 420);
  await navigate("/", ".landing-page");
  await evaluate("window.scrollTo(0, document.documentElement.scrollHeight)");
  assert.ok(await evaluate("scrollY > 0"), "short screens scroll rather than clipping");
  await click('.landing-nav a[href="#landing-top"]');
  await wait("scrollY === 0", "Home returns to the top");
  await viewport(1440, 900);
  await call("Emulation.setEmulatedMedia", { features: [{ name: "prefers-reduced-motion", value: "reduce" }] });
  assert.equal(await evaluate("parseFloat(getComputedStyle(document.querySelector('.landing-login--primary svg')).transitionDuration)"), 0);
  await call("Emulation.setEmulatedMedia", { features: [] });
  results.push({ check: "meaningful About dialog, keyboard focus containment/restoration, Escape/close/backdrop dismissal, Home scroll, and reduced motion", passed: true });

  for (const path of ["/", "/login"]) {
    const selector = path === "/" ? ".landing-page" : ".login-card input";
    await navigate(path, selector);
    await call("Page.reload");
    await wait(`location.pathname === ${JSON.stringify(path)} && document.querySelector(${JSON.stringify(selector)})`, `${path} refresh`);
  }
  for (const path of ["/home", "/map", "/registry", "/analytics", "/inspections/calendar", "/inspections", "/users", "/reports", "/settings"]) {
    await call("Page.navigate", { url: `${origin}${path}` });
    await wait("location.pathname === '/login' && document.querySelector('.login-card input')", `protected ${path}`);
    assert.equal(await evaluate("Boolean(document.querySelector('.saas-root'))"), false);
  }
  results.push({ check: "both router CTAs, browser back, direct entry, refresh, and all nine unauthenticated protected routes", passed: true });

  await navigate("/login", ".login-card input");
  await fill('.login-card input[type="text"]', "admin@example.test");
  await fill('.login-card input[type="password"]', "incorrect");
  await click(".signin-btn");
  await wait("document.querySelector('.message-alert--error')?.textContent.includes('Invalid credentials')", "rejected login");
  assert.equal(await evaluate("localStorage.getItem('revela_token')"), null);
  await fill('.login-card input[type="text"]', "inspector@example.test");
  await fill('.login-card input[type="password"]', "browser-test-password");
  await click(".signin-btn");
  await wait("document.querySelector('.message-alert--error')?.textContent.includes('Access denied')", "non-admin rejected before storage");
  assert.equal(await evaluate("localStorage.getItem('revela_token')"), null);
  await fill('.login-card input[type="text"]', "admin@example.test");
  await click(".signin-btn");
  await wait("location.pathname === '/home' && document.querySelector('.saas-root')", "normal successful login");
  assert.equal(await evaluate("localStorage.getItem('revela_token')"), "entry-test-token");
  const payload = await evaluate("window.__entryRequests.find(r => r.path.endsWith('/auth/login')).body");
  assert.equal(payload.source, "web");
  assert.equal(payload.device_access.screenWidth, 1440);
  await call("Page.reload");
  await wait("location.pathname === '/home' && document.querySelector('.saas-root')", "authenticated refresh and profile hydration");
  await navigate("/", ".landing-page");
  assert.equal(await evaluate("localStorage.getItem('revela_token')"), "entry-test-token", "the public page preserves an active session");
  await navigate("/home", ".saas-root");
  await click(".logout-btn");
  await wait("document.querySelector('.swal2-confirm')?.textContent.includes('log out')", "logout confirmation");
  await click(".swal2-confirm");
  await wait("location.pathname === '/' && document.querySelector('.landing-page')", "existing root logout destination");
  assert.equal(await evaluate("localStorage.getItem('revela_token')"), null);
  assert.ok(await evaluate("window.__entryRequests.some(r => r.path.endsWith('/auth/logout'))"));
  results.push({ check: "invalid credentials, role gate, successful form login, session hydration, public page with session, and logout to root (mock API)", passed: true });

  for (const token of ["expired-entry-test-token", "inspector-entry-test-token"]) {
    await evaluate(`localStorage.setItem('revela_token', ${JSON.stringify(token)})`);
    await call("Page.navigate", { url: `${origin}/home` });
    await wait("location.pathname === '/login' && document.querySelector('.login-card input')", "invalid/forbidden session redirected");
    assert.equal(await evaluate("localStorage.getItem('revela_token')"), null);
  }
  await evaluate("localStorage.setItem('revela_token', 'expired-entry-test-token')");
  await navigate("/", ".landing-page");
  await wait("!localStorage.getItem('revela_token')", "expired session on the public page");
  assert.equal(await evaluate("location.pathname"), "/", "invalid sessions cannot redirect the public page");
  await click(".landing-login--primary");
  await wait("location.pathname === '/login' && document.querySelector('.message-alert--error')?.textContent.includes('session has expired')", "session notice preserved until login");
  await navigate("/login", ".login-card input");
  await fill('.login-card input[type="text"]', "2fa@example.test");
  await fill('.login-card input[type="password"]', "browser-test-password");
  await click(".signin-btn");
  await wait("document.querySelector('.form-heading')?.textContent === 'Two-Step Verification'", "2FA challenge");
  assert.equal(await evaluate("localStorage.getItem('revela_token')"), null);
  await fill('input[placeholder="e.g. 123456"]', "123456");
  await click(".signin-btn");
  await wait("location.pathname === '/home' && document.querySelector('.saas-root')", "2FA login redirect");
  await evaluate("localStorage.removeItem('revela_token')");
  await navigate("/login", ".login-card input");
  await click(".forgot-btn");
  await fill('input[placeholder="Email or phone number"]', "admin@example.test");
  await click(".otp-send-btn");
  await wait("document.querySelector('input[placeholder=\"e.g. 48291\"]')", "recovery OTP");
  await fill('input[placeholder="e.g. 48291"]', "12345");
  await click(".otp-send-btn");
  await fill('input[placeholder="Min. 8 characters"]', "browser-new-password");
  await fill('input[placeholder="Repeat new password"]', "browser-new-password");
  await click(".otp-send-btn");
  await wait("document.querySelector('.message-alert--success')?.textContent.includes('Password reset successful')", "password recovery success");
  results.push({ check: "expired/forbidden sessions, no public-route redirect loop, session notices, 2FA, and password recovery (mock API)", passed: true });

  await viewport(393, 852, true);
  await navigate("/", ".landing-page");
  await click(".landing-login--primary");
  await wait("location.pathname === '/login' && document.querySelector('.restricted-root')", "existing phone portal notice");
  await screenshot("login-phone-existing-device-policy");
  for (const path of ["/terms", "/privacy", "/cookies"]) {
    await navigate("/", ".landing-page");
    await click(".landing-about-trigger");
    await wait("document.querySelector('#landing-about:modal')", "mobile About");
    const dialogFits = await evaluate(`(() => {
      const dialog = document.querySelector('#landing-about').getBoundingClientRect();
      return dialog.left >= 0 && dialog.right <= innerWidth && dialog.top >= 0 && dialog.bottom <= innerHeight;
    })()`);
    assert.ok(dialogFits, "mobile About fits the viewport");
    if (path === "/terms") await screenshot("about-phone");
    await click(`.landing-about-legal a[href="${path}"]`);
    await wait(`location.pathname === ${JSON.stringify(path)} && document.querySelector('.legal-page-content h1')`, "public legal link");
  }
  await viewport(820, 1180, true);
  await navigate("/login", ".login-card input");
  assert.equal(await evaluate("document.documentElement.scrollWidth > innerWidth"), false);
  await screenshot("login-tablet-existing-form");
  results.push({ check: "existing phone portal policy, tablet login, and working public legal links on mobile", passed: true });

  assert.deepEqual(exceptions, [], "no uncaught browser exceptions");
  await writeFile(join(output, "results.json"), JSON.stringify({ browser: "Microsoft Edge, production build, synthetic API only", exceptions, results }, null, 2));
  await rm(join(output, "failure.png"), { force: true });
  console.log(`Passed ${results.length} scenario groups. Screenshots and results: ${output}`);
  await Promise.race([call("Browser.close").catch(() => {}), sleep(2000)]);
} catch (error) {
  if (call && session) {
    try { const { data } = await call("Page.captureScreenshot", { format: "png" }); await writeFile(join(output, "failure.png"), Buffer.from(data, "base64")); } catch { /* browser may have closed */ }
    try { console.error((await call("Runtime.evaluate", { expression: "JSON.stringify({ focus: document.activeElement?.tagName + '.' + document.activeElement?.className, documentFocused: document.hasFocus() })", returnByValue: true })).result?.value); } catch { /* browser may have closed */ }
  }
  if (exceptions.length) console.error("Browser exceptions:", exceptions);
  console.error(error);
  process.exitCode = 1;
} finally {
  socket?.close();
  if (browser && browser.exitCode === null) {
    await Promise.race([new Promise(resolve => browser.once("close", resolve)), sleep(2000)]);
    if (browser.exitCode === null) await new Promise(resolve => spawn("taskkill", ["/PID", String(browser.pid), "/T", "/F"], { windowsHide: true }).once("close", resolve));
  }
  server.httpServer.closeAllConnections();
  await new Promise(resolve => server.httpServer.close(resolve));
  await rm(profile, { recursive: true, force: true, maxRetries: 10, retryDelay: 300 });
}
