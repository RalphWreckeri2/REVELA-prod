// Dev-only, synthetic API/browser check. No credentials or production data.
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { existsSync, mkdtempSync, readFileSync, readdirSync } from "node:fs";
import { rm } from "node:fs/promises";
import { join } from "node:path";
import { createServer } from "vite";

const edge = process.env.EDGE_BINARY || "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe";
const tempRoot = process.env.LOCALAPPDATA && join(process.env.LOCALAPPDATA, "Temp", "opencode");
assert.ok(existsSync(edge) && tempRoot && existsSync(tempRoot));
const profile = mkdtempSync(join(tempRoot, "revela-export-browser-"));
const server = await createServer({ server: { host: "127.0.0.1", port: 0, open: false } });
await server.listen();
let browser;
let socket;
try {
  const debugUrl = await new Promise((resolve, reject) => {
    browser = spawn(edge, ["--headless", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
      "--window-size=1500,950", `--user-data-dir=${profile}`, "--remote-debugging-port=0", "about:blank"], { windowsHide: true });
    browser.stdout.resume();
    browser.stderr.on("data", chunk => {
      const url = chunk.toString().match(/DevTools listening on (ws:\/\/[^\s]+)/)?.[1];
      if (url) resolve(url);
    });
    browser.on("error", reject);
    setTimeout(() => reject(new Error("Edge did not start")), 20000);
  });
  socket = new WebSocket(debugUrl);
  await new Promise(resolve => socket.addEventListener("open", resolve, { once: true }));
  let id = 0;
  let session;
  const pending = new Map();
  socket.addEventListener("message", event => {
    const msg = JSON.parse(event.data);
    const request = pending.get(msg.id);
    if (!request) return;
    pending.delete(msg.id);
    if (msg.error) request.reject(new Error(JSON.stringify(msg.error)));
    else request.resolve(msg.result);
  });
  const call = (method, params = {}) => new Promise((resolve, reject) => {
    const requestID = ++id;
    pending.set(requestID, { resolve, reject });
    socket.send(JSON.stringify({ id: requestID, method, params, sessionId: session }));
  });
  const { targetId } = await call("Target.createTarget", { url: "about:blank" });
  session = (await call("Target.attachToTarget", { targetId, flatten: true })).sessionId;
  await call("Runtime.enable");
  await call("Page.enable");
  await call("Browser.setDownloadBehavior", { behavior: "allow", downloadPath: profile });
  await call("Emulation.setDeviceMetricsOverride", { width: 1280, height: 850, deviceScaleFactor: 1, mobile: false });
  const evaluate = async expression => {
    const result = await call("Runtime.evaluate", { expression, returnByValue: true, awaitPromise: true });
    if (result.exceptionDetails) throw new Error(result.exceptionDetails.exception?.description || result.exceptionDetails.text);
    return result.result.value;
  };
  const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
  const wait = async (expression, label, attempts = 200) => {
    for (let i = 0; i < attempts; i += 1) {
      if (await evaluate(`Boolean(${expression})`)) return;
      await sleep(100);
    }
    throw new Error(`Timed out: ${label}`);
  };
  await call("Page.navigate", { url: `http://127.0.0.1:${server.httpServer.address().port}/scripts/layout-preview.html?page=reports` });
  await wait("window.__demographicRequests >= 1 && document.querySelector('.export-reports-page')", "initial report");
  await wait("document.body.textContent.includes('Current confirmed compliance')", "confirmation labels");
  for (const theme of ["light", "dark"]) {
    await evaluate(`document.documentElement.classList.toggle('theme-dark', ${theme === "dark"})`);
    assert.ok(await evaluate("document.body.textContent.includes('Office-confirmed compliant: 3') && document.body.textContent.includes('Inspection-verified compliant: 5')"));
    console.log(`${theme}: submitted/verified confirmation labels visible`);
  }
  await evaluate("window.__demographicOverride = { total_businesses: 1249 }");
  await evaluate("window.dispatchEvent(new CustomEvent('revela:registry-update'))");
  await wait("document.body.textContent.includes('1,249') || document.body.textContent.includes('1249')", "registry update");
  const beforeFocus = await evaluate("window.__demographicRequests");
  await evaluate("window.dispatchEvent(new Event('focus')); document.dispatchEvent(new Event('visibilitychange'))");
  await wait(`window.__demographicRequests > ${beforeFocus}`, "focus/visibility refresh");
  const beforeRace = await evaluate("window.__demographicRequests");
  await evaluate("window.__holdNextDemographic = true; window.__demographicOverride = { total_businesses: 1001 }; window.dispatchEvent(new CustomEvent('revela:inspection-update'))");
  await wait(`window.__demographicRequests > ${beforeRace}`, "held older refresh");
  await evaluate("window.__demographicOverride = { total_businesses: 1301 }; window.dispatchEvent(new CustomEvent('revela:registry-update'))");
  await wait("document.body.textContent.includes('1,301') || document.body.textContent.includes('1301')", "newer refresh");
  await evaluate("window.__releaseDemographic()");
  await sleep(200);
  assert.ok(await evaluate("document.body.textContent.includes('1,301') || document.body.textContent.includes('1301')"), "late older response did not overwrite the newer snapshot");
  await evaluate("window.__demographicOverride = { total_businesses: 1500 }");
  await evaluate("[...document.querySelectorAll('button')].find(b => b.textContent.includes('Export Demographics CSV')).click()");
  await wait("document.body.textContent.includes('1500') || document.body.textContent.includes('1,500')", "immediate export snapshot");
  await wait("[...document.querySelectorAll('.saas-card')].some(card => card.textContent.includes('1500') || card.textContent.includes('1,500'))", "display refreshed");
  for (let i = 0; i < 100 && !readdirSync(profile).some(name => name.endsWith('.csv')); i += 1) await sleep(100);
  const csvFile = readdirSync(profile).find(name => name.endsWith('.csv'));
  assert.ok(csvFile, "CSV download completed");
  assert.match(readFileSync(join(profile, csvFile), "utf8"), /Total Registered Entities,1500/);
  await evaluate("window.__demographicOverride = { total_businesses: 1600 }");
  await evaluate("[...document.querySelectorAll('button')].find(b => b.textContent.includes('Complete Demographic Dossier (PDF)')).click()");
  await wait("document.querySelector('.print-report-container')?.textContent.includes('1600')", "fresh PDF data");
  await evaluate("window.__demographicSizeOverride = [{ size_label: 'Micro', count: 777 }]");
  await evaluate("[...document.querySelectorAll('#chart-card-size button')].find(b => b.textContent.includes('Export PNG')).click()");
  await wait("document.querySelector('#chart-card-size')?.textContent.includes('777')", "fresh PNG card and legend");
  await wait("document.body.textContent.includes('Chart Exported')", "PNG capture completed", 600);
  for (let i = 0; i < 300 && !readdirSync(profile).some(name => name.endsWith('.png')); i += 1) await sleep(100);
  assert.ok(readdirSync(profile).some(name => name.endsWith('.png')), `fresh PNG downloaded (${readdirSync(profile).join(", ")})`);
  await evaluate("window.__failNextDemographic = true; window.__demographicOverride = { total_businesses: 2000 }");
  await evaluate("[...document.querySelectorAll('button')].find(b => b.textContent.includes('Export Demographics CSV')).click()");
  await wait("document.body.textContent.includes('Report not exported')", "refresh failure blocks export");
  assert.equal(readdirSync(profile).filter(name => name.endsWith('.csv')).length, 1);
  await call("Page.navigate", { url: `http://127.0.0.1:${server.httpServer.address().port}/scripts/layout-preview.html?page=analytics` });
  await wait("document.body.textContent.includes('Verified inspection reports') && document.body.textContent.includes('Submitted · awaiting verification (reports)')", "analytics submitted/verified labels");
  for (const theme of ["light", "dark"]) {
    await evaluate(`document.documentElement.classList.toggle('theme-dark', ${theme === "dark"})`);
    assert.ok(await evaluate("document.body.textContent.includes('Verified Green reports') && document.body.textContent.includes('Green share of verified reports')"));
    console.log(`${theme}: analytics verified and submitted labels visible`);
  }
  await evaluate("[...document.querySelectorAll('.analytics-tab-btn')].find(button => button.textContent.includes('Operations')).click()");
  await wait("document.body.textContent.includes('Work submitted') && document.body.textContent.includes('Admin-verified')", "leaderboard submitted/verified labels");
  for (const theme of ["light", "dark"]) {
    await evaluate(`document.documentElement.classList.toggle('theme-dark', ${theme === "dark"})`);
    assert.ok(await evaluate("document.body.textContent.includes('Work submitted') && document.body.textContent.includes('Admin-verified')"));
    console.log(`${theme}: leaderboard submitted and verified labels visible`);
  }
  console.log("event/focus refresh, newer-response fence, immediate CSV/PDF/PNG, failed refresh and both themes OK");
} finally {
  socket?.close();
  if (browser && browser.exitCode === null) browser.kill();
  await server.close();
  await rm(profile, { recursive: true, force: true, maxRetries: 10, retryDelay: 300 });
}
