import test from "node:test";
import assert from "node:assert/strict";
import { backupStatusPresentation, formatBackupDate, formatBackupSize, validateBackupStatus } from "./backupStatusView.js";

const unconfigured = () => ({
  status: "not_configured", configured: false, lastSuccessfulBackup: null, history: null,
  schedule: { configured: false, enabled: false, nextRunAt: null, summary: null },
  retention: { configured: false, summary: null },
});

test("unconfigured backend is not interpreted as a successful or empty backup ledger", () => {
  const data = validateBackupStatus(unconfigured());
  assert.equal(backupStatusPresentation(data, false, "").summary, "Not configured · No successful backup yet");
  assert.equal(data.history, null);
  assert.equal(data.schedule.nextRunAt, null);
});

test("unconfirmed, unknown, and inconsistent readiness fail closed", () => {
  for (const data of [null, {}, { ...unconfigured(), status: "success" },
    { ...unconfigured(), status: "ready" }, { ...unconfigured(), history: [{}] },
    { ...unconfigured(), lastSuccessfulBackup: { id: "fake", trigger: "manual", status: "running" } }]) {
    assert.throws(() => validateBackupStatus(data), /incomplete database backup status/);
  }
});

test("status fetch errors are not presented as failed backup runs or stale readiness", () => {
  const ready = { ...unconfigured(), configured: true, status: "ready" };
  assert.equal(backupStatusPresentation(ready, true, "").text, "Loading…");
  assert.equal(backupStatusPresentation(ready, false, "Server unavailable").text, "Status unavailable");
  assert.equal(backupStatusPresentation({ ...ready, status: "failed" }, false, "").text, "Failed");
  assert.equal(backupStatusPresentation({ ...ready, status: "running" }, false, "").text, "Running");
});

test("timestamps use Manila time, including date rollover, and ambiguous dates stay unknown", () => {
  assert.match(formatBackupDate("2026-10-23T11:00:00Z"), /Oct 23, 2026.*7:00 PM/);
  assert.match(formatBackupDate("2026-10-23T18:30:00Z"), /Oct 24, 2026.*2:30 AM/);
  assert.equal(formatBackupDate("2026-10-23T19:00:00+08:00"), formatBackupDate("2026-10-23T11:00:00Z"));
  for (const value of [null, "", "invalid", "2026-10-23T19:00:00", "2026-10-23"]) {
    assert.equal(formatBackupDate(value), "—");
  }
});

test("unknown file sizes never become a fabricated zero-byte backup", () => {
  for (const value of [null, undefined, -1, NaN, Infinity, "1024"]) assert.equal(formatBackupSize(value), "—");
  assert.equal(formatBackupSize(0), "0 B");
  assert.equal(formatBackupSize(1536), "1.5 KB");
  assert.equal(formatBackupSize(1048576), "1 MB");
});
