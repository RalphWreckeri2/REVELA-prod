# Registry / inspection fix batch

## Read-only Follow-up finding

The Inspection details Follow-up action opens the assignment dialog and calls
`POST /api/inspections/assign` → `assign_inspection`. It reuses the latest report,
sets Reassigned, clears its submitted evidence/result, and records a lifecycle
event. It does not increment warnings. Mobile receives `currentNoticeLevel`
from `geospatial_logs.noticeLevel`: 0 offers 1st notice, 1 offers 2nd, 2 offers
3rd. Clear Warning already resets both registry warningLevel and pin noticeLevel.
The Green assignment block is preserved.

## Required pre-deployment order

Before deploying the color change, an operator must run the existing backfill
against the intended deployment database in this order:

1. **Dry-run:** `python scripts/backfill_enforcement_ladder.py`
2. **Review results:** reconcile proposed warning levels and locks with verified
   inspections and enforcement events, including warnings deliberately cleared.
   Resolve ambiguous/unmatched Orange and Black rows before proceeding. The
   script infers history; its proposal is not proof that a warning is current.
3. **Apply the reviewed plan:** `python scripts/backfill_enforcement_ladder.py --apply`
4. **Dry-run again:** `python scripts/backfill_enforcement_ladder.py`; review any
   remaining proposals before deploying the new color reader.

This batch does not execute a production backfill or deploy anything. The
production columns already exist; there are no schema changes or migrations.

## Verification baseline

Before implementation: backend 858 passed, 4 failed, 28 skipped (548 passing
subtests); frontend `npm run verify` passed. Three backend failures are the
previously known grid/SSE failures. The fourth, the CORS/login integration test,
is an **accepted environment-related verification gap**, only while its cause
is MySQL 1045 access denied for root@localhost producing HTTP 500. It is not a
passing test. A different cause must be treated as unexpected.

The runtime database target was checked without displaying credentials and is
local loopback. Credentials were not changed. New database workflow tests use
SQLite in memory; the pre-existing disposable-MySQL audit remains opt-in.

## Part 1 verification

After the color/Revoked changes and fixture repairs: **868 passed, 4 accepted
failures, 28 skipped; 554 passing subtests**. Frontend `npm run verify` passed.
The CORS failure still has the accepted local MySQL 1045 cause.

The SQLite fixture already had warningLevel and blackLocked. Its expiry error
was an alias-scope bug in the test adapter; UPDATE FROM preserves the registry
alias in SET without replacing the production color expression. Clear Warning
was verified through real writes and the subsequent inspector-task query:
Pending returns to Yellow and mobile receives currentNoticeLevel=0. Part 6
therefore needs no implementation.

### Existing-test changes and reasons

- `tests/test_enforcement_ladder_colors.py`: replace the Python/SQL expectations
  that Orange beats Revoked, update the historical comparison, and add cleared
  warning / Revoked regressions using the real color builder.
- `tests/test_black_lock_guard.py`: add migrated/unmigrated Revoked coverage.
- `tests/test_black_guard_wiring.py` and `tests/test_verify_ladder_writes.py`:
  teach the cursor fixtures the expanded lock/status query and return shape.
- `tests/test_sync_ladder_protection.py`: extend the preload fixture with Revoked
  IDs and verify their protection without ladder columns.
- `tests/test_yellow_flag_idempotency.py`: retry call count 2→3 and legacy insert
  1→2, because per-test source-cache resets expose the source-column probe.
  Assert the added call really is the probe; retain insert/notification checks.
- `tests/test_yellow_flag_validation.py`: valid offsite insert call count 2→3
  for that same probe, explicitly asserted.
- `tests/test_black_dispatch_unlock.py`: replace the obsolete missing-columns
  bypass expectation with a typed refusal and zero writes for Revoked.
- `tests/test_registry_snap.py`: replace the unconstrained lock fixture and
  mocked color sync with a real in-memory workflow; retain the two cached rows
  in actual businessID order. Assert coordinates, color and one color write.
  The API-error test now asserts no SQL writes/commit instead of mocking sync.

For the registry-only Orange failure, the test was correct: impossible Orange
requests should be rejected before a lock lookup. Production validation order
was fixed; that test's assertions were not changed.

## Part 2 verification

Admin escalation now resolves the current effective color, locks the registry
row, writes Revoked + blackLocked/At/By, updates the pin and records black_locked
in one transaction. Red/Yellow/Orange work at any warning level without an
inspection. Black, Green, Purple and non-admin callers are refused with typed
errors. Missing ladder columns give a clear conflict. Unregistered pins only
change their pin; virtual registry flags get a real registry lock.

The Map's registry-only branch had a second precedence copy. It now calls the
shared CASE builder. Registry readers also use that shared row rule when there
is no physical pin, so a virtual Black business is Black on both screens.
Verified Black inspection behavior was not changed.

New `tests/test_black_escalation.py` executes escalation, actual Map/Registry
payload queries, audit rollback and later sync against the isolated database.
The existing SQL adapter gained LATERAL / FOR UPDATE syntax substitutions for
these fixtures; production CASE arms and color sync are not mocked. No existing
test assertion was changed in this part.

Full backend: **888 passed, 4 accepted failures, 28 skipped; 554 passing
subtests**. Frontend `npm run verify` passed. The CORS verification gap remains
the same local MySQL 1045 error.

## Part 3 verification

Follow-up now reads a small tested UI policy using the current flag color,
registry status/lock and dispatch grant. It is not restricted by warning stage
or an old Orange result. The existing Green assignment block remains. Verified
Black reports hide both Follow-up and the equivalent reassign action without
a grant. The server returns a typed Black assignment conflict as HTTP 409.

The Inspection payload now carries the shared effective color and ladder state.
The grant lookup uses the same registry match as the color builder, including
legacy pins without businessID. New backend tests cover linked/legacy grants,
payload shape, unchanged report data on refusal, other inspectable colors and
typed HTTP mapping. The three frontend Follow-up tests were appended to
`src/components/dispatchEligibility.test.js`; no old assertion was changed.

Full backend: **900 passed, 4 accepted failures, 28 skipped; 554 passing
subtests**. Frontend `npm run verify` passed with 146 policy tests.

## Part 4 verification

A shared deletion guard refuses locked or Revoked businesses unless the role
is exactly `SUPER_ADMIN`. Registry deletion and the Map virtual-business delete
both map its typed error to 403. Ordinary pin deletion remains isolated from
business deletion. Map payloads now expose blackDispatchUnlocked in both UNION
branches, or 0 when the column is absent. The existing Map normalizer already
preserves the field via its API-record spread.

New `tests/test_black_delete_and_map_payload.py` covers exact roles, both HTTP
routes, unmigrated Revoked protection, and actual JSON-shaped Map payloads.
The existing virtual deletion test in `tests/test_delete_isolation.py` now
uses real in-memory data and additionally checks that the row disappeared;
its original exact-delete assertions are retained. A payload/dispatch test
was appended to `src/components/dispatchEligibility.test.js`.

Full backend: **924 passed, 4 accepted failures, 28 skipped; 554 passing
subtests**. Frontend `npm run verify` passed with 147 policy tests.

## Part 5 verification

Verified inspection details now show Clear Warning through registryLadderPolicy
for an admin, with a registry business, warningLevel > 0, a non-Black current
state and an explicit zero non-Verified-inspection count. That count is computed
on the backend across all matching pins, not just the loaded reports. The
existing clear-warning route is reused. After success the open detail is
refetched and a registry update refreshes the Map; the server also publishes
the update for other open clients.

Clear Warning and the existing single-use unlock now consistently recognize
Revoked without a lock bit. Their routes map returned typed conflicts to 409
as well as raised ones (the old routes only handled the latter). The unlock
does not alter permit status or the lock bit. Verified Black was not changed.

Existing tests changed:
- `src/components/registryLadderPolicy.test.js`: replace the old assertion that
  Revoked is not Black; add Inspection eligibility, ordered refresh, failed-clear
  and string-zero coverage.
- `tests/test_black_dispatch_unlock.py::test_a_business_that_is_not_black_is_refused`:
  make the fixture truly non-Black (Active + lock=0 instead of Revoked + lock=0).
  Every refusal assertion is retained.

New `tests/test_inspection_clear_warning.py` executes the actual Inspection
payload, clear route, linked/legacy open-inspection checks and all six verified
results from Pending/Expired/Closed. Pending returns to Yellow after clearing,
applicationStatus stays Pending, and the historical report is preserved.

Full backend: **955 passed, 4 accepted failures, 28 skipped; 554 passing
subtests**. Frontend `npm run verify` passed with 151 policy tests.

## Part 7 and final verification

The Map's virtual registry branch was still emitting `registry_only`, while
the frontend recognizes `registry`. It now emits the canonical SOURCE_REGISTRY
value and displays **Official BPLO Registry**. New real-payload backend coverage
checks this with and without the source column; the frontend source test was
extended without changing any previous label or unknown-source assertion.

Final full backend: **957 passed, 4 accepted failures, 28 skipped; 554 passing
subtests**. Final frontend `npm run verify`: lint, context checks, **152 tests**
and production build passed. The same four failures remain; none disappeared.
The CORS failure remains the accepted environment-related verification gap
(local MySQL 1045), not a pass. Vite retains its pre-existing large-chunk warning.

No new skips or expected-failure marks were added. Probe caches are reset for
every backend test. The new workflows execute the real color builders and
color sync. SQLite substitutes unsupported MySQL syntax, so these checks do
not replace live MySQL concurrency/deployment verification or a browser smoke
test. No production backfill or deployment was executed.

## Line-level existing-test ledger

Line numbers refer to the final files. Backend paths are relative to
`revela_backend`; frontend paths are relative to `revela_web`.

| Existing file and lines | Change and reason |
| --- | --- |
| `tests/test_enforcement_ladder_colors.py:150,183–187,406–427,448–455` | Expected-color helper and three tests now require Black to outrank Orange, including the historical comparison. |
| `tests/test_enforcement_ladder_colors.py:457–473` | Add real-builder Pending/clear/history and Revoked regressions. |
| `tests/test_black_guard_wiring.py:59` | Cursor fixture recognizes the expanded lock/status read; existing test assertions retained. |
| `tests/test_verify_ladder_writes.py:55,103–104` | Cursor fixture recognizes the expanded read and includes applicationStatus; existing assertions retained. |
| `tests/test_black_lock_guard.py:63–72` | Add Revoked guard coverage with and without ladder columns; old tests retained. |
| `tests/test_sync_ladder_protection.py:39–63,98–105` | Extend preload fixture and add unmigrated Revoked protection coverage; old assertions retained. |
| `tests/test_yellow_flag_idempotency.py:44–55` | Retry DB count 2→3 for the source-column probe; explicitly check that probe and retain duplicate-key/notification assertions. |
| `tests/test_yellow_flag_idempotency.py:75–83` | Legacy DB count 1→2 for that probe; retain single-insert/notification checks. |
| `tests/test_yellow_flag_validation.py:65–78` | Valid offsite DB count 2→3 for that probe, explicitly asserted. |
| `tests/test_black_dispatch_unlock.py:382–389` | Replace obsolete unmigrated guard bypass with typed Revoked refusal and zero writes. |
| `tests/test_black_dispatch_unlock.py:87–91` | Non-Black refusal fixture is now Active + lock=0; all refusal assertions retained. |
| `tests/test_registry_snap.py:15–105` | Real in-memory rows and real sync/color execution; assert persisted coordinates/color and one color write. Cached fixture IDs now follow actual SQL order. |
| `tests/test_registry_snap.py:107–158` | Remove sync mock; API failure must leave only the SELECT, no writes and no commit. |
| `tests/test_delete_isolation.py:226–240` | Real virtual-business deletion instead of an unconstrained mock; retain exact-delete assertions and additionally verify row removal. |
| `src/components/dispatchEligibility.test.js:92–127` | Append three Follow-up policy tests and one real-shape Map grant test; no old assertion changed. |
| `src/components/registryLadderPolicy.test.js:83–88` | Replace the obsolete Revoked-is-not-Black expectation with the agreed Black rule, Clear Warning refusal and SUPER_ADMIN unlock eligibility. |
| `src/components/registryLadderPolicy.test.js:242–276` | Append Inspection eligibility, ordered refresh, failure and string-zero tests. |
| `src/components/flagSource.test.js:91–99` | Append registry-only payload label/filter coverage; old unknown-source assertions retained. |

New test/support files: `tests/conftest.py`, `tests/registry_sqlite.py`,
`tests/test_registry_color_workflows.py`, `tests/test_black_escalation.py`,
`tests/test_follow_up_black.py`, `tests/test_black_delete_and_map_payload.py`,
`tests/test_inspection_clear_warning.py`, `tests/test_registry_only_source_label.py`.
