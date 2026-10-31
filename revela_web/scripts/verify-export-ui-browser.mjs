import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { existsSync, mkdtempSync } from "node:fs";
import { rm, writeFile } from "node:fs/promises";
import { join } from "node:path";
import { createServer } from "vite";

const edge = process.env.EDGE_BINARY || "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe";
const tempRoot = process.env.LOCALAPPDATA && join(process.env.LOCALAPPDATA, "Temp", "opencode");
if (!existsSync(edge) || !tempRoot || !existsSync(tempRoot)) throw new Error("This browser check requires Edge and the approved temporary directory.");

const profile = mkdtempSync(join(tempRoot, "revela-export-ui-"));
const server = await createServer({ logLevel: "silent", server: { host: "127.0.0.1", port: 0 } });
let browser;
let socket;
try {
  await server.listen();
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
  let session;
  const pending = new Map();
  socket.addEventListener("message", event => {
    const message = JSON.parse(event.data);
    const request = pending.get(message.id);
    if (!request) return;
    pending.delete(message.id);
    if (message.error) request.reject(new Error(JSON.stringify(message.error)));
    else request.resolve(message.result);
  });
  const call = (method, params = {}) => new Promise((resolve, reject) => {
    const id = ++nextId;
    pending.set(id, { resolve, reject });
    socket.send(JSON.stringify({ id, method, params, sessionId: session }));
  });
  const { targetId } = await call("Target.createTarget", { url: "about:blank" });
  session = (await call("Target.attachToTarget", { targetId, flatten: true })).sessionId;
  await call("Page.enable");
  await call("Runtime.enable");
  const evaluate = async expression => {
    const result = await call("Runtime.evaluate", { expression, returnByValue: true, awaitPromise: true });
    if (result.exceptionDetails) throw new Error(result.exceptionDetails.text);
    return result.result.value;
  };
  const waitFor = async expression => {
    for (let i = 0; i < 160; i++) {
      if (await evaluate(`Boolean(${expression})`)) return;
      await new Promise(resolve => setTimeout(resolve, 80));
    }
    throw new Error(`Timed out waiting for ${expression}: ${await evaluate("document.body.innerText.slice(0, 400)")}`);
  };

  for (const [width, height, theme] of [[1440, 900, "light"], [1440, 900, "dark"], [820, 1000, "dark"]]) {
    await call("Emulation.setDeviceMetricsOverride", { width, height, mobile: false, deviceScaleFactor: 1 });
    await call("Page.navigate", { url: `http://127.0.0.1:${server.httpServer.address().port}/scripts/layout-preview.html?page=reports&theme=${theme}` });
    await waitFor("document.querySelector('#chart-card-size .export-actions-menu > summary:not([aria-disabled=true])')");
    if (process.env.REVELA_EXPORT_CAPTURE) {
      const screenshot = await call("Page.captureScreenshot", { format: "png" });
      const output = join(tempRoot, `revela-export-ui-${width}-${theme}.png`);
      await writeFile(output, Buffer.from(screenshot.data, "base64"));
      console.log(`Layout screenshot: ${output}`);
    }
    assert.equal(await evaluate("document.body.textContent.includes('BPLO Official')"), false);
    assert.equal(await evaluate("document.body.textContent.includes('Active Municipality-wide')"), false);
    assert.equal(await evaluate("document.querySelectorAll('.export-report-view-nav button').length"), 2);
    assert.equal(await evaluate("document.querySelectorAll('.export-report-demographic-grid .export-actions-menu').length"), 7);
    assert.equal(await evaluate("Boolean(document.querySelector('.operational-report-card'))"), false);
    await evaluate("document.querySelector('.export-profile-menu > summary').click()");
    assert.equal(await evaluate("[...document.querySelectorAll('.export-profile-menu button')].map(button => button.textContent.trim()).join('|')"),
      "Demographics spreadsheet (CSV)|Complete dossier (PDF)");
    await evaluate("document.querySelector('.export-profile-menu > summary').click()");
    if (width === 1440 && theme === "light") {
      await evaluate("document.querySelector('.export-profile-menu > summary').click(); document.querySelector('.export-profile-menu button:last-child').click()");
      await waitFor("document.querySelectorAll('.demographic-complete-body .dossier-section').length === 8");
      await call("Emulation.setEmulatedMedia", { media: "print" });
      const printStyles = await evaluate(`(() => ({
        header: getComputedStyle(document.querySelector('.print-header')).position,
        footer: getComputedStyle(document.querySelector('.print-footer')).position,
        tableColors: [...new Set([...document.querySelectorAll('.demographic-complete-body .print-table th')]
          .map(th => getComputedStyle(th).backgroundColor))]
      }))()`);
      assert.equal(printStyles.header, "fixed");
      assert.equal(printStyles.footer, "fixed");
      assert.deepEqual(printStyles.tableColors, ["rgb(234, 241, 237)"], "dossier uses one quiet table-header color");
      if (process.env.REVELA_EXPORT_CAPTURE) {
        const pdf = await call("Page.printToPDF", { printBackground: true, preferCSSPageSize: true });
        const output = join(tempRoot, "revela-export-complete-dossier.pdf");
        await writeFile(output, Buffer.from(pdf.data, "base64"));
        console.log(`Print preview: ${output}`);
      }
      await call("Emulation.setEmulatedMedia", { media: "screen" });
      await evaluate("window.dispatchEvent(new Event('afterprint'))");
      await waitFor("!document.querySelector('.print-report-container')");
    }
    await evaluate("document.querySelector('#chart-card-size .export-actions-menu > summary').click()");
    assert.equal(await evaluate("document.querySelectorAll('#chart-card-size .export-actions-menu__panel button').length"), 2);
    if (width === 1440 && theme === "light") {
      await evaluate(`window.print = () => { window.__printCount = (window.__printCount || 0) + 1; }; document.querySelector('#chart-card-size button[title*="PNG"]').click()`);
      await waitFor("document.body.textContent.includes('Chart Exported!') || document.body.textContent.includes('Export Failed')");
      assert.equal(await evaluate("document.body.textContent.includes('Chart Exported!')"), true, "PNG export still works from the menu");
      await evaluate(`document.querySelector('.swal2-container')?.remove(); document.body.classList.remove('swal2-shown', 'swal2-height-auto'); document.querySelector('#chart-card-size .export-actions-menu > summary').click(); document.querySelector('#chart-card-size button[title*="PDF"]').click()`);
      await waitFor(`document.querySelector('.print-report-container img[src^="data:image/png"]')`);
      assert.equal(await evaluate("Boolean(document.querySelector('.print-report-container img'))"), true, "PDF includes the chart image");
    }
    await evaluate("[...document.querySelectorAll('.export-report-view-nav button')].find(button => button.textContent.includes('Field reports')).click()");
    await waitFor("document.querySelector('.operational-report-card') && !document.querySelector('#chart-card-size')");
    assert.equal(await evaluate("Boolean(document.querySelector('.export-profile-menu'))"), false);
    assert.equal(await evaluate("document.querySelectorAll('.operational-report-card').length"), 3);
    assert.equal(await evaluate("Boolean(document.querySelector('.operational-report-details:not([open]) > summary'))"), true);
    await evaluate("[...document.querySelectorAll('.export-report-view-nav button')].find(button => button.textContent.includes('Business profile')).click()");
    await waitFor("document.querySelector('#chart-card-size') && !document.querySelector('.operational-report-card')");
    assert.equal(await evaluate("document.documentElement.scrollWidth <= innerWidth + 2"), true, `${theme} ${width}px has no horizontal overflow`);
    console.log(`${theme} ${width}px: export sections and chart menus passed`);
  }
} finally {
  socket?.close();
  if (browser && browser.exitCode === null) browser.kill();
  await server.close();
  await rm(profile, { recursive: true, force: true, maxRetries: 5, retryDelay: 100 }).catch(() => {});
}
