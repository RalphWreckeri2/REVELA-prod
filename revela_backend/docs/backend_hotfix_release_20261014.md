# Backend hotfix release — 2026-10-14

## Prepared state

- Branch: `release/backend-hotfix-20261014`.
- Base: `origin/main`, `1182cbf461f1c04baf1f72a2a884228d700a9d5b`.
- Worktree: `C:\Users\Mateo\AppData\Local\Temp\opencode\revela-backend-release-20261014`.
- Changes are uncommitted. No publication, SQL, reset, external request, service
  startup, Railway configuration change, or deployment was performed.
- The original `C:\REVELA-prod` WIP and Flutter fixes remain separate.

## Exact release manifest

All paths below are relative to `revela_backend/`.

### Runtime

| File | Selective change |
| --- | --- |
| `api/auth/routes.py` | Authenticated, mobile-only foreground heartbeat. |
| `api/flags/routes.py` | Yellow input/owner/UUID contract and 400/409 handling; authenticated address-search/reverse-geocoding routes. |
| `api/flags/service.py` | Strict selected-barangay validation; idempotent insert and duplicate-notification suppression. |
| `api/inspections/routes.py` | Report/cycle/timestamp parsing, conflicts and accepted-retry notification bypass. |
| `api/inspections/service.py` | Assignment cycle and dispatch/submission/receipt fields, reassignment resets, locked retry reconciliation and decimal GPS accuracy comparison. |
| `api/models/inspection_lifecycle_events.py` | Explicit UTC lifecycle timestamps. |
| `api/registry/service.py` | Two quota-reserved Geocoding functions; failure logging does not include request URLs/keys. |
| `api/utils/barangay_scope.py` | Pure unbuffered geometry validation, extracted without experimental modules. |

`config.py`, `api/auth/sessions.py`, `app.py`, Docker/dependencies, notification
implementations, detection functions and boundary data are unchanged from the
base. Session inactivity remains ten minutes; JWT lifetime remains twelve hours.
UUIDs are normalized to lowercase before using the binary-collated unique key.
Successful first submissions retain existing status codes and notification paths.

### Migrations

1. `migrations/20261014_01_yellow_flag_idempotency.sql`
2. `migrations/20261014_02_inspection_submission_timestamps.sql`

The existing reviewed scripts were included unchanged. The operator has confirmed
that the three added columns are missing. Definitions match the known schema:

- Existing `geospatial_logs.reportedByUserID` is an integer reporter identifier.
  Add nullable `clientSubmissionID CHAR(36) CHARACTER SET ascii COLLATE ascii_bin`,
  then unique `uq_geo_reporter_submission(reportedByUserID, clientSubmissionID)`.
- Existing `inspection_reports.irTimestamp` is dispatch time. Add nullable
  `submittedAt` and `submissionReceivedAt`, both `DATETIME(6) DEFAULT NULL`.
- Retry accuracy comparison matches existing `verifiedAccuracy DECIMAL(8,2)`;
  no GPS column/type alteration is included.

These are run-once DDL, not an automatic startup migration. If schema state changes
or a previous run partially succeeds, stop and approve only the missing operations.
Do not infer historical submission timestamps or backfill them from dispatch time.

### Regression support

- `tests/test_auth_inactivity.py` — update the explicit-activity call-site check
  for the new mobile-only endpoint; verify ten-minute heartbeat expiry behavior.
- `tests/test_backend_release_contract.py`.
- `tests/test_barangay_scope.py`.
- `tests/test_inspection_submission_idempotency.py`.
- `tests/test_yellow_flag_address_search.py`.
- `tests/test_yellow_flag_idempotency.py`.
- `tests/test_yellow_flag_validation.py`.
- `scripts/run_backend_release_tests.py`.

This document is the only additional release file. No QA runtime, test database
setup, Nearby pilot, web or Flutter changes are part of this release.

## Validation

From `revela_backend`, using the existing Python environment:

```powershell
& 'C:\REVELA-prod\revela_backend\.venv\Scripts\python.exe' -B scripts/run_backend_release_tests.py
```

Result: **115 tests passed; zero offline guard violations**. The runner also uses
the unchanged baseline auth-session tests. HTTP/socket access, real MySQL
connections, dotenv loading, production app factory and scheduler startup are
blocked. Flask requests are handled in-process with mocks/in-memory session stores.
No dependency installation is needed. Syntax checks use `compile()` without
writing bytecode; `git diff --check` is clean.

These checks establish offline contracts, not live MySQL concurrency, migration
application, delivery guarantees, Google configuration or hosted compatibility.

## Remaining boundary and Android constraints

The six discrepancies remain: **Barangay II-A (Pob.), Calingatan, District I
(Pob.), District IV (Pob.), Loob and Manggahan**. Their barangay polygons extend
outside the existing buffered municipal polygon. The release neither enlarges
the existing tolerance nor changes either boundary dataset. The barangay predicate
adds no buffer, preserves holes, and fails closed on missing/ambiguous geometry.
A regression explicitly verifies that disagreement still rejects the submission.

Broad boundary testing requires a separately approved authoritative, versioned
municipal/barangay geometry policy shared with the client. Do not silently drop
the municipality check or change Nearby behavior. A separately approved narrow
test may use coordinates inside both current boundaries.

Old Android clients without `assignmentCycleID` cannot submit reassigned reports;
they receive 409. Use the updated production APK for the test fleet. Legacy first
assignments and UUID-less Yellow submissions retain their supported paths, but
UUID-less submissions do not gain deduplication.

Build the updated Flutter work, **not this worktree's baseline Flutter copy**, only
after separate build approval:

```powershell
flutter build apk --flavor production --release --no-pub --dart-define=API_BASE=https://api.revelasys.site
```

Verify signing identity, Maps package/SHA restrictions, Firebase configuration,
effective endpoint and empty production draft queues. Keep `.qa` isolated.

## Proposed Railway procedure — approval required

1. Approve this exact diff and its test/boundary limitations. Record the current
   successful Railway deployment ID/SHA and selectable rollback artifact. Confirm
   protected-data/evidence backup and evidence-volume readiness from the completed
   preflight; do not alter variables or service settings as part of this release.
2. Keep participating apps/automatic sync and deployment-triggering publication
   paused. A test-data reset is a separate approval and is not included here.
3. With explicit migration approval, recheck schema state in the intended database,
   apply migration 01 (column, then unique index), then migration 02 (two columns).
   Verify definitions/indexes before releasing code. Do not start Flask to migrate.
4. Obtain explicit commit/publication and deployment approval. Commit only the
   listed release files from this isolated worktree; do not cherry-pick the WIP
   commit. Publish through the backend service's existing approved deployment
   source. If that source is `main`, use a backend-only PR/approved merge, after
   migrations are ready. Never change the Railway branch or variables implicitly.
5. Deploy the reviewed resulting SHA through the existing service. Expected root
   is `revela_backend`; repository startup is Gunicorn, one worker, sixteen
   threads, 120-second timeout, bound to `$PORT`. Preserve this configuration;
   stop for separate approval if the actual setup requires changes.
6. Account for unchanged startup effects: permit expiry at startup +10 seconds
   and midnight can mutate reference data and notify admins; 03:00 coordinate
   refresh can consume quota, call Google and update pins. Times are host-local,
   and workers/replicas or rolling overlap can duplicate scheduling. Deployment
   approval must cover these effects or provide separately approved controls.
7. Check the successful deployment SHA, startup logs and `/api/health`. Health is
   process liveness only. Authenticated/API/database-writing checks and Google
   features require a separate live-test approval, even when the database is
   disposable team data. First submissions can generate notifications/emails;
   assignments can send FCM pushes.
8. On failure, stop test clients/auto-sync and redeploy the recorded previous
   successful artifact through Railway's deployment history. Retain the additive
   columns/index. Old code lacks new retry guarantees. Code rollback does not undo
   submissions, reset operations, migrations, files or already delivered messages;
   any database/file restoration requires its own approval.

Stop after preparation and validation. No step above is authorized by this file.
