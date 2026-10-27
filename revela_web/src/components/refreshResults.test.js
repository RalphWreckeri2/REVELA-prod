import test from "node:test";
import assert from "node:assert/strict";
import { refreshResults } from "./useAppDataRefresh.js";

test("required reads are awaited; partial failures do not claim success", async () => {
  let finish;
  const pending = new Promise(resolve => { finish = resolve; });
  let completed = false;
  const result = refreshResults([Promise.resolve(true), pending]);
  result.then(() => { completed = true; });
  await Promise.resolve();
  assert.equal(completed, false);
  finish(false);
  assert.deepEqual(await result, { ok: false, status: "partial-failure" });
  assert.deepEqual(await refreshResults([Promise.resolve(false), Promise.reject(new Error("network"))]), { ok: false, status: "failure" });
  assert.deepEqual(await refreshResults([Promise.resolve(true), Promise.resolve({ ok: true })]), { ok: true, status: "success" });
});
