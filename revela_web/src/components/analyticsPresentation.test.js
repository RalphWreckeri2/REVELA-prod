import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import {
  activeInspectorWorkload,
  activeFlagRecommendations,
  completeInspectionTimeline,
  groupOperationsStatusBreakdown,
  groupInspectionStatuses,
  INSPECTION_STATUS_STACKS,
  pivotCategoryCounts,
  recommendationAllocationLabel,
  recommendationReason,
  rankedRecommendationRows,
} from "./analyticsPresentation.js";

const analyticsPageSource = readFileSync(
  new URL("../pages/AnalyticsPage.jsx", import.meta.url),
  "utf8",
);
const analyticsPageStyles = readFileSync(
  new URL("../styles/AnalyticsPage.css", import.meta.url),
  "utf8",
);

test("Analytics loading skeletons preserve local content geometry", () => {
  assert.match(analyticsPageSource, /role="status" aria-busy="true" className="analytics-sr-only"/);
  assert.match(analyticsPageSource, /analytics-skeleton-frame--\$\{variant\}/);
  assert.match(analyticsPageSource, /analytics-kpi-value-skeleton/);
  assert.equal((analyticsPageSource.match(/variant="stacked"/g) || []).length, 4);
  assert.equal((analyticsPageSource.match(/getStackedChartLayout\(/g) || []).length, 8);
  assert.match(analyticsPageSource, /const getStackedChartLayout = \(data, statuses\)/);
  assert.doesNotMatch(analyticsPageSource, /chartHeight=\{480\}/);
  assert.match(analyticsPageSource, /variant="operations" rows=\{operationsStatusRows\.length\}/);
  assert.match(analyticsPageSource, /variant="radar"/);
  assert.match(analyticsPageStyles, /\.analytics-skeleton-frame\s*\{[^}]*width:\s*100%/);
  assert.match(analyticsPageStyles, /\.analytics-skeleton-frame--stacked\s*\{/);
  assert.match(analyticsPageStyles, /\.analytics-skeleton-frame--table\s*\{/);
  assert.match(analyticsPageStyles, /\.analytics-skeleton-frame--map\s*\{/);
  assert.match(analyticsPageStyles, /\.analytics-kpi-value-skeleton--compact\s*\{/);
  assert.doesNotMatch(analyticsPageSource, /AnalyticsSkeleton/);
});

test("groups inspection statuses and excludes barangays with no reports", () => {
  const rows = groupInspectionStatuses([
    { barangayName: "A", assigned: 1, reassigned: 2, in_progress: 3, unassigned: 4, submitted: 5, verified: 6 },
    { barangayName: "B", assigned: 0, reassigned: 0, in_progress: 0, unassigned: 0, submitted: 0, verified: 0 },
  ]);
  assert.deepEqual(rows, [{
    barangayName: "A",
    assigned: 1,
    reassigned: 2,
    in_progress: 3,
    unassigned: 4,
    submitted: 5,
    verified: 6,
    pending: 10,
    awaiting_review: 5,
    total: 21,
  }]);
});

test("Operations status totals use the same groups as Section B", () => {
  const sectionB = groupInspectionStatuses([{
    barangayName: "All",
    assigned: 1,
    reassigned: 2,
    in_progress: 3,
    unassigned: 4,
    submitted: 5,
    verified: 6,
  }])[0];
  const operations = groupOperationsStatusBreakdown([
    { status: "Assigned", count: 1 },
    { status: "Reassigned", count: 2 },
    { status: "In Progress", count: 3 },
    { status: "Unassigned", count: 4 },
    { status: "Submitted", count: 5 },
    { status: "Verified", count: 6 },
  ]);
  assert.deepEqual(operations, {
    pending: sectionB.pending,
    awaiting_review: sectionB.awaiting_review,
    verified: sectionB.verified,
    total: sectionB.total,
  });
  assert.deepEqual(INSPECTION_STATUS_STACKS, [
    { key: "pending", label: "Pending", color: "#f97316" },
    { key: "awaiting_review", label: "Waiting for review", color: "#3b82f6" },
    { key: "verified", label: "Verified", color: "#10b981" },
  ]);
});

test("active inspectors remain visible with zero workload", () => {
  const result = activeInspectorWorkload([
    { userID: 2, fullName: "Bea", avg_resolution_time: 0 },
    { userID: 1, fullName: "Ana", avg_resolution_time: 1440 },
  ], [
    { userID: "1", pending: 1, awaiting_review: 2, verified: 3 },
  ]);
  assert.deepEqual(result.map(row => ({
    userID: row.userID,
    fullName: row.fullName,
    pending: row.pending,
    awaiting_review: row.awaiting_review,
    verified: row.verified,
  })), [
    { userID: 1, fullName: "Ana", pending: 1, awaiting_review: 2, verified: 3 },
    { userID: 2, fullName: "Bea", pending: 0, awaiting_review: 0, verified: 0 },
  ]);
});

test("ranked recommendation rows preserve table order and attach matching dispatch data", () => {
  const rows = rankedRecommendationRows([
    { barangayID: 2, rank: 1, barangayName: "A" },
    { barangayID: 1, rank: 2, barangayName: "B" },
  ], [
    { barangayID: "1", inspectors: 1 },
  ]);
  assert.deepEqual(rows.map(({ rank, barangayName, dispatch }) => ({
    rank,
    barangayName,
    inspectors: dispatch?.inspectors ?? null,
  })), [
    { rank: 1, barangayName: "A", inspectors: null },
    { rank: 2, barangayName: "B", inspectors: 1 },
  ]);
});

test("active recommendation list excludes no-flag barangays and counts them", () => {
  const result = activeFlagRecommendations([
    { barangayName: "A", flagged_count: 2 },
    { barangayName: "B", flagged_count: 0 },
    { barangayName: "C", flagged_count: 1 },
  ]);
  assert.deepEqual(result, {
    rows: [
      { barangayName: "A", flagged_count: 2 },
      { barangayName: "C", flagged_count: 1 },
    ],
    noActiveFlagsCount: 1,
  });
});

test("recommendation wording uses requested reason and allocation phrases", () => {
  assert.equal(recommendationReason({
    red_count: 42, unregistered_candidate_count: 42, yellow_count: 0, distance_km: 0.9,
  }), "Red 42 (42 not in registry) · Yellow 0 · 0.9 km from BPLO");
  assert.equal(recommendationAllocationLabel({ allocation_status: "ready", inspectors: 1 }), "1 inspector allocated");
  assert.equal(recommendationAllocationLabel({ allocation_status: "ready", inspectors: 2 }), "2 inspectors allocated");
  assert.equal(recommendationAllocationLabel({ allocation_status: "deferred", inspectors: 0 }), "Waiting for a free inspector");
  assert.equal(recommendationAllocationLabel(null), "Not scheduled yet");
});

test("recommendation columns align with priority and dispatch values", () => {
  assert.match(
    analyticsPageStyles,
    /\.analytics-recommendation-columns > span:nth-child\(3\),\s*\.analytics-recommendation-dispatch-label\s*\{[^}]*justify-self:\s*end;[^}]*text-align:\s*right;/,
  );
  assert.match(
    analyticsPageStyles,
    /\.analytics-recommendation-priority\s*\{[^}]*justify-self:\s*end;/,
  );
  assert.match(
    analyticsPageStyles,
    /\.analytics-recommendation-assignment\s*\{[^}]*justify-self:\s*end;/,
  );
});

test("expanded recommendations show executive metrics without raw score weights", () => {
  const recommendationDisclosure = analyticsPageSource.slice(
    analyticsPageSource.indexOf('className="analytics-recommendation-detail"'),
    analyticsPageSource.indexOf('className="analytics-recommendation-toggle"'),
  );
  assert.match(recommendationDisclosure, /Priority level/);
  assert.match(recommendationDisclosure, /Unregistered flags/);
  assert.match(recommendationDisclosure, /Distance from BPLO/);
  assert.match(recommendationDisclosure, /Action steps/);
  assert.match(recommendationDisclosure, /dispatch\.actionSteps/);
  assert.doesNotMatch(recommendationDisclosure, /scoreBreakdown|weight \{score\?\.weight/);
  assert.match(analyticsPageStyles, /\.analytics-recommendation-executive-metrics\s*\{/);
});

test("pivots grouped counts by barangay", () => {
  assert.deepEqual(pivotCategoryCounts([
    { barangayName: "A", size_label: "Micro", count: 2 },
    { barangayName: "A", size_label: "Small", count: 3 },
    { barangayName: "B", size_label: "Micro", count: 4 },
  ], "size_label"), [
    { barangayName: "A", Micro: 2, Small: 3 },
    { barangayName: "B", Micro: 4 },
  ]);
});

test("fills missing daily dates and switches to weekly totals above 31 days", () => {
  const daily = completeInspectionTimeline([
    { date: "2026-01-01", submitted: 1, verified: 0 },
    { date: "2026-01-03", submitted: 0, verified: 2 },
  ]);
  assert.equal(daily.interval, "day");
  assert.deepEqual(daily.rows[1], { date: "2026-01-02", submitted: 0, verified: 0 });

  const weekly = completeInspectionTimeline([
    { date: "2026-01-01", submitted: 1, verified: 0 },
    { date: "2026-02-05", submitted: 0, verified: 2 },
  ]);
  assert.equal(weekly.interval, "week");
  assert.equal(weekly.rows[0].submitted, 1);
  assert.equal(weekly.rows.at(-1).verified, 2);
  assert.ok(weekly.rows.some(row => row.submitted === 0 && row.verified === 0));
});

test("fills an explicitly selected date range even when there are no reports", () => {
  const result = completeInspectionTimeline([], "2026-03-01", "2026-03-03");
  assert.equal(result.interval, "day");
  assert.deepEqual(result.rows, [
    { date: "2026-03-01", submitted: 0, verified: 0 },
    { date: "2026-03-02", submitted: 0, verified: 0 },
    { date: "2026-03-03", submitted: 0, verified: 0 },
  ]);
});
