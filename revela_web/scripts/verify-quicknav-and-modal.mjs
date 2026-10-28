import { spawn } from "node:child_process";
import { existsSync, mkdtempSync } from "node:fs";
import { rm, writeFile } from "node:fs/promises";
import { join } from "node:path";

const edge = process.env.EDGE_BINARY || "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe";
const tempRoot = process.env.LOCALAPPDATA && join(process.env.LOCALAPPDATA, "Temp", "opencode");
if (!existsSync(edge) || !tempRoot || !existsSync(tempRoot)) {
  throw new Error("Missing edge or tempRoot");
}

const profile = mkdtempSync(join(tempRoot, "revela-quicknav-test-"));
const url = "http://localhost:5173/scripts/layout-preview.html?page=analytics&state=populated";

let browser;
let socket;

try {
  const debuggerURL = await new Promise((resolve, reject) => {
    browser = spawn(edge, [
      "--headless", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
      "--disable-background-networking", "--disable-component-update", "--disable-sync", "--no-proxy-server",
      `--user-data-dir=${profile}`, "--window-size=1440,900", "--remote-debugging-port=0", url,
    ], { windowsHide: true });
    let stderr = "";
    const timer = setTimeout(() => reject(new Error("Browser startup timed out: " + stderr)), 20000);
    browser.stdout.resume();
    browser.stderr.on("data", chunk => {
      stderr += chunk;
      const match = stderr.match(/DevTools listening on (ws:\/\/[^\s]+)/)?.[1];
      if (match) { clearTimeout(timer); resolve(match); }
    });
    browser.on("error", reject);
  });

  socket = new WebSocket(debuggerURL);
  await new Promise((resolve, reject) => {
    socket.addEventListener("open", resolve);
    socket.addEventListener("error", reject);
  });

  let requestID = 0;
  const pending = new Map();
  socket.addEventListener("message", event => {
    const msg = JSON.parse(event.data);
    if (!msg.id) return;
    const req = pending.get(msg.id);
    pending.delete(msg.id);
    if (msg.error) req?.reject(new Error(JSON.stringify(msg.error)));
    else req?.resolve(msg.result);
  });

  const call = (method, params = {}, sessionId) => new Promise((resolve, reject) => {
    const id = ++requestID;
    pending.set(id, { resolve, reject });
    socket.send(JSON.stringify({ id, method, params, sessionId }));
  });

  const targets = await call("Target.getTargets");
  const pageTarget = targets.targetInfos.find(t => t.type === "page" && t.url.includes("layout-preview.html"));
  const { sessionId } = await call("Target.attachToTarget", { targetId: pageTarget.targetId, flatten: true });

  await call("Page.enable", {}, sessionId);
  await call("Runtime.enable", {}, sessionId);
  await call("DOM.enable", {}, sessionId);

  const evalCode = async (expr) => {
    const res = await call("Runtime.evaluate", { expression: expr, returnByValue: true }, sessionId);
    if (res.exceptionDetails) {
      throw new Error(`Eval error: ${res.exceptionDetails.text} (${expr})`);
    }
    return res.result?.value;
  };

  const sleep = ms => new Promise(r => setTimeout(r, ms));
  await sleep(2500);

  console.log("=== STEP 1: Check Filters button in header ===");
  const filterBtnCheck = await evalCode(`(() => {
    const btn = document.querySelector(".analytics-filter-btn");
    const kpis = document.querySelector(".analytics-census-grid");
    const nav = document.querySelector(".analytics-section-nav");
    const topNav = document.querySelector(".top-navbar");
    if (!btn) return { error: "No filter button found" };
    const bRect = btn.getBoundingClientRect();
    const kRect = kpis ? kpis.getBoundingClientRect() : null;
    const nRect = nav ? nav.getBoundingClientRect() : null;
    const tRect = topNav ? topNav.getBoundingClientRect() : null;
    return {
      text: btn.textContent.trim(),
      btnBox: { top: bRect.top, bottom: bRect.bottom, left: bRect.left, right: bRect.right },
      topNavBottom: tRect ? tRect.bottom : null,
      kpiTop: kRect ? kRect.top : null,
      navTop: nRect ? nRect.top : null,
      overlapsTopNav: tRect ? bRect.top < tRect.bottom : false,
      overlapsKpis: kRect ? bRect.bottom > kRect.top && bRect.right > kRect.left && bRect.left < kRect.right : false,
      overlapsNav: nRect ? bRect.bottom > nRect.top && bRect.right > nRect.left && bRect.left < nRect.right : false,
    };
  })()`);
  console.log("Filters button check:", JSON.stringify(filterBtnCheck, null, 2));

  console.log("=== STEP 2: Light Mode Quick Nav check ===");
  const lightQuickNav = await evalCode(`(() => {
    const content = document.querySelector(".saas-content");
    const mainNav = document.querySelector(".analytics-section-nav");
    content.scrollTop = mainNav.offsetTop + mainNav.offsetHeight + 50;
    return new Promise(resolve => {
      setTimeout(() => {
        const qn = document.querySelector(".analytics-quick-nav");
        if (!qn) return resolve({ error: "No quick nav appeared" });
        const qnStyle = window.getComputedStyle(qn);
        const activeBtn = qn.querySelector(".analytics-quick-nav-btn.active");
        const inactiveBtn = qn.querySelector(".analytics-quick-nav-btn:not(.active)");
        resolve({
          visible: true,
          navBg: qnStyle.backgroundColor,
          activeText: activeBtn?.textContent.trim(),
          activeColor: activeBtn ? window.getComputedStyle(activeBtn).color : null,
          activeBg: activeBtn ? window.getComputedStyle(activeBtn).backgroundColor : null,
          inactiveText: inactiveBtn?.textContent.trim(),
          inactiveColor: inactiveBtn ? window.getComputedStyle(inactiveBtn).color : null,
        });
      }, 500);
    });
  })()`);
  console.log("Light mode quick nav:", JSON.stringify(lightQuickNav, null, 2));

  console.log("=== STEP 3: Dark Mode Quick Nav check ===");
  const darkQuickNav = await evalCode(`(() => {
    document.documentElement.classList.add("theme-dark");
    return new Promise(resolve => {
      setTimeout(() => {
        const qn = document.querySelector(".analytics-quick-nav");
        if (!qn) return resolve({ error: "No quick nav in dark mode" });
        const qnStyle = window.getComputedStyle(qn);
        const activeBtn = qn.querySelector(".analytics-quick-nav-btn.active");
        const inactiveBtn = qn.querySelector(".analytics-quick-nav-btn:not(.active)");
        resolve({
          theme: "dark",
          navBg: qnStyle.backgroundColor,
          navBoxShadow: qnStyle.boxShadow,
          navBorder: qnStyle.borderColor,
          activeText: activeBtn?.textContent.trim(),
          activeColor: activeBtn ? window.getComputedStyle(activeBtn).color : null,
          activeBg: activeBtn ? window.getComputedStyle(activeBtn).backgroundColor : null,
          inactiveText: inactiveBtn?.textContent.trim(),
          inactiveColor: inactiveBtn ? window.getComputedStyle(inactiveBtn).color : null,
        });
      }, 500);
    });
  })()`);
  console.log("Dark mode quick nav:", JSON.stringify(darkQuickNav, null, 2));

  // Take screenshot of dark mode quick nav
  const darkNavShot = await call("Page.captureScreenshot", { format: "png" }, sessionId);
  await writeFile("C:\\Users\\Mateo\\.gemini\\antigravity-ide\\brain\\898a7f1f-6874-4f2e-8194-4eb0d87967ea\\dark_quicknav_proof.png", Buffer.from(darkNavShot.data, "base64"));
  console.log("Saved dark_quicknav_proof.png");

  console.log("=== STEP 4: Test Filter Modal in Dark Mode ===");
  // Scroll back up and click Filters button
  const modalCheck = await evalCode(`(() => {
    const content = document.querySelector(".saas-content");
    content.scrollTop = 0;
    const btn = document.querySelector(".analytics-filter-btn");
    btn.click();
    return new Promise(resolve => {
      setTimeout(() => {
        const portal = document.querySelector(".analytics-filter-portal");
        const modal = document.querySelector(".analytics-filter-modal");
        const backdrop = document.querySelector(".analytics-filter-backdrop");
        if (!portal || !modal) return resolve({ error: "Modal didn't open" });
        const mStyle = window.getComputedStyle(modal);
        const bStyle = backdrop ? window.getComputedStyle(backdrop) : null;
        resolve({
          modalOpen: true,
          parent: modal.parentElement.tagName,
          portalZIndex: window.getComputedStyle(portal).zIndex,
          backdropZIndex: bStyle?.zIndex,
          modalZIndex: mStyle.zIndex,
          modalBg: mStyle.backgroundColor,
          accordionsCount: modal.querySelectorAll(".filter-accordion-header").length,
          applyBtnExists: Boolean(modal.querySelector(".primary-btn")),
          closeBtnExists: Boolean(modal.querySelector(".analytics-filter-close-btn")),
          clearBtnExists: Boolean(modal.querySelector(".ghost-btn")),
        });
      }, 500);
    });
  })()`);
  console.log("Dark mode filter modal:", JSON.stringify(modalCheck, null, 2));

  const darkModalShot = await call("Page.captureScreenshot", { format: "png" }, sessionId);
  await writeFile("C:\\Users\\Mateo\\.gemini\\antigravity-ide\\brain\\898a7f1f-6874-4f2e-8194-4eb0d87967ea\\dark_modal_proof.png", Buffer.from(darkModalShot.data, "base64"));
  console.log("Saved dark_modal_proof.png");

  console.log("=== STEP 5: Test Interactions Inside Modal (Accordions, Select, Apply) ===");
  const interactionCheck = await evalCode(`(() => {
    // Click location accordion
    const accordions = [...document.querySelectorAll(".filter-accordion-header")];
    const locationAccordion = accordions.find(a => a.textContent.includes("Location"));
    if (locationAccordion) locationAccordion.click();

    // Select Registry Status -> "Active"
    const selects = [...document.querySelectorAll(".analytics-filter-modal select")];
    const statusSel = selects.find(s => [...s.options].some(o => o.value === "Active"));
    if (statusSel) {
      statusSel.value = "Active";
      statusSel.dispatchEvent(new Event("change", { bubbles: true }));
    }

    return new Promise(resolve => {
      setTimeout(() => {
        const applyBtn = [...document.querySelectorAll(".analytics-filter-modal-footer button")].find(b => b.textContent.includes("Apply"));
        applyBtn.click();
        setTimeout(() => {
          const chips = [...document.querySelectorAll(".filter-chip")].map(c => c.textContent.trim());
          const filterBtn = document.querySelector(".analytics-filter-btn");
          resolve({
            modalClosed: !document.querySelector(".analytics-filter-portal"),
            activeChips: chips,
            filterBtnText: filterBtn?.textContent.trim(),
            hasFilterClass: filterBtn?.classList.contains("has-filters"),
          });
        }, 500);
      }, 300);
    });
  })()`);
  console.log("Interaction and Apply result:", JSON.stringify(interactionCheck, null, 2));

  console.log("=== STEP 6: Narrow Viewport Check (768x900) ===");
  await call("Emulation.setDeviceMetricsOverride", {
    width: 768,
    height: 900,
    deviceScaleFactor: 1,
    mobile: false,
  }, sessionId);
  await sleep(1000);

  const narrowCheck = await evalCode(`(() => {
    const filterBtn = document.querySelector(".analytics-filter-btn");
    filterBtn.click();
    return new Promise(resolve => {
      setTimeout(() => {
        const modal = document.querySelector(".analytics-filter-modal");
        const mRect = modal.getBoundingClientRect();
        resolve({
          modalWidth: mRect.width,
          modalHeight: mRect.height,
          windowWidth: window.innerWidth,
          fitsInWindow: mRect.width <= window.innerWidth,
        });
      }, 500);
    });
  })()`);
  console.log("Narrow viewport modal check:", JSON.stringify(narrowCheck, null, 2));

  const narrowShot = await call("Page.captureScreenshot", { format: "png" }, sessionId);
  await writeFile("C:\\Users\\Mateo\\.gemini\\antigravity-ide\\brain\\898a7f1f-6874-4f2e-8194-4eb0d87967ea\\narrow_modal_proof.png", Buffer.from(narrowShot.data, "base64"));
  console.log("Saved narrow_modal_proof.png");

} finally {
  if (browser) browser.kill();
  if (profile && existsSync(profile)) {
    try { await rm(profile, { recursive: true, force: true }); } catch {}
  }
}
