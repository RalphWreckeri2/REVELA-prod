// Production Settings page, synthetic API/credentials only. No live mutations.
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { existsSync, mkdtempSync } from "node:fs";
import { writeFile } from "node:fs/promises";
import { join } from "node:path";
import { preview } from "vite";

const edge = process.env.EDGE_BINARY || "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe";
const tempRoot = process.env.LOCALAPPDATA && join(process.env.LOCALAPPDATA, "Temp", "opencode");
if (!existsSync(edge) || !tempRoot || !existsSync(tempRoot)) throw new Error("Local Edge and the approved temporary directory are required.");
const profile = mkdtempSync(join(tempRoot, "revela-settings-browser-"));
const server = await preview({ preview: { host: "127.0.0.1", port: 0, open: false } });
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
const checks = [], exceptions = [];
let browser, socket, session, call;

function installFixtures() {
  localStorage.clear();
  localStorage.setItem("revela_token", "settings-synthetic-token");
  localStorage.setItem("revela-theme", "light");
  localStorage.setItem("revela_emailAlerts", "true");
  const audit = window.__settings = {
    requests: [], modes: { preferences: "failure", setup: "failure", backup: "unconfigured" }, pendingCleanup: false,
    user: { id: 17, fullName: "Synthetic Settings Admin", email: "settings@example.test", role: "Admin", emailInspectionAlerts: true, is_2fa_enabled: false },
    policy: { w1_risk: 68, w2_sector: 7, w3_distance: 25, bplo_lat: 13.960413, bplo_lng: 121.114547 },
    backup: {
      status: "not_configured", configured: false, lastSuccessfulBackup: null, history: null,
      reason: "Database backup runtime configuration is incomplete.",
      schedule: { configured: false, enabled: false, nextRunAt: null, summary: null },
      retention: { configured: false, summary: null },
      historyUnavailableReason: "Backup history is unavailable until backup storage configuration is complete.",
      manualBackupDisabledReason: "Database backup runtime configuration is incomplete.",
      downloadDisabledReason: "Authenticated backup downloads require configured private storage.",
      canManualBackup: false, canDownload: false, configurationIssues: ["Missing BACKUP_DB_HOST"],
      automaticExecutionEnabled: false,
      automaticExecutionStatus: "not_ready",
      automaticExecutionReason: "No external scheduled trigger is integrated. The in-process scheduler can stop when the API sleeps.",
      externalTriggerConfigured: false,
    },
  };
  audit.originalBackup = structuredClone(audit.backup);
  const nativeFetch = window.fetch.bind(window);
  const nativeSetItem = Storage.prototype.setItem;
  Storage.prototype.setItem = function (key, value) {
    if (key === "revela_emailAlerts" && audit.modes.storageFail) throw new Error("Synthetic browser storage failure");
    return nativeSetItem.call(this, key, value);
  };
  window.fetch = async (input, options = {}) => {
    const url = new URL(typeof input === "string" ? input : input.url, location.href);
    if (!url.pathname.startsWith("/api/")) {
      if (url.origin === location.origin) return nativeFetch(input, options);
      throw new Error("External request blocked by Settings fixture");
    }
    const path = url.pathname, method = options.method || "GET";
    const body = options.body ? JSON.parse(options.body) : null;
    audit.requests.push({ path, method, body, authorization: new Headers(options.headers).get("Authorization") });
    const json = (data, status = 200) => {
      const response = Response.json(data, { status });
      Object.defineProperty(response, "url", { value: url.href });
      return response;
    };
    if (path.endsWith("/auth/me")) return audit.modes.refreshFail ? json({ error: "Synthetic refresh failure" }, 503) : json(audit.user);
    if (path.endsWith("/auth/me/preferences")) {
      if (audit.modes.preferences === "failure") return json({ error: "Synthetic email save failure" }, 503);
      if (audit.modes.preferences === "invalid") return json({ message: "Unconfirmed response" });
      audit.user.emailInspectionAlerts = body.emailInspectionAlerts;
      return json({ emailInspectionAlerts: audit.user.emailInspectionAlerts });
    }
    if (path.endsWith("/auth/setup-2fa")) {
      if (audit.modes.setup === "held") await new Promise(resolve => { audit.releaseSetup = resolve; });
      if (audit.modes.setup === "failure") return json({ error: "Synthetic setup failure" }, 503);
      if (audit.modes.setup === "incomplete") return json({ secret: "SYNTHETIC" });
      return json({ secret: "JBSWY3DPEHPK3PXP", otpUri: "otpauth://totp/REVELA:synthetic?secret=JBSWY3DPEHPK3PXP&issuer=REVELA" });
    }
    if (path.endsWith("/auth/verify-2fa-setup")) {
      if (body.code !== "123456") return json({ error: "Invalid 2FA code" }, 400);
      audit.user.is_2fa_enabled = true;
      return json({ message: "2FA enabled successfully" });
    }
    if (path.endsWith("/auth/disable-2fa")) {
      audit.user.is_2fa_enabled = false;
      return json({ message: "2FA disabled successfully" });
    }
    if (path.endsWith("/analytics/wlc-config")) {
      if (method === "PUT") Object.assign(audit.policy, body);
      return json(method === "PUT" ? { data: audit.policy } : audit.policy);
    }
    if (path.endsWith("/admin-settings/database-backup/status")) {
      if (audit.modes.backup === "held") await new Promise(resolve => { audit.releaseBackup = resolve; });
      if (audit.modes.backup === "failure") return json({ error: "Synthetic backup status outage" }, 503);
      if (audit.modes.backup === "missing") return json({ error: "Not found" }, 404);
      if (audit.modes.backup === "incomplete") return json({ status: "ready" });
      return json(audit.backup);
    }
    if (path.endsWith("/admin-settings/backups/run") && method === "POST") {
      return json({ message: "Database backup started.", status: "running" }, 202);
    }
    if (/\/admin-settings\/backups\/[0-9a-f]{32}\/download$/.test(path)) {
      return new Response(new Uint8Array([0x1f, 0x8b, 0x08]), {
        headers: { "Content-Type": "application/gzip", "Content-Disposition": 'attachment; filename="revela-test.sql.gz"' },
      });
    }
    if (path.endsWith("/inspections/evidence-storage-stats")) {
      const count = audit.pendingCleanup || audit.cleaned ? 0 : 2;
      const categories = Object.fromEntries(["older_180d", "older_365d", "older_90d", "older_30d", "all_verified"].map(key => [key, { label: key, reportCount: count, photoCount: count, estimatedMB: 1 }]));
      return json({ totalDiskMB: 1, totalFilesOnDisk: 2, cleanupPending: audit.pendingCleanup, categories });
    }
    if (path.endsWith("/archive-evidence/cleanup")) {
      if (audit.modes.cleanup === "failure") return json({ error: "Synthetic cleanup safely stopped" }, 500);
      audit.pendingCleanup = audit.modes.cleanup === "pending";
      audit.cleaned = true;
      return json({ deletedFiles: 2, freedMB: audit.pendingCleanup ? 0 : 1, warning: audit.pendingCleanup ? "Recovery backup disposal is pending; not all space was freed." : null });
    }
    if (path.endsWith("/notifications/unread-count")) return json({ count: 0 });
    if (path.endsWith("/notifications/stream")) return new Response(new ReadableStream({ start(controller) { controller.enqueue(new TextEncoder().encode('data: {"type":"connected"}\n\n')); } }), { headers: { "Content-Type": "text/event-stream" } });
    if (path.endsWith("/notifications")) return json({ data: [] });
    if (path.endsWith("/auth/activity")) return json({ message: "Activity recorded" });
    return json({ error: `Unexpected synthetic API path: ${path}` }, 404);
  };
}

try {
  const debuggerURL = await new Promise((resolve, reject) => {
    browser = spawn(edge, ["--headless", "--disable-gpu", "--no-first-run", "--no-default-browser-check", "--disable-background-networking", "--disable-component-update", "--disable-sync", "--no-proxy-server", "--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1, EXCLUDE localhost", `--user-data-dir=${profile}`, "--remote-debugging-port=0", "about:blank"], { windowsHide: true });
    let stderr = "";
    const timer = setTimeout(() => reject(new Error(`Edge startup timeout: ${stderr}`)), 20000);
    browser.stdout.resume();
    browser.stderr.on("data", chunk => {
      stderr += chunk;
      const url = stderr.match(/DevTools listening on (ws:\/\/[^\s]+)/)?.[1];
      if (url) { clearTimeout(timer); resolve(url); }
    });
    browser.on("error", error => { clearTimeout(timer); reject(error); });
  });
  socket = new WebSocket(debuggerURL);
  await new Promise((resolve, reject) => { socket.addEventListener("open", resolve); socket.addEventListener("error", reject); });
  let id = 0;
  const pending = new Map();
  socket.addEventListener("message", event => {
    const message = JSON.parse(event.data);
    if (message.method === "Runtime.exceptionThrown") exceptions.push(message.params.exceptionDetails.exception?.description || message.params.exceptionDetails.text);
    if (!message.id) return;
    const request = pending.get(message.id);
    pending.delete(message.id);
    clearTimeout(request?.timer);
    if (message.error) request?.reject(new Error(JSON.stringify(message.error)));
    else request?.resolve(message.result);
  });
  call = (method, params = {}, sessionId = session) => new Promise((resolve, reject) => {
    const requestID = ++id;
    const timer = setTimeout(() => { pending.delete(requestID); reject(new Error(`CDP timeout: ${method}`)); }, 30000);
    pending.set(requestID, { resolve, reject, timer });
    socket.send(JSON.stringify({ id: requestID, method, params, sessionId }));
  });
  const { targetId } = await call("Target.createTarget", { url: "about:blank" });
  session = (await call("Target.attachToTarget", { targetId, flatten: true })).sessionId;
  await call("Runtime.enable");
  await call("Page.enable");
  await call("Page.bringToFront");
  await call("Emulation.setFocusEmulationEnabled", { enabled: true });
  await call("Emulation.setDeviceMetricsOverride", { width: 1440, height: 1100, deviceScaleFactor: 1, mobile: false, screenWidth: 1440, screenHeight: 1100 });
  await call("Page.addScriptToEvaluateOnNewDocument", { source: `(${installFixtures.toString()})()` });
  const evaluate = async expression => {
    const result = await call("Runtime.evaluate", { expression, returnByValue: true, awaitPromise: true });
    if (result.exceptionDetails) throw new Error(result.exceptionDetails.exception?.description || result.exceptionDetails.text);
    return result.result?.value;
  };
  const wait = async (expression, label) => {
    const deadline = Date.now() + 20000;
    while (Date.now() < deadline) { if (await evaluate(`Boolean(${expression})`)) return; await sleep(50); }
    throw new Error(`Timed out: ${label}`);
  };
  const click = async (scope, text) => {
    assert.equal(await evaluate(`(() => { const e = [...document.querySelectorAll(${JSON.stringify(scope)})].find(e => e.textContent.trim() === ${JSON.stringify(text)} && e.getClientRects().length && !e.disabled); if (!e) return false; e.click(); return true; })()`), true, `Clickable: ${text}`);
    await sleep(100);
  };
  const input = async (selector, value) => {
    await evaluate(`(() => { const e = document.querySelector(${JSON.stringify(selector)}); Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(e, ${JSON.stringify(value)}); e.dispatchEvent(new Event('input', { bubbles: true })); })()`);
    await sleep(70);
  };
  const record = label => { checks.push(label); console.log(`PASS ${label}`); };
  const closeAlert = async () => {
    await evaluate(`document.querySelector('.swal2-confirm')?.click()`);
    await wait(`!document.querySelector('.swal2-container')`, "alert completely closed");
    // SweetAlert restores the previous focus on a separate 100ms timer.
    await sleep(150);
  };
  const count = suffix => evaluate(`__settings.requests.filter(r => r.path.endsWith(${JSON.stringify(suffix)})).length`);
  const key = async (name, code, virtualKey) => {
    const text = name === "Enter" ? "\r" : name === " " ? " " : undefined;
    await call("Input.dispatchKeyEvent", { type: "keyDown", key: name, code, windowsVirtualKeyCode: virtualKey, text, unmodifiedText: text });
    await call("Input.dispatchKeyEvent", { type: "keyUp", key: name, code, windowsVirtualKeyCode: virtualKey });
    await sleep(100);
  };
  const origin = `http://127.0.0.1:${server.httpServer.address().port}`;
  await call("Page.navigate", { url: `${origin}/settings` });
  await wait(`document.querySelector('#settings-preferences-body') && document.querySelector('#settings-database-backup-summary')`, "Settings ready");
  for (const section of ["security", "evidence", "manual"]) await evaluate(`document.querySelector('#settings-${section}-title').closest('button').click()`);

  const backupPath = "/admin-settings/database-backup/status";
  const backupScope = "#settings-database-backup-body";
  await wait(`document.querySelector('#settings-database-backup-summary')?.textContent === 'Recovery copies of system database records' && document.querySelector('#settings-database-backup-state')?.textContent === 'Not configured'`, "unconfigured backend status");
  assert.deepEqual(await evaluate(`[...document.querySelectorAll('.settings-section')].map(e => e.getAttribute('aria-labelledby')).filter(id => /evidence|database-backup|manual/.test(id))`),
    ["settings-evidence-title", "settings-database-backup-title", "settings-manual-title"]);
  assert.equal(await evaluate(`document.querySelector('${backupScope}').hidden`), true);
  await evaluate(`document.querySelector('#settings-database-backup-title').closest('button').focus()`);
  await key("Enter", "Enter", 13);
  assert.equal(await evaluate(`document.querySelector('${backupScope}').hidden`), false);
  assert.equal(await evaluate(`document.querySelector('${backupScope} .database-backup-description').textContent.trim()`),
    "Recovery copies of system database records. Inspection photos are managed separately.");
  assert.equal(await evaluate(`document.querySelector('${backupScope} .primary-btn').disabled`), true);
  assert.ok(await evaluate(`document.querySelector('#database-backup-action-reason').textContent.includes('runtime configuration is incomplete')`));
  assert.equal(await evaluate(`[...document.querySelectorAll('${backupScope} [role="status"], ${backupScope} .database-backup-note')].filter(node => node.textContent.includes('runtime configuration is incomplete')).length`), 1);
  assert.equal(await evaluate(`document.querySelector('${backupScope} .database-backup-setup summary').textContent`), "View setup requirements");
  assert.equal(await evaluate(`document.querySelector('${backupScope} .database-backup-setup').open`), false);
  assert.equal(await evaluate(`document.querySelectorAll('${backupScope} tbody tr').length`), 1);
  assert.equal(await evaluate(`document.querySelectorAll('${backupScope} tbody button, ${backupScope} a').length`), 0);
  assert.ok(await evaluate(`document.querySelectorAll('${backupScope} dd')[1].textContent.startsWith('Setup required')`));
  assert.ok(await evaluate(`document.querySelector('${backupScope} .database-backup-warning').textContent.includes('Complete the setup requirements')`));
  assert.equal(await evaluate(`document.querySelector('${backupScope} .database-backup-policy').open`), false);
  assert.equal(await evaluate(`document.querySelector('${backupScope} .database-backup-policy summary').textContent`), "View proposed policy");
  assert.ok(await evaluate(`__settings.requests.filter(r => r.path.endsWith('${backupPath}')).every(r => r.authorization === 'Bearer settings-synthetic-token')`));
  record("Database Backup is a native collapsible card in the requested order with honest unconfigured status and inactive proposal");

  const backupBefore = await count(backupPath);
  await evaluate(`__settings.modes.backup = 'held'; (() => { const button = document.querySelector('${backupScope} .ghost-btn'); button.click(); button.click(); })()`);
  await wait(`typeof __settings.releaseBackup === 'function' && document.querySelector('${backupScope} .ghost-btn').disabled`, "pending status refresh");
  assert.equal(await count(backupPath), backupBefore + 1);
  assert.equal(await evaluate(`document.querySelector('${backupScope} .primary-btn').disabled`), true);
  assert.ok(await evaluate(`document.querySelector('${backupScope}').textContent.includes('Loading backup history')`));
  await evaluate(`__settings.modes.backup = 'unconfigured'; __settings.releaseBackup()`);
  await wait(`!document.querySelector('${backupScope} .ghost-btn').disabled`, "status refresh finished");
  for (const [mode, expected] of [["failure", "Synthetic backup status outage"], ["missing", "GET /api/admin-settings/database-backup/status"], ["incomplete", "incomplete database backup status"]]) {
    await evaluate(`__settings.modes.backup = '${mode}'`);
    await click(`${backupScope} button`, "Refresh");
    await wait(`document.querySelector('${backupScope} [role="alert"]')?.textContent.includes(${JSON.stringify(expected)})`, `${mode} status response`);
    assert.equal(await evaluate(`document.querySelector('#settings-database-backup-state').textContent`), "Status unavailable");
    assert.equal(await evaluate(`document.querySelector('${backupScope} .primary-btn').disabled`), true);
    assert.equal(await evaluate(`document.querySelectorAll('${backupScope} dd')[1].textContent.trim()`), "Unavailable");
  }
  await evaluate(`__settings.modes.backup = 'unconfigured'`);
  await click(`${backupScope} button`, "Refresh");
  await wait(`!document.querySelector('${backupScope} [role="alert"]')`, "status retry succeeds");
  record("Status refresh uses Bearer auth, deduplicates concurrent clicks, and handles loading/outage/missing/invalid responses without fake backup failures");

  await evaluate(`(() => {
    const completed = { id: 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa', trigger: 'manual', status: 'completed', completedAt: '2026-10-23T11:00:00Z', sizeBytes: 1048576 };
    __settings.backup = { ...__settings.backup, status: 'ready', configured: true, reason: null,
      canManualBackup: true, canDownload: true, configurationIssues: [], automaticExecutionEnabled: false,
      lastSuccessfulBackup: completed, history: [completed,
        { id: 'cccccccccccccccccccccccccccccccc', trigger: 'automatic', status: 'completed', startedAt: '2026-10-23T11:00:00Z', completedAt: '2026-10-23T11:01:00Z', sizeBytes: 2048, monthlyArchive: true },
        { id: 'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb', trigger: 'automatic', status: 'failed', startedAt: '2026-10-24T11:00:00Z', sizeBytes: null }],
      schedule: { configured: true, enabled: false, nextRunAt: null, summary: 'Every Friday at 7:00 PM Asia/Manila; monthly archive' },
      retention: { configured: true, summary: 'Proposed retention: keep 4 successful weekly copies and 3 monthly archives; manual backups are a separate category proposed for 30 days. Automatic cleanup is disabled.', cleanupEnabled: false,
        policy: { weekly_successful_copies: 4, monthly_archives: 3, manual_days_proposed: 30, cleanup_enabled: false } },
      automaticExecutionStatus: 'not_ready',
      automaticExecutionReason: 'No external scheduled trigger is integrated. The in-process scheduler can stop when the API sleeps.',
      externalTriggerConfigured: false };
  })()`);
  await click(`${backupScope} button`, "Refresh");
  await wait(`document.querySelector('#settings-database-backup-state').textContent === 'Ready'`, "backend supplied completed history");
  assert.ok(await evaluate(`document.querySelectorAll('${backupScope} dd')[0].textContent.includes('7:00 PM') && document.querySelectorAll('${backupScope} dd')[0].textContent.includes('1 MB')`));
  assert.ok(await evaluate(`document.querySelectorAll('${backupScope} dd')[1].textContent.startsWith('Off')`));
  assert.ok(await evaluate(`document.querySelectorAll('${backupScope} dd')[2].textContent.startsWith('Not active')`));
  assert.equal(await evaluate(`document.querySelector('${backupScope} .database-backup-policy').open`), false);
  assert.ok(await evaluate(`document.querySelector('${backupScope} .database-backup-policy').textContent.includes('30 days')`));
  assert.ok(await evaluate(`document.querySelector('${backupScope} .database-backup-policy').textContent.includes('Cleanup is disabled')`));
  assert.ok(await evaluate(`document.querySelector('${backupScope} .database-backup-warning').textContent.includes('disabled in the backend configuration')`));
  await evaluate(`__settings.backup.schedule.enabled = true; __settings.backup.automaticExecutionReason = 'The external scheduler is not configured with its protected API trigger.'`);
  await click(`${backupScope} button`, "Refresh");
  await wait(`document.querySelectorAll('${backupScope} dd')[1].textContent.startsWith('Trigger missing')`, "external trigger readiness");
  assert.ok(await evaluate(`document.querySelector('${backupScope} .database-backup-warning').textContent.includes('protected API trigger')`));
  await evaluate(`__settings.backup.externalTriggerConfigured = true; __settings.backup.automaticExecutionReason = 'Restore verification is pending.'`);
  await click(`${backupScope} button`, "Refresh");
  await wait(`document.querySelectorAll('${backupScope} dd')[1].textContent.startsWith('Pending verification')`, "automatic execution readiness");
  assert.ok(await evaluate(`document.querySelector('${backupScope} .database-backup-warning').textContent.includes('Restore verification is pending')`));
  await evaluate(`__settings.backup.automaticExecutionStatus = 'ready'`);
  await click(`${backupScope} button`, "Refresh");
  await wait(`document.querySelectorAll('${backupScope} dd')[1].textContent.trim() === 'On'`, "automatic backup ready");
  assert.deepEqual(await evaluate(`[...document.querySelectorAll('${backupScope} tbody tr')].map(r => r.cells[1].textContent)`), ["Manual", "Monthly archive", "Automatic"]);
  assert.deepEqual(await evaluate(`[...document.querySelectorAll('${backupScope} tbody tr')].map(r => r.cells[3].textContent)`), ["1 MB", "2 KB", "—"]);
  assert.equal(await evaluate(`document.querySelectorAll('${backupScope} tbody button').length`), 2);
  assert.equal(await evaluate(`document.querySelector('${backupScope} tbody button').disabled`), false);
  await click(`${backupScope} tbody button`, "Download");
  assert.equal(await evaluate(`__settings.requests.at(-1).method`), "GET");
  assert.ok(await evaluate(`__settings.requests.at(-1).path.endsWith('/admin-settings/backups/${"a".repeat(32)}/download')`));
  await click(`${backupScope} .primary-btn`, "Back Up Now");
  assert.equal(await evaluate(`__settings.requests.find(r => r.path.endsWith('/admin-settings/backups/run'))?.method`), "POST");
  for (const state of ["running", "failed"]) {
    await evaluate(`__settings.backup.status = '${state}'; __settings.backup.schedule.enabled = false`);
    await click(`${backupScope} button`, "Refresh");
    await wait(`document.querySelector('#settings-database-backup-state').textContent === '${state === "running" ? "Running" : "Failed"}'`, `${state} backup response`);
    assert.ok(await evaluate(`document.querySelectorAll('${backupScope} dd')[1].textContent.startsWith('Off')`));
    assert.equal(
      await evaluate(`document.querySelector('${backupScope} .primary-btn').disabled`),
      state === "running",
    );
  }
  await evaluate(`__settings.backup = { ...__settings.originalBackup, history: [] }`);
  await click(`${backupScope} button`, "Refresh");
  await wait(`document.querySelector('${backupScope} tbody').textContent.includes('No backup runs have been reported')`, "actual empty ledger");
  await evaluate(`__settings.backup = structuredClone(__settings.originalBackup)`);
  await click(`${backupScope} button`, "Refresh");
  await wait(`document.querySelector('#settings-database-backup-state').textContent === 'Not configured'`, "unconfigured status restored");
  assert.ok(await evaluate(`__settings.requests.filter(r => r.path.includes('database-backup')).every(r => r.method === 'GET')`));
  record("Backend-supplied Ready/Running/Failed, Manila timestamps, sizes, monthly history, authenticated actions, and the disabled schedule render accurately");

  await click("#settings-preferences-body button", "Dark");
  await click("#settings-preferences-body button", "Off");
  await click("#settings-preferences-body button", "Save Preferences");
  await wait(`document.querySelector('#settings-preferences-body [role="alert"]')`, "save failure");
  assert.equal(await evaluate(`localStorage.getItem('revela_emailAlerts')`), "true");
  assert.equal(await evaluate(`localStorage.getItem('revela-theme')`), "dark");
  assert.equal(await evaluate(`__settings.user.emailInspectionAlerts`), true);
  await closeAlert();
  record("Rejected email save preserves confirmed fallback; theme remains browser-local");

  const meBefore = await count("/auth/me");
  await evaluate(`__settings.modes.preferences = 'success'; __settings.modes.refreshFail = true`);
  await click("#settings-preferences-body button", "Save Preferences");
  await wait(`localStorage.getItem('revela_emailAlerts') === 'false' && !document.querySelector('#settings-preferences-state')`, "confirmed preference save");
  assert.ok(await evaluate(`document.querySelector('#settings-preferences-summary').textContent.includes('Email Off (account)')`));
  assert.equal(await count("/auth/me"), meBefore);
  await closeAlert();
  record("Confirmed save updates account summary without a fragile follow-up refresh");

  await evaluate(`__settings.modes.storageFail = true`);
  await click("#settings-preferences-body button", "On");
  await click("#settings-preferences-body button", "Save Preferences");
  await wait(`document.querySelector('.swal2-html-container')?.textContent.includes('account was updated')`, "storage failure warning");
  assert.equal(await evaluate(`document.querySelector('#settings-preferences-body [role="alert"]') === null`), true);
  assert.ok(await evaluate(`document.querySelector('#settings-preferences-summary').textContent.includes('Email On (account)')`));
  await closeAlert();
  await evaluate(`__settings.modes.storageFail = false; __settings.modes.preferences = 'invalid'`);
  await click("#settings-preferences-body button", "Off");
  await click("#settings-preferences-body button", "Save Preferences");
  await wait(`document.querySelector('#settings-preferences-body [role="alert"]')`, "invalid save response rejected");
  assert.equal(await evaluate(`localStorage.getItem('revela_emailAlerts')`), "false");
  assert.equal(await evaluate(`__settings.user.emailInspectionAlerts`), true);
  await closeAlert();
  record("Browser cache errors are not mislabeled as server failures; unconfirmed responses are rejected");

  await click("#settings-security-body button", "Enable");
  await wait(`document.querySelector('.modal-backdrop')?.textContent.includes('Retry setup')`, "2FA setup failure");
  assert.equal(await evaluate(`document.querySelector('.modal-backdrop input')`), null);
  assert.equal(await count("/auth/verify-2fa-setup"), 0);
  await evaluate(`__settings.modes.setup = 'incomplete'`);
  await click(".modal-backdrop button", "Retry setup");
  await wait(`document.querySelector('.modal-backdrop')?.textContent.includes('Retry setup')`, "incomplete setup rejected");
  assert.equal(await evaluate(`document.querySelector('.modal-backdrop input')`), null);
  await evaluate(`__settings.modes.setup = 'held'`);
  await click(".modal-backdrop button", "Retry setup");
  await wait(`document.querySelector('.modal-backdrop')?.textContent.includes('Generating secure keys')`, "pending setup");
  assert.equal(await evaluate(`document.querySelector('.modal-backdrop form')`), null);
  await evaluate(`__settings.modes.setup = 'success'; __settings.releaseSetup()`);
  await wait(`document.querySelector('.modal-backdrop input[maxlength="6"]')`, "retry succeeds");
  await input('.modal-backdrop input[maxlength="6"]', "12345");
  assert.equal(await evaluate(`document.querySelector('.modal-backdrop button[type="submit"]').disabled`), true);
  await input('.modal-backdrop input[maxlength="6"]', "999999");
  await click(".modal-backdrop button", "Verify & Enable");
  await wait(`document.querySelector('.modal-backdrop')?.textContent.includes('Invalid 2FA code')`, "invalid code error");
  await input('.modal-backdrop input[maxlength="6"]', "123456");
  await click(".modal-backdrop button", "Verify & Enable");
  await wait(`!document.querySelector('.modal-backdrop') && [...document.querySelectorAll('#settings-security-body button')].some(b => b.textContent === 'Disable')`, "2FA enabled");
  await closeAlert();
  await click("#settings-security-body button", "Disable");
  await click(".swal2-container button", "Cancel");
  assert.equal(await count("/auth/disable-2fa"), 0);
  await click("#settings-security-body button", "Disable");
  await click(".swal2-container button", "Yes, disable it");
  await wait(`[...document.querySelectorAll('#settings-security-body button')].some(b => b.textContent === 'Enable')`, "2FA disabled");
  await closeAlert();
  record("Failed, incomplete, and pending setup cannot verify; retry/invalid code/enable/disable work");

  assert.equal(await evaluate(`document.querySelectorAll('button.settings-cutoff-card[aria-pressed]').length`), 5);
  assert.equal(await evaluate(`document.querySelectorAll('button.settings-manual-card').length`), 6);
  await evaluate(`document.querySelectorAll('.settings-cutoff-card')[0].focus()`);
  await key("Tab", "Tab", 9);
  assert.equal(await evaluate(`document.activeElement === document.querySelectorAll('.settings-cutoff-card')[1]`), true,
    JSON.stringify(await evaluate(`({ active: document.activeElement?.outerHTML, focused: document.hasFocus(), cards: [...document.querySelectorAll('.settings-cutoff-card')].map(e => ({ disabled: e.disabled, tabIndex: e.tabIndex, visible: e.getClientRects().length })) })`)));
  await key("Enter", "Enter", 13);
  assert.equal(await evaluate(`document.activeElement.getAttribute('aria-pressed')`), "true");
  await evaluate(`document.querySelectorAll('.settings-cutoff-card')[2].focus()`);
  await key(" ", "Space", 32);
  assert.equal(await evaluate(`document.activeElement.getAttribute('aria-pressed')`), "true");
  for (const [index, name, code, virtualKey, expected] of [[0, "Enter", "Enter", 13, "Roles and access"], [1, " ", "Space", 32, "Map & Flags"]]) {
    await evaluate(`document.querySelectorAll('.settings-manual-card')[${index}].focus()`);
    await key(name, code, virtualKey);
    await wait(`document.querySelector('.instructional-manual-reader h3')`, "keyboard guide opens");
    assert.equal(await evaluate(`document.querySelector('.instructional-manual-reader h3').textContent`), expected);
    await click(".instructional-manual-panel button", "Close guide");
    await wait(`!document.querySelector('.modal-backdrop')`, "manual closed");
  }
  record("Age filters and manual cards support native Tab, Enter, and Space");

  await evaluate(`__settings.modes.cleanup = 'failure'`);
  const statsBefore = await count("/inspections/evidence-storage-stats");
  await click("#settings-evidence-body button", "Clear Server Storage");
  await click(".swal2-container button", "I have backup, Clear Storage");
  await wait(`document.querySelector('.swal2-title')?.textContent === 'Cleanup Failed'`, "cleanup error");
  await closeAlert();
  await wait(`__settings.requests.filter(r => r.path.endsWith('/evidence-storage-stats')).length > ${statsBefore}`, "usage refresh on failure");
  await evaluate(`__settings.modes.cleanup = 'pending'`);
  await click("#settings-evidence-body button", "Clear Server Storage");
  await click(".swal2-container button", "I have backup, Clear Storage");
  await wait(`document.querySelector('.swal2-title')?.textContent === 'Cleanup Needs Attention'`, "pending backup warning");
  await closeAlert();
  await wait(`document.querySelector('#settings-evidence-body .settings-warning')`, "pending recovery remains visible");
  assert.equal(await evaluate(`[...document.querySelectorAll('#settings-evidence-body button')].find(b => b.textContent.trim() === 'Clear Server Storage').disabled`), false);
  await evaluate(`__settings.modes.cleanup = 'success'`);
  await click("#settings-evidence-body button", "Clear Server Storage");
  await wait(`document.querySelector('.swal2-title')?.textContent === 'Retry Pending Cleanup?'`, "recovery retry confirmation");
  await click(".swal2-container button", "I have backup, Clear Storage");
  await wait(`document.querySelector('.swal2-title')?.textContent === 'Storage Cleared'`, "recovery retry succeeds");
  await closeAlert();
  await wait(`!document.querySelector('#settings-evidence-body .settings-warning')`, "recovery warning clears");
  record("Cleanup failures never show success; pending recovery warns and remains retryable with zero eligible reports");

  for (const section of ["preferences", "security", "evidence", "manual"]) {
    await evaluate(`(() => { const button = document.querySelector('#settings-${section}-title').closest('button'); if (button.getAttribute('aria-expanded') === 'true') button.click(); })()`);
  }
  for (const theme of ["light", "dark"]) {
    await evaluate(`document.documentElement.classList.toggle('theme-dark', ${theme === "dark"}); document.documentElement.classList.toggle('theme-light', ${theme === "light"})`);
    for (const width of [1440, 1280, 1024, 768, 600]) {
      await call("Emulation.setDeviceMetricsOverride", { width, height: 1100, deviceScaleFactor: 1, mobile: false, screenWidth: width, screenHeight: 1100 });
      await sleep(200);
      await evaluate(`document.querySelector('#settings-database-backup-title').scrollIntoView({ block: 'start' })`);
      const layout = await evaluate(`(() => {
        const section = document.querySelector('#settings-database-backup-title').closest('section');
        const panel = document.querySelector('.database-backup-panel');
        const b = section.getBoundingClientRect();
        return { viewportOverflow: document.documentElement.scrollWidth > innerWidth, sectionOverflow: section.scrollWidth > section.clientWidth + 1,
          panelOverflow: panel.scrollWidth > panel.clientWidth + 1, cardInViewport: b.left >= 0 && b.right <= innerWidth,
          buttonsFit: [...panel.querySelectorAll('.database-backup-buttons button')].every(button => { const r = button.getBoundingClientRect(); return r.left >= b.left && r.right <= b.right; }),
          titleFont: getComputedStyle(document.querySelector('#settings-database-backup-title')).fontSize,
          matchingBorder: getComputedStyle(section).borderRadius === getComputedStyle(document.querySelector('#settings-evidence-title').closest('section')).borderRadius };
      })()`);
      assert.deepEqual(layout, { viewportOverflow: false, sectionOverflow: false, panelOverflow: false, cardInViewport: true, buttonsFit: true, titleFont: "18px", matchingBorder: true }, `${theme} ${width}px backup layout`);
      const { data } = await call("Page.captureScreenshot", { format: "png", fromSurface: true, captureBeyondViewport: false });
      await writeFile(join(profile, `database-backup-${theme}-${width}.png`), Buffer.from(data, "base64"));
    }
  }
  record("Database Backup matches existing card typography/radius and fits 600–1440px in light/dark themes without overflow");
  assert.deepEqual(exceptions, []);
  console.log(JSON.stringify({ checks, exceptions, profile, note: "Synthetic API only; no live account, database, evidence, or provider changed." }, null, 2));
} catch (error) {
  console.error(error);
  if (call && session) {
    try {
      const result = await call("Runtime.evaluate", { expression: "({ text: document.body.innerText, requests: window.__settings?.requests })", returnByValue: true });
      await writeFile(join(profile, "failed-state.json"), JSON.stringify(result.result?.value, null, 2));
      console.error(`Failure state: ${profile}`);
    } catch { /* Browser may already be closed. */ }
  }
  process.exitCode = 1;
} finally {
  if (call) await call("Browser.close", {}, undefined).catch(() => {});
  socket?.close();
  browser?.kill();
  await server.httpServer.close();
}
