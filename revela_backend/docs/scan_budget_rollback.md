# API usage and scan-budget rollback — 2026-10-20

## Verified boundary

The source is commit `9ae7de0` (`Fix analytics loading and scan budgets`),
compared against its parent `0e79712` (`sql query optimized`) and
`analytics_and_scan_budget_review.md`. This is a selective source rollback.

These application files now exactly match `0e79712`:

- `api/flags/routes.py`
- `api/flags/service.py`
- `api/utils/quota_settings.py`
- `api/utils/usage_report.py`
- `../revela_web/src/components/ApiUsageSettingsPanel.jsx`

`../revela_web/src/pages/MapPage.jsx` reverses only the scan-budget commit's
hunks; the later Re-verify daily-limit guard remains.
`../revela_web/src/services/api.js` removes only `getDetectionPreflightRequest`.

## Reverted behavior

- Removed browser and server scan-budget preflight/admission, its GET route,
  the request estimator, and the preflight-derived per-execution request budget.
  Quick Discovery can again start a bounded partial slice even when its request
  cap cannot fund the whole sampling scope.
- Restored the previous API Usage & Limits panel, usage-report field contract,
  configured-slice presentation, disabled-method reporting rule, quota field help,
  and monthly-scan funding-validation logic.
- Restored Map confirmation/results, request/point counters, error messages,
  and detection-route responses. The previous `attempted_points` includes
  previously checkpointed/skipped cells; summaries again use the import-time
  work-limit constants. This deliberately restores the old reporting behavior.
- Removed persistent scan-plan creation/adoption/completion and cycle-ID-based
  resume. Restored configuration-fingerprinted checkpoints, the completed-run
  watermark, Quick rotation, and the previous Test Mode fingerprint inputs.
- Removed persisted saturated-cell gap checkpoints and the associated accounting.
  Saturated/incomplete cells follow the previous retry/terminal-gap behavior.
- Restored the earlier Legacy pagination, New Nearby disabled-budget/fixture
  safeguards, bounded retry behavior, and quota-error handling.
- Removed `api/flags/scan_budget.py`, the optional budget-raising command
  `scripts/configure_quick_discovery_budget.py`, and the repository migration
  `migrations/20261019_01_detection_scan_plans.sql`. No down migration was run.
- Updated the affected scan/usage test harnesses to the restored contract and
  replaced the removed preflight tests with actual runner regressions.

The existing execution request/time caps, stricter Test Mode request cap,
atomic per-method daily/monthly reservations, fail-closed ledger behavior,
request pacing, bounded adaptive refinement, completed-monthly-scan allowance,
scan lock, registry prerequisite, and cancellation/checkpoint safeguards remain.

**This restores previous behavior; it does not fix the original five-request
scan limitation.** A real five-request execution cap still stops paid requests
at five. Removing admission does not increase that cap or guarantee completion.

## Preserved work

- Progressive analytics sections, shared computation/cache and startup warmup,
  invalidation, stale-data/expiry handling, skeletons, cancellation, request
  deadlines, retry/backoff, reconnect recovery, and metadata loading.
- `app.py`'s analytics invalidation hook and the shared API helper's HTTP status,
  AbortSignal, and analytics-section support.
- Later registry, mobile-login/device-hint, modal, compliance, and Re-verify work.
- All pre-existing uncommitted analytics, Overview/KPI, styling, browser-fixture,
  and package-script work. These files were not edited by this rollback.
- Independent corrections to stale quota test fixtures from the original commit.

## Configuration and database evidence

A direct connection using the local backend configuration was inspected in a
**read-only transaction** without starting the Flask application, invoking schema
guards, executing migration SQL, or running the repair command.

Observed locally:

| Evidence | Result |
|---|---|
| Configured database target | Local MySQL |
| Scan/Nearby/Test Mode environment overrides | None present |
| Saved `run_detection.*`, `quota.*`, `test_mode.*` overrides | No rows |
| `detection_scan_plans` table | Exists, zero rows |
| `scan_point_log` table | Exists, zero rows |

The new schema therefore exists locally, but its presence cannot distinguish
manual migration from the removed runtime `CREATE TABLE IF NOT EXISTS` guard.
There is no current local override evidencing an applied budget repair. The
original review states that its repair tests used isolated settings and did not
apply to a deployment database. Neither fact proves what happened on a host not
accessible from this checkout. The checked-in October 15 SQL dump has settings
schema but no saved quota values to establish a deployed before-value.

The table, usage ledger, detection-run history, saved settings, and checkpoint
records were left in place. No settings were written, counters reset, or database
tables/records deleted during the rollback.

The following are verified **pre-change code defaults**, not claimed historical
deployment values. `quota_config.py`, `quota_ceilings.py`, `test_mode.py`,
`app_settings.py`, and `detection_runs.py` were not changed by `9ae7de0` and
have not been changed by this rollback:

| Setting | Pre-change default |
|---|---|
| Nearby method | `legacy` |
| `run_detection.max_requests` / `RUN_DETECTION_MAX_REQUESTS` | 120 |
| `run_detection.max_seconds` / `RUN_DETECTION_MAX_SECONDS` | 90 seconds |
| Legacy Nearby request allowance | 120/day; 2,000/month |
| Completed monthly scan allowance | 10 |
| New Nearby request allowance | 0/day; 0/month (disabled) |
| Test Mode enabled / max requests / max centers | false / 20 / 6 |

The reported five-request/five-scan dialog does not verify the underlying
environment/admin/Test Mode values. The removed script's proposed 24 or 39
requests are recommendations, not previous values. No deployed configuration
restoration target can be verified from the available evidence.

## Deployment follow-up

The source rollback has not been deployed. Deploy frontend and backend together.
No local settings restoration or database down migration is needed.

On the actual host, inspect the effective environment and persisted settings
read-only. `revela_app_settings` stores current values/timestamps, not a full
before/after audit. If the removed repair command ran, it could only raise
`run_detection.max_requests`; restore that setting only from a verified prior
configuration snapshot/audit. Do not infer a previous value from 5, 24, 39, or
the code default 120, and do not clear all overrides.

Also check whether `detection_scan_plans` exists there and contains running plans.
The exact-baseline runner uses configuration fingerprints, not the newer random
cycle IDs. If production has such saved progress, retain all plan/checkpoint
rows and arrange a verified, additive compatibility conversion before switching
that database to this runner; otherwise those cycle checkpoints would not be
reused. The local database has no such progress to convert. Production plan
presence and any required conversion remain unverified; no conversion or table
drop is assumed or performed here.

## Focused checks

- Backend scan/grid, safeguards, rate-limit continuation, offline integration,
  quota ledger/configuration, admin usage, map compliance, analytics sections:
  **241 passed, 76 subtests passed**.
- Preserved analytics stale-cache behavior: **23 passed, 3 subtests passed**.
- Regression: five-request Quick slice with four saved checkpoints starts,
  pauses after five paid calls, reports the previous nine-point counter, and
  resumes without re-requesting completed cells. Daily/monthly reservations and
  the completed-monthly-scan limit still reject requests at their limits.
- Frontend ESLint and context invariants passed; **198 Node tests passed**
  across the available verification targets, including 15 API-usage and 25
  analytics/cache tests. Vite production build passed.
- Synthetic/offline analytics browser smoke: **26 checks passed**, including
  skeletons, progressive loading, retained data, bounded retries, reconnect,
  and stale-filter response rejection.
- `npm run verify` reaches a pre-existing missing
  `src/components/mapMarkerPosition.test.js` target and stops there. That file
  is absent from `HEAD`; the remaining available targets and build were run
  separately. The package scripts were preserved.
