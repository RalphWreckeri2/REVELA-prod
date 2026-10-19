# Analytics loading and scan budget review

## Findings and scope of evidence

Repository code, the local non-secret quota configuration, synthetic HTTP responses,
and isolated database substitutes were inspected. The local `.env` sets none of the
scan/nearby budget variables; the effective defaults are Legacy Nearby, 120 requests
per execution, 90 seconds of grid work, 120 requests/day, 2,000/month, and 10 completed
scans/month. The reported dialog's **5 requests / 5 monthly scans** is different from
these defaults. Deployed environment variables, persisted admin overrides, Test Mode
configuration, historical per-run logs, live Cloud quota utilization, and an approved
monetary budget were not available. No live Google requests or Cloud/billing changes
were made.

No screenshot images were attached to this session. Skeletons follow the actual
Analytics page's eight-card KPI grid, chart cards, bar plots, and donut charts.

## Analytics: traced flow and confirmed causes

Before the changes:

1. The protected route hydrates the session, downloads the Analytics/Recharts chunks,
   and mounts `AnalyticsPage`. Session hydration also has an existing 1-second minimum.
2. The page requests WLC settings, filter metadata, barangays, and `/analytics/all`.
3. JWT/session checks and the process-local analytics cache run on the backend.
4. On a miss, **all tiers run serially**: descriptive SQL, diagnostic SQL/DBSCAN/spatial
   work, WLC rankings/dispatch, operations, scan history, and JSON serialization.
5. The page waits for this entire response before showing any usable section. The
   full endpoint additionally reads the requesting user's rollover notification.

Confirmed problems and fixes:

- **Head-of-line blocking:** cards waited for unrelated later tiers. Section reads
  (`/analytics/all?section=descriptive`, etc.) now receive a 202 while preparation is
  pending and a finished tier as soon as it is published. All sections, startup warmup,
  and full-response callers share the **same per-filter computation**, not four sets
  of SQL queries. This reduces time to usable data without claiming to reduce the
  runtime of every underlying query.
- **Missing cache invalidation:** the invalidation helper had no callers. Successful
  data mutations, WLC changes, and quota-paused writes now invalidate once per HTTP
  operation. Read-only searches and rejected writes do not. An invalidated in-flight
  computation cannot republish stale results.
- **Unbounded/hard-to-recover frontend requests:** the page lacked a fetch deadline,
  explicit reconnect recovery, and meaningful errors for silent refresh failures.
  A coordinator now owns each filter/token scope, with a 20-second attempt timeout,
  two retry attempts with backoff, deduplication of simultaneous triggers, bounded
  preparation polling, and abort plus generation checks on filter changes.
- **Loading was all-or-nothing:** each tier now has loading, ready/empty, updating,
  offline, expired, and error behavior. Existing data stays visible during refresh
  within the existing 15-minute display-age ceiling. Expired 503 responses with an
  active replacement are polled rather than mistaken for a terminal failure.
- **Filter requests failed together and did not reconnect:** metadata and barangays
  now settle independently, use cancellation/timeouts, deduplicate active loads,
  recover on reconnect, and expose a retry action.
- **Unnecessary WLC re-fetching:** changing analytics filters no longer fetches WLC
  configuration again.
- **Timestamp precision:** a newly cached float timestamp could round forward by a
  fraction of a microsecond, spuriously classifying an immediate read as expired.
  Only sub-millisecond rounding error is tolerated. Real future/invalid timestamps
  and the 15-minute ceiling remain rejected. Publishing later tiers never resets an
  earlier tier's computation timestamp.

### Database, caching, and hosting assessment

The repository already warms the default snapshot asynchronously at process startup,
single-flights cache misses, and uses a 60-second cache TTL. A redeploy loses this
process-local cache; the previous full-response dependency made that cold path visible.
The Docker command is one Gunicorn gthread worker with 16 threads. Its `--timeout 120`
is a worker-liveness threshold, **not** a per-request deadline for gthread work.
Vercel serves the client; API requests go directly to the configured backend origin.

The ranking SQL contains a geospatial-by-registry join fan-out. A previously gated
split-query candidate exists, but this session has no production MySQL plan/runtime
evidence to justify enabling it or adding indexes. Hosting sleep/startup duration and
production SQL latency cannot be quantified from this checkout. The new
`[analytics-section] ... ready_ms=...` messages complement existing request/cache logs.
Temporarily setting `REVELA_ANALYTICS_PHASES=1` provides named SQL timings for the
remaining deployment investigation. The change fixes confirmed fetch/cache/critical-
path problems; skeletons are not the performance fix by themselves.

## Scan call graph and calculations

Quick Discovery samples **up to 24 centers**, with no adaptive refinement. The reported
scope is 24. Legacy intentionally stops after the first result page for this mode;
finishing Quick Discovery does not mean enumerating every POI within each circle.

Full Coverage uses **38 centers** with the shipped effective 0.009-degree grid and
850-meter radius over the checked-in municipal geometry. Other supported spacing,
Test Mode, or radius settings change the center count; the preflight computes the
actual plan instead of hard-coding 38.

For either mode, reconciliation, registry matching, barangay lookup, and flag checks
are local SQL/geometry work. They make **zero additional Text Search, Place Details,
or Geocoding calls**. The scan's only Google HTTP funnels are `_places_get` and
`_new_nearby_request`.

| Mode / endpoint | Normal/base requests | Bounded maximum per traversal | Basis |
|---|---:|---:|---|
| Quick / Legacy | 24 | 24 | 24 centers × 1 first page; no automatic Legacy HTTP retries |
| Quick / New | 24 | 96 | 24 × (1 initial + at most 3 per-minute-429 retries) |
| Full / Legacy | 38 | 1,482 | 38 × (1 root + 12 adaptive child queries) × at most 3 pages |
| Full / New | 38 | 1,976 | 38 × 13 queries × 1 page × at most 4 attempts |

The adaptive child budget is **12 children plus the root**, not 12 total queries.
New Nearby has no pagination. Legacy pagination is now explicitly bounded to three
pages. Every real attempt, including a failed/throttled attempt, reserves and consumes
a persistent daily and monthly request slot before being sent. Fixture replays do not.
Network failures stop a partial traversal; resuming an unfinished cell can add failed
attempts/repeated incomplete work beyond a successful traversal's bound. Arbitrarily
many interrupted resumes are not a fundable single-run guarantee.

### Explicit answers

1. **One complete Quick Discovery:** 24 successful Legacy requests for the reported
   24-center scope; New normally uses 24 and needs up to 96 with its bounded RPM
   retries. Smaller actual scopes use N / 4N. Failed partial scans still spend requests.
2. **Minimum remaining daily allowance:** 24 Legacy, or 96 New for retry-inclusive
   admission, plus the same remaining monthly request allowance. The corresponding
   execution cap must also fit. Keep the existing Legacy daily cap at 120: it funds
   one Quick scan and leaves at most **96 same-method requests** for other work. For
   an expected other-use volume E, the required configured limit is `24 + E`; the
   checkout supplies no traffic forecast to justify E > 96 or raising 120. Other API
   methods have independent budgets and cannot subsidize Nearby. Actual Google
   remaining allowance is also necessary, but external project consumption is unknown.
3. **What prevents completion:** a genuinely enforced 5-request cap cannot fund 24
   remaining Legacy centers (or 96 New attempts). Check `run_detection.max_requests`,
   `RUN_DETECTION_MAX_REQUESTS`, and an enabled `test_mode.max_requests`. Daily/monthly
   request headroom, method selection/disabled New budgets, and the work clock can
   independently stop execution. Five monthly scans remaining is not the blocker.
   The old dialog printed startup constants instead of effective limits, so its
   displayed 5 alone does not prove which configuration source enforced the stop.
4. **Additional Full Coverage allowance:** compared with Quick's 24 Legacy requests,
   Full needs **14 more in the no-refinement case** and **1,458 more at its bounded
   maximum**. A single worst-case Legacy cell needs 39 requests: an execution cap of
   24 needs **15 additional slots** to fit it. The optional repair sets that cap to
   39. The existing daily budget is still only 120; it does not guarantee all 1,482
   in a day, and the recorded Legacy Cloud ceiling is itself only 1,000/day. Spread
   work across resumable executions/days. With no other consumption or interruptions,
   the 2,000 monthly request cap can fit one 1,482-request traversal plus five Quick
   scans (120), leaving 398 requests. The active remaining ledger must actually have
   that headroom. For New, Full needs **14 more base requests**, or **1,880 more than
   retry-inclusive Quick's 96** at its 1,976 maximum. New is currently disabled; no
   approval or live monetary budget was available to enable/fund it. Terminal result
   saturation is explicitly `completed_with_gaps`, not proof of exhaustive coverage.
5. **Why 9 points versus 5 requests:** the old `attempted_points` added previously
   checkpointed/skipped cells to this attempt's cells. **4 saved + 5 newly requested
   = 9** is reproduced in a mock test. Fixture replays are another way points can
   exceed paid requests. The displayed cap could also be a stale startup constant.
   The exact historical split requires the deployed run summary/logs and Test Mode
   settings; it cannot be reconstructed from the dialog alone. The new response/UI
   separates prior saved centers, centers attempted this execution, processed centers,
   paid requests, fixture replays, and effective request limits/source.

## Configuration table

Locations below are relative to `revela_backend/`. Persisted quota keys live in
`revela_app_settings`; they override environment defaults and are cached for 5 seconds.
Cloud figures below are the repository's recorded figures, not a live Cloud audit.

| Setting/environment variable | Location | Current value | Recommended value | Calculation/basis |
|---|---|---|---|---|
| `RUN_DETECTION_NEARBY_API` | `api/utils/quota_config.py`, `api/flags/service.py` | `legacy` locally/default; deployment unknown | Keep `legacy` | New is a distinct SKU with disabled app budgets |
| `RUN_DETECTION_MAX_REQUESTS` / `run_detection.max_requests` | `quota_config.py`, `quota_settings.py`, persisted override | Default 120; reported dialog 5; effective deployed source unknown | Minimum **24** for Legacy Quick; **39** to also fit one bounded Full cell; retain 120 if already configured | 24 × 1; Full cell (1 + 12) × 3 = 39; repair only raises a smaller execution cap within existing budgets |
| `test_mode.enabled`, `test_mode.max_requests`, `test_mode.max_grid_points` | `api/utils/test_mode.py`, persisted settings | Defaults `false`, 20, 6; deployed unknown | Keep production Test Mode disabled; explicitly review any enabled test scope/cap | Effective execution cap is the smaller app/Test Mode value; test-scope fixtures can be free |
| `LEGACY_NEARBY_DAILY_CAP` (`PLACES_DAILY_CAP`) / `quota.legacy_nearby.daily` | `quota_config.py`, `quota_settings.py` | **120/day** default/local; deployed remaining unknown | **120/day** | 24 Quick + up to 96 other same-method requests; no daily budget increase |
| `LEGACY_NEARBY_MONTHLY_CAP` (`PLACES_MONTHLY_CAP`) / `quota.legacy_nearby.monthly` | same | **2,000/month** default/local | **2,000/month** | One bounded Full traversal + five Legacy Quicks = 1,602; remaining consumption still authoritative |
| `RUN_DETECTION_MAX_SECONDS` / `run_detection.max_seconds` | `quota_config.py`, `service.py` | **90 seconds** grid work | **90**, pending hosting/runtime evidence | Legacy Quick's pacing-only floor is 23 × 1.25 = 28.75 seconds; HTTP and processing add time. No unverified hosting deadline increase |
| `RUN_DETECTION_MONTHLY_SCAN_LIMIT` / `run_detection.monthly_scan_limit` | `quota_config.py`, `api/models/detection_runs.py`, persisted override | Reported **5**; default/local **10** | Keep deployed **5** if that is the saved setting | Five Legacy Quicks use 120 monthly requests. Partial runs consume API requests, not completed-scan slots |
| `run_detection.grid_step_degrees`; radius / Quick center cap | `quota_settings.py`, `service.py` | **0.009**, **850 m**, **24** | Retain | Actual Full grid = 38; preflight recomputes effective scope |
| `NEARBY_NEW_DAILY_CAP` / `NEARBY_NEW_MONTHLY_CAP` (legacy aliases `NEW_NEARBY_*`) | `quota_config.py`, `quota_settings.py` | **0 / 0**, disabled; daily application maximum 200 | Retain disabled until a method-specific budget is established | Quick needs 96 retry-inclusive requests; New Full maximum 1,976; quota alone is not monetary approval |
| Legacy Places Google quota | `api/utils/quota_ceilings.py`, read-only report | Recorded **1,000/day, 60/min** | Retain | App remains below it; shared process pacer is 48/min (1.25 s) |
| New Nearby Google quota | same | Recorded **75,000/day, 600/min** | Retain | Does not enable the app method or establish billing allowance |
| Text Search / Details / Geocoding Google quotas | same | Recorded **500 / 125,000 / 1,500 per day**, **600 / 600 / 3,000 per minute** | Retain | Scan makes zero calls to these methods |
| Text Search / Details / Geocoding app budgets | `quota_config.py`, `quota_settings.py` | Daily **80 / 90 / 1,500**; monthly **2,500 / 3,000 / 8,000** | Retain | Separate method ledgers; Text Search workflows share its own daily budget |
| Analytics cache / display age | `api/analytics/routes.py`, frontend cache policy | **60 s / 15 min** | Retain | Invalidation and progressive publication fix the confirmed problems; earlier data cannot be re-dated by later work |
| Analytics request timeout / retries / preparation bound | `revela_web/src/services/analyticsLoader.js` | Previously no request deadline/reconnect policy | **20 s / 2 retries / 45 preparation polls at 2 s** | Pending work and transport failures are separately bounded; simultaneous triggers join active requests |
| `REVELA_ANALYTICS_PHASES` | `api/analytics/routes.py` | Off unless set | Temporarily **1** during deployment diagnosis | Capture SQL phase timings and compare with section-ready/request logs |

## Resume and enforcement changes

- A persisted `detection_scan_plans` row freezes the selected coordinates and gives
  each mode/configuration an independent cycle. Thread-local Quick rotation and
  another mode's completed scan can no longer replace or erase partial progress.
- Compatible old checkpoints are adopted, including saved Quick centers displaced
  by the previous rotation. Request-budget-only Test Mode changes preserve geographic
  checkpoint identity.
- Complete cells are skipped. A fully bounded saturated cell is saved as a **gap**
  checkpoint and advances the next slice, with final `completed_with_gaps` reporting.
  A time/request-interrupted or API-failed cell stays retryable. A final cell cut off
  during pagination cannot be mistaken for completed coverage or charged as a
  completed monthly scan.
- A fresh preflight is checked before confirmation and checked again by the backend
  before starting. Quick admission funds the entire remaining sampling scope,
  including applicable retries. Full admission shows both its minimum and bounded
  maximum and limits the execution to the remaining method budget. Per-request
  atomic reservations remain the final safeguard.
- Usage reports, preflight, and run summaries expose the effective app/Test Mode
  limits. Funding validation now uses the **selected** Nearby method rather than
  choosing a ledger merely because another method has a positive cap.
- Google HTTP 429 / Legacy `OVER_QUERY_LIMIT` errors carry `google_quota`; internal
  caps carry application-specific codes. Exhausted per-minute New retries are not
  mislabeled as an application daily cap.

## Deployment

1. Deploy backend and frontend together. Apply
   `migrations/20261019_01_detection_scan_plans.sql`; the existing runtime guard also
   creates the table when CREATE permission is available.
2. On the backend host, inspect the **effective** budget first:

   ```sh
   python scripts/configure_quick_discovery_budget.py
   ```

   To repair a too-small Legacy execution cap for Quick within the existing method
   budgets:

   ```sh
   python scripts/configure_quick_discovery_budget.py --apply
   ```

   To also fit one bounded Full cell:

   ```sh
   python scripts/configure_quick_discovery_budget.py --full-slices --apply
   ```

   Expected changes from a verified live cap of 5 are **5 → 24** or **5 → 39**,
   respectively. If the effective cap is already 120, the command changes nothing.
   It refuses an enabled Test Mode or an insufficient existing method budget and
   does not raise daily/monthly API caps, monthly scan allowance, or Cloud/billing
   settings. It was verified with isolated settings, not applied to an unavailable
   deployment database.
3. Read the new API Usage & Limits preflight and confirm actual daily/monthly remaining
   allowance. Compare the backend key's Cloud project and live Cloud remaining quota;
   other consumers of that project are outside REVELA's ledger. New endpoint billing
   and approved monetary headroom remain missing information.
4. Capture cold/warm request and SQL-phase logs on Railway. Confirm its actual edge
   request deadline/sleep policy before increasing the 90-second work slice. Keep the
   existing single-process SSE/cache deployment model unless shared coordination is
   supplied for additional replicas.

## Changed files

Application:
- `app.py`
- `api/analytics/routes.py`
- `api/flags/routes.py`, `api/flags/service.py`, `api/flags/scan_budget.py`
- `api/utils/quota_settings.py`, `api/utils/usage_report.py`
- `migrations/20261019_01_detection_scan_plans.sql`
- `scripts/configure_quick_discovery_budget.py`
- `../revela_web/src/pages/AnalyticsPage.jsx`, `../revela_web/src/pages/MapPage.jsx`
- `../revela_web/src/services/api.js`, `../revela_web/src/services/analyticsLoader.js`
- `../revela_web/src/components/useAnalyticsData.js`, `../revela_web/src/components/ApiUsageSettingsPanel.jsx`
- `../revela_web/src/styles/AnalyticsPage.css`

Verification:
- `tests/test_analytics_sections.py`, `tests/test_scan_budget.py`
- `tests/test_admin_settings.py`, `tests/test_quota_config.py`
- `tests/test_run_detection_grid.py`, `tests/test_run_detection_safeguards.py`
- `tests/test_run_detection_rate_limit_continuation.py`, `tests/test_nearby_new_detection_integration.py`
- `tests/test_map_compliance.py` (existing scan harness now isolates preflight/plan storage)
- `../revela_web/src/services/analyticsLoader.test.js`
- `../revela_web/scripts/analytics-smoke.html`, `../revela_web/scripts/analytics-smoke.jsx`
- `../revela_web/scripts/verify-compliance-browser.mjs` (reuses the isolated browser runner for either fixture)
- `../revela_web/package.json` (analytics test commands added to existing verification)

## Verification results

- Focused backend analytics/scan/quota/map regression selection: **320 passed,
  87 subtests passed**. It includes cache single-flight/invalidation/age behavior,
  progressive availability while later work is blocked, Quick's exact 24 real-call
  reservations, the 39-call saturated-cell bound, saved gaps across slices, zero-paid-
  call preflight rejection, per-method funding, bounded retries, failed-request
  accounting, and resume without duplicate flags.
- `npm run verify`: **passed** — ESLint, context checks, **196 Node tests** (23
  analytics/cache tests), and the Vite production build.
- `npm run test:analytics:browser`: **10 checks passed** using synthetic responses in
  headless Edge. Checks cover initial placeholders, progressive/slow responses,
  StrictMode request deduplication, empty charts, retained refresh data, offline and
  reconnect, failure backoff/manual retry, and late responses after a filter change.
- The complete backend suite has a pre-existing collection error in
  `tests/test_registry_pin_location_consistency.py`: it imports the missing
  `_map_registry_coordinate_sql`. Excluding that file, the final broad run reports
  **1,087 passed, 31 failed, 28 skipped, 567 subtests passed**. The same 31 failures
  were reproduced in the affected test modules with the **pre-change flags service
  loaded from Git in memory**. They include missing older migration fixtures, existing
  registry/enforcement test mismatches, local DB authentication, and SSE auth mocks.
  A stale quota-config assertion was corrected to test the already-recorded verified
  quota behavior; it is included in the passing focused selection.

Verification used mocked Google responses or isolated database fixtures. The repair
command was tested without modifying deployed settings, and production SQL/hosting
timings remain a deployment measurement rather than an invented benchmark.
