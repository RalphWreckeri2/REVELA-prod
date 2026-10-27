// Manual, opt-in measurements. Only numeric timings/aggregate counts are retained;
// never store tokens, candidate names, report details, or response bodies.
const ENABLED = "revela:benchmark:enabled";
const CONFIG = "revela:benchmark:config";
const ROWS = "revela:benchmark:rows";
const HEADERS = [
  "scenario", "trial", "outcome", "elapsed_ms", "accepted_ms", "visible_ms",
  "data_ms", "markers_ms", "clustered_ms", "fit_ms", "tiles_ms", "idle_ms", "ready_ms", "request_id",
  "http_status", "registry_rows", "map_rows", "geolocated_rows", "expected_markers",
  "created_markers", "flags_pages", "cache", "network", "workload", "notes",
];

const enabled = () => typeof window !== "undefined" && window.sessionStorage.getItem(ENABLED) === "1";
const config = () => {
  try { return JSON.parse(window.sessionStorage.getItem(CONFIG) || "{}"); }
  catch { return {}; }
};
const rows = () => {
  try { return JSON.parse(window.sessionStorage.getItem(ROWS) || "[]"); }
  catch { return []; }
};
const quote = value => `"${String(value ?? "").replaceAll('"', '""')}"`;

export function beginBenchmark(scenario, workload = {}, startedAt = performance.now()) {
  if (!enabled()) return null;
  return { scenario, startedAt, workload, stages: {}, ...config() };
}

export function benchmarkStage(trial, name, details = {}) {
  if (!trial || trial.finished || trial.stages[name]) return;
  trial.stages[name] = { ms: performance.now() - trial.startedAt, ...details };
}

export function finishBenchmark(trial, outcome, details = {}) {
  if (!trial || trial.finished) return null;
  trial.finished = true;
  const { stages } = trial;
  const entry = {
    scenario: trial.scenario, trial: rows().length + 1, outcome,
    elapsed_ms: +(performance.now() - trial.startedAt).toFixed(2),
    data_ms: stages.data?.ms, markers_ms: stages.markers?.ms,
    clustered_ms: stages.clustered?.ms, fit_ms: stages.fit?.ms,
    tiles_ms: stages.tiles?.ms, idle_ms: stages.idle?.ms, ready_ms: stages.ready?.ms,
    cache: trial.cache, network: trial.network,
    registry_rows: trial.registry_rows, map_rows: trial.map_rows,
    geolocated_rows: trial.geolocated_rows,
    expected_markers: trial.expected_markers,
    workload: JSON.stringify(trial.workload),
    ...details,
  };
  const next = [...rows(), entry];
  window.sessionStorage.setItem(ROWS, JSON.stringify(next));
  console.info("[responsiveness-benchmark]", entry);
  return entry;
}

let mapTrial;
export function markMapNavigation() {
  if (enabled()) mapTrial = beginBenchmark("map", { navigation: "spa" });
}
export function startMapBenchmark() {
  if (!enabled()) return null;
  if (!mapTrial || mapTrial.finished) {
    const navigation = performance.getEntriesByType("navigation")[0];
    mapTrial = beginBenchmark("map", { navigation: "document" }, navigation?.startTime ?? performance.now());
  }
  return mapTrial;
}
export function endMapBenchmark() { mapTrial = null; }

// Tiles must have loaded after the municipal fit; idle must follow those tiles.
// Marker creation and clustering must refer to the complete paginated dataset.
export function mapReady(trial, painted = () => requestAnimationFrame(() => {
  benchmarkStage(trial, "ready");
  finishBenchmark(trial, "completed", {
    request_id: trial.requestId, http_status: trial.httpStatus,
    registry_rows: trial.registryRows, map_rows: trial.stages.data?.mapRows,
    geolocated_rows: trial.stages.data?.geolocatedRows,
    expected_markers: trial.stages.data?.expectedMarkers,
    created_markers: trial.stages.markers?.createdMarkers,
    flags_pages: trial.stages.data?.pages,
  });
})) {
  if (!trial || trial.finished || trial.readyScheduled) return false;
  const { data, markers, clustered, fit, tiles, idle } = trial.stages;
  if (!data || !markers || !clustered || !fit || !tiles || !idle) return false;
  if (markers.createdMarkers !== data.expectedMarkers || clustered.ms < markers.ms ||
      tiles.ms < fit.ms || idle.ms < tiles.ms) return false;
  trial.readyScheduled = true;
  painted();
  return true;
}

export function installBenchmarkControls(matchingDryRunRequest) {
  if (typeof window === "undefined") return;
  window.revelaBenchmark = {
    enable: (settings = {}) => {
      window.sessionStorage.setItem(ENABLED, "1");
      window.sessionStorage.setItem(CONFIG, JSON.stringify(settings));
    },
    disable: () => window.sessionStorage.removeItem(ENABLED),
    configure: settings => window.sessionStorage.setItem(CONFIG, JSON.stringify(settings)),
    rows,
    clear: () => window.sessionStorage.removeItem(ROWS),
    exportCSV: () => {
      const csv = [HEADERS.join(","), ...rows().map(row => HEADERS.map(key => quote(row[key])).join(","))].join("\r\n") + "\r\n";
      const url = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
      const link = document.createElement("a");
      link.href = url;
      link.download = "revela-responsiveness-web.csv";
      link.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    },
    // Explicit manual call only. Dry-run does not run Google discovery or write flags.
    dryRun: async candidates => {
      if (!enabled()) throw new Error("Enable benchmarking first.");
      const trial = beginBenchmark("matching-only", { candidates: candidates.length,
        matcher: "unindexed-dry-run", fixture: config().fixture });
      let requestId, httpStatus;
      try {
        const result = await matchingDryRunRequest(candidates, window.localStorage.getItem("revela_token"), {
          onResponse: response => { requestId = response.headers.get("X-Request-ID"); httpStatus = response.status; },
        });
        finishBenchmark(trial, result.results?.some(row => row.error) ? "incomplete" : "completed", {
          request_id: requestId, http_status: httpStatus, registry_rows: result.registry_size,
          notes: `evaluated=${result.candidates_evaluated};google_requests=${result.google_requests_made}`,
        });
        return result;
      } catch (error) {
        finishBenchmark(trial, "failed", { request_id: requestId, http_status: httpStatus ?? error.status, notes: error.message });
        throw error;
      }
    },
  };
}
