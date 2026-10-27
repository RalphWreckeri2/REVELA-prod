// Synthetic local API + real Edge/CDP requests. Never connects to production.
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { createServer as createHttpServer } from "node:http";
import { existsSync, mkdtempSync, writeFileSync } from "node:fs";
import { rm } from "node:fs/promises";
import { join } from "node:path";
import { createServer as createViteServer } from "vite";

const edge = process.env.EDGE_BINARY || "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe";
const tempRoot = process.env.LOCALAPPDATA && join(process.env.LOCALAPPDATA, "Temp", "opencode");
assert.ok(existsSync(edge) && tempRoot && existsSync(tempRoot), "Local Edge and approved temp directory required");
 const profile = mkdtempSync(join(tempRoot, "revela-refresh-browser-"));
const captures = process.argv.includes("--capture-navbar") ? mkdtempSync(join(tempRoot, "revela-navbar-captures-")) : null;
const calls = [];
const clients = new Set();
const fixture = {
  holdRegistry: false, heldRegistry: [], holdUsers: false, heldUsers: [], failRegistry: false, failBarangays: false,
  holds: new Set(), pending: new Map(), failures: new Set(), storageMB: 37,
  flagName: "Synthetic Map Flag", reportName: "Synthetic Inspection", reportCount: 1,
  delayRegistryMs: 0,
  addedUser: null,
};
const release = key => {
  fixture.holds.delete(key);
  const pending = fixture.pending.get(key) || [];
  fixture.pending.delete(key);
  pending.forEach(resolve => resolve());
};
const sections = {
  descriptive: { kpis: { total_businesses: 123, active_count: 80, expired_count: 20, pending_count: 3, compliance_rate: 80 },
    sectoral_distribution: [], business_size_dist: [], business_type_dist: [], registration_type_dist: [],
    nature_per_barangay: [], compliance_by_size: [], compliance_timeline: [], enforcement_progress: [],
    audit_summary: { total_inspections: 0, result_breakdown: [], submitted_result_breakdown: [], workflow: {} },
    confirmed_compliance: { office_confirmed: 0, inspection_verified: 0, total_confirmed: 0 },
    non_registry_monitoring: { summary: { total: 0, needs_verification: 0, under_inspection: 0, verified_green: 0 }, records: [], by_barangay: [], generated_at: new Date().toISOString() } },
  diagnostic: { scan_history: [], category_risk_drivers: [], dbscan_clusters: [], morans_data: { points: [] } },
  prescriptive: { rankings: [], dispatch_recommendations: [], wlc_config: {} },
  operations: { inspector_stats: [], status_breakdown: [], inspection_timeline: [] },
  summary: { kpis: { total_businesses: 4321, active_count: 80, expired_count: 20, pending_count: 3 }, new_year_rollover: null },
};
const api = createHttpServer(async (req, res) => {
  res.setHeader("Access-Control-Allow-Origin", "*");
  res.setHeader("Access-Control-Allow-Headers", "Authorization, Content-Type");
  if (req.method === "OPTIONS") { res.writeHead(204); res.end(); return; }
  const url = new URL(req.url, `http://${req.headers.host}`);
  calls.push({ path: url.pathname, query: url.search, method: req.method });
  const reply = (data, code = 200) => { res.writeHead(code, { "Content-Type": "application/json", "Access-Control-Allow-Origin": "*" }); res.end(JSON.stringify(data)); };
  const path = url.pathname;
  const gate = async key => {
    if (fixture.holds.has(key)) await new Promise(resolve => fixture.pending.set(key, [...(fixture.pending.get(key) || []), resolve]));
    if (res.destroyed) return true;
    if (fixture.failures.delete(key)) { reply({ error: `Synthetic ${key} failure` }, 503); return true; }
    return false;
  };
  if (path === "/api/notifications/stream") {
    res.writeHead(200, { "Content-Type": "text/event-stream", "Cache-Control": "no-cache", "Access-Control-Allow-Origin": "*" });
    clients.add(res); res.write('data: {"type":"connected"}\n\n');
    res.on("close", () => clients.delete(res));
    return;
  }
  if (path === "/api/auth/me") {
    const userID = Number((req.headers.authorization || "").match(/user-(\d+)/)?.[1] || 17);
    reply({ id: userID, userID, fullName: `Synthetic User ${userID}`, role: "SUPER_ADMIN", email: `user${userID}@example.test` }); return;
  }
  if (path === "/api/auth/activity") { reply({ ok: true }); return; }
  if (path === "/api/auth/login" && req.method === "POST") {
    reply({ access_token: "user-18", user: { userRole: "SUPER_ADMIN", mustChangePassword: false } }); return;
  }
  if (path === "/api/auth/logout" && req.method === "POST") { reply({ ok: true }); return; }
  if (path === "/api/notifications") { reply({ data: [{ id: 3, title: "Synthetic notice", message: "No real data", readAt: null }] }); return; }
  if (path === "/api/notifications/unread-count") { reply({ count: 1 }); return; }
  if (path === "/api/registry/") {
    if (fixture.delayRegistryMs) await new Promise(resolve => setTimeout(resolve, fixture.delayRegistryMs));
    if (fixture.holdRegistry) await new Promise(resolve => fixture.heldRegistry.push(resolve));
    if (fixture.failRegistry) { fixture.failRegistry = false; reply({ error: "Synthetic registry failure" }, 503); return; }
    reply({ data: [{ businessID: "B-1", businessName: url.searchParams.get("status") === "Expired" ? "Expired Synthetic Shop" : "Synthetic Shop",
      applicationStatus: url.searchParams.get("status") === "Expired" ? "Expired" : "Active", barangayName: "Barangay I" }], total: 1, pages: 1, page: 1 }); return;
  }
  if (path === "/api/registry/barangays") {
    if (await gate(path)) return;
    if (fixture.failBarangays) { fixture.failBarangays = false; reply({ error: "Synthetic barangay failure" }, 503); return; }
    reply([{ barangayID: 1, barangayName: "Barangay I" }]); return;
  }
  if (path === "/api/users/") {
    if (req.method === "POST") {
      let body = "";
      for await (const chunk of req) body += chunk;
      fixture.addedUser = JSON.parse(body);
      reply({ tempPassword: "SyntheticOnly-123" }); return;
    }
    if (await gate(url.searchParams.get("role") === "Inspector" ? "/api/users/:Inspector" : path)) return;
    if (fixture.holdUsers) await new Promise(resolve => fixture.heldUsers.push(resolve));
    reply([{ userID: 17, fullName: "Synthetic User 17", userRole: "SUPER_ADMIN", email: "user17@example.test", isActive: true },
      ...(fixture.addedUser ? [{ userID: 18, fullName: fixture.addedUser.fullName, email: fixture.addedUser.email,
        userRole: fixture.addedUser.role, isActive: true }] : [])]); return;
  }
  if (path === "/api/users/generate-password") { reply({ tempPassword: "SyntheticOnly-123" }); return; }
  if (path === "/api/inspections/") {
    if (await gate(path)) return;
    const limit = Number(url.searchParams.get("limit") || 50);
    const data = fixture.reportCount ? [{ reportID: 91, logID: 3, businessName: fixture.reportName,
      detectedName: fixture.reportName, verificationStatus: "Assigned", inspectionResult: "Yellow",
      barangayName: "Barangay I", assignedInspectorName: "Synthetic Inspector", deadline: new Date().toISOString() }] : [];
    reply({ data, total: data.length, total_rows: data.length, page: 1, pages: 1, per_page: limit }); return;
  }
  if (path === "/api/inspections/calendar") {
    if (await gate(path)) return;
    const month = url.searchParams.get("month"), selectedDate = url.searchParams.get("date");
    reply({ month, selectedDate, days: [{ date: selectedDate, count: 1 }], activities: [] }); return;
  }
  if (path === "/api/analytics/all") {
    const filter = url.searchParams.get("application_status");
    const name = url.searchParams.get("section");
    if (await gate(`${path}:${name}`)) return;
    const age = filter ? 899 : 0;
    const computed_at = new Date(Date.now() - age * 1000).toISOString();
    const data = { ...(sections[name] ?? {}) };
    if (data.kpis) data.kpis = { ...data.kpis, total_businesses: filter === "Active" ? 777 : filter === "Expired" ? 888 : name === "summary" ? 4321 : 123,
      current_year_registered_count: filter === "Active" ? 777 : filter === "Expired" ? 888 : 123 };
    reply({ [name]: data, analytics_cache: { age_seconds: age, computed_at } }); return;
  }
  if (path === "/api/analytics/filter-metadata") { reply({ lines_of_business: [], business_types: [], business_sizes: [] }); return; }
  if (path === "/api/analytics/wlc-config") { if (await gate(path)) return; reply({ w1_risk: 68, w2_sector: 7, w3_distance: 25 }); return; }
  if (path === "/api/flags/") {
    if (await gate(path)) return;
    const rows = fixture.flagName ? [{ logID: 3, detectedName: fixture.flagName, flagColor: "Red",
      latitude: 13.9667, longitude: 121.1167, barangayName: "Barangay I", originSource: "detection" }] : [];
    reply({ data: rows, total: rows.length, page: 1, pages: 1 }); return;
  }
  if (path === "/api/analytics/ops-rankings") { if (await gate(path)) return; reply({ data: [] }); return; }
  if (path === "/api/flags/detection-quota" || path === "/api/flags/places-usage") { if (await gate(path)) return; reply({}); return; }
  if (path === "/api/analytics/demographic-reports") { if (await gate(path)) return; reply({ descriptive: { ...sections.descriptive, kpis: { ...sections.descriptive.kpis, total_businesses: 123 } } }); return; }
  if (path === "/api/inspections/evidence-storage-stats") { if (await gate(path)) return; reply({ categories: {}, totalDiskMB: fixture.storageMB, totalFilesOnDisk: 2 }); return; }
  // Never implement a mutating application endpoint in this synthetic fixture.
  reply({ error: `Unexpected synthetic request: ${req.method} ${path}` }, 404);
});
await new Promise(resolve => api.listen(0, "127.0.0.1", resolve));
process.env.VITE_API_ORIGIN = `http://127.0.0.1:${api.address().port}`;
const server = await createViteServer({ server: { host: "127.0.0.1", port: 0, open: false } });
await server.listen();
const origin = `http://127.0.0.1:${server.httpServer.address().port}`;
let browser, socket;
 const network = [], exceptions = [], streams = new Set();
 let streamAborts = 0;
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
try {
  const debuggerURL = await new Promise((resolve, reject) => {
    browser = spawn(edge, ["--headless", "--disable-gpu", "--no-first-run", "--no-default-browser-check", "--disable-background-networking", "--disable-component-update", "--disable-sync", "--no-proxy-server", "--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1, EXCLUDE localhost", `--user-data-dir=${profile}`, "--remote-debugging-port=0", "about:blank"], { windowsHide: true });
    let stderr = "";
    const timer = setTimeout(() => reject(new Error(`Edge startup timeout: ${stderr}`)), 20000);
    browser.stdout.resume(); browser.stderr.on("data", chunk => {
      stderr += chunk;
      const match = stderr.match(/DevTools listening on (ws:\/\/[^\s]+)/);
      if (match) { clearTimeout(timer); resolve(match[1]); }
    });
    browser.on("error", reject);
  });
  socket = new WebSocket(debuggerURL);
  await new Promise((resolve, reject) => { socket.addEventListener("open", resolve); socket.addEventListener("error", reject); });
  let id = 0, session;
  const pending = new Map();
  socket.addEventListener("message", event => {
    const message = JSON.parse(event.data);
     if (message.method === "Network.requestWillBeSent" && message.params.request.url.startsWith(process.env.VITE_API_ORIGIN)) {
       network.push(message.params.request.url);
       if (new URL(message.params.request.url).pathname === "/api/notifications/stream") streams.add(message.params.requestId);
     }
     if (message.method === "Network.loadingFailed" && streams.delete(message.params.requestId) && message.params.canceled) streamAborts++;
    if (message.method === "Runtime.exceptionThrown") exceptions.push(message.params.exceptionDetails.exception?.description || message.params.exceptionDetails.text);
    if (!message.id) return;
    const task = pending.get(message.id); pending.delete(message.id); clearTimeout(task?.timer);
    if (message.error) task?.reject(new Error(JSON.stringify(message.error)));
    else task?.resolve(message.result);
  });
  const call = (method, params = {}, sessionId = session) => new Promise((resolve, reject) => {
    const requestID = ++id;
    const timer = setTimeout(() => { pending.delete(requestID); reject(new Error(`CDP timed out: ${method}`)); }, 30000);
    pending.set(requestID, { resolve, reject, timer });
    socket.send(JSON.stringify({ id: requestID, method, params, sessionId }));
  });
  const { targetId } = await call("Target.createTarget", { url: "about:blank" });
  session = (await call("Target.attachToTarget", { targetId, flatten: true })).sessionId;
  await call("Runtime.enable"); await call("Page.enable"); await call("Network.enable");
  await call("Emulation.setFocusEmulationEnabled", { enabled: true });
  const metrics = async width => call("Emulation.setDeviceMetricsOverride", { width, height: 900, deviceScaleFactor: 1, mobile: false, screenWidth: width, screenHeight: 900 });
  await metrics(1500);
  await call("Page.addScriptToEvaluateOnNewDocument", { source: `
    if (!localStorage.getItem('revela_token')) localStorage.setItem('revela_token', 'user-17');
    const realNow = Date.now.bind(Date);
    window.__clockOffset = 0;
    Date.now = () => realNow() + window.__clockOffset;
    window.__hidden = false; window.__online = true;
    Object.defineProperty(document, 'visibilityState', { configurable: true, get: () => window.__hidden ? 'hidden' : 'visible' });
    Object.defineProperty(navigator, 'onLine', { configurable: true, get: () => window.__online });
  ` });
  const evaluate = async expression => {
    const response = await call("Runtime.evaluate", { expression, returnByValue: true, awaitPromise: true });
    if (response.exceptionDetails) throw new Error(response.exceptionDetails.exception?.description || response.exceptionDetails.text);
    return response.result?.value;
  };
  const wait = async (expression, label, timeout = 20000) => {
    const until = Date.now() + timeout;
    while (Date.now() < until) {
      try { if (await evaluate(`Boolean(${expression})`)) return; }
      catch (error) { if (!/navigated|Execution context was destroyed/i.test(error.message)) throw error; }
      await sleep(60);
    }
    if (label.includes("filtered analytics")) console.log("analytics diagnostic", {
      recent: calls.filter(call => call.path.startsWith("/api/analytics")).slice(-12),
      dom: await evaluate("document.querySelector('.analytics-page')?.innerText.slice(0,3500)"),
      filter: await evaluate("[...document.querySelectorAll('label')].find(e=>e.textContent==='Registry Status')?.parentElement.querySelector('select')?.value"),
    });
    throw new Error(`Timed out: ${label}; exceptions=${exceptions.slice(-2).join(" | ")}`);
  };
  const count = path => calls.filter(call => call.path === path).length;
  const waitForCalls = async (check, label, timeout = 15000) => {
    const until = Date.now() + timeout;
    while (Date.now() < until) { if (check()) return; await sleep(50); }
    throw new Error(`Timed out waiting for synthetic API: ${label}; last=${JSON.stringify(calls.slice(-10))}`);
  };
  const navigate = async path => { await call("Page.navigate", { url: origin + path }); await wait("document.querySelector('#app-refresh-mode')", `mounted ${path}`); };
  const choose = async mode => { await evaluate(`(() => { const e = document.querySelector('#app-refresh-mode'); e.value=${JSON.stringify(mode)}; e.dispatchEvent(new Event('change',{bubbles:true})); })()`); await wait(`document.querySelector('#app-refresh-mode').value === ${JSON.stringify(mode)}`, `${mode} mode`); };
  const last = () => evaluate("document.querySelector('.app-refresh-popover p')?.textContent.replace('Last successful refresh: ', '').replace('No successful refresh yet', 'No successful sync yet')");
  const refresh = () => evaluate("document.querySelector('button[aria-label=" + JSON.stringify("Refresh Data") + "]')?.click()");

  await navigate("/registry");
  await wait("document.querySelector('.app-refresh-controls [role=status]')?.textContent?.startsWith('Next refresh in')", "initial registry sync");
  assert.equal(await evaluate("document.querySelector('#app-refresh-mode').value"), "medium");
  assert.ok(network.some(url => new URL(url).pathname === "/api/registry/") && network.some(url => new URL(url).pathname === "/api/notifications/stream"), "CDP Network includes real local registry GET and SSE");
  await choose("easy");
  await call("Page.reload", { ignoreCache: true });
  await wait("document.querySelector('#app-refresh-mode')?.value === 'easy'", "mode survives reload");
  await evaluate("localStorage.setItem('revela_token', 'user-18')");
  await call("Page.reload", { ignoreCache: true });
  await wait("document.querySelector('#app-refresh-mode')?.value === 'medium'", "other user default");
  await choose("lax");
  await evaluate("localStorage.setItem('revela_token', 'user-17')");
  await call("Page.reload", { ignoreCache: true });
  await wait("document.querySelector('#app-refresh-mode')?.value === 'easy'", "first user's preference isolated");
  await wait("document.querySelector('.app-refresh-controls [role=status]')?.textContent?.startsWith('Next refresh in')", "reloaded registry");
  console.log("PASS browser: per-user Medium default and Easy/Lax persistence across real reloads");

  await choose("hard");
  const before = count("/api/registry/");
  const priorLast = await last();
  fixture.holdRegistry = true;
  await sleep(1100);
  await refresh();
  await wait(`document.querySelector('.app-refresh-controls [role=status]')?.textContent === 'Refreshing…'`, "manual in-flight");
  assert.equal(count("/api/registry/"), before + 1, "manual requests latest registry immediately");
  assert.equal(await last(), priorLast, "held refresh has not reset last sync");
  await evaluate("document.querySelector('button[aria-label=" + JSON.stringify("Refresh Data") + "]')?.click()");
  await evaluate("window.__clockOffset += 65000; window.dispatchEvent(new Event('focus')); document.dispatchEvent(new Event('visibilitychange'))");
  clients.forEach(client => client.write('data: {"type":"registry_updated"}\n\n'));
  await sleep(150);
  assert.equal(count("/api/registry/"), before + 1, "second click coalesces");
  fixture.holdRegistry = false; fixture.heldRegistry.splice(0).forEach(resolve => resolve());
   await wait("document.querySelector('.app-refresh-controls [role=status]')?.textContent === 'Changes available'", "manual completion with concurrent change notice");
  assert.notEqual(await last(), priorLast, "full success resets last sync");
  console.log("PASS simulated browser due-clock + real requests: manual/timer/focus/SSE overlap joins one in-flight GET; success resets deadline");

  const lastSuccess = await last();
  await sleep(1100); // Distinguish a false success timestamp from a same-second render.
  fixture.failBarangays = true;
  await refresh();
   await wait("document.querySelector('.app-refresh-controls [role=status]')?.textContent === 'Partially updated'", "partial failure");
   assert.ok(await evaluate("document.querySelector('.app-refresh-popover .app-refresh-errors')?.textContent.includes('Request')"), "failure details accessible in refresh popover");
  assert.equal(await last(), lastSuccess);
  assert.ok(await evaluate("document.body.textContent.includes('Synthetic Shop')"));
  await sleep(1100);
  fixture.failBarangays = true; fixture.failRegistry = true;
  await refresh();
  await wait("document.querySelector('.app-refresh-controls [role=status]')?.textContent === 'Refresh failed'", "full failure");
  assert.equal(await last(), lastSuccess);
  assert.ok(await evaluate("document.body.textContent.includes('Synthetic Shop')"));
  console.log("PASS browser: partial/full failure leaves prior registry and deadline intact");

  for (const mode of ["medium", "easy", "lax"]) {
    const oldLast = await last();
    await choose(mode);
    assert.equal(await last(), oldLast, "mode change alone never marks data fresh");
    const previousCount = count("/api/registry/");
    await refresh();
    await wait("document.querySelector('.app-refresh-controls [role=status]')?.textContent?.startsWith('Next refresh in')", `${mode} manual request completes`);
    assert.equal(count("/api/registry/"), previousCount + 1, `${mode} manual GET bypasses interval`);
  }
  console.log("PASS browser: manual GET starts and completes in Medium, Easy and Lax without waiting for the interval");

  const passiveCount = count("/api/registry/");
  const notificationCount = count("/api/notifications");
  clients.forEach(client => client.write('data: {"type":"registry_updated"}\n\n'));
   await wait(`document.querySelector('.app-refresh-controls [role=status]')?.textContent === 'Changes available'`, "passive stale marker");
  await sleep(250);
  assert.equal(count("/api/registry/"), passiveCount, "SSE does not cause registry read");
  assert.ok(count("/api/notifications") > notificationCount, "notification delivery still fetches notifications");
  console.log("PASS browser: real local SSE message marks data stale, continues notification delivery, no data GET");

  fixture.holdRegistry = true;
  const beforeFiltered = count("/api/registry/");
  await evaluate(`(() => { const e=[...document.querySelectorAll('select')].find(e=>[...e.options].some(option=>option.value==='Active') && [...e.options].some(option=>option.value==='Expired')); e.value='Active'; e.dispatchEvent(new Event('change',{bubbles:true})); })()`);
  await wait(`document.querySelector('.app-refresh-controls [role=status]')?.textContent === 'Refreshing…'`, "registry filter query in flight");
  assert.equal(count("/api/registry/"), beforeFiltered + 1);
  assert.equal(calls.filter(call => call.path === "/api/registry/").at(-1).query.includes("status=Active"), true);
  assert.equal(await last(), "No successful sync yet", "filtered registry cannot inherit prior query's deadline");
  fixture.holdRegistry = false; fixture.heldRegistry.splice(0).forEach(resolve => resolve());
  await wait("document.querySelector('.app-refresh-controls [role=status]')?.textContent?.startsWith('Next refresh in')", "registry filter refreshed");

  fixture.holdUsers = true;
  const usersBefore = count("/api/users/");
  await evaluate("document.querySelector('a[href=" + JSON.stringify("/users") + "]')?.click()");
  await wait("location.pathname === '/users' && document.querySelector('.app-refresh-controls [role=status]')?.textContent === 'Refreshing…'", "new users view in flight");
  await waitForCalls(() => count("/api/users/") > usersBefore, "Users initial request");
  assert.equal(count("/api/users/"), usersBefore + 1);
  assert.equal(await last(), "No successful sync yet", "new route cannot inherit registry freshness");
  fixture.holdUsers = false; fixture.heldUsers.splice(0).forEach(resolve => resolve());
  await wait("document.querySelector('.app-refresh-controls [role=status]')?.textContent?.startsWith('Next refresh in')", "users route");
  const usersNow = count("/api/users/");
  const registryNow = count("/api/registry/");
  await refresh();
  await wait(`document.querySelector('.app-refresh-controls [role=status]')?.textContent?.startsWith('Next refresh in')`, "users manual sync");
  assert.equal(count("/api/users/"), usersNow + 1);
  assert.equal(count("/api/registry/"), registryNow, "unmounted registry not fetched");
  console.log("PASS browser: filter/route changes have independent freshness; manual users refresh does not fetch registry");

  await choose("hard");
  await evaluate("window.__hidden = true; document.dispatchEvent(new Event('visibilitychange')); window.__clockOffset += 70000");
  const paused = count("/api/users/");
  await evaluate("window.dispatchEvent(new Event('focus')); document.dispatchEvent(new Event('visibilitychange'))");
  await sleep(150);
  assert.equal(count("/api/users/"), paused, "hidden tab stays paused");
  await evaluate("window.__hidden = false; document.dispatchEvent(new Event('visibilitychange')); window.dispatchEvent(new Event('focus'))");
  await wait(`document.querySelector('.app-refresh-controls [role=status]')?.textContent?.startsWith('Next refresh in')`, "visible due refresh");
  assert.equal(count("/api/users/"), paused + 1, "visibility and focus coalesce to one due request");
  await evaluate("window.__online = false; window.dispatchEvent(new Event('offline')); window.__clockOffset += 70000; window.dispatchEvent(new Event('focus'))");
  const offline = count("/api/users/");
  await sleep(150);
  assert.equal(count("/api/users/"), offline);
  await evaluate("window.__online = true; window.dispatchEvent(new Event('online')); window.dispatchEvent(new Event('focus'))");
  await wait(`document.querySelector('.app-refresh-controls [role=status]')?.textContent?.startsWith('Next refresh in')`, "online due refresh");
  assert.equal(count("/api/users/"), offline + 1);
  console.log("PASS simulated browser clock/visibility/network: hidden/offline pause, one due refresh on resume");

  if (process.argv.includes("--elapsed-hard")) {
    const beforeTimer = count("/api/users/");
    const start = performance.now();
    while (count("/api/users/") === beforeTimer && performance.now() - start < 68000) await sleep(100);
    const elapsed = performance.now() - start;
    assert.ok(elapsed >= 58000 && elapsed < 68000, `real Hard timer elapsed ${elapsed.toFixed(0)}ms`);
    await sleep(200);
    assert.equal(count("/api/users/"), beforeTimer + 1, "one actual scheduled timer request");
    console.log(`PASS elapsed-time browser: Hard timer issued one GET after ${elapsed.toFixed(0)}ms`);
  }

  await navigate("/analytics");
  await wait("document.querySelector('.analytics-page') && document.querySelector('.app-refresh-controls [role=status]')?.textContent?.startsWith('Next refresh in')", "analytics initial load");
  await choose("easy");
  await evaluate("[...document.querySelectorAll('h3')].find(e => e.textContent.includes('Data filters'))?.parentElement?.click()");
  await wait("[...document.querySelectorAll('label')].some(e=>e.textContent==='Registry Status')", "filter panel opened");
  await evaluate(`(() => { const e=[...document.querySelectorAll('label')].find(e=>e.textContent==='Registry Status').parentElement.querySelector('select'); e.value='Active'; e.dispatchEvent(new Event('change',{bubbles:true})); [...document.querySelectorAll('button')].find(b=>b.textContent.trim()==='Apply filters').click(); })()`);
  await wait("document.querySelector('.analytics-page')?.textContent.includes('777')", "Active-filtered analytics loaded");
  await wait("document.querySelector('.analytics-page [role=alert]')?.textContent.includes('historical')", "15-minute policy labels old analytics", 15000);
  assert.ok(await evaluate("document.querySelector('.analytics-page [role=alert]')?.textContent.includes('Last computed:')"));
  await choose("lax");
  assert.ok(await evaluate("document.querySelector('.analytics-page')?.textContent.includes('777') && document.querySelector('.analytics-page [role=alert]')?.textContent.includes('historical')"));
  await evaluate(`(() => { const e=[...document.querySelectorAll('label')].find(e=>e.textContent==='Registry Status').parentElement.querySelector('select'); e.value='Expired'; e.dispatchEvent(new Event('change',{bubbles:true})); [...document.querySelectorAll('button')].find(b=>b.textContent.trim()==='Apply filters').click(); })()`);
  await wait("document.querySelector('.analytics-page')?.textContent.includes('888')", "Expired-filtered analytics loaded");
  assert.ok(await evaluate("!document.querySelector('.analytics-page')?.textContent.includes('777')"), "old filter result not shown under new filter");
  await wait("document.querySelector('.analytics-page [role=alert]')?.textContent.includes('historical')", "filtered Lax historical timestamp", 15000);
  console.log("PASS browser: Easy/Lax retain timestamped historical analytics, Active/Expired filters isolate results (server age simulated)");

  const view = async (path, label) => {
    const linked = await evaluate(`Boolean(document.querySelector('a[href=${JSON.stringify(path)}]'))`);
    if (linked) await evaluate(`document.querySelector('a[href=${JSON.stringify(path)}]').click()`);
    else await evaluate(`history.pushState(null, '', ${JSON.stringify(path)}); window.dispatchEvent(new PopStateEvent('popstate'))`);
    await wait(`location.pathname === ${JSON.stringify(path)} && document.querySelector('.app-refresh-controls [role=status]')?.textContent?.startsWith('Next refresh in')`, label, 25000);
  };
  const passive = async (event, paths) => {
    const baseline = new Map(paths.map(path => [path, count(path)]));
    clients.forEach(client => client.write(`data: {"type":"${event}"}\n\n`));
    await sleep(220);
    for (const [path, before] of baseline) assert.equal(count(path), before, `${event} must not fetch ${path}`);
  };
  const noMutationRefresh = () => assert.deepEqual(calls.filter(call =>
    call.method !== "GET" && /\/api\/(flags\/(run-detection|reconcile)|registry\/(upload|sync|reverify|snap-unresolved))/.test(call.path)), []);

  await view("/home", "Overview initial reads");
  const homePaths = ["/api/analytics/all", "/api/flags/", "/api/inspections/", "/api/users/"];
  const homeBefore = Object.fromEntries(homePaths.map(path => [path, count(path)]));
  fixture.holds.add("/api/inspections/");
  const homeLast = await last();
  await refresh();
  await wait("document.querySelector('.app-refresh-controls [role=status]')?.textContent === 'Refreshing…'", "Overview awaits inspections");
  for (const path of homePaths) assert.equal(count(path), homeBefore[path] + (path === "/api/analytics/all" ? 2 : 1), `Overview manual reads ${path} once per required dataset`);
  assert.equal(await last(), homeLast);
  release("/api/inspections/");
  await wait("document.querySelector('.app-refresh-controls [role=status]')?.textContent?.startsWith('Next refresh in')", "Overview completes");
  await sleep(1100);
  const homeSuccess = await last();
  fixture.failures.add("/api/inspections/");
  await refresh();
  await wait("document.querySelector('.app-refresh-controls [role=status]')?.textContent === 'Partially updated'", "Overview partial failure");
  assert.equal(await last(), homeSuccess);
  assert.ok(await evaluate("document.body.textContent.includes('4,321')"), "Overview retains the last successful KPI snapshot");
  await passive("registry_updated", homePaths);
  fixture.holds.add("/api/analytics/all:summary");
  await refresh();
  await wait("document.querySelector('.app-refresh-controls [role=status]')?.textContent === 'Refreshing…'", "Overview summary held for navigation");
  await evaluate("document.querySelector('a[href=" + JSON.stringify("/map") + "]')?.click()");
  await wait("location.pathname === '/map' && document.querySelector('.app-refresh-controls [role=status]')?.textContent?.startsWith('Next refresh in')", "Map after Overview unmount", 25000);
  const mapLast = await last();
  release("/api/analytics/all:summary");
  await sleep(250);
  assert.equal(await last(), mapLast, "late Overview completion cannot change Map freshness");
  noMutationRefresh();
  console.log("PASS browser Overview: 5 required reads, awaited/partial/stale and late unmount isolation; no mutation");

  const mapPaths = ["/api/flags/", "/api/analytics/ops-rankings", "/api/registry/barangays", "/api/users/", "/api/flags/detection-quota", "/api/flags/places-usage"];
  const mapBefore = Object.fromEntries(mapPaths.map(path => [path, count(path)]));
  fixture.holds.add("/api/analytics/ops-rankings");
  const mapSuccess = await last();
  await refresh();
  await wait("document.querySelector('.app-refresh-controls [role=status]')?.textContent === 'Refreshing…'", "Map awaits rankings");
  await waitForCalls(() => mapPaths.every(path => count(path) > mapBefore[path]), "Map required reads");
  for (const path of mapPaths) assert.equal(count(path), mapBefore[path] + 1, `Map manual reads ${path} once`);
  assert.equal(await last(), mapSuccess);
  release("/api/analytics/ops-rankings");
  await wait("document.querySelector('.app-refresh-controls [role=status]')?.textContent?.startsWith('Next refresh in')", "Map completed rankings");
  const mapFullSuccess = await last();
  await sleep(1100);
  fixture.failures.add("/api/analytics/ops-rankings");
  await refresh();
  await wait("document.querySelector('.app-refresh-controls [role=status]')?.textContent === 'Partially updated'", "Map partial ranking failure");
  assert.equal(await last(), mapFullSuccess);
  assert.ok(await evaluate("document.body.textContent.includes('Synthetic Map Flag')"), "Map preserves flags after ranking failure");
  await passive("flag_updated", mapPaths);
  fixture.holds.add("/api/flags/");
  await refresh();
  await wait("document.querySelector('.app-refresh-controls [role=status]')?.textContent === 'Refreshing…'", "Map held flags");
  await evaluate("document.querySelector('a[href=" + JSON.stringify("/inspections") + "]')?.click()");
  await wait("location.pathname === '/inspections' && document.querySelector('.app-refresh-controls [role=status]')?.textContent?.startsWith('Next refresh in')", "Inspection after Map unmount", 25000);
  const inspectionLast = await last();
  release("/api/flags/");
  await sleep(250);
  assert.equal(await last(), inspectionLast);
  noMutationRefresh();
  console.log("PASS browser Map: required flags/rankings/auxiliary GETs, awaited/partial/stale and abort on unmount; no detection POST");

  const dispatchBefore = count("/api/inspections/");
  fixture.holds.add("/api/inspections/");
  const dispatchLast = await last();
  await refresh();
  await wait("document.querySelector('.app-refresh-controls [role=status]')?.textContent === 'Refreshing…'", "Dispatch held report list");
  assert.equal(count("/api/inspections/"), dispatchBefore + 1);
  assert.ok(calls.filter(c => c.path === "/api/inspections/").at(-1).query.includes("limit=100"));
  assert.equal(await last(), dispatchLast);
  release("/api/inspections/");
  await wait("document.querySelector('.app-refresh-controls [role=status]')?.textContent?.startsWith('Next refresh in')", "Dispatch manual complete");
  const dispatchSuccess = await last();
  await sleep(1100);
  fixture.failures.add("/api/inspections/");
  await refresh();
  await wait("document.querySelector('.app-refresh-controls [role=status]')?.textContent === 'Refresh failed'", "Dispatch one-endpoint failure");
  assert.equal(await last(), dispatchSuccess);
  assert.ok(await evaluate("document.body.textContent.includes('Synthetic Inspection')"));
  await passive("inspection_updated", ["/api/inspections/"]);
  fixture.holds.add("/api/inspections/");
  await refresh();
  await wait("document.querySelector('.app-refresh-controls [role=status]')?.textContent === 'Refreshing…'", "Dispatch unmount request");
  await evaluate("document.querySelector('a[href=" + JSON.stringify("/reports") + "]')?.click()");
  await wait("location.pathname === '/reports' && document.querySelector('.app-refresh-controls [role=status]')?.textContent?.startsWith('Next refresh in')", "Reports after Dispatch unmount", 25000);
  const reportsLast = await last();
  release("/api/inspections/");
  await sleep(220);
  assert.equal(await last(), reportsLast);
  noMutationRefresh();
  console.log("PASS browser Inspection Dispatch: required report GET, awaited/failure/stale and unmount isolation; single endpoint has no partial state");

  const reportsBefore = count("/api/analytics/demographic-reports");
  fixture.holds.add("/api/analytics/demographic-reports");
  await refresh();
  await wait("document.querySelector('.app-refresh-controls [role=status]')?.textContent === 'Refreshing…'", "Reports held demographic GET");
  assert.equal(count("/api/analytics/demographic-reports"), reportsBefore + 1);
  assert.equal(await last(), reportsLast);
  release("/api/analytics/demographic-reports");
  await wait("document.querySelector('.app-refresh-controls [role=status]')?.textContent?.startsWith('Next refresh in')", "Reports manual complete");
  const reportsSuccess = await last();
  await sleep(1100);
  fixture.failures.add("/api/analytics/demographic-reports");
  await refresh();
  await wait("document.querySelector('.app-refresh-controls [role=status]')?.textContent === 'Refresh failed'", "Reports one-endpoint failure");
  assert.equal(await last(), reportsSuccess);
  assert.ok(await evaluate("document.querySelector('.export-reports-page')?.textContent.includes('123')"), "Reports preserves demographics");
   await wait("[...document.querySelectorAll('.export-reports-page [role=alert]')].some(el => el.textContent.includes('Showing the last successful report snapshot from'))", "reports failure banner");
  await passive("registry_updated", ["/api/analytics/demographic-reports"]);
  fixture.holds.add("/api/analytics/demographic-reports");
  await refresh();
  await wait("document.querySelector('.app-refresh-controls [role=status]')?.textContent === 'Refreshing…'", "Reports unmount request");
  await evaluate("document.querySelector('a[href=" + JSON.stringify("/settings") + "]')?.click()");
  await wait("location.pathname === '/settings' && document.querySelector('.app-refresh-controls [role=status]')?.textContent?.startsWith('Next refresh in')", "Settings after Reports unmount", 25000);
  const settingsLast = await last();
  release("/api/analytics/demographic-reports");
  await sleep(220);
  assert.equal(await last(), settingsLast);
  noMutationRefresh();
  console.log("PASS browser Reports: demographic GET awaited, failed refresh retains snapshot, passive event and unmount isolation; no partial for single endpoint");

  const settingsPaths = ["/api/analytics/wlc-config", "/api/inspections/evidence-storage-stats"];
  const settingsBefore = Object.fromEntries(settingsPaths.map(path => [path, count(path)]));
  fixture.holds.add("/api/inspections/evidence-storage-stats");
  await refresh();
  await wait("document.querySelector('.app-refresh-controls [role=status]')?.textContent === 'Refreshing…'", "Settings awaits evidence usage");
  for (const path of settingsPaths) assert.equal(count(path), settingsBefore[path] + 1, `Settings manual GET ${path}`);
  assert.equal(await last(), settingsLast);
  release("/api/inspections/evidence-storage-stats");
  await wait("document.querySelector('.app-refresh-controls [role=status]')?.textContent?.startsWith('Next refresh in')", "Settings manual complete");
  const settingsSuccess = await last();
  await sleep(1100);
  fixture.failures.add("/api/inspections/evidence-storage-stats");
  await refresh();
  await wait("document.querySelector('.app-refresh-controls [role=status]')?.textContent === 'Partially updated'", "Settings partial failure");
  assert.equal(await last(), settingsSuccess);
  assert.ok(await evaluate("document.querySelector('.settings-page')?.textContent.includes('37 MB')"), "Settings retains evidence usage");
  await passive("registry_updated", settingsPaths);
  fixture.holds.add("/api/inspections/evidence-storage-stats");
  await refresh();
  await wait("document.querySelector('.app-refresh-controls [role=status]')?.textContent === 'Refreshing…'", "Settings unmount request");
  await evaluate("history.pushState(null,'','/inspections/calendar'); window.dispatchEvent(new PopStateEvent('popstate'))");
  await wait("location.pathname === '/inspections/calendar' && document.querySelector('.app-refresh-controls [role=status]')?.textContent?.startsWith('Next refresh in')", "Calendar after Settings unmount", 25000);
  const calendarLast = await last();
  release("/api/inspections/evidence-storage-stats");
  await sleep(220);
  assert.equal(await last(), calendarLast);
  noMutationRefresh();
  console.log("PASS browser Settings: policy/storage GETs, awaited/partial/stale and unmount isolation; no mutation");

  const deadlinesBefore = count("/api/inspections/");
  fixture.holds.add("/api/inspections/");
  await refresh();
  await wait("document.querySelector('.app-refresh-controls [role=status]')?.textContent === 'Refreshing…'", "Calendar deadline pagination held");
  assert.equal(count("/api/inspections/"), deadlinesBefore + 1);
  assert.ok(calls.filter(c => c.path === "/api/inspections/").at(-1).query.includes("limit=200"));
  assert.equal(await last(), calendarLast);
  release("/api/inspections/");
  await wait("document.querySelector('.app-refresh-controls [role=status]')?.textContent?.startsWith('Next refresh in')", "Calendar deadline manual complete");
  const deadlineSuccess = await last();
  await sleep(1100);
  fixture.failures.add("/api/inspections/");
  await refresh();
  await wait("document.querySelector('.app-refresh-controls [role=status]')?.textContent === 'Refresh failed'", "Calendar deadline failure");
  assert.equal(await last(), deadlineSuccess);
  assert.ok(await evaluate("document.querySelector('.inspection-calendar-page')?.textContent.includes('Synthetic Inspection')"), "Calendar preserves deadline data");
  await passive("inspection_updated", ["/api/inspections/", "/api/inspections/calendar"]);
  await evaluate("document.querySelector('#inspection-calendar-tab-activity')?.click()");
  await wait("document.querySelector('#inspection-calendar-tab-activity')?.getAttribute('aria-selected') === 'true' && document.querySelector('.app-refresh-controls [role=status]')?.textContent?.startsWith('Next refresh in')", "Calendar activity switched", 25000);
  const activityBefore = count("/api/inspections/calendar");
  fixture.holds.add("/api/inspections/calendar");
  const activityLast = await last();
  await refresh();
  await wait("document.querySelector('.app-refresh-controls [role=status]')?.textContent === 'Refreshing…'", "Calendar activity held");
  assert.equal(count("/api/inspections/calendar"), activityBefore + 1);
  assert.equal(await last(), activityLast);
  release("/api/inspections/calendar");
  await wait("document.querySelector('.app-refresh-controls [role=status]')?.textContent?.startsWith('Next refresh in')", "Calendar activity manual complete");
  const activitySuccess = await last();
  await sleep(1100);
  fixture.failures.add("/api/inspections/calendar");
  await refresh();
  await wait("document.querySelector('.app-refresh-controls [role=status]')?.textContent === 'Refresh failed'", "Calendar activity failure");
  assert.equal(await last(), activitySuccess);
  assert.ok(await evaluate("document.querySelector('.inspection-calendar-page')?.textContent.includes('1')"), "Calendar retains activity counts");
  await passive("inspection_updated", ["/api/inspections/calendar"]);
  fixture.holds.add("/api/inspections/calendar");
  await refresh();
  await wait("document.querySelector('.app-refresh-controls [role=status]')?.textContent === 'Refreshing…'", "Calendar unmount request");
  await evaluate("document.querySelector('a[href=" + JSON.stringify("/registry") + "]')?.click()");
  await wait("location.pathname === '/registry' && document.querySelector('.app-refresh-controls [role=status]')?.textContent?.startsWith('Next refresh in')", "Registry after Calendar unmount", 25000);
  const finalRegistry = await last();
  release("/api/inspections/calendar");
  await sleep(220);
  assert.equal(await last(), finalRegistry);
  noMutationRefresh();
  console.log("PASS browser Calendar: deadlines/activity exact GETs, awaited/failure/stale and unmount isolation; no partial for single dataset");

  if (process.argv.includes("--cache-revisits")) {
    const routes = [
      ["/registry", "Synthetic Shop"], ["/users", "Synthetic User 17"], ["/home", "4,321"],
      ["/map", "Synthetic Map Flag"], ["/inspections", "Synthetic Inspection"],
      ["/reports", "123"], ["/settings", "37 MB"], ["/inspections/calendar", "Synthetic Inspection"],
      ["/analytics", "123"],
    ];
    const markers = {
      "/registry": ".page-title", "/users": ".page-title", "/home": ".overview-page",
      "/map": ".map-shell", "/inspections": ".inspection-dispatch-page", "/reports": ".export-reports-page",
      "/settings": ".settings-page", "/inspections/calendar": ".inspection-calendar-page", "/analytics": ".analytics-page",
    };
    const routeTo = async path => {
      const linked = await evaluate(`Boolean(document.querySelector('a[href=${JSON.stringify(path)}]'))`);
      if (linked) await evaluate(`document.querySelector('a[href=${JSON.stringify(path)}]').click()`);
      else await evaluate(`history.pushState(null, '', ${JSON.stringify(path)}); window.dispatchEvent(new PopStateEvent('popstate'))`);
      const heading = path === "/registry" ? "Business Registry" : path === "/users" ? "User Management" : null;
      await wait(`location.pathname === ${JSON.stringify(path)} && document.querySelector(${JSON.stringify(markers[path])})${heading ? ` && document.querySelector('h1.page-title')?.textContent === ${JSON.stringify(heading)}` : ""}`, `route ${path}`);
    };
    const reads = () => calls.filter(call => call.method === "GET" && !/\/api\/(auth|notifications)/.test(call.path)).length;
    for (const [path, content] of routes) {
      const separator = path === "/users" ? "/registry" : "/users";
      await routeTo(separator);
      await wait(`document.querySelector('.app-refresh-popover p')?.textContent.includes('Last successful refresh:') && !document.querySelector('.app-refresh-popover p')?.textContent.includes('No successful refresh yet')`, `separator cached ${separator}`);
      const before = reads();
      const start = performance.now();
      await routeTo(path);
      const visible = await evaluate(`document.querySelector('.saas-content')?.textContent.includes(${JSON.stringify(content)})`);
      const elapsed = Math.round(performance.now() - start);
      await sleep(120);
      assert.ok(visible, `${path} must paint cached content immediately`);
      assert.equal(reads(), before, `${path} must not issue a navigation application-data GET`);
      console.log(`PASS cached revisit ${path}: painted in ${elapsed}ms, zero application-data GETs`);
    }
    if (process.argv.includes("--cache-behavior")) {
      await routeTo("/registry");
      await refresh();
      await wait("document.querySelector('.app-refresh-controls [role=status]')?.textContent?.startsWith('Next refresh in')", "fresh registry before due revisit");
      await choose("hard");
      const previousDeadline = await last();
      await routeTo("/users");
      fixture.delayRegistryMs = 750;
      const beforeDue = count("/api/registry/");
      await evaluate("window.__clockOffset += 70000");
      await routeTo("/registry");
      assert.ok(await evaluate("document.body.textContent.includes('Synthetic Shop')"), "due revisit paints cached registry");
      assert.equal(await last(), previousDeadline, "deadline is unchanged while the due read is pending");
      await waitForCalls(() => count("/api/registry/") > beforeDue, "due revisit background GET");
      assert.equal(count("/api/registry/"), beforeDue + 1);
      await wait("document.querySelector('.app-refresh-controls [role=status]')?.textContent?.startsWith('Next refresh in')", "due revisit completion", 5000);
      assert.notEqual(await last(), previousDeadline);
      fixture.delayRegistryMs = 0;
      console.log("PASS due revisit: cached content visible before delayed GET; one background request resets deadline only on completion");

      await choose("lax");
      fixture.holdRegistry = true;
      const manualBefore = count("/api/registry/");
      const manualLast = await last();
      await refresh();
      await wait("document.querySelector('.app-refresh-controls [role=status]')?.textContent === 'Refreshing…'", "manual cached refresh pending");
      await waitForCalls(() => count("/api/registry/") > manualBefore, "manual cached GET");
      assert.ok(await evaluate("document.body.textContent.includes('Synthetic Shop')"), "manual refresh retains cached rows");
      assert.equal(await last(), manualLast);
      fixture.holdRegistry = false; fixture.heldRegistry.splice(0).forEach(resolve => resolve());
      await wait("document.querySelector('.app-refresh-controls [role=status]')?.textContent?.startsWith('Next refresh in')", "manual cached refresh completed");
      console.log("PASS manual cached refresh: old data stays visible until required GET succeeds");

      const changeStatus = value => evaluate(`(() => { const e=[...document.querySelectorAll('select')].find(e=>[...e.options].some(o=>o.value==='Active')&&[...e.options].some(o=>o.value==='Expired')); e.value=${JSON.stringify(value)};e.dispatchEvent(new Event('change',{bubbles:true})); })()`);
      const firstActive = count("/api/registry/");
      await changeStatus("Active");
      await waitForCalls(() => count("/api/registry/") > firstActive, "uncached Active filter initial GET");
      await wait("document.querySelector('.app-refresh-controls [role=status]')?.textContent?.startsWith('Next refresh in')", "first Active filter loaded");
      await changeStatus("All Status");
      await wait("document.querySelector('tbody')?.textContent.includes('Synthetic Shop')", "default query restored");
      const beforeCachedFilter = count("/api/registry/");
      await changeStatus("Active");
      await wait("document.querySelector('.app-refresh-popover p')?.textContent.includes('Last successful refresh:') && !document.querySelector('.app-refresh-popover p')?.textContent.includes('No successful refresh yet')", "previously loaded Active query");
      if (count("/api/registry/") !== beforeCachedFilter) console.log("filter-cache diagnostic", {
        beforeCachedFilter, after: count("/api/registry/"), recent: calls.filter(call => call.path === "/api/registry/").slice(-5), last: await last(),
      });
      assert.equal(count("/api/registry/"), beforeCachedFilter, "cached filter reuses its query data");
      fixture.holdRegistry = true;
      await changeStatus("Expired");
      await wait("document.querySelector('.app-refresh-controls [role=status]')?.textContent === 'Refreshing…'", "new Expired query");
      assert.equal(await last(), "No successful sync yet", "new filter cannot inherit another query deadline");
      const beforeNewFilter = count("/api/registry/");
      await waitForCalls(() => count("/api/registry/") > beforeNewFilter || fixture.heldRegistry.length > 0, "new filter GET");
      assert.ok(!await evaluate("document.querySelector('tbody')?.textContent.includes('Synthetic Shop')"), "old query rows are not shown for new filter");
      fixture.holdRegistry = false; fixture.heldRegistry.splice(0).forEach(resolve => resolve());
      await wait("document.querySelector('tbody')?.textContent.includes('Expired Synthetic Shop')", "new filtered rows");
      const afterNewFilter = count("/api/registry/");
      await changeStatus("Active");
      await wait("document.querySelector('tbody')?.textContent.includes('Synthetic Shop')", "Active filter cache restored");
      assert.ok(!await evaluate("document.querySelector('tbody')?.textContent.includes('Expired Synthetic Shop')"));
      assert.equal(count("/api/registry/"), afterNewFilter);
      console.log("PASS query cache: prior filter reused, new filter fetched once, and rows stayed isolated");

      const preservedLast = await last();
      await sleep(1100);
      fixture.failRegistry = true;
      fixture.failBarangays = true;
      await refresh();
      await wait("document.querySelector('.app-refresh-controls [role=status]')?.textContent === 'Refresh failed'", "cached query failed refresh");
      assert.equal(await last(), preservedLast);
      assert.ok(await evaluate("document.querySelector('tbody')?.textContent.includes('Synthetic Shop')"));
      await routeTo("/users");
      await routeTo("/registry");
      const beforeFailedReturn = count("/api/registry/");
      await changeStatus("Active");
      await wait("document.querySelector('.app-refresh-controls [role=status]')?.textContent === 'Refresh failed'", "cached query failure status survives route change");
      assert.equal(count("/api/registry/"), beforeFailedReturn, "failed cached query honors backoff on revisit");
      assert.equal(await last(), preservedLast);
      assert.ok(await evaluate("document.querySelector('tbody')?.textContent.includes('Synthetic Shop')"));
      await refresh();
      await wait("document.querySelector('.app-refresh-controls [role=status]')?.textContent?.startsWith('Next refresh in')", "manual retry clears prior failure");
      console.log("PASS failed cached revisit: data/error/deadline persist; manual retry still works");

      await routeTo("/home");
      const homeSnapshot = await last();
      await routeTo("/users");
      await evaluate("[...document.querySelectorAll('button')].find(e=>e.textContent.includes('Create User'))?.click()");
      await wait("document.querySelector('.um-modal .um-form')", "local user creation form");
      await wait("document.querySelector('.um-input-group input')?.value.length >= 8", "synthetic generated password");
      await evaluate(`(() => { const fields=[...document.querySelectorAll('.um-form input')]; const setter=Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set;
        for (const [input,value] of [[fields[0],'Cached User Change'],[fields[1],'cache-change@example.test']]) { setter.call(input,value); input.dispatchEvent(new Event('input',{bubbles:true})); }
        document.querySelector('.um-form button[type=submit]').click(); })()`);
      await waitForCalls(() => Boolean(fixture.addedUser), "synthetic successful user POST");
      await wait("!document.querySelector('.um-modal')", "user mutation completed");
      const homeBeforeMutation = count("/api/analytics/all");
      fixture.holds.add("/api/analytics/all:summary");
      await routeTo("/home");
      assert.ok(await evaluate("document.body.textContent.includes('4,321')"), "mutated dependent view paints cached content");
      assert.equal(await last(), homeSnapshot, "local mutation does not claim a fresh snapshot before re-read");
      await waitForCalls(() => count("/api/analytics/all") > homeBeforeMutation, "local mutation invalidated dependent Home cache");
      release("/api/analytics/all:summary");
      await wait("document.querySelector('.app-refresh-controls [role=status]')?.textContent?.startsWith('Next refresh in')", "mutation-triggered due refresh");
      assert.ok(calls.some(call => call.method === "POST" && call.path === "/api/users/"));
      noMutationRefresh();
      console.log("PASS local successful mutation: dependent cached view stays visible, then revalidates once; detection/import untouched");
    }
  }

  if (process.argv.includes("--trace-revisit")) {
    const previousDeadline = await last();
    await view("/users", "Users before registry revisit trace");
    fixture.delayRegistryMs = 800;
    const beforeRevisit = count("/api/registry/");
    const start = performance.now();
    await evaluate("document.querySelector('a[href=" + JSON.stringify("/registry") + "]')?.click()");
    await wait("location.pathname === '/registry' && document.querySelector('#app-refresh-mode')", "registry revisit trace");
    const immediate = await evaluate("document.body.textContent.includes('Synthetic Shop')");
    await wait("document.body.textContent.includes('Synthetic Shop')", "registry revisit content", 5000);
    console.log("TRACE registry revisit", { immediatelyVisible: immediate, redundantGets: count("/api/registry/") - beforeRevisit,
      visibleAfterMs: Math.round(performance.now() - start), previousDeadline, returnDeadline: await last(), syntheticApiDelayMs: fixture.delayRegistryMs });
    fixture.delayRegistryMs = 0;
  }

   const layout = async () => evaluate(`(() => { const nav=document.querySelector('.top-navbar'); const rect=e=>({left:e.getBoundingClientRect().left,right:e.getBoundingClientRect().right,top:e.getBoundingClientRect().top,bottom:e.getBoundingClientRect().bottom}); return {viewport:innerWidth, nav:rect(nav), scroll:nav.scrollWidth, client:nav.clientWidth, children:[...nav.children].filter(e=>e.getBoundingClientRect().width).map(rect), actions:[...document.querySelectorAll('.app-refresh-main > *, .top-nav-separator, .notification-wrapper, .nav-profile, .nav-logout')].map(rect), title:document.querySelector('.top-nav-title')?.textContent}; })()`);
   const fits = view => view.actions.every(rect => rect.left >= view.nav.left - 1 && rect.right <= view.viewport + 1 && rect.top >= view.nav.top - 1 && rect.bottom <= view.nav.bottom + 1);
   const overlaps = view => view.actions.some((rect, index) => view.actions.slice(index + 1).some(other =>
     Math.min(rect.right, other.right) - Math.max(rect.left, other.left) > 1 &&
     Math.min(rect.bottom, other.bottom) - Math.max(rect.top, other.top) > 1));
   for (const width of [1500, 820, 560]) {
     await metrics(width); await sleep(250);
     const view = await layout();
     assert.ok(fits(view) && !overlaps(view) && view.scroll <= view.client + 1, JSON.stringify(view));
     assert.ok(await evaluate("document.querySelector('.nav-logout')?.getBoundingClientRect().width > 0 && document.querySelector('.notification-wrapper > button')?.getBoundingClientRect().width > 0"));
     if (captures) {
       const { data } = await call("Page.captureScreenshot", { format: "png", captureBeyondViewport: false });
       writeFileSync(join(captures, `navbar-${width}.png`), Buffer.from(data, "base64"));
     }
     console.log(`PASS browser navbar layout: ${width}px`, view);
   }
   if (captures) console.log("Local navbar screenshots:", captures);
   await evaluate("document.querySelector('.app-refresh-details summary').click()");
   assert.ok(await evaluate("document.querySelector('.app-refresh-details').open && document.querySelector('.app-refresh-popover').textContent.includes('Last successful refresh:')"));
   await evaluate("document.querySelector('.app-refresh-details summary').dispatchEvent(new KeyboardEvent('keydown', {key:'Escape', bubbles:true}))");
   assert.equal(await evaluate("document.querySelector('.app-refresh-details').open"), false);
   await evaluate("document.querySelector('.notification-wrapper > button').click()");
   await wait("document.querySelector('.notification-connection')?.textContent.includes('Notification stream connected')", "notification connection label");
   await evaluate("document.querySelector('.notification-wrapper > button').click()");
  await metrics(390);
   await wait("document.querySelector('.restricted-root') && !document.querySelector('#app-refresh-mode')", "existing phone access notice");
   console.log("PASS browser: phone-sized viewport still shows existing device gate");
   await metrics(1500);
   await wait("document.querySelector('.nav-logout')", "navbar restored after gate");
   const streamAbortsBefore = streamAborts;
   await evaluate("document.querySelector('.nav-logout').click()");
   await wait("document.querySelector('.swal2-confirm')", "existing sign-out confirmation");
   assert.equal(await evaluate("localStorage.getItem('revela_token')"), "user-17", "confirmation does not sign out early");
   await evaluate("document.querySelector('.swal2-cancel').click()");
   await wait("!document.querySelector('.swal2-confirm')", "cancelled sign-out closes confirmation");
   assert.equal(await evaluate("localStorage.getItem('revela_token')"), "user-17", "cancel keeps session");
   await evaluate("document.querySelector('.nav-logout').click()");
   await wait("document.querySelector('.swal2-confirm')", "confirmed sign-out dialog");
   await evaluate("document.querySelector('.swal2-confirm').click()");
   await wait("location.pathname === '/' && !localStorage.getItem('revela_token')", "sign-out clears synthetic session and redirects");
   assert.ok(calls.some(call => call.path === "/api/auth/logout" && call.method === "POST"), "existing server revoke called");
   await wait("document.querySelector('.saas-sidebar') == null", "dashboard unmounted");
    await waitForCalls(() => streamAborts > streamAbortsBefore, "notification stream aborted on sign-out");
    console.log("PASS browser: confirmed navbar logout revokes synthetic session, clears storage, unmounts SSE and redirects");
    if (process.argv.includes("--cache-behavior")) {
      fixture.holds.add("/api/analytics/all:summary");
      await evaluate("history.pushState(null,'','/login'); window.dispatchEvent(new PopStateEvent('popstate'))");
      await wait("document.querySelector('.signin-btn')", "local synthetic login screen");
      await evaluate(`(() => { const setter=Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set;
        const fields=[...document.querySelectorAll('.glass-input')];
        for (const [field,value] of [[fields[0],'user18@example.test'],[fields[1],'SyntheticOnly-123']]) { setter.call(field,value); field.dispatchEvent(new Event('input',{bubbles:true})); }
      })()`);
      await evaluate("document.querySelector('.signin-btn').click()");
      await waitForCalls(() => calls.some(call => call.method === "POST" && call.path === "/api/auth/login"), "local synthetic login POST");
      await wait("location.pathname === '/home' && document.querySelector('.app-refresh-controls')", "new authenticated user view");
      await waitForCalls(() => (fixture.pending.get("/api/analytics/all:summary") || []).length > 0, "new account has an uncached analytics load");
      assert.equal(await last(), "No successful sync yet", "new account cannot inherit previous user's deadline");
      assert.ok(!await evaluate("document.querySelector('.overview-page')?.textContent.includes('4,321')"), "new account cannot see previous user's cached KPI");
      release("/api/analytics/all:summary");
      await wait("document.querySelector('.overview-page')?.textContent.includes('4,321')", "new account's own snapshot arrived");
      console.log("PASS browser: logout/account change discarded in-memory datasets and required a new GET");
    }
  assert.equal(exceptions.length, 0, `browser exceptions: ${exceptions.join(" | ")}`);
  console.log(`Synthetic API requests observed in CDP Network: ${network.length}`);
} finally {
  socket?.close();
  if (browser && browser.exitCode === null) browser.kill();
  await server.close();
  api.closeAllConnections(); await new Promise(resolve => api.close(resolve));
  await rm(profile, { recursive: true, force: true, maxRetries: 10, retryDelay: 300 });
}
