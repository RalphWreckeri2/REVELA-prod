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
