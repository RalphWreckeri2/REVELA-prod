import test from "node:test";
import assert from "node:assert/strict";
import { recordedDeadline, deadlineGroups, deadlineStatusCounts, loadLatestAssignments } from "./deadlineCalendar.js";

test("naive deadlines retain their civil Philippine date; explicit offsets convert to Manila", () => {
  assert.equal(recordedDeadline("2026-10-30 00:15:00").date, "2026-10-30");
  assert.equal(recordedDeadline("2026-10-30T23:59:00").clock, "23:59");
  assert.equal(recordedDeadline("2026-10-29T18:00:00Z").date, "2026-10-30");
  assert.equal(recordedDeadline("2026-10-30").date, "2026-10-30");
  for (const value of [null, "", "invalid", "2026-02-30 12:00:00", "2026-10-30T24:00", "2026-10-30T12:60", "2026-10-30T12:00+15:00"]) assert.equal(recordedDeadline(value), null);
});
test("deadline groups deduplicate identities and include submitted and verified", () => {
  const reports = ["Assigned", "Reassigned", "Submitted", "Verified"].map((verificationStatus, i) => ({ reportID: i + 1, deadline: "2026-10-30 08:00:00", verificationStatus }));
  const groups = deadlineGroups([...reports, reports[0], { reportID: 5, deadline: null }]);
  assert.equal(groups.days.get("2026-10-30").length, 4);
  assert.equal(groups.excluded, 1);
  assert.deepEqual(deadlineStatusCounts(groups.days.get("2026-10-30")), { pending: 2, submitted: 1, verified: 1, other: 0 });
});
test("all declared pages are loaded without status filters or retry loops", async () => {
  const calls = [];
  const rows = await loadLatestAssignments(async ({ page, limit }) => {
    calls.push(page);
    return { page, per_page: limit, total: 3, pages: 2, data: page === 1 ? [{ reportID: 1 }, { reportID: 2 }] : [{ reportID: 3 }] };
  }, { limit: 2 });
  assert.deepEqual(calls, [1, 2]);
  assert.equal(rows.length, 3);
});
test("duplicates, shortened pages, changing totals, and request failures withhold results", async () => {
  for (const fault of ["duplicate", "short", "changed", "failure"]) {
    await assert.rejects(loadLatestAssignments(async ({ page, limit }) => {
      if (page === 2 && fault === "failure") throw new Error("offline");
      return { page, per_page: limit, total: page === 2 && fault === "changed" ? 4 : 3, pages: 2,
        data: page === 1 ? [{ reportID: 1 }, { reportID: 2 }] : fault === "short" ? [] : [{ reportID: fault === "duplicate" ? 2 : 3 }] };
    }, { limit: 2 }));
  }
});
test("superseded loads stop fetching subsequent pages", async () => {
  let current = true;
  let calls = 0;
  const result = await loadLatestAssignments(async ({ page, limit }) => {
    calls += 1; current = false;
    return { page, per_page: limit, total: 3, pages: 2, data: [{ reportID: 1 }, { reportID: 2 }] };
  }, { limit: 2, isCurrent: () => current });
  assert.equal(result, null);
  assert.equal(calls, 1);
});
