import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { existsSync, mkdtempSync } from "node:fs";
import { mkdir, rm, writeFile } from "node:fs/promises";
import { join } from "node:path";
import { createServer } from "vite";

const edge = process.env.EDGE_BINARY || "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe";
const tempRoot = process.env.LOCALAPPDATA && join(process.env.LOCALAPPDATA, "Temp", "opencode");
assert.ok(existsSync(edge) && tempRoot && existsSync(tempRoot));
const profile = mkdtempSync(join(tempRoot, "revela-landing-sections-"));
const captures = join(tempRoot, "revela-support-route-review");
await mkdir(captures, { recursive: true });
const server = await createServer({ server: { host: "127.0.0.1", port: 0, open: false } });
await server.listen();
let browser;
let socket;
try {
  const debuggerURL = await new Promise((resolve, reject) => {
    browser = spawn(edge, ["--headless", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
      "--disable-background-networking", "--no-proxy-server", `--user-data-dir=${profile}`,
      "--window-size=1600,1000", "--remote-debugging-port=0", "about:blank"], { windowsHide: true });
    browser.stdout.resume();
    browser.stderr.on("data", chunk => {
      const match = chunk.toString().match(/DevTools listening on (ws:\/\/[^\s]+)/);
      if (match) resolve(match[1]);
    });
    browser.on("error", reject);
    setTimeout(() => reject(new Error("Browser startup timed out")), 20000);
  });
  socket = new WebSocket(debuggerURL);
  await new Promise(resolve => socket.addEventListener("open", resolve, { once: true }));
  let id = 0;
  let session;
  const pending = new Map();
  socket.addEventListener("message", event => {
    const response = JSON.parse(event.data);
    const request = pending.get(response.id);
    if (!request) return;
    pending.delete(response.id);
    if (response.error) request.reject(new Error(JSON.stringify(response.error)));
    else request.resolve(response.result);
  });
  const call = (method, params = {}) => new Promise((resolve, reject) => {
    const requestID = ++id;
    pending.set(requestID, { resolve, reject });
    socket.send(JSON.stringify({ id: requestID, method, params, sessionId: session }));
  });
  const { targetId } = await call("Target.createTarget", { url: "about:blank" });
  session = (await call("Target.attachToTarget", { targetId, flatten: true })).sessionId;
  await call("Runtime.enable");
  socket.addEventListener("message", event => {
    const message = JSON.parse(event.data);
    if (message.method === "Runtime.consoleAPICalled" && message.params.type === "error") console.error(message.params.args.map(arg => arg.value || arg.description));
    if (message.method === "Runtime.exceptionThrown") console.error(message.params.exceptionDetails.exception?.description);
  });
  await call("Page.enable");
  const evaluate = async expression => {
    const result = await call("Runtime.evaluate", { expression, returnByValue: true, awaitPromise: true });
    if (result.exceptionDetails) throw new Error(result.exceptionDetails.exception?.description || result.exceptionDetails.text);
    return result.result.value;
  };
  for (const [label, width, height, mobile] of [
    ["desktop 100%", 1440, 900, false], ["desktop 125%", 1152, 720, false],
    ["tablet 100%", 768, 1024, true], ["tablet 125%", 614, 819, true],
    ["narrow 100%", 620, 900, false], ["narrow 125%", 560, 720, false],
    ["short screen", 900, 650, false],
  ]) {
    await call("Emulation.setDeviceMetricsOverride", { width, height, deviceScaleFactor: 1, mobile,
      screenWidth: width, screenHeight: height });
    await call("Emulation.setUserAgentOverride", { userAgent: mobile
      ? "Mozilla/5.0 (iPad; CPU OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
      : "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36" });
    await call("Page.navigate", { url: `http://127.0.0.1:${server.httpServer.address().port}/` });
    await new Promise(resolve => setTimeout(resolve, 600));
    for (let retry = 0; retry < 100; retry += 1) {
      if (await evaluate("Boolean(document.querySelector('.landing-page'))")) break;
      await new Promise(resolve => setTimeout(resolve, 100));
    }
    await evaluate("document.querySelector('.landing-opening-skip')?.click()");
    await evaluate("document.fonts.ready");
    const layout = await evaluate(`(() => {
      const page = document.querySelector('.landing-page');
      const sections = [...page.querySelectorAll('main > section')];
      const rects = sections.map(section => section.getBoundingClientRect());
      const footer = page.querySelector('.landing-footer').getBoundingClientRect();
      return { heights: rects.map(rect => rect.height), joins: rects.slice(1).map((rect, i) => rect.top - rects[i].bottom),
        snap: getComputedStyle(page).scrollSnapType, scrollHeight: page.scrollHeight,
        footerBottom: footer.bottom, lastBottom: rects.at(-1).bottom,
        route: page.querySelector('.landing-road-highlight__stroke').getAttribute('d').length };
    })()`);
    assert.ok(layout.heights.every(value => value >= height - 1), `${label}: section shorter than viewport ${JSON.stringify(layout)}`);
    assert.ok(layout.joins.every(value => Math.abs(value) < 1), `${label}: gap between sections`);
    assert.ok(layout.route > 100, `${label}: route missing`);
    assert.ok(Math.abs(layout.footerBottom - layout.lastBottom) < 1, `${label}: footer not at end`);
    assert.equal(layout.snap.startsWith("y"), width > 640 && height > 800);
    for (const [hash, heading] of [["#about", "#about-title"], ["#features", "#features-title"], ["#contact", "#contact-title"]]) {
      await evaluate(`document.querySelector('.landing-nav a[href="${hash}"]').click()`);
      await new Promise(resolve => setTimeout(resolve, 1100));
      const nav = await evaluate(`(() => {
        const page = document.querySelector('.landing-page');
        const section = document.querySelector('${hash}').getBoundingClientRect();
        const title = document.querySelector('${heading}').getBoundingClientRect();
        const header = document.querySelector('.landing-header-inner').getBoundingClientRect();
        return { sectionTop: section.top, titleTop: title.top, headerBottom: header.bottom,
          titleBottom: title.bottom, scrollTop: page.scrollTop };
      })()`);
      assert.ok(nav.titleTop > nav.headerBottom && nav.titleTop < height && nav.titleBottom <= height + 1,
        `${label} ${hash}: title hidden ${JSON.stringify(nav)}`);
      assert.ok(Math.abs(nav.sectionTop) < 3, `${label} ${hash}: section navigation misaligned ${JSON.stringify(nav)}`);
    }
    await evaluate("document.querySelector('.landing-page').scrollTop = document.querySelector('.landing-page').scrollHeight");
    await new Promise(resolve => setTimeout(resolve, 500));
    assert.ok(await evaluate("document.querySelector('.landing-footer').getBoundingClientRect().bottom <= innerHeight + 1"), `${label}: footer unreachable`);
    const endpoint = await evaluate(`(() => {
      const page = document.querySelector('.landing-page');
      const route = document.querySelector('.landing-road-highlight__stroke');
      const tip = document.querySelector('.landing-road-highlight__tip');
      const dot = document.querySelector('.landing-road-highlight__destination');
      const footer = document.querySelector('.landing-footer').getBoundingClientRect();
      const point = route.getPointAtLength(route.getTotalLength());
      const tipRect = tip.getBoundingClientRect();
      const dotRect = dot.getBoundingClientRect();
      const cx = tipRect.left + tipRect.width / 2;
      const cy = tipRect.top + tipRect.height / 2;
      const overlap = [...document.querySelectorAll('#contact .landing-section-lead, #contact .landing-section-detail, #contact a')]
        .some(element => {
          const rect = element.getBoundingClientRect();
          return cx + 9 > rect.left && cx - 9 < rect.right && cy + 9 > rect.top && cy - 9 < rect.bottom;
        });
      return { maxScroll: page.scrollHeight - page.clientHeight, scrollTop: page.scrollTop,
        gap: footer.top - cy, tipVisible: getComputedStyle(tip).display !== 'none',
        pointX: point.x, pointY: point.y, tipX: Number(tip.getAttribute('cx')),
        tipY: Number(tip.getAttribute('cy')), dotOpacity: getComputedStyle(dot).opacity,
        dotGap: Math.hypot(dotRect.left + dotRect.width / 2 - cx, dotRect.top + dotRect.height / 2 - cy),
        overlap, screenX: cx, screenY: cy, dash: route.style.strokeDashoffset };
    })()`);
    assert.ok(Math.abs(endpoint.maxScroll - endpoint.scrollTop) < 2, `${label}: not at maximum scroll ${JSON.stringify(endpoint)}`);
    assert.ok(endpoint.tipVisible && endpoint.screenY > 0 && endpoint.screenY < height,
      `${label}: final tip not visible ${JSON.stringify(endpoint)}`);
    assert.ok(endpoint.gap >= 59 && endpoint.gap <= 101 && endpoint.dotGap < 2,
      `${label}: destination is not 60–100px above the footer ${JSON.stringify(endpoint)}`);
    assert.ok(Math.hypot(endpoint.pointX - endpoint.tipX, endpoint.pointY - endpoint.tipY) < 1 && !endpoint.overlap,
      `${label}: tip does not meet the clear route endpoint ${JSON.stringify(endpoint)}`);
    assert.equal(Number(endpoint.dash), 0, `${label}: route not fully drawn`);
    assert.equal(Number(endpoint.dotOpacity), 1, `${label}: destination glow not visible`);
    const { data } = await call("Page.captureScreenshot", { format: "png" });
    await writeFile(join(captures, `${label.replaceAll(' ', '-')}.png`), Buffer.from(data, "base64"));
    console.log(`${label}: visible destination ${endpoint.gap.toFixed(1)}px above footer, x=${endpoint.screenX.toFixed(1)}px`);
    if (label === "desktop 100%") {
      const stroke = ".landing-road-highlight__stroke";
      const atEnd = await evaluate(`document.querySelector('${stroke}').style.strokeDashoffset`);
      const reverse = await evaluate(`(() => {
        const page = document.querySelector('.landing-page');
        page.style.scrollSnapType = 'none';
        page.style.scrollBehavior = 'auto';
        page.scrollTop -= 180;
        return page.scrollTop;
      })()`);
      await new Promise(resolve => setTimeout(resolve, 120));
      const beforeEndpoint = await evaluate(`(() => {
        const tip = document.querySelector('.landing-road-highlight__tip');
        const dot = document.querySelector('.landing-road-highlight__destination');
        return { tip: Number(tip.getAttribute('cy')), end: Number(dot.getAttribute('cy')),
          dash: Number(document.querySelector('${stroke}').style.strokeDashoffset) };
      })()`);
      assert.ok(reverse < endpoint.maxScroll && beforeEndpoint.tip < beforeEndpoint.end - 50 && beforeEndpoint.dash > 0,
        `reverse scroll should retrace the last portion: ${JSON.stringify(beforeEndpoint)}`);
      await evaluate(`(() => {
        const page = document.querySelector('.landing-page');
        page.scrollTop = page.scrollHeight;
        page.style.scrollSnapType = '';
        page.style.scrollBehavior = '';
      })()`);
      await new Promise(resolve => setTimeout(resolve, 180));
      assert.equal(Number(await evaluate(`document.querySelector('${stroke}').style.strokeDashoffset`)), 0);
      await evaluate("document.querySelector('.landing-page').scrollTop = 0");
      await new Promise(resolve => setTimeout(resolve, 600));
      const atStart = await evaluate(`document.querySelector('${stroke}').style.strokeDashoffset`);
      assert.ok(Number(atEnd) < Number(atStart), "route reverses with scroll");
      const lightPath = await evaluate(`document.querySelector('${stroke}').getAttribute('d')`);
      await evaluate("localStorage.setItem('revela-theme', 'dark')");
      await call("Page.reload");
      await new Promise(resolve => setTimeout(resolve, 800));
      await evaluate("document.querySelector('.landing-opening-skip')?.click()");
      const darkPath = await evaluate(`document.querySelector('${stroke}').getAttribute('d')`);
      assert.ok(darkPath && darkPath !== lightPath, "dark-theme route recalculated");
      await call("Emulation.setEmulatedMedia", { features: [{ name: "prefers-reduced-motion", value: "reduce" }] });
      await new Promise(resolve => setTimeout(resolve, 100));
      assert.equal(await evaluate(`document.querySelector('${stroke}').style.strokeDashoffset`), "0");
      await call("Emulation.setEmulatedMedia", { features: [] });
    }
    console.log(`${label}: sections, route, anchors, footer OK`);
  }
} finally {
  socket?.close();
  if (browser && browser.exitCode === null) browser.kill();
  await server.close();
  await rm(profile, { recursive: true, force: true, maxRetries: 10, retryDelay: 300 });
}
