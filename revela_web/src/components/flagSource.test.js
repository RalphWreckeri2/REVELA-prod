import test from "node:test";
import assert from "node:assert/strict";

import {
  PIN_SOURCES,
  SOURCE_FILTERS,
  SOURCE_LABELS,
  UNKNOWN_SOURCE_LABEL,
  isInspectorReported,
  isMapsSourced,
  matchesSourceFilter,
  sourceLabel,
} from "./flagSource.js";

test("every stored source has a label", () => {
  for (const source of PIN_SOURCES) {
    assert.equal(typeof SOURCE_LABELS[source], "string", source);
  }
});

test("the labels match what the Map showed before", () => {
  // The old inferred labels, kept so the words on screen do not change.
  assert.equal(sourceLabel("registry"), "Official BPLO Registry");
  assert.equal(sourceLabel("registry_detected"), "Registry & Google Maps");
  assert.equal(sourceLabel("detection"), "Google Maps only");
  assert.equal(sourceLabel("manual"), "Inspector Field Report");
});

test("an unrecognised or absent source falls back to Unknown", () => {
  assert.equal(sourceLabel(undefined), UNKNOWN_SOURCE_LABEL);
  assert.equal(sourceLabel(null), UNKNOWN_SOURCE_LABEL);
  assert.equal(sourceLabel("maps_only"), UNKNOWN_SOURCE_LABEL);
  assert.equal(sourceLabel("inspector_reported"), UNKNOWN_SOURCE_LABEL);
});

test("the old vocabulary is no longer produced", () => {
  // These were guesses; the stored column replaces them. They must not come
  // back as if they meant anything.
  for (const old of ["registry_only", "registry_and_maps", "maps_only",
                     "inspector_reported"]) {
    assert.equal(sourceLabel(old), UNKNOWN_SOURCE_LABEL, old);
  }
});

test("only a field report counts as inspector reported", () => {
  assert.equal(isInspectorReported("manual"), true);
  for (const source of PIN_SOURCES.filter((s) => s !== "manual")) {
    assert.equal(isInspectorReported(source), false, source);
  }
});

test("two sources are Google-Maps sourced", () => {
  assert.equal(isMapsSourced("registry_detected"), true);
  assert.equal(isMapsSourced("detection"), true);
  assert.equal(isMapsSourced("registry"), false);
  assert.equal(isMapsSourced("manual"), false);
});

test("the all filter keeps everything", () => {
  for (const source of PIN_SOURCES) {
    assert.equal(matchesSourceFilter(source, "all"), true, source);
    assert.equal(matchesSourceFilter(source, undefined), true, source);
  }
});

test("the Registry Only pill keeps only registry pins", () => {
  assert.equal(matchesSourceFilter("registry", "registry"), true);
  assert.equal(matchesSourceFilter("registry_detected", "registry"), false);
  assert.equal(matchesSourceFilter("detection", "registry"), false);
  assert.equal(matchesSourceFilter("manual", "registry"), false);
});

test("the Registry + Maps pill keeps only registry_detected pins", () => {
  assert.equal(matchesSourceFilter("registry_detected", "registry_detected"), true);
  assert.equal(matchesSourceFilter("registry", "registry_detected"), false);
  assert.equal(matchesSourceFilter("detection", "registry_detected"), false);
});

test("an unknown source is not hidden by a filter the admin did not ask for", () => {
  assert.equal(matchesSourceFilter("unknown", "registry"), true);
  assert.equal(matchesSourceFilter("unknown", "registry_detected"), true);
});

test("the filter pills carry the stored vocabulary as their values", () => {
  assert.deepEqual(SOURCE_FILTERS.map((f) => f.value),
    ["all", "registry", "registry_detected"]);
  assert.deepEqual(SOURCE_FILTERS.map((f) => f.label),
    ["All Sources", "Registry Only", "Registry + Maps"]);
});

test("registry-only API flag has a recognized origin label and filter", () => {
  const payload = { data: [{ logID: -5, businessID: "5", detectedName: "ACME",
    flagColor: "Orange", flagSource: "registry", blackDispatchUnlocked: 0 }] };
  const source = payload.data[0].flagSource;
  assert.equal(sourceLabel(source), "Official BPLO Registry");
  assert.notEqual(sourceLabel(source), UNKNOWN_SOURCE_LABEL);
  assert.equal(matchesSourceFilter(source, "registry"), true);
  assert.equal(matchesSourceFilter(source, "registry_detected"), false);
});
