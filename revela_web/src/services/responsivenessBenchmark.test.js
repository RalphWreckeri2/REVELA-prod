import test from 'node:test';
import assert from 'node:assert/strict';
import {
  beginBenchmark, benchmarkStage, finishBenchmark, installBenchmarkControls,
  mapReady,
} from './responsivenessBenchmark.js';

function storage() {
  const values = new Map();
  return {
    getItem: key => values.get(key) ?? null,
    setItem: (key, value) => values.set(key, value),
    removeItem: key => values.delete(key),
  };
}

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

test('map readiness waits for all pages, full marker count, clustering and fitted tiles/idle', () => {
  globalThis.window = { sessionStorage: storage() };
  window.sessionStorage.setItem('revela:benchmark:enabled', '1');
  const trial = beginBenchmark('map');
  trial.stages = {
    data: { ms: 10, mapRows: 841, geolocatedRows: 479, expectedMarkers: 841, pages: 1 },
    markers: { ms: 11, createdMarkers: 840 },
    clustered: { ms: 12 }, fit: { ms: 5 }, tiles: { ms: 13 }, idle: { ms: 14 },
  };
  assert.equal(mapReady(trial, () => assert.fail('not complete')), false);
  trial.stages.markers.createdMarkers = 841;
  assert.equal(mapReady(trial, () => {
    benchmarkStage(trial, 'ready');
    finishBenchmark(trial, 'completed', { map_rows: 841, geolocated_rows: 479, expected_markers: 841 });
  }), true);
  assert.equal(window.sessionStorage.getItem('revela:benchmark:rows').includes('"map_rows":841'), true);
  assert.equal(mapReady(trial), false);
  delete globalThis.window;
});
