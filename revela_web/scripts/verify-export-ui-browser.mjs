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
      await evaluate("window.dispatchEvent(new Event('afterprint'))");
      await waitFor("!document.querySelector('.print-report-container')");
    }
    await evaluate("[...document.querySelectorAll('.export-report-view-nav button')].find(button => button.textContent.includes('Field reports')).click()");
    await waitFor("document.querySelector('.operational-report-card') && !document.querySelector('#chart-card-size')");
    assert.equal(await evaluate("Boolean(document.querySelector('.export-profile-menu'))"), false);
    assert.equal(await evaluate("document.querySelectorAll('.operational-report-card').length"), 3);
    assert.equal(await evaluate("Boolean(document.querySelector('.operational-report-details:not([open]) > summary'))"), true);
    if (width === 1440 && theme === "light") {
      await evaluate(`(() => {
        const original = window.fetch;
        window.fetch = (input, options) => {
          const path = new URL(input, location.href).pathname;
          if (path.endsWith('/flags/inspection-verified-compliant')) return Promise.resolve(Response.json({
            data: Array.from({ length: 2 }, (_, i) => ({ detectionReference: i + 1, businessName: 'Verified business ' + i,
              barangayID: 2, barangayName: 'Barangay II', address: 'Municipal Road, Mataasnakahoy', originSource: 'detection',
              verifiedOn: '2026-10-25T14:00:00Z', registryLinked: i === 0 })), generatedAt: '2026-10-31T10:00:00Z'
          }));
          if (path.endsWith('/flags/') || path.endsWith('/flags')) return Promise.resolve(Response.json({ data: Array.from({ length: 224 }, (_, i) => ({
            flagColor: i % 10 === 0 ? 'Yellow' : 'Red', detectedName: 'Field candidate ' + (i + 1),
            barangayName: 'Barangay II', resolvedAddress: 'Municipal Road, Mataasnakahoy, Batangas, Philippines',
            detectedDate: '2026-10-30T10:00:00Z'
          })) }));
          if (path.endsWith('/analytics/all')) return Promise.resolve(Response.json({ prescriptive: {
            rankings: Array.from({ length: 16 }, (_, i) => ({ rank: i + 1, barangayName: 'Barangay ' + (i + 1),
              ops_score: 95 - i * 4, risk_level: i < 4 ? 'High' : 'Medium', priority_label: i < 4 ? 'High Priority' : 'Standard',
              flagged_count: 20 - i, dispatchable_count: 12 - Math.floor(i / 2), registry_active_flag_rate: 0 })),
            workforce: {}, model: {}
          } }));
          return original(input, options);
        };
      })()`);

      const checkPdf = async (selector, rows, name) => {
        await waitFor(`document.querySelector('${selector}')`);
        assert.equal(await evaluate(`document.querySelectorAll('${selector} .print-table:first-of-type tbody tr').length`), rows);
        await call("Emulation.setEmulatedMedia", { media: "print" });
        const printStyle = await evaluate(`(() => ({
          header: getComputedStyle(document.querySelector('.print-header')).position,
          footer: getComputedStyle(document.querySelector('.print-footer')).position,
          colors: [...new Set([...document.querySelectorAll('${selector} .print-table th')]
            .map(th => getComputedStyle(th).backgroundColor))]
        }))()`);
        assert.equal(printStyle.header, "fixed");
        assert.equal(printStyle.footer, "fixed");
        assert.deepEqual(printStyle.colors, ["rgb(234, 241, 237)"], `${name} uses the quiet table palette`);
        const pdf = await call("Page.printToPDF", { printBackground: true, preferCSSPageSize: true });
        const pdfBuffer = Buffer.from(pdf.data, "base64");
        const pages = (pdfBuffer.toString("latin1").match(/\/Type\s*\/Page\b/g) || []).length;
        assert.ok(pages > 0 && pages <= (name === "unregistered" ? 10 : name === "dispatch" ? 2 : 1),
          `${name} fits within the expected printed pages (${pages})`);
        if (process.env.REVELA_EXPORT_CAPTURE) {
          const output = join(tempRoot, `revela-export-${name}.pdf`);
          await writeFile(output, pdfBuffer);
          console.log(`Print preview: ${output}`);
        }
        await call("Emulation.setEmulatedMedia", { media: "screen" });
        await evaluate("window.dispatchEvent(new Event('afterprint')); document.querySelector('.swal2-container')?.remove(); document.body.classList.remove('swal2-shown', 'swal2-height-auto')");
        await waitFor("!document.querySelector('.print-report-container')");
      };
      const download = async label => {
        const button = label === "Inspection-Verified Compliant Businesses" ? ".compliance-report-download" : ".primary-btn";
        await evaluate(`(() => { const card = [...document.querySelectorAll('.operational-report-card')].find(el => el.textContent.includes(${JSON.stringify(label)})); card.querySelector(${JSON.stringify(button)}).click(); })()`);
        await waitFor("document.querySelector('.swal2-radio input[value=pdf]')");
        await evaluate("document.querySelector('.swal2-radio input[value=pdf]').click(); document.querySelector('.swal2-confirm').click()");
      };

      await download("List of Unregistered Businesses");
      await checkPdf(".unregistered-print-body", 224, "unregistered");
      await download("Inspection-Verified Compliant Businesses");
      await checkPdf(".inspection-print-body", 2, "inspection-compliant");
      await download("Field Inspector Dispatch Plan");
      await checkPdf(".dispatch-print-body", 16, "dispatch");
    }
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
