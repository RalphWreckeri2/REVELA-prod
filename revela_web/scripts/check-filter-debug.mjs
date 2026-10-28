import { spawn } from "node:child_process";
import { existsSync } from "node:fs";

const edge = process.env.EDGE_BINARY || "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe";
const browser = spawn(edge, [
  "--headless", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
  "--window-size=1440,900",
  "--remote-debugging-port=9222", "http://localhost:5173/scripts/layout-preview.html?page=analytics&state=populated"
], { windowsHide: true });

let stderr = "";
const timer = setTimeout(() => {
  console.error("Timed out waiting for Edge");
  process.exit(1);
}, 10000);

browser.stderr.on("data", chunk => {
  stderr += chunk;
  const match = stderr.match(/DevTools listening on (ws:\/\/[^\s]+)/);
  if (match) {
    clearTimeout(timer);
    connect(match[1]);
  }
});

async function connect(wsUrl) {
  const ws = new WebSocket(wsUrl);
  await new Promise(r => ws.onopen = r);
  let id = 0;
  const pending = new Map();
  ws.onmessage = e => {
    const msg = JSON.parse(e.data);
    if (msg.id && pending.has(msg.id)) {
      pending.get(msg.id)(msg);
      pending.delete(msg.id);
    }
  };
  const send = (method, params = {}, sessionId) => new Promise(resolve => {
    const msgId = ++id;
    pending.set(msgId, resolve);
    ws.send(JSON.stringify({ id: msgId, method, params, sessionId }));
  });
  const targets = await send("Target.getTargets");
  console.log("Targets:", targets.result.targetInfos.map(t => ({ id: t.targetId, url: t.url, type: t.type })));
  let pageTarget = targets.result.targetInfos.find(t => t.type === "page" && t.url.includes("localhost"));
  if (!pageTarget) pageTarget = targets.result.targetInfos.find(t => t.type === "page");
  const attached = await send("Target.attachToTarget", { targetId: pageTarget.targetId, flatten: true });
  const sessionId = attached.result.sessionId;

  await send("Page.enable", {}, sessionId);
  await send("Runtime.enable", {}, sessionId);
  if (!pageTarget.url.includes("localhost")) {
    await send("Page.navigate", { url: "http://localhost:5173/scripts/layout-preview.html?page=analytics&state=populated" }, sessionId);
  }
  // wait 3 seconds for app to render
  await new Promise(r => setTimeout(r, 3000));

  const res = await send("Runtime.evaluate", {
    expression: `(async () => {
      const btn = document.querySelector('.analytics-filter-sticky-btn');
      const panel = document.getElementById('analytics-filter-panel');
      const btnRect = btn ? btn.getBoundingClientRect() : null;
      const panelDisplayBefore = panel ? getComputedStyle(panel).display : null;
      btn?.click();
      await new Promise(r => setTimeout(r, 100));
      const panelDisplayAfter = panel ? getComputedStyle(panel).display : null;
      const panelRect = panel ? panel.getBoundingClientRect() : null;
      const panelStyles = panel ? {
        position: getComputedStyle(panel).position,
        zIndex: getComputedStyle(panel).zIndex,
        pointerEvents: getComputedStyle(panel).pointerEvents,
        top: getComputedStyle(panel).top,
        right: getComputedStyle(panel).right,
        width: getComputedStyle(panel).width,
        height: getComputedStyle(panel).height,
        overflow: getComputedStyle(panel).overflow,
      } : null;
      
      let topEl = null;
      let topElAtBtn = null;
      if (btnRect) {
        topElAtBtn = document.elementFromPoint(btnRect.left + 10, btnRect.top + 10)?.outerHTML?.slice(0, 100);
      }
      if (panelRect && panelRect.width > 0) {
        topEl = document.elementFromPoint(panelRect.left + 50, panelRect.top + 50)?.outerHTML?.slice(0, 150);
      }
      const toJSONRect = r => r ? ({ x: r.x, y: r.y, top: r.top, left: r.left, width: r.width, height: r.height, bottom: r.bottom, right: r.right }) : null;
      const btnRectJSON = toJSONRect(btnRect);
      const panelRectJSON = toJSONRect(panelRect);
      
      const selects = panel ? [...panel.querySelectorAll('select')].map(s => ({
        value: s.value,
        optionsCount: s.options.length,
        rect: toJSONRect(s.getBoundingClientRect())
      })) : [];

      const accordions = panel ? [...panel.querySelectorAll('.filter-accordion-header')].map(a => ({
        text: a.innerText.trim(),
        rect: toJSONRect(a.getBoundingClientRect())
      })) : [];

      // Test clicking the first select or accordion
      let clickedAccordionResult = null;
      if (accordions.length > 0) {
        const firstAcc = panel.querySelector('.filter-accordion-header');
        firstAcc?.click();
        await new Promise(r => setTimeout(r, 50));
        clickedAccordionResult = panel.querySelector('.filter-accordion-body') ? "opened" : "failed";
      }

      const backdrop = document.querySelector('.analytics-filter-backdrop');
      const backdropRect = toJSONRect(backdrop?.getBoundingClientRect());
      const scroller = document.querySelector('.saas-content');
      
      // Now scroll scroller down 500px
      scroller.scrollTop = 500;
      await new Promise(r => setTimeout(r, 100));

      const panelRectScrolled = toJSONRect(panel?.getBoundingClientRect());
      const btnRectScrolled = toJSONRect(btn?.getBoundingClientRect());
      const backdropRectScrolled = toJSONRect(backdrop?.getBoundingClientRect());

      return {
        url: location.href,
        btnText: btn ? btn.innerText : null,
        btnRect: btnRectJSON,
        btnRectScrolled,
        panelRect: panelRectJSON,
        panelRectScrolled,
        backdropRect,
        backdropRectScrolled,
        scrollerScrollTop: scroller.scrollTop,
        scrollerRect: toJSONRect(scroller.getBoundingClientRect()),
      };
    })()`,
    awaitPromise: true,
    returnByValue: true
  }, sessionId);

  if (res.error) console.error("CDP error:", res.error);
  console.log("Evaluation result:", JSON.stringify(res.result?.value || res, null, 2));
  browser.kill();
  process.exit(0);
}
