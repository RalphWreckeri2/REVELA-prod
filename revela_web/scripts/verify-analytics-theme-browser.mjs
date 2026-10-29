import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { mkdtempSync } from "node:fs";
import { rm } from "node:fs/promises";
import { join } from "node:path";
import { createServer } from "vite";

const edge = process.env.EDGE_BINARY || "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe";
const profile = mkdtempSync(join("C:\\Users\\Mateo\\AppData\\Local\\Temp\\opencode", "analytics-theme-"));
const server = await createServer({ logLevel: "silent", server: { host: "127.0.0.1", port: 0 } });
let browser;
let socket;
try {
  await server.listen();
  const origin = `http://127.0.0.1:${server.httpServer.address().port}`;
  const debuggerUrl = await new Promise((resolve, reject) => {
    browser = spawn(edge, ["--headless", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
      "--disable-background-networking", "--no-proxy-server",
      "--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1, EXCLUDE localhost",
      `--user-data-dir=${profile}`, "--remote-debugging-port=0", "about:blank"], { windowsHide: true });
    const timer = setTimeout(() => reject(new Error("Edge startup timed out")), 20000);
    browser.stdout.resume();
    browser.stderr.on("data", chunk => {
      const url = String(chunk).match(/DevTools listening on (ws:\/\/[^\s]+)/)?.[1];
      if (url) { clearTimeout(timer); resolve(url); }
    });
    browser.on("error", reject);
  });
  socket = new WebSocket(debuggerUrl);
  await new Promise((resolve, reject) => {
    socket.addEventListener("open", resolve, { once: true });
    socket.addEventListener("error", reject, { once: true });
  });
  let nextId = 0;
  let sessionId;
  const pending = new Map();
  socket.addEventListener("message", event => {
    const message = JSON.parse(event.data);
    if (!message.id) return;
    const request = pending.get(message.id);
    if (!request) return;
    pending.delete(message.id);
    clearTimeout(request.timer);
    if (message.error) request.reject(new Error(JSON.stringify(message.error)));
    else request.resolve(message.result);
  });
  const call = (method, params = {}, session = sessionId) => new Promise((resolve, reject) => {
    const id = ++nextId;
    const timer = setTimeout(() => { pending.delete(id); reject(new Error(`CDP timed out: ${method}`)); }, 30000);
    pending.set(id, { resolve, reject, timer });
    socket.send(JSON.stringify({ id, method, params, sessionId: session }));
  });
  const { targetId } = await call("Target.createTarget", { url: "about:blank" });
  sessionId = (await call("Target.attachToTarget", { targetId, flatten: true })).sessionId;
  await call("Page.enable");
  await call("Runtime.enable");
  await call("Emulation.setDeviceMetricsOverride", { width: 1440, height: 900, deviceScaleFactor: 1, mobile: false, screenWidth: 1440, screenHeight: 900 });
  await call("Emulation.setUserAgentOverride", { userAgent: "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36" });
  const evaluate = async expression => {
    const result = await call("Runtime.evaluate", { expression, returnByValue: true, awaitPromise: true });
    if (result.exceptionDetails) throw new Error(result.exceptionDetails.text);
    return result.result.value;
  };
  const waitFor = async expression => {
    const deadline = Date.now() + 20000;
    while (Date.now() < deadline) {
      if (await evaluate(`Boolean(${expression})`)) return;
      await new Promise(resolve => setTimeout(resolve, 80));
    }
    throw new Error(`Timed out waiting for ${expression}`);
  };
  const inspect = async () => evaluate(`(() => {
    const style = selector => {
      const element = document.querySelector(selector);
      if (!element) return null;
      const computed = getComputedStyle(element);
      return { background: computed.backgroundColor, color: computed.color, fill: computed.fill,
        border: computed.borderTopColor, width: element.getBoundingClientRect().width };
    };
    return {
      dark: document.documentElement.classList.contains('theme-dark'),
      kpi: style('.kpi-card'), kpiLabel: style('.kpi-card .kpi-info p'),
      filter: style('.map-overview-filter-card'), select: style('.map-overview select'),
      mapCard: style('.map-overview-layout'), mapControl: style('.map-overview-legend-toggle'),
      chartCard: style('.analytics-inspector-operations-card'),
      axis: style('.analytics-inspector-operations-card .recharts-cartesian-axis-tick-value'),
      grid: document.querySelector('.analytics-inspector-operations-card .recharts-cartesian-grid line')?.getAttribute('stroke'),
      overflow: document.documentElement.scrollWidth > innerWidth,
    };
  })()`);

  for (const theme of ["light", "dark"]) {
    await call("Page.navigate", { url: `${origin}/scripts/layout-preview.html?page=analytics&theme=${theme}` });
    try {
      await waitFor("document.querySelector('.map-overview-layout') && document.querySelector('.analytics-inspector-operations-card .recharts-cartesian-axis-tick-value')");
    } catch (error) {
      console.error(await evaluate(`({ text: document.body.innerText.slice(0, 1200), map: Boolean(document.querySelector('.map-overview-layout')), chart: Boolean(document.querySelector('.analytics-inspector-operations-card')), rows: document.querySelectorAll('.analytics-inspector-operations-card .recharts-cartesian-axis-tick-value').length })`));
      throw error;
    }
    await evaluate(`(() => { const sample = document.createElement('div'); sample.className = 'kpi-card frosted-glass saas-card';
      sample.innerHTML = '<div class="kpi-info"><h3>42</h3><p>Sample KPI</p></div>';
      document.querySelector('.saas-content').append(sample); })()`);
    await evaluate(`document.querySelector('.analytics-tab-btn[aria-current="page"]').click()`);
    const page = await inspect();
    assert.equal(page.dark, theme === "dark");
    assert.equal(page.overflow, false);
    for (const key of ["kpi", "kpiLabel", "filter", "select", "mapCard", "mapControl", "chartCard", "axis"]) {
      assert.ok(page[key], `${theme}: ${key} rendered`);
    }
    assert.ok(page.grid?.includes("--analytics-grid-color"), `${theme}: chart uses theme grid token`);
    if (theme === "dark") {
      for (const key of ["kpi", "filter", "select", "mapCard", "mapControl", "chartCard"]) {
        assert.match(page[key].background, /rgb\((?:13|20), (?:13|20), (?:13|20)\)/, `${key} is dark`);
      }
      assert.equal(page.kpiLabel.color, "rgb(203, 213, 225)");
      assert.equal(page.axis.fill, "rgb(203, 213, 225)");
    } else {
      for (const key of ["filter", "mapCard", "chartCard"]) {
        assert.match(page[key].background, /rgb\(25[0-5], 25[0-5], 25[0-5]\)/, `${key} stays light`);
      }
    }
    await evaluate(`document.querySelectorAll('.map-overview-segmented button')[1].click()`);
    const selected = await evaluate(`(() => { const button = document.querySelector('.map-overview-segmented button.active');
      return { background: getComputedStyle(button).backgroundColor, color: getComputedStyle(button).color }; })()`);
    assert.equal(selected.color, theme === "dark" ? "rgb(191, 219, 254)" : "rgb(29, 78, 216)");
    assert.notEqual(selected.background, page.select.background, "selected map tab is distinct from the input surface");
    const position = await evaluate(`(() => { const chart = document.querySelector('.analytics-inspector-operations-card');
      chart.scrollIntoView(); const r = chart.querySelector('.recharts-bar-rectangle').getBoundingClientRect();
      return { x: r.x + r.width / 2, y: r.y + r.height / 2 }; })()`);
    await call("Input.dispatchMouseEvent", { type: "mouseMoved", ...position });
    await waitFor("document.querySelector('.analytics-inspector-operations-card .analytics-chart-tooltip')");
    assert.equal(await evaluate(`getComputedStyle(document.querySelector('.analytics-inspector-operations-card .analytics-chart-tooltip')).color`), "rgb(255, 255, 255)");
    await evaluate(`document.querySelector('.analytics-filter-smoke-trigger').click()`);
    await waitFor("document.querySelector('.analytics-filter-modal select')");
    const modal = await evaluate(`(() => { const panel = document.querySelector('.analytics-filter-modal');
      const select = panel.querySelector('select'); const label = panel.querySelector('label');
      return { background: getComputedStyle(panel).backgroundColor,
        text: getComputedStyle(label).color, input: getComputedStyle(select).backgroundColor }; })()`);
    assert.equal(modal.background, theme === "dark" ? "rgb(13, 13, 13)" : "rgb(255, 255, 255)");
    assert.equal(modal.text, theme === "dark" ? "rgb(203, 213, 225)" : "rgb(100, 116, 139)");
    assert.equal(modal.input, theme === "dark" ? "rgb(20, 20, 20)" : "rgb(248, 250, 252)");
    console.log(`Analytics ${theme} theme: map panel, chart, controls, and filter dialog passed`);
  }
  await call("Browser.close").catch(() => {});
} finally {
  socket?.close();
  browser?.kill();
  await server.close();
  if (browser && browser.exitCode == null) await new Promise(resolve => browser.once("exit", resolve));
  await rm(profile, { recursive: true, force: true, maxRetries: 6, retryDelay: 200 });
}
