import { spawn } from "node:child_process";
import { existsSync, mkdtempSync } from "node:fs";
import { rm } from "node:fs/promises";
import { join } from "node:path";
import { createServer } from "vite";

const edge = process.env.EDGE_BINARY || "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe";
const tempRoot = process.env.LOCALAPPDATA && join(process.env.LOCALAPPDATA, "Temp", "opencode");
const smokePage = process.argv[2] || "compliance-smoke";
if (!/^[a-z-]+$/.test(smokePage)) throw new Error("Invalid browser fixture name.");
if (!existsSync(edge) || !tempRoot || !existsSync(tempRoot)) throw new Error("This optional browser check requires local Edge and the approved temporary directory.");
const profile = mkdtempSync(join(tempRoot, "revela-compliance-browser-"));
const server = await createServer({ server: { host: "127.0.0.1", port: 0, open: false } });
let browser;
let socket;
const sleep = milliseconds => new Promise(resolve => setTimeout(resolve, milliseconds));
try {
  await server.listen();
  const port = server.httpServer.address().port;
  const debuggerURL = await new Promise((resolve, reject) => {
    browser = spawn(edge, [
      "--headless", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
      "--disable-background-networking", "--disable-component-update", "--disable-sync", "--no-proxy-server",
      "--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1, EXCLUDE localhost",
      `--user-data-dir=${profile}`, "--window-size=820,1000", "--remote-debugging-port=0", "about:blank",
    ], { windowsHide: true });
    let stderr = "";
    const timer = setTimeout(() => reject(new Error("Browser debugger startup timed out: " + stderr)), 20000);
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
  let requestID = 0;
  const pending = new Map();
  socket.addEventListener("message", event => {
    const message = JSON.parse(event.data);
    if (!message.id) return;
    const request = pending.get(message.id);
    pending.delete(message.id);
    if (message.error) request?.reject(new Error(JSON.stringify(message.error)));
    else request?.resolve(message.result);
  });
  const call = (method, params = {}, sessionId) => new Promise((resolve, reject) => {
    const id = ++requestID;
    pending.set(id, { resolve, reject });
    socket.send(JSON.stringify({ id, method, params, sessionId }));
  });
  const target = await call("Target.createTarget", { url: "about:blank" });
  const { sessionId } = await call("Target.attachToTarget", { targetId: target.targetId, flatten: true });
  const scenarios = smokePage === "compliance-smoke"
    ? [[1440, 900], [820, 1000], [768, 600], [1280, 480]]
      .flatMap(([width, height]) => ["light", "dark"].map(theme => ({ width, height, theme })))
    : smokePage === "actionable-smoke"
      ? [[1440, 900], [820, 1000], [768, 600]].map(([width, height]) => ({ width, height, theme: "light" }))
    : [{ width: 820, height: 1000, theme: "light" }];
  for (const { width, height, theme } of scenarios) {
    await call("Emulation.setDeviceMetricsOverride", { width, height, deviceScaleFactor: 1, mobile: false }, sessionId);
    const url = `http://127.0.0.1:${port}/scripts/${smokePage}.html?theme=${theme}&viewport=${width}x${height}`;
    await call("Page.navigate", { url }, sessionId);
    let parsed;
    for (let attempt = 0; attempt < 400; attempt += 1) {
      const response = await call("Runtime.evaluate", {
        expression: `location.href === ${JSON.stringify(url)} && document.getElementById('${smokePage}-results')?.textContent`, returnByValue: true,
      }, sessionId);
      const text = response.result?.value;
      if (typeof text === "string" && text.startsWith("{")) { parsed = JSON.parse(text); break; }
      await sleep(100);
    }
    if (!parsed) throw new Error("Browser did not finish the smoke checks");
    console.log(JSON.stringify({ width, height, theme, ...parsed }, null, 2));
    if (parsed.failed) { process.exitCode = 1; break; }
  }
  await Promise.race([call("Browser.close").catch(() => {}), sleep(2000)]);
} finally {
  socket?.close();
  if (browser && browser.exitCode === null) {
    await Promise.race([new Promise(resolve => browser.once("close", resolve)), sleep(3000)]);
    if (browser.exitCode === null) {
      await new Promise(resolve => spawn("taskkill", ["/PID", String(browser.pid), "/T", "/F"], { windowsHide: true }).once("close", resolve));
    }
  }
  await server.close();
  await sleep(500);
  await rm(profile, { recursive: true, force: true, maxRetries: 10, retryDelay: 300 });
}
