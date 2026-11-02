import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import {
  beginBenchmark, benchmarkStage, endMapBenchmark, finishBenchmark, installBenchmarkControls,
  mapIdle, mapReady, mapTilesLoaded, mapViewportChanged, markMapBenchmarkUnmount,
  markMapNavigation, startMapBenchmark,
} from './responsivenessBenchmark.js';

const mapPageSource = readFileSync(new URL('../pages/MapPage.jsx', import.meta.url), 'utf8');

function storage() {
  const values = new Map();
  return {
    getItem: key => values.get(key) ?? null,
    setItem: (key, value) => values.set(key, value),
    removeItem: key => values.delete(key),
  };
}

test('direct map loads keep document timing while SPA trials use their own start', () => {
  const sessionStorage = storage();
  globalThis.window = {
    sessionStorage,
    location: { pathname: '/map', href: 'https://revela.test/map?trial=direct' },
    performance: {
      getEntriesByType: () => [{
        name: 'https://revela.test/map?trial=direct',
        type: 'navigate',
        startTime: 0,
      }],
    },
  };
  window.sessionStorage.setItem('revela:benchmark:enabled', '1');
  const documentTrial = startMapBenchmark();
  assert.equal(documentTrial.workload.navigation, 'document');
  assert.equal(documentTrial.startedAt, 0);
  endMapBenchmark(documentTrial);

  window.location.pathname = '/home';
  markMapNavigation({ button: 0 });
  window.location.pathname = '/map';
  const spaTrial = startMapBenchmark();
  assert.equal(spaTrial.workload.navigation, 'spa');
  assert.ok(spaTrial.startedAt > 0);
  endMapBenchmark(spaTrial);

  const laterMapTrial = startMapBenchmark();
  assert.equal(laterMapTrial.workload.navigation, 'mount');
  assert.ok(laterMapTrial.startedAt > 0);
  endMapBenchmark(laterMapTrial);
  delete globalThis.window;
});

test('configure merges settings and map trials use navigation start with identity-safe remount cleanup', () => {
  const sessionStorage = storage();
  globalThis.window = { sessionStorage };
  window.revelaBenchmark = undefined;
  installBenchmarkControls(async () => ({}));
  window.revelaBenchmark.enable({ cache: 'warm', network: 'wifi', registry_rows: 605 });
  window.revelaBenchmark.configure({ network: 'ethernet' });
  const configured = beginBenchmark('settings-check');
  assert.equal(configured.cache, 'warm');
  assert.equal(configured.network, 'ethernet');
  assert.equal(configured.registry_rows, 605);

  markMapNavigation({ button: 0 });
  const spaTrial = startMapBenchmark();
  assert.equal(spaTrial.workload.navigation, 'spa');
  assert.ok(spaTrial.startedAt > 0);
  markMapBenchmarkUnmount(spaTrial);
  const remountedTrial = startMapBenchmark();
  assert.notEqual(remountedTrial, spaTrial);
  assert.equal(remountedTrial.workload.navigation, 'mount');
  endMapBenchmark(spaTrial);
  assert.equal(startMapBenchmark(), remountedTrial);

  endMapBenchmark(remountedTrial);
  markMapNavigation({ button: 1 });
  assert.equal(startMapBenchmark().workload.navigation, 'mount');
  endMapBenchmark();
  delete globalThis.window;
});

test('incomplete map results retain configured and measured metadata', () => {
  const sessionStorage = storage();
  globalThis.window = { sessionStorage };
  window.sessionStorage.setItem('revela:benchmark:enabled', '1');
  window.sessionStorage.setItem('revela:benchmark:config', JSON.stringify({
    registry_rows: 5, map_rows: 10, geolocated_rows: 4, expected_markers: 4,
  }));
  const trial = beginBenchmark('map');
  trial.requestId = 'page-request';
  trial.httpStatus = 206;
  trial.pages = 1;
  benchmarkStage(trial, 'data', {
    mapRows: 10, geolocatedRows: 4, expectedMarkers: 4, pages: 1,
  });
  benchmarkStage(trial, 'markers', { createdMarkers: 3 });
  const row = finishBenchmark(trial, 'incomplete', {
    request_id: undefined, notes: 'readiness timeout',
  });
  assert.equal(row.request_id, 'page-request');
  assert.equal(row.http_status, 206);
  assert.equal(row.registry_rows, 5);
  assert.equal(row.map_rows, 10);
  assert.equal(row.geolocated_rows, 4);
  assert.equal(row.expected_markers, 4);
  assert.equal(row.created_markers, 3);
  assert.equal(row.flags_pages, 1);
  assert.ok(Number.isFinite(row.data_ms));
  assert.ok(Number.isFinite(row.markers_ms));
  delete globalThis.window;
});

test('failed map requests retain response and pagination metadata', () => {
  const sessionStorage = storage();
  globalThis.window = { sessionStorage };
  window.sessionStorage.setItem('revela:benchmark:enabled', '1');
  window.sessionStorage.setItem('revela:benchmark:config', JSON.stringify({
    registry_rows: 5, map_rows: 10, geolocated_rows: 4, expected_markers: 4,
  }));
  const trial = beginBenchmark('map');
  trial.requestId = 'failed-page';
  trial.httpStatus = 503;
  trial.pages = 2;
  const row = finishBenchmark(trial, 'failed', { notes: 'flags request failed' });
  assert.equal(row.request_id, 'failed-page');
  assert.equal(row.http_status, 503);
  assert.equal(row.registry_rows, 5);
  assert.equal(row.map_rows, 10);
  assert.equal(row.flags_pages, 2);
  delete globalThis.window;
});

test('disabled by default; manual matcher records success and failed responses without storing candidates', async () => {
  const sessionStorage = storage();
  globalThis.window = { sessionStorage, localStorage: storage() };
  installBenchmarkControls(async (candidates, token, { onResponse }) => {
    assert.equal(token, 'mock-token');
    onResponse({ status: 200, headers: { get: () => 'fixture-req' } });
    return { registry_size: 602, candidates_evaluated: candidates.length, google_requests_made: 0, results: [{ match_status: 'auto' }] };
  });
  assert.equal(beginBenchmark('disabled'), null);
  window.revelaBenchmark.enable({ cache: 'warm', network: 'fixture' });
  window.localStorage.setItem('revela_token', 'mock-token');
  await window.revelaBenchmark.dryRun([{ name: 'DO NOT LOG', lat: 1, lng: 2 }]);
  const row = window.revelaBenchmark.rows()[0];
  assert.equal(row.request_id, 'fixture-req');
  assert.equal(row.registry_rows, 602);
  assert.equal(row.outcome, 'completed');
  assert.ok(!sessionStorage.getItem('revela:benchmark:rows').includes('DO NOT LOG'));
  installBenchmarkControls(async () => { throw new Error('mock network failure'); });
  await assert.rejects(window.revelaBenchmark.dryRun([{ lat: 1, lng: 2 }]));
  assert.equal(window.revelaBenchmark.rows()[1].outcome, 'failed');
  let downloaded;
  const createURL = URL.createObjectURL;
  const revokeURL = URL.revokeObjectURL;
  URL.createObjectURL = blob => { downloaded = blob; return 'blob:fixture'; };
  URL.revokeObjectURL = () => {};
  globalThis.document = { createElement: () => ({ click() {} }) };
  try {
    window.revelaBenchmark.exportCSV();
    const csv = await downloaded.text();
    assert.equal(csv.trim().split('\r\n').length, 3); // header + both outcomes
    assert.match(csv, /"fixture-req"/);
    assert.match(csv, /"failed"/);
  } finally {
    URL.createObjectURL = createURL;
    URL.revokeObjectURL = revokeURL;
    delete globalThis.document;
  }
  window.revelaBenchmark.disable();
  delete globalThis.window;
});

test('cached marker stages cannot satisfy readiness before fresh paginated data arrives', () => {
  globalThis.window = { sessionStorage: storage() };
  window.sessionStorage.setItem('revela:benchmark:enabled', '1');
  const trial = beginBenchmark('map');
  trial.stages = {
    markers: { ms: 1, createdMarkers: 4 },
    clustered: { ms: 2 },
    fit: { ms: 3 },
  };
  assert.equal(mapReady(trial), false);
  assert.equal(trial.readyScheduled, undefined);
  delete globalThis.window;
});

function readyMapTrial() {
  globalThis.window = { sessionStorage: storage() };
  window.sessionStorage.setItem('revela:benchmark:enabled', '1');
  const trial = beginBenchmark('map');
  trial.stages = {
    data: { ms: 1, mapRows: 2, geolocatedRows: 2, expectedMarkers: 2, pages: 1 },
    markers: { ms: 2, createdMarkers: 2 },
    clustered: { ms: 3 },
    fit: { ms: 0 },
  };
  return trial;
}

function captureAnimationFrames() {
  const original = globalThis.requestAnimationFrame;
  const frames = [];
  globalThis.requestAnimationFrame = callback => frames.push(callback);
  return {
    frames,
    restore() {
      if (original === undefined) delete globalThis.requestAnimationFrame;
      else globalThis.requestAnimationFrame = original;
    },
  };
}

test('map readiness accepts idle before tiles for the same unchanged viewport', () => {
  const trial = readyMapTrial();
  const animationFrames = captureAnimationFrames();
  try {
    assert.equal(mapIdle(trial), true);
    assert.equal(trial.stages.idle.viewportVersion, 0);
    assert.equal(animationFrames.frames.length, 0);
    assert.equal(mapTilesLoaded(trial), true);
    assert.equal(trial.stages.tiles.viewportVersion, 0);
    assert.equal(animationFrames.frames.length, 1);
    animationFrames.frames[0]();
    assert.equal(trial.finished, true);
    assert.equal(window.sessionStorage.getItem('revela:benchmark:rows').includes('"outcome":"completed"'), true);
  } finally {
    animationFrames.restore();
    delete globalThis.window;
  }
});

test('map readiness accepts tiles before idle for the same unchanged viewport', () => {
  const trial = readyMapTrial();
  const animationFrames = captureAnimationFrames();
  try {
    assert.equal(mapTilesLoaded(trial), true);
    assert.equal(trial.stages.idle, undefined);
    assert.equal(animationFrames.frames.length, 0);
    assert.equal(mapIdle(trial), true);
    assert.equal(trial.stages.tiles.viewportVersion, trial.stages.idle.viewportVersion);
    assert.equal(animationFrames.frames.length, 1);
    animationFrames.frames[0]();
    assert.equal(trial.finished, true);
  } finally {
    animationFrames.restore();
    delete globalThis.window;
  }
});

test('viewport changes between tiles and idle invalidate the earlier event', () => {
  const trial = readyMapTrial();
  const animationFrames = captureAnimationFrames();
  try {
    mapIdle(trial);
    assert.equal(mapViewportChanged(trial), true);
    assert.equal(trial.stages.idle, undefined);
    mapTilesLoaded(trial);
    assert.equal(animationFrames.frames.length, 0);
    mapIdle(trial);
    assert.equal(animationFrames.frames.length, 1);
    animationFrames.frames[0]();
    assert.equal(trial.finished, true);
  } finally {
    animationFrames.restore();
    delete globalThis.window;
  }
});

test('MapPage invalidates readiness on real viewport and clamp adjustments', () => {
  assert.ok(mapPageSource.includes('map.addListener("zoom_changed"'));
  assert.ok(mapPageSource.includes('map.addListener("bounds_changed"'));
  assert.ok(mapPageSource.includes('mapViewportChanged(benchmarkTrial)'));
  assert.ok(mapPageSource.includes('map.setCenter({ lat, lng })'));
  assert.ok(mapPageSource.includes('map.setZoom(minZoom)'));
  assert.ok(mapPageSource.includes('if (!adjustedViewport) mapIdle(benchmarkTrial)'));
});

test('viewport changes before the animation frame prevent stale readiness', () => {
  const trial = readyMapTrial();
  const animationFrames = captureAnimationFrames();
  try {
    mapTilesLoaded(trial);
    mapIdle(trial);
    assert.equal(animationFrames.frames.length, 1);

    mapViewportChanged(trial);
    animationFrames.frames[0]();
    assert.equal(trial.finished, undefined);
    assert.equal(trial.readyScheduled, false);

    mapIdle(trial);
    assert.equal(animationFrames.frames.length, 1, 'idle alone cannot schedule the changed viewport');
    mapTilesLoaded(trial);
    assert.equal(animationFrames.frames.length, 2);
    animationFrames.frames[1]();
    assert.equal(trial.finished, true);
  } finally {
    animationFrames.restore();
    delete globalThis.window;
  }
});

test('map readiness remains incomplete when either tiles or idle is missing', () => {
  const trialWithoutTiles = readyMapTrial();
  const trialWithoutIdle = readyMapTrial();
  const animationFrames = captureAnimationFrames();
  try {
    mapIdle(trialWithoutTiles);
    assert.equal(mapReady(trialWithoutTiles), false);
    mapTilesLoaded(trialWithoutIdle);
    assert.equal(mapReady(trialWithoutIdle), false);
    assert.equal(animationFrames.frames.length, 0);
  } finally {
    animationFrames.restore();
    delete globalThis.window;
  }
});

test('map readiness waits for all pages, full marker count, clustering and fitted tiles/idle', () => {
  globalThis.window = { sessionStorage: storage() };
  window.sessionStorage.setItem('revela:benchmark:enabled', '1');
  const trial = beginBenchmark('map');
  trial.stages = {
    data: { ms: 10, mapRows: 3, geolocatedRows: 2, expectedMarkers: 3, pages: 1 },
    markers: { ms: 11, createdMarkers: 2 },
    clustered: { ms: 12 }, fit: { ms: 0 },
  };
  const animationFrames = captureAnimationFrames();
  mapTilesLoaded(trial);
  mapIdle(trial);
  assert.equal(animationFrames.frames.length, 0, 'marker count mismatch keeps both events insufficient');
  trial.stages.markers.createdMarkers = 3;
  assert.equal(mapReady(trial), true);
  assert.equal(animationFrames.frames.length, 1);
  animationFrames.frames[0]();
  assert.equal(window.sessionStorage.getItem('revela:benchmark:rows').includes('"map_rows":3'), true);
  assert.equal(mapReady(trial), false);
  animationFrames.restore();
  delete globalThis.window;
});
