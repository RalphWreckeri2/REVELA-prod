# Mobile/session integration — prepared, not published

- Branch: `integrate/mobile-session-fixes-20261015`.
- Worktree: `C:\Users\Mateo\AppData\Local\Temp\opencode\revela-mobile-session-integration-20261015`.
- Base: `main` at `78c6a17031eb3abcb6e58060089f0b5707f7a3ef`, including `56cada5`.
- Source: `wip/laptop-transfer-20261014` at `ab79e99`, including its current
  uncommitted mobile changes and untracked task-card timestamp test.
- The original WIP was read only. No commit, merge, push, build, publication or
  deployment is included in this preparation.

## Integrated scope

- Backend: selective mobile login-reclaim/configuration hunks and matching tests.
  An inactive mobile slot is reclaimable after 60 seconds; protected API requests
  retain the 10-minute inactivity window and the JWT retains its 12-hour ceiling.
  Foreground mobile heartbeats protect a live session. Existing web sessions keep
  their normal inactivity policy. Recovery is timeout based, not immediate OS
  force-close detection; activity tracking retains the existing single-worker
  constraint.
- Flutter: validated session restoration, explicit offline biometric/PIN access,
  non-destructive ordinary session invalidation, genuine activity reporting,
  account/cycle-scoped inspection drafts, interrupted/retry synchronization,
  evidence checkpoints and canonical timestamp reconciliation, including NULL.
- Inspection UI: current/history separation, assignment identity, GPS status and
  separate Manila dispatch/submission timestamps. The latest WIP timestamp fixes
  and tests are included.
- Yellow Flags: account-owned UUID retry queue, address/reverse lookup contracts,
  local barangay-name resolution, strict polygon/hole validation and overlapping
  marker selection with distinguishable report/cycle references.
- Android: existing Street View platform view, build-identity channel, production
  Maps/signing checks, isolated QA client configuration and matching manifests.
- Mobile policies: native screens, bundled documents and asset registration.

The main backend hotfix, models, routes, geometry utility, UUID normalization,
JSON validation, safe logging, migrations and release regressions are retained.
Web navigation/calendar/settings changes are untouched. The map has one pair of
zoom controls. Flutter dependency constraints, lockfile and app version are
unchanged; the native Maps dependency supports the imported Street View code.

## Excluded

Experimental Nearby modules/migration/tests, backend QA infrastructure and SQL
fixtures, walking-direction provider/imports/UI, unused pin picker/URL helper,
web/PDF changes, iOS-only changes and dependency/version churn.

## Offline validation

- Flutter 3.41.9 / Dart 3.11.5: `flutter pub get --offline --enforce-lockfile`.
- From `revela_mobile`: `flutter test --no-pub --reporter expanded` — 137 passed.
  `test/flutter_test_config.dart` forbids live Dart HTTP; transports are mocked.
  Tests use temporary local SQLite fixtures, never production databases.
- Targeted `flutter analyze --no-pub` across all 44 changed/new Dart files — no
  issues. New integration tests cover Yellow retries/account isolation and
  static native-channel, exclusion and duplicate-zoom wiring.
- From `revela_backend`, using the existing Python environment:
  `python -B scripts/run_backend_release_tests.py` — 138 passed, zero guard
  violations. HTTP/socket/MySQL connections, dotenv loading, production app
  startup and scheduler startup are blocked. All previous hotfix suites remain
  included; session/restart/heartbeat/reclaim tests are added.
- Six changed Python files pass in-memory syntax compilation without imports or
  bytecode writes. Diff/format/preservation checks accompany the preparation.

## Remaining limits — separate approval required

- No APK/native build or device/Google validation was performed. Native channel
  checks are static, not proof of Android build/runtime or imagery availability.
- Walking directions remain excluded and unfinished.
- Municipal/barangay geometry disagreements remain unchanged for Barangay II-A
  (Pob.), Calingatan, District I (Pob.), District IV (Pob.), Loob and Manggahan.
  Server municipality enforcement and strict barangay validation remain intact.
- Committed SQL does not establish applied schema. The existing Yellow UUID
  column/unique index and inspection submission timestamp columns must be
  verified separately before any deployment/live synchronization. No database
  inspection, migration, live submission, Railway change or Google request was
  made.

Await approval before committing, publishing or integrating this preparation
into `main`.
