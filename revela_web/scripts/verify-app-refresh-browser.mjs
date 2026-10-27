// Synthetic local API + real Edge/CDP requests. Never connects to production.
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { createServer as createHttpServer } from "node:http";
import { existsSync, mkdtempSync } from "node:fs";
import { rm } from "node:fs/promises";
import { join } from "node:path";
import { createServer as createViteServer } from "vite";

const edge = process.env.EDGE_BINARY || "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe";
const tempRoot = process.env.LOCALAPPDATA && join(process.env.LOCALAPPDATA, "Temp", "opencode");
assert.ok(existsSync(edge) && tempRoot && existsSync(tempRoot), "Local Edge and approved temp directory required");
const profile = mkdtempSync(join(tempRoot, "revela-refresh-browser-"));
const calls = [];
const clients = new Set();
const fixture = {
  holdRegistry: false, heldRegistry: [], holdUsers: false, heldUsers: [], failRegistry: false, failBarangays: false,
  holds: new Set(), pending: new Map(), failures: new Set(), storageMB: 37,
  flagName: "Synthetic Map Flag", reportName: "Synthetic Inspection", reportCount: 1,
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
  if (path === "/api/notifications") { reply({ data: [{ id: 3, title: "Synthetic notice", message: "No real data", readAt: null }] }); return; }
  if (path === "/api/notifications/unread-count") { reply({ count: 1 }); return; }
  if (path === "/api/registry/") {
    if (fixture.holdRegistry) await new Promise(resolve => fixture.heldRegistry.push(resolve));
    if (fixture.failRegistry) { fixture.failRegistry = false; reply({ error: "Synthetic registry failure" }, 503); return; }
    reply({ data: [{ businessID: "B-1", businessName: "Synthetic Shop", applicationStatus: "Active", barangayName: "Barangay I" }], total: 1, pages: 1, page: 1 }); return;
  }
  if (path === "/api/registry/barangays") {
    if (await gate(path)) return;
    if (fixture.failBarangays) { fixture.failBarangays = false; reply({ error: "Synthetic barangay failure" }, 503); return; }
    reply([{ barangayID: 1, barangayName: "Barangay I" }]); return;
  }
  if (path === "/api/users/") {
    if (await gate(url.searchParams.get("role") === "Inspector" ? "/api/users/:Inspector" : path)) return;
    if (fixture.holdUsers) await new Promise(resolve => fixture.heldUsers.push(resolve));
    reply([{ userID: 17, fullName: "Synthetic User 17", userRole: "SUPER_ADMIN", email: "user17@example.test", isActive: true }]); return;
  }
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
const network = [], exceptions = [];
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
    if (message.method === "Network.requestWillBeSent" && message.params.request.url.startsWith(process.env.VITE_API_ORIGIN)) network.push(message.params.request.url);
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
  const last = () => evaluate("document.querySelector('.app-refresh-controls span[title]')?.title");
  const status = () => evaluate("document.querySelector('.app-refresh-controls [role=status]')?.textContent");
  const refresh = () => evaluate("document.querySelector('button[aria-label=" + JSON.stringify("Refresh Data") + "]')?.click()");

  await navigate("/registry");
  await wait("document.querySelector('.app-refresh-controls [role=status]')?.textContent === 'Synced'", "initial registry sync");
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
  await wait("document.querySelector('.app-refresh-controls [role=status]')?.textContent === 'Synced'", "reloaded registry");
  console.log("PASS browser: per-user Medium default and Easy/Lax persistence across real reloads");

  await choose("hard");
  const before = count("/api/registry/");
  const priorLast = await last();
  fixture.holdRegistry = true;
  await sleep(1100);
  await refresh();
  await wait(`document.querySelector('.app-refresh-controls [role=status]')?.textContent === 'Syncing…'`, "manual in-flight");
  assert.equal(count("/api/registry/"), before + 1, "manual requests latest registry immediately");
  assert.equal(await last(), priorLast, "held refresh has not reset last sync");
  await evaluate("document.querySelector('button[aria-label=" + JSON.stringify("Refresh Data") + "]')?.click()");
  await evaluate("window.__clockOffset += 65000; window.dispatchEvent(new Event('focus')); document.dispatchEvent(new Event('visibilitychange'))");
  clients.forEach(client => client.write('data: {"type":"registry_updated"}\n\n'));
  await sleep(150);
  assert.equal(count("/api/registry/"), before + 1, "second click coalesces");
  fixture.holdRegistry = false; fixture.heldRegistry.splice(0).forEach(resolve => resolve());
  await wait("document.querySelector('.app-refresh-controls [role=status]')?.textContent === 'Synced'", "manual completion");
  assert.notEqual(await last(), priorLast, "full success resets last sync");
  console.log("PASS simulated browser due-clock + real requests: manual/timer/focus/SSE overlap joins one in-flight GET; success resets deadline");

  const lastSuccess = await last();
  await sleep(1100); // Distinguish a false success timestamp from a same-second render.
  fixture.failBarangays = true;
  await refresh();
  await wait("document.querySelector('.app-refresh-controls [role=status]')?.textContent === 'Partially updated'", "partial failure");
  assert.equal(await last(), lastSuccess);
  assert.ok(await evaluate("document.body.textContent.includes('Synthetic Shop')"));
  await sleep(1100);
  fixture.failBarangays = true; fixture.failRegistry = true;
  await refresh();
  await wait("document.querySelector('.app-refresh-controls [role=status]')?.textContent === 'Sync failed'", "full failure");
  assert.equal(await last(), lastSuccess);
  assert.ok(await evaluate("document.body.textContent.includes('Synthetic Shop')"));
  console.log("PASS browser: partial/full failure leaves prior registry and deadline intact");

  for (const mode of ["medium", "easy", "lax"]) {
    const oldLast = await last();
    await choose(mode);
    assert.equal(await last(), oldLast, "mode change alone never marks data fresh");
    const previousCount = count("/api/registry/");
    await refresh();
    await wait("document.querySelector('.app-refresh-controls [role=status]')?.textContent === 'Synced'", `${mode} manual request completes`);
    assert.equal(count("/api/registry/"), previousCount + 1, `${mode} manual GET bypasses interval`);
  }
  console.log("PASS browser: manual GET starts and completes in Medium, Easy and Lax without waiting for the interval");

  const passiveCount = count("/api/registry/");
  const notificationCount = count("/api/notifications");
  clients.forEach(client => client.write('data: {"type":"registry_updated"}\n\n'));
  await wait(`document.querySelector('.app-refresh-controls span[title]')?.textContent.includes('Changed')`, "passive stale marker");
  await sleep(250);
  assert.equal(count("/api/registry/"), passiveCount, "SSE does not cause registry read");
  assert.ok(count("/api/notifications") > notificationCount, "notification delivery still fetches notifications");
  console.log("PASS browser: real local SSE message marks data stale, continues notification delivery, no data GET");

  fixture.holdRegistry = true;
  const beforeFiltered = count("/api/registry/");
  await evaluate(`(() => { const e=[...document.querySelectorAll('select')].find(e=>[...e.options].some(option=>option.value==='Active') && [...e.options].some(option=>option.value==='Expired')); e.value='Active'; e.dispatchEvent(new Event('change',{bubbles:true})); })()`);
  await wait(`document.querySelector('.app-refresh-controls [role=status]')?.textContent === 'Syncing…'`, "registry filter query in flight");
  assert.equal(count("/api/registry/"), beforeFiltered + 1);
  assert.equal(calls.filter(call => call.path === "/api/registry/").at(-1).query.includes("status=Active"), true);
  assert.equal(await last(), "No successful sync yet", "filtered registry cannot inherit prior query's deadline");
  fixture.holdRegistry = false; fixture.heldRegistry.splice(0).forEach(resolve => resolve());
  await wait("document.querySelector('.app-refresh-controls [role=status]')?.textContent === 'Synced'", "registry filter refreshed");

  fixture.holdUsers = true;
  const usersBefore = count("/api/users/");
  await evaluate("document.querySelector('a[href=" + JSON.stringify("/users") + "]')?.click()");
  await wait("location.pathname === '/users' && document.querySelector('.app-refresh-controls [role=status]')?.textContent === 'Syncing…'", "new users view in flight");
  await waitForCalls(() => count("/api/users/") > usersBefore, "Users initial request");
  assert.equal(count("/api/users/"), usersBefore + 1);
  assert.equal(await last(), "No successful sync yet", "new route cannot inherit registry freshness");
  fixture.holdUsers = false; fixture.heldUsers.splice(0).forEach(resolve => resolve());
  await wait("document.querySelector('.app-refresh-controls [role=status]')?.textContent === 'Synced'", "users route");
  const usersNow = count("/api/users/");
  const registryNow = count("/api/registry/");
  await refresh();
  await wait(`document.querySelector('.app-refresh-controls [role=status]')?.textContent === 'Synced'`, "users manual sync");
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
  await wait(`document.querySelector('.app-refresh-controls [role=status]')?.textContent === 'Synced'`, "visible due refresh");
  assert.equal(count("/api/users/"), paused + 1, "visibility and focus coalesce to one due request");
  await evaluate("window.__online = false; window.dispatchEvent(new Event('offline')); window.__clockOffset += 70000; window.dispatchEvent(new Event('focus'))");
  const offline = count("/api/users/");
  await sleep(150);
  assert.equal(count("/api/users/"), offline);
  await evaluate("window.__online = true; window.dispatchEvent(new Event('online')); window.dispatchEvent(new Event('focus'))");
  await wait(`document.querySelector('.app-refresh-controls [role=status]')?.textContent === 'Synced'`, "online due refresh");
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
  await wait("document.querySelector('.analytics-page') && document.querySelector('.app-refresh-controls [role=status]')?.textContent === 'Synced'", "analytics initial load");
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
    else await call("Page.navigate", { url: origin + path });
    await wait(`location.pathname === ${JSON.stringify(path)} && document.querySelector('.app-refresh-controls [role=status]')?.textContent === 'Synced'`, label, 25000);
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
  await wait("document.querySelector('.app-refresh-controls [role=status]')?.textContent === 'Syncing…'", "Overview awaits inspections");
  for (const path of homePaths) assert.equal(count(path), homeBefore[path] + (path === "/api/analytics/all" ? 2 : 1), `Overview manual reads ${path} once per required dataset`);
  assert.equal(await last(), homeLast);
  release("/api/inspections/");
  await wait("document.querySelector('.app-refresh-controls [role=status]')?.textContent === 'Synced'", "Overview completes");
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
  await wait("document.querySelector('.app-refresh-controls [role=status]')?.textContent === 'Syncing…'", "Overview summary held for navigation");
  await evaluate("document.querySelector('a[href=" + JSON.stringify("/map") + "]')?.click()");
  await wait("location.pathname === '/map' && document.querySelector('.app-refresh-controls [role=status]')?.textContent === 'Synced'", "Map after Overview unmount", 25000);
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
  await wait("document.querySelector('.app-refresh-controls [role=status]')?.textContent === 'Syncing…'", "Map awaits rankings");
  await waitForCalls(() => mapPaths.every(path => count(path) > mapBefore[path]), "Map required reads");
  for (const path of mapPaths) assert.equal(count(path), mapBefore[path] + 1, `Map manual reads ${path} once`);
  assert.equal(await last(), mapSuccess);
  release("/api/analytics/ops-rankings");
  await wait("document.querySelector('.app-refresh-controls [role=status]')?.textContent === 'Synced'", "Map completed rankings");
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
  await wait("document.querySelector('.app-refresh-controls [role=status]')?.textContent === 'Syncing…'", "Map held flags");
  await evaluate("document.querySelector('a[href=" + JSON.stringify("/inspections") + "]')?.click()");
  await wait("location.pathname === '/inspections' && document.querySelector('.app-refresh-controls [role=status]')?.textContent === 'Synced'", "Inspection after Map unmount", 25000);
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
  await wait("document.querySelector('.app-refresh-controls [role=status]')?.textContent === 'Syncing…'", "Dispatch held report list");
  assert.equal(count("/api/inspections/"), dispatchBefore + 1);
  assert.ok(calls.filter(c => c.path === "/api/inspections/").at(-1).query.includes("limit=100"));
  assert.equal(await last(), dispatchLast);
  release("/api/inspections/");
  await wait("document.querySelector('.app-refresh-controls [role=status]')?.textContent === 'Synced'", "Dispatch manual complete");
  const dispatchSuccess = await last();
  await sleep(1100);
  fixture.failures.add("/api/inspections/");
  await refresh();
  await wait("document.querySelector('.app-refresh-controls [role=status]')?.textContent === 'Sync failed'", "Dispatch one-endpoint failure");
  assert.equal(await last(), dispatchSuccess);
  assert.ok(await evaluate("document.body.textContent.includes('Synthetic Inspection')"));
  await passive("inspection_updated", ["/api/inspections/"]);
  fixture.holds.add("/api/inspections/");
  await refresh();
  await wait("document.querySelector('.app-refresh-controls [role=status]')?.textContent === 'Syncing…'", "Dispatch unmount request");
  await evaluate("document.querySelector('a[href=" + JSON.stringify("/reports") + "]')?.click()");
  await wait("location.pathname === '/reports' && document.querySelector('.app-refresh-controls [role=status]')?.textContent === 'Synced'", "Reports after Dispatch unmount", 25000);
  const reportsLast = await last();
  release("/api/inspections/");
  await sleep(220);
  assert.equal(await last(), reportsLast);
  noMutationRefresh();
  console.log("PASS browser Inspection Dispatch: required report GET, awaited/failure/stale and unmount isolation; single endpoint has no partial state");

  const reportsBefore = count("/api/analytics/demographic-reports");
  fixture.holds.add("/api/analytics/demographic-reports");
  await refresh();
  await wait("document.querySelector('.app-refresh-controls [role=status]')?.textContent === 'Syncing…'", "Reports held demographic GET");
  assert.equal(count("/api/analytics/demographic-reports"), reportsBefore + 1);
  assert.equal(await last(), reportsLast);
  release("/api/analytics/demographic-reports");
  await wait("document.querySelector('.app-refresh-controls [role=status]')?.textContent === 'Synced'", "Reports manual complete");
  const reportsSuccess = await last();
  await sleep(1100);
  fixture.failures.add("/api/analytics/demographic-reports");
  await refresh();
  await wait("document.querySelector('.app-refresh-controls [role=status]')?.textContent === 'Sync failed'", "Reports one-endpoint failure");
  assert.equal(await last(), reportsSuccess);
  assert.ok(await evaluate("document.querySelector('.export-reports-page')?.textContent.includes('123')"), "Reports preserves demographics");
  assert.ok(await evaluate("document.querySelector('.export-reports-page [role=alert]')?.textContent.includes('Showing the last successful report snapshot from')"));
  await passive("registry_updated", ["/api/analytics/demographic-reports"]);
  fixture.holds.add("/api/analytics/demographic-reports");
  await refresh();
  await wait("document.querySelector('.app-refresh-controls [role=status]')?.textContent === 'Syncing…'", "Reports unmount request");
  await evaluate("document.querySelector('a[href=" + JSON.stringify("/settings") + "]')?.click()");
  await wait("location.pathname === '/settings' && document.querySelector('.app-refresh-controls [role=status]')?.textContent === 'Synced'", "Settings after Reports unmount", 25000);
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
  await wait("document.querySelector('.app-refresh-controls [role=status]')?.textContent === 'Syncing…'", "Settings awaits evidence usage");
  for (const path of settingsPaths) assert.equal(count(path), settingsBefore[path] + 1, `Settings manual GET ${path}`);
  assert.equal(await last(), settingsLast);
  release("/api/inspections/evidence-storage-stats");
  await wait("document.querySelector('.app-refresh-controls [role=status]')?.textContent === 'Synced'", "Settings manual complete");
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
  await wait("document.querySelector('.app-refresh-controls [role=status]')?.textContent === 'Syncing…'", "Settings unmount request");
  await evaluate("history.pushState(null,'','/inspections/calendar'); window.dispatchEvent(new PopStateEvent('popstate'))");
  await wait("location.pathname === '/inspections/calendar' && document.querySelector('.app-refresh-controls [role=status]')?.textContent === 'Synced'", "Calendar after Settings unmount", 25000);
  const calendarLast = await last();
  release("/api/inspections/evidence-storage-stats");
  await sleep(220);
  assert.equal(await last(), calendarLast);
  noMutationRefresh();
  console.log("PASS browser Settings: policy/storage GETs, awaited/partial/stale and unmount isolation; no mutation");

  const deadlinesBefore = count("/api/inspections/");
  fixture.holds.add("/api/inspections/");
  await refresh();
  await wait("document.querySelector('.app-refresh-controls [role=status]')?.textContent === 'Syncing…'", "Calendar deadline pagination held");
  assert.equal(count("/api/inspections/"), deadlinesBefore + 1);
  assert.ok(calls.filter(c => c.path === "/api/inspections/").at(-1).query.includes("limit=200"));
  assert.equal(await last(), calendarLast);
  release("/api/inspections/");
  await wait("document.querySelector('.app-refresh-controls [role=status]')?.textContent === 'Synced'", "Calendar deadline manual complete");
  const deadlineSuccess = await last();
  await sleep(1100);
  fixture.failures.add("/api/inspections/");
  await refresh();
  await wait("document.querySelector('.app-refresh-controls [role=status]')?.textContent === 'Sync failed'", "Calendar deadline failure");
  assert.equal(await last(), deadlineSuccess);
  assert.ok(await evaluate("document.querySelector('.inspection-calendar-page')?.textContent.includes('Synthetic Inspection')"), "Calendar preserves deadline data");
  await passive("inspection_updated", ["/api/inspections/", "/api/inspections/calendar"]);
  await evaluate("document.querySelector('#inspection-calendar-tab-activity')?.click()");
  await wait("document.querySelector('#inspection-calendar-tab-activity')?.getAttribute('aria-selected') === 'true' && document.querySelector('.app-refresh-controls [role=status]')?.textContent === 'Synced'", "Calendar activity switched", 25000);
  const activityBefore = count("/api/inspections/calendar");
  fixture.holds.add("/api/inspections/calendar");
  const activityLast = await last();
  await refresh();
  await wait("document.querySelector('.app-refresh-controls [role=status]')?.textContent === 'Syncing…'", "Calendar activity held");
  assert.equal(count("/api/inspections/calendar"), activityBefore + 1);
  assert.equal(await last(), activityLast);
  release("/api/inspections/calendar");
  await wait("document.querySelector('.app-refresh-controls [role=status]')?.textContent === 'Synced'", "Calendar activity manual complete");
  const activitySuccess = await last();
  await sleep(1100);
  fixture.failures.add("/api/inspections/calendar");
  await refresh();
  await wait("document.querySelector('.app-refresh-controls [role=status]')?.textContent === 'Sync failed'", "Calendar activity failure");
  assert.equal(await last(), activitySuccess);
  assert.ok(await evaluate("document.querySelector('.inspection-calendar-page')?.textContent.includes('1')"), "Calendar retains activity counts");
  await passive("inspection_updated", ["/api/inspections/calendar"]);
  fixture.holds.add("/api/inspections/calendar");
  await refresh();
  await wait("document.querySelector('.app-refresh-controls [role=status]')?.textContent === 'Syncing…'", "Calendar unmount request");
  await evaluate("document.querySelector('a[href=" + JSON.stringify("/registry") + "]')?.click()");
  await wait("location.pathname === '/registry' && document.querySelector('.app-refresh-controls [role=status]')?.textContent === 'Synced'", "Registry after Calendar unmount", 25000);
  const finalRegistry = await last();
  release("/api/inspections/calendar");
  await sleep(220);
  assert.equal(await last(), finalRegistry);
  noMutationRefresh();
  console.log("PASS browser Calendar: deadlines/activity exact GETs, awaited/failure/stale and unmount isolation; no partial for single dataset");

  await metrics(1500);
  const layout = async () => evaluate(`(() => { const nav=document.querySelector('.top-navbar'), controls=document.querySelector('.app-refresh-controls'), button=document.querySelector('button[aria-label="Refresh Data"]'); const rect=e=>({left:e.getBoundingClientRect().left,right:e.getBoundingClientRect().right,top:e.getBoundingClientRect().top,bottom:e.getBoundingClientRect().bottom}); return {viewport:innerWidth, nav:rect(nav), scroll:nav.scrollWidth, client:nav.clientWidth, controls:rect(controls), button:rect(button), children:[...document.querySelector('.top-nav-right').children].map(rect)}; })()`);
  const wide = await layout();
  await metrics(560); await sleep(250);
  const narrow = await layout();
  const fits = view => view.children.every(rect => rect.left >= view.nav.left - 1 && rect.right <= view.viewport + 1 && rect.top >= view.nav.top - 1 && rect.bottom <= view.nav.bottom + 1);
  const overlaps = view => view.children.some((rect, index) => view.children.slice(index + 1).some(other =>
    Math.min(rect.right, other.right) - Math.max(rect.left, other.left) > 1 &&
    Math.min(rect.bottom, other.bottom) - Math.max(rect.top, other.top) > 1));
  assert.ok(fits(wide) && fits(narrow) && !overlaps(wide) && !overlaps(narrow) && narrow.scroll <= narrow.client + 1, JSON.stringify({ wide, narrow }));
  console.log("PASS browser navbar layout: 1500px desktop and 560px supported minimum", { wide, narrow });
  await metrics(390);
  await wait("document.querySelector('.restricted-root') && !document.querySelector('#app-refresh-mode')", "existing phone access notice");
  console.log("PASS browser: phone-sized viewport still shows existing device gate");
  assert.equal(exceptions.length, 0, `browser exceptions: ${exceptions.join(" | ")}`);
  console.log(`Synthetic API requests observed in CDP Network: ${network.length}`);
} finally {
  socket?.close();
  if (browser && browser.exitCode === null) browser.kill();
  await server.close();
  api.closeAllConnections(); await new Promise(resolve => api.close(resolve));
  await rm(profile, { recursive: true, force: true, maxRetries: 10, retryDelay: 300 });
}
