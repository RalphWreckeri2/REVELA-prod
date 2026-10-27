import test from "node:test";
import assert from "node:assert/strict";
import { formatElapsedMinutes } from "./formatElapsedMinutes.js";

test("elapsed minutes round before splitting and carry through hours and days", () => {
  for (const [minutes, expected] of [
    [3, "3 min"], [65, "1h 5 min"], [1204.9, "20h 5 min"],
    [5942, "4d 3h 2 min"], [59.5, "1h"], [1439.5, "1d"],
    [1500.5, "1d 1h 1 min"], [0.49, "0 min"], [0.5, "1 min"],
    [60, "1h"], [1440, "1d"], [2881, "2d 1 min"],
  ]) assert.equal(formatElapsedMinutes(minutes), expected);
});

test("missing, invalid and negative durations never become zero", () => {
  for (const value of [null, undefined, "", "0", Number.NaN, Infinity, -1, -0.1, Number.MAX_VALUE]) {
    assert.equal(formatElapsedMinutes(value), "Unavailable");
  }
  assert.equal(formatElapsedMinutes(0), "0 min");
});
