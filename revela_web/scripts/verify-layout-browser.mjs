import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { existsSync, mkdtempSync } from "node:fs";
import { rm, writeFile } from "node:fs/promises";
import { join, resolve } from "node:path";
import { createServer } from "vite";

const edge = process.env.EDGE_BINARY || "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe";
const tempRoot = process.env.OPENCODE_TEMP_ROOT || "C:\\Users\\Mateo\\AppData\\Local\\Temp\\opencode";
const focusedAnalytics = process.argv.includes("--analytics-fixes-only");
const clsOnly = process.argv.includes("--analytics-cls-only");
const output = focusedAnalytics || clsOnly ? tempRoot : resolve("artifacts/layout-review");
if (!existsSync(edge) || !existsSync(tempRoot) || !existsSync(output)) throw new Error("Edge, the approved temporary directory, and artifacts/layout-review are required.");
const profile = mkdtempSync(join(tempRoot, "revela-layout-browser-"));
const server = await createServer({ server: { host: "127.0.0.1", port: 0, open: false } });
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
const results = [];
const consoleIssues = [];
let browser;
let socket;
let call;
let session;

try {
  await server.listen();
  const origin = `http://127.0.0.1:${server.httpServer.address().port}`;
  const debuggerURL = await new Promise((resolve, reject) => {
    browser = spawn(edge, ["--headless", "--disable-gpu", "--no-first-run", "--no-default-browser-check", "--disable-background-networking", "--disable-component-update", "--disable-sync", "--no-proxy-server", "--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1, EXCLUDE localhost", `--user-data-dir=${profile}`, "--remote-debugging-port=0", "about:blank"], { windowsHide: true });
    let stderr = "";
    const timer = setTimeout(() => reject(new Error(`Edge startup timed out: ${stderr}`)), 20000);
    browser.stdout.resume();
    browser.stderr.on("data", chunk => {
      stderr += chunk;
      const url = stderr.match(/DevTools listening on (ws:\/\/[^\s]+)/)?.[1];
      if (url) { clearTimeout(timer); resolve(url); }
    });
    browser.on("error", reject);
  });
  socket = new WebSocket(debuggerURL);
  await new Promise((resolve, reject) => { socket.addEventListener("open", resolve); socket.addEventListener("error", reject); });
  let id = 0;
  const pending = new Map();
  const downloads = [];
  socket.addEventListener("message", event => {
    const message = JSON.parse(event.data);
    if (message.method === "Runtime.consoleAPICalled") {
      const text = message.params.args.map(arg => arg.value || arg.description || "").join(" ");
      if (/width\(%s\).*height\(%s\)|width\(-?\d+\).*height\(-?\d+\)|ResizeObserver loop/i.test(text)) consoleIssues.push(text);
    }
    if (message.method === "Runtime.exceptionThrown") consoleIssues.push(message.params.exceptionDetails.exception?.description || message.params.exceptionDetails.text);
    if (message.method === "Browser.downloadWillBegin") downloads.push(message.params.suggestedFilename);
    if (!message.id) return;
    const request = pending.get(message.id);
    pending.delete(message.id);
    clearTimeout(request?.timer);
    if (message.error) request?.reject(new Error(JSON.stringify(message.error)));
    else request?.resolve(message.result);
  });
  call = (method, params = {}, sessionId = session) => new Promise((resolve, reject) => {
    const requestID = ++id;
    const timer = setTimeout(() => { pending.delete(requestID); reject(new Error(`CDP timed out: ${method}`)); }, 30000);
    pending.set(requestID, { resolve, reject, timer });
    socket.send(JSON.stringify({ id: requestID, method, params, sessionId }));
  });
  const { targetId } = await call("Target.createTarget", { url: "about:blank" });
  session = (await call("Target.attachToTarget", { targetId, flatten: true })).sessionId;
  await call("Runtime.enable");
  await call("Page.enable");
  await call("Browser.setDownloadBehavior", { behavior: "allow", downloadPath: profile, eventsEnabled: true });
  const evaluate = async expression => {
    const response = await call("Runtime.evaluate", { expression, returnByValue: true, awaitPromise: true });
    if (response.exceptionDetails) throw new Error(response.exceptionDetails.exception?.description || response.exceptionDetails.text);
    return response.result?.value;
  };
  const wait = async (expression, label, timeout = 20000) => {
    const deadline = Date.now() + timeout;
    while (Date.now() < deadline) { if (await evaluate(`Boolean(${expression})`)) return; await sleep(50); }
    throw new Error(`Timed out: ${label}`);
  };
  const desktopUA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36";
  const androidUA = "Mozilla/5.0 (Linux; Android 14; SM-X200) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Mobile Safari/537.36";
  const ipadUA = "Mozilla/5.0 (iPad; CPU OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1";
  const metrics = async (width, height, userAgent = desktopUA, mobile = false) => {
    await call("Emulation.setDeviceMetricsOverride", { width, height, deviceScaleFactor: 1, mobile, screenWidth: width, screenHeight: height });
    await call("Emulation.setPageScaleFactor", { pageScaleFactor: 1 });
    await call("Emulation.setUserAgentOverride", { userAgent });
    await call("Emulation.setTouchEmulationEnabled", { enabled: mobile, maxTouchPoints: mobile ? 5 : 1 });
  };
  const navigate = async (page, state = "populated", sidebar = "expanded") => {
    await call("Page.navigate", { url: `${origin}/scripts/layout-preview.html?page=${page}&state=${state}&sidebar=${sidebar}` });
    await wait(`document.querySelector('${page === "access" ? ".login-card input, .restricted-root" : ".saas-content"}')`, "app shell");
    if (page !== "access") {
      const ready = state === "loading" ? (page === "analytics" ? ".analytics-loading-layout" : "#chart-card-size") : state === "error" ? (page === "analytics" ? ".analytics-section-state" : '[role="alert"]') : page === "analytics" ? ".analytics-feature-card" : "#chart-card-size";
      await wait(`document.querySelector('${ready}')`, `${page} ${state}`);
      if (state === "populated") await wait(`document.querySelectorAll('.responsive-chart svg.recharts-surface').length >= 2`, "all chart SVGs");
    }
    await sleep(350);
  };
  const scrollTo = async selector => {
    await evaluate(`(() => { const card = document.querySelector(${JSON.stringify(selector)}); const main = document.querySelector('.saas-content'); main.scrollTop += card.getBoundingClientRect().top - main.getBoundingClientRect().top - 16; })()`);
    await sleep(180);
  };
  const screenshot = async filename => {
    // Recharts animates some existing series for 1.5s. Capture their settled
    // presentation rather than an intermediate frame after a resize/tab mount.
    await sleep(1600);
    const { data } = await call("Page.captureScreenshot", { format: "png", fromSurface: true, captureBeyondViewport: false });
    await writeFile(join(output, filename), Buffer.from(data, "base64"));
  };
  const measure = async page => evaluate(`(() => {
    const bounds = element => { const r = element.getBoundingClientRect(); return { x: r.x, y: r.y, width: r.width, height: r.height, right: r.right, bottom: r.bottom }; };
    const cards = [...document.querySelectorAll(${JSON.stringify(page === "analytics" ? ".analytics-feature-card" : '.export-report-demographic-grid > [id^="chart-card-"]')})];
    return { zoom: visualViewport.scale, width: innerWidth, overflow: document.documentElement.scrollWidth > innerWidth,
      content: bounds(document.querySelector('.saas-content')), dock: document.querySelector('.analytics-tools') ? bounds(document.querySelector('.analytics-tools')) : null,
      cards: cards.map(card => ({ title: card.querySelector('h3').textContent, ...bounds(card),
        chart: card.querySelector('.responsive-chart') ? bounds(card.querySelector('.responsive-chart')) : null,
        overflow: card.scrollWidth > card.clientWidth + 1,
        titleWidth: card.querySelector('h3').getBoundingClientRect().width,
        axesInside: [...card.querySelectorAll('.wrapped-axis-tick text, .recharts-cartesian-axis-tick-value')].every(tick => {
          const r = tick.getBoundingClientRect(); const svg = tick.closest('svg').getBoundingClientRect();
          return r.left >= svg.left - 1 && r.right <= svg.right + 1 && r.top >= svg.top - 1 && r.bottom <= svg.bottom + 1;
        }),
        legendInside: [...card.querySelectorAll('.analytics-donut-legend, :scope > div:last-child')].every(legend => legend.getBoundingClientRect().right <= card.getBoundingClientRect().right + 1),
      })) };
  })()`);

  if (clsOnly) {
    await metrics(1280, 900);
    await call("Page.addScriptToEvaluateOnNewDocument", { source: `
      window.__analyticsShifts = [];
      new PerformanceObserver(list => {
        for (const entry of list.getEntries()) if (!entry.hadRecentInput) window.__analyticsShifts.push(entry.value);
      }).observe({ type: 'layout-shift', buffered: true });
    ` });
    await call("Page.navigate", { url: `${origin}/scripts/layout-preview.html?page=analytics&state=loading` });
    await wait(`document.querySelector('.analytics-overview-skeleton') && getComputedStyle(document.querySelector('.analytics-overview-skeleton')).visibility === 'visible'`, "delayed Overview skeleton");
    const before = await evaluate(`(() => {
      const bounds = selector => { const r = document.querySelector(selector).getBoundingClientRect(); return { width: r.width, height: r.height }; };
      return { map: bounds('.analytics-overview-skeleton .map-overview-layout'), kpi: bounds('.analytics-overview-skeleton .map-overview-total'), operations: bounds('.analytics-loading-section .analytics-inspector-operations-card') };
    })()`);
    await evaluate(`window.__releaseLayout()`);
    await wait(`document.querySelector('.map-overview-layout:not(.analytics-overview-skeleton .map-overview-layout)') && !document.querySelector('.analytics-loading-section')`, "loaded Overview");
    await sleep(600);
    const after = await evaluate(`(() => {
      const bounds = selector => { const r = document.querySelector(selector).getBoundingClientRect(); return { width: r.width, height: r.height }; };
      return { map: bounds('.map-overview:not(.analytics-overview-skeleton) .map-overview-layout'), kpi: bounds('.map-overview:not(.analytics-overview-skeleton) .map-overview-total'), operations: bounds('.analytics-inspector-operations-card'), cls: window.__analyticsShifts.reduce((sum, value) => sum + value, 0) };
    })()`);
    console.log(JSON.stringify({ before, after }, null, 2));
    assert.ok(after.cls < 0.1, `Overview CLS ${after.cls} must remain below 0.1`);
    await call("Page.navigate", { url: `${origin}/scripts/layout-preview.html?page=analytics&state=loading&tab=prescriptive&recommendations=ranked` });
    await wait(`document.querySelector('.analytics-recommendations-skeleton') && getComputedStyle(document.querySelector('.analytics-recommendations-skeleton')).visibility === 'visible'`, "delayed Recommendations skeleton");
    const recommendationsBefore = await evaluate(`(() => {
      const r = document.querySelector('.analytics-recommendations-skeleton').getBoundingClientRect();
      return { width: r.width, height: r.height };
    })()`);
    await evaluate(`window.__releaseLayout()`);
    await wait(`document.querySelectorAll('.analytics-recommendation-row summary').length === 5`, "five ranked rows");
    await sleep(400);
    const recommendationsAfter = await evaluate(`(() => {
      const r = document.querySelector('.analytics-recommendation-list').getBoundingClientRect();
      return { width: r.width, height: r.height, cls: window.__analyticsShifts.reduce((sum, value) => sum + value, 0) };
    })()`);
    console.log(JSON.stringify({ recommendationsBefore, recommendationsAfter }, null, 2));
    assert.ok(recommendationsAfter.cls < 0.1, `Recommendations CLS ${recommendationsAfter.cls} must remain below 0.1`);
    await evaluate(`document.querySelector('.analytics-tab-btn').click()`);
    await wait(`document.querySelector('.map-overview-layout')`, "cached Overview tab");
    assert.equal(await evaluate(`Boolean(document.querySelector('.analytics-loading-section'))`), false, "cached tab switch must not show a page skeleton");
    await evaluate(`document.querySelectorAll('.analytics-tab-btn')[1].click()`);
    await wait(`document.querySelector('.analytics-recommendation-rows')`, "cached Recommendations tab");
    assert.equal(await evaluate(`Boolean(document.querySelector('.analytics-recommendations-skeleton'))`), false, "returning to a cached tab must not re-skeleton");
    results.push({ page: "Overview", before, after }, { page: "Recommendations", before: recommendationsBefore, after: recommendationsAfter });
    await metrics(768, 1024, ipadUA, true);
    await call("Page.navigate", { url: `${origin}/scripts/layout-preview.html?page=analytics&state=loading` });
    await wait(`document.querySelector('.analytics-overview-skeleton') && getComputedStyle(document.querySelector('.analytics-overview-skeleton')).visibility === 'visible'`, "tablet Overview skeleton");
    await evaluate(`window.__releaseLayout()`);
    await wait(`document.querySelector('.map-overview:not(.analytics-overview-skeleton) .map-overview-layout')`, "tablet Overview loaded");
    await sleep(400);
    const tabletCls = await evaluate(`window.__analyticsShifts.reduce((sum, value) => sum + value, 0)`);
    assert.ok(tabletCls < 0.1, `tablet Overview CLS ${tabletCls} must remain below 0.1`);
    results.push({ page: "Overview tablet", cls: tabletCls });
  } else if (focusedAnalytics) {
    for (const [width, height] of [[1920, 1080], [1280, 900], [1024, 900]]) {
      for (const sidebar of ["expanded", "collapsed"]) {
        await metrics(width, height);
        await navigate("analytics", "populated", sidebar);
        const ui = await evaluate(`(() => {
          const nav = document.querySelector('.analytics-section-nav');
          const r = nav.getBoundingClientRect();
          const filters = [...document.querySelectorAll('.saas-card')].find(card => card.querySelector('h3')?.textContent.includes('Data filters'));
          const section = [...document.querySelectorAll('h2')].find(node => node.textContent === 'Descriptive Analytics');
          const grid = document.querySelector('.analytics-census-grid');
          const cards = [...grid.children];
          return {
            navCount: document.querySelectorAll('nav[aria-label="Analytics sections"]').length,
            floatingNavVisibleAtTop: Boolean(document.querySelector('.analytics-quick-nav')),
            inFlow: getComputedStyle(nav).position === 'relative' || getComputedStyle(nav).position === 'static',
            order: filters.getBoundingClientRect().bottom <= r.top && r.bottom < section.getBoundingClientRect().top,
            subtitles: [...nav.querySelectorAll('.analytics-tab-subtitle')].map(node => node.textContent),
            navFits: [...nav.querySelectorAll('button')].every(node => { const b = node.getBoundingClientRect(); return b.left >= r.left && b.right <= r.right && b.top >= r.top && b.bottom <= r.bottom; }),
            columns: getComputedStyle(grid).gridTemplateColumns.split(' ').length,
            contentWidth: grid.getBoundingClientRect().width,
            cardCount: cards.length,
            iconVariants: cards.map(card => card.querySelector('.kpi-icon').className),
            iconsFit: cards.every(card => { const icon = card.querySelector('.kpi-icon').getBoundingClientRect(); const info = card.querySelector('.kpi-info').getBoundingClientRect(); return icon.width === 32 && icon.height === 32 && icon.right <= info.left && card.scrollWidth <= card.clientWidth + 1; }),
            compact: cards.every(card => card.getBoundingClientRect().height <= 72),
            colors: cards.map(card => getComputedStyle(card.querySelector('.kpi-icon')).color),
            backgrounds: cards.map(card => getComputedStyle(card.querySelector('.kpi-icon')).backgroundColor),
            overflow: document.documentElement.scrollWidth > innerWidth,
          };
        })()`);
        assert.equal(ui.navCount, 1);
        assert.equal(ui.floatingNavVisibleAtTop, false);
        assert.ok(ui.inFlow && ui.order && ui.navFits, "rectangular tabs fit between filters and active section");
        assert.deepEqual(ui.subtitles, ["What is happening?", "Why is it happening?", "What should we do?", "Inspector performance"]);
        assert.equal(ui.cardCount, 8);
        assert.equal(ui.columns, ui.contentWidth > 859 ? 4 : 2);
        assert.deepEqual(ui.iconVariants, ["gold", "green", "plain", "gold", "green", "red", "gold", "red"].map(variant => `kpi-icon kpi-icon--${variant}`));
        assert.deepEqual(ui.colors, ["rgb(202, 138, 4)", "rgb(86, 171, 47)", "rgb(26, 32, 44)", "rgb(202, 138, 4)", "rgb(86, 171, 47)", "rgb(239, 68, 68)", "rgb(202, 138, 4)", "rgb(239, 68, 68)"]);
        assert.ok(ui.iconsFit && ui.compact, "all compact cards have aligned left-side icons");
        assert.equal(ui.backgrounds[2], "rgba(0, 0, 0, 0)", "outlined star has no colored container");
        assert.equal(ui.overflow, false);
        const data = await measure("analytics");
        assert.ok(data.cards.every(card => !card.overflow && card.chart?.width > 0), "existing charts keep their dimensions");
        await screenshot(`revela-analytics-fixes-${width}-${sidebar}.png`);
        await scrollTo(".analytics-census-grid");
        await wait(`document.querySelector('.analytics-quick-nav')`, "floating navigation after main tabs leave view");
        const dock = await evaluate(`(() => {
          const bounds = element => { const r = element.getBoundingClientRect(); return { left: r.left, right: r.right, top: r.top, bottom: r.bottom, width: r.width }; };
          const main = bounds(document.querySelector('.saas-main'));
          const nav = bounds(document.querySelector('.analytics-quick-nav'));
          return { main, nav, active: document.querySelector('.analytics-quick-nav-btn.active')?.textContent.trim() };
        })()`);
        assert.ok(dock.nav.left >= dock.main.left && dock.nav.right <= dock.main.right, "floating navigation remains centered in content area");
        assert.ok(Math.abs((dock.nav.left + dock.nav.right) / 2 - (dock.main.left + dock.main.right) / 2) < 2, "floating navigation is bottom-center in content area");
        await evaluate(`[...document.querySelectorAll('.analytics-quick-nav-btn')].find(button => button.textContent.includes('Operations')).click()`);
        assert.equal(await evaluate(`document.querySelector('.analytics-tab-btn[aria-current="page"]')?.textContent.includes('Operations')`), true, "floating tab updates the main tab");
        assert.equal(await evaluate(`document.querySelector('.analytics-quick-nav-btn.active')?.textContent.trim()`), "Operations", "main and floating tab states stay synchronized");
        await evaluate(`document.querySelector('.saas-content').scrollTop = 0`);
        await wait(`!document.querySelector('.analytics-quick-nav')`, "floating navigation hides when main tabs return");
        await screenshot(`revela-analytics-census-${width}-${sidebar}.png`);
        await evaluate(`document.querySelector('[aria-label="Open AI Analyst"]').click()`);
        assert.ok(await evaluate(`(() => { const main = document.querySelector('.saas-main').getBoundingClientRect(); const panel = document.querySelector('.analytics-assistant-panel').getBoundingClientRect(); return panel.left >= main.left && panel.right <= main.right && panel.bottom <= main.bottom; })()`), "chat panel stays inside the content area");
        await evaluate(`document.querySelector('[aria-label="Close AI Analyst"]').click(); document.querySelector('.sidebar-collapse-toggle').click()`);
        assert.ok(await evaluate(`Boolean(document.querySelector('[aria-label="Open AI Analyst"]'))`), "closing chat restores the standalone mascot");
        await sleep(350);
        assert.equal(await evaluate(`document.documentElement.scrollWidth > innerWidth`), false, "live sidebar toggle does not overflow");
        results.push({ width, height, sidebar, ...ui });
        console.log(`Analytics restoration passed: ${width} × ${height}, ${sidebar} sidebar, ${ui.columns} census columns`);
      }
    }
  } else {
  for (const [width, height] of (process.argv.includes("--details-only") ? [] : [[768, 1024], [1024, 768], [1280, 800], [1440, 1000]])) {
    for (const page of ["analytics", "reports"]) {
      for (const sidebar of ["expanded", "collapsed"]) {
        await metrics(width, height, width <= 1024 ? ipadUA : desktopUA, width <= 1024);
        await navigate(page, "populated", sidebar);
        const data = await measure(page);
        assert.equal(data.zoom, 1, "100% viewport scale");
        assert.equal(data.width, width, "unzoomed CSS viewport width");
        assert.equal(data.overflow, false, "no page-level horizontal overflow");
        assert.equal(data.cards.length, page === "analytics" ? 2 : 7, "all demographic cards rendered");
        for (const card of data.cards) {
          assert.ok(card.width >= 340, `${page} ${width} ${sidebar}: ${card.title} has usable width`);
          assert.ok(card.chart?.width > 0 && card.chart?.height > 0, `${card.title} positive chart dimensions`);
          assert.ok(card.chart.x >= card.x && card.chart.right <= card.right + 1, `${card.title} entire chart fits card width`);
          assert.equal(card.overflow, false, `${card.title} content fits card`);
          assert.ok(card.legendInside, `${card.title} legend inside card`);
          assert.ok(card.axesInside, `${page} ${width} ${sidebar}: ${card.title} axes inside chart`);
          if (page === "reports") assert.ok(card.titleWidth >= 240, `${card.title} title not squeezed`);
        }
        if (page === "analytics") {
          assert.ok(Math.abs(data.cards[0].width - data.cards[1].width) < 1, "registry and inspection charts share full width");
          assert.ok(data.cards[1].y > data.cards[0].y, "the two Descriptive charts stack vertically");
          assert.ok(data.cards[0].height > 300 && data.cards[1].height > 300, "stacked charts keep usable height");
          assert.ok(data.content.bottom <= data.dock.y + 1, "dock reserves space outside scroll content");
        }
        results.push({ page, width, height, sidebar, ...data });
        console.log(`Layout passed: ${page} ${width} × ${height}, ${sidebar} sidebar`);
        if (width === 768) {
          await evaluate(`document.querySelector('.mobile-toggle').click()`);
          await wait(`document.querySelector('.saas-root.mobile-open')`, "tablet navigation drawer");
          await evaluate(`document.querySelector('.mobile-toggle').click()`);
        } else {
          await evaluate(`document.querySelector('.sidebar-collapse-toggle').click()`);
          await sleep(300);
          const toggled = await measure(page);
          assert.ok(toggled.cards.every(card => card.chart?.width > 0 && !card.overflow), "charts resize after live sidebar toggle");
          await evaluate(`document.querySelector('.sidebar-collapse-toggle').click()`);
          await sleep(300);
        }
        if (sidebar === "expanded" || width === 1440) {
          await scrollTo(page === "analytics" ? ".analytics-feature-card--registry-status" : "#chart-card-size");
          await screenshot(`${page}-${width}-${sidebar}.png`);
          if (page === "analytics" && width >= 1280) {
            await scrollTo(".analytics-feature-card--inspection-status");
            await screenshot(`${page}-${width}-${sidebar}-inspection.png`);
          }
        }
      }
    }
  }

  // Exercise the stacked-chart tooltip, tab remounting, the two-chart
  // Descriptive layout, and the assistant drawer while charts stay in their
  // own scroll area.
  await metrics(1280, 800);
  console.log("Checking tooltips, tabs, assistant, and resize");
  await navigate("analytics");
  await scrollTo(".analytics-feature-card--registry-status");
  const bar = await evaluate(`(() => { const r = document.querySelector('.analytics-feature-card--registry-status .recharts-bar-rectangle').getBoundingClientRect(); return { x: r.x + r.width / 2, y: r.y + r.height / 2 }; })()`);
  await call("Input.dispatchMouseEvent", { type: "mouseMoved", ...bar });
  await wait(`document.querySelector('.analytics-feature-card--registry-status .analytics-stacked-tooltip')?.textContent.includes('Barangay I')`, "registry stacked tooltip");
  assert.equal(await evaluate(`(() => { const card = document.querySelector('.analytics-feature-card--registry-status').getBoundingClientRect(); const tip = document.querySelector('.analytics-feature-card--registry-status .analytics-stacked-tooltip').getBoundingClientRect(); return tip.left >= card.left && tip.right <= card.right && tip.top >= card.top && tip.bottom <= card.bottom; })()`), true, "stacked tooltip fits card");
  await screenshot("analytics-registry-stacked-tooltip.png");
  await call("Input.dispatchMouseEvent", { type: "mouseMoved", x: 5, y: 5 });
  await evaluate(`[...document.querySelectorAll('.analytics-tab-btn')].find(button => button.textContent.includes('Operations')).click()`);
  await wait(`document.body.textContent.includes('Inspection Activity Timeline')`, "operations tab");
  await evaluate(`document.querySelector('.analytics-tab-btn').click()`);
  await wait(`document.querySelectorAll('.analytics-feature-card .responsive-chart .recharts-wrapper').length === 2`, "descriptive tab remount");
  await evaluate(`document.querySelector('[aria-label="Open AI Analyst"]').click()`);
  assert.equal(await evaluate(`document.querySelector('.saas-content').getBoundingClientRect().bottom <= document.querySelector('.analytics-tools').getBoundingClientRect().top + 1`), true, "expanded assistant never overlays charts");
  await evaluate(`document.querySelector('[aria-label="Close AI Analyst"]').click()`);
  await metrics(1920, 1080);
  await scrollTo(".analytics-feature-card--registry-status");
  const wide = await measure("analytics");
  assert.ok(wide.cards[0].chart.height > 500 && wide.cards[0].axesInside, "roomy registry chart keeps all barangay rows legible inside its scroll area");
  await screenshot("analytics-wide-registry-chart.png");
  await metrics(1200, 800);
  await scrollTo(".analytics-feature-card--inspection-status");
  await screenshot("analytics-narrow-stacked-charts.png");
  results.push({ checks: "stacked tooltip, tab remount, assistant space, narrow stacked charts, live resize" });

  for (const [width, height] of [[768, 1024], [1024, 768], [1280, 800], [1440, 1000]]) {
    await metrics(width, height);
    for (const page of ["analytics", "reports"]) {
      for (const state of ["loading", "empty", "error"]) {
        await navigate(page, state);
        if (state === "loading" && page === "analytics") await scrollTo(".analytics-skeleton-charts");
        else if (page === "reports") await scrollTo("#chart-card-size");
        else if (state === "empty") await scrollTo(".analytics-feature-card--registry-status");
        assert.equal(await evaluate(`document.documentElement.scrollWidth > innerWidth`), false, `${state} no horizontal overflow`);
        if (width === 768 || width === 1440) await screenshot(`${page}-${width}-${state}.png`);
        if (state === "loading") {
          await evaluate(`window.__releaseLayout()`);
          await wait(`document.querySelectorAll('.responsive-chart svg.recharts-surface').length >= 2`, "charts mount after loading");
        }
        results.push({ page, width, state, passed: true });
        console.log(`State passed: ${page} ${width} ${state}`);
      }
    }
  }

  // Real image capture and PDF/print preparation, retaining the app handlers.
  await metrics(1024, 768);
  console.log("Checking PNG and PDF exports");
  await navigate("reports");
  await scrollTo("#chart-card-size");
  await evaluate(`document.querySelector('#chart-card-size .export-actions-menu > summary').click(); document.querySelector('#chart-card-size button[title*="PNG"]').click()`);
  await wait(`document.body.textContent.includes('Chart Exported!') || document.body.textContent.includes('Export Failed')`, "PNG export", 30000);
  assert.equal(await evaluate(`document.body.textContent.includes('Chart Exported!')`), true, "PNG capture succeeds");
  await sleep(200);
  assert.ok(downloads.some(filename => filename.endsWith(".png")), "PNG download starts");
  await evaluate(`document.querySelector('.swal2-container')?.remove(); document.body.classList.remove('swal2-shown', 'swal2-height-auto'); document.querySelector('#chart-card-size .export-actions-menu > summary').click(); document.querySelector('#chart-card-size button[title*="PDF"]').click()`);
  await wait(`window.__printCount > 0`, "PDF print flow", 30000);
  assert.ok(await evaluate(`Boolean(document.querySelector('.print-report-container img[src^="data:image/png"]'))`), "PDF includes chart image");
  await call("Emulation.setEmulatedMedia", { media: "print" });
  await screenshot("reports-print-preview.png");
  await call("Emulation.setEmulatedMedia", { media: "screen" });
  results.push({ checks: "actual PNG download and official PDF/print chart preparation" });

  for (const [label, ua, width, height, expected] of [
    ["Android tablet portrait", androidUA, 768, 1024, true],
    ["Android tablet landscape", androidUA, 1024, 768, true],
    ["iPad Safari", ipadUA, 768, 1024, true],
    ["iPadOS Macintosh Mobile", "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1", 1024, 768, true],
    ["iPhone", "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 Mobile/15E148 Safari/604.1", 393, 852, false],
    ["Android phone", androidUA.replace("SM-X200", "Pixel 8"), 412, 915, false],
  ]) {
    await metrics(width, height, ua, true);
    await navigate("access");
    const login = await evaluate(`Boolean(document.querySelector('.login-card input'))`);
    assert.equal(login, expected, `${label} ${expected ? "reaches normal login" : "is restricted"}`);
    if (label === "Android tablet portrait") {
      await screenshot("tablet-normal-login.png");
      await evaluate(`(async () => { const { loginRequest } = await import('/src/services/api.js'); try { await loginRequest('preview@example.com', 'incorrect'); } catch { /* expected synthetic 401 */ } })()`);
      const body = await evaluate(`window.__loginPayload`);
      assert.equal(body.source, "web", "tablet uses the normal web authentication flow");
      assert.deepEqual(body.device_access, { screenWidth: width, screenHeight: height, maxTouchPoints: 5 }, "tablet hints accompany credential validation");
    }
    results.push({ device: label, width, height, normalLogin: login });
  }

  }
  assert.deepEqual(consoleIssues, [], "no Recharts dimension warnings or browser exceptions");
  await writeFile(join(output, clsOnly ? "analytics-cls-results.json" : focusedAnalytics ? "revela-analytics-fixes-results.json" : "results.json"), JSON.stringify({ zoom: "100%", browser: "Microsoft Edge (Chromium), fresh profile", consoleIssues, results }, null, 2));
  await rm(join(output, focusedAnalytics ? "revela-analytics-fixes-failure.png" : "failure.png"), { force: true });
  console.log(`Passed ${results.length} ${clsOnly ? "analytics CLS and cached-tab" : "layout/state/device"} scenarios at 100% zoom. Results: ${output}`);
  await Promise.race([call("Browser.close").catch(() => {}), sleep(2000)]);
} catch (error) {
  if (call && session) {
    try { const { data } = await call("Page.captureScreenshot", { format: "png" }); await writeFile(join(output, focusedAnalytics ? "revela-analytics-fixes-failure.png" : "failure.png"), Buffer.from(data, "base64")); } catch { /* browser may have closed */ }
  }
  console.error(error);
  if (consoleIssues.length) console.error(consoleIssues);
  process.exitCode = 1;
} finally {
  socket?.close();
  if (browser && browser.exitCode === null) {
    await Promise.race([new Promise(resolve => browser.once("close", resolve)), sleep(2000)]);
    if (browser.exitCode === null) await new Promise(resolve => spawn("taskkill", ["/PID", String(browser.pid), "/T", "/F"], { windowsHide: true }).once("close", resolve));
  }
  await server.close();
  await sleep(300);
  await rm(profile, { recursive: true, force: true, maxRetries: 10, retryDelay: 300 });
}
