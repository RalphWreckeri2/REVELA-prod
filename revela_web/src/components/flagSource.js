/**
 * Where a map pin came from, and what to call it on screen.
 *
 * Extracted so the labels and the filter are testable without a DOM,
 * following the existing policy-module convention (see dispatchEligibility.js,
 * registryLadderPolicy.js).
 *
 * The server now stores this on the row (geospatial_logs.source) instead of
 * guessing it from which columns happen to be set. The stored vocabulary:
 *
 *   registry            Official BPLO Registry
 *   registry_detected   Registry + Google Maps
 *   detection           Google Maps only
 *   manual              Inspector Field Report
 *   unknown             Unknown origin
 *
 * A database that has not run the migration still answers, because the
 * readers fall back to inferring the label. That fallback now speaks the same
 * vocabulary, so the frontend never has to carry two.
 */

export const PIN_SOURCES = Object.freeze([
  "registry",
  "registry_detected",
  "detection",
  "manual",
  "unknown",
]);

export const SOURCE_LABELS = Object.freeze({
  registry: "Official BPLO Registry",
  registry_detected: "Registry & Google Maps",
  detection: "Google Maps only",
  manual: "Inspector Field Report",
  unknown: "Unknown origin",
});

/** Shown when the server sent something we do not recognise. */
export const UNKNOWN_SOURCE_LABEL = "Unknown origin";

export function sourceLabel(source) {
  return SOURCE_LABELS[source] ?? UNKNOWN_SOURCE_LABEL;
}

/** An inspector-reported pin is a field report, not a scan or a registry row. */
export function isInspectorReported(source) {
  return source === "manual";
}

/** A pin that exists on Google Maps. */
export function isMapsSourced(source) {
  return source === "registry_detected" || source === "detection";
}

/**
 * The Green-filter source pills.
 *
 * `registry` and `registry_detected` are the two the Map has always offered;
 * they are now matched against the stored values rather than the old guessed
 * labels, which is why the filter values are the vocabulary itself.
 */
export const SOURCE_FILTERS = Object.freeze([
  { value: "all", label: "All Sources" },
  { value: "registry", label: "Registry Only" },
  { value: "registry_detected", label: "Registry + Maps" },
]);

/**
 * Does a flag pass the source filter?
 *
 * A registry-only pin and a pin that is also on Maps are distinct: the first
 * has no placeID, the second does. Matching on the stored source is exact
 * where the old label was a guess.
 *
 * An `unknown` source is never hidden. Until
 * migrations/20261017_01_geospatial_source.sql has run, every existing pin
 * reads 'unknown', so hiding them would make the filter return nothing at all
 * and look broken rather than filtered. The same reasoning covers a value this
 * build does not recognise: it is not evidence of anything.
 */
export function matchesSourceFilter(source, filter) {
  if (!filter || filter === "all") return true;
  if (source === "unknown" || !PIN_SOURCES.includes(source)) return true;
  if (filter === "registry") return source === "registry";
  if (filter === "registry_detected") return source === "registry_detected";
  return true;
}
