import test from "node:test";
import assert from "node:assert/strict";
import { availableNumber, dateQuery, deadlinePresentation, formatOverviewNumber, manilaGreeting, weatherPresentation } from "./overviewPresentation.js";

test("reported zeros stay distinct from unavailable or malformed metric fields", () => {
  assert.equal(formatOverviewNumber(0), "0");
  assert.equal(formatOverviewNumber("0", "%"), "0%");
  assert.equal(formatOverviewNumber(12345), "12,345");
  assert.equal(formatOverviewNumber(76.3, "%"), "76.3%");
  for (const value of [null, undefined, "", " ", "not a number", NaN, Infinity, false, {}, []]) {
    assert.equal(availableNumber(value), null);
    assert.equal(formatOverviewNumber(value, "%"), "—");
  }
});

test("greeting periods use Manila time independently of the browser timezone", () => {
  assert.equal(manilaGreeting(new Date("2026-10-13T16:00:00Z")), "Good morning");
  assert.equal(manilaGreeting(new Date("2026-10-14T03:59:59Z")), "Good morning");
  assert.equal(manilaGreeting(new Date("2026-10-14T04:00:00Z")), "Good afternoon");
  assert.equal(manilaGreeting(new Date("2026-10-14T10:00:00Z")), "Good evening");
});

test("weather descriptions and icons match clear, cloudy, rain, fog and storm codes", () => {
  for (const [code, icon, description] of [
    [0, "sun", "Clear sky"], [2, "partly-cloudy", "Partly cloudy"],
    [3, "cloud", "Overcast"], [45, "fog", "Fog"], [65, "rain", "Heavy rain"],
    [75, "snow", "Heavy snow"], [95, "thunderstorm", "Thunderstorm"],
    [99, "thunderstorm", "Thunderstorm with heavy hail"],
  ]) {
    const weather = weatherPresentation({ current: { temperature_2m: 29.6, weather_code: code } });
    assert.equal(weather.temperature, "30°C");
    assert.equal(weather.icon, icon);
    assert.equal(weather.description, description);
    assert.equal(weather.partial, false);
    assert.equal(weather.observation, null);
  }
});

test("unknown and incomplete weather responses never substitute favorable conditions", () => {
  const unknown = weatherPresentation({ current: { temperature_2m: 0, weather_code: 999 } });
  assert.equal(unknown.temperature, "0°C");
  assert.equal(unknown.description, "Unknown weather code");
  assert.equal(unknown.icon, "unknown");
  assert.equal(unknown.partial, true);
  const missing = weatherPresentation({ current: {} });
  assert.equal(missing.temperature, "—");
  assert.equal(missing.description, "Conditions unavailable");
  assert.equal(missing.icon, "unknown");
  for (const data of [null, {}, { current: null }, { current: [] }]) {
    assert.equal(weatherPresentation(data), null);
  }
});

test("an observation is shown only when the response provides an interpretable timestamp", () => {
  const data = { utc_offset_seconds: 0, current: { temperature_2m: 30, weather_code: 2, time: "2026-10-14T04:00" } };
  const utc = weatherPresentation(data).observation;
  assert.match(utc, /Oct 14/);
  assert.match(utc, /12:00\s?PM/i);
  assert.equal(weatherPresentation({ ...data, utc_offset_seconds: 28800, current: { ...data.current, time: "2026-10-14T12:00" } }).observation, utc);
  assert.equal(weatherPresentation({ current: { ...data.current, time: "2026-10-14T04:00Z" } }).observation, utc);
  assert.equal(weatherPresentation({ current: data.current }).observation, null);
  assert.equal(weatherPresentation({ ...data, current: { ...data.current, time: "invalid" } }).observation, null);
});

test("selected dates without deadlines remain empty instead of falling back to other assignments", () => {
  const month = new Date(2026, 9, 1);
  const now = new Date(2026, 9, 14, 12);
  const inspections = Object.freeze([
    Object.freeze({ reportID: 1, verificationStatus: "Assigned", deadline: "2026-10-20T12:00:00" }),
    Object.freeze({ reportID: 2, verificationStatus: "Reassigned", deadline: "2026-10-10T12:00:00" }),
    Object.freeze({ reportID: 3, verificationStatus: "Verified", deadline: "2026-10-10T12:00:00" }),
    Object.freeze({ reportID: 4, verificationStatus: "Assigned", deadline: "invalid" }),
    Object.freeze({ reportID: 5, verificationStatus: "Assigned" }),
  ]);
  const view = deadlinePresentation(inspections, month, null, now);
  assert.deepEqual(view.displayedTasks.map(task => task.reportID), [2, 1]);
  assert.deepEqual(view.statusByDate, { 10: "overdue", 20: "upcoming" });
  assert.deepEqual(deadlinePresentation(inspections, month, 15, now).displayedTasks, []);
  assert.deepEqual(deadlinePresentation(inspections, month, 10, now).displayedTasks.map(task => task.reportID), [2]);
  assert.deepEqual(inspections.map(task => task.reportID), [1, 2, 3, 4, 5]);
});

test("deadline scope retains the earliest three default tasks and all tasks on a selected date", () => {
  const month = new Date(2026, 9, 1);
  const now = new Date(2026, 9, 14, 12);
  const tasks = Array.from({ length: 5 }, (_, reportID) => ({ reportID, verificationStatus: "Assigned", deadline: "2026-10-20T12:00:00" }));
  tasks.push({ reportID: 6, verificationStatus: "Reassigned", deadline: "2026-11-01T12:00:00" });
  assert.equal(deadlinePresentation(tasks, month, null, now).displayedTasks.length, 3);
  assert.equal(deadlinePresentation(tasks, month, 20, now).displayedTasks.length, 5);
  assert.equal(deadlinePresentation(tasks, new Date(2026, 10, 1), 1, now).displayedTasks[0].reportID, 6);
  assert.deepEqual(deadlinePresentation(undefined, month, 15, now).displayedTasks, []);
  assert.equal(dateQuery(new Date(2026, 9, 5)), "2026-10-05");
});
